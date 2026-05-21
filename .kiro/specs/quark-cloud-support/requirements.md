# Requirements Document

## Introduction

MediaSync115 当前以 115 网盘为唯一的云存储后端，详情页（`MovieDetail.vue` / `TvDetail.vue` / `DoubanDetail.vue`）的"115 网盘"主 Tab 下汇聚了 Pansou、HDHive、Telegram 三个资源源的 115 链接，并支持一键转存到 115 默认目录。三个源在底层（`pansou_service` / `hdhive_service` / `tg_index_service`）实际上已经能够识别夸克网盘的分享链接，但目前一律被按 `pan115_savable=false` 过滤掉，用户即便有夸克账号也无法在 MediaSync115 内部完成夸克转存。

本期需求**严格限定为两件事**：

1. **设置页支持配置夸克网盘 Cookie**：用户在设置页粘贴夸克 Cookie，系统持久化到运行时配置并支持连通性检查。
2. **详情页新增"夸克网盘"主 Tab**：在影视详情页（包括 TMDB 与豆瓣详情页）增加一个与"115 网盘"同级的主 Tab，下方同样按 Pansou / HDHive / Telegram 三个子 Tab 展示**夸克网盘**的资源，并支持对每条夸克分享一键转存到夸克盘默认目录。

本期通过新增独立的 `QuarkService`、扩展现有资源源接口的"网盘类型"维度（保持 115 行为不变），并在前端复用与 115 Tab 同结构的 Vue 组件来实现，目标是**最小侵入**。本期不涉及订阅自动转存、STRM、归档监听、探索页 / 搜索页夸克资源接入等更高阶能力，这些将在后续 Phase 通过逐步抽象完成。

## Glossary

- **MediaSync115**: 当前后端 + 前端整体应用，运行于 FastAPI（后端）+ Vue 3（前端）。
- **System**: MediaSync115 整体后端服务（用作 EARS 中的默认主体当行为跨多个模块时）。
- **Pan115Service**: 现有的 115 网盘服务模块（`backend/app/services/pan115_service.py`），本期不修改其行为。
- **QuarkService**: 本期新增的夸克网盘服务模块（`backend/app/services/quark_service.py`），封装夸克网盘 cookie 管理、连通性检查、分享解析与转存等接口。
- **Settings_Page**: 前端 `/settings` 设置页面，本期需新增"夸克网盘"子区块。
- **Quark_Cookie**: 用户从浏览器手动复制粘贴的夸克网盘登录 Cookie 字符串，由用户负责维护。
- **Quark_Default_Dir**: 用户在设置页中选定的夸克网盘默认转存目录，由夸克侧目录 ID（`fid` / `pdir_fid` 等等价标识）和显示路径组成。
- **Quark_Share_Link**: 形如 `https://pan.quark.cn/s/{share_id}` 的夸克分享链接（可能附带提取码）。
- **Detail_Page**: 影视详情页，包括 `MovieDetail.vue`、`TvDetail.vue`、`DoubanDetail.vue` 三个页面。
- **Pan115_Tab**: 现有详情页中名为"115 网盘"的主 Tab，下方含 Pansou / HDHive / Telegram 三个子 Tab。
- **Quark_Tab**: 本期新增、与 Pan115_Tab 在详情页内同级的"夸克网盘"主 Tab，下方含 Pansou / HDHive / Telegram 三个子 Tab。
- **Resource_Source**: 资源源（Pansou、HDHive、Telegram 索引），现已存在并对 115 资源做过滤；本期需要扩展成可按"网盘类型"切换。
- **Operation_Log_Service**: 现有 `operation_log_service` 模块，用于记录用户级关键操作日志。
- **Runtime_Settings_Service**: 现有 `runtime_settings_service` 模块，用于持久化运行时配置（如 PAN115_COOKIE）。

## Requirements

### Requirement 1: 夸克网盘 Cookie 配置入口

