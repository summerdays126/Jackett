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

## V3 适配说明

本版本为 V3 适配版，主要变更：
- 使用稳定 SDK 导入路径（`app.sdk.logging`、`app.sdk.network` 等）
- 移除所有旧版内部路径依赖（`app.core.*`、`app.helper.*` 等）
- 符合 V3 `_PluginBase` 生命周期规范
- 插件版本 `9.9.9`，要求 MoviePilot `>=3.0.0`

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

## V3 vs V2 主要差异

| 项目 | V2 | V3 |
|------|----|----|
| 插件目录 | `plugins.v2/` | `plugins.v3/` |
| 索引文件 | `package.v2.json` | `package.v3.json` |
| 导入路径 | `app.core.*` / `app.helper.*` | `app.sdk.*` / `app.schemas.types` |
| 事件注册 | `app.core.event.eventmanager` | `app.sdk.events.eventmanager` |
| 日志 | `app.log` | `app.sdk.logging.logger` |
| HTTP | `app.utils.http.RequestUtils` | `app.sdk.network.AsyncRequestUtils` |
| 依赖管理 | `requirements.txt` | `pyproject.toml` |
