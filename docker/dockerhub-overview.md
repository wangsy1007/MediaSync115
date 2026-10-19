# MediaSync115

**影视搜索 · 榜单探索 · 订阅 · 115 转存 · 自动归档 · STRM 生成 · Emby 代理 302 直连播放 的一体化媒体同步工具**

面向个人媒体库的全栈应用（Vue 3 + FastAPI + SQLite），围绕「找片 → 找资源 → 转存 → 订阅 → 入库同步」构建。当前版本 **2.0.1**，多架构镜像支持 `linux/amd64` 与 `linux/arm64`。

- 📦 部署文档 / Compose：https://github.com/wangsy1007/MediaSync115
- 💬 Telegram 群：https://t.me/+EkEBz7x7i9NlYzFl

---

## ✨ 功能一览

- **搜索与探索** — TMDB 搜索、豆瓣榜单探索、电影/剧集/演职员详情
- **多来源找资源** — 115 网盘分享、磁力、ED2K；支持 Pansou、聚影、Telegram、SeedHub、不太灵
- **画质筛选** — 按分辨率 / 编码 / HDR / 音频语言 / 字幕 / 排除标签 / 体积范围智能排序过滤
- **一键转存** — 详情页 / 探索页卡片一键转存，后台转存队列，统一「转存 → 归档 → STRM」链路
- **订阅与自动扫描** — 电影/剧集订阅，剧集支持**季/集粒度**（指定季、集段、只追新集、含特别篇）
- **自动归档 & STRM** — 待整理目录自动归档，归档/离线完成后自动生成 `.strm`
- **Emby 联动 & 代理 302 播放** — 已入库标记、缺集判断；**Emby 代理端口 8099**，播放 302 到 115 CDN
- **飞牛影视集成** — 已入库标记、缺集判断、全量同步索引、媒体库封面
- **容器内一键升级** — 挂载 `docker.sock` 后，在「设置 → 关于」点击即可拉取镜像并由 dockhelper 重建容器
- **Telegram Bot / 智能助手** — 搜索、转存、订阅、入库通知；助手对接后端能力
- 日志、调度、运行时设置、健康检查

---

## 🏷️ 镜像标签

| Tag | 说明 |
|-----|------|
| `latest` | 最新稳定版，推荐 NAS 及日常部署 |
| `2.0.1` | 锁定版本，避免自动漂移 |

多架构镜像，`docker pull` 会按宿主机平台自动选择 `amd64` / `arm64`。

---

## 🚀 快速开始

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

> `-v /var/run/docker.sock` 用于 WebUI **一键升级**。不需要可去掉该行及 `CONTAINER_NAME` / `DOCKER_IMAGE_NAME`。挂载 sock 等同宿主机 Docker 管理权限，仅在可信环境使用。

### docker compose（推荐）

完整文件见 GitHub：[`compose.yaml`](https://github.com/wangsy1007/MediaSync115/blob/master/compose.yaml)

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
      # WebUI 一键升级；不需要可删除下一行
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
docker compose up -d
```

### 同时部署盘搜（Pansou）

见 GitHub：[`compose.pansou.yaml`](https://github.com/wangsy1007/MediaSync115/blob/master/compose.pansou.yaml) + [`docker/pansou.env`](https://github.com/wangsy1007/MediaSync115/blob/master/docker/pansou.env)

- 盘搜对外端口 **38080**
- MediaSync115 容器内自动使用 `http://pansou:8888/`，一般无需再在设置页填写 Pansou 地址

```bash
docker compose -f compose.pansou.yaml up -d
```

---

## 🔌 端口 & 挂载

| 端口 | 必填 | 说明 |
|------|------|------|
| `5173` | 是 | 前端 UI：`http://你的IP:5173` |
| `9008` | 是 | 后端 API + STRM 播放 |
| `8099` | 否 | Emby 代理 302；不需要可删除 |

| 挂载 | 必填 | 说明 |
|------|------|------|
| `./data:/app/data` | 是 | 配置、数据库、缓存。**升级勿删** |
| `./strm:/app/strm` | STRM 场景 | STRM 输出目录 |
| `/var/run/docker.sock` | 一键升级 | WebUI 内拉取并重建容器 |

**环境变量：** `TZ`（建议 `Asia/Shanghai`）、`CONTAINER_NAME`、`DOCKER_IMAGE_NAME`（一键升级用）。TMDB / 115 / Emby / 飞牛等在设置页填写，写入 `data/runtime_settings.json`。

---

## ⚙️ 首次启动配置

无需预先创建 `.env`。登录默认账号 `admin` / `password`（请尽快修改），在设置页填写：

| 配置项 | 获取方式 |
|--------|----------|
| TMDB API Key | https://www.themoviedb.org/settings/api |
| 115 Cookie | 浏览器登录 115 → F12 → Network → 复制完整 `Cookie` |
| Emby URL + API Key | Emby 后台 → 高级 → API 密钥 |
| 飞牛影视 URL + API Key | 飞牛后台 → 设置 → API 密钥 |
| Pansou 地址 | 非集成 compose 时填写 |

访问：`http://你的IP:5173`（UI） · `http://你的IP:8099`（Emby 代理） · `http://你的IP:9008/api/docs`（API）

---

## 🔄 更新方式

1. **WebUI 一键升级**（推荐，需已挂载 `docker.sock`）  
   设置 → 关于 → 检查更新 → 一键升级

2. **NAS / 命令行**

```bash
docker compose pull && docker compose up -d
```

保持 `data` / `strm` 挂载不变即可保留配置与数据库。

---

## 📝 更新记录（2.0.1）

- 版本号与构建信息统一为 **2.0.1**（amd64 / arm64）
- 支持容器内一键升级（docker.sock + dockhelper）
- 归档续作片名身份校验；失效分享自动换链
- 电影华语/外语分类优先按 TMDB 产地
- 延续 1.3.x / 2.0.0：STRM 刷新媒体库、TG 入库通知、媒体库封面等
