# -*- coding: utf-8 -*-
"""
JackettIndexer Plugin for MoviePilot V3

V3 adapted version - uses stable SDK imports, removes deprecated paths.
Plugin unchanged in functionality, only import paths and SDK usage updated.

Version: 9.9.9
Author: Claude (Papa-patch v9.9.9)
"""

import re
import traceback
import copy
import xml.dom.minidom
from typing import List, Dict, Optional, Any, Tuple, Type

from apscheduler.triggers.cron import CronTrigger

from app.plugins import _PluginBase
from app.schemas.types import MediaType, EventType
from app.sdk.logging import logger
from app.sdk.network import AsyncRequestUtils
from app.sdk.events import Event, eventmanager

from .agenttool import SearchTorrentsTool, ListIndexersTool

# 旧版兼容导入（V3 兼容层仍支持）
from app.utils.dom import DomUtils
from app.utils.string import StringUtils


class JackettIndexer(_PluginBase):
    """
    Jackett Indexer Plugin (V3 Adapted)

    Provides torrent search functionality through Jackett Torznab API.
    Registers all configured Jackett indexers as MoviePilot sites.
    """

    # Plugin metadata
    plugin_name = "Jackett索引器"
    plugin_desc = "集成Jackett索引器搜索，支持Torznab协议多站点搜索。支持全部站点类型（公开/半公开/私有）。"
    plugin_icon = "Jackett_A.png"
    plugin_version = "9.9.9"
    plugin_author = "Summer&Openclaw"
    author_url = "https://github.com"
    plugin_config_prefix = "jackettindexer_"
    plugin_order = 15
    auth_level = 2

    # Private attributes
    _enabled: bool = False
    _host: str = ""
    _api_key: str = ""
    _proxy: bool = False
    _cron: str = "0 0 */12 * *"
    _onlyonce: bool = False
    _indexers: List[Dict[str, Any]] = []
    _scheduler = None
    _last_update = None
    _original_search_all = None
    _original_async_search_all = None

    # Domain identifier
    JACKETT_DOMAIN = "jackett_indexer.claude"

    def init_plugin(self, config: dict | None = None) -> None:
        """读取配置，建立本次运行状态。"""
        logger.info(f"【{self.plugin_name}】开始初始化插件")

        self.stop_service()

        if not config:
            return

        self._enabled = config.get("enabled", False)
        self._host = config.get("host", "").rstrip("/")
        self._api_key = config.get("api_key", "")
        self._proxy = config.get("proxy", False)
        self._cron = config.get("cron", "0 0 */12 * *")
        self._onlyonce = config.get("onlyonce", False)

        if not self._enabled:
            logger.info(f"【{self.plugin_name}】插件未启用")
            return

        if not self._host or not self._api_key:
            logger.error(f"【{self.plugin_name}】配置错误：缺少服务器地址或API密钥")
            return

        if not self._host.startswith(("http://", "https://")):
            logger.error(f"【{self.plugin_name}】配置错误：服务器地址必须以 http:// 或 https:// 开头")
            return

        # 启动定时同步
        if self._cron:
            from apscheduler.schedulers.background import BackgroundScheduler
            try:
                self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
                self._scheduler.add_job(
                    func=self._sync_indexers,
                    trigger=CronTrigger.from_crontab(self._cron),
                    name=f"{self.plugin_name}定时同步"
                )
                self._scheduler.start()
                logger.info(f"【{self.plugin_name}】定时同步任务已启动，周期：{self._cron}")
            except Exception as e:
                logger.error(f"【{self.plugin_name}】定时任务创建失败：{str(e)}")

        if self._onlyonce:
            self._onlyonce = False
            self.update_config({**config, "onlyonce": False})
            self._sync_indexers()

        # 获取并注册索引器
        self._fetch_and_build_indexers()

        # 注册到站点管理
        try:
            from app.helper.sites import SitesHelper
            sites_helper = SitesHelper()
            for indexer in self._indexers:
                domain = indexer.get("domain", "")
                sites_helper.add_indexer(domain, indexer)
        except ImportError:
            logger.warning(f"【{self.plugin_name}】无法导入 SitesHelper，站点注册跳过")

        logger.info(f"【{self.plugin_name}】插件初始化完成，共注册 {len(self._indexers)} 个索引器")

        # 应用搜索链补丁
        self._apply_search_patch()

    def _fetch_and_build_indexers(self) -> bool:
        """从 Jackett 获取索引器并构建索引器字典。"""
        try:
            indexers = self._get_indexers_from_jackett()
            if not indexers:
                logger.warning(f"【{self.plugin_name}】未获取到索引器列表")
                return False

            self._indexers = []
            xxx_filtered_count = 0

            for indexer_data in indexers:
                try:
                    indexer_dict, is_xxx_only = self._build_indexer_dict(indexer_data)
                    if is_xxx_only:
                        xxx_filtered_count += 1
                        continue
                    self._indexers.append(indexer_dict)
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】构建索引器失败：{str(e)}")
                    continue

            logger.info(f"【{self.plugin_name}】成功获取 {len(self._indexers)} 个索引器，XXX 专属站点 {xxx_filtered_count} 个被过滤")
            return True

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取索引器异常：{str(e)}\n{traceback.format_exc()}")
            return False

    def _sync_indexers(self) -> bool:
        """定时同步索引器。"""
        try:
            if not self._fetch_and_build_indexers():
                return False

            try:
                from app.helper.sites import SitesHelper
                sites_helper = SitesHelper()
                registered_count = 0
                for indexer in self._indexers:
                    domain = indexer.get("domain", "")
                    site_info = sites_helper.get_indexer(domain)
                    if not site_info:
                        sites_helper.add_indexer(domain, copy.deepcopy(indexer))
                        registered_count += 1
            except ImportError:
                registered_count = 0

            from datetime import datetime
            self._last_update = datetime.now()
            logger.info(f"【{self.plugin_name}】索引器同步完成，总计 {len(self._indexers)} 个，新增 {registered_count} 个")
            return True

        except Exception as e:
            logger.error(f"【{self.plugin_name}】同步索引器异常：{str(e)}\n{traceback.format_exc()}")
            return False

    def _get_indexers_from_jackett(self) -> List[Dict[str, Any]]:
        """从 Jackett API 获取索引器列表。"""
        try:
            from urllib.parse import urlencode
            url = f"{self._host}/api/v2.0/indexers/all/results/torznab/api"
            params = {"apikey": self._api_key, "t": "indexers", "configured": "true"}

            # V3: 使用 AsyncRequestUtils 但同步调用 .result()
            response = AsyncRequestUtils(proxies=self._proxy).get_res(url=url, params=params, timeout=30)

            if not response:
                logger.error(f"【{self.plugin_name}】API请求失败：无响应")
                return []

            if response.status_code != 200:
                logger.error(f"【{self.plugin_name}】API请求失败：HTTP {response.status_code}")
                return []

            return self._parse_indexers_xml(response.text)

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取索引器列表异常：{str(e)}\n{traceback.format_exc()}")
            return []

    def _parse_indexers_xml(self, xml_content: str) -> List[Dict[str, Any]]:
        """解析 Jackett 索引器 XML 响应。"""
        try:
            dom_tree = xml.dom.minidom.parseString(xml_content)
            root_node = dom_tree.documentElement

            if root_node.tagName == "error":
                logger.error(f"【{self.plugin_name}】Torznab错误：{root_node.getAttribute('description')}")
                return []

            indexer_elements = root_node.getElementsByTagName("indexer")
            indexers = []

            for elem in indexer_elements:
                try:
                    indexer = {
                        "id": elem.getAttribute("id"),
                        "title": DomUtils.tag_value(elem, "title", default=""),
                        "type": elem.getAttribute("type"),
                        "language": elem.getAttribute("language") or "en-US",
                    }
                    if indexer["id"] and indexer["title"]:
                        indexers.append(indexer)
                except Exception:
                    continue

            return indexers

        except Exception as e:
            logger.error(f"【{self.plugin_name}】解析XML失败：{str(e)}")
            return []

    def _get_indexer_categories(self, indexer_name: str) -> Tuple[Optional[Dict[str, List[Dict[str, Any]]]], bool]:
        """获取索引器分类信息。"""
        try:
            url = f"{self._host}/api/v2.0/indexers/{indexer_name}/results/torznab/api"
            params = {"apikey": self._api_key, "t": "caps"}

            response = AsyncRequestUtils(proxies=self._proxy).get_res(url=url, params=params, timeout=15)

            if not response or response.status_code != 200:
                return None, False

            dom_tree = xml.dom.minidom.parseString(response.text)
            root_node = dom_tree.documentElement
            categories = root_node.getElementsByTagName("category")

            if not categories:
                return None, False

            category_map = {"movie": [], "tv": []}
            top_level_categories = set()

            for cat in categories:
                cat_id = cat.getAttribute("id")
                cat_name = cat.getAttribute("name")
                if not cat_id:
                    continue
                try:
                    cat_num = int(cat_id)
                    top_level = (cat_num // 1000) * 1000
                    top_level_categories.add(top_level)
                    cat_entry = {"id": int(cat_id), "cat": cat_name or f"Category {cat_id}", "desc": cat_name or f"Category {cat_id}"}
                    if top_level == 2000 and not any(c["id"] == cat_entry["id"] for c in category_map["movie"]):
                        category_map["movie"].append(cat_entry)
                    elif top_level == 5000 and not any(c["id"] == cat_entry["id"] for c in category_map["tv"]):
                        category_map["tv"].append(cat_entry)
                except (ValueError, TypeError):
                    continue

            has_xxx = 6000 in top_level_categories
            has_other = any(cat in top_level_categories for cat in [2000, 5000, 3000, 4000, 1000, 7000, 8000])
            is_xxx_only = has_xxx and not has_other

            if is_xxx_only:
                return None, True

            result = {}
            if category_map["movie"]:
                result["movie"] = category_map["movie"]
            if category_map["tv"]:
                result["tv"] = category_map["tv"]

            return (result if result else None), False

        except Exception:
            return None, False

    def _build_indexer_dict(self, indexer: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        """从 Jackett 数据构建 MoviePilot 索引器字典。"""
        indexer_name = indexer.get("id", "")
        indexer_title = indexer.get("title", indexer_name)
        indexer_type = indexer.get("type", "")
        domain = self.JACKETT_DOMAIN.replace(self.plugin_author.lower(), str(indexer_name))
        is_public = indexer_type.lower() == "public" if indexer_type else False

        category, is_xxx_only = self._get_indexer_categories(indexer_name)
        rss_url = self._build_rss_url(indexer_name, category)

        indexer_dict = {
            "id": f"{self.plugin_name}-{indexer_title}",
            "name": f"{self.plugin_name}-{indexer_title}",
            "url": f"{self._host.rstrip('/')}/api/v2.0/indexers/{indexer_name}/results/torznab/",
            "domain": domain,
            "public": is_public,
            "privacy": indexer_type if indexer_type else "private",
            "proxy": False,
            "rss": rss_url,
        }
        if category:
            indexer_dict["category"] = category

        return indexer_dict, is_xxx_only

    def _build_rss_url(self, indexer_name: str, category: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> str:
        """构建 Jackett Torznab RSS URL。"""
        from urllib.parse import urlencode
        cat_ids = []
        if category:
            if category.get("movie"):
                cat_ids.append("2000")
            if category.get("tv"):
                cat_ids.append("5000")
        if not cat_ids:
            cat_ids = ["2000", "5000"]

        params = [("apikey", self._api_key), ("t", "search"), ("q", ""), ("cat", ",".join(cat_ids)), ("limit", 30)]
        return f"{self._host.rstrip('/')}/api/v2.0/indexers/{indexer_name}/results/torznab/api?{urlencode(params)}"

    # ---------------------------------------------------------------------------
    # 搜索链补丁：中文关键词回退英文标题搜索
    # ---------------------------------------------------------------------------

    def _apply_search_patch(self):
        """向 SearchChain 注入中文关键词英文回退补丁。"""
        try:
            from app.chain.search import SearchChain
        except ImportError:
            logger.warning(f"【{self.plugin_name}】无法导入 SearchChain，跳过搜索链补丁")
            return

        marker = f"_en_fallback_{self.plugin_config_prefix}"
        if getattr(SearchChain._SearchChain__search_all_sites, marker, False):
            return

        plugin_ref = self
        prev_sync = SearchChain._SearchChain__search_all_sites
        prev_async = SearchChain._SearchChain__async_search_all_sites
        self._original_search_all = prev_sync
        self._original_async_search_all = prev_async

        def patched_sync(chain_self, keyword, mediainfo=None, sites=None, page=0, area="title"):
            results = list(prev_sync(chain_self, keyword, mediainfo, sites, page, area) or [])
            if not plugin_ref._enabled or not plugin_ref._indexers:
                return results
            if not mediainfo or not keyword or area == "imdbid":
                return results
            if not StringUtils.is_chinese(keyword):
                return results
            en_keyword = plugin_ref._get_en_keyword(mediainfo)
            if not en_keyword:
                return results
            logger.info(f"【{plugin_ref.plugin_name}】检测到中文关键词，补充搜索英文标题：{en_keyword}")
            extra = plugin_ref._extra_search_sync(chain_self, en_keyword, mediainfo, sites, page)
            if extra:
                results.extend(extra)
            return results

        async def patched_async(chain_self, keyword, mediainfo=None, sites=None, page=0, area="title"):
            results = list(await prev_async(chain_self, keyword, mediainfo, sites, page, area) or [])
            if not plugin_ref._enabled or not plugin_ref._indexers:
                return results
            if not mediainfo or not keyword or area == "imdbid":
                return results
            if not StringUtils.is_chinese(keyword):
                return results
            en_keyword = plugin_ref._get_en_keyword(mediainfo)
            if not en_keyword:
                return results
            logger.info(f"【{plugin_ref.plugin_name}】检测到中文关键词，补充异步搜索英文标题：{en_keyword}")
            extra = await plugin_ref._extra_search_async(chain_self, en_keyword, mediainfo, sites, page)
            if extra:
                results.extend(extra)
            return results

        setattr(patched_sync, marker, True)
        setattr(patched_async, marker, True)
        SearchChain._SearchChain__search_all_sites = patched_sync
        SearchChain._SearchChain__async_search_all_sites = patched_async
        logger.info(f"【{self.plugin_name}】搜索链补丁注入成功")

    def _remove_search_patch(self):
        """恢复被补丁替换的 SearchChain 方法。"""
        try:
            from app.chain.search import SearchChain
            marker = f"_en_fallback_{self.plugin_config_prefix}"
            if (self._original_search_all and
                    getattr(SearchChain._SearchChain__search_all_sites, marker, False)):
                SearchChain._SearchChain__search_all_sites = self._original_search_all
                self._original_search_all = None
            if (self._original_async_search_all and
                    getattr(SearchChain._SearchChain__async_search_all_sites, marker, False)):
                SearchChain._SearchChain__async_search_all_sites = self._original_async_search_all
                self._original_async_search_all = None
        except Exception:
            pass

    @staticmethod
    def _get_en_keyword(mediainfo) -> Optional[str]:
        """从 mediainfo 提取英文/非中文标题作为回退关键词。"""
        if mediainfo.en_title:
            return mediainfo.en_title
        if mediainfo.original_title and not StringUtils.is_chinese(mediainfo.original_title):
            return mediainfo.original_title
        return None

    def _extra_search_sync(self, chain_self, en_keyword: str, mediainfo, sites, page: int) -> list:
        """同步补充搜索。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app.db.systemconfig_oper import SystemConfigOper
        from app.schemas.types import SystemConfigKey

        enabled_ids = sites or SystemConfigOper().get(SystemConfigKey.IndexerSites) or []
        indexers = [idx for idx in list(self._indexers) if not enabled_ids or idx.get("id") in enabled_ids]
        if not indexers:
            return []

        results = []
        with ThreadPoolExecutor(max_workers=len(indexers)) as executor:
            tasks = [executor.submit(self.search_torrents, site=s, keyword=en_keyword,
                                      mtype=mediainfo.type if mediainfo else None, page=page) for s in indexers]
            for future in as_completed(tasks):
                try:
                    result = future.result()
                    if result:
                        results.extend(result)
                except Exception:
                    pass
        return results

    async def _extra_search_async(self, chain_self, en_keyword: str, mediainfo, sites, page: int) -> list:
        """异步补充搜索。"""
        import asyncio
        from app.db.systemconfig_oper import SystemConfigOper
        from app.schemas.types import SystemConfigKey

        enabled_ids = sites or SystemConfigOper().get(SystemConfigKey.IndexerSites) or []
        indexers = [idx for idx in list(self._indexers) if not enabled_ids or idx.get("id") in enabled_ids]
        if not indexers:
            return []

        results = []
        tasks = [chain_self.async_search_torrents(site=s, keyword=en_keyword,
                                                    mtype=mediainfo.type if mediainfo else None, page=page)
                 for s in indexers]
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                if result:
                    results.extend(result)
            except Exception:
                pass
        return results

    # ---------------------------------------------------------------------------
    # V3 必须实现的方法
    # ---------------------------------------------------------------------------

    def get_state(self) -> bool:
        """返回插件当前是否启用。"""
        return self._enabled

    def stop_service(self) -> None:
        """释放插件创建的后台资源。"""
        try:
            if self._scheduler:
                try:
                    self._scheduler.remove_all_jobs()
                    if self._scheduler.running:
                        self._scheduler.shutdown(wait=False)
                except Exception:
                    pass
                self._scheduler = None

            self._remove_search_patch()

            if self._indexers:
                logger.info(f"【{self.plugin_name}】服务已停止，{len(self._indexers)} 个索引器保留在站点管理中")
                self._indexers = []

        except Exception as e:
            logger.error(f"【{self.plugin_name}】停止服务异常：{str(e)}")

    def get_api(self) -> list[dict[str, Any]]:
        """返回动态 API 声明。"""
        return [
            {
                "path": "/indexers",
                "endpoint": self.get_indexers,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取索引器列表",
            },
            {
                "path": "/search",
                "endpoint": self.api_search,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "搜索种子资源",
            }
        ]

    def get_form(self) -> Tuple[list[dict], dict[str, Any]]:
        """返回配置页面和默认配置。"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件",
                                       "hint": "开启后将使用Jackett进行搜索", "persistent-hint": True}}
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {"component": "VSwitch", "props": {"model": "onlyonce", "label": "立即运行一次",
                                       "hint": "插件将立即同步索引器列表", "persistent-hint": True}}
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {"component": "VTextField", "props": {"model": "host", "label": "服务器地址",
                                       "placeholder": "http://127.0.0.1:9117",
                                       "hint": "Jackett服务器地址", "persistent-hint": True}}
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {"component": "VTextField", "props": {"model": "api_key", "label": "API密钥",
                                       "type": "password", "hint": "在Jackett界面获取API密钥", "persistent-hint": True}}
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {"component": "VTextField", "props": {"model": "cron", "label": "同步周期",
                                       "placeholder": "0 0 */12 * *", "hint": "Cron表达式，默认每12小时", "persistent-hint": True}}
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {"component": "VSwitch", "props": {"model": "proxy", "label": "使用代理",
                                       "hint": "访问Jackett时使用系统代理", "persistent-hint": True}}
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "border": "start",
                                       "title": "配置步骤",
                                       "text": "① 填写Jackett地址和API密钥 → ② 保存并启用「立即运行一次」→ ③ 在站点管理中添加站点"}}
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "host": "",
            "api_key": "",
            "proxy": False,
            "cron": "0 0 */12 * *",
            "onlyonce": False
        }

    def get_page(self) -> list[dict]:
        """返回插件详情页。"""
        status_info = ['状态：运行中' if self._enabled else '状态：已停用']
        if self._last_update:
            status_info.append(f'最后同步：{self._last_update.strftime("%Y-%m-%d %H:%M:%S")}')
        status_info.append(f'索引器数量：{len(self._indexers)}')

        header_row = {
            'component': 'VRow', 'props': {'class': 'font-weight-bold text-caption align-center py-1 px-2'},
            'content': [
                {'component': 'VCol', 'props': {'cols': 5}, 'content': [{'component': 'span', 'text': '索引器名称'}]},
                {'component': 'VCol', 'props': {'cols': 2}, 'content': [{'component': 'span', 'text': '隐私类型'}]},
                {'component': 'VCol', 'props': {'cols': 3}, 'content': [{'component': 'span', 'text': '站点domain'}]},
                {'component': 'VCol', 'props': {'cols': 2}, 'content': [{'component': 'span', 'text': 'RSS链接'}]},
            ]
        }

        data_rows = []
        for site in self._indexers:
            privacy = site.get("privacy", "private")
            privacy_text = {"public": "公开", "semi-public": "半私有"}.get(privacy.lower(), "私有")
            display_name = site.get("name", "Unknown")
            if display_name.startswith(f"{self.plugin_name}-"):
                display_name = display_name[len(f"{self.plugin_name}-"):]
            domain = site.get("domain", "N/A")
            rss_url = site.get("rss", "")
            rss_col = [{'component': 'a', 'props': {'href': rss_url, 'target': '_blank', 'title': rss_url}, 'text': '复制RSS链接'}] if rss_url else [{'component': 'span', 'text': '-'}]

            data_rows.append({
                'component': 'VRow', 'props': {'class': 'text-caption align-center py-1 px-2'},
                'content': [
                    {'component': 'VCol', 'props': {'cols': 5, 'class': 'text-truncate'}, 'content': [{'component': 'span', 'text': display_name}]},
                    {'component': 'VCol', 'props': {'cols': 2}, 'content': [{'component': 'span', 'text': privacy_text}]},
                    {'component': 'VCol', 'props': {'cols': 3, 'class': 'text-truncate'}, 'content': [{'component': 'span', 'text': domain}]},
                    {'component': 'VCol', 'props': {'cols': 2}, 'content': rss_col},
                ]
            })

        return [
            {'component': 'VRow', 'content': [
                {'component': 'VCol', 'props': {'cols': 12}, 'content': [
                    {'component': 'VAlert', 'props': {'type': 'success' if self._enabled else 'info', 'variant': 'tonal', 'text': ' | '.join(status_info)}}
                ]}
            ]},
            {'component': 'VRow', 'content': [
                {'component': 'VCol', 'props': {'cols': 12}, 'content': [
                    {'component': 'VCard', 'props': {'class': 'pa-0'}, 'content': [
                        {'component': 'VCardText', 'props': {'class': 'pa-2'}, 'content': [
                            {'component': 'div', 'props': {'style': 'max-height:30rem; overflow-y:auto'}, 'content': [header_row] + data_rows}
                        ]}
                    ]}
                ]}
            ]}
        ]

    def get_command(self) -> list[dict[str, Any]]:
        """注册远程命令。"""
        return [
            {"cmd": "/jackett_search", "event": EventType.PluginAction, "desc": "Jackett搜索", "category": "索引器",
             "data": {"action": "jackett_search"}},
            {"cmd": "/jackett_sites", "event": EventType.PluginAction, "desc": "Jackett站点列表", "category": "索引器",
             "data": {"action": "jackett_sites"}}
        ]

    @eventmanager.register(EventType.PluginAction)
    def command_action(self, event: Event):
        """处理远程命令。"""
        if not self._enabled:
            return
        event_data = event.event_data or {}
        action = event_data.get("action")
        if not action:
            return

        channel = event_data.get("channel")
        source = event_data.get("source")
        user = event_data.get("user")

        if action == "jackett_sites":
            self._handle_sites_command(channel, source, user)
            return

        if action != "jackett_search":
            return

        args = event_data.get("args", "")
        if not args:
            self.post_message(channel=channel, title="❌ Jackett搜索失败", text="请提供搜索关键词", userid=user)
            return

        parts = args.strip().split()
        keyword = parts[0]
        mtype, indexer_name = None, None
        if len(parts) > 1:
            if parts[1].lower() in ["movie", "tv"]:
                mtype = parts[1].lower()
                if len(parts) > 2:
                    indexer_name = parts[2]
            else:
                indexer_name = parts[1]

        self.post_message(channel=channel, title="🔍 Jackett搜索中...", text=f"关键词：{keyword}", userid=user)

        try:
            results = self.api_search(keyword=keyword, indexer_name=indexer_name, mtype=mtype, page=0)
            if not results:
                self.post_message(channel=channel, title="📭 未找到结果", text=f"关键词：{keyword}", userid=user)
                return

            max_display = 10
            result_text = f"找到 {len(results)} 条结果，显示前 {min(len(results), max_display)} 条：\n\n"
            for idx, torrent in enumerate(results[:max_display], 1):
                size_gb = torrent['size'] / (1024**3) if torrent['size'] > 0 else 0
                promo = []
                if torrent['downloadvolumefactor'] == 0.0:
                    promo.append("🆓")
                elif torrent['downloadvolumefactor'] == 0.5:
                    promo.append("50%")
                if torrent['uploadvolumefactor'] == 2.0:
                    promo.append("2xUp")
                promo_str = " ".join(promo) if promo else ""
                result_text += f"{idx}. {torrent['title']}\n   大小: {size_gb:.2f}GB | 做种: {torrent['seeders']} | 下载: {torrent['peers']}\n   站点: {torrent['site_name']}\n"
                if promo_str:
                    result_text += f"   促销: {promo_str}\n"
                result_text += "\n"

            self.post_message(channel=channel, title="✅ Jackett搜索完成", text=result_text.strip(), userid=user)

        except Exception as e:
            logger.error(f"【{self.plugin_name}】远程搜索失败：{str(e)}")
            self.post_message(channel=channel, title="❌ Jackett搜索失败", text=f"错误：{str(e)}", userid=user)

    def _handle_sites_command(self, channel, source, user):
        """处理站点列表命令。"""
        try:
            if not self._indexers:
                self.post_message(channel=channel, title="📋 Jackett站点列表", text="当前没有已注册的索引器", userid=user)
                return

            total = len(self._indexers)
            private_count = sum(1 for idx in self._indexers if idx.get("privacy", "").lower() not in ["public", "semi-public"])
            sites_text = f"共 {total} 个索引器（私有:{private_count}）\n\n"
            for idx, indexer in enumerate(self._indexers, 1):
                privacy = indexer.get("privacy", "private")
                icon = {"public": "🌐", "semi-public": "🔓"}.get(privacy.lower(), "🔒")
                site_name = indexer.get("name", "Unknown")
                if site_name.startswith(f"{self.plugin_name}-"):
                    site_name = site_name[len(f"{self.plugin_name}-"):]
                sites_text += f"{idx}. {icon} {site_name}\n"

            self.post_message(channel=channel, title="📋 Jackett站点列表", text=sites_text.strip(), userid=user)
        except Exception as e:
            self.post_message(channel=channel, title="❌ 获取站点列表失败", text=f"错误：{str(e)}", userid=user)

    def get_agent_tools(self) -> list[Type]:
        """注册 Agent 工具。"""
        return [SearchTorrentsTool, ListIndexersTool]

    def get_module(self) -> Dict[str, Any]:
        """声明模块扩展方法。"""
        if not self._enabled:
            return {}
        return {
            "search_torrents": self.search_torrents,
            "async_search_torrents": self.async_search_torrents,
            "refresh_torrents": self.refresh_torrents,
            "async_refresh_torrents": self.async_refresh_torrents,
        }

    # ---------------------------------------------------------------------------
    # 搜索与 TorrentInfo 相关方法（核心功能，逻辑保持不变）
    # ---------------------------------------------------------------------------

    async def async_search_torrents(self, site: Dict[str, Any], keyword: str,
                                     mtype: Optional[MediaType] = None, page: Optional[int] = 0) -> List:
        """异步搜索。"""
        return self.search_torrents(site, keyword, mtype, page)

    def refresh_torrents(self, site: Dict[str, Any], keyword: Optional[str] = None,
                          cat: Optional[str] = None, page: Optional[int] = 0) -> List:
        """浏览最新种子（spider模式）。"""
        if not site or not isinstance(site, dict):
            return []
        site_name = site.get("name", "")
        site_prefix = site_name.split("-")[0] if "-" in site_name else site_name
        if site_prefix != self.plugin_name:
            return []
        domain = site.get("domain", "").replace("http://", "").replace("https://", "").rstrip("/")
        indexer_name = domain.split(".")[-1]
        if not indexer_name:
            return []
        try:
            params = {"apikey": self._api_key, "t": "search", "q": "", "cat": "2000,5000", "limit": 100, "offset": page * 100 if page else 0}
            xml_content = self._search_jackett_api(indexer_name, params)
            if not xml_content:
                return []
            return self._parse_torznab_xml(xml_content, site_name)
        except Exception as e:
            logger.error(f"【{self.plugin_name}】[refresh] 异常：{str(e)}")
            return []

    async def async_refresh_torrents(self, site: Dict[str, Any], keyword: Optional[str] = None,
                                       cat: Optional[str] = None, page: Optional[int] = 0) -> List:
        """异步浏览。"""
        return self.refresh_torrents(site, keyword, cat, page)

    def search_torrents(self, site: Dict[str, Any], keyword: str,
                         mtype: Optional[MediaType] = None, page: Optional[int] = 0) -> List:
        """通过 Jackett Torznab API 搜索种子。"""
        results = []
        if not site or not isinstance(site, dict) or not keyword:
            return results

        site_name = site.get("name", "")
        site_prefix = site_name.split("-")[0] if "-" in site_name else site_name
        if site_prefix != self.plugin_name:
            return results

        try:
            is_imdb = self._is_imdb_id(keyword)
            if not is_imdb and not self._is_english_keyword(keyword):
                return results
        except Exception:
            return results

        try:
            domain = site.get("domain", "")
            if not domain:
                return results
            domain_clean = domain.replace("http://", "").replace("https://", "").rstrip("/")
            indexer_name = domain_clean.split(".")[-1]
            if not indexer_name:
                return results

            search_params = self._build_search_params(keyword, mtype, page)
            xml_content = self._search_jackett_api(indexer_name, search_params)
            if not xml_content or not isinstance(xml_content, str):
                return results

            results = self._parse_torznab_xml(xml_content, site_name)
            logger.info(f"【{self.plugin_name}】搜索完成：{site_name} 返回 {len(results)} 个结果")

        except Exception as e:
            logger.error(f"【{self.plugin_name}】搜索异常：{str(e)}\n{traceback.format_exc()}")

        return results

    def _build_search_params(self, keyword: str, mtype: Optional[MediaType] = None, page: int = 0) -> Dict[str, Any]:
        """构建搜索参数。"""
        categories = self._get_categories(mtype)
        is_imdb_id = self._is_imdb_id(keyword)
        params = {"apikey": self._api_key, "limit": 100, "offset": page * 100 if page else 0}

        if is_imdb_id:
            params["t"] = "tvsearch" if mtype == MediaType.TV else "movie"
            params["imdbid"] = keyword
        else:
            params["t"] = "search"
            params["q"] = keyword

        if categories:
            params["cat"] = ",".join(map(str, categories))
        return params

    @staticmethod
    def _get_categories(mtype: Optional[MediaType] = None) -> List[int]:
        """根据媒体类型获取 Torznab 分类 ID。"""
        if not mtype:
            return [2000, 5000]
        elif mtype == MediaType.MOVIE:
            return [2000]
        elif mtype == MediaType.TV:
            return [5000]
        return [2000, 5000]

    def _search_jackett_api(self, indexer_name: str, params: Dict[str, Any]) -> Optional[str]:
        """执行 Jackett API 请求。"""
        try:
            url = f"{self._host}/api/v2.0/indexers/{indexer_name}/results/torznab/api"
            response = AsyncRequestUtils(proxies=self._proxy).get_res(url=url, params=params, timeout=60)
            if not response or not hasattr(response, 'status_code'):
                return None
            if response.status_code != 200:
                return None
            error_msg = self._parse_jackett_error(response.text)
            if error_msg:
                logger.warning(f"【{self.plugin_name}】索引器 [{indexer_name}] 搜索失败：{error_msg}")
                return None
            return response.text if response.text else None
        except Exception as e:
            logger.error(f"【{self.plugin_name}】搜索API异常：{str(e)}")
            return None

    def _parse_torznab_xml(self, xml_content: str, site_name: str) -> List:
        """解析 Torznab XML 响应。"""
        results = []
        try:
            from app.core.context import TorrentInfo
            dom_tree = xml.dom.minidom.parseString(xml_content)
            root_node = dom_tree.documentElement
            if root_node.tagName == "error":
                return []
            channel = root_node.getElementsByTagName("channel")
            if not channel:
                return []
            items = channel[0].getElementsByTagName("item")
            for item in items:
                torrent = self._parse_torznab_item(item, site_name)
                if torrent:
                    results.append(torrent)
        except Exception as e:
            logger.error(f"【{self.plugin_name}】解析XML异常：{str(e)}")
        return results

    def _parse_torznab_item(self, item, site_name: str):
        """解析单个 Torznab item。"""
        try:
            from app.core.context import TorrentInfo
            title = DomUtils.tag_value(item, "title", default="")
            if not title:
                return None

            enclosure = ""
            try:
                enc = item.getElementsByTagName("enclosure")
                if enc:
                    enclosure = enc[0].getAttribute("url")
            except Exception:
                pass
            if not enclosure:
                enclosure = DomUtils.tag_value(item, "link", default="")

            magnet = self._get_torznab_attr(item, "magneturl")
            if magnet:
                enclosure = magnet
            if not enclosure:
                return None

            size = 0
            size_str = DomUtils.tag_value(item, "size", default="0")
            try:
                size = int(size_str) if size_str.isdigit() else 0
            except Exception:
                pass

            seeders = self._get_torznab_attr_int(item, "seeders", 0)
            peers = self._get_torznab_attr_int(item, "peers", 0)
            leechers = max(0, peers - seeders)
            pub_date = DomUtils.tag_value(item, "pubDate", default="")
            description = DomUtils.tag_value(item, "description", default="")
            page_url = DomUtils.tag_value(item, "comments", default="") or DomUtils.tag_value(item, "guid", default="")
            imdb_id = self._get_torznab_attr(item, "imdbid")
            grabs = self._get_torznab_attr_int(item, "grabs", 0)
            download_factor = self._get_torznab_attr_float(item, "downloadvolumefactor", 1.0)

            return TorrentInfo(
                title=title, enclosure=enclosure, description=description, size=size,
                seeders=seeders, peers=leechers, page_url=page_url, site_name=site_name,
                pubdate=self._parse_rfc2822_date(pub_date), imdbid=self._format_imdb_id(imdb_id),
                downloadvolumefactor=download_factor, uploadvolumefactor=1.0, grabs=grabs,
            )
        except Exception as e:
            logger.error(f"【{self.plugin_name}】解析种子信息异常：{str(e)}")
            return None

    def _get_torznab_attr(self, item, attr_name: str, default: str = "") -> str:
        try:
            attrs = item.getElementsByTagName("torznab:attr")
            for attr in attrs:
                if attr.getAttribute("name") == attr_name:
                    return attr.getAttribute("value")
            return default
        except Exception:
            return default

    def _get_torznab_attr_int(self, item, attr_name: str, default: int = 0) -> int:
        try:
            value = self._get_torznab_attr(item, attr_name, str(default))
            return int(value) if value.isdigit() else default
        except Exception:
            return default

    def _get_torznab_attr_float(self, item, attr_name: str, default: float = 0.0) -> float:
        try:
            return float(self._get_torznab_attr(item, attr_name, str(default)))
        except Exception:
            return default

    @staticmethod
    def _parse_rfc2822_date(date_str: str) -> str:
        try:
            if not date_str:
                return ""
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return date_str

    def _parse_jackett_error(self, xml_content: str) -> Optional[str]:
        try:
            if not xml_content or '<error' not in xml_content:
                return None
            dom_tree = xml.dom.minidom.parseString(xml_content)
            root_node = dom_tree.documentElement
            if root_node.tagName != "error":
                return None
            return root_node.getAttribute("description") or f"Error {root_node.getAttribute('code')}"
        except Exception:
            return None

    @staticmethod
    def _is_imdb_id(keyword: str) -> bool:
        return bool(re.match(r'^tt\d{7,}$', keyword.strip())) if keyword else False

    @staticmethod
    def _is_english_keyword(keyword: str) -> bool:
        if not keyword:
            return False
        cleaned = re.sub(r'[.,!?;:()\[\]{}\s\-_]+', '', keyword)
        if not cleaned:
            return True
        ascii_count = sum(1 for c in cleaned if ord(c) < 128)
        cjk_count = sum(1 for c in cleaned if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
        if cjk_count > 0 and cjk_count / len(cleaned) > 0.3:
            return False
        return ascii_count / len(cleaned) > 0.5 if cleaned else True

    @staticmethod
    def _format_imdb_id(imdb_id: Any) -> str:
        try:
            if not imdb_id:
                return ""
            imdb_str = str(imdb_id)
            return imdb_str if imdb_str.startswith("tt") else f"tt{imdb_str}"
        except Exception:
            return ""

    def get_indexers(self) -> List[Dict[str, Any]]:
        """返回插件管理的索引器列表。"""
        return self._indexers if self._indexers else []

    def api_search(self, keyword: str, indexer_name: str = None, mtype: str = None, page: int = 0) -> List[Dict[str, Any]]:
        """API 搜索端点。"""
        if not self._enabled or not keyword:
            return []

        media_type = None
        if mtype:
            if mtype.lower() == "movie":
                media_type = MediaType.MOVIE
            elif mtype.lower() == "tv":
                media_type = MediaType.TV

        results = []
        if indexer_name:
            for indexer in self._indexers:
                domain = indexer.get("domain", "").replace("http://", "").replace("https://", "").rstrip("/")
                idx_name = domain.split(".")[-1]
                if idx_name == indexer_name:
                    torrents = self.search_torrents(indexer, keyword, media_type, page)
                    results.extend(torrents)
                    break
        else:
            for indexer in self._indexers:
                try:
                    torrents = self.search_torrents(indexer, keyword, media_type, page)
                    results.extend(torrents)
                except Exception:
                    continue

        return [{"title": t.title, "description": t.description, "enclosure": t.enclosure,
                 "page_url": t.page_url, "size": t.size, "seeders": t.seeders, "peers": t.peers,
                 "pubdate": t.pubdate, "imdbid": t.imdbid, "downloadvolumefactor": t.downloadvolumefactor,
                 "uploadvolumefactor": t.uploadvolumefactor, "site_name": t.site_name, "grabs": t.grabs} for t in results]
