# MediaSync115 项目文档

> 生成日期：2026-05-12

---

## 项目概述

MediaSync115 是一个面向个人媒体库管理的全栈应用，围绕"找片、找资源、转存、订阅、入库同步"构建。

- **后端**: Python 3.12 + FastAPI + SQLAlchemy 2.0 async (SQLite WAL)
- **前端**: Vue 3 + Vite 6 + Element Plus + Pinia + Vue Router
- **部署**: Docker 多阶段构建（Nginx + Uvicorn 合并镜像）
- **测试**: pytest（后端）、Playwright（前端冒烟测试）

### 核心功能

1. TMDB / 豆瓣搜索探索与排行榜
2. 115 网盘资源获取、一键转存
3. 影视订阅与自动扫描（支持季/集粒度）
4. 自动归档与 STRM 文件生成
5. Emby / 飞牛影视集成（已入库标记、缺集判断、同步）
6. Emby 代理 302 播放（端口 8099）
7. Telegram Bot 集成（频道索引、消息搜索、通知）
8. 资源画质筛选（分辨率/编码/HDR/音频/字幕/排除标签/体积范围）

### 归档说明

归档模块当前已经支持可配置化命名：

- `movie_root_dir`、`tv_root_dir`
- `movie_filename_template`、`tv_filename_template`
- 分类规则仍负责 `电影/分类`、`剧集/分类` 这两层
- 模板直接表示后续完整相对路径，可以把季目录一起写进去

---

## 目录结构

```
MediaSync115/
├── backend/
│   ├── app/
│   │   ├── api/                  # FastAPI 路由处理器（12个模块）
│   │   │   ├── archive.py        # 归档/刮削端点
│   │   │   ├── auth.py           # 认证端点
│   │   │   ├── license.py        # 授权管理
│   │   │   ├── logs.py           # 操作日志
│   │   │   ├── pan115.py         # 115网盘 API
│   │   │   ├── pansou.py         # Pansou 搜索
│   │   │   ├── scheduler.py      # 定时任务管理
│   │   │   ├── search.py         # 多源搜索聚合（114KB）
│   │   │   ├── settings.py       # 运行时配置（42KB）
│   │   │   ├── strm.py           # STRM 文件生成
│   │   │   ├── subscriptions.py  # 订阅管理（51KB）
│   │   │   └── workflow.py       # 工作流执行
│   │   ├── core/
│   │   │   ├── config.py         # Pydantic 环境变量配置
│   │   │   └── database.py       # SQLAlchemy async 初始化
│   │   ├── models/
│   │   │   ├── models.py         # 核心模型（Subscription, DownloadRecord, OperationLog 等）
│   │   │   ├── archive.py        # 归档相关模型
│   │   │   ├── emby_sync_index.py
│   │   │   ├── feiniu_sync_index.py
│   │   │   ├── scheduler_task.py
│   │   │   └── workflow.py
│   │   ├── services/             # 业务逻辑服务层（60+ 文件）
│   │   ├── analytics/            # Kafka 事件分析
│   │   │   ├── event_types.py
│   │   │   ├── kafka_producer.py
│   │   │   └── schemas.py
│   │   ├── utils/
│   │   │   ├── name_parser.py    # 媒体名称解析
│   │   │   ├── proxy.py          # 代理配置
│   │   │   └── resource_tags.py  # 资源画质标签
│   │   └── scheduler.py          # APScheduler 单例管理器
│   ├── main.py                   # FastAPI 入口
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── tests/                    # pytest 测试套件
├── frontend/
│   ├── src/
│   │   ├── App.vue
│   │   ├── main.js
│   │   ├── api/
│   │   │   └── index.js          # Axios API 客户端封装
│   │   ├── components/
│   │   │   ├── OptimizedImage.vue
│   │   │   ├── VirtualList.vue
│   │   │   ├── explore/
│   │   │   │   └── ExploreSectionRow.vue
│   │   │   └── media/
│   │   │       └── LibraryBadge.vue
│   │   ├── composables/
│   │   │   └── usePerformance.js
│   │   ├── router/
│   │   │   └── index.js
│   │   ├── views/                # 15个页面组件
│   │   │   ├── Login.vue
│   │   │   ├── Search.vue
│   │   │   ├── Subscriptions.vue
│   │   │   ├── Downloads.vue
│   │   │   ├── Archive.vue
│   │   │   ├── Strm.vue
│   │   │   ├── Logs.vue
│   │   │   ├── Settings.vue
│   │   │   ├── Scheduler.vue
│   │   │   ├── Workflow.vue
│   │   │   ├── MovieDetail.vue
│   │   │   ├── TvDetail.vue
│   │   │   ├── DoubanDetail.vue
│   │   │   ├── ExploreSection.vue
│   │   │   └── SubscriptionLogs.vue
│   │   └── utils/
│   │       ├── detailTabs.js
│   │       ├── license.js
│   │       ├── pan115.js
│   │       ├── performance.js
│   │       ├── resourceTags.js
│   │       └── timezone.js
│   ├── package.json
│   ├── vite.config.js
│   └── tests/smoke/              # Playwright 冒烟测试
├── docker/all-in-one/
│   ├── nginx.conf
│   └── start.sh
├── compose.yaml                  # Docker Compose（all-in-one）
├── compose.nas.yaml              # Docker Compose（NAS 变体）
├── Dockerfile                    # 多阶段构建
└── .github/workflows/docker.yml  # CI/CD 流水线
```

