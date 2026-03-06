# MediaSync115 - 项目上下文指南

## 项目概述

MediaSync115 是一个全栈媒体同步应用，用于搜索电影/电视节目、管理订阅，并深度集成 115 云盘进行文件管理、离线下载和分享链接转存。

### 主要功能

- **媒体搜索**: 通过 Nullbr API（基于 TMDB）搜索电影和电视剧
- **榜单浏览**: 豆瓣榜单、TMDB 热门榜单
- **订阅管理**: 自动追踪订阅内容的更新
- **115 云盘集成**: 文件管理、离线下载、分享链接解析和转存
- **多源搜索**: HDHive、Pansou、Telegram 频道资源索引
- **工作流引擎**: 可配置的自动化工作流
- **定时任务**: 基于 APScheduler 的任务调度系统

---

## 技术栈

### 后端 (Python/FastAPI)

| 组件 | 版本/技术 |
|------|----------|
| Web 框架 | FastAPI >= 0.110.0 |
| 数据库 | SQLite + aiosqlite (异步) |
| ORM | SQLAlchemy 2.0 |
| 数据验证 | Pydantic 2.0 |
| 定时任务 | APScheduler >= 3.10.0 |
| HTTP 客户端 | httpx >= 0.27.0 |
| 115 云盘 | p115client >= 0.0.8.4.6 |
| Telegram | Telethon >= 1.36.0 |

### 前端 (Vue 3)

| 组件 | 版本/技术 |
|------|----------|
| 框架 | Vue 3.4+ (Composition API) |
| 构建工具 | Vite 5 |
| UI 组件库 | Element Plus 2.6+ |
| 状态管理 | Pinia 2.1+ |
| HTTP 客户端 | Axios 1.6+ |
| 样式 | SCSS/Sass |
| 图标 | @element-plus/icons-vue |

---

## 项目结构

```
MediaSync115/
├── backend/                      # FastAPI 后端
│   ├── main.py                   # 应用入口点
│   ├── requirements.txt          # Python 依赖
│   ├── Dockerfile                # 后端 Docker 配置
│   ├── .env.example              # 环境变量模板
│   ├── app/
│   │   ├── __init__.py
│   │   ├── api/                  # API 路由模块
│   │   │   ├── __init__.py
│   │   │   ├── search.py         # 搜索相关 API
│   │   │   ├── subscriptions.py  # 订阅管理 API
│   │   │   ├── pan115.py         # 115 云盘操作 API
│   │   │   ├── pansou.py         # Pansou 搜索 API
│   │   │   ├── scheduler.py      # 定时任务 API
│   │   │   ├── settings.py       # 设置管理 API
│   │   │   ├── workflow.py       # 工作流 API
│   │   │   └── logs.py           # 日志查询 API
│   │   ├── core/                 # 核心基础设施
│   │   │   ├── __init__.py
│   │   │   ├── config.py         # 配置管理 (Pydantic Settings)
│   │   │   └── database.py       # 数据库连接和会话管理
│   │   ├── models/               # SQLAlchemy ORM 模型
│   │   │   ├── __init__.py
│   │   │   ├── models.py         # 订阅、下载记录、操作日志等
│   │   │   ├── scheduler_task.py # 定时任务模型
│   │   │   └── workflow.py       # 工作流模型
│   │   ├── services/             # 业务逻辑服务层 (20+ 服务)
│   │   │   ├── nullbr_service.py
│   │   │   ├── pan115_service.py
│   │   │   ├── subscription_service.py
│   │   │   ├── tg_service.py
│   │   │   ├── workflow_service.py
│   │   │   └── ...
│   │   └── utils/                # 工具函数
│   └── data/                     # SQLite 数据库存储目录
├── frontend/                     # Vue 3 前端
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js            # Vite 配置 (含代理)
│   ├── Dockerfile                # 前端 Docker 配置
│   ├── nginx.conf                # Nginx 配置
│   └── src/
│       ├── main.js               # 应用入口
│       ├── App.vue               # 根组件
│       ├── api/
│       │   └── index.js          # 统一 API 封装 (axios)
│       ├── router/
│       │   └── index.js          # Vue Router 配置
│       ├── views/                # 页面组件
│       │   ├── Search.vue
│       │   ├── Subscriptions.vue
│       │   ├── Downloads.vue
│       │   ├── Settings.vue
│       │   ├── MovieDetail.vue
│       │   ├── TvDetail.vue
│       │   └── ...
│       ├── styles/               # SCSS 样式
│       │   └── main.scss
│       └── utils/                # 工具函数
│           └── timezone.js       # 时区处理
└── AGENTS.md                     # AI 代理开发指南
```

