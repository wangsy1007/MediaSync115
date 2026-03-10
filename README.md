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

MediaSync115 是一个全栈影视资源管理项目，围绕“找资源、转存资源、订阅资源、同步媒体库”四条主链路构建。

它当前支持：
- TMDB 搜索和探索
- 豆瓣榜单探索
- 115 网盘资源、磁力、ED2K 获取
- 探索页与详情页一键转存
- 电影/剧集订阅与自动扫描
- Emby 已入库标记、缺集判断和全量同步索引
- 日志、调度、运行时设置、健康检查

## What It Does

MediaSync115 面向个人媒体库管理，核心目标是把“找片、找资源、转存、订阅、入库同步”串成一套完整流程。

### 1. 搜索影视内容
- 搜索电影和剧集
- 查看电影详情、剧集详情、豆瓣详情
- 从 TMDB 和豆瓣榜单探索热门内容

### 2. 获取多种资源
- 获取 115 网盘分享资源
- 获取磁力链接
- 获取 ED2K 链接
- 支持多种资源来源：
  - Nullbr
  - Pansou
  - HDHive
  - Telegram
  - SeedHub

### 3. 转存到 115 网盘
- 详情页支持一键转存
- 剧集支持按缺集选集转存
- 探索页支持卡片一键转存
- 支持后台转存队列，连续点击会自动排队执行
- 转存资源默认直存到 115 默认目录
- HDHive 资源支持积分解锁后继续转存

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
- 支持定时同步 Emby 数据，用于回填入库状态和缺集信息

### 6. 系统管理能力
- 查看任务日志和操作日志
- 查看下载记录
- 查看调度任务
- 通过设置页统一管理：
  - TMDB
  - 115
  - Nullbr
  - HDHive
  - Telegram
  - Emby

### 7. Docker 一键部署
- 支持 all-in-one 单镜像一键部署
- 支持 Docker Compose 一键启动前后端
- 单镜像和双镜像都通过 Nginx 统一反代后端 API
- 运行数据持久化到本地目录
- 支持容器健康检查

## Features

### 搜索与探索
- TMDB 搜索电影和剧集
- 豆瓣探索首页与更多榜单页
- TMDB 探索首页与更多榜单页
- 详情页支持多资源来源切换

### 资源获取
- 115 网盘资源
- 磁力链接
- ED2K 链接
- 资源来源支持 Nullbr、Pansou、HDHive、Telegram、SeedHub

### 转存与下载
- 详情页一键转存
- 剧集选集转存
- 探索页转存队列
- 115 直存默认目录
- HDHive 积分解锁确认流程

### 订阅自动化
- 电影和剧集订阅
- 后台订阅扫描
- 自动搜索资源与转存
- 已完成订阅自动清理

### Emby 联动
- 影视卡片和详情页已入库对号
- 剧集缺集判断
- Emby 全量同步索引
- 定时同步和手动同步

### 运维能力
- FastAPI 健康检查
- 调度任务管理
- 操作日志与任务日志
- Docker Compose 部署
- Playwright 前端冒烟测试

## Tech Stack

### Frontend
- Vue 3
- Vite
- Element Plus
- Pinia
- Axios
- SCSS

### Backend
- FastAPI
- SQLAlchemy 2.0
- SQLite + aiosqlite
- Pydantic 2
- APScheduler

### Deployment
- Docker
- Docker Compose
- Nginx

## Quick Start

### 1. Clone

```bash
git clone <your-repo-url>
cd MediaSync115
```

### 2. Prepare backend env

```bash
cp backend/.env.example backend/.env
```

至少需要按你的环境填写这些配置：
- `NULLBR_APP_ID`
- `NULLBR_API_KEY`
- `TMDB_API_KEY`
- `PAN115_COOKIE`
- `EMBY_URL`
- `EMBY_API_KEY`

### 3. Start with all-in-one Docker Compose

```bash
docker compose -f docker-compose.single.yml up --build -d
```