**User Story:** 作为 MediaSync115 用户，我想在设置页粘贴我的夸克网盘 Cookie 并保存，以便系统能用我的账号执行转存。

#### Acceptance Criteria

1. THE Settings_Page SHALL 在"网盘设置"区块下展示一个独立的"夸克网盘"子区块，与现有"115 网盘"子区块并列。
2. THE Settings_Page SHALL 在"夸克网盘"子区块中提供一个多行文本输入框，用于接收 Quark_Cookie 字符串，并提供"显示 / 隐藏明文"切换按钮以避免误操作时凭证暴露。
3. WHEN 用户在"夸克网盘"子区块中点击"保存"按钮，THE System SHALL 通过 Runtime_Settings_Service 将该 Cookie 持久化为运行时配置项 `QUARK_COOKIE`。
4. THE System SHALL 在向客户端返回任意配置接口响应时，对 `QUARK_COOKIE` 的值进行脱敏（仅返回首尾各 4 字符或仅返回 `is_configured: true/false`），不返回完整 Cookie 原文。
5. IF 用户提交的 Quark_Cookie 为空字符串或仅包含空白字符，THEN THE System SHALL 返回 HTTP 400 错误并提示"夸克 Cookie 不能为空"。
6. WHEN 用户成功保存 Quark_Cookie，THE Operation_Log_Service SHALL 记录一条类型为 `quark_cookie_updated` 的操作日志，且日志中不包含 Cookie 原文。
7. THE System SHALL 支持通过环境变量 `QUARK_COOKIE` 注入初始 Cookie，并在容器启动时加载到 Runtime_Settings_Service。

### Requirement 2: 夸克网盘连通性检查

**User Story:** 作为用户，我想在保存夸克 Cookie 后立即验证其有效性，以便确认配置成功而不必等到第一次转存才发现失败。

#### Acceptance Criteria

1. THE Settings_Page SHALL 在"夸克网盘"子区块提供一个"连通性检查"按钮，行为模式与现有"115 网盘"子区块的连通性检查按钮保持一致。
2. WHEN 用户点击"连通性检查"按钮，THE System SHALL 通过 QuarkService 调用一个轻量级的夸克账号查询接口（如获取用户信息或根目录列表），且单次调用不超过 15 秒。
3. WHEN 连通性检查请求返回有效响应，THE System SHALL 在前端展示"连接成功"提示，并展示从夸克接口获取到的可识别用户标识（如昵称、UID 后缀或可用空间），不展示 Cookie 原文。
4. IF 连通性检查请求返回鉴权失败或 Cookie 已过期的响应，THEN THE System SHALL 返回 HTTP 401 错误并提示"夸克 Cookie 无效或已过期，请重新获取"。
5. IF 连通性检查请求由于网络异常或夸克接口 5xx 错误失败，THEN THE System SHALL 返回 HTTP 502 错误并提示"无法连接夸克网盘，请稍后重试"。
6. THE System SHALL 在连通性检查的请求和响应日志中均不输出 Quark_Cookie 原文，只能输出脱敏后的标识。

### Requirement 3: 夸克网盘默认转存目录配置

**User Story:** 作为用户，我想在设置页指定一个夸克网盘的默认转存目录，以便详情页的"一键转存"动作有明确的目的地。

#### Acceptance Criteria

