# Design Document — Quark Cloud Support

## 概述

本期目标是在不改变现有 115 网盘体验的前提下，为 MediaSync115 引入对夸克网盘的支持，范围严格限定在两件事：

1. **设置页配置夸克 Cookie**（含连通性检查与默认转存目录选择）；
2. **影视详情页新增"夸克网盘"主 Tab**（与 115 Tab 并列，下含 Pansou / HDHive / Telegram 三个子 Tab + 一键转存）。

设计采取"**最小侵入、独立模块**"策略：

- **不引入 Cloud Provider 抽象层**。本期通过新增 `QuarkService`、独立的 API 路由前缀（`/api/quark/*`、`/api/search/{movie|tv}/{id}/quark/*`）、独立的前端组件（`QuarkResourceTab.vue`）实现 dual-provider 共存。等 Phase 2（订阅自动转存到夸克 / STRM 走夸克）真正需要时再做抽象。
- **现有 115 代码路径完全不动**。`Pan115Service`、`/115/*` 路由、`pan115_share_link` / `pan115_savable` 字段全部保留；新字段以"加列"方式落库。
- **三个资源源（Pansou / HDHive / Telegram）的底层抓取能力已经具备返回夸克资源的能力**，本期只需新增"按 cloud_type 过滤 + 标注"的薄适配层，不重写资源源服务。

## 引导性架构

### 1. 顶层组件视图

```
┌─────────────────────────────────────────────────────────────────┐
│                      Frontend (Vue 3)                           │
│                                                                 │
│  ┌─────────────────┐   ┌────────────────────────────────────┐   │
│  │ Settings.vue    │   │ MovieDetail.vue / TvDetail.vue /   │   │
│  │  - 115 子区块    │   │ DoubanDetail.vue                   │   │
│  │  - 夸克子区块 ★  │   │  - 主 Tab: 115 / 夸克★ / 磁力       │   │
│  └────────┬────────┘   │  - 夸克 Tab → QuarkResourceTab.vue  │   │
│           │            └─────────────┬──────────────────────┘   │
│           │                          │                          │
│           ▼                          ▼                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ frontend/src/api/index.js                                │    │
│  │  - quarkApi (新增★)                                       │    │
│  │  - searchApi.getMovie/TvQuarkPansou/Hdhive/Tg (新增★)    │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │  HTTP
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backend (FastAPI)                          │
│                                                                 │
│  Routes (新增★):                                                 │
│   - /api/quark/cookie/{check,update,info}                       │
│   - /api/quark/connectivity/check                               │
│   - /api/quark/folders                                          │
│   - /api/quark/default-folder (GET/POST)                        │
│   - /api/quark/share/save-to-folder                             │
│   - /api/search/{movie|tv}/{id}/quark/{pansou,hdhive,tg}        │
│                                                                 │
│  Services:                                                       │
│   ┌─────────────────────┐    ┌──────────────────────────────┐   │
│   │ Pan115Service       │    │ QuarkService (新增★)          │   │
│   │ (本期不动)            │    │ - cookie / connectivity       │   │
│   └─────────────────────┘    │ - folders / share / save       │   │
│                              └──────────────────────────────┘   │
│                                                                  │
│  Resource Sources (改动)：                                        │
│   - pansou_service.search(cloud_types=[...])  ── 已支持，扩调用    │
│   - hdhive_service.get_*_resource(pan_type=)  ── 新参数★          │
│   - tg_index_service               ── 新增 cloud_type 列★          │
│                                                                  │
│  Runtime Settings (扩展)：                                        │
│   - QUARK_COOKIE / QUARK_DEFAULT_DIR (新增★)                      │
│                                                                  │
│  DB Migrations:                                                   │
│   - tg_index 表新增 cloud_type 列 (默认 "pan115")★                │
└─────────────────────────────────────────────────────────────────┘
```

### 2. 数据流：用户在详情页点击"一键转存（夸克）"

```
User clicks "一键转存"
  └─ Vue (QuarkResourceTab.vue)
      └─ POST /api/quark/share/save-to-folder
          { share_url, share_id, title, target_folder_id?, receive_code? }
          └─ FastAPI Route Handler
              └─ QuarkService.save_share_to_folder()
                  ├─ parse share URL → share_id, receive_code
                  ├─ list_share_files(share_id, ...)
                  ├─ create_folder_if_needed(target_folder_id, title)
                  ├─ save_share_files_to_target(...)
                  └─ return result
              └─ operation_log_service.log("quark_save", ...)
              └─ HTTP 200 / 401 / 412 / 429 / 502
```

