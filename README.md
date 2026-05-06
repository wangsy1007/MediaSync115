# MediaSync115

<p align="center">
  <strong>影视搜索、榜单探索、订阅、115 转存、自动归档、STRM 生成、Emby 代理 302 播放的一体化媒体同步工具</strong>
</p>

<p align="center">
  <img alt="Vue 3" src="https://img.shields.io/badge/Vue-3-42b883?style=for-the-badge&logo=vue.js&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/SQLite-3-003b57?style=for-the-badge&logo=sqlite&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-Compose-2496ed?style=for-the-badge&logo=docker&logoColor=white">
  <img alt="Playwright" src="https://img.shields.io/badge/Tested%20with-Playwright-2ead33?style=for-the-badge&logo=playwright&logoColor=white">
</p>

tg群：https://t.me/+EkEBz7x7i9NlYzFl

tg群的二维码：

<img width="300" height="300" alt="image" src="https://github.com/user-attachments/assets/19c930cc-3a3a-4ba4-b2bb-b9703982efce" />


## Overview

MediaSync115 是一个面向个人媒体库管理的全栈应用，围绕"找片、找资源、转存、订阅、入库同步"构建。

它当前支持：
- TMDB 搜索和探索
- 豆瓣榜单探索
- 115 网盘资源、磁力、ED2K 获取
- 探索页与详情页一键转存
- 电影/剧集订阅与自动扫描
- 转存后自动归档与 STRM 生成
- Emby 已入库标记、缺集判断和全量同步索引
- **Emby 代理 302 播放**（端口 8099）
- **飞牛影视集成**（已入库标记、缺集判断）
- **资源画质筛选**（分辨率/编码/HDR/音频/字幕/排除标签/体积范围）
- **剧集季/集粒度订阅**（指定季、集段、只追新集、含特别篇）
- **订阅状态细化**（匹配中/转存中/离线已提交/归档中等多阶段追踪）
- TG Bot 搜索、订阅、通知
- 可选 Kafka 埋点统计能力
- 日志、调度、运行时设置、健康检查

## What It Does

### 1. 搜索影视内容
- 搜索电影和剧集
- 查看电影详情、剧集详情、豆瓣详情
- 从 TMDB 和豆瓣榜单探索热门内容

### 2. 获取多种资源
- 获取 115 网盘分享资源
- 获取磁力链接
- 获取 ED2K 链接
- 支持 Pansou、HDHive、Telegram、SeedHub、不太灵
- **支持资源画质筛选**：按分辨率、编码、HDR、音频语言、字幕等维度自动排序过滤

### 3. 转存到 115 网盘
- 详情页支持一键转存
- 剧集支持按缺集选集转存
- 探索页支持卡片一键转存
- 支持后台转存队列
- 转存资源默认直存到 115 默认目录
- 手动转存、订阅自动转存、工作流转存统一走"转存 -> 归档 -> STRM"链路

### 4. 订阅与自动扫描
- 支持订阅电影和剧集
- **剧集支持季/集粒度**：全剧追踪、指定季、指定集段，以及「只追新集」模式
- **订阅设置面板**（电影+剧集通用）：配置画质偏好（分辨率/编码/HDR/音频语言/字幕/排除标签/体积范围）
- 后台定时扫描订阅内容（HDHive / Pansou / TG / 离线磁力多来源链路）
- 自动搜索可用资源并执行转存
- 已完成的电影/剧集订阅可自动清理

### 5. 自动归档与 STRM
- 支持将待整理目录中的影视自动归档到 115 输出目录
- 支持在归档完成后自动生成 `.strm` 文件
- 支持离线下载完成后自动触发归档和后续 STRM 生成
- 生成的 STRM 可直接供 Emby、飞牛影视和支持 HTTP STRM 的播放器使用

### 6. Emby 联动 & 代理 302 播放
- 卡片和详情页显示 Emby 已入库标记
- 支持剧集缺集判断（含飞牛影视合并查询）
- 支持 Emby 媒体库全量同步索引
- 支持定时同步 Emby 数据
- **Emby 代理端口 8099**：Emby 客户端连接代理端口，STRM 播放自动 302 跳转到 115 CDN 直连播放，无需经过服务器中转