---

## 核心服务层

| 服务文件 | 大小 | 功能 |
|----------|------|------|
| `pan115_service.py` | 78KB | 115网盘：文件列表、离线下载、分享链接提取、视频筛选 |
| `douban_explore_service.py` | 62KB | 豆瓣：排行榜、探索分区、媒体详情 |
| `runtime_settings_service.py` | 54KB | 动态配置持久化与环境变量覆盖 |
| `archive_service.py` | 50KB | 归档扫描、元数据提取、Emby 集成 |
| `subscription_service.py` | — | 订阅检查、自动下载、状态跟踪 |
| `emby_service.py` | — | Emby 媒体库同步、已入库标记 |
| `feiniu_service.py` | 32KB | 飞牛云存储文件管理与同步 |
| `hdhive_service.py` | 31KB | HDHive 签到、资源搜索 |
| `tg_service.py` + `tg_bot/` | — | Telegram 频道索引、消息搜索、Bot 通知 |
| `tmdb_service.py` | — | TMDB API：电影/剧集详情、搜索、图片 |
| `workflow_executor.py` | — | 自定义工作流引擎（条件逻辑） |
| `operation_log_service.py` | — | 请求/响应审计日志，Trace ID 追踪 |
| `auth_service.py` | — | 会话认证、密码哈希 |
| `license_service.py` | — | 授权验证 |
| `job_registry.py` | — | 调度器任务注册表 |

---

## API 路由

| 路径 | 功能 |
|------|------|
| `/api/auth/` | 认证（登录/登出/会话/改密） |
| `/api/subscriptions/` | 订阅 CRUD + 执行 |
| `/api/downloads/` | 下载记录管理 |
| `/api/archive/` | 归档扫描与刮削 |
| `/api/search/` | 多源统一搜索 |
| `/api/pan115/` | 115网盘操作 |
| `/api/pansou/` | Pansou 搜索集成 |
| `/api/strm/` | STRM 文件生成与播放 |
| `/api/scheduler/` | 定时任务管理 |
| `/api/workflow/` | 工作流 CRUD + 执行 |
| `/api/settings/` | 运行时配置 |
| `/api/logs/` | 操作日志与订阅日志 |
| `/api/license/` | 授权验证 |

**未鉴权白名单**: `/api/auth/*`、`/api/strm/play/*`

---

## 前端路由

| 路径 | 页面 |
|------|------|
| `/login` | 登录 |
| `/explore/douban` | 豆瓣探索排行 |
| `/explore/tmdb` | TMDB 探索排行 |
| `/explore/:source/section/:key` | 探索分区详情 |
| `/subscriptions` | 订阅管理 |
| `/downloads` | 下载记录 |
| `/archive` | 归档管理 |
| `/strm` | STRM 文件管理 |
| `/logs` | 操作日志 |
| `/settings` | 应用设置 |
| `/scheduler` | 定时任务 |
| `/workflow` | 工作流管理 |
| `/movie/:id` | 电影详情页 |
| `/tv/:id` | 剧集详情页 |

---

## 关键依赖

### 后端

| 包 | 版本 | 用途 |
|----|------|------|
| FastAPI | 0.110.0+ | Web 框架 |
| Uvicorn | 0.29.0+ | ASGI 服务器 |
| SQLAlchemy | 2.0.0+ | ORM（async） |
| aiosqlite | 0.20.0+ | 异步 SQLite 驱动 |
| Pydantic | 2.0.0+ | 数据验证 |
| APScheduler | 3.10.0+ | 定时任务 |
| Telethon | 1.36.0+ | Telegram 客户端 |
| python-telegram-bot | 21.0+ | Telegram Bot API |
| httpx | 0.27.0+ | 异步 HTTP 客户端（支持 SOCKS） |
| p115client | 0.0.8.4.6+ | 115网盘 API |
| Playwright | 1.40.0+ | 浏览器自动化 |
| kafka-python | 2.0.2+ | Kafka 生产者（分析） |
| websockets | 12.0+ | WebSocket 支持 |
| watchdog | 4.0.0+ | 文件系统监控 |

