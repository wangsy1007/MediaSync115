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
- 支持 Nullbr、Pansou、HDHive、Telegram、SeedHub

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

### 1. 准备配置文件

```bash
mkdir -p backend/data
```

注意：
- `docker compose` 部署时不再需要预先创建 `backend/.env`。
- 首次启动后可直接进入设置页填写必要参数，配置会持久化到 `backend/data/runtime_settings.json`。
- 如果你习惯本地开发用 `.env`，应用仍然兼容读取 `backend/.env`。

### 2. 使用 docker run 部署

```bash
docker pull wangsy1007/mediasync115:latest

docker run -d \
  --name mediasync115 \
  -p 5173:80 \
  -v $(pwd)/backend/data:/app/data \
  --restart unless-stopped \
  wangsy1007/mediasync115:latest
```

### 3. 使用 docker compose 部署

```yaml
services:
  app:
    image: wangsy1007/mediasync115:latest
    container_name: mediasync115
    restart: unless-stopped
    working_dir: /app
    ports:
      - "5173:80"
    volumes:
      - ./backend/data:/app/data
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
      start_period: 30s
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

## FAQ

### Docker 已启动，但前端首次可用为什么会慢？
后端启动阶段会执行首页探索预热和部分运行时初始化，健康检查通过前页面不会完全可用。这是当前实现的设计选择。

### 数据丢失后怎么恢复？
核心数据都在 `backend/data/` 下。只要这个目录保留，容器重建后数据库和运行时配置都会继续存在。

### 详情页 Nullbr 为什么不是自动加载？
当前详情页已经改成手动获取 Nullbr 资源，避免页面打开即触发重型请求。