---

## 构建和运行

### 开发环境

#### 后端

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或: .\venv\Scripts\activate  # Windows PowerShell

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入必要的 API 密钥

# 启动开发服务器
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**服务地址:**
- API: http://localhost:8000
- API 文档 (Swagger): http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

#### 前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

**开发服务器:** http://localhost:5173

> 前端通过 Vite 代理将 `/api` 请求转发到后端 (默认: http://localhost:8001)

### 生产构建

#### 前端构建

```bash
cd frontend
npm run build
# 输出到 dist/ 目录
```

#### Docker 部署

```bash
# 构建并启动所有服务
docker-compose up --build

# 后台运行
docker-compose up -d

# 停止服务
docker-compose down
```

---

## 环境变量配置

### 必需配置

```bash
# 应用配置
APP_NAME=MediaSync115
APP_VERSION=1.0.0
DEBUG=true

# Nullbr API (媒体搜索)
NULLBR_APP_ID=your_nullbr_app_id
NULLBR_API_KEY=your_nullbr_api_key
NULLBR_BASE_URL=https://api.nullbr.com/

# TMDB API
TMDB_API_KEY=your_tmdb_api_key
TMDB_BASE_URL=https://api.themoviedb.org/3
TMDB_IMAGE_BASE_URL=https://image.tmdb.org/t/p/w500

# 115 云盘
PAN115_COOKIE=your_115_cookie_here

# Pansou 搜索服务
PANSOU_BASE_URL=http://127.0.0.1:8088/

# 数据库
DATABASE_URL=sqlite+aiosqlite:///./data/mediasync.db
```

### 可选配置

```bash
# 代理配置
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
SOCKS_PROXY=socks5://127.0.0.1:7890

# HDHive 资源站
HDHIVE_COOKIE=your_hdhive_cookie
HDHIVE_BASE_URL=https://hdhive.com/

# Telegram 配置
TG_API_ID=your_telegram_api_id
TG_API_HASH=your_telegram_api_hash
TG_PHONE=your_phone_number
TG_CHANNEL_USERNAMES=channel1,channel2
TG_SEARCH_DAYS=30

# Emby 媒体服务器
EMBY_URL=http://127.0.0.1:8096/
EMBY_API_KEY=your_emby_api_key
```

---

## 开发规范

### 后端 (Python)

#### 导入顺序

```python
# 1. 标准库
import asyncio
import hashlib
from datetime import datetime
from typing import Any

# 2. 第三方库
import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

# 3. 本地导入
from app.core.config import settings
from app.services.nullbr_service import nullbr_service
```

#### 类型注解

- 使用 Python 3.10+ 语法: `str | None` (而非 `Optional[str]`)
- 使用 `list[dict]` (而非 `List[Dict]`)
- SQLAlchemy 模型使用 `Mapped[]`: `Mapped[int]`, `Mapped[str | None]`

#### 异步模式

- 所有 I/O 操作必须是异步的
- 使用 `asyncio.to_thread()` 包装阻塞式同步调用
- 数据库会话使用异步上下文管理器

#### 命名规范

- 函数/变量/模块: `snake_case`
- 类名: `PascalCase`
- 常量: `UPPER_SNAKE_CASE`
- 服务实例: 单例模式，如 `nullbr_service = NullbrService()`

#### 错误处理

```python
from fastapi import HTTPException

# API 错误使用 HTTPException
raise HTTPException(status_code=400, detail="错误信息")

# 服务层捕获并处理异常
try:
    result = await some_async_operation()
except Exception as exc:
    # 记录日志并优雅处理
    return {"error": str(exc)}
```

### 前端 (Vue 3)

#### Script Setup 语法

```vue
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { searchApi } from '@/api'

const router = useRouter()
const loading = ref(false)
const results = ref([])

const handleSearch = async () => {
  loading.value = true
  try {
    const { data } = await searchApi.search(keyword)
    results.value = data.items || []
  } catch (error) {
    ElMessage.error('搜索失败')
  } finally {
    loading.value = false
  }
}
</script>
```

#### 命名规范

- 变量/函数/Props: `camelCase`
- 组件文件名和导入: `PascalCase`
- 模板中使用 kebab-case: `<el-button>`

#### API 调用模式

```javascript
// api/index.js 中使用箭头函数简写
export const searchApi = {
  search: (query, page = 1) => api.get('/search', { params: { query, page } }),
  getMovie: (tmdbId) => api.get(`/search/movie/${tmdbId}`),
}
```

#### 响应式数据

- 使用 `ref()` 存储原始值和对象
- 使用 `computed()` 计算派生状态
- 在 script 中使用 `.value` 访问 ref，模板中直接使用

### 样式 (SCSS)

```scss
.component-name {
  padding: 16px;

  .nested-element {
    margin: 8px 0;
  }

  &:hover {
    opacity: 0.9;
  }
}
```

---

## 核心服务说明

### 后端服务列表

| 服务 | 功能描述 |
|------|----------|
| `nullbr_service` | Nullbr API 搜索服务 |
| `pan115_service` | 115 云盘操作（文件、离线下载、分享） |
| `subscription_service` | 订阅管理 |
| `tg_service` | Telegram 客户端和消息索引 |
| `hdhive_service` | HDHive 资源站搜索 |
| `pansou_service` | Pansou 聚合搜索 |
| `workflow_service` | 工作流管理 |
| `scheduler_manager` | 定时任务调度 |
| `operation_log_service` | 操作日志记录 |
| `emby_service` | Emby 媒体服务器集成 |

### API 模块列表

| 路由前缀 | 功能 |
|----------|------|
| `/api/search` | 媒体搜索（电影、电视剧、榜单） |
| `/api/subscriptions` | 订阅 CRUD 和下载记录 |
| `/api/pan115` | 115 云盘所有操作 |
| `/api/pansou` | Pansou 搜索配置 |
| `/api/settings` | 运行时设置和健康检查 |
| `/api/scheduler` | 定时任务管理 |
| `/api/workflow` | 工作流管理 |
| `/api/logs` | 操作日志查询 |

---

## 数据库模型

### 核心模型

| 模型 | 描述 |
|------|------|
| `Subscription` | 订阅信息 |
| `DownloadRecord` | 下载记录 |
| `SubscriptionExecutionLog` | 订阅执行日志 |
| `SubscriptionStepLog` | 订阅执行步骤日志 |
| `OperationLog` | 系统操作日志 |
| `TgMessageIndex` | Telegram 消息索引 |
| `TgSyncState` | Telegram 同步状态 |
| `SchedulerTask` | 定时任务配置 |

---

## 路由结构

### 前端路由

| 路径 | 页面 | 描述 |
|------|------|------|
| `/` | 重定向到 `/explore/douban` | 首页 |
| `/explore/:source` | Search.vue | 榜单浏览 (douban/tmdb) |
| `/explore/:source/section/:key` | ExploreSection.vue | 具体榜单内容 |
| `/subscriptions` | Subscriptions.vue | 订阅管理 |
| `/downloads` | Downloads.vue | 离线下载管理 |
| `/logs` | Logs.vue | 系统日志 |
| `/settings` | Settings.vue | 系统设置 |
| `/scheduler` | Scheduler.vue | 定时任务 |
| `/workflow` | Workflow.vue | 工作流管理 |
| `/movie/:id` | MovieDetail.vue | 电影详情 |
| `/tv/:id` | TvDetail.vue | 电视剧详情 |
| `/douban/:type/:id` | DoubanDetail.vue | 豆瓣条目详情 |

---

## 快速参考

### 常用命令

```bash
# 后端
uvicorn main:app --reload                    # 开发模式
python test_nullbr.py                        # 测试 Nullbr API
python test_115_response.py                  # 测试 115 接口

# 前端
npm run dev                                  # 开发服务器
npm run build                                # 生产构建
npm run preview                              # 预览构建

# 数据库
# 删除 data/mediasync.db 可重置数据库，SQLAlchemy 会自动重建表
```

### 开发工作流

1. **添加新 API**: 
   - 在 `backend/app/services/` 创建服务
   - 在 `backend/app/api/` 添加路由
   - 在 `frontend/src/api/index.js` 添加前端 API 方法

2. **添加新页面**:
   - 在 `frontend/src/views/` 创建组件
   - 在 `frontend/src/router/index.js` 注册路由

3. **数据库变更**:
   - 修改 `backend/app/models/` 下的模型
   - 删除数据库文件让 SQLAlchemy 自动重建（开发环境）

---

## 注意事项

- 后端使用异步 SQLAlchemy，所有数据库操作必须是异步的
- 前端使用 Element Plus 的中文语言包
- 系统默认使用北京时间（Asia/Shanghai）
- 操作日志会自动记录所有 API 请求（30 天自动清理）
- 定时任务使用 APScheduler，支持持久化存储

---

*最后更新: 2025-03-05*
