# MediaSync115

<p align="center">
  <strong>影视搜索 · 榜单探索 · 订阅 · 115 转存 · 自动归档 · STRM 生成 · Emby 代理 302 播放的一体化媒体同步工具</strong>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2.0.1-blue?style=for-the-badge">
  <img alt="Vue 3" src="https://img.shields.io/badge/Vue-3-42b883?style=for-the-badge&logo=vue.js&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/SQLite-3-003b57?style=for-the-badge&logo=sqlite&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-amd64%20%7C%20arm64-2496ed?style=for-the-badge&logo=docker&logoColor=white">
</p>

<p align="center">
  <a href="https://hub.docker.com/r/wangsy1007/mediasync115">Docker Hub</a>
  ·
  <a href="https://t.me/+EkEBz7x7i9NlYzFl">Telegram 交流群</a>
</p>

<p align="center">
  <img width="280" height="280" alt="Telegram 群二维码" src="https://github.com/user-attachments/assets/19c930cc-3a3a-4ba4-b2bb-b9703982efce" />
</p>

> **说明**：本仓库现仅保留项目说明文档。应用以 Docker 镜像形式发布与更新，请通过 [Docker Hub](https://hub.docker.com/r/wangsy1007/mediasync115) 拉取使用。

---

## 项目总结（现状）

MediaSync115 是面向**个人媒体库**的全栈应用，把「找片 → 找资源 → 转存 → 订阅补齐 → 归档命名 → STRM / 播放器入库」串成一条可自动运转的闭环。

当前稳定版本为 **2.0.1**，提供 `linux/amd64` 与 `linux/arm64` 多架构镜像；适合本机 Docker、群晖 / 飞牛 / UNRAID 等 NAS 部署。配置、数据库与缓存全部落在挂载目录 `data/`，容器重建不丢数据。

### 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 · Element Plus · Pinia · Vue Router |
| 后端 | Python FastAPI · SQLAlchemy async · SQLite（WAL） |
| 调度 | APScheduler（订阅扫描、归档、STRM、媒体库同步等） |
| 部署 | All-in-one Docker 镜像（UI `5173` / API·STRM `9008` / Emby 代理 `8099`） |
| 测试 | pytest（后端）· Playwright（前端冒烟） |

### 能力闭环

```text
TMDB / 豆瓣探索
      ↓
多渠道找资源（画质筛选）
      ↓
115 转存 / 磁力·ED2K 离线
      ↓
订阅定时补齐（电影 / 剧集季集粒度）
      ↓
自动归档（TMDB 识别命名）+ 失败隔离
      ↓
生成 STRM → Emby 代理 302 / 飞牛同步
      ↓
TG Bot 通知 · 媒体库封面 · 智能助手
```

---

## 功能一览

### 1. 搜索与探索
- TMDB 搜索电影、剧集、演职员
- 豆瓣 / 猫眼等榜单探索，详情页查看元数据
- 探索页与详情页支持一键转存

### 2. 多来源找资源
- 115 网盘分享、磁力链接、ED2K
- 渠道：Pansou（盘搜）、聚影、Telegram、SeedHub、不太灵 等
- **画质筛选**：分辨率 / 编码 / HDR / 音频语言 / 字幕 / 排除标签 / 体积范围

### 3. 转存与离线
- 详情页、探索页卡片一键转存；剧集可按缺集选集
- 后台转存队列，与订阅、归档、STRM 统一链路
- 失效分享（已取消 / 空分享）自动换链；部分 115「已转存」错误码按成功处理
- TG Bot 支持磁链 / ed2k / 115 直走系统转存与离线任务

### 4. 订阅与自动扫描
- 电影 / 剧集订阅；剧集支持**全剧 / 指定季 / 指定集段 / 只追新集 / 特别篇**
- 订阅级画质偏好；多阶段状态（匹配中 / 转存中 / 离线已提交 / 归档中等）
- 定时多来源扫描自动补齐；本季大结局且库内全集时可自动清理连载订阅
- 已完成订阅可自动清理

### 5. 自动归档与 STRM
- 待整理目录按 TMDB 身份归档命名；电影华语 / 外语优先按产地分类
- 归档覆盖模式（对齐 MoviePilot：never / size / always / latest / quality 等）
- 归档失败目录隔离与可选定时清理；覆盖失败可推送 Telegram
- 归档 / 离线完成后自动生成 `.strm`，供 Emby、飞牛影视等使用
- STRM 后可主动刷新 Emby / 飞牛媒体库并同步应用内索引

### 6. Emby / 飞牛联动
- 卡片与详情显示已入库标记；剧集缺集合并查询 Emby + 飞牛
- 全量同步索引与定时同步
- **Emby 代理 8099**：播放自动 302 到 115 CDN 直连（含 ISO 原盘 Range 反代对齐）
- Emby / 飞牛**媒体库封面生成**（多风格、中文字体、定时更新）

### 7. Telegram Bot 与通知
- 搜索、详情、转存、订阅；消息支持海报预览
- 归档入库通知（成功即发）；归档覆盖失败通知等

### 8. 智能助手与其它
- 智能助手对接后端能力，支持选项交互与较长任务收尾
- 工作流、分享中心、本地上传、日志中心（分类筛选 / 自动刷新）、调度管理
- 可选 Kafka 埋点（未配置则自动禁用）
- 运行时设置页配置，健康检查与版本更新检测
- **容器内一键升级**（设置 → 关于）：挂载 `docker.sock` 后，点击即可拉取镜像并由 dockhelper 重建容器（对齐 ETKN 一类做法）

### 容器内一键升级（可选）

原理：主容器通过 `/var/run/docker.sock` 调用 Docker API 拉取新镜像，再启动短生命周期 **dockhelper** 容器完成「停旧 → 按原配置起新 → 失败回滚」。页面短暂中断后自动恢复，无需在 NAS 面板手动重新部署。

Compose 需包含（官方模板已默认加上）：

```yaml
environment:
  CONTAINER_NAME: mediasync115
  DOCKER_IMAGE_NAME: wangsy1007/mediasync115:latest
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

> 挂载 `docker.sock` 等同把宿主机 Docker 管理权限交给容器，仅在可信环境使用。

---

## 2.0.1 重点

- 版本号与构建信息统一为 **2.0.1**（多架构 `amd64` / `arm64`）
- 支持容器内一键升级（`docker.sock` + dockhelper）
- 延续 2.0.0：归档续作身份校验、失效分享换链、电影产地分类等

---

## 快速开始

镜像：

```text
https://hub.docker.com/r/wangsy1007/mediasync115
```

| Tag | 说明 |
|-----|------|
| `latest` | 日常与 NAS 推荐，便于面板识别「可更新」 |
| `2.0.1` | 锁定版本，避免自动漂移 |

### docker run

```bash
mkdir -p data strm

docker pull wangsy1007/mediasync115:latest

docker run -d \
  --name mediasync115 \
  -p 5173:5173 \
  -p 9008:9008 \
  -p 8099:8099 \
  -e TZ=Asia/Shanghai \
  -e CONTAINER_NAME=mediasync115 \
  -e DOCKER_IMAGE_NAME=wangsy1007/mediasync115:latest \
  --add-host host.docker.internal:host-gateway \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/strm:/app/strm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --restart unless-stopped \
  wangsy1007/mediasync115:latest
```

> `/var/run/docker.sock` 用于 WebUI 一键升级；不需要可去掉该挂载及对应环境变量。

### docker compose（推荐）

仓库提供可直接使用的部署文件：

| 文件 | 用途 |
|------|------|
| [`compose.nas.yaml`](./compose.nas.yaml) | 仅 MediaSync115（Docker Hub 镜像，推荐） |
| [`compose.nas.pansou.yaml`](./compose.nas.pansou.yaml) | MediaSync115 + [Pansou 盘搜](https://github.com/fish2018/pansou)（对外 **38080**） |
| [`docker/pansou.env`](./docker/pansou.env) | 盘搜环境变量（与盘搜 compose 配套） |

GitHub 文档仓库根目录另提供同名简写 `compose.yaml` / `compose.pansou.yaml`（内容与上述 NAS 模板一致），可直接 `docker compose up -d`。

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
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      TZ: Asia/Shanghai
      CONTAINER_NAME: mediasync115
      DOCKER_IMAGE_NAME: wangsy1007/mediasync115:latest
    volumes:
      - ./data:/app/data
      - ${STRM_HOST_DIR:-./strm}:/app/strm
      - /var/run/docker.sock:/var/run/docker.sock
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

```bash
mkdir -p data strm
docker compose -f compose.nas.yaml up -d

# 含盘搜
docker compose -f compose.nas.pansou.yaml up -d
```

---

## 端口与挂载

| 端口 | 必填 | 说明 |
|------|------|------|
| `5173` | 是 | 前端 UI：`http://你的IP:5173` |
| `9008` | 是 | 后端 API + STRM 播放；飞牛读 STRM 常走此端口 |
| `8099` | 否 | Emby 代理 302；不需要可去掉映射 |

| 挂载 | 必填 | 说明 |
|------|------|------|
| `./data:/app/data` | 是 | 配置、数据库、缓存。**升级勿删** |
| `./strm:/app/strm` | STRM 场景 | STRM 输出目录，需被播放器媒体库路径覆盖到 |

设置页中请将 `STRM 输出目录` 填为容器内路径 `/app/strm`。

---

## 首次配置

无需预先创建 `.env`。首次启动后打开设置页填写（写入 `data/runtime_settings.json`）：

| 配置项 | 获取方式 |
|--------|----------|
| TMDB API Key | [TMDB API 设置](https://www.themoviedb.org/settings/api) |
| 115 Cookie | 浏览器登录 115 → F12 → Network → 复制完整 `Cookie` |
| Emby URL + API Key | Emby 后台 → 高级 → API 密钥 |
| 飞牛影视 URL + API Key | 飞牛后台 → 设置 → API 密钥 |
| Pansou 地址 | 若单独部署盘搜则填写，例如 `http://192.168.x.x:38080/` |

**默认登录**（请尽快修改）：

| 项目 | 默认值 |
|------|--------|
| 账号 | `admin` |
| 密码 | `password` |

也可用环境变量 `MEDIASYNC_USER` / `MEDIASYNC_PASSWORD` 覆盖（多用于自动化）。

**Emby 代理 8099 提示**：
- 在 STRM 设置中开启「Emby 代理」后，`.strm` 会走代理端口
- Emby 客户端连接 `http://你的IP:8099` 即可 302 到 115 CDN
- Emby URL 需为**容器内可访问**地址：宿主机 Emby 常用 `http://host.docker.internal:8096`

访问：
- UI：`http://127.0.0.1:5173`
- Emby 代理：`http://127.0.0.1:8099`
- API 文档：`http://127.0.0.1:9008/api/docs`

---

## NAS 更新

推荐镜像 tag：`wangsy1007/mediasync115:latest`。

1. 保持 `data` / `strm` 宿主机挂载不变  
2. 面板提示有更新时：拉取更新 / 重新部署  
3. 或命令行：

```bash
docker compose pull
docker compose up -d
```

升级后数据会保留：只要不删除宿主机 `data/` 目录即可。

---

## 常见问题

**前端首次可用偏慢？**  
启动阶段会做探索预热等初始化，健康检查通过前页面可能尚未完全可用。

**数据丢了怎么恢复？**  
核心都在 `data/`。保留该目录即可在容器重建后恢复配置与数据库。

**详情页资源为什么不自动加载？**  
为避免打开即触发重型请求，详情页改为手动获取资源。

**只要镜像、不要源码？**  
是的。本仓库仅文档；运行请用 Docker Hub 镜像。问题与交流见上方 Telegram 群。

---

## 许可与交流

个人媒体库自用工具。部署与使用问题欢迎到 [Telegram 群](https://t.me/+EkEBz7x7i9NlYzFl) 讨论。
