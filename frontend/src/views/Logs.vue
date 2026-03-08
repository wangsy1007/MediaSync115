<template>
  <div class="logs-page">
    <div class="page-header">
      <h2>日志中心</h2>
      <div class="filters">
        <el-select v-model="filters.sourceType" clearable placeholder="类型" class="filter-item">
          <el-option v-for="item in sourceTypeOptions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="filters.module" clearable placeholder="模块" class="filter-item">
          <el-option v-for="item in moduleOptions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="状态" class="filter-item">
          <el-option v-for="item in statusOptions" :key="item" :label="item" :value="item" />
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
          <el-table-column prop="created_at" label="时间" min-width="170" :formatter="formatBeijingTableCell" />
          <el-table-column prop="source_type" label="类型" width="130" />
          <el-table-column prop="module" label="模块" width="120" />
          <el-table-column prop="action" label="动作" min-width="260" show-overflow-tooltip />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ row.status || 'info' }}</el-tag>
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

    .pager-wrap {
      justify-content: center;
    }
  }
}
</style>
