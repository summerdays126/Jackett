# JackettIndexer V3

MoviePilot V3 插件，集成 Jackett 索引器搜索功能。

## 功能

- 支持 Jackett Torznab API 多站点搜索
- 自动同步 Jackett 已配置的索引器
- 支持电影/剧集分类过滤
- 支持 IMDb ID 精准搜索
- 中文关键词自动回退英文标题搜索
- 支持站点 RSS 订阅
- 支持 Agent 工具调用
- **不过滤任何类型的站点（公开/半公开/私有/XXX）**

## 版本历史

| 版本 | 说明 |
|------|------|
| v3.3.0 | 全面迁移到 app.sdk.* 稳定 SDK 导入路径；取消所有旧路径依赖 |
| v3.2.0 | 修复 AsyncRequestUtils 同步调用崩溃；取消过滤公开站点；取消过滤 XXX 站点 |
| v3.1.0 | 修复 AsyncRequestUtils 同步调用崩溃 |
| v9.9.9 | Summer&Openclaw V3 适配版 |

## 安装

### 方式一：从 GitHub 个人仓库安装（推荐）

在 MoviePilot 插件市场 → 设置 → 添加插件源：

```
https://github.com/<你的用户名>/<你的仓库名>/raw/main/package.v3.json
```

### 方式二：本地安装

将 `plugins.v3/jackettindexer/` 目录复制到 MoviePilot 的 `plugins.v3/` 目录。

## 配置

1. 填写 Jackett 服务器地址（如 `http://127.0.0.1:9117`）
2. 填写 Jackett API 密钥（在 Jackett WebUI 右上角复制）
3. 启用「立即运行一次」同步索引器
4. 在 MoviePilot 站点管理中查看已注册的索引器

## V3 SDK 导入路径

| 能力 | V3 稳定导入 |
|------|-------------|
| 日志 | `app.sdk.logging` |
| 事件 | `app.sdk.events` |
| HTTP / 站点 | `app.sdk.network` |
| 媒体上下文 | `app.sdk.media` |
| 字符串工具 | `app.sdk.string` |
| 插件管理 | `app.sdk.plugins` |