1. THE Settings_Page SHALL 在"夸克网盘"子区块提供一个"默认转存目录"字段，展示当前已选目录的显示路径。
2. WHEN 用户点击"默认转存目录"旁的"浏览"按钮，THE System SHALL 弹出夸克网盘目录选择对话框，并通过 QuarkService 加载夸克网盘的根目录列表。
3. WHEN 用户在目录选择对话框中点击某个目录节点，THE System SHALL 通过 QuarkService 加载该节点的子目录并展开，单次返回条目数不超过 500，超出时分页返回。
4. WHEN 用户在目录选择对话框中确认选择某个目录，THE System SHALL 通过 Runtime_Settings_Service 将该目录的夸克侧目录 ID 与显示路径持久化为运行时配置项 `QUARK_DEFAULT_DIR`。
5. IF 用户在 Quark_Cookie 未配置或无效的情况下点击"浏览"按钮，THEN THE System SHALL 返回 HTTP 401 错误并在前端弹窗提示"请先在上方配置有效的夸克 Cookie"。
6. WHEN 目录列表请求超过 15 秒未返回，THE System SHALL 中止请求并提示"夸克目录加载超时，请稍后重试"。
7. WHILE Quark_Default_Dir 未配置（首次保存 Cookie 后尚未选择目录），THE Detail_Page 上的"一键转存"动作 SHALL 弹出 toast 提示"请先在设置页选择夸克默认转存目录"，不发起后端请求。

### Requirement 4: 详情页"夸克网盘"主 Tab 与三源子 Tab 结构

**User Story:** 作为用户，我希望在影视详情页里有一个"夸克网盘" Tab，结构与"115 网盘" Tab 一模一样地按 Pansou / HDHive / Telegram 三个子 Tab 展示资源，以便我能用同样的心智模型操作夸克资源。

#### Acceptance Criteria

1. THE Detail_Page（包括 `MovieDetail.vue`、`TvDetail.vue`、`DoubanDetail.vue` 三个页面）SHALL 在主 Tab 列表中新增一个名为"夸克网盘"的主 Tab，位置紧邻现有"115 网盘" Tab 之后。
2. THE Quark_Tab SHALL 在内部包含三个子 Tab：`Pansou`、`HDHive`、`Telegram`，与 Pan115_Tab 的子 Tab 命名、顺序、空状态文案模式完全一致。
3. WHEN 用户在 Detail_Page 上首次切换到 Quark_Tab，THE System SHALL 仅加载当前活跃子 Tab（默认 Pansou）的夸克资源，不预先加载其余两个子 Tab，避免一次性发起 3 个请求。
4. WHEN 用户在 Quark_Tab 内切换子 Tab，THE System SHALL 调用对应资源源的"夸克"专用后端接口加载数据，并对每个子 Tab 内的结果使用与 Pan115_Tab 同样的分页（默认 `pan115PageSize`）。
5. THE Quark_Tab SHALL 在每个子 Tab 中展示资源列表表格，列结构（资源名称、来源、大小、操作列）与 Pan115_Tab 同构。
6. THE Quark_Tab SHALL 在用户切换到该 Tab 之前不发起任何夸克侧请求；首次切入时才触发首批资源加载（懒加载）。
7. WHEN 用户在 Detail_Page 间切换（例如从豆瓣详情跳转到 TMDB 详情），THE Quark_Tab SHALL 在新的 Detail_Page 上保持与 Pan115_Tab 一致的"重置已加载状态、按需重新加载"行为。
8. THE Quark_Tab SHALL 在 Tab 标题旁显示一个小标识标签（如"夸克"或夸克 logo），以便用户在快速切换时能与 115 Tab 视觉区分。
9. WHILE Quark_Cookie 未配置或 QuarkService 在最近一次实际调用中检测到 Cookie 失效，THE Quark_Tab SHALL 在 Tab 标题旁额外展示一个灰色"未配置"角标（与第 8 条的"夸克"标识并列），点击角标 SHALL 跳转至 Settings_Page 的"夸克网盘"子区块。
10. WHEN 用户在 Settings_Page 成功保存 Quark_Cookie 后回到 Detail_Page，THE Quark_Tab SHALL 在下一次进入或刷新时移除"未配置"角标。

### Requirement 5: Pansou 子源夸克资源后端接口

**User Story:** 作为后端，我需要提供 `/movie/{id}/quark/pansou`、`/tv/{id}/quark/pansou` 等接口返回夸克网盘 Pansou 资源，使 Quark_Tab 能加载数据。

#### Acceptance Criteria

