# -*- coding: utf-8 -*-
"""
Agent tools for JackettIndexer plugin V3

V3 迁移说明：
- MoviePilotTool 基类路径仍为 app.agent.tools.base（已在稳定 SDK 列表中）
- PluginManager 改为从 app.sdk.plugins 导入
- schemas 使用插件本地的 TorrentInfo 定义
"""

from typing import Optional, Type

from pydantic import BaseModel, Field

from app.agent.tools.base import MoviePilotTool
from app.sdk.plugins import PluginManager


class SearchTorrentsToolInput(BaseModel):
    """搜索种子工具输入参数"""
    keyword: str = Field(
        ...,
        description="搜索关键词或IMDb ID (如 'The Matrix' 或 'tt0133093')"
    )
    mtype: str | None = Field(
        default=None,
        description="媒体类型过滤：'movie' 或 'tv'，留空则搜索两者"
    )
    indexer_name: str | None = Field(
        default=None,
        description="指定 Jackett 索引器名称，留空则搜索所有索引器"
    )


class ListIndexersToolInput(BaseModel):
    """列出索引器工具输入参数"""
    pass


class SearchTorrentsTool(MoviePilotTool):
    """Jackett搜索种子工具"""

    name: str = "jackett_search_torrents"
    description: str = (
        "Search for torrents across all Jackett indexers. "
        "Use this when the user wants to find movies or TV shows torrents. "
        "Supports keyword search and IMDb ID search (format: tt1234567). "
        "Can filter by media type (movie/tv) and specific indexer."
    )
    args_schema: Type[BaseModel] = SearchTorrentsToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        """根据参数生成友好的提示消息"""
        keyword = kwargs.get("keyword", "")
        mtype = kwargs.get("mtype")
        indexer_name = kwargs.get("indexer_name")

        message = f"正在通过Jackett搜索: {keyword}"
        if mtype:
            message += f" (类型: {mtype})"
        if indexer_name:
            message += f" (索引器: {indexer_name})"

        return message

    async def run(
        self,
        keyword: str,
        mtype: str | None = None,
        indexer_name: str | None = None,
        **kwargs
    ) -> str:
        """
        执行种子搜索

        Args:
            keyword: 搜索关键词或IMDb ID
            mtype: 媒体类型 (movie/tv)
            indexer_name: 指定索引器名称
            **kwargs: 其他参数

        Returns:
            搜索结果的格式化字符串
        """
        try:
            # 获取插件实例
            plugins = PluginManager().running_plugins
            plugin_instance = plugins.get("JackettIndexer")

            if not plugin_instance:
                return "❌ JackettIndexer 插件未运行"

            if not plugin_instance._enabled:
                return "❌ JackettIndexer 插件未启用"

            # 调用插件的搜索API
            # api_search 返回 SearchAPIResponse (Pydantic model)；
            # HTTP 调用由框架序列化为 JSON，直接 Python 调用需取 .results
            response = plugin_instance.api_search(
                keyword=keyword,
                indexer_name=indexer_name,
                mtype=mtype,
                page=0
            )
            results_list = response.results if hasattr(response, "results") else []

            if not results_list:
                return f"📭 未找到结果：关键词 '{keyword}'"

            # 格式化结果（显示前5条）
            max_display = 5
            result_lines = [
                f"✅ 找到 {len(results_list)} 条结果，显示前 {min(len(results_list), max_display)} 条：\n"
            ]

            for idx, torrent in enumerate(results_list[:max_display], 1):
                # TorrentResultItem 是 Pydantic 模型，转为 dict 统一访问
                t = torrent.model_dump() if hasattr(torrent, "model_dump") else torrent
                # 格式化大小
                size_gb = t.get("size", 0) / (1024**3) if t.get("size", 0) > 0 else 0

                # 促销标志
                promo = []
                df = t.get("downloadvolumefactor", 1.0)
                if df == 0.0:
                    promo.append("🆓")
                elif df == 0.5:
                    promo.append("50%")
                if t.get("uploadvolumefactor", 1.0) == 2.0:
                    promo.append("2xUp")
                promo_str = " ".join(promo) if promo else ""

                line = (
                    f"{idx}. {t.get('title', '')}\n"
                    f"   大小: {size_gb:.2f}GB | 做种: {t.get('seeders', 0)} | 下载: {t.get('peers', 0)}\n"
                    f"   站点: {t.get('site_name', '')}"
                )
                if t.get("grabs"):
                    line += f" | 完成: {t.get('grabs')}"
                result_lines.append(line)

                if promo_str:
                    result_lines.append(f"   促销: {promo_str}")

                result_lines.append("")

            return "\n".join(result_lines)

        except Exception as e:
            return f"❌ 搜索失败: {str(e)}"


class ListIndexersTool(MoviePilotTool):
    """Jackett索引器列表工具"""

    name: str = "jackett_list_indexers"
    description: str = (
        "List all available Jackett indexers. "
        "Use this when the user wants to know which indexers are registered and available for searching."
    )
    args_schema: Type[BaseModel] = ListIndexersToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        """根据参数生成友好的提示消息"""
        return "正在获取Jackett索引器列表"

    async def run(self, **kwargs) -> str:
        """
        获取索引器列表

        Returns:
            索引器列表的格式化字符串
        """
        try:
            # 获取插件实例
            plugins = PluginManager().running_plugins
            plugin_instance = plugins.get("JackettIndexer")

            if not plugin_instance:
                return "❌ JackettIndexer 插件未运行"

            if not plugin_instance._enabled:
                return "❌ JackettIndexer 插件未启用"

            # 获取索引器列表
            # get_indexers 返回 IndexersAPIResponse (Pydantic model)；
            # HTTP 调用由框架序列化为 JSON，直接 Python 调用需取 .indexers
            response = plugin_instance.get_indexers()
            indexers_list = response.indexers if hasattr(response, "indexers") else []

            if not indexers_list:
                return "📋 当前没有已注册的Jackett索引器"

            # 统计信息
            total = len(indexers_list)
            private_count = sum(
                1 for idx in indexers_list
                if idx.get("privacy", "").lower() not in ["public", "semi-public"]
            )
            semi_private_count = sum(
                1 for idx in indexers_list
                if idx.get("privacy", "").lower() == "semi-public"
            )

            # 构建列表
            result_lines = [
                f"📋 **Jackett索引器列表**",
                f"共 {total} 个索引器（私有:{private_count} | 半私有:{semi_private_count}）\n"
            ]

            for idx, indexer in enumerate(indexers_list, 1):
                # IndexerItem 是 Pydantic 模型，转为 dict 统一访问
                item = indexer.model_dump() if hasattr(indexer, "model_dump") else indexer
                # 隐私类型标识
                privacy = item.get("privacy", "private")
                if privacy.lower() == "public":
                    privacy_icon = "🌐"
                elif privacy.lower() == "semi-public":
                    privacy_icon = "🔓"
                else:
                    privacy_icon = "🔒"

                # 站点名称（去掉插件前缀）
                site_name = item.get("name", "Unknown")
                plugin_prefix = "Jackett索引器-"
                if site_name.startswith(plugin_prefix):
                    site_name = site_name[len(plugin_prefix):]

                # 提取索引器名称
                domain = item.get("domain", "")
                indexer_name = domain.split(".")[-1] if domain else "N/A"

                result_lines.append(f"{idx}. {privacy_icon} {site_name} ({indexer_name})")

            return "\n".join(result_lines)

        except Exception as e:
            return f"❌ 获取索引器列表失败: {str(e)}"
