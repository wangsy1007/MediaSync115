<template>
  <div class="archive-page">
    <div class="page-header">
      <div>
        <h2>归档刮削</h2>
        <p class="page-subtitle">自动扫描 115 网盘离线目录，识别影片并按电影/剧集 + 类型归档到分类文件夹。为降低 115 风控概率，扫描会按低频模式顺序执行。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="refreshing" @click="refreshAll">刷新</el-button>
        <el-button type="primary" :loading="scanLoading" @click="runScan">立即扫描</el-button>
      </div>
    </div>

    <el-card class="section-card">
      <template #header>
        <div class="card-title">归档配置</div>
      </template>

      <el-form label-width="140px" class="config-form">
        <div class="config-grid">
          <el-form-item label="启用归档">
            <el-switch v-model="config.archive_enabled" />
          </el-form-item>
          <el-form-item label="兜底扫描间隔">
            <el-input-number v-model="config.archive_interval_minutes" :min="1" :max="1440" />
            <span class="suffix-text">分钟</span>
          </el-form-item>

          <el-form-item label="115 监听目录" class="grid-span-2">
            <div class="folder-row">
              <el-tag v-if="config.archive_watch_cid" closable type="info" @close="config.archive_watch_cid = ''; config.archive_watch_name = ''">
                {{ config.archive_watch_name || config.archive_watch_cid }}
              </el-tag>
              <el-button size="small" @click="openPicker('watch')">选择目录</el-button>
            </div>
            <div class="form-hint">离线下载完成的影视文件所在目录（只读扫描）</div>
          </el-form-item>

          <el-form-item label="115 输出目录" class="grid-span-2">
            <div class="folder-row">
              <el-tag v-if="config.archive_output_cid" closable type="info" @close="config.archive_output_cid = ''; config.archive_output_name = ''">
                {{ config.archive_output_name || config.archive_output_cid }}
              </el-tag>
              <el-button size="small" @click="openPicker('output')">选择目录</el-button>
            </div>
            <div class="form-hint">归档后的文件将整理到此目录下的 movies / tv 子目录中</div>
          </el-form-item>
        </div>

        <div class="config-actions">
          <el-button type="primary" :loading="saving" @click="saveConfig">保存配置</el-button>
        </div>
      </el-form>
    </el-card>

    <el-card class="section-card">
      <template #header>
        <div class="card-title">运行状态</div>
      </template>

      <div class="status-grid">
        <div class="status-item">
          <span class="status-label">归档状态</span>
          <el-tag :type="config.archive_enabled ? 'success' : 'info'">{{ config.archive_enabled ? '已启用' : '未启用' }}</el-tag>
        </div>
        <div class="status-item">
          <span class="status-label">监听目录</span>
          <span class="status-value">{{ config.archive_watch_name || config.archive_watch_cid || '未配置' }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">输出目录</span>
          <span class="status-value">{{ config.archive_output_name || config.archive_output_cid || '未配置' }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">扫描间隔</span>
          <span class="status-value">{{ config.archive_interval_minutes }} 分钟</span>
        </div>
        <div class="status-item">
          <span class="status-label">扫描任务</span>
          <el-tag :type="runtime.scan_running ? 'warning' : 'info'">{{ runtime.scan_running ? '执行中' : '空闲' }}</el-tag>
        </div>
      </div>
    </el-card>

    <el-card class="section-card">
      <template #header>
        <div class="tasks-header">
          <div class="card-title">归档任务</div>
          <div class="tasks-toolbar">
            <el-select v-model="filters.status" clearable placeholder="全部状态" class="status-filter" @change="handleFilterChange">
              <el-option label="处理中" value="processing" />
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
              <el-option label="跳过" value="skipped" />
            </el-select>
            <el-button @click="clearFinished(false)">清理已完成</el-button>
            <el-button type="danger" plain @click="clearFinished(true)">清理含失败</el-button>
          </div>
        </div>
      </template>

      <div class="table-wrap">
        <el-table :data="tasks" v-loading="tasksLoading" size="small">
          <el-table-column prop="created_at" label="时间" min-width="170" :formatter="formatBeijingTableCell" />
          <el-table-column prop="source_filename" label="源文件" min-width="220" show-overflow-tooltip />
          <el-table-column label="类型" width="90">
            <template #default="{ row }">{{ mediaTypeLabel(row.media_type) }}</template>
          </el-table-column>
          <el-table-column prop="tmdb_title" label="识别结果" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span>{{ row.tmdb_title || '-' }}</span>
              <span v-if="row.tmdb_year" class="year-text">({{ row.tmdb_year }})</span>
            </template>
          </el-table-column>
          <el-table-column prop="genre_name" label="分类" width="130" show-overflow-tooltip />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="target_path" label="目标路径" min-width="260" show-overflow-tooltip />
          <el-table-column prop="error_message" label="错误原因" min-width="220" show-overflow-tooltip />
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'failed'" type="primary" text @click="retryTask(row)">重试</el-button>
              <span v-else class="muted-text">-</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager-wrap">
        <el-pagination
          background
          layout="prev, pager, next, jumper, total"
          :total="total"
          :current-page="filters.page"
          :page-size="filters.limit"
          @current-change="handlePageChange"
        />
      </div>
    </el-card>

    <el-dialog v-model="pickerVisible" :title="pickerTitle" width="520px" :close-on-click-modal="false">
      <div class="picker-breadcrumb">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item v-for="crumb in pickerBreadcrumbs" :key="crumb.cid">
            <a @click.prevent="navigatePicker(crumb.cid)">{{ getFolderDisplayName(crumb) }}</a>
            </el-breadcrumb-item>
          </el-breadcrumb>
      </div>

      <div class="picker-toolbar">
        <el-button size="small" :loading="pickerCreating" @click="createPickerFolder">新建文件夹</el-button>
      </div>

      <el-table :data="pickerFolders" v-loading="pickerLoading" size="small" max-height="400px" @row-click="handlePickerRowClick">
        <el-table-column label="文件夹名称" min-width="300">
          <template #default="{ row }">
            <span>{{ getFolderDisplayName(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="cid" label="CID" width="120" show-overflow-tooltip />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" type="primary" text @click.stop="enterPickerFolder(row)">进入</el-button>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <div class="picker-footer">
          <span>当前目录 CID: {{ pickerCurrentCid }}</span>
          <div>
            <el-button @click="pickerVisible = false">取消</el-button>
            <el-button type="primary" @click="confirmPicker">选择当前目录</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { archiveApi, pan115Api } from '@/api'
import { formatBeijingTableCell } from '@/utils/timezone'

const refreshing = ref(false)
const saving = ref(false)
const scanLoading = ref(false)
const tasksLoading = ref(false)
const total = ref(0)
const tasks = ref([])
let scanPollingTimer = null

const config = reactive({
  archive_enabled: false,
  archive_watch_cid: '',
  archive_watch_name: '',
  archive_output_cid: '',
  archive_output_name: '',
  archive_interval_minutes: 10
})

const runtime = reactive({
  scan_running: false,
  last_scan_started_at: '',
  last_scan_finished_at: '',
  last_scan_trigger: '',
  last_scan_error: ''
})

const filters = reactive({
  status: '',
  page: 1,
  limit: 20
})

const pickerVisible = ref(false)
const pickerTarget = ref('')
const pickerFolders = ref([])
const pickerLoading = ref(false)
const pickerCreating = ref(false)
const pickerCurrentCid = ref('0')
const pickerHistory = ref([])

const pickerTitle = computed(() => pickerTarget.value === 'watch' ? '选择 115 监听目录' : '选择 115 输出目录')
const pickerBreadcrumbs = computed(() => [{ cid: '0', name: '根目录' }, ...pickerHistory.value])

const getFolderDisplayName = (folder) => {
  if (!folder || typeof folder !== 'object') return '-'
  return String(
    folder.name
    || folder.n
    || folder.fn
    || folder.folder_name
    || folder.file_name
    || folder.cid
    || '-'
  ).trim() || '-'
}

// 获取当前目录的名称
const getCurrentFolderName = () => {
  if (pickerCurrentCid.value === '0') return '根目录'
  const found = pickerHistory.value.find(h => h.cid === pickerCurrentCid.value)
  return getFolderDisplayName(found) || pickerCurrentCid.value
}

const mediaTypeLabel = (v) => v === 'movie' ? '电影' : v === 'tv' ? '剧集' : '-'
const statusLabel = (v) => ({ processing: '处理中', success: '成功', failed: '失败', skipped: '跳过' }[v] || '待处理')
const statusTagType = (v) => ({ success: 'success', failed: 'danger', processing: 'warning' }[v] || 'info')

const loadConfig = async () => {
  const { data } = await archiveApi.getConfig()
  config.archive_enabled = !!data.archive_enabled
  config.archive_watch_cid = data.archive_watch_cid || ''
  config.archive_watch_name = data.archive_watch_name || ''
  config.archive_output_cid = data.archive_output_cid || ''
  config.archive_output_name = data.archive_output_name || ''
  config.archive_interval_minutes = Number(data.archive_interval_minutes || 10)
  runtime.scan_running = !!data.runtime?.scan_running
  runtime.last_scan_started_at = data.runtime?.last_scan_started_at || ''
  runtime.last_scan_finished_at = data.runtime?.last_scan_finished_at || ''
  runtime.last_scan_trigger = data.runtime?.last_scan_trigger || ''
  runtime.last_scan_error = data.runtime?.last_scan_error || ''
}

const loadTasks = async () => {
  tasksLoading.value = true
  try {
    const { data } = await archiveApi.listTasks({ status: filters.status || undefined, limit: filters.limit, offset: (filters.page - 1) * filters.limit })
    tasks.value = data.items || []
    total.value = Number(data.total || 0)
  } finally {
    tasksLoading.value = false
  }
}

const refreshAll = async () => {
  refreshing.value = true
  try {
    await Promise.all([loadConfig(), loadTasks()])
  } catch {
    ElMessage.error('刷新归档信息失败')
  } finally {
    refreshing.value = false
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await archiveApi.updateConfig({
      archive_enabled: config.archive_enabled,
      archive_watch_cid: config.archive_watch_cid,
      archive_watch_name: config.archive_watch_name,
      archive_output_cid: config.archive_output_cid,
      archive_output_name: config.archive_output_name,
      archive_interval_minutes: config.archive_interval_minutes
    })
    ElMessage.success('归档配置已保存')
  } finally {
    saving.value = false
  }
}

const runScan = async () => {
  scanLoading.value = true
  try {
    const { data } = await archiveApi.runScan()
    runtime.scan_running = !!data.runtime?.scan_running
    runtime.last_scan_started_at = data.runtime?.last_scan_started_at || runtime.last_scan_started_at
    runtime.last_scan_finished_at = data.runtime?.last_scan_finished_at || runtime.last_scan_finished_at
    runtime.last_scan_trigger = data.runtime?.last_scan_trigger || runtime.last_scan_trigger
    runtime.last_scan_error = data.runtime?.last_scan_error || ''
    ElMessage.success(data.message || '归档扫描已启动')
    startScanPolling()
    await loadTasks()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '归档扫描失败')
  } finally {
    scanLoading.value = false
  }
}

const stopScanPolling = () => {
  if (scanPollingTimer) {
    clearInterval(scanPollingTimer)
    scanPollingTimer = null
  }
}

const startScanPolling = () => {
  stopScanPolling()
  scanPollingTimer = window.setInterval(async () => {
    try {
      await Promise.all([loadConfig(), loadTasks()])
      if (!runtime.scan_running) {
        stopScanPolling()
        if (runtime.last_scan_error) {
          ElMessage.warning(runtime.last_scan_error)
        } else {
          ElMessage.success('归档扫描已完成')
        }
      }
    } catch {
      stopScanPolling()
    }
  }, 3000)
}

const retryTask = async (row) => {
  await archiveApi.retryTask(row.id)
  ElMessage.success('归档任务已重新执行')
  await loadTasks()
}

const clearFinished = async (includeFailed) => {
  try {
    await ElMessageBox.confirm(includeFailed ? '确认清理已完成和失败的归档任务吗？' : '确认清理已完成的归档任务吗？', '提示', { type: 'warning' })
    const { data } = await archiveApi.clearTasks(includeFailed)
    ElMessage.success(`已清理 ${data.removed || 0} 条任务记录`)
    await loadTasks()
  } catch (error) {
    if (error !== 'cancel') { /* cancelled */ }
  }
}

const handlePageChange = (page) => { filters.page = page; loadTasks() }
const handleFilterChange = () => { filters.page = 1; loadTasks() }

const openPicker = (target) => {
  pickerTarget.value = target
  pickerCurrentCid.value = '0'
  pickerHistory.value = []
  pickerFolders.value = []
  pickerVisible.value = true
  loadPickerFolders('0')
}

const loadPickerFolders = async (cid) => {
  pickerLoading.value = true
  pickerCurrentCid.value = cid
  try {
    const { data } = await archiveApi.listFolders(cid)
    pickerFolders.value = (Array.isArray(data?.folders) ? data.folders : []).map(folder => ({
      cid: String(folder.cid || ''),
      name: getFolderDisplayName(folder)
    }))
  } catch {
    pickerFolders.value = []
  } finally {
    pickerLoading.value = false
  }
}

const navigatePicker = (cid) => {
  // 如果点击的是当前目录，不做任何事
  if (cid === pickerCurrentCid.value) return
  
  // 查找目标目录在面包屑中的索引
  const index = pickerHistory.value.findIndex(h => h.cid === cid)
  if (index >= 0) {
    // 点击的是面包屑中的某个目录，截断历史
    pickerHistory.value = pickerHistory.value.slice(0, index)
  }
  // 否则是点击面包屑的根目录，清空历史
  else if (cid === '0') {
    pickerHistory.value = []
  }
  
  loadPickerFolders(cid)
}

const handlePickerRowClick = (row) => {
  enterPickerFolder(row)
}

const enterPickerFolder = (row) => {
  const rowName = getFolderDisplayName(row)
  // 进入子目录前，将当前目录加入历史
  const currentName = getCurrentFolderName()
  if (pickerCurrentCid.value !== '0' && !pickerHistory.value.find(h => h.cid === pickerCurrentCid.value)) {
    pickerHistory.value.push({ cid: pickerCurrentCid.value, name: currentName })
  }
  // 将目标目录加入历史（使用 row.name）
  if (!pickerHistory.value.find(h => h.cid === row.cid)) {
    pickerHistory.value.push({ cid: row.cid, name: rowName })
  }
  loadPickerFolders(row.cid)
}

const createPickerFolder = async () => {
  try {
    const { value } = await ElMessageBox.prompt('请输入新文件夹名称', '新建文件夹', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPattern: /\S+/,
      inputErrorMessage: '文件夹名称不能为空'
    })

    const folderName = String(value || '').trim()
    if (!folderName) {
      return
    }

    pickerCreating.value = true
    await pan115Api.createFolder(pickerCurrentCid.value, folderName)
    ElMessage.success(`已创建文件夹：${folderName}`)
    await loadPickerFolders(pickerCurrentCid.value)
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return
    }
  } finally {
    pickerCreating.value = false
  }
}

const confirmPicker = () => {
  const folderName = getCurrentFolderName()
  if (pickerTarget.value === 'watch') {
    config.archive_watch_cid = pickerCurrentCid.value
    config.archive_watch_name = folderName
  } else {
    config.archive_output_cid = pickerCurrentCid.value
    config.archive_output_name = folderName
  }
  pickerVisible.value = false
  ElMessage.success('目录已选择，点击保存配置生效')
}

onMounted(async () => {
  await refreshAll()
  if (runtime.scan_running) {
    startScanPolling()
  }
})

onBeforeUnmount(() => {
  stopScanPolling()
})
</script>

<style lang="scss" scoped>
.archive-page {
  display: flex;
  flex-direction: column;
  gap: 16px;

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
  }

  .page-subtitle {
    margin: 8px 0 0;
    color: var(--ms-text-secondary);
  }

  .header-actions {
    display: flex;
    gap: 12px;
  }

  .section-card .card-title {
    font-weight: 600;
    color: var(--ms-text-primary);
  }

  .config-form {
    .config-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 20px;
    }
    .grid-span-2 { grid-column: span 2; }
    .suffix-text { margin-left: 10px; color: var(--ms-text-secondary); }
    .config-actions { margin-top: 12px; }
  }

  .folder-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .form-hint {
    margin-top: 4px;
    font-size: 12px;
    color: var(--ms-text-secondary);
  }

  .status-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px 20px;
  }

  .status-item {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .status-label {
    color: var(--ms-text-secondary);
    white-space: nowrap;
  }

  .status-value, .year-text, .muted-text {
    color: var(--ms-text-secondary);
  }

  .tasks-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
  }

  .tasks-toolbar {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }

  .status-filter { width: 140px; }
  .table-wrap { overflow-x: auto; }

  .pager-wrap {
    margin-top: 16px;
    display: flex;
    justify-content: flex-end;
  }
}

.picker-breadcrumb { margin-bottom: 12px; }

.picker-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}

.picker-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  font-size: 13px;
  color: var(--ms-text-secondary);
}

@media (max-width: 1024px) {
  .archive-page {
    .page-header, .tasks-header { flex-direction: column; align-items: stretch; }
    .header-actions, .tasks-toolbar { width: 100%; }
    .config-form .config-grid, .status-grid { grid-template-columns: 1fr; }
    .config-form .grid-span-2 { grid-column: span 1; }
    .table-wrap .el-table { min-width: 980px; }
  }
}

@media (max-width: 768px) {
  .archive-page .header-actions { flex-direction: column; }
}
</style>
