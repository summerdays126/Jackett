# -*- coding: utf-8 -*-
"""
Agent tools for JackettIndexer plugin (V3.3)
"""

from typing import Optional, Type

from pydantic import BaseModel

from app.agent.tools.base import MoviePilotTool
from app.sdk.plugins import PluginManager

from .schemas import SearchTorrentsToolInput, ListIndexersToolInput


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
        keyword = kwargs.get("keyword", "")
        mtype = kwargs.get("mtype")
        indexer_name = kwargs.get("indexer_name")
        message = f"正在通过Jackett搜索: {keyword}"
        if mtype:
            message += f" (类型: {mtype})"
        if indexer_name:
            message += f" (索引器: {indexer_name})"
        return message

    async def run(self, keyword: str, mtype: str | None = None,
                  indexer_name: str | None = None, **kwargs) -> str:
        try:
            plugins = PluginManager().running_plugins
            plugin_instance = plugins.get("JackettIndexer")
            if not plugin_instance:
                return "❌ JackettIndexer 插件未运行"
            if not plugin_instance._enabled:
                return "❌ JackettIndexer 插件未启用"

            results = plugin_instance.api_search(keyword=keyword, indexer_name=indexer_name, mtype=mtype, page=0)
            if not results:
                return f"📭 未找到结果：关键词 '{keyword}'"

            max_display = 5
            result_lines = [f"✅ 找到 {len(results)} 条结果，显示前 {min(len(results), max_display)} 条：\n"]
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
                result_lines.append(
                    f"{idx}. {torrent['title']}\n   大小: {size_gb:.2f}GB | 做种: {torrent['seeders']} | 下载: {torrent['peers']}\n   站点: {torrent['site_name']}"
                )
                if torrent.get('grabs'):
                    result_lines[-1] += f" | 完成: {torrent['grabs']}"
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
        return "正在获取Jackett索引器列表"

    async def run(self, **kwargs) -> str:
        try:
            plugins = PluginManager().running_plugins
            plugin_instance = plugins.get("JackettIndexer")
            if not plugin_instance:
                return "❌ JackettIndexer 插件未运行"
            if not plugin_instance._enabled:
                return "❌ JackettIndexer 插件未启用"

            indexers = plugin_instance.get_indexers()
            if not indexers:
                return "📋 当前没有已注册的Jackett索引器"

            total = len(indexers)
            private_count = sum(1 for idx in indexers if idx.get("privacy", "").lower() not in ["public", "semi-public"])
            result_lines = [f"📋 **Jackett索引器列表**\n共 {total} 个索引器（私有:{private_count}）\n"]
            for idx, indexer in enumerate(indexers, 1):
                privacy = indexer.get("privacy", "private")
                icon = {"public": "🌐", "semi-public": "🔓"}.get(privacy.lower(), "🔒")
                site_name = indexer.get("name", "Unknown")
                if site_name.startswith("Jackett索引器-"):
                    site_name = site_name[len("Jackett索引器-"):]
                result_lines.append(f"{idx}. {icon} {site_name}")
            return "\n".join(result_lines)
        except Exception as e:
            return f"❌ 获取索引器列表失败: {str(e)}"