1. THE System SHALL 在后端新增 `GET /api/search/movie/{tmdb_id}/quark/pansou` 与 `GET /api/search/tv/{tmdb_id}/quark/pansou` 两个接口，参数与 `/115/pansou` 系列保持一致（`page`、`refresh`、TV 多 `season`）。
2. WHEN Pansou 子源夸克接口被调用，THE System SHALL 在底层 `pansou_service.search` 调用中传入 `cloud_types=["quark"]`，使 Pansou 仅返回夸克网盘资源。
3. THE System SHALL 在返回的每条资源记录上同时附加 `cloud_type: "quark"` 与 `quark_share_link` 字段（替代 115 接口里的 `pan115_share_link`），并保留 `cloud_savable` 字段表征该资源是否能被当前夸克 Cookie 转存。
4. WHILE Quark_Cookie 未配置或检测为无效，THE System SHALL 在响应中将所有夸克资源的 `cloud_savable` 字段置为 `false`，并附加原因码 `quark_cookie_missing` 或 `quark_cookie_invalid`。
5. THE System SHALL 复用 `_movie_pan115_cache` / `_tv_pan115_cache` 同等的内存缓存策略，但使用独立的缓存命名空间（如 `_movie_quark_cache`），避免与 115 缓存冲突。
6. THE System SHALL 在 Pansou 接口失败（网络 / 5xx）时返回 HTTP 502 与 `attempts: [{service: "pansou", status: "error", error: "..."}]` 结构，前端可据此显示"暂无可用夸克网盘资源"。
7. THE System SHALL 在响应中保留与 115 系列接口相同的关键字字段（`keyword`、`attempted_keywords`、`keyword_hit_index`），便于前端复用展示组件。

### Requirement 6: HDHive 子源夸克资源后端接口

**User Story:** 作为后端，我需要提供 `/movie/{id}/quark/hdhive`、`/tv/{id}/quark/hdhive` 接口返回 HDHive 上的夸克分享，使 Quark_Tab 的 HDHive 子 Tab 能加载数据。

#### Acceptance Criteria

1. THE System SHALL 在后端新增 `GET /api/search/movie/{tmdb_id}/quark/hdhive` 与 `GET /api/search/tv/{tmdb_id}/quark/hdhive` 两个接口，参数与 `/115/hdhive` 系列保持一致。
2. THE System SHALL 在 `hdhive_service.get_movie_pan115_result` / `get_tv_pan115_result` 旁新增等价的 `get_movie_quark_result` / `get_tv_quark_result` 方法（或扩展现有方法增加 `pan_type` 入参），由该方法按 `pan_type == "quark"`（或 HDHive 实际使用的字段名）筛选原始资源。
3. THE System SHALL 在返回的每条资源记录上附加 `cloud_type: "quark"` 与 `quark_share_link` 字段，且字段语义与 Requirement 5 一致。
4. THE System SHALL 在 HDHive 响应中返回 `quark_diagnostics: { raw_total, filtered_quark_total, pan_type_counts }` 结构，用于前端在空状态下显示原始总数与按网盘类型分布。
5. THE System SHALL 在 HDHive Cookie / API Key 未配置时返回 HTTP 412 错误，错误体中包含原因码 `hdhive_not_configured`，与 115 接口在该场景下的行为一致。
6. WHEN HDHive 接口被调用，THE System SHALL 不修改现有 115 HDHive 接口的行为或返回结构。

### Requirement 7: Telegram 子源夸克资源后端接口

**User Story:** 作为后端，我需要提供 `/movie/{id}/quark/tg`、`/tv/{id}/quark/tg` 接口返回 TG 索引中的夸克分享，使 Quark_Tab 的 Telegram 子 Tab 能加载数据。

#### Acceptance Criteria

