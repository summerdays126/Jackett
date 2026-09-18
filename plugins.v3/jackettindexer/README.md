# JackettIndexer V3 Plugin

> MoviePilot V3 版本专用，V2 用户请继续使用 `plugins.v2/jackettindexer`

集成 Jackett 索引器搜索，支持 Torznab 协议多站点搜索、RSS 订阅及 Spider 浏览。仅索引私有和半公开站点。

## V3 迁移说明

| 迁移项 | V2 | V3 |
|--------|----|----|
| 导入路径 | `app.log`, `app.core.*`, `app.helper.*`, `app.utils.*` | `app.sdk.logging`, `app.sdk.*`, `app.sdk.utilities`, `app.sdk.network` |
| TorrentInfo | `app.core.context.TorrentInfo` | 本地 `schemas.TorrentInfo` dataclass |
| API 响应 | 依赖宿主隐式包装 | 明确声明 `response_model` |
| 事件处理 | `@eventmanager.register` 实例方法 | 适配 V3 eventmanager |
| Agent Tools | `app.core.plugin.PluginManager` | `app.sdk.plugins.PluginManager` |
| 版本 | 1.7.1 | 2.0.0 |

## 功能特性

- ✅ 多站点统一搜索（通过 Jackett Torznab API）
- ✅ IMDb ID 搜索支持
- ✅ 中文关键词自动英文标题回退补充搜索
- ✅ RSS 订阅支持（Spider 模式）
- ✅ 定时同步索引器列表
- ✅ 私有/半公开站点过滤
- ✅ XXX 站点自动过滤
- ✅ 远程命令 (`/jackett_search`, `/jackett_sites`)
- ✅ Agent 工具集成

## 安装

1. 将 `plugins.v3/jackettindexer/` 目录复制到 MoviePilot V3 的插件目录
2. 或通过 MoviePilot 插件市场安装
3. 在插件配置页填写 Jackett 服务器地址和 API 密钥
4. 启用「立即运行一次」同步索引器

## 配置说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| 服务器地址 | Jackett 服务地址，如 `http://127.0.0.1:9117` | - |
| API 密钥 | Jackett Web 界面右上角获取 | - |
| 同步周期 | Cron 表达式 | `0 0 */12 * *`（每12小时） |
| 使用代理 | 访问 Jackett 时是否使用系统代理 | 否 |

## 使用方法

### 远程命令

```
/jackett_search The Matrix
/jackett_search The Matrix movie
/jackett_search tt0133093
/jackett_sites
```

### API 端点

```
GET /api/v1/plugin/JackettIndexer/indexers  # 获取索引器列表
GET /api/v1/plugin/JackettIndexer/search?keyword=xxx&mtype=movie&page=0  # 搜索种子
```

## 许可证

MIT