### 3. 数据流：用户在详情页打开夸克 Tab → Pansou 子 Tab

```
User switches to Quark Tab (defaults to Pansou subtab)
  └─ QuarkResourceTab.vue (lazy load on first activation)
      └─ GET /api/search/movie/{id}/quark/pansou?page=1
          └─ FastAPI Route Handler (api/search.py 新增)
              └─ pansou_service.search(keyword, cloud_types=["quark"])
              └─ normalize → cloud_type=quark, share_link, ...
              └─ check QUARK_COOKIE → cloud_savable
              └─ return { list: [...], attempts, keyword, ... }
```

## 后端设计

### A. QuarkService（新增）

文件：`backend/app/services/quark_service.py`

按现有 `Pan115Service` 风格设计为单例 + 可重新初始化的 cookie：

```python
class QuarkService:
    """夸克网盘服务

    封装夸克网盘的逆向接口（参考 quark-auto-save 等社区项目）。
    所有远程调用使用 httpx.AsyncClient，超时阈值默认 30s。
    Cookie 失效时在内存内标记 invalid 并在 5 分钟内短路 401。
    """

    _BASE_URL = "https://drive-pc.quark.cn"
    _CONNECT_TIMEOUT = 15.0
    _READ_TIMEOUT = 30.0
    _SAVE_OPERATION_TIMEOUT = 180.0
    _INVALID_COOKIE_TTL_SECONDS = 5 * 60

    def __init__(self, cookie: Optional[str] = None) -> None:
        self._cookie = (cookie or settings.QUARK_COOKIE or "").strip()
        self._invalid_until: float = 0.0
        self._invalid_reason: str = ""

    # ───── cookie 管理 ─────
    def update_cookie(self, cookie: str) -> None: ...
    def is_configured(self) -> bool: ...
    def is_invalidated(self) -> bool: ...
    def mark_invalid(self, reason: str) -> None: ...
    def clear_invalid(self) -> None: ...

    # ───── 连通性 / 用户 ─────
    async def check_cookie_valid(self) -> dict[str, Any]: ...
    async def get_account_info(self) -> dict[str, Any]: ...

    # ───── 目录浏览 ─────
    async def list_folders(
        self, parent_fid: str = "0", *, page: int = 1, size: int = 200
    ) -> dict[str, Any]: ...

    # ───── 分享解析与转存 ─────
    async def parse_share_url(self, share_url: str) -> dict[str, Any]:
        """从 https://pan.quark.cn/s/{share_id}#/list/share/... 解析 share_id, pwd_id, receive_code"""

    async def list_share_files(
        self, share_id: str, *, receive_code: str = "", parent_fid: str = "0",
    ) -> list[dict[str, Any]]: ...

    async def save_share_to_folder(
        self,
        share_url: str,
        target_folder_fid: str,
        *,
        folder_name: Optional[str] = None,
        receive_code: str = "",
        tmdb_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        转存流程（与 115 对齐）：
          1. parse_share_url → share_id, pwd_id, receive_code
          2. list_share_files
          3. 若提供 folder_name，则在 target_folder_fid 下 create_folder
          4. save_share_files_to_target_folder（夸克批量保存接口）
          5. 返回 {save_id, item_count, target_fid, target_path}
        异常映射：
          - cookie 失效 → ValueError("quark_cookie_invalid") → API 层转 401
          - 限流 → ValueError("quark_rate_limited") → API 层转 429
          - 5xx/网络 → 直接抛 → API 层转 502
        """


quark_service = QuarkService()
```

**Cookie 失效短路逻辑**：所有公开 async 方法在入口检查 `is_invalidated()`：True 时直接抛 `ValueError("quark_cookie_invalid")`，避免重复打远程接口；`update_cookie()` 调用时 `clear_invalid()`。

**httpx 客户端**：复用 `proxy_manager.create_httpx_client(...)`，与 115 / TMDB 一致。

### B. RuntimeSettingsService 扩展

文件：`backend/app/services/runtime_settings_service.py`

