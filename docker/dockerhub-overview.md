# MediaSync115

**影视搜索 · 榜单探索 · 订阅 · 115 转存 · 自动归档 · STRM 生成 · Emby 代理 302 直连播放 的一体化媒体同步工具**

一个面向个人媒体库管理的全栈应用（Vue 3 + FastAPI + SQLite），围绕「找片 → 找资源 → 转存 → 订阅 → 入库同步」构建。多架构镜像，支持 `linux/amd64` 与 `linux/arm64`。

- 📦 源码 / 完整文档：https://github.com/wangsy1007/MediaSync115
- 💬 Telegram 群：https://t.me/+EkEBz7x7i9NlYzFl

---

## ✨ 功能一览

- **搜索与探索** — TMDB 搜索、豆瓣榜单探索、电影/剧集/演职员详情
- **多来源找资源** — 115 网盘分享、磁力、ED2K；支持 Pansou、HDHive、Telegram、SeedHub、不太灵
- **画质筛选** — 按分辨率 / 编码 / HDR / 音频语言 / 字幕 / 排除标签 / 体积范围智能排序过滤
- **一键转存** — 详情页 / 探索页卡片一键转存，后台转存队列，统一「转存 → 归档 → STRM」链路
- **订阅与自动扫描** — 电影/剧集订阅，剧集支持**季/集粒度**（指定季、集段、只追新集、含特别篇），后台定时多来源扫描并自动转存
- **自动归档 & STRM** — 待整理目录自动归档到输出目录，归档/离线完成后自动生成 `.strm`
- **Emby 联动 & 代理 302 播放** — 已入库标记、缺集判断、全量同步索引；**Emby 代理端口 8099**，播放自动 302 跳转 115 CDN 直连，无需服务器中转
- **飞牛影视集成** — 已入库标记、缺集判断（Emby + 飞牛合并查询）、全量同步索引
- **ISO 原盘播放** — 原盘 302 直链链路对齐，缓解卡顿；订阅转存默认可跳过 ISO/IMG 原盘
- **Telegram Bot** — 搜索、查看详情、发起转存、添加订阅，消息海报预览
- **可选 Kafka 埋点** — 未配置时自动禁用，不影响主业务
- 日志（支持自动刷新）、调度、运行时设置、健康检查

---

## 🏷️ 镜像标签

| Tag | 说明 |
|-----|------|
| `latest` | 最新稳定版，推荐 NAS 及日常部署使用（NAS 更容易识别到「可更新」） |
| `1.3.0` | 锁定版本，避免自动漂移 |

多架构镜像，`docker pull` 会按宿主机平台自动选择 `amd64` / `arm64`。

---

## 🚀 快速开始

### docker run

```bash
docker pull wangsy1007/mediasync115:latest

docker run -d \
  --name mediasync115 \
  -p 5173:5173 \
  -p 9008:9008 \
  -p 8099:8099 \
  -e TZ=Asia/Shanghai \
  -e EMBY_PROXY_HOST=your-emby-host \
  -e EMBY_PROXY_PORT=8096 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/strm:/app/strm \
  --restart unless-stopped \
  wangsy1007/mediasync115:latest
```

### docker compose

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
      - ./strm:/app/strm
```

```bash
docker compose up -d
```

> 需要同时部署盘搜（Pansou）？仓库提供 `compose.pansou.yaml` / `compose.nas.pansou.yaml` 一键集成，详见 GitHub 仓库。

---

## 🔌 端口 & 挂载

| 端口 | 必填 | 说明 |
|------|------|------|
| `5173` | 是 | 前端 UI，浏览器访问 `http://你的IP:5173` |
| `9008` | 是 | 后端 API + STRM 播放端口 |
| `8099` | 否 | **Emby 代理端口**，客户端连此端口实现 302 直连播放；不需要可删除 |

| 挂载 | 必填 | 说明 |
|------|------|------|
| `./data:/app/data` | 是 | 持久化数据（配置、数据库、缓存）。**升级容器时不要删除此目录，数据即在其中** |
| `./strm:/app/strm` | STRM 场景 | STRM 输出目录，需被 Emby/飞牛媒体库路径覆盖到 |

**常用环境变量：** `TZ`（时区，建议 `Asia/Shanghai`）、`EMBY_PROXY_HOST`（真实 Emby 地址，宿主机用 `host.docker.internal`）、`EMBY_PROXY_PORT`（真实 Emby 端口，默认 `8096`）。

---

## ⚙️ 首次启动配置

无需预先创建 `.env`。首次启动后进入**设置页**填写，配置持久化到 `data/runtime_settings.json`：

| 配置项 | 获取方式 |
|--------|----------|
| TMDB API Key | https://www.themoviedb.org/settings/api |
| 115 Cookie | 浏览器登录 115 → F12 → Network → 复制请求里的完整 `Cookie` 头 |
| Emby URL + API Key | Emby 后台 → 高级 → API 密钥管理 |
| 飞牛影视 URL + API Key | 飞牛后台 → 设置 → API 密钥 |
| Pansou 地址 | 使用非集成 compose 时填写；集成 `compose.pansou.yaml` 通常可省略 |

访问地址：`http://你的IP:5173`（UI） · `http://你的IP:8099`（Emby 代理） · `http://你的IP:9008/api/docs`（API 文档）

---

## 🔄 NAS 手动更新

推荐使用 `latest`，`latest` 更新后多数 NAS 面板会提示「有可更新镜像」，点击拉取更新 / 重新部署即可，保持数据目录挂载不变。命令行等效：

```bash
docker compose pull && docker compose up -d
```

数据全部在挂载的 `data/` 目录内，重建容器不丢数据。

---

## 📝 更新记录（1.3.0）

- 日志页面支持自动刷新
- ISO 原盘播放对齐 SmartStrm 302 直链链路，强制本地 Range 反代，根治播放卡顿/退出
- 订阅转存默认跳过 ISO/IMG 原盘资源
- 强化 STRM 全量生成入口：清空目录后自动升级为全量重建
- 302 直链播放全面对齐，锁定 UA 一致性

完整更新日志见 GitHub 仓库 [`CHANGELOG.md`](https://github.com/wangsy1007/MediaSync115/blob/master/CHANGELOG.md)。