1. THE System SHALL 在后端新增 `GET /api/search/movie/{tmdb_id}/quark/tg` 与 `GET /api/search/tv/{tmdb_id}/quark/tg` 两个接口，参数与 `/115/tg` 系列保持一致。
2. THE System SHALL 在 TG 索引匹配阶段对原始 message 文本同时进行 115 与夸克的链接识别：当匹配到 `pan.quark.cn/s/...` 域名（或夸克分享码格式）时，将 `cloud_type` 标注为 `"quark"`，提取链接放入 `quark_share_link` 字段。
3. THE System SHALL 在 TG 夸克接口的返回中仅包含 `cloud_type == "quark"` 的资源条目，且字段语义与 Requirement 5 一致。
4. THE System SHALL 在 TG 索引数据库表中**新增 `cloud_type` 字段**（默认 `"pan115"`，老数据迁移时回填），且**继续复用既有的通用 `share_link` 列**存放原始链接（115 或夸克），不为夸克新增独立的 `quark_share_link` 列；查询时通过 `cloud_type` 区分。
5. WHEN TG 索引尚未建立或 TG Bot 未登录，THE System SHALL 返回与 115 TG 接口同样的错误码 / 提示语（不引入新错误码）。
6. THE System SHALL 不破坏现有 `pan115_share_link` 在 TG 接口里的语义；115 链接的条目继续在 `/tg` 系列接口里返回。

### Requirement 8: 夸克分享一键转存（详情页内）

**User Story:** 作为用户，我希望在详情页 Quark_Tab 的资源行上点"一键转存"按钮就能把该夸克分享保存到我夸克盘的默认目录，以便我不用打开夸克 app 手动操作。

#### Acceptance Criteria

1. WHEN 用户在 Quark_Tab 的资源表格中点击某行的"一键转存"按钮，THE System SHALL 调用 `POST /api/quark/share/save-to-folder` 接口，请求体包含 `share_url`、目标目录 ID（默认取 Quark_Default_Dir）以及（如有）资源标题作为子目录名。
2. THE System SHALL 在 `quark_service.save_share_to_folder` 中实现以下流程：解析夸克分享 URL → 拉取分享内文件列表 → 在目标父目录下创建以资源标题命名的子目录（与 115 行为对齐） → 将分享内全部文件转存到该子目录。
3. WHERE 用户的夸克侧分享带提取码（在 URL 内或资源记录里有 `quark_receive_code`），THE System SHALL 在转存时自动携带提取码。
4. WHEN 一次夸克转存请求成功完成，THE Operation_Log_Service SHALL 记录一条类型为 `quark_save` 的操作日志，包含资源标题、分享链接（脱敏处理 share_id 即可）、目标目录路径、转存项数量。
5. WHEN 转存请求成功，THE Detail_Page SHALL 在该资源行展示与 115 转存一致的"已转存"标记 / 短暂动效。
6. THE System SHALL 在夸克转存接口实现中使用异步 IO（沿用现有 115 服务的 `async/await` 模式），不得阻塞 FastAPI 主事件循环；单次接口超时阈值不超过 180 秒（与 115 `SAVE_OPERATION_TIMEOUT` 对齐）。
7. IF 转存请求因 Quark_Cookie 过期失败，THEN THE System SHALL 返回 HTTP 401 错误并提示"夸克 Cookie 无效或已过期，请重新获取"。
8. IF 转存请求因夸克接口限流（HTTP 429 或等价业务错误码）失败，THEN THE System SHALL 返回 HTTP 429 错误并提示"夸克网盘繁忙，请稍后重试"。
9. IF 转存请求因夸克接口返回 5xx 或网络异常失败，THEN THE System SHALL 返回 HTTP 502 错误并提示"夸克转存失败，请检查链接或稍后重试"。
10. IF Quark_Default_Dir 未配置且请求体未指定目标目录，THEN THE System SHALL 返回 HTTP 412 错误，原因码 `quark_default_dir_missing`，前端弹窗提示并提供"前往设置"跳转按钮。

### Requirement 9: 转存按钮的禁用态与降级提示

