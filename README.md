# MediaSync115

<p align="center">
  <strong>影视搜索、榜单探索、订阅、115 转存、Emby 联动的一体化媒体同步工具</strong>
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

MediaSync115 是一个面向个人媒体库管理的全栈应用，围绕“找片、找资源、转存、订阅、入库同步”构建。

它当前支持：
- TMDB 搜索和探索
- 豆瓣榜单探索
- 115 网盘资源、磁力、ED2K 获取
- 探索页与详情页一键转存
- 电影/剧集订阅与自动扫描
- Emby 已入库标记、缺集判断和全量同步索引
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

### 3. 转存到 115 网盘
- 详情页支持一键转存
- 剧集支持按缺集选集转存
- 探索页支持卡片一键转存
- 支持后台转存队列
- 转存资源默认直存到 115 默认目录

### 4. 订阅与自动扫描
- 支持订阅电影和剧集
- 后台定时扫描订阅内容
- 自动搜索可用资源并执行转存
- 已完成的电影订阅可自动清理
- 已补齐缺集的剧集订阅可自动清理

### 5. Emby 联动
- 卡片和详情页显示 Emby 已入库标记
- 支持剧集缺集判断
- 支持 Emby 媒体库全量同步索引
- 支持定时同步 Emby 数据

## Quick Start

Docker Hub 页面：

```text
https://hub.docker.com/r/wangsy1007/mediasync115
```

当前提供 `latest` 和明确版本号 tag，例如 `1.0.4`；多架构镜像会由 Docker 客户端按宿主机平台自动选择对应版本。

推荐策略：
- 日常部署和 NAS 手动更新用户：使用 `latest`
- 想锁定版本不自动漂移：使用 `1.0.4`

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
  -p 5173:80 \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  wangsy1007/mediasync115:latest
```

如果你确实需要强制指定架构，也可以显式传入 `--platform`：

```bash
docker pull --platform linux/amd64 wangsy1007/mediasync115:latest
docker pull --platform linux/arm64 wangsy1007/mediasync115:latest
```

### 3. 使用 Docker Compose 部署

仓库根目录已经提供官方 [compose.yaml](/Users/wangsy1007/code/MediaSync115/compose.yaml)，默认使用 `latest`，适合 NAS 手动点击更新。你也可以直接使用下面这份配置：

```yaml
services:
  mediasync115:
    image: wangsy1007/mediasync115:latest
    container_name: mediasync115
    restart: unless-stopped
    ports:
      - "5173:80"
    volumes:
      - ./data:/app/data
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://127.0.0.1/healthz', timeout=10)"
        ]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 90s
```

启动：

```bash
docker compose up -d
```

首次启动后，请在设置页补齐必要配置，例如：

- `TMDB_API_KEY`
- `PAN115_COOKIE`
- `EMBY_URL`
- `EMBY_API_KEY`

如果你之前已经把 `backend/.env` 错误创建成目录，不会影响当前 compose 方案；如果你仍需本地 `.env`，先删除目录再重新创建文件：

```bash
rm -rf backend/.env
cp backend/.env.example backend/.env
```

访问地址：
- `http://127.0.0.1:5173`
- `http://127.0.0.1:5173/api/docs`

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
- 端口：`5173 -> 80`
- 卷：宿主机数据目录映射到 `/app/data`
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
- 使用固定版本 tag，例如 `1.0.4`：适合想锁版本的用户，但通常不会收到“新版本可更新”提示

### 4. 升级后数据是否保留

会保留。运行时配置、数据库和缓存都在宿主机挂载目录 `data/` 下，只要这个目录不删，重建容器不会丢数据。

## FAQ

### Docker 已启动，但前端首次可用为什么会慢？
后端启动阶段会执行首页探索预热和部分运行时初始化，健康检查通过前页面不会完全可用。这是当前实现的设计选择。

### 数据丢失后怎么恢复？
核心数据都在 `data/` 下。只要这个目录保留，容器重建后数据库和运行时配置都会继续存在。

### 详情页资源为什么不是自动加载？
当前详情页已经改成手动获取资源，避免页面打开即触发重型请求。
