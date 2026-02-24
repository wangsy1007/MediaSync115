<template>
  <div class="scheduler-page">
    <div class="page-header">
      <h2>调度中心</h2>
      <el-button type="primary" @click="refreshAll" :loading="loading">刷新</el-button>
    </div>

    <el-card class="section-card">
      <template #header>
        <div class="card-title">运行中任务</div>
      </template>
      <el-table :data="jobs" v-loading="loading" size="small">
        <el-table-column prop="id" label="任务ID" min-width="180" />
        <el-table-column prop="kind" label="类型" width="100" />
        <el-table-column prop="next_run_time" label="下次运行" min-width="180" :formatter="formatBeijingTableCell" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="primary" text @click="runJob(row.id)">立即执行</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="section-card">
      <template #header>
        <div class="card-title">动态任务</div>
      </template>
      <el-table :data="tasks" v-loading="loading" size="small">
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="job_key" label="Job Key" min-width="180" />
        <el-table-column prop="trigger_type" label="触发类型" width="100" />
        <el-table-column prop="state" label="状态" width="80" />
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button type="success" text @click="enableTask(row)" v-if="!row.enabled">启用</el-button>
            <el-button type="warning" text @click="pauseTask(row)" v-else>暂停</el-button>
            <el-button type="danger" text @click="deleteTask(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { schedulerApi } from '@/api'
import { formatBeijingTableCell } from '@/utils/timezone'

const loading = ref(false)
const jobs = ref([])
const tasks = ref([])

const refreshAll = async () => {
  loading.value = true
  try {
    const [jobsResp, tasksResp] = await Promise.all([
      schedulerApi.listJobs(),
      schedulerApi.listTasks()
    ])
    jobs.value = jobsResp.data.items || []
    tasks.value = tasksResp.data || []
  } catch (error) {
    ElMessage.error('刷新调度信息失败')
  } finally {
    loading.value = false
  }
}

const runJob = async (jobId) => {
  try {
    await schedulerApi.runJob(jobId)
    ElMessage.success('任务已触发')
    await refreshAll()
  } catch (error) {
    ElMessage.error('任务执行失败')
  }
}

const enableTask = async (row) => {
  try {
    await schedulerApi.enableTask(row.id)
    ElMessage.success('任务已启用')
    await refreshAll()
  } catch (error) {
    ElMessage.error('启用失败')
  }
}

const pauseTask = async (row) => {
  try {
    await schedulerApi.pauseTask(row.id)
    ElMessage.success('任务已暂停')
    await refreshAll()
  } catch (error) {
    ElMessage.error('暂停失败')
  }
}

const deleteTask = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除任务 ${row.name} 吗？`, '提示', { type: 'warning' })
    await schedulerApi.deleteTask(row.id)
    ElMessage.success('任务已删除')
    await refreshAll()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

onMounted(refreshAll)
</script>

<style lang="scss" scoped>
.scheduler-page {
  display: flex;
  flex-direction: column;
  gap: 16px;

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .section-card {
    .card-title {
      font-weight: 600;
      color: var(--ms-text-primary);
    }
  }
}
</style>