**User Story:** 作为用户，我希望即使我没配置夸克 Cookie，详情页 Quark_Tab 的资源也仍然可见且能告诉我为什么不能转存，以便我决定是否要去配置。

#### Acceptance Criteria

1. WHILE Quark_Cookie 未配置或被 QuarkService 标记为 invalid，THE Quark_Tab 上每行资源的"一键转存"按钮 SHALL 处于禁用态，并在悬停提示中显示"请先在设置页配置夸克 Cookie"。
2. WHEN 用户在禁用态下点击"一键转存"按钮，THE Detail_Page SHALL 弹出 toast 提示并提供"前往设置"按钮，跳转至 Settings_Page 的"夸克网盘"子区块。
3. THE Quark_Tab SHALL 在禁用态下保留资源信息（标题、来源、大小、链接）可见，仅禁用"一键转存"按钮，不隐藏整条资源记录。
4. IF QuarkService 在最近一次实际调用中检测到 Cookie 失效，THEN THE System SHALL 在内存中将该 Cookie 标记为 invalid，并在后续 5 分钟内对该 Cookie 的目录浏览 / 分享解析 / 转存请求直接返回 401，不再发起远程调用。
5. WHEN 用户在 Settings_Page 重新保存 Quark_Cookie，THE System SHALL 立即清除上述 invalid 标记并在下一次请求中重新尝试夸克接口。

### Requirement 10: 与 115 现有功能的兼容性约束

**User Story:** 作为现有 115 用户，我希望升级到支持夸克的新版本后，所有现有 115 行为完全保持不变。

#### Acceptance Criteria

1. THE System SHALL 在所有现有以 `pan115_share_link` / `pan115_savable` 为字段名的 API 响应中继续保留这两个字段，且其语义与升级前一致。
2. THE Pan115_Tab 在 Detail_Page 上的位置、子 Tab 顺序、按钮文案、转存行为 SHALL 与升级前完全一致；不允许因新增 Quark_Tab 而修改 Pan115_Tab 的代码路径。
3. THE Pan115Service SHALL 在本期内保持调用接口、返回结构、副作用完全不变，禁止本期重构其内部实现。
4. WHILE 用户的 Quark_Cookie 未配置，THE System SHALL 保证 115 资源在详情页的展示与转存行为与升级前一致。
5. THE System SHALL 在订阅自动转存、STRM 生成、归档监听、离线下载监听、探索页 / 搜索结果页等本期不在范围内的流程中，继续仅使用 Pan115Service，禁止引入对 QuarkService 的调用。
6. WHEN 数据库迁移涉及 TG 索引表新增 `cloud_type` 字段时，THE System SHALL 仅以新增列方式承载（默认值 `"pan115"`），禁止修改或删除现有列；老数据回填默认值。

### Requirement 11: 安全与敏感信息脱敏

**User Story:** 作为用户，我不希望我的夸克 Cookie 出现在日志或 API 响应中，以避免凭证泄露。

#### Acceptance Criteria

1. THE System SHALL 在所有日志输出（应用日志、操作日志、错误日志）中以掩码替换 Quark_Cookie 原文，仅允许保留首尾各 4 字符做问题定位。
2. THE System SHALL 在所有对外 API 响应（包括设置接口、调试接口、错误响应）中以"是否已配置"的布尔值或脱敏字符串表示 Quark_Cookie 状态，不返回 Cookie 原文。
3. WHEN 后端发起夸克接口的远程调用，THE System SHALL 仅在 HTTP 请求头中携带 Quark_Cookie，不将其写入请求体、URL 查询参数或日志。
4. WHERE 部署在容器环境通过环境变量 `QUARK_COOKIE` 注入初始 Cookie，THE System SHALL 在启动日志中不回显 Cookie 原文。

### Requirement 12: 性能与异步约束

**User Story:** 作为用户，我希望夸克转存等操作不会让前端长时间转圈或阻塞其他操作。

#### Acceptance Criteria