新增字段（沿用 `_env_overrides` 模式）：

| key | env name | 默认值 | 说明 |
|---|---|---|---|
| `quark_cookie` | `QUARK_COOKIE` | `""` | 夸克 Cookie 全文 |
| `quark_default_folder_id` | — | `"0"` | 夸克默认目录 fid（`"0"` 为根目录） |
| `quark_default_folder_name` | — | `"根目录"` | 夸克默认目录显示名称 |

新增方法（与 115 对应方法 1:1 对齐）：

```python
def get_quark_cookie(self) -> str: ...
def update_quark_cookie(self, cookie: str) -> str: ...
def get_quark_default_folder(self) -> dict[str, str]:  # {"folder_id", "folder_name"}
    ...
def update_quark_default_folder(self, folder_id: str, folder_name: str = "") -> None: ...
```

`apply_runtime_overrides()` 在末尾增加：

```python
settings.QUARK_COOKIE = self.get_quark_cookie() or None
quark_service.update_cookie(self.get_quark_cookie())
```

### C. core.config.Settings 扩展

`backend/app/core/config.py` 增加：

```python
QUARK_COOKIE: Optional[str] = None
```

`pydantic` 自动从环境变量读取。

### D. 后端 API 路由

#### D.1 夸克账号设置：`backend/app/api/quark.py`（新增）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/quark/cookie` | 返回脱敏后的 cookie 状态（首尾 4 字符 + `is_configured` 布尔） |
| GET | `/api/quark/cookie/check` | 用当前 cookie 调一次 `check_cookie_valid` |
| POST | `/api/quark/cookie/update` | body: `{cookie}`；空字符串 → 400 |
| GET | `/api/quark/connectivity/check` | 等价于 `cookie/check`，作为设置页"连通性检查"按钮入口 |
| GET | `/api/quark/folders` | query: `parent_fid`、`page`、`size`；返回子目录列表 |
| GET | `/api/quark/default-folder` | 返回当前默认目录 |
| POST | `/api/quark/default-folder` | body: `{folder_id, folder_name}` |
| POST | `/api/quark/share/save-to-folder` | 转存动作主入口（见下） |

`POST /api/quark/share/save-to-folder` 请求/响应契约：

```python
class QuarkSaveToFolderRequest(BaseModel):
    share_url: str                         # 必填
    folder_name: Optional[str] = None      # 可选；无则保存到 target_folder_id 根
    target_folder_id: Optional[str] = None # 可选；缺省取 quark_default_folder_id
    receive_code: Optional[str] = ""       # 提取码
    tmdb_id: Optional[int] = None          # 用于 operation_log

class QuarkSaveToFolderResponse(BaseModel):
    success: bool
    save_id: Optional[str] = None
    item_count: int
    target_folder: dict   # {"folder_id", "folder_path"}
    message: str
```

错误码（HTTP status / `detail.code`）：

| 场景 | HTTP | code |
|---|---|---|
| Cookie 未配置 | 412 | `quark_cookie_missing` |
| Cookie 失效 | 401 | `quark_cookie_invalid` |
| 默认目录未设 + 请求未指定目标目录 | 412 | `quark_default_dir_missing` |
| 限流 | 429 | `quark_rate_limited` |
| 上游 5xx / 网络 | 502 | `quark_api_unstable` |

#### D.2 三源夸克资源接口：扩展 `backend/app/api/search.py`

新增 6 个端点（与 115 系列 1:1 对齐）：

```
GET /api/search/movie/{tmdb_id}/quark/pansou
GET /api/search/movie/{tmdb_id}/quark/hdhive
GET /api/search/movie/{tmdb_id}/quark/tg
GET /api/search/tv/{tmdb_id}/quark/pansou
GET /api/search/tv/{tmdb_id}/quark/hdhive
GET /api/search/tv/{tmdb_id}/quark/tg
```

参数：与 115 系列对应端点完全一致（`page`、`refresh`、TV 多 `season`）。

返回结构：与 115 系列**字段名兼容**，但有以下差异：

