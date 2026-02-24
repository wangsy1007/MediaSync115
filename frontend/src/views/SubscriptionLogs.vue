<template>
  <div class="subscription-logs-page">
    <div class="page-header">
      <h2>订阅详细日志</h2>
      <div class="filters">
        <el-select v-model="filters.channel" clearable placeholder="渠道" style="width: 140px">
          <el-option label="Nullbr" value="nullbr" />
          <el-option label="Pansou" value="pansou" />
        </el-select>
        <el-input v-model.trim="filters.runId" placeholder="Run ID" clearable style="width: 240px" />
        <el-input-number v-model="filters.limit" :min="20" :max="1000" :step="20" />
        <el-button type="primary" :loading="loading" @click="fetchStepLogs">刷新</el-button>
      </div>
    </div>

    <el-card>
      <el-table :data="logs" v-loading="loading" size="small" stripe>
        <el-table-column type="expand" width="42">
          <template #default="{ row }">
            <div class="payload-panel">
              <div class="payload-row"><span>Run ID:</span><code>{{ row.run_id }}</code></div>
              <div class="payload-row"><span>订阅:</span><span>{{ row.subscription_title || '-' }}</span></div>
              <div class="payload-row"><span>步骤:</span><span>{{ getStepLabel(row.step) }}</span></div>
              <pre v-if="row.payload" class="payload-json">{{ formatPayload(row.payload) }}</pre>
              <span v-else class="payload-empty">无额外 payload</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" min-width="170" :formatter="formatBeijingTableCell" />
        <el-table-column prop="channel" label="渠道" width="90" />
        <el-table-column label="Run ID" min-width="240">
          <template #default="{ row }">
            <el-button link type="primary" @click="applyRunIdFilter(row.run_id)">{{ row.run_id }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="subscription_title" label="影视" min-width="200" show-overflow-tooltip />
        <el-table-column label="步骤" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ getStepLabel(row.step) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="320" show-overflow-tooltip />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { subscriptionApi } from '@/api'
import { formatBeijingTableCell } from '@/utils/timezone'

const loading = ref(false)
const logs = ref([])
const filters = reactive({
  channel: '',
  runId: '',
  limit: 200
})

const stepLabelMap = {
  run_start: '任务启动',
  run_finish: '任务完成',
  subscription_start: '开始处理订阅',
  subscription_done: '订阅处理完成',
  subscription_failed: '订阅处理失败',
  fetch_resources: '资源抓取完成',
  fetch_skip: '跳过抓取',
  fetch_nullbr_start: 'Nullbr 抓取开始',
  fetch_nullbr_done: 'Nullbr 抓取结束',
  fetch_pansou_tmdb_start: 'Pansou TMDB 抓取开始',
  fetch_pansou_tmdb_done: 'Pansou TMDB 抓取结束',
  fetch_pansou_tmdb_empty: 'Pansou TMDB 无结果',
  fetch_pansou_tmdb_failed: 'Pansou TMDB 抓取失败',
  fetch_pansou_keyword_start: 'Pansou 关键词抓取开始',
  fetch_pansou_keyword_done: 'Pansou 关键词抓取结束',
  store_new_resources: '资源入库',
  auto_transfer_skip: '跳过自动转存',
  auto_transfer_new_start: '新资源转存开始',
  auto_transfer_new_done: '新资源转存完成',
  auto_transfer_retry_start: '历史重试开始',
  auto_transfer_retry_done: '历史重试完成',
  auto_transfer_item_start: '单条资源转存开始',
  auto_transfer_item_done: '单条资源转存成功',
  auto_transfer_item_failed: '单条资源转存失败',
  auto_transfer_summary: '自动转存汇总'
}

const getStepLabel = (step) => stepLabelMap[step] || step || '-'

const formatPayload = (payload) => {
  if (!payload) return ''
  if (typeof payload === 'string') return payload
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return String(payload)
  }
}

const applyRunIdFilter = (runId) => {
  filters.runId = runId || ''
  fetchStepLogs()
}

const statusTagType = (status) => {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'partial') return 'warning'
  return 'info'
}

const fetchStepLogs = async () => {
  loading.value = true
  try {
    const params = {
      limit: Number(filters.limit || 200)
    }
    if (filters.channel) params.channel = filters.channel
    if (filters.runId) params.run_id = filters.runId
    const { data } = await subscriptionApi.listStepLogs(params)
    logs.value = Array.isArray(data) ? data : []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchStepLogs()
})
</script>

<style lang="scss" scoped>
.subscription-logs-page {
  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;

    h2 {
      margin: 0;
      color: var(--ms-text-primary);
    }

    .filters {
      display: flex;
      gap: 10px;
      align-items: center;
    }
  }

  .payload-panel {
    padding: 8px 16px;
    background: var(--ms-glass-bg);
    border: 1px solid var(--ms-border-color);
    border-radius: 8px;

    .payload-row {
      margin-bottom: 8px;
      color: var(--ms-text-secondary);

      span:first-child {
        color: var(--ms-text-muted);
        margin-right: 8px;
      }

      code {
        color: var(--ms-text-primary);
      }
    }

    .payload-json {
      margin: 0;
      padding: 10px;
      border-radius: 8px;
      max-height: 320px;
      overflow: auto;
      background: var(--ms-bg-elevated);
      color: var(--ms-text-primary);
      font-size: 12px;
      line-height: 1.5;
    }

    .payload-empty {
      color: var(--ms-text-muted);
      font-size: 12px;
    }
  }
}
</style>
