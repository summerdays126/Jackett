# -*- coding: utf-8 -*-
"""
Schema definitions for JackettIndexer plugin V3
"""

from dataclasses import dataclass
from typing import Optional, Any

from pydantic import BaseModel, Field


# ------------------------------------------------------------------ #
#  TorrentInfo：插件内部数据结构（不经过 API 层）
# ------------------------------------------------------------------ #

@dataclass
class TorrentInfo:
    """
    种子信息数据结构（V3 使用 dataclass 而非链式赋值）

    迁移说明：
    - V2 使用 app.core.context.TorrentInfo（已废弃）
    - V3 插件内建简单 TorrentInfo dataclass，避免依赖宿主内部类型
    """
    title: str = ""
    enclosure: str = ""
    description: str = ""
    size: int = 0
    seeders: int = 0
    peers: int = 0
    page_url: str = ""
    site_name: str = ""
    pubdate: str = ""
    imdbid: str = ""
    downloadvolumefactor: float = 1.0
    uploadvolumefactor: float = 1.0
    grabs: int = 0

    def __post_init__(self):
        """确保数值字段为有效类型"""
        if not isinstance(self.size, int):
            self.size = int(self.size or 0)
        if not isinstance(self.seeders, int):
            self.seeders = int(self.seeders or 0)
        if not isinstance(self.peers, int):
            self.peers = int(self.peers or 0)
        if not isinstance(self.downloadvolumefactor, float):
            self.downloadvolumefactor = float(self.downloadvolumefactor or 1.0)
        if not isinstance(self.uploadvolumefactor, float):
            self.uploadvolumefactor = float(self.uploadvolumefactor or 1.0)
        if not isinstance(self.grabs, int):
            self.grabs = int(self.grabs or 0)

    def to_dict(self) -> dict:
        """
        转换为字典，兼容 MoviePilot 内部 Context.to_dict() 链式调用。
        MoviePilot API 端点（如 site.py:682）调用 torrent.to_dict()，
        必须有此方法否则报 AttributeError。
        """
        return {
            "title": self.title,
            "enclosure": self.enclosure,
            "description": self.description,
            "size": self.size,
            "seeders": self.seeders,
            "peers": self.peers,
            "page_url": self.page_url,
            "site_name": self.site_name,
            "pubdate": self.pubdate,
            "imdbid": self.imdbid,
            "downloadvolumefactor": self.downloadvolumefactor,
            "uploadvolumefactor": self.uploadvolumefactor,
            "grabs": self.grabs,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TorrentInfo":
        """
        从字典创建 TorrentInfo 实例，兼容 MoviePilot 内部 from_dict 调用链。
        MoviePilot download.py:241 调用 torrentinfo.from_dict(torrent_in.model_dump())，
        必须有此类方法否则报 AttributeError。
        """
        return cls(
            title=data.get("title", ""),
            enclosure=data.get("enclosure", ""),
            description=data.get("description", ""),
            size=data.get("size", 0),
            seeders=data.get("seeders", 0),
            peers=data.get("peers", 0),
            page_url=data.get("page_url", ""),
            site_name=data.get("site_name", ""),
            pubdate=data.get("pubdate", ""),
            imdbid=data.get("imdbid", ""),
            downloadvolumefactor=data.get("downloadvolumefactor", 1.0),
            uploadvolumefactor=data.get("uploadvolumefactor", 1.0),
            grabs=data.get("grabs", 0),
        )


# ------------------------------------------------------------------ #
#  API 响应模型：V3 插件必须显式声明 response_model
# ------------------------------------------------------------------ #

class TorrentResultItem(BaseModel):
    """单个种子搜索结果的 API 响应模型"""
    title: str = Field(description="种子标题")
    description: str = Field(description="种子描述/简介")
    enclosure: str = Field(description="下载链接（torrent 文件 URL 或磁力链接）")
    page_url: str = Field(description="种子详情页 URL")
    size: int = Field(description="种子大小，单位字节")
    seeders: int = Field(description="做种人数")
    peers: int = Field(description="下载人数（已减去做种）")
    pubdate: str = Field(description="发布时间，格式 YYYY-MM-DD HH:MM:SS")
    imdbid: str = Field(default="", description="关联的 IMDb ID")
    downloadvolumefactor: float = Field(description="下载倍率因子，0=免费，0.5=50%")
    uploadvolumefactor: float = Field(default=1.0, description="上传倍率因子")
    site_name: str = Field(description="来源站点名称")
    grabs: int = Field(default=0, description="已完成下载次数")


class SearchAPIResponse(BaseModel):
    """搜索 API 的响应模型（直接返回列表，不套 envelope）"""
    results: list[TorrentResultItem] = Field(description="种子搜索结果列表")


class IndexerItem(BaseModel):
    """单个索引器的 API 响应模型"""
    id: str = Field(description="索引器 ID")
    name: str = Field(description="索引器名称")
    domain: str = Field(description="索引器 domain 标识")
    url: str = Field(description="Torznab API 地址")
    rss: str = Field(description="RSS 订阅地址")
    public: bool = Field(description="是否为公开站点")
    privacy: str = Field(description="隐私类型：public/semi-public/private")
    category: dict[str, list[dict[str, Any]]] = Field(default_factory=dict, description="支持的媒体分类，键为 movie/tv，值为分类项列表")


class IndexersAPIResponse(BaseModel):
    """索引器列表 API 的响应模型"""
    indexers: list[IndexerItem] = Field(description="已注册的 Jackett 索引器列表")