```jsonc
{
  "id": 123456,
  "media_type": "movie",
  "page": 1,
  "list": [
    {
      "title": "...",
      "share_link": "https://pan.quark.cn/s/abcdef",   // 通用字段
      "cloud_type": "quark",                            // 新增 ★
      "cloud_savable": true,                            // 替代 pan115_savable
      "cloud_save_disabled_reason": "",                 // "quark_cookie_missing" 等
      "size": "1.5GB",
      "source_service": "pansou",
      "raw_item": {...},

      // 兼容字段（保留以让前端 saveResource 等通用函数仍能识别 share_link）：
      "pan115_share_link": "",       // 始终为空（夸克资源不出现 115 链接）
      "pan115_savable": false        // 始终为 false（夸克资源永远不能用 115 转存）
    }
  ],
  "attempts": [{"service": "pansou", "status": "ok", "count": 12}],
  "keyword": "...", "attempted_keywords": [...], "keyword_hit_index": 0,
  "search_service": "pansou"
}
```

> 设计要点：用 `share_link` 作为通用字段、`cloud_type` 区分网盘类型；前端在 Quark Tab 内只读 `share_link` + `cloud_type==quark` 不读 `pan115_*`，但保留 `pan115_*` 占位避免破坏现有通用渲染逻辑。

**缓存策略**：新增独立缓存命名空间 `_movie_quark_cache` / `_tv_quark_cache`，TTL 与 115 完全一致（`PAN115_CACHE_TTL_SECONDS`）。空结果短 TTL（`PAN115_EMPTY_CACHE_TTL_SECONDS`）也对齐。

### E. 资源源适配

#### E.1 Pansou

`pansou_service.search()` 已经支持 `cloud_types=["quark"]`，无需改动；新接口在调用时直接传入：

```python
search_result = await pansou_service.search(
    keyword=keyword,
    cloud_types=["quark"],
    res="results",
)
```

新增辅助函数 `_extract_quark_share_link(text)`（域名 `pan.quark.cn` 识别），在 `_normalize_pansou_items()` 同等位置但针对夸克的版本里调用。考虑到 normalize 逻辑相似，重构为：

```python
def _normalize_pan_items(payload, *, cloud_type: str) -> list[dict]:
    """通用归一化函数；按 cloud_type 选择链接识别正则与字段命名"""
```

并保留旧 `_normalize_pansou_items` 作为兼容包装（调用时传 `cloud_type="pan115"`），避免回归。

#### E.2 HDHive

`hdhive_service` 现有方法已实现按 `pan_type=="115"` 过滤。新增 `pan_type` 入参：

```python
class HdhiveService:
    async def get_movie_resource_result(
        self, tmdb_id: int, *, pan_type: str = "115"
    ) -> dict[str, Any]: ...
    async def get_tv_resource_result(
        self, tmdb_id: int, *, pan_type: str = "115"
    ) -> dict[str, Any]: ...

    # 现有 get_movie_pan115_result / get_tv_pan115_result 改为内部实现委托：
    async def get_movie_pan115_result(self, tmdb_id):
        return await self.get_movie_resource_result(tmdb_id, pan_type="115")
```

`_collect_tmdb_resources` 内部按 `pan_type` 参数动态过滤，并在归一化结果上写入 `cloud_type`。原 `pan115_savable=False` 字段保留；新增 `cloud_savable` 由 API 层根据 `quark_service.is_configured()` 决定（HDHive 解锁后 `cloud_savable=true`）。

#### E.3 Telegram 索引

需要做两件事：

1. **数据库 schema 变更**：`tg_index` 表新增 `cloud_type VARCHAR(16) NOT NULL DEFAULT 'pan115'` 列；
2. **索引服务变更**：`tg_index_service` 在解析 message 时同时识别 `pan.quark.cn` 域名链接，落库时写入 `cloud_type`。

**Schema 迁移**（Alembic 或等价的启动期 `ensure_tables_exist`）：

```sql
ALTER TABLE tg_index ADD COLUMN cloud_type VARCHAR(16) NOT NULL DEFAULT 'pan115';
CREATE INDEX idx_tg_index_cloud_type ON tg_index(cloud_type);
-- 老数据已默认 'pan115'，无需 backfill；新解析路径直接写正确值。
```

**索引器变更**（`tg_index_service`）：