1. THE System SHALL 在 QuarkService 内部对所有远程 HTTP 调用使用异步 IO（如 `httpx.AsyncClient`），且每次调用配置不超过 30 秒的超时阈值（转存操作除外，参见 Requirement 8.6）。
2. WHEN 夸克转存涉及单次分享内超过 50 个文件，THE System SHALL 通过批量接口（或后端分片调用）完成，避免前端发起 50 次串行 HTTP 请求。
3. THE System SHALL 在夸克目录浏览接口中，对单次请求返回的目录条目数量设置不超过 500 的上限，超出时分页返回。
4. THE Quark_Tab 在前端上 SHALL 对每个子 Tab 的资源加载使用懒加载（首次切入子 Tab 才触发请求），避免主 Tab 切换时触发 3 个并发请求。

### Requirement 13: 操作日志与可观测性

**User Story:** 作为用户，我希望能在操作日志页查到所有夸克相关的关键操作，以便排查问题。

#### Acceptance Criteria

1. WHEN 用户成功保存 Quark_Cookie，THE Operation_Log_Service SHALL 记录类型为 `quark_cookie_updated` 的日志条目。
2. WHEN 用户成功完成一次夸克连通性检查，THE Operation_Log_Service SHALL 记录类型为 `quark_connectivity_check` 的日志条目，包含检查结果（成功 / 失败原因码）。
3. WHEN 用户成功完成一次夸克转存，THE Operation_Log_Service SHALL 记录类型为 `quark_save` 的日志条目，包含目标目录、转存项数量、源分享链接（share_id 部分可保留）。
4. IF 任意夸克接口调用失败，THEN THE Operation_Log_Service SHALL 记录一条 `quark_error` 日志条目，包含错误码与失败接口名（不含 Cookie 原文，不含完整 stack trace）。

## Out of Scope

以下能力**不在本期需求范围内**，将在后续 Phase 单独立项：

1. **搜索结果页 / 探索页 / 订阅资源列表展示夸克资源**：本期夸克资源仅在影视详情页 Quark_Tab 内出现。搜索结果页、探索页、订阅资源列表仍按现有 115-only 逻辑展示。
2. **订阅自动转存到夸克**：本期订阅自动转存仍只走 115，不支持按订阅配置目标网盘或自动选择网盘。
3. **STRM 走夸克**：本期 STRM 生成仍只对 115 网盘文件生效；夸克侧文件直链 / 流式播放需要专门 PoC。
4. **夸克归档监听 / 离线下载**：现有归档与离线下载监听只覆盖 115，本期不扩展到夸克。
5. **TV 剧集"按勾选转存"对话框**：详情页 Pan115_Tab 在剧集场景下提供"按勾选项转存"次级按钮；本期 Quark_Tab 仅提供"一键转存（整个分享）"，不实现勾选转存。该能力在 Phase 2 评估。
6. **夸克网盘内文件管理 UI**：本期不提供"重命名 / 删除 / 移动"等管理动作；只提供"浏览目录"（限设置页选目录）和"一键转存"。
7. **夸克扫码登录**：本期 Cookie 由用户手动从浏览器复制粘贴；不实现扫码登录、不实现 Cookie 自动续期。
8. **完整的字段重命名（pan115_\* → cloud_\*）**：本期仅在 Quark_Tab 相关接口中使用 `quark_share_link` / `cloud_type` / `cloud_savable` 等新字段；不重构现有 115 接口的字段命名。
9. **云盘抽象层（统一 Provider 接口）**：本期不引入 `BaseCloudService` 抽象；业务侧通过新增独立后端接口与独立 Vue 组件实现 dual-provider 共存。抽象层等到 Phase 2 至少有 2 个 provider 都需要被订阅 / STRM 等流程消费时再做。
10. **跨网盘资源去重**：当同一影片同时存在 115 和夸克分享时，不在本期做合并 / 去重 / 优先级选择，两个 Tab 各自展示。
11. **Quark_Tab 内的"复合源（all）"视图**：Pan115_Tab 历史上有过 pansou + hdhive + tg 合并入口；本期 Quark_Tab 只提供按子源分别浏览，不实现合并视图。
12. **夸克下载链接获取（用于本地下载）**：本期不提供从夸克获取直链下载文件的能力。