### 4. Open the app

- Frontend: `http://127.0.0.1:5173`
- API Docs: `http://127.0.0.1:5173/api/docs`

查看状态：

```bash
docker compose -f docker-compose.single.yml ps
docker compose -f docker-compose.single.yml logs -f
```

停止服务：

```bash
docker compose -f docker-compose.single.yml down
```

## Docker Deployment

项目现在同时提供两套 Docker 形态：
- `All-in-one` 单镜像：适合最终用户部署
- `Split` 双镜像：适合开发和调试

### Option 1: All-in-one image from Docker Hub

Docker Hub 页面：

```text
https://hub.docker.com/r/wangsy1007/mediasync115
```

镜像名：

```bash
wangsy1007/mediasync115:latest
```

拉取镜像：

```bash
docker pull wangsy1007/mediasync115:latest
```

#### Run with docker run

```bash
docker run -d \
  --name mediasync115 \
  -p 5173:80 \
  -v $(pwd)/backend/data:/app/data \
  -v $(pwd)/backend/.env:/app/.env:ro \
  --restart unless-stopped \
  wangsy1007/mediasync115:latest
```

#### Run with single-service compose

```bash
docker compose -f docker-compose.single.yml up -d
```

`docker-compose.single.yml` 内容：

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
      - ./backend/.env:/app/.env:ro
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

### Option 2: Build the all-in-one image locally

```bash
docker build -t wangsy1007/mediasync115:latest .
```

### Option 3: Existing split frontend/backend compose

```bash
docker compose up --build -d
```

这套模式保留给开发和排障使用：
- `backend`: FastAPI 服务
- `frontend`: Nginx 静态前端 + `/api` 反代后端

### Persistent data
- `./backend/data:/app/data`

### Mounted config
- `./backend/.env:/app/.env:ro`

### Exposed ports
- `5173:80` for all-in-one image
- `5173:80` for split frontend service

说明：
- 单镜像内部运行 `Nginx + Uvicorn`
- 对外只暴露一个端口，浏览器统一访问 `5173`
- 双镜像 Compose 默认不直接暴露后端 `8000` 到宿主机
- 若你需要宿主机直接访问后端，可自行在 `docker-compose.yml` 中添加端口映射

### Common Docker commands

```bash
docker build -t wangsy1007/mediasync115:latest .
docker run -d --name mediasync115 -p 5173:80 -v $(pwd)/backend/data:/app/data -v $(pwd)/backend/.env:/app/.env:ro --restart unless-stopped wangsy1007/mediasync115:latest
docker compose -f docker-compose.single.yml up --build -d
docker compose -f docker-compose.single.yml ps
docker compose -f docker-compose.single.yml logs -f
docker compose -f docker-compose.single.yml down

docker compose up --build -d
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose down
```

## Local Development

### Start with helper script

推荐直接使用项目脚本：

```bash
./dev-linux.sh start
./dev-linux.sh restart
./dev-linux.sh status
./dev-linux.sh logs
./dev-linux.sh stop
```

### Start backend manually

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

### Start frontend manually

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

### Local URLs
- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`
- API Docs: `http://127.0.0.1:8000/docs`

## Configuration

后端环境变量模板见：
- [backend/.env.example](/mnt/d/code/MediaSync115/backend/.env.example)

### Required
- `NULLBR_APP_ID`
- `NULLBR_API_KEY`
- `TMDB_API_KEY`
- `PAN115_COOKIE`

### Common optional
- `PANSOU_BASE_URL`
- `HDHIVE_COOKIE`
- `HDHIVE_BASE_URL`
- `TG_API_ID`
- `TG_API_HASH`
- `TG_PHONE`
- `TG_PROXY`
- `TG_CHANNEL_USERNAMES`
- `EMBY_URL`
- `EMBY_API_KEY`
- `HTTP_PROXY`
- `HTTPS_PROXY`
- `ALL_PROXY`
- `SOCKS_PROXY`