- 新增正则 `_QUARK_SHARE_URL_PATTERN = re.compile(r"https?://pan\.quark\.cn/s/[A-Za-z0-9_]+(?:\?[^\s\"'<>]*)?", re.IGNORECASE)`
- 在原有 115 解析失败时（或并行匹配后）尝试夸克识别；命中即落库 `cloud_type="quark"`、`share_link=` 完整 URL
- 现有 `pan115_share_link` 列继续存在，但夸克条目此列为空，依赖 `share_link` + `cloud_type` 即可。
- **rebuild 流程必须覆盖该识别逻辑**（rebuild 是清空重建，已自动覆盖；增量同步 `runTgIndexIncremental` 也调用同一识别函数即可）。

**查询接口**：新增 `tg_index_service.get_movie_quark_resources(tmdb_id)` / `get_tv_quark_resources(tmdb_id)`，与现有 115 版本只差在 `WHERE cloud_type = ?` 的参数。

#### E.4 资源源适配的兼容性约束

- 现有 `/api/search/{movie|tv}/{id}/115/{pansou,hdhive,tg}` 的实现路径**完全不变**；只在三个底层 service 上加 `pan_type` / `cloud_types` 入参。
- 现有 `pan115_share_link` / `pan115_savable` 字段在 115 系列响应中保留原样。
- `tg_index` 老数据默认 `cloud_type="pan115"`，所有现有 115 查询不受影响。

## 前端设计

### F. 设置页夸克子区块（Settings.vue）

在 `Settings.vue` 的 tabs 列表中，**紧跟 `name="pan115"` 之后**新增 `name="quark"`：

```vue
<el-tab-pane label="夸克网盘" name="quark">
  <el-card class="settings-card">
    <template #header>
      <div class="card-header">
        <span>夸克网盘配置</span>
        <div class="status-tags">
          <el-tag v-if="quarkCookieStatus.valid" type="success" size="small">已连接</el-tag>
          <el-tag v-else-if="quarkCookieStatus.is_configured" type="warning" size="small">未验证</el-tag>
          <el-tag v-else type="info" size="small">未配置</el-tag>
        </div>
      </div>
    </template>

    <!-- 1. Cookie 输入 -->
    <el-form-item label="Cookie">
      <el-input v-model="quarkCookieDraft" type="textarea" :rows="3"
        :placeholder="'从浏览器复制夸克网盘 cookie...'" :show-password="!showQuarkCookiePlain" />
      <el-button @click="showQuarkCookiePlain = !showQuarkCookiePlain">
        {{ showQuarkCookiePlain ? '隐藏' : '显示' }}明文
      </el-button>
      <el-button type="primary" :loading="savingQuarkCookie" @click="handleSaveQuarkCookie">
        保存
      </el-button>
      <el-button :loading="checkingQuarkConnectivity" @click="handleCheckQuarkConnectivity">
        连通性检查
      </el-button>
    </el-form-item>

    <!-- 2. 默认转存目录 -->
    <el-form-item label="默认转存目录">
      <span>{{ quarkDefaultFolder.folder_name || '未选择' }}</span>
      <el-button @click="openQuarkFolderPicker" :disabled="!quarkCookieStatus.is_configured">
        浏览
      </el-button>
    </el-form-item>

    <!-- 3. 帮助文案：稳定性提示 -->
    <el-alert type="warning" :closable="false">
      夸克网盘转存能力依赖逆向接口，可能因官方接口调整而失效。
      若发现连通性检查失败，请重新从浏览器获取 Cookie 后保存。
    </el-alert>
  </el-card>

  <!-- 目录选择对话框 -->
  <QuarkFolderPickerDialog v-model:visible="quarkFolderPickerVisible"
    @selected="handleQuarkFolderSelected" />
</el-tab-pane>
```

新增组件 `frontend/src/components/quark/QuarkFolderPickerDialog.vue`：以 `el-tree` 形式异步加载夸克目录树（lazy load 子节点）；行为模型参考现有 115 的目录选择实现。

新增 API 客户端 `frontend/src/api/index.js`：

```javascript
export const quarkApi = {
  getCookieInfo: () => api.get('/quark/cookie'),
  checkCookie: () => api.get('/quark/cookie/check'),
  updateCookie: (cookie) => api.post('/quark/cookie/update', { cookie }),
  checkConnectivity: () => api.get('/quark/connectivity/check'),
  listFolders: (parentFid = '0', page = 1, size = 200) =>
    api.get('/quark/folders', { params: { parent_fid: parentFid, page, size } }),
  getDefaultFolder: () => api.get('/quark/default-folder'),
  setDefaultFolder: (folderId, folderName = '') =>
    api.post('/quark/default-folder', { folder_id: folderId, folder_name: folderName }),
  saveShareToFolder: (payload) =>
    api.post('/quark/share/save-to-folder', payload, { timeout: 180000 }),
}
```

