# -*- coding: utf-8 -*-
"""
JackettIndexer Plugin for MoviePilot V3.3

V3 adapted version - uses stable SDK imports throughout.
Fixes AsyncRequestUtils async/sync bug by using synchronous RequestUtils.
No filtering of any site type (public/semi-private/private/XXX).

Version: 3.3.0
Author: Summer&Openclaw
"""

import re
import traceback
import copy
import xml.dom.minidom
from typing import List, Dict, Optional, Any, Tuple, Type, Callable
from datetime import datetime
from urllib.parse import urlencode

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# SDK imports (V3 compliant - stable public contracts)
from app.sdk.media import TorrentInfo
from app.sdk.events import Event, eventmanager
from app.sdk.network import RequestUtils, SitesHelper
from app.sdk.logging import logger
from app.sdk.string import StringUtils

# Stable public imports
from app.plugins import _PluginBase
from app.schemas.types import MediaType, EventType

# Foundation modules (not wrapped by SDK, direct stable path)
from app.foundation.dom import DomUtils

from .agenttool import SearchTorrentsTool, ListIndexersTool


class JackettIndexer(_PluginBase):
    """
    Jackett Indexer Plugin (V3.3)

    Provides torrent search functionality through Jackett Torznab API.
    Registers all configured Jackett indexers as MoviePilot sites.
    """

    # Plugin metadata
    plugin_name = "Jackett索引器"
    plugin_desc = "集成Jackett索引器搜索，支持Torznab协议多站点搜索。支持全部站点类型（含公开/半公开/私有/XXX）。"
    plugin_icon = "Jackett_A.png"
    plugin_version = "3.3.0"
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
    _scheduler: Optional[BackgroundScheduler] = None
    _sites_helper: Optional[SitesHelper] = None
    _last_update: Optional[datetime] = None
    # 搜索链补丁：保存被替换的原始方法
    _original_search_all: Optional[Callable] = None
    _original_async_search_all: Optional[Callable] = None

    # Domain identifier
    JACKETT_DOMAIN = "jackett_indexer.claude"

    def init_plugin(self, config: dict = None):
        """Initialize the plugin with user configuration."""
        logger.info(f"【{self.plugin_name}】开始初始化插件")

        # Stop existing services
        self.stop_service()

        # Load configuration
        if config:
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

        # Initialize sites helper
        self._sites_helper = SitesHelper()

        # Setup scheduler for periodic sync
        if self._cron:
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

        # Handle run once flag
        if self._onlyonce:
            self._onlyonce = False
            self.update_config({
                **config,
                "onlyonce": False
            })
            logger.info(f"【{self.plugin_name}】立即运行完成，已关闭立即运行标志")

        # Fetch and register indexers
        if not self._indexers:
            logger.info(f"【{self.plugin_name}】开始获取索引器...")
            self._fetch_and_build_indexers()

        # Register indexers to site management
        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            self._sites_helper.add_indexer(domain, indexer)
            logger.debug(f"【{self.plugin_name}】注册到站点管理：{indexer.get('name')} (domain: {domain})")

        logger.info(f"【{self.plugin_name}】插件初始化完成，共注册 {len(self._indexers)} 个索引器")

        # 应用搜索链补丁
        self._apply_search_patch()

    def _fetch_and_build_indexers(self) -> bool:
        """Fetch indexers from Jackett and build indexer dictionaries."""
        try:
            indexers = self._get_indexers_from_jackett()
            if not indexers:
                logger.warning(f"【{self.plugin_name}】未获取到索引器列表")
                return False

            # Build indexer dicts
            self._indexers = []
            for indexer_data in indexers:
                try:
                    indexer_dict = self._build_indexer_dict(indexer_data)
                    self._indexers.append(indexer_dict)
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】构建索引器失败：{str(e)}")
                    continue

            logger.info(f"【{self.plugin_name}】成功获取 {len(self._indexers)} 个索引器")
            return True

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取索引器异常：{str(e)}\n{traceback.format_exc()}")
            return False

    def _sync_indexers(self) -> bool:
        """Periodic sync: fetch indexers and register new ones."""
        try:
            # Fetch indexers from Jackett
            if not self._fetch_and_build_indexers():
                return False

            # Register indexers to site management
            registered_count = 0
            for indexer in self._indexers:
                domain = indexer.get("domain", "")
                site_info = self._sites_helper.get_indexer(domain)
                if not site_info:
                    new_indexer = copy.deepcopy(indexer)
                    self._sites_helper.add_indexer(domain, new_indexer)
                    logger.info(f"【{self.plugin_name}】✅ 成功添加到站点管理：{indexer.get('name')} (domain: {domain})")
                    registered_count += 1

            self._last_update = datetime.now()
            logger.info(f"【{self.plugin_name}】索引器同步完成，总计 {len(self._indexers)} 个，新增 {registered_count} 个")
            return True

        except Exception as e:
            logger.error(f"【{self.plugin_name}】同步索引器异常：{str(e)}\n{traceback.format_exc()}")
            return False

    def _get_indexers_from_jackett(self) -> List[Dict[str, Any]]:
        """Fetch indexer list from Jackett API."""
        try:
            url = f"{self._host}/api/v2.0/indexers/all/results/torznab/api"
            params = {
                "apikey": self._api_key,
                "t": "indexers",
                "configured": "true"
            }

            logger.debug(f"【{self.plugin_name}】正在获取索引器列表：{url}?t=indexers&configured=true")

            # V3.1 FIX: 使用同步的 RequestUtils，不要用 AsyncRequestUtils
            # AsyncRequestUtils.get_res() 是 async 方法，同步调用会返回 coroutine 而不是 Response
            response = RequestUtils(proxies=self._proxy).get_res(
                url=url,
                params=params,
                timeout=30
            )

            if not response:
                logger.error(f"【{self.plugin_name}】API请求失败：无响应")
                return []

            if response.status_code != 200:
                logger.error(f"【{self.plugin_name}】API请求失败：HTTP {response.status_code}")
                logger.debug(f"【{self.plugin_name}】响应内容：{response.text}")
                return []

            # Parse XML response
            indexers = self._parse_indexers_xml(response.text)

            logger.info(f"【{self.plugin_name}】获取到 {len(indexers)} 个已配置的索引器")

            for idx in indexers[:3]:
                idx_type = idx.get("type", "未知")
                logger.debug(f"【{self.plugin_name}】索引器示例：id={idx.get('id')}, title={idx.get('title')}, type={idx_type}")

            return indexers

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取索引器列表异常：{str(e)}\n{traceback.format_exc()}")
            return []

    def _parse_indexers_xml(self, xml_content: str) -> List[Dict[str, Any]]:
        """Parse Jackett indexers XML response."""
        try:
            dom_tree = xml.dom.minidom.parseString(xml_content)
            root_node = dom_tree.documentElement

            if root_node.tagName == "error":
                error_code = root_node.getAttribute("code")
                error_desc = root_node.getAttribute("description")
                logger.error(f"【{self.plugin_name}】Torznab错误 {error_code}：{error_desc}")
                return []

            indexer_elements = root_node.getElementsByTagName("indexer")

            indexers = []
            for elem in indexer_elements:
                try:
                    indexer = {
                        "id": elem.getAttribute("id"),
                        "title": DomUtils.tag_value(elem, "title", default=""),
                        "type": DomUtils.tag_value(elem, "type", default=""),
                        "language": DomUtils.tag_value(elem, "language", default="") or "en-US",
                    }

                    if indexer["id"] and indexer["title"]:
                        indexers.append(indexer)
                        logger.debug(f"【{self.plugin_name}】解析到索引器：id={indexer['id']}, title={indexer['title']}")

                except Exception as e:
                    logger.debug(f"【{self.plugin_name}】解析索引器失败：{str(e)}")
                    continue

            return indexers

        except Exception as e:
            logger.error(f"【{self.plugin_name}】解析XML失败：{str(e)}")
            return []

    def _get_indexer_categories(self, indexer_name: str) -> Tuple[Optional[Dict[str, List[Dict[str, Any]]]], bool]:
        """Get indexer categories from Jackett Torznab API."""
        try:
            url = f"{self._host}/api/v2.0/indexers/{indexer_name}/results/torznab/api"
            params = {"apikey": self._api_key, "t": "caps"}

            # V3.1 FIX: 使用同步 RequestUtils
            response = RequestUtils(proxies=self._proxy).get_res(
                url=url,
                params=params,
                timeout=15
            )

            if not response or response.status_code != 200:
                logger.debug(f"【{self.plugin_name}】无法获取索引器 {indexer_name} 的分类信息")
                return None, False

            try:
                dom_tree = xml.dom.minidom.parseString(response.text)
                root_node = dom_tree.documentElement
            except Exception as e:
                logger.debug(f"【{self.plugin_name}】解析索引器 {indexer_name} XML失败：{str(e)}")
                return None, False

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

                    cat_entry = {
                        "id": int(cat_id),
                        "cat": cat_name or f"Category {cat_id}",
                        "desc": cat_name or f"Category {cat_id}"
                    }

                    if top_level == 2000:
                        if not any(c["id"] == cat_entry["id"] for c in category_map["movie"]):
                            category_map["movie"].append(cat_entry)
                    elif top_level == 5000:
                        if not any(c["id"] == cat_entry["id"] for c in category_map["tv"]):
                            category_map["tv"].append(cat_entry)

                except (ValueError, TypeError):
                    continue

            # 不过滤任何类型的站点（包括 XXX），所有索引器均会被注册

            if not category_map["movie"] and not category_map["tv"]:
                logger.debug(f"【{self.plugin_name}】索引器 {indexer_name} 无电影/电视分类")
                return None, False

            result = {}
            if category_map["movie"]:
                result["movie"] = category_map["movie"]
            if category_map["tv"]:
                result["tv"] = category_map["tv"]

            return (result if result else None), False

        except Exception as e:
            logger.debug(f"【{self.plugin_name}】获取索引器 {indexer_name} 分类信息异常：{str(e)}")
            return None, False

    def _build_indexer_dict(self, indexer: Dict[str, Any]) -> Dict[str, Any]:
        """Build MoviePilot indexer dictionary from Jackett indexer data."""
        indexer_name = indexer.get("id", "")
        indexer_title = indexer.get("title", indexer_name)
        indexer_type = indexer.get("type", "")

        # 每个索引器独立 domain：直接用索引器 ID 命名
        domain = f"jackett_{indexer_name}"

        is_public = indexer_type.lower() == "public" if indexer_type else False

        type_display = indexer_type if indexer_type else "(空)"
        privacy_display = "公开" if is_public else "私有"
        logger.debug(f"【{self.plugin_name}】索引器 {indexer_title} 类型：{type_display} -> {privacy_display}")

        category, _ = self._get_indexer_categories(indexer_name)
        rss_url = self._build_rss_url(indexer_name=indexer_name, category=category)

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

        return indexer_dict

    def _build_rss_url(self, indexer_name: str, category: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> str:
        """Build Jackett Torznab RSS URL."""
        cat_ids = []
        if category:
            if category.get("movie"):
                cat_ids.append("2000")
            if category.get("tv"):
                cat_ids.append("5000")
        if not cat_ids:
            cat_ids = ["2000", "5000"]

        params = [
            ("apikey", self._api_key),
            ("t", "search"),
            ("q", ""),
            ("cat", ",".join(cat_ids)),
            ("limit", 30),
        ]
        query_string = urlencode(params)
        return f"{self._host.rstrip('/')}/api/v2.0/indexers/{indexer_name}/results/torznab/api?{query_string}"

    # ------------------------------------------------------------------ #
    #  搜索链补丁：支持中文媒体搜索时对英文索引器使用英文标题回退
    # ------------------------------------------------------------------ #

    def _apply_search_patch(self):
        """向 SearchChain 注入补丁，支持中文关键词回退英文标题搜索。"""
        try:
            from app.chain.search import SearchChain
        except ImportError:
            logger.warning(f"【{self.plugin_name}】无法导入 SearchChain，跳过搜索链补丁")
            return

        marker = f"_en_fallback_{self.plugin_config_prefix}"

        if getattr(SearchChain._SearchChain__search_all_sites, marker, False):
            logger.debug(f"【{self.plugin_name}】搜索链补丁已存在，跳过")
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
                logger.debug(f"【{plugin_ref.plugin_name}】中文关键词 '{keyword}' 无可用英文标题，跳过补充搜索")
                return results
            logger.info(f"【{plugin_ref.plugin_name}】检测到中文关键词，对本插件索引器补充搜索英文标题：{en_keyword}")
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
                logger.debug(f"【{plugin_ref.plugin_name}】中文关键词 '{keyword}' 无可用英文标题，跳过补充搜索")
                return results
            logger.info(f"【{plugin_ref.plugin_name}】检测到中文关键词，对本插件索引器补充异步搜索英文标题：{en_keyword}")
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
            if (self._original_search_all is not None and
                    getattr(SearchChain._SearchChain__search_all_sites, marker, False)):
                SearchChain._SearchChain__search_all_sites = self._original_search_all
                self._original_search_all = None
                logger.info(f"【{self.plugin_name}】搜索链同步补丁已恢复")
            if (self._original_async_search_all is not None and
                    getattr(SearchChain._SearchChain__async_search_all_sites, marker, False)):
                SearchChain._SearchChain__async_search_all_sites = self._original_async_search_all
                self._original_async_search_all = None
                logger.info(f"【{self.plugin_name}】搜索链异步补丁已恢复")
        except Exception as e:
            logger.error(f"【{self.plugin_name}】恢复搜索链补丁失败：{e}")

    @staticmethod
    def _get_en_keyword(mediainfo) -> Optional[str]:
        """从 mediainfo 中提取英文/非中文标题作为回退关键词。"""
        if mediainfo.en_title:
            return mediainfo.en_title
        if mediainfo.original_title and not StringUtils.is_chinese(mediainfo.original_title):
            return mediainfo.original_title
        return None

    def _extra_search_sync(self, chain_self, en_keyword: str, mediainfo, sites, page: int) -> list:
        """同步：对本插件自己的索引器用英文标题发起补充搜索。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app.db.systemconfig_oper import SystemConfigOper
        from app.schemas.types import SystemConfigKey

        enabled_ids = sites or SystemConfigOper().get(SystemConfigKey.IndexerSites) or []
        indexers = [
            idx for idx in list(self._indexers)
            if not enabled_ids or idx.get("id") in enabled_ids
        ]
        if not indexers:
            return []

        results = []
        with ThreadPoolExecutor(max_workers=len(indexers)) as executor:
            tasks = [
                executor.submit(self.search_torrents,
                                site=s, keyword=en_keyword,
                                mtype=mediainfo.type if mediainfo else None,
                                page=page)
                for s in indexers
            ]
            for future in as_completed(tasks):
                try:
                    result = future.result()
                    if result:
                        results.extend(result)
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】补充搜索异常：{e}")
        logger.info(f"【{self.plugin_name}】英文标题补充搜索完成，关键词：{en_keyword}，获得 {len(results)} 个结果")
        return results

    async def _extra_search_async(self, chain_self, en_keyword: str, mediainfo, sites, page: int) -> list:
        """异步：对本插件自己的索引器用英文标题发起补充搜索。"""
        import asyncio
        from app.db.systemconfig_oper import SystemConfigOper
        from app.schemas.types import SystemConfigKey

        enabled_ids = sites or SystemConfigOper().get(SystemConfigKey.IndexerSites) or []
        indexers = [
            idx for idx in list(self._indexers)
            if not enabled_ids or idx.get("id") in enabled_ids
        ]
        if not indexers:
            return []

        results = []
        tasks = [
            chain_self.async_search_torrents(
                site=s, keyword=en_keyword,
                mtype=mediainfo.type if mediainfo else None,
                page=page)
            for s in indexers
        ]
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                if result:
                    results.extend(result)
            except Exception as e:
                logger.error(f"【{self.plugin_name}】补充异步搜索异常：{e}")
        logger.info(f"【{self.plugin_name}】英文标题补充异步搜索完成，关键词：{en_keyword}，获得 {len(results)} 个结果")
        return results

    def get_state(self) -> bool:
        """Get plugin enabled state."""
        return self._enabled

    def stop_service(self):
        """Stop plugin services and cleanup resources."""
        try:
            if self._scheduler:
                try:
                    self._scheduler.remove_all_jobs()
                    if self._scheduler.running:
                        self._scheduler.shutdown(wait=False)
                    self._scheduler = None
                    logger.info(f"【{self.plugin_name}】定时任务已停止")
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】停止定时任务失败：{str(e)}")

            self._remove_search_patch()

            if self._indexers:
                logger.info(f"【{self.plugin_name}】服务已停止，{len(self._indexers)} 个索引器保留在站点管理中")
                self._indexers = []

        except Exception as e:
            logger.error(f"【{self.plugin_name}】停止服务异常：{str(e)}")

    def get_module(self) -> Dict[str, Any]:
        """Declare module methods to hijack system search."""
        if not self._enabled:
            logger.debug(f"【{self.plugin_name}】get_module 被调用，但插件未启用，返回空字典")
            return {}

        result = {
            "search_torrents": self.search_torrents,
            "async_search_torrents": self.async_search_torrents,
            "refresh_torrents": self.refresh_torrents,
            "async_refresh_torrents": self.async_refresh_torrents,
        }
        logger.debug(f"【{self.plugin_name}】get_module 被调用，注册 search_torrents/async_search_torrents/refresh_torrents 方法")
        return result

    async def async_search_torrents(
        self,
        site: Dict[str, Any],
        keyword: str,
        mtype: Optional[MediaType] = None,
        page: Optional[int] = 0
    ) -> List[TorrentInfo]:
        """Async wrapper for search_torrents."""
        logger.debug(f"【{self.plugin_name}】async_search_torrents 被调用")
        return self.search_torrents(site, keyword, mtype, page)

    def refresh_torrents(
        self,
        site: Dict[str, Any],
        keyword: Optional[str] = None,
        cat: Optional[str] = None,
        page: Optional[int] = 0
    ) -> List[TorrentInfo]:
        """Browse latest torrents from a Jackett indexer (spider mode)."""
        if site is None or not isinstance(site, dict):
            return []

        site_name = site.get("name", "")
        site_prefix = site_name.split("-")[0] if "-" in site_name else site_name
        if site_prefix != self.plugin_name:
            return []

        domain = site.get("domain", "")
        domain_clean = domain.replace("http://", "").replace("https://", "").rstrip("/")
        indexer_name = domain_clean.split(".")[-1]
        if not indexer_name:
            logger.warning(f"【{self.plugin_name}】[refresh] 无法从domain提取索引器名称：{domain}")
            return []

        logger.info(f"【{self.plugin_name}】开始浏览站点最新种子：{site_name}，索引器：{indexer_name}")

        try:
            params = {
                "apikey": self._api_key,
                "t": "search",
                "q": "",
                "cat": "2000,5000",
                "limit": 100,
                "offset": page * 100 if page else 0,
            }
            xml_content = self._search_jackett_api(indexer_name, params)
            if not xml_content:
                return []

            results = self._parse_torznab_xml(xml_content, site_name)
            logger.info(f"【{self.plugin_name}】浏览完成：{site_name} 获取 {len(results)} 个种子")
            return results

        except Exception as e:
            logger.error(f"【{self.plugin_name}】[refresh] 异常：{str(e)}\n{traceback.format_exc()}")
            return []

    async def async_refresh_torrents(
        self,
        site: Dict[str, Any],
        keyword: Optional[str] = None,
        cat: Optional[str] = None,
        page: Optional[int] = 0
    ) -> List[TorrentInfo]:
        """Async wrapper for refresh_torrents."""
        return self.refresh_torrents(site, keyword, cat, page)

    def search_torrents(
        self,
        site: Dict[str, Any],
        keyword: str,
        mtype: Optional[MediaType] = None,
        page: Optional[int] = 0
    ) -> List[TorrentInfo]:
        """Search torrents through Jackett Torznab API."""
        results = []

        if site is None or not isinstance(site, dict):
            logger.debug(f"【{self.plugin_name}】站点参数无效")
            return results

        if not keyword:
            logger.debug(f"【{self.plugin_name}】关键词为空")
            return results

        site_name = site.get("name", "")
        if not site_name:
            logger.warning(f"【{self.plugin_name}】站点名称为空")
            return results

        site_prefix = site_name.split("-")[0] if "-" in site_name else site_name
        if site_prefix != self.plugin_name:
            return results

        logger.info(f"【{self.plugin_name}】开始检索站点：{site_name}，关键词：{keyword}")

        try:
            is_imdb = self._is_imdb_id(keyword)

            if not is_imdb and not self._is_english_keyword(keyword):
                logger.debug(f"【{self.plugin_name}】检测到非英文关键词，跳过搜索：{keyword}")
                return results
        except Exception as e:
            logger.error(f"【{self.plugin_name}】站点验证异常：{str(e)}\n{traceback.format_exc()}")
            return results

        try:
            domain = site.get("domain", "")
            if not domain:
                logger.warning(f"【{self.plugin_name}】站点缺少 domain 字段：{site_name}")
                return results

            domain_clean = domain.replace("http://", "").replace("https://", "").rstrip("/")
            indexer_name = domain_clean.split(".")[-1]

            if not indexer_name:
                logger.warning(f"【{self.plugin_name}】从domain提取的索引器ID为空：{domain}")
                return results

            logger.debug(f"【{self.plugin_name}】从domain提取索引器ID：{indexer_name}")

            search_params = self._build_search_params(
                keyword=keyword,
                mtype=mtype,
                page=page
            )

            logger.debug(f"【{self.plugin_name}】开始搜索站点：{site_name}，关键词：{keyword}，索引器ID：{indexer_name}")

            xml_content = self._search_jackett_api(indexer_name, search_params)

            if not xml_content:
                logger.debug(f"【{self.plugin_name}】搜索未返回结果")
                return results

            if not isinstance(xml_content, str):
                logger.error(f"【{self.plugin_name}】搜索返回了非字符串类型的结果：{type(xml_content)}")
                return results

            logger.debug(f"【{self.plugin_name}】索引器 [{indexer_name}] 开始解析XML内容，长度：{len(xml_content)}")
            results = self._parse_torznab_xml(xml_content, site_name)

            logger.info(f"【{self.plugin_name}】搜索完成：{site_name} 返回 {len(results)} 个结果")

        except Exception as e:
            logger.error(f"【{self.plugin_name}】搜索异常：{str(e)}\n{traceback.format_exc()}")

        return results

    def _build_search_params(
        self,
        keyword: str,
        mtype: Optional[MediaType] = None,
        page: int = 0
    ) -> Dict[str, Any]:
        """Build Jackett Torznab API search parameters."""
        categories = self._get_categories(mtype)
        is_imdb_id = self._is_imdb_id(keyword)

        params = {
            "apikey": self._api_key,
            "limit": 100,
            "offset": page * 100 if page else 0,
        }

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
        """Get Torznab category IDs based on media type."""
        if not mtype:
            return [2000, 5000]
        elif mtype == MediaType.MOVIE:
            return [2000]
        elif mtype == MediaType.TV:
            return [5000]
        return [2000, 5000]

    def _search_jackett_api(self, indexer_name: str, params: Dict[str, Any]) -> Optional[str]:
        """Execute Jackett Torznab API search request."""
        try:
            url = f"{self._host}/api/v2.0/indexers/{indexer_name}/results/torznab/api"

            logger.debug(f"【{self.plugin_name}】正在搜索 Jackett 索引器 [{indexer_name}]: {url}")
            logger.debug(f"【{self.plugin_name}】搜索参数：{params}")

            # V3.1 FIX: 使用同步 RequestUtils
            response = RequestUtils(proxies=self._proxy).get_res(
                url=url,
                params=params,
                timeout=60
            )

            if response is None:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：response 为 None")
                return None

            if not response:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：response 为 {type(response)}")
                return None

            if not hasattr(response, 'status_code') or not hasattr(response, 'text'):
                logger.error(f"【{self.plugin_name}】响应对象格式异常：response type={type(response)}")
                return None

            if response.status_code != 200:
                logger.error(f"【{self.plugin_name}】搜索API请求失败：HTTP {response.status_code}")
                try:
                    response_text = response.text if hasattr(response, 'text') else ''
                    if response_text:
                        logger.debug(f"【{self.plugin_name}】响应内容：{response_text[:500]}")
                except Exception:
                    pass
                return None

            try:
                xml_content = response.text
                if xml_content is None or xml_content == '':
                    logger.warning(f"【{self.plugin_name}】响应内容为空")
                    return None

                error_message = self._parse_jackett_error(xml_content)
                if error_message:
                    logger.warning(f"【{self.plugin_name}】索引器 [{indexer_name}] 搜索失败：{error_message}")
                    return None

                logger.debug(f"【{self.plugin_name}】索引器 [{indexer_name}] 成功获取响应，长度：{len(xml_content)}")
                return xml_content
            except Exception as e:
                logger.error(f"【{self.plugin_name}】读取响应text属性失败：{str(e)}")
                return None

        except Exception as e:
            logger.error(f"【{self.plugin_name}】搜索API异常：{str(e)}\n{traceback.format_exc()}")
            return None

    def _parse_torznab_xml(self, xml_content: str, site_name: str) -> List[TorrentInfo]:
        """Parse Torznab XML response to TorrentInfo objects."""
        results = []

        try:
            if not xml_content or not isinstance(xml_content, str):
                logger.error(f"【{self.plugin_name}】XML内容为空或类型错误")
                return results

            dom_tree = xml.dom.minidom.parseString(xml_content)
            root_node = dom_tree.documentElement

            if not root_node:
                logger.error(f"【{self.plugin_name}】XML解析失败：无法获取根节点")
                return results

            if root_node.tagName == "error":
                error_code = root_node.getAttribute("code")
                error_desc = root_node.getAttribute("description")
                logger.error(f"【{self.plugin_name}】Torznab错误 {error_code}：{error_desc}")
                return []

            channel = root_node.getElementsByTagName("channel")
            if not channel:
                logger.debug(f"【{self.plugin_name}】XML响应中未找到 channel 元素")
                return []

            items = channel[0].getElementsByTagName("item")
            logger.debug(f"【{self.plugin_name}】找到 {len(items)} 个item元素")

            for idx, item in enumerate(items):
                try:
                    torrent_info = self._parse_torznab_item(item, site_name)
                    if torrent_info:
                        results.append(torrent_info)
                        logger.debug(f"【{self.plugin_name}】成功解析item #{idx}: {torrent_info.title[:50]}")
                    else:
                        logger.debug(f"【{self.plugin_name}】item #{idx} 解析结果为 None")
                except Exception as e:
                    logger.warning(f"【{self.plugin_name}】解析item #{idx} 失败：{str(e)}")
                    continue

            logger.debug(f"【{self.plugin_name}】XML解析完成，从 {len(items)} 个item中解析出 {len(results)} 个有效结果")

        except Exception as e:
            logger.error(f"【{self.plugin_name}】解析XML异常：{str(e)}\n{traceback.format_exc()}")

        return results

    def _parse_torznab_item(self, item, site_name: str) -> Optional[TorrentInfo]:
        """Parse single Torznab item element to TorrentInfo."""
        try:
            if item is None:
                logger.warning(f"【{self.plugin_name}】XML item 为 None，跳过")
                return None

            title = DomUtils.tag_value(item, "title", default="")
            if not title:
                logger.debug(f"【{self.plugin_name}】跳过无标题的item")
                return None

            enclosure = ""
            try:
                enclosure_node = item.getElementsByTagName("enclosure")
                if enclosure_node and len(enclosure_node) > 0:
                    enclosure = enclosure_node[0].getAttribute("url")
            except Exception as e:
                logger.debug(f"【{self.plugin_name}】获取enclosure失败：{str(e)}")

            if not enclosure:
                try:
                    enclosure = DomUtils.tag_value(item, "link", default="")
                except Exception as e:
                    logger.debug(f"【{self.plugin_name}】获取link失败：{str(e)}")

            try:
                magnet_url = self._get_torznab_attr(item, "magneturl")
                if magnet_url:
                    enclosure = magnet_url
            except Exception as e:
                logger.debug(f"【{self.plugin_name}】获取magneturl失败：{str(e)}")

            if not enclosure:
                logger.debug(f"【{self.plugin_name}】跳过无下载链接的结果：{title}")
                return None

            size_str = DomUtils.tag_value(item, "size", default="0")
            try:
                size = int(size_str) if size_str.isdigit() else 0
            except Exception:
                size = 0

            seeders = self._get_torznab_attr_int(item, "seeders", 0)
            peers = self._get_torznab_attr_int(item, "peers", 0)
            leechers = max(0, peers - seeders)

            pub_date = DomUtils.tag_value(item, "pubDate", default="")
            description = DomUtils.tag_value(item, "description", default="")
            page_url = DomUtils.tag_value(item, "comments", default="") or \
                      DomUtils.tag_value(item, "guid", default="")

            imdb_id = self._get_torznab_attr(item, "imdbid")
            grabs = self._get_torznab_attr_int(item, "grabs", 0)
            download_factor = self._get_torznab_attr_float(item, "downloadvolumefactor", 1.0)

            return TorrentInfo(
                title=title,
                enclosure=enclosure,
                description=description,
                size=size,
                seeders=seeders,
                peers=leechers,
                page_url=page_url,
                site_name=site_name,
                pubdate=self._parse_rfc2822_date(pub_date),
                imdbid=self._format_imdb_id(imdb_id),
                downloadvolumefactor=download_factor,
                uploadvolumefactor=1.0,
                grabs=grabs,
            )

        except Exception as e:
            logger.error(f"【{self.plugin_name}】解析种子信息异常：{str(e)}")
            return None

    def _get_torznab_attr(self, item, attr_name: str, default: str = "") -> str:
        """Get Torznab attribute value from item."""
        try:
            attrs = item.getElementsByTagName("torznab:attr")
            for attr in attrs:
                if attr.getAttribute("name") == attr_name:
                    return attr.getAttribute("value")
            return default
        except Exception:
            return default

    def _get_torznab_attr_int(self, item, attr_name: str, default: int = 0) -> int:
        """Get Torznab attribute as integer."""
        try:
            value = self._get_torznab_attr(item, attr_name, str(default))
            return int(value) if value.isdigit() else default
        except Exception:
            return default

    def _get_torznab_attr_float(self, item, attr_name: str, default: float = 0.0) -> float:
        """Get Torznab attribute as float."""
        try:
            value = self._get_torznab_attr(item, attr_name, str(default))
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _parse_rfc2822_date(date_str: str) -> str:
        """Parse RFC 2822 date string to MoviePilot format."""
        try:
            if not date_str:
                return ""
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return date_str

    def _parse_jackett_error(self, xml_content: str) -> Optional[str]:
        """Parse Jackett error XML response and extract error message."""
        try:
            if not xml_content or '<error' not in xml_content:
                return None

            dom_tree = xml.dom.minidom.parseString(xml_content)
            root_node = dom_tree.documentElement

            if root_node.tagName != "error":
                return None

            error_code = root_node.getAttribute("code")
            error_desc = root_node.getAttribute("description")

            if not error_desc:
                return f"Error code {error_code}" if error_code else "Unknown error"

            error_lines = error_desc.split('\n')
            first_line = error_lines[0].strip() if error_lines else error_desc

            if "Exception" in first_line and ":" in first_line:
                parts = first_line.split(":")
                if len(parts) >= 3:
                    message = ":".join(parts[-2:]).strip()
                    return message
                elif len(parts) >= 2:
                    message = parts[-1].strip()
                    return message

            return first_line

        except Exception as e:
            logger.debug(f"【{self.plugin_name}】解析错误响应失败：{str(e)}")
            return None

    @staticmethod
    def _is_imdb_id(keyword: str) -> bool:
        """Check if keyword is an IMDb ID (format: tt followed by digits)."""
        if not keyword:
            return False
        return bool(re.match(r'^tt\d{7,}$', keyword.strip()))

    @staticmethod
    def _is_english_keyword(keyword: str) -> bool:
        """Check if keyword is primarily English."""
        if not keyword:
            return False

        cleaned = re.sub(r'[.,!?;:()\[\]{}\s\-_]+', '', keyword)

        if not cleaned:
            return True

        ascii_count = sum(1 for c in cleaned if ord(c) < 128)
        total_count = len(cleaned)

        if total_count == 0:
            return True

        ascii_ratio = ascii_count / total_count

        cjk_count = sum(1 for c in cleaned if '\u4e00' <= c <= '\u9fff' or
                       '\u3040' <= c <= '\u309f' or
                       '\u30a0' <= c <= '\u30ff' or
                       '\uac00' <= c <= '\ud7af')

        if cjk_count > 0 and cjk_count / total_count > 0.3:
            return False

        return ascii_ratio > 0.5

    @staticmethod
    def _format_imdb_id(imdb_id: Any) -> str:
        """Format IMDB ID to standard tt prefix format."""
        try:
            if not imdb_id:
                return ""
            imdb_str = str(imdb_id)
            if not imdb_str.startswith("tt"):
                imdb_str = f"tt{imdb_str}"
            return imdb_str
        except Exception:
            return ""

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """Get plugin configuration form for web UI."""
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                            'hint': '开启后将使用Jackett进行搜索',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                            'hint': '插件将立即同步索引器列表',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'host',
                                            'label': '服务器地址',
                                            'placeholder': 'http://127.0.0.1:9117',
                                            'hint': 'Jackett服务器地址',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'api_key',
                                            'label': 'API密钥',
                                            'placeholder': '',
                                            'hint': '在Jackett界面点击扳手图标获取API密钥',
                                            'persistent-hint': True,
                                            'type': 'password'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '同步周期',
                                            'placeholder': '0 0 */12 * *',
                                            'hint': 'Cron表达式，默认每12小时同步一次索引器',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'proxy',
                                            'label': '使用代理',
                                            'hint': '访问Jackett时使用系统代理',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'border': 'start',
                                            'title': '配置步骤',
                                            'text': '① 填写Jackett服务器地址和API密钥 → ② 保存并启用「立即运行一次」同步索引器 → ③ 在「站点管理」中添加站点（使用插件详情页的domain作为站点地址）→ ④ （可选）上一步新增的站点中填入RSS地址'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'border': 'start',
                                            'title': '获取API密钥',
                                            'text': '打开Jackett Web界面，页面右上角可直接看到API Key输入框，点击旁边的复制按钮即可。'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'success',
                                            'variant': 'tonal',
                                            'border': 'start',
                                            'text': '📖 使用说明：https://github.com/summerdays126/MoviePilot-PluginsV2/blob/main/plugins.v2/jackettindexer/README.md'
                                        }
                                    }
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

    def get_page(self) -> List[dict]:
        """拼装插件详情页面，需要返回页面配置，同时附带数据"""
        status_info = []
        if self._enabled:
            status_info.append('状态：运行中')
        else:
            status_info.append('状态：已停用')

        if self._last_update:
            status_info.append(f'最后同步：{self._last_update.strftime("%Y-%m-%d %H:%M:%S")}')

        status_info.append(f'索引器数量：{len(self._indexers)}')

        header_row = {
            'component': 'VRow',
            'props': {'class': 'font-weight-bold text-caption align-center py-1 px-2'},
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
            if privacy.lower() == "public":
                privacy_text = "公开"
            elif privacy.lower() == "semi-public":
                privacy_text = "半私有"
            else:
                privacy_text = "私有"

            display_name = site.get("name", "Unknown")
            prefix = f"{self.plugin_name}-"
            if display_name.startswith(prefix):
                display_name = display_name[len(prefix):]

            domain = site.get("domain", "N/A")
            rss_url = site.get("rss", "")

            rss_col_content = (
                [{'component': 'a',
                  'props': {'href': rss_url, 'target': '_blank', 'title': rss_url},
                  'text': '复制RSS链接'}]
                if rss_url else
                [{'component': 'span', 'text': '-'}]
            )

            data_rows.append({
                'component': 'VRow',
                'props': {'class': 'text-caption align-center py-1 px-2'},
                'content': [
                    {'component': 'VCol', 'props': {'cols': 5, 'class': 'text-truncate'}, 'content': [{'component': 'span', 'text': display_name}]},
                    {'component': 'VCol', 'props': {'cols': 2}, 'content': [{'component': 'span', 'text': privacy_text}]},
                    {'component': 'VCol', 'props': {'cols': 3, 'class': 'text-truncate'}, 'content': [{'component': 'span', 'text': domain}]},
                    {'component': 'VCol', 'props': {'cols': 2}, 'content': rss_col_content},
                ]
            })

        return [
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'success' if self._enabled else 'info',
                                    'variant': 'tonal',
                                    'text': ' | '.join(status_info)
                                }
                            }
                        ]
                    }
                ]
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {'class': 'pa-0'},
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'props': {'class': 'pa-2'},
                                        'content': [
                                            {
                                                'component': 'div',
                                                'props': {'style': 'max-height:30rem; overflow-y:auto'},
                                                'content': [header_row] + data_rows
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def get_indexers(self) -> List[Dict[str, Any]]:
        """返回插件管理的索引器列表，供系统查询"""
        return self._indexers if self._indexers else []

    def api_search(self, keyword: str, indexer_name: str = None, mtype: str = None, page: int = 0) -> List[Dict[str, Any]]:
        """API搜索端点：搜索种子资源"""
        if not self._enabled:
            return []

        if not keyword:
            return []

        media_type = None
        if mtype:
            if mtype.lower() == "movie":
                media_type = MediaType.MOVIE
            elif mtype.lower() == "tv":
                media_type = MediaType.TV

        results = []

        if indexer_name:
            target_indexer = None
            for indexer in self._indexers:
                domain = indexer.get("domain", "")
                domain_clean = domain.replace("http://", "").replace("https://", "").rstrip("/")
                idx_name = domain_clean.split(".")[-1]
                if idx_name == indexer_name:
                    target_indexer = indexer
                    break

            if target_indexer:
                torrents = self.search_torrents(target_indexer, keyword, media_type, page)
                results.extend(torrents)
        else:
            for indexer in self._indexers:
                try:
                    torrents = self.search_torrents(indexer, keyword, media_type, page)
                    results.extend(torrents)
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】搜索索引器 {indexer.get('name')} 失败：{str(e)}")
                    continue

        return [
            {
                "title": t.title,
                "description": t.description,
                "enclosure": t.enclosure,
                "page_url": t.page_url,
                "size": t.size,
                "seeders": t.seeders,
                "peers": t.peers,
                "pubdate": t.pubdate,
                "imdbid": t.imdbid,
                "downloadvolumefactor": t.downloadvolumefactor,
                "uploadvolumefactor": t.uploadvolumefactor,
                "site_name": t.site_name,
                "grabs": t.grabs,
            }
            for t in results
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        """Get plugin API endpoints."""
        return [
            {
                "path": "/indexers",
                "endpoint": self.get_indexers,
                "methods": ["GET"],
                "summary": "获取索引器列表",
                "description": "返回所有已注册的 Jackett 索引器"
            },
            {
                "path": "/search",
                "endpoint": self.api_search,
                "methods": ["GET"],
                "summary": "搜索种子资源",
                "description": "通过Jackett搜索种子资源。参数：keyword(必填), indexer_name(可选), mtype(可选: movie/tv), page(可选，默认0)"
            }
        ]

    def get_command(self) -> List[Dict[str, Any]]:
        """注册插件远程命令"""
        return [
            {
                "cmd": "/jackett_search",
                "event": EventType.PluginAction,
                "desc": "Jackett搜索",
                "category": "索引器",
                "data": {"action": "jackett_search"}
            },
            {
                "cmd": "/jackett_sites",
                "event": EventType.PluginAction,
                "desc": "Jackett站点列表",
                "category": "索引器",
                "data": {"action": "jackett_sites"}
            }
        ]

    @eventmanager.register(EventType.PluginAction)
    def command_action(self, event: Event):
        """远程命令响应"""
        if not self._enabled:
            return

        event_data = event.event_data
        if not event_data:
            return

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
            self.post_message(
                channel=channel,
                title="❌ Jackett搜索失败",
                text="请提供搜索关键词\n\n"
                     "用法：/jackett_search 关键词 [分类] [索引器名称]\n"
                     "分类：movie 或 tv\n"
                     "示例：/jackett_search The Matrix movie iptorrents",
                userid=user
            )
            return

        parts = args.strip().split()
        if len(parts) < 1:
            self.post_message(
                channel=channel,
                title="❌ Jackett搜索失败",
                text="请提供搜索关键词",
                userid=user
            )
            return

        keyword = parts[0]
        mtype = None
        indexer_name = None

        if len(parts) > 1:
            if parts[1].lower() in ["movie", "tv"]:
                mtype = parts[1].lower()
                if len(parts) > 2:
                    indexer_name = parts[2]
            else:
                indexer_name = parts[1]

        media_type = None
        if mtype:
            media_type = MediaType.MOVIE if mtype == "movie" else MediaType.TV

        search_info = f"关键词：{keyword}"
        if mtype:
            search_info += f"\n分类：{mtype}"
        if indexer_name:
            search_info += f"\n索引器：{indexer_name}"

        self.post_message(
            channel=channel,
            title="🔍 Jackett搜索中...",
            text=search_info,
            userid=user
        )

        try:
            results = self.api_search(keyword=keyword, indexer_name=indexer_name, mtype=mtype, page=0)

            if not results:
                self.post_message(
                    channel=channel,
                    title="📭 未找到结果",
                    text=f"关键词：{keyword}\n未搜索到任何种子",
                    userid=user
                )
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

                result_text += (
                    f"{idx}. {torrent['title']}\n"
                    f"   大小: {size_gb:.2f}GB | "
                    f"做种: {torrent['seeders']} | "
                    f"下载: {torrent['peers']}\n"
                    f"   站点: {torrent['site_name']}\n"
                )

                if promo_str:
                    result_text += f"   促销: {promo_str}\n"

                result_text += "\n"

            self.post_message(
                channel=channel,
                title="✅ Jackett搜索完成",
                text=result_text.strip(),
                userid=user
            )

        except Exception as e:
            logger.error(f"【{self.plugin_name}】远程搜索失败：{str(e)}\n{traceback.format_exc()}")
            self.post_message(
                channel=channel,
                title="❌ Jackett搜索失败",
                text=f"搜索过程中发生错误：{str(e)}",
                userid=user
            )

    def _handle_sites_command(self, channel, source, user):
        """处理站点列表命令"""
        try:
            if not self._indexers:
                self.post_message(
                    channel=channel,
                    title="📋 Jackett站点列表",
                    text="当前没有已注册的索引器\n请先配置并启用插件",
                    userid=user
                )
                return

            total = len(self._indexers)
            private_count = sum(1 for idx in self._indexers
                              if idx.get("privacy", "").lower() not in ["public", "semi-public"])
            semi_private_count = sum(1 for idx in self._indexers
                                    if idx.get("privacy", "").lower() == "semi-public")

            sites_text = f"共 {total} 个索引器（私有:{private_count} | 半私有:{semi_private_count}）\n\n"

            for idx, indexer in enumerate(self._indexers, 1):
                privacy = indexer.get("privacy", "private")
                if privacy.lower() == "public":
                    privacy_icon = "🌐"
                elif privacy.lower() == "semi-public":
                    privacy_icon = "🔓"
                else:
                    privacy_icon = "🔒"

                site_name = indexer.get("name", "Unknown")
                if site_name.startswith(f"{self.plugin_name}-"):
                    site_name = site_name[len(f"{self.plugin_name}-"):]

                sites_text += f"{idx}. {privacy_icon} {site_name}\n"

            self.post_message(
                channel=channel,
                title="📋 Jackett站点列表",
                text=sites_text.strip(),
                userid=user
            )

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取站点列表失败：{str(e)}\n{traceback.format_exc()}")
            self.post_message(
                channel=channel,
                title="❌ 获取站点列表失败",
                text=f"发生错误：{str(e)}",
                userid=user
            )

    def get_agent_tools(self) -> List[Type]:
        """获取插件智能体工具"""
        return [SearchTorrentsTool, ListIndexersTool]