### 前端

| 包 | 版本 | 用途 |
|----|------|------|
| Vue | 3.4.21 | 渐进式框架 |
| Vue Router | 4.3.0 | 客户端路由 |
| Pinia | 2.1.7 | 状态管理 |
| Element Plus | 2.6.1 | UI 组件库 |
| Axios | 1.6.8 | HTTP 客户端 |
| Vite | 6.2.0 | 构建工具 |
| Playwright | 1.54.2 | E2E 测试 |

---

## 架构关键点

### 后端

1. **全异步** — 所有 I/O 均为 async，最大化并发吞吐
2. **SQLite + WAL** — 无外部数据库依赖，WAL 模式支持读写并发
3. **中间件级日志** — 全量请求/响应追踪，Trace ID，30天自动清理
4. **APScheduler 单例** — 任务持久化到数据库，动态加载
5. **三层限速（Pan115）** — 断路器 + 限流 + 405 检测
6. **会话认证** — HTTP-only Cookie，中间件拦截 `/api/*`
7. **FastAPI lifespan** — 管理启动/关闭生命周期
8. **Kafka 分析**（可选）— 事件流监控

### 前端

1. **虚拟滚动** — `VirtualList.vue` 处理大列表性能
2. **图片优化** — `OptimizedImage.vue` 懒加载
3. **代码分割** — Vite rollup 按模块拆包（element-plus / vue-vendor / utils / icons）
4. **Terser 压缩** — 生产构建移除 console/debugger
5. **`?from=` 参数** — 详情页支持返回来源页

---

## 端口分配

| 端口 | 用途 |
|------|------|
| 5173 | 前端 UI（开发: Vite dev server；生产: Nginx） |
| 9008 | 后端 API（Uvicorn） |
| 8099 | Emby 代理 302 播放 |
| 8000 | 后端开发服务器（本地调试） |

---

## 环境变量

| 变量 | 说明 |
|------|------|
| `TMDB_API_KEY` | TMDB API 密钥 |
| `PAN115_COOKIE` | 115网盘 Cookie |
| `EMBY_URL` / `EMBY_API_KEY` | Emby 服务器地址与密钥 |
| `FEINIU_URL` / `FEINIU_SECRET` / `FEINIU_API_KEY` | 飞牛云配置 |
| `TG_API_ID` / `TG_API_HASH` / `TG_PHONE` / `TG_SESSION` | Telegram 配置 |
| `HDHIVE_COOKIE` / `HDHIVE_API_KEY` | HDHive 配置 |
| `HTTP_PROXY` / `HTTPS_PROXY` / `SOCKS_PROXY` | 代理配置 |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka 地址（可选） |
| `DATABASE_URL` | 数据库连接（默认 SQLite） |
| `CORS_ORIGINS` | 跨域允许来源 |
| `TZ` | 时区（默认 Asia/Shanghai） |

---

## 部署

### Docker（推荐）

```bash
# 构建镜像
docker build -t mediasync115:local .

# 运行容器
docker run -d \
  --name mediasync115 \
  -p 5173:5173 \
  -p 9008:9008 \
  -p 8099:8099 \
  -e TZ=Asia/Shanghai \
  -v mediasync115-data:/app/data \
  --restart unless-stopped \
  mediasync115:local

# 或使用 Docker Compose
docker compose up -d
```

### 多阶段构建流程

1. **前端构建**（Node 20）— Vite 构建 Vue 应用
2. **后端构建**（Python 3.12）— 安装 pip 依赖
3. **最终镜像** — Nginx（前端静态文件）+ Uvicorn（后端 API）

健康检查：`GET /healthz`（端口 5173）

### 本地开发

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev   # 端口 5173，/api 代理到后端 8000
```

---

## 数据持久化

- 所有持久化数据存储在 `data/` 目录（数据库、运行时配置）
- 开发时不要删除 `data/` 目录
- `.env` 和密钥文件不要提交到 Git

---

## 代码风格

- **Python**: `snake_case`，中文 docstring，完整类型提示
- **Vue**: `<script setup>` Composition API，`PascalCase.vue` 组件命名
- **Git 提交**: 中文信息，格式 `feat: xxx` / `fix: xxx` / `chore: xxx`