### G. 详情页 Quark Tab

#### G.1 Tab 注册

`MovieDetail.vue` / `TvDetail.vue` / `DoubanDetail.vue` 三个文件的 `_visibleTabs` / `detailTabsForm` / `ALL_PAN115_CHILDREN` 类似的常量需扩展为同时支持 `quark`：

```javascript
// 详情页主 Tab 顺序
const DEFAULT_MAIN_ORDER = ['pan115', 'quark', 'magnet']

// 夸克子 Tab
const ALL_QUARK_CHILDREN = ['quark_pansou', 'quark_hdhive', 'quark_tg']

// detailTabsForm 扩展
const detailTabsForm = reactive({
  main_order: ['pan115', 'quark', 'magnet'],   // 改动
  pan115: true, pan115_children: [...],         // 不动
  quark: true,                                  // 新增 ★
  quark_children: ['quark_pansou', 'quark_hdhive', 'quark_tg'],  // 新增 ★
  magnet: true, magnet_children: [...],         // 不动
})
```

设置页的"详情页 Tab 显隐"配置区也需要新增一个"夸克网盘"分组（与 115 同结构）。这部分 UI 改动较小，复用现有 `subtab-order-list` 渲染。

#### G.2 Quark Tab 组件复用策略

新建 `frontend/src/components/detail/QuarkResourceTab.vue`：与现有详情页 Pan115 部分**结构同构**（el-tabs + 三个 el-table + 一键转存按钮），但所有数据 / API / 转存动作走夸克版本：

```vue
<script setup>
import { ref, computed, watch } from 'vue'
import { searchApi, quarkApi } from '@/api'
import { ElMessage } from 'element-plus'

const props = defineProps({
  mediaType: { type: String, required: true },  // 'movie' | 'tv'
  tmdbId: { type: [Number, String], required: true },
  visible: { type: Boolean, default: false },
  // 夸克 cookie 状态由父组件传入，控制按钮禁用态
  quarkConfigured: { type: Boolean, default: false },
})

const SOURCE_QUARK_APIS = {
  pansou: (type) => type === 'tv'
    ? searchApi.getTvQuarkPansou : searchApi.getMovieQuarkPansou,
  hdhive: (type) => type === 'tv'
    ? searchApi.getTvQuarkHdhive : searchApi.getMovieQuarkHdhive,
  tg: (type) => type === 'tv'
    ? searchApi.getTvQuarkTg : searchApi.getMovieQuarkTg,
}

const activeSubTab = ref('pansou')
const resources = reactive({ pansou: [], hdhive: [], tg: [] })
const loaded = reactive({ pansou: false, hdhive: false, tg: false })
const tried = reactive({ pansou: false, hdhive: false, tg: false })
const loading = reactive({ pansou: false, hdhive: false, tg: false })
const pager = reactive({ pansou: 1, hdhive: 1, tg: 1 })

// 懒加载：父组件 visible 切到 true 时才开始拉首批
watch(() => [props.visible, activeSubTab.value], async ([visible, sub]) => {
  if (!visible) return
  if (loaded[sub]) return
  await fetchResources(sub)
})

const fetchResources = async (sub, force = false) => {
  loading[sub] = true; tried[sub] = true
  try {
    const fn = SOURCE_QUARK_APIS[sub](props.mediaType)
    const { data } = await fn(props.tmdbId, 1, force)
    resources[sub] = Array.isArray(data?.list) ? data.list : []
    loaded[sub] = true
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '夸克资源加载失败')
  } finally { loading[sub] = false }
}

const isSaveDisabled = (row) => !props.quarkConfigured || row.cloud_savable === false
const saveResource = async (row) => {
  if (isSaveDisabled(row)) {
    ElMessage.warning('请先在设置页配置夸克 Cookie 与默认转存目录')
    return
  }
  row.saving = true
  try {
    const { data } = await quarkApi.saveShareToFolder({
      share_url: row.share_link,
      folder_name: row.title || row.name,
      tmdb_id: Number(props.tmdbId),
    })
    if (data?.success) {
      row.justSaved = true
      ElMessage.success(`已转存（共 ${data.item_count} 个文件）`)
    }
  } catch (e) {
    const code = e.response?.data?.code
    if (code === 'quark_default_dir_missing') { /* 弹窗 + 跳转设置 */ }
    else if (code === 'quark_cookie_invalid') { /* 弹窗提示重新获取 */ }
    else { ElMessage.error(e.response?.data?.detail || '夸克转存失败') }
  } finally { row.saving = false }
}
</script>
```