## Risk & Open Questions

### 风险

1. **夸克接口稳定性风险（高）**：夸克网盘官方未公开转存 API，本期实现依赖逆向接口（参考 `quark-auto-save` 等社区项目）。一旦夸克侧调整接口签名、风控策略或加密参数，本期能力可能在无任何代码改动的情况下失效。**缓解措施**：
   - QuarkService 实现层与业务层解耦，便于后续替换底层调用；
   - 在错误处理路径里把"未知接口错误"清晰区分为 `quark_api_unstable`，便于运营观察；
   - 在 README / 设置页文案中提示用户该能力依赖逆向接口、可能不稳定。

2. **Cookie 维护成本风险（中）**：夸克 Cookie 有效期较短，且涉及多个子域，用户复制粘贴时容易遗漏字段。**缓解措施**：
   - 提供"连通性检查"按钮帮助用户立即验证；
   - Cookie 失效时给出明确文案"请重新获取并粘贴 Cookie"；
   - 文档中给出完整的 Cookie 字段清单和获取步骤。

3. **限流与封号风险（中）**：批量转存可能触发夸克的频控甚至账号风控。**缓解措施**：
   - 单次批量转存调用之间引入退避；
   - 对 HTTP 429 / 风控错误显式返回 429 给前端，提醒用户稍后重试；
   - 不在订阅服务里启用夸克自动转存（已通过 Out of Scope 第 2 条约束）。

4. **TG 索引数据迁移风险（中）**：TG 索引表此前只对 115 链接做了索引，本期需要让 TG 索引同时识别并存储夸克链接。**缓解措施**：
   - 新增 `cloud_type` 字段时仅以新增列方式落库，老数据默认 `"pan115"`；
   - TG 索引重建（rebuild）流程在本期内必须能正确给夸克链接条目写入 `cloud_type = "quark"`；
   - 增量同步路径（`runTgIndexIncremental`）也必须覆盖该识别逻辑。

5. **HDHive 资源类型字段不确定（中）**：HDHive 原始返回的 `pan_type` 字段是否对夸克使用统一的字符串值（如 `"quark"`、`"夸克"`）尚未确认。**缓解措施**：实现前先抓取一次 HDHive 真实响应核对，在 `quark_service` 或 hdhive 适配层使用归一化函数处理多种可能值。

### Open Questions

> 已确认决策（用户拍板）：
> - **TG 索引表的链接列**：采用"通用 `share_link` + `cloud_type` 区分"的形式，不为每种网盘单独建列。已落入 Requirement 7.4。
> - **Quark_Tab 在 Cookie 未配置时的视觉提示**：Tab 标题旁展示灰色"未配置"角标，点击跳转设置页。已落入 Requirement 4.9 / 4.10。

剩余待实现期确认：

1. **夸克侧的目录 ID 形态**：夸克目录 ID（`fid` / `pdir_fid`）是否能像 115 的 `cid` 一样作为长期稳定的引用？还是说每次会话需要重新解析？（影响 `QUARK_DEFAULT_DIR` 的持久化方案。）
2. **夸克分享是否始终允许游客查看文件列表**：是否所有公开分享都能在不登录情况下解析？带提取码的分享需要单独流程吗？（直接影响 Requirement 8 的实现。）
3. **多账号支持**：本期是否需要支持"多个夸克账号"？目前默认只支持单账号（一个 `QUARK_COOKIE`）。如果用户提出多账号需求，需要单独立项。
4. **HDHive 原始返回里夸克的 `pan_type` 字段值**：是 `"quark"` / `"夸克"` / 其他？需要在实现 Requirement 6 时先抓一次 HDHive 真实响应核对，必要时在适配层加归一化。