### Default database

```text
backend/data/mediasync.db
```

### Runtime settings file

```text
backend/data/runtime_settings.json
```

## Testing

### Frontend build

```bash
cd frontend
npm run build
```

### Frontend smoke tests

```bash
cd frontend
npm run test:smoke
npm run test:smoke:headed
```

当前 Playwright 冒烟覆盖：
- 豆瓣探索首页
- 更多榜单页
- 电影详情页
- 剧集详情页
- 豆瓣详情页

如首次运行缺少浏览器依赖：

```bash
cd frontend
npx playwright install chromium
npx playwright install-deps chromium
```

### Backend tests

```bash
cd backend
pytest tests
```

### Live smoke test

```bash
python3 backend/tests/run_live_subscription_transfer_smoke.py
```

这个脚本会联调真实运行中的服务，重点覆盖：
- 订阅队列
- 转存队列
- 剧集串行转存

## Application Routes

- `/explore/douban`: 豆瓣探索首页
- `/explore/tmdb`: TMDB 探索首页
- `/explore/:source/section/:key`: 更多榜单页
- `/movie/:id`: 电影详情页
- `/tv/:id`: 剧集详情页
- `/douban/:mediaType/:id`: 豆瓣详情页
- `/subscriptions`: 订阅列表
- `/downloads`: 下载列表
- `/logs`: 日志页
- `/settings`: 设置页
- `/scheduler`: 调度页

## Project Structure

```text
MediaSync115/
├── backend/
│   ├── app/
│   │   ├── api/                 # FastAPI 路由
│   │   ├── core/                # 配置、数据库、基础设施
│   │   ├── models/              # SQLAlchemy 模型
│   │   └── services/            # 业务服务
│   ├── data/                    # SQLite、运行时配置、缓存数据
│   ├── tests/                   # 后端测试与联调脚本
│   ├── .env.example
│   ├── Dockerfile
│   └── main.py
├── frontend/
│   ├── src/
│   │   ├── api/                 # Axios API 封装
│   │   ├── components/          # 组件
│   │   ├── router/              # 路由
│   │   └── views/               # 页面
│   ├── tests/smoke/             # Playwright 冒烟测试
│   ├── Dockerfile
│   └── package.json
├── docker/
│   └── all-in-one/              # 单镜像 Nginx 与启动脚本
├── Dockerfile                   # All-in-one 单镜像构建入口
├── docker-compose.yml
├── docker-compose.single.yml
├── dev-linux.sh
└── README.md
```

## Current Behavior Notes

### Explore pages
- 首页采用分区级懒加载
- 首页支持后端预热缓存
- 更多榜单页使用单分区分页加载

### Emby
- 已入库状态会展示在卡片和详情页
- 剧集对号基于“缺集为 0”规则
- Emby 数据支持本地索引和定时同步

### 115 transfer
- 新转存默认直存到 115 默认目录
- 剧集支持选集转存
- HDHive 一键转存和选集转存都带积分解锁提示

## FAQ

### Docker 已启动，但前端首次可用为什么会慢？
后端启动阶段会执行首页探索预热和部分运行时初始化，健康检查通过前前端不会启动反代到后端。这是当前实现的设计选择。

### 为什么 Docker Compose 里没有暴露后端 8000？
当前默认部署模型把 Nginx 作为统一入口，浏览器访问 `5173` 即可，API 通过 `/api` 反代到后端。

### 数据丢失后怎么恢复？
核心数据都在 `backend/data/` 下。只要这个目录保留，容器重建后数据库和运行时配置会继续存在。

### 详情页 Nullbr 为什么不是自动加载？
当前详情页已经改成手动获取 Nullbr 资源，避免页面打开即触发重型请求。

## Development Notes

- 默认开发分支使用 `master`
- 前端和后端都支持本地运行与 Docker 运行
- Docker 镜像已经过实际构建和部署验证
- 前端 Playwright 冒烟测试已接入