详情页接入：

```vue
<el-tab-pane v-if="key === 'quark'" name="quark">
  <template #label>
    <span>
      夸克网盘
      <el-tag v-if="!quarkConfigured" type="info" size="small" style="margin-left: 4px">未配置</el-tag>
    </span>
  </template>
  <QuarkResourceTab
    :media-type="mediaType" :tmdb-id="tmdbId"
    :visible="activeTab === 'quark'"
    :quark-configured="quarkConfigured"
  />
</el-tab-pane>
```

`quarkConfigured` 由详情页 `onMounted` 时调用 `quarkApi.getCookieInfo()` 获取（or 由全局 store 维护，避免每个详情页重复请求）。建议加一个简单 store：`useQuarkConfigStore`（pinia）或直接在 `Settings.vue` 保存后通过 event bus 通知；首期最简单做法就是详情页 mount 时拉一次 `getCookieInfo()`。

#### G.3 SearchApi 扩展

```javascript
// 与 115 系列保持完全相同的签名风格
getMovieQuarkPansou: (tmdbId, page = 1, refresh = false) =>
  api.get(`/search/movie/${tmdbId}/quark/pansou`, { params: { page, refresh } }),
getMovieQuarkHdhive: (tmdbId, page = 1, refresh = false) =>
  api.get(`/search/movie/${tmdbId}/quark/hdhive`, { params: { page, refresh } }),
getMovieQuarkTg: (tmdbId, page = 1, refresh = false) =>
  api.get(`/search/movie/${tmdbId}/quark/tg`, { params: { page, refresh } }),
getTvQuarkPansou: (tmdbId, page = 1, refresh = false, season = null) =>
  api.get(`/search/tv/${tmdbId}/quark/pansou`, { params: { page, refresh, season } }),
getTvQuarkHdhive: (tmdbId, page = 1, refresh = false, season = null) =>
  api.get(`/search/tv/${tmdbId}/quark/hdhive`, { params: { page, refresh, season } }),
getTvQuarkTg: (tmdbId, page = 1, refresh = false, season = null) =>
  api.get(`/search/tv/${tmdbId}/quark/tg`, { params: { page, refresh, season } }),
```

## 数据契约速查

### 资源条目（夸克接口返回的单条）

```jsonc
{
  "id": "pansou-abc123",                // 复用现有 ID 生成方式
  "title": "...",
  "name": "...",
  "size": "1.5GB",
  "share_link": "https://pan.quark.cn/s/abcdef",
  "cloud_type": "quark",                 // ★ 关键
  "cloud_savable": true,                 // ★ 控制按钮可点
  "cloud_save_disabled_reason": "",      // 空 / quark_cookie_missing / quark_cookie_invalid

  "source_service": "pansou",
  "media_type": "movie" | "tv" | "resource",

  // 兼容字段（夸克条目永远为 false / 空）
  "pan115_share_link": "",
  "pan115_savable": false,

  // 客户端态（前端附加）
  "saving": false,
  "justSaved": false
}
```

### Cookie 状态

```jsonc
GET /api/quark/cookie  →
{
  "is_configured": true,
  "preview": "abcd***wxyz",   // 仅首尾 4 字符
  "valid": true,              // 上次 check 结果
  "checked_at": "2026-05-20T12:34:56+08:00"
}
```

### 错误响应（统一）

```jsonc
{
  "detail": "夸克 Cookie 无效或已过期，请重新获取",
  "code": "quark_cookie_invalid"
}
```

## DB Migration 摘要