### 7. 飞牛影视集成
- 卡片和详情页显示飞牛已入库标记
- 剧集缺集判断同时查询 Emby + 飞牛，合并结果
- 支持飞牛媒体库全量同步索引

### 8. Telegram Bot 与通知
- 支持 TG Bot 搜索电影和剧集
- 支持在 TG Bot 中查看详情、搜索资源、发起转存和添加订阅
- TG Bot 影视消息支持海报预览
- 订阅转存成功通知支持海报预览

### 9. 可选 Analytics 埋点
- 支持通过 Kafka 发送搜索、订阅、转存等事件
- 未配置 Kafka 时自动禁用，不影响主业务流程

## Quick Start

Docker Hub 页面：

```text
https://hub.docker.com/r/wangsy1007/mediasync115
```

当前提供 `latest` 和明确版本号 tag，例如 `1.1.8`；多架构镜像支持 linux/amd64 和 linux/arm64，Docker 客户端会按宿主机平台自动选择对应版本。

推荐策略：
- 日常部署和 NAS 手动更新用户：使用 `latest`
- 想锁定版本不自动漂移：使用 `1.1.8`

### 1. 准备数据目录

```bash
mkdir -p data
```

注意：
- `docker compose` 部署时不需要预先创建 `backend/.env`
- 首次启动后可直接进入设置页填写必要参数，配置会持久化到 `data/runtime_settings.json`
- 如果你习惯本地开发用 `.env`，应用仍然兼容读取 `backend/.env`

### 2. 使用 docker run 部署

```bash
docker pull wangsy1007/mediasync115:latest

docker run -d \
  --name mediasync115 \
  -p 5173:5173 \
  -p 9008:9008 \
  -p 8099:8099 \
  -e EMBY_PROXY_HOST=your-emby-host \
  -e EMBY_PROXY_PORT=8096 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/strm:/app/strm \
  --restart unless-stopped \
  wangsy1007/mediasync115:latest
```

- `8099`：Emby 代理端口（可选，启用后 Emby 客户端连接此端口实现 302 直连播放）
- `EMBY_PROXY_HOST`：真实 Emby 服务器的地址（默认 `host.docker.internal`）
- `EMBY_PROXY_PORT`：真实 Emby 服务器的端口（默认 `8096`）

如果你要使用 STRM 生成功能，建议把宿主机目录挂载到容器内固定路径 `/app/strm`，然后在设置页把 `STRM 输出目录` 填成 `/app/strm`。

如果你确实需要强制指定架构，也可以显式传入 `--platform`：

```bash
docker pull --platform linux/amd64 wangsy1007/mediasync115:latest
docker pull --platform linux/arm64 wangsy1007/mediasync115:latest
```

### 3. 使用 Docker Compose 部署

仓库根目录已经提供官方 [`compose.yaml`](./compose.yaml)，默认使用 `latest`，适合 NAS 手动点击更新。你也可以直接使用下面这份配置：

```yaml
services:
  mediasync115:
    image: wangsy1007/mediasync115:latest
    container_name: mediasync115
    restart: unless-stopped
    ports:
      - "5173:5173"
      - "9008:9008"
      - "8099:8099"
    environment:
      TZ: Asia/Shanghai
      EMBY_PROXY_HOST: ${EMBY_PROXY_HOST:-host.docker.internal}
      EMBY_PROXY_PORT: ${EMBY_PROXY_PORT:-8096}
    volumes:
      - ./data:/app/data
      - ${STRM_HOST_DIR:-./strm}:/app/strm
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5173/healthz', timeout=10)"
        ]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
```

启动：

```bash
docker compose up -d
```

如果你想把 STRM 输出到宿主机其他目录，可以在仓库根目录创建 `.env`，例如：

```bash
STRM_HOST_DIR=/Volumes/Media/strm
```

然后重新执行：

```bash
docker compose up -d --build
```

设置页中请把 `STRM 输出目录` 固定填写为 `/app/strm`。

首次启动后，请在设置页补齐必要配置，例如：

- `TMDB_API_KEY`
- `PAN115_COOKIE`
- `EMBY_URL`

