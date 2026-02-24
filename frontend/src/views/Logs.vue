<template>
  <div class="logs-page">
    <div class="page-header">
      <h2>日志中心</h2>
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

    <el-alert
      title="当前先展示订阅执行详细日志，后续可扩展更多日志类型"
      type="info"
      :closable="false"
      style="margin-bottom: 12px"
    />

    <el-card>
      <el-table :data="logs" v-loading="loading" size="small" stripe>
        <el-table-column prop="created_at" label="时间" min-width="170" :formatter="formatBeijingTableCell" />
        <el-table-column prop="channel" label="渠道" width="90" />
        <el-table-column prop="run_id" label="Run ID" min-width="230" />
        <el-table-column prop="subscription_title" label="影视" min-width="180" />
        <el-table-column prop="step" label="步骤" min-width="170" />
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
import { ElMessage } from 'element-plus'
import { subscriptionApi } from '@/api'
import { formatBeijingTableCell } from '@/utils/timezone'

const loading = ref(false)
const logs = ref([])
const filters = reactive({
  channel: '',
  runId: '',
  limit: 200
})

const statusTagType = (status) => {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'partial') return 'warning'
  return 'info'
}

const toFallbackRows = (items) => {
  return (Array.isArray(items) ? items : []).map((item) => ({
    id: item.id,
    run_id: '-',
    channel: item.channel,
    subscription_id: null,
    subscription_title: '-',
    step: 'execution_summary',
    status: item.status,
    message: item.message,
    payload: item,
    created_at: item.started_at
  }))
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
  } catch (error) {
    if (error.response?.status === 404) {
      // 兼容旧后端：回退到执行汇总日志，避免页面直接报错。
      try {
        const { data } = await subscriptionApi.listLogs({ limit: Number(filters.limit || 200) })
        logs.value = toFallbackRows(data)
        ElMessage.warning('当前后端未启用详细步骤日志，已显示执行汇总日志')
      } catch {
        ElMessage.error('日志获取失败')
      }
    } else {
      ElMessage.error(error.response?.data?.detail || '日志获取失败')
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchStepLogs()
})
</script>

<style lang="scss" scoped>
.logs-page {
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
}
</style>
