# JackettIndexer for MoviePilot V3

集成 Jackett 索引器到 MoviePilot V3，支持 Torznab 协议多站点搜索。

## 功能特性

- ✅ **Torznab 协议支持**：通过 Jackett API 获取所有已配置索引器的搜索结果
- ✅ **全局搜索**：`site={}` 空字典时自动遍历所有已配置 Jackett 索引器
- ✅ **指定索引器搜索**：支持按索引器名称精确搜索
- ✅ **RSS 订阅**：定时同步各索引器最新种子
- ✅ **中文回退**：关键词自动转换为英文搜索（Jackett 对英文支持更好）
- ✅ **Agent Tools**：支持 AI Agent 通过自然语言搜索
- ✅ **MoviePilot V3 兼容**：适配 V3 SDK API

## 支持的索引器

1337x, AniRena, AudioBook Bay, Bangumi Moe, BT.etree, EBookBay, E-Hentai, EZTV, LimeTorrents, Nyaa.si, The Pirate Bay, TheRARBG, Tokyo Toshokan, YTS 等（所有在 Jackett 中配置为私有/半公开的索引器）

## 安装

### 方式一：MoviePilot 市场（推荐）

1. 在 MoviePilot → 插件管理 → 市场 中搜索 `JackettIndexer`
2. 点击安装

### 方式二：本地安装

1. 下载最新 ZIP 包
2. MoviePilot → 插件管理 → 本地插件安装 → 上传 ZIP

## 配置

1. 安装后在插件设置中填写：
   - **Jackett 地址**：`http://192.168.x.x:9117`（Jackett 的 HTTP 地址）
   - **API Key**：Jackett 设置页面中的 API Key
2. 保存后插件会自动获取 Jackett 中已配置的索引器

## 开发

```text
MoviePilot-Plugins-JackettIndexer/
├── plugins.v3/
│   └── jackettindexer/
│       ├── __init__.py      # 主插件代码
│       ├── schemas.py       # Pydantic 数据模型
│       ├── agenttool.py     # Agent 工具
│       ├── README.md        # 插件说明
│       └── icons/
│           └── Jackett_A.png
├── package.v3.json          # V3 市场索引
└── package.v2.json          # V2 已废弃标记
```

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 2.0.0 | 2026-09-19 | V3 重构，修复全局搜索 Bug |
| 1.7.1 | 2026-01-01 | V2 最后一个版本 |

## 许可证

MIT