访问地址：
- `http://127.0.0.1:9008` — 前端 UI + 后端 API
- `http://127.0.0.1:8099` — Emby 代理（Emby 客户端连接此端口）
- `http://127.0.0.1:9008/api/docs` — API 文档

## NAS Manual Update

推荐在 NAS 上使用 `wangsy1007/mediasync115:latest` 部署。这样当 Docker Hub 上的 `latest` 更新后，很多 NAS 的 Docker 管理界面都能识别到“有可更新镜像”，用户只需要手动点击更新即可。

前提：
- 镜像 tag 使用 `latest`
- 数据目录映射到宿主机，例如 `./data:/app/data`
- 不要把数据库和运行时配置写在容器内部

### 1. 首次部署

如果 NAS 支持导入 compose 文件，直接使用仓库自带的 `compose.yaml`。

如果 NAS 只支持填写镜像参数，请保持等效配置：
- 镜像：`wangsy1007/mediasync115:latest`
- 端口：`5173`（前端 UI）、`9008`（STRM 播放）、`8099`（Emby 代理）
- 卷：宿主机数据目录映射到 `/app/data`
- 可选：宿主机 STRM 目录映射到 `/app/strm`
- 重启策略：`unless-stopped`

### 2. 用户手动更新

当 NAS 提示 `latest` 有新版本时，用户只需要：
- 点击“拉取更新”或“重新部署”
- 等待容器重建完成
- 保持原来的数据目录挂载不变

如果是命令行更新，等效操作是：

```bash
docker compose pull
docker compose up -d
```

### 3. 版本选择建议

- 使用 `latest`：适合绝大多数 NAS 用户，能更容易被平台识别到有更新
- 使用固定版本 tag，例如 `1.1.8`：适合想锁版本的用户，但通常不会收到“新版本可更新”提示

## Changelog

`1.1.8` 重点更新：
- 新增 **Emby 代理 302 播放**（端口 8099），Emby 客户端连接代理端口即可实现 115 直连播放
- 新增 **资源画质筛选**：按分辨率/编码/HDR/音频语言/字幕/排除标签/体积范围智能过滤
- 新增 **剧集季/集粒度订阅**：支持全剧/指定季/指定集段追踪 + 只追新集模式
- 新增 **飞牛影视集成**：已入库标记、缺集判断、全量同步索引
- 优化移动端搜索结果海报卡片布局和侧边栏文字显示
- SQLite 启用 WAL 模式 + 连接超时，解决高并发订阅检查时数据库锁问题
- 订阅状态模型细化（匹配中/转存中/离线已提交/归档中等多阶段追踪）
- 首页推荐列表移除两侧黑色渐变遮罩

`1.1.3` 重点更新：
- 影视探索首页海报骨架屏改为按容器宽度动态显示数量

`1.1.2` 重点更新：
- 探索页首屏优先返回豆瓣列表，TMDB 匹配改后台异步回填
- 探索页真实 502 不再误提示为"后端启动中"
- 容器启动日志新增前后端成功提示，并延长健康检查启动宽限时间

`1.1.1` 重点更新：
- 新增 Kafka 埋点统计支持（可选启用）
- 提升订阅定时调度稳定性与并发保护
- 优化容器启动阶段前端 502 体验
- TG Bot 影视消息新增海报预览
- 转存后自动归档并在归档完成后自动生成 STRM

完整更新日志见 [`CHANGELOG.md`](./CHANGELOG.md)。

### 4. 升级后数据是否保留

会保留。运行时配置、数据库和缓存都在宿主机挂载目录 `data/` 下，只要这个目录不删，重建容器不会丢数据。

## FAQ

### Docker 已启动，但前端首次可用为什么会慢？
后端启动阶段会执行首页探索预热和部分运行时初始化，健康检查通过前页面不会完全可用。这是当前实现的设计选择。

### 数据丢失后怎么恢复？
核心数据都在 `data/` 下。只要这个目录保留，容器重建后数据库和运行时配置都会继续存在。

### 详情页资源为什么不是自动加载？
当前详情页已经改成手动获取资源，避免页面打开即触发重型请求。
