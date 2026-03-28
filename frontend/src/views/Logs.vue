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
          <el-table-column prop="message" label="说明" min-width="220" show-overflow-tooltip />
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
  if (!value) return '-'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

const formatSummaryBlock = (value) => {
  if (!value) return '-'
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch {
      return value
    }
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const formatHttpCell = (row) => {
  const method = row.http_method || '-'
  const path = row.path || '-'
  const statusCode = row.status_code || '-'
  return `${method} ${path} (${statusCode})`
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
      background: #f7f8fa;
      border: 1px solid #ebeef5;
      border-radius: 10px;
      padding: 12px;

      pre {
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        font-size: 12px;
        line-height: 1.6;
        color: var(--ms-text-regular);
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