```sql
-- tg_index 表（生产已存在）：
ALTER TABLE tg_index
  ADD COLUMN cloud_type VARCHAR(16) NOT NULL DEFAULT 'pan115';
CREATE INDEX idx_tg_index_cloud_type ON tg_index(cloud_type);

-- runtime_settings.json：在启动期由 RuntimeSettingsService.apply_runtime_overrides 自动补默认值
--   "quark_cookie": ""
--   "quark_default_folder_id": "0"
--   "quark_default_folder_name": "根目录"
-- 不需要 DB DDL。
```

启动期的 `ensure_tables_exist`（`backend/app/core/database.py`）需要识别新列。沿用项目现有"ALTER 检测式" pattern，在导入模型时执行 `ALTER TABLE IF NOT EXISTS COLUMN ...`（对 SQLite 需 try/except `OperationalError("duplicate column")` 兼容）。

## 兼容性与回滚策略

| 维度 | 兼容性保障 |
|---|---|
| `Pan115Service` 行为 | 完全不动；新增模块独立路由前缀 |
| 现有 `pan115_share_link` / `pan115_savable` 字段 | 保留；夸克条目里这两个字段为空字符串 / `false` |
| `/api/search/{movie\|tv}/{id}/115/*` 接口 | 完全不变 |
| `tg_index` 表结构 | 仅新增列；老数据默认 `cloud_type="pan115"` |
| 设置页 `pan115` Tab | 完全不动；新增 `quark` Tab 在其后 |
| 详情页 `pan115` Tab | 完全不动；新增 `quark` Tab 通过新组件实现，不修改 `pan115` 渲染路径 |
| 探索页 / 搜索页 / 订阅资源列表 | 不接入夸克；零回归（属于 Out of Scope） |
| STRM / 归档 / 离线下载 / 订阅自动转存 | 不接入夸克；零回归 |
| 前端 `searchApi.getMoviePan115*` / 现有详情页 saveResource | 不动 |

**回滚路径**：

1. 关闭 dual-Tab：在 `Settings.vue` "详情页 Tab 显隐"配置中关闭"夸克网盘"主 Tab 即可；不影响数据。
2. 移除夸克：删除 `quark_*` 路由 / 文件 / runtime_settings 字段 / migration 列。

## 测试策略（轻量）

| 维度 | 测试方式 |
|---|---|
| `quark_service` 单元测试 | mock httpx，覆盖 `parse_share_url`、`save_share_to_folder` 成功 / 401 / 429 / 502 路径 |
| `quark_service` cookie 失效短路 | 设置 `_invalid_until`，验证下一次调用直接抛 `quark_cookie_invalid`，不真正触发 httpx 调用 |
| 三源夸克接口集成 | 用 `respx` 或 monkeypatch `pansou_service.search` 返回固定 payload，断言响应里 `cloud_type=quark` |
| `tg_index_service` 夸克识别 | 给定包含 `pan.quark.cn` 链接的 message，断言落库 `cloud_type=quark` |
| Migration | 在 SQLite 临时数据库上执行迁移函数两次，验证幂等 |
| 兼容性 | 跑现有 115 测试套件 (`tests/test_search.py`、`tests/test_*pan115*`) 全部通过 |
| 前端 smoke | `tests/smoke/explore-detail.spec.js` 增加：进入详情页 → 切到夸克 Tab → 看到三个子 Tab；点一键转存（cookie 未配置）→ 看到禁用提示 |

不在本期内：夸克真实账号端到端测试（依赖 cookie），由开发者本地 PoC 验证。

## 实施顺序建议

1. **后端 QuarkService 骨架 + cookie/connectivity 接口**（`/api/quark/cookie/*`、`/api/quark/connectivity/check`）→ 设置页 cookie 子区块 → 端到端跑通"保存 → 检查"。
2. **后端目录浏览 + 默认目录持久化**（`/api/quark/folders`、`/api/quark/default-folder`）→ 设置页"浏览"对话框。
3. **后端三源夸克接口**（pansou / hdhive / tg；包括 tg_index 迁移）。
4. **后端转存接口**（`/api/quark/share/save-to-folder`）。
5. **前端 `QuarkResourceTab.vue` + 三个详情页 Tab 注册**。
6. **设置页详情页 Tab 显隐配置扩展**。
7. **冒烟测试 + Docker 部署 + 在浏览器实际验证**。

每个阶段独立可发布，便于回滚。
