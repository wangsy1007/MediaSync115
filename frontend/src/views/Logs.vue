<template>
  <div class="logs-page">
    <div class="page-header">
      <h2>日志中心</h2>
      <div class="filters">
        <el-select v-model="filters.sourceType" clearable placeholder="类型" class="filter-item">
          <el-option v-for="item in sourceTypeOptions" :key="item" :label="translateLabel(item, sourceTypeLabels)" :value="item" />
        </el-select>
        <el-select v-model="filters.module" clearable placeholder="模块" class="filter-item">
          <el-option v-for="item in moduleOptions" :key="item" :label="translateLabel(item, moduleLabels)" :value="item" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="状态" class="filter-item">
          <el-option v-for="item in statusOptions" :key="item" :label="translateLabel(item, statusLabels)" :value="item" />
        </el-select>
        <el-input v-model.trim="filters.path" clearable placeholder="路径包含..." class="filter-item filter-item-wide" />
        <el-input v-model.trim="filters.traceId" clearable placeholder="Trace ID" class="filter-item filter-item-wide" />
        <el-date-picker
          v-model="filters.dateRange"
          type="datetimerange"
          unlink-panels
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          class="filter-item filter-item-date"
        />
        <el-input-number v-model="filters.limit" :min="20" :max="500" :step="20" />
        <el-button type="primary" :loading="loading" @click="handleSearch">刷新</el-button>
      </div>
    </div>

    <el-card class="summary-card">
      <div class="summary-tags">
        <el-tag type="success">成功 {{ summary.success || 0 }}</el-tag>
        <el-tag type="warning">警告 {{ summary.warning || 0 }}</el-tag>
        <el-tag type="danger">失败 {{ summary.failed || 0 }}</el-tag>
        <el-tag type="info">信息 {{ summary.info || 0 }}</el-tag>
        <span class="summary-total">总计 {{ total }}</span>
      </div>
    </el-card>

    <el-card>
      <div class="table-wrap">
        <el-table :data="logs" v-loading="loading" size="small">
          <el-table-column type="expand" width="44">
            <template #default="{ row }">
              <div class="log-detail">
                <div class="log-detail__block">
                  <div class="log-detail__title">详细说明</div>
                  <pre>{{ row.message || '-' }}</pre>
                </div>
                <div class="log-detail__block">
                  <div class="log-detail__title">请求详情</div>
                  <pre>{{ formatSummaryBlock(row.request_summary) }}</pre>
                </div>
                <div class="log-detail__block">
                  <div class="log-detail__title">响应详情</div>
                  <pre>{{ formatSummaryBlock(row.response_summary) }}</pre>
                </div>
                <div class="log-detail__block">
                  <div class="log-detail__title">额外信息</div>
                  <pre>{{ formatSummaryBlock(row.extra) }}</pre>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="时间" min-width="170" :formatter="formatBeijingTableCell" />
          <el-table-column label="类型" width="130">
            <template #default="{ row }">{{ translateLabel(row.source_type, sourceTypeLabels) }}</template>
          </el-table-column>
          <el-table-column label="模块" width="120">
            <template #default="{ row }">{{ translateLabel(row.module, moduleLabels) }}</template>
          </el-table-column>
          <el-table-column label="动作" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">{{ translateAction(row.action) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ translateLabel(row.status, statusLabels) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="HTTP" min-width="180">
            <template #default="{ row }">
              <span>{{ formatHttpCell(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="duration_ms" label="耗时(ms)" width="110" />
          <el-table-column label="说明" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <span>{{ formatMessage(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="trace_id" label="Trace ID" min-width="230" show-overflow-tooltip />
          <el-table-column label="请求摘要" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <span>{{ stringifySummary(row.request_summary) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="响应摘要" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <span>{{ stringifySummary(row.response_summary) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="额外信息" min-width="280" show-overflow-tooltip>
            <template #default="{ row }">
              <span>{{ stringifySummary(row.extra) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager-wrap">
        <el-pagination
          background
          layout="prev, pager, next, jumper, total"
          :total="total"
          :current-page="currentPage"
          :page-size="filters.limit"
          @current-change="handlePageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { logsApi } from '@/api'
import { formatBeijingTableCell } from '@/utils/timezone'

const sourceTypeLabels = {
  api: 'API 请求',
  scheduler: '定时任务',
  background_task: '后台任务',
  explore_queue: '探索队列',
}

const moduleLabels = {
  scheduler: '调度器',
  subscriptions: '订阅',
  explore_queue: '探索队列',
  pan115: '115网盘',
  search: '搜索',
  settings: '设置',
  archive: '归档',
  emby: 'Emby',
  health: '健康检查',
  logs: '日志',
  downloads: '下载',
  unknown: '未知',
}

const statusLabels = {
  success: '成功',
  failed: '失败',
  warning: '警告',
  info: '信息',
  partial: '部分成功',
}

const actionLabels = {
  'scheduler.job.start': '调度任务开始',
  'scheduler.job.finish': '调度任务完成',
  'scheduler.job.update': '调度任务更新',
  'scheduler.job.result_persist_failed': '调度结果持久化失败',
  'subscription.run.background.start': '订阅后台任务开始',
  'subscription.run.background.running': '订阅后台任务执行中',
  'subscription.run.background.finish': '订阅后台任务完成',
  'subscription.item.done': '单项订阅处理完成',
  'subscription.item.failed': '单项订阅处理失败',
  'explore.queue.subscribe.start': '探索订阅开始',
  'explore.queue.subscribe.finish': '探索订阅完成',
  'explore.queue.save.start': '探索转存开始',
  'explore.queue.save.finish': '探索转存完成',
  'archive.watch.start': '归档监听启动',
  'archive.watch.stop': '归档监听停止',
  'archive.scan.start': '归档扫描开始',
  'archive.scan.finish': '归档扫描完成',
  'archive.file.start': '归档文件开始处理',
  'archive.file.parsed': '归档文件名解析完成',
  'archive.file.matched': '归档 TMDB 匹配完成',
  'archive.file.plan': '归档目标路径已生成',
  'archive.file.skipped': '归档文件已跳过',
  'archive.file.success': '归档文件处理成功',
  'archive.file.failed': '归档文件处理失败',
  'archive.tasks.clear': '归档任务已清理',
  'api.request.start': '接口请求开始',
  'api.request.finish': '接口请求完成',
  'api.request.exception': '接口请求异常',
}

const translateLabel = (value, map) => {
  if (!value) return '-'
  return map[value] || value
}

const apiActionPatterns = [
  [/^(GET|POST|PUT|DELETE|PATCH)\s+\/api\/search/, '搜索'],
  [/^(GET|POST|PUT|DELETE|PATCH)\s+\/api\/pan115/, '115网盘'],
  [/^(GET|POST|PUT|DELETE|PATCH)\s+\/api\/archive/, '归档'],
  [/^(GET|POST|PUT|DELETE|PATCH)\s+\/api\/subscriptions/, '订阅'],
  [/^(GET|POST|PUT|DELETE|PATCH)\s+\/api\/settings/, '设置'],
  [/^(GET|POST|PUT|DELETE|PATCH)\s+\/api\/emby/, 'Emby'],
  [/^(GET|POST|PUT|DELETE|PATCH)\s+\/api\/logs/, '日志'],
  [/^(GET|POST|PUT|DELETE|PATCH)\s+\/api\/health/, '健康检查'],
  [/^(GET|POST|PUT|DELETE|PATCH)\s+\/api\/downloads/, '下载'],
  [/^(GET|POST|PUT|DELETE|PATCH)\s+\/api\/scheduler/, '调度器'],
  [/^(GET|POST|PUT|DELETE|PATCH)\s+\/api\/workflows/, '工作流'],
]

const httpMethodLabels = { GET: '查询', POST: '提交', PUT: '更新', DELETE: '删除', PATCH: '修改' }

const summaryKeyLabels = {
  method: '请求方法',
  path: '请求路径',
  route_path: '路由路径',
  query: '查询参数',
  client: '客户端',
  ip: 'IP地址',
  user_agent: '用户代理',
  timezone: '时区',
  auth: '认证信息',
  authenticated: '已认证',
  username: '用户名',
  headers: '头信息',
  endpoint: '处理函数',
  status_code: '状态码',
  duration_ms: '耗时(毫秒)',
  data: '数据',
  detail: '详情',
  body: '请求体',
  params: '参数',
  url: '地址',
  content_type: '内容类型',
  content_length: '内容长度',
  code: '结果代码',
  msg: '结果消息',
  success: '成功',
  error: '错误',
  errors: '错误列表',
  count: '数量',
  total: '总数',
  items: '项目',
  results: '结果',
  list: '列表',
  page: '页码',
  page_size: '每页数量',
  page_num: '页码',
  limit: '限制数量',
  offset: '偏移量'
}

const headerKeyLabels = {
  'content-type': '内容类型',
  'content-length': '内容长度',
  referer: '来源页',
  origin: '来源站点',
  location: '跳转地址',
  'x-trace-id': '追踪ID',
  accept: '接受类型',
  host: '主机',
  connection: '连接方式'
}

const endpointLabels = {
  check_all_services_health: '检查全部服务健康状态',
  check_cookie_valid: '检查 Cookie 有效性',
  check_emby_credentials: '检查 Emby 连接',
  check_feiniu_credentials: '检查飞牛连接',
  check_hdhive_credentials: '检查 HDHive 连接',
  check_nullbr_credentials: '检查 Nullbr 连接',
  check_tg_credentials: '检查 Telegram 连接',
  check_tg_qr_login_status: '检查 Telegram 二维码登录状态',
  enqueue_explore_subscribe_task: '加入探索订阅队列',
  get_app_info: '获取应用信息',
  get_auth_session: '获取登录会话',
  get_available_charts: '获取可用榜单',
  get_bridge_by_imdb_id: '通过 IMDb 获取桥接信息',
  get_current_cookie: '获取当前 Cookie',
  get_default_folder: '获取默认目录',
  get_douban_subject_detail: '获取豆瓣条目详情',
  get_emby_status_map: '获取 Emby 状态图',
  get_emby_sync_status: '获取 Emby 同步状态',
  get_explore_meta: '获取探索元信息',
  get_explore_queue_active_tasks: '获取探索队列活动任务',
  get_explore_section: '获取探索分区',
  get_feiniu_status_map: '获取飞牛状态图',
  get_feiniu_sync_status: '获取飞牛同步状态',
  get_file_list: '获取文件列表',
  get_license_status: '获取许可证状态',
  get_movie: '获取电影详情',
  get_movie_magnet_butailing: '获取电影不太灵磁力',
  get_movie_pan115: '获取电影 115 资源',
  get_offline_default_folder: '获取离线默认目录',
  get_offline_quota: '获取离线配额',
  get_offline_tasks: '获取离线任务列表',
  get_pan115_risk_health: '获取 115 风控健康状态',
  get_pansou_config: '获取盘搜配置',
  get_proxy_config: '获取代理配置',
  get_runtime_settings: '获取运行时设置',
  get_subscription_status_map: '获取订阅状态图',
  get_tg_index_job: '获取 Telegram 索引任务',
  get_tg_index_status: '获取 Telegram 索引状态',
  get_tv: '获取剧集详情',
  get_tv_magnet: '获取剧集磁力资源',
  get_tv_magnet_butailing: '获取剧集不太灵磁力',
  get_tv_pan115: '获取剧集 115 资源',
  health_check: '健康检查',
  list_dynamic_tasks: '获取动态任务列表',
  list_scheduler_jobs: '获取调度任务列表',
  list_subscription_logs: '获取订阅日志',
  list_subscriptions: '获取订阅列表',
  list_tv_missing_status: '获取剧集缺集状态',
  list_workflows: '获取工作流列表',
  login: '登录',
  login_feiniu: '登录飞牛',
  proxy_explore_poster: '代理探索海报',
  run_chart_subscription_now: '立即执行榜单订阅',
  run_feiniu_sync: '立即执行飞牛同步',
  run_hdhive_checkin: '执行 HDHive 签到',
  search: '搜索',
  set_offline_default_folder: '设置离线默认目录',
  start_tg_index_backfill: '启动 Telegram 索引补录',
  start_tg_qr_login: '启动 Telegram 二维码登录',
  update_pansou_config: '更新盘搜配置',
  update_runtime_settings: '更新运行时设置',
  unknown: '未知'
}

const pathPatterns = [
  [/^\/api\/search\//, '搜索接口'],
  [/^\/api\/search$/, '搜索接口'],
  [/^\/api\/settings\//, '设置接口'],
  [/^\/api\/settings$/, '设置接口'],
  [/^\/api\/logs\//, '日志接口'],
  [/^\/api\/logs$/, '日志接口'],
  [/^\/api\/pan115\//, '115网盘接口'],
  [/^\/api\/pan115$/, '115网盘接口'],
  [/^\/api\/subscriptions\//, '订阅接口'],
  [/^\/api\/subscriptions$/, '订阅接口'],
  [/^\/api\/scheduler\//, '调度器接口'],
  [/^\/api\/scheduler$/, '调度器接口'],
  [/^\/api\/downloads\//, '下载接口'],
  [/^\/api\/downloads$/, '下载接口'],
  [/^\/api\/auth\//, '认证接口'],
  [/^\/api\/auth$/, '认证接口'],
  [/^\/api\/health\//, '健康检查接口'],
  [/^\/api\/health$/, '健康检查接口'],
  [/^\/api\/license\//, '许可证接口'],
  [/^\/api\/license$/, '许可证接口'],
  [/^\/api\/workflows\//, '工作流接口'],
  [/^\/api\/workflows$/, '工作流接口']
]

const translateAction = (value) => {
  if (!value) return '-'
  if (actionLabels[value]) return actionLabels[value]
  for (const [key, label] of Object.entries(actionLabels)) {
    if (value.startsWith(key)) return label
  }
  // 翻译 API 请求 action（如 "GET /api/search/..."）
  for (const [pattern, moduleName] of apiActionPatterns) {
    const match = value.match(pattern)
    if (match) {
      const method = httpMethodLabels[match[1]] || match[1]
      return `${method}${moduleName}`
    }
  }
  return value
}

const translateHttpMethod = (method) => {
  const normalized = String(method || '').toUpperCase()
  return httpMethodLabels[normalized] || normalized || '-'
}

const translateEndpoint = (value) => {
  const normalized = String(value || '').trim()
  if (!normalized) return '-'
  return endpointLabels[normalized] || normalized
}

const translatePath = (value) => {
  const normalized = String(value || '').trim()
  if (!normalized) return '-'
  for (const [pattern, label] of pathPatterns) {
    if (pattern.test(normalized)) {
      return `${label}（${normalized}）`
    }
  }
  return normalized
}

const tryParseJson = (value) => {
  if (typeof value !== 'string') return value
  const text = value.trim()
  if (!text) return value
  if (!(text.startsWith('{') || text.startsWith('['))) return value
  try {
    return JSON.parse(text)
  } catch {
    return value
  }
}

const translateSummaryValue = (value, key = '') => {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (value === null || value === undefined) return value
  if (key === 'method') return translateHttpMethod(value)
  if (key === 'endpoint') return translateEndpoint(value)
  if (key === 'path' || key === 'route_path') return translatePath(value)
  if (typeof value === 'string' && /^(GET|POST|PUT|DELETE|PATCH)$/.test(value)) {
    return translateHttpMethod(value)
  }
  if (key === 'content-type' && value === 'application/json') return 'JSON'
  if (key === 'status' || key === 'result') {
    const lowered = String(value).trim().toLowerCase()
    return statusLabels[lowered] || value
  }
  return value
}

const translateSummaryData = (value, parentKey = '') => {
  const parsed = tryParseJson(value)
  if (Array.isArray(parsed)) {
    return parsed.map((item) => translateSummaryData(item, parentKey))
  }
  if (parsed && typeof parsed === 'object') {
    return Object.fromEntries(
      Object.entries(parsed).map(([key, item]) => {
        const translatedKey = parentKey === 'headers'
          ? (headerKeyLabels[key] || key)
          : (summaryKeyLabels[key] || key)
        return [translatedKey, translateSummaryData(item, key)]
      })
    )
  }
  return translateSummaryValue(parsed, parentKey)
}

const stringifyTranslatedSummary = (value) => {
  if (!value) return '-'
  const translated = translateSummaryData(value)
  if (typeof translated === 'string') return translated
  try {
    return JSON.stringify(translated, ensureAsciiFalseReplacer())
  } catch {
    return String(translated)
  }
}

const ensureAsciiFalseReplacer = () => (key, val) => val

const formatApiMessage = (message, row) => {
  const raw = String(message || '').trim()
  if (!raw) return '-'

  let match = raw.match(/^(GET|POST|PUT|DELETE|PATCH)\s+(\S+)\s*->\s*(\d{3})$/)
  if (match) {
    return `接口请求完成：${translateHttpMethod(match[1])} ${translatePath(match[2])}，状态码 ${match[3]}`
  }

  match = raw.match(/^收到接口请求：(GET|POST|PUT|DELETE|PATCH)\s+([^，]+)，模块=([^，]+)，路由=([^，]+)，处理函数=([^，]+)，客户端=(.+)$/)
  if (match) {
    return `收到接口请求：${translateHttpMethod(match[1])} ${translatePath(match[2])}，模块=${translateLabel(match[3], moduleLabels)}，路由=${translatePath(match[4])}，处理函数=${translateEndpoint(match[5])}，客户端=${match[6]}`
  }

  match = raw.match(/^接口处理完成：(GET|POST|PUT|DELETE|PATCH)\s+([^，]+)，模块=([^，]+)，状态码=(\d+)，耗时=(\d+)ms，结果=(.+)$/)
  if (match) {
    return `接口处理完成：${translateHttpMethod(match[1])} ${translatePath(match[2])}，模块=${translateLabel(match[3], moduleLabels)}，状态码=${match[4]}，耗时=${match[5]}毫秒，结果=${translateLabel(String(match[6]).trim().toLowerCase(), statusLabels)}`
  }

  return raw.replace(/\b(GET|POST|PUT|DELETE|PATCH)\b/g, (_, method) => translateHttpMethod(method))
}

const formatMessage = (row) => {
  if (!row) return '-'
  if (row.source_type === 'api') {
    return formatApiMessage(row.message, row)
  }
  return row.message || '-'
}

const loading = ref(false)
const logs = ref([])
const total = ref(0)
const currentPage = ref(1)
const summary = reactive({
  success: 0,
  warning: 0,
  failed: 0,
  info: 0
})
const moduleOptions = ref([])
const sourceTypeOptions = ref([])
const statusOptions = ref([])

const filters = reactive({
  sourceType: '',
  module: '',
  status: '',
  path: '',
  traceId: '',
  dateRange: [],
  limit: 100
})

const statusTagType = (status) => {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'warning' || status === 'partial') return 'warning'
  return 'info'
}

const stringifySummary = (value) => {
  return stringifyTranslatedSummary(value)
}

const formatSummaryBlock = (value) => {
  if (!value) return '-'
  const translated = translateSummaryData(value)
  try {
    return JSON.stringify(translated, null, 2)
  } catch {
    return String(translated)
  }
}

const formatHttpCell = (row) => {
  const method = translateHttpMethod(row.http_method || '-')
  const path = translatePath(row.path || '-')
  const statusCode = row.status_code || '-'
  return `${method} ${path}（状态码 ${statusCode}）`
}

const fetchFilterOptions = async () => {
  try {
    const { data } = await logsApi.modules()
    moduleOptions.value = Array.isArray(data?.modules) ? data.modules : []
    sourceTypeOptions.value = Array.isArray(data?.source_types) ? data.source_types : []
    statusOptions.value = Array.isArray(data?.statuses) ? data.statuses : []
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '日志筛选项获取失败')
  }
}

const fetchLogs = async () => {
  loading.value = true
  try {
    const params = {
      limit: Number(filters.limit || 100),
      offset: (currentPage.value - 1) * Number(filters.limit || 100)
    }
    if (filters.sourceType) params.source_type = filters.sourceType
    if (filters.module) params.module = filters.module
    if (filters.status) params.status = filters.status
    if (filters.path) params.path = filters.path
    if (filters.traceId) params.trace_id = filters.traceId
    if (Array.isArray(filters.dateRange) && filters.dateRange.length === 2) {
      params.date_from = filters.dateRange[0] ? new Date(filters.dateRange[0]).toISOString() : undefined
      params.date_to = filters.dateRange[1] ? new Date(filters.dateRange[1]).toISOString() : undefined
    }

    const { data } = await logsApi.list(params)
    logs.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total || 0)
    summary.success = Number(data?.summary?.success || 0)
    summary.warning = Number(data?.summary?.warning || 0)
    summary.failed = Number(data?.summary?.failed || 0)
    summary.info = Number(data?.summary?.info || 0)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '日志获取失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  currentPage.value = 1
  await fetchLogs()
}

const handlePageChange = async (page) => {
  currentPage.value = Number(page || 1)
  await fetchLogs()
}

onMounted(async () => {
  await fetchFilterOptions()
  await fetchLogs()
})
</script>

<style lang="scss" scoped>
.logs-page {
  .page-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;

    h2 {
      margin: 0;
      color: var(--ms-text-primary);
      white-space: nowrap;
    }

    .filters {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 10px;
      width: 100%;

      .filter-item {
        width: 130px;
      }

      .filter-item-wide {
        width: 220px;
      }

      .filter-item-date {
        width: 360px;
      }
    }
  }

  .summary-card {
    margin-bottom: 12px;
  }

  .summary-tags {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;

    .summary-total {
      color: var(--ms-text-secondary);
      font-size: 13px;
    }
  }

  .table-wrap {
    overflow-x: auto;

    .el-table {
      min-width: 1600px;
    }
  }

  .log-detail {
    display: grid;
    grid-template-columns: repeat(2, minmax(280px, 1fr));
    gap: 12px;

    &__block {
      background: var(--ms-bg-subtle);
      border: 1px solid var(--ms-border-color);
      border-radius: 10px;
      padding: 12px;

      pre {
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        font-size: 12px;
        line-height: 1.6;
        color: var(--ms-text-secondary);
      }
    }

    &__title {
      margin-bottom: 8px;
      font-size: 12px;
      font-weight: 600;
      color: var(--ms-text-primary);
    }
  }

  .pager-wrap {
    margin-top: 16px;
    display: flex;
    justify-content: flex-end;
  }
}

@media (max-width: 1024px) {
  .logs-page {
    .page-header {
      flex-direction: column;
      align-items: stretch;

      .filters {
        justify-content: flex-start;

        .filter-item,
        .filter-item-wide,
        .filter-item-date {
          width: 100%;
        }

        :deep(.el-input-number),
        :deep(.el-button) {
          width: 100%;
        }
      }
    }

    .log-detail {
      grid-template-columns: 1fr;
    }

    .pager-wrap {
      justify-content: center;
    }
  }
}

@media (max-width: 768px) {
  .logs-page {
    :deep(.el-card__body) {
      padding-inline: 16px;
    }

    .summary-tags {
      gap: 8px;
    }

    .table-wrap {
      .el-table {
        min-width: 1120px;
      }
    }

    .pager-wrap {
      margin-top: 12px;
      overflow-x: auto;
    }
  }
}
</style>
