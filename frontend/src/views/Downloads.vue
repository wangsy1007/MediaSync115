<template>
  <div class="downloads-page">
    <div class="page-header">
      <h2>离线下载</h2>
      <el-button type="primary" :loading="refreshing" @click="handleRefresh">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <el-card class="add-card">
      <div class="add-form">
        <el-input
          v-model="offlineUrl"
          placeholder="粘贴磁力 / ED2K / HTTP 下载链接"
          clearable
          @keyup.enter="openAddOfflineDialog"
        />
        <el-button type="primary" :loading="adding" @click="openAddOfflineDialog">
          添加离线任务
        </el-button>
      </div>
      <div class="default-folder-tip">
        当前默认离线文件夹：{{ currentOfflineDefaultFolderText }}
      </div>
    </el-card>

    <el-card class="tasks-card">
      <template #header>
        <div class="card-header">
          <span>离线任务列表（{{ offlineTasks.length }}）</span>
          <el-button type="danger" size="small" :disabled="completedCount === 0" @click="handleClearTasks">
            清空已完成
          </el-button>
        </div>
      </template>

      <div class="table-wrap">
        <el-table :data="offlineTasks" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="文件名" min-width="300">
          <template #default="{ row }">
            <span class="file-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="size" label="大小" width="120">
          <template #default="{ row }">
            {{ formatSize(row.size) }}
          </template>
        </el-table-column>
        <el-table-column prop="percent" label="进度" width="150">
          <template #default="{ row }">
            <el-progress
              :percentage="getRowPercent(row)"
              :status="getProgressStatus(row.status)"
              :stroke-width="10"
            />
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusTagType(row.status)" size="small">
              {{ getStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              type="primary"
              size="small"
              text
              @click="handleRetryTask(row)"
              :disabled="Number(row.status) !== -1"
            >
              重试
            </el-button>
            <el-button
              type="danger"
              size="small"
              text
              @click="handleDeleteTask(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
        </el-table>
      </div>
    </el-card>

    <el-dialog
      v-model="addDialogVisible"
      title="添加离线任务"
      width="min(560px, 92vw)"
      destroy-on-close
    >
      <el-form label-width="120px">
        <el-form-item label="下载链接">
          <el-input v-model="addForm.url" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="下载到文件夹">
          <el-tree-select
            v-model="addForm.folderId"
            :data="folderTree"
            :props="folderTreeProps"
            placeholder="选择离线下载目录"
            check-strictly
            lazy
            :load="loadFolderChildren"
            :render-after-expand="false"
            clearable
            @change="handleAddFolderChange"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="addForm.rememberDefault">
            记住此文件夹为默认离线目录
          </el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="confirmAddOfflineTask">确认添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { pan115Api } from '@/api'
import { Refresh } from '@element-plus/icons-vue'
import { normalizePan115FolderOptions } from '@/utils/pan115'

const offlineTasks = ref([])
const loading = ref(false)
const refreshing = ref(false)
const adding = ref(false)
const offlineUrl = ref('')
const lastRefreshAt = ref(0)
const addDialogVisible = ref(false)
const addForm = ref({
  url: '',
  folderId: '0',
  folderName: '根目录',
  rememberDefault: false
})
const offlineDefaultFolder = ref({
  folderId: '0',
  folderName: '根目录'
})
const folderTree = ref([])
const folderTreeProps = {
  label: 'name',
  value: 'id',
  children: 'children',
  isLeaf: (data) => data.isLeaf === true
}

const completedCount = computed(() => offlineTasks.value.filter(item => Number(item.status) === 2).length)
const currentOfflineDefaultFolderText = computed(() => {
  const folderId = offlineDefaultFolder.value.folderId || '0'
  const folderName = offlineDefaultFolder.value.folderName || ''
  if (folderId === '0') return '根目录'
  return folderName ? `${folderName} (ID: ${folderId})` : `ID: ${folderId}`
})

const formatSize = (bytes) => {
  if (!bytes) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = parseFloat(bytes)
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(2)} ${units[unitIndex]}`
}

const getStatusLabel = (status) => {
  const labels = {
    0: '等待中',
    1: '下载中',
    2: '已完成',
    '-1': '失败'
  }
  return labels[status] || '未知'
}

const getStatusTagType = (status) => {
  const types = {
    0: 'info',
    1: 'warning',
    2: 'success',
    '-1': 'danger'
  }
  return types[status] || ''
}

const getProgressStatus = (status) => {
  const normalized = Number(status)
  if (normalized === 2) return 'success'
  if (normalized === -1) return 'exception'
  return ''
}

const getRowPercent = (row) => {
  const percent = row?.percentDone ?? row?.percent ?? 0
  const value = Number(percent)
  if (!Number.isFinite(value)) return 0
  if (value < 0) return 0
  if (value > 100) return 100
  return Number(value.toFixed(2))
}

const normalizeTasks = (data) => {
  if (Array.isArray(data?.tasks)) return data.tasks
  if (Array.isArray(data?.data?.tasks)) return data.data.tasks
  return []
}

const fetchFolders = async (cid = '0') => {
  try {
    const { data } = await pan115Api.getFileList(cid, 0, 50)
    return normalizePan115FolderOptions(data.data)
  } catch (error) {
    return []
  }
}

const loadFolderChildren = async (node, resolve) => {
  const cid = node.level === 0 ? '0' : node.data?.id || '0'
  const folders = await fetchFolders(cid)
  if (node.level === 0) {
    resolve([
      { id: '0', name: '根目录', isLeaf: false },
      ...folders
    ])
    return
  }
  resolve(folders)
}

const findFolderNameById = (nodes, folderId) => {
  const id = String(folderId || '0')
  if (id === '0') return '根目录'
  for (const node of nodes || []) {
    if (String(node.id) === id) return node.name || ''
    if (node.children && node.children.length > 0) {
      const childName = findFolderNameById(node.children, id)
      if (childName) return childName
    }
  }
  return ''
}

const handleAddFolderChange = (value) => {
  const folderId = value ? String(value) : '0'
  addForm.value.folderId = folderId
  addForm.value.folderName = findFolderNameById(folderTree.value, folderId)
}

const fetchOfflineDefaultFolder = async () => {
  try {
    const { data } = await pan115Api.getOfflineDefaultFolder()
    offlineDefaultFolder.value.folderId = data.folder_id || '0'
    offlineDefaultFolder.value.folderName = data.folder_name || (offlineDefaultFolder.value.folderId === '0' ? '根目录' : '')
  } catch (error) {
    offlineDefaultFolder.value.folderId = '0'
    offlineDefaultFolder.value.folderName = '根目录'
  }
}

const fetchOfflineTasks = async () => {
  loading.value = true
  try {
    const { data } = await pan115Api.getOfflineTasks()
    offlineTasks.value = normalizeTasks(data)
  } catch (error) {
    ElMessage.error('获取离线任务失败')
  } finally {
    loading.value = false
  }
}

const handleRefresh = async () => {
  if (refreshing.value || loading.value) return
  const now = Date.now()
  if (now - lastRefreshAt.value < 1500) {
    ElMessage.warning('刷新过于频繁，请稍后再试')
    return
  }
  lastRefreshAt.value = now
  refreshing.value = true
  try {
    await fetchOfflineTasks()
  } finally {
    refreshing.value = false
  }
}

const openAddOfflineDialog = async () => {
  const url = offlineUrl.value.trim()
  if (!url) {
    ElMessage.warning('请先输入离线下载链接')
    return
  }

  await fetchOfflineDefaultFolder()
  addForm.value.url = url
  addForm.value.folderId = offlineDefaultFolder.value.folderId || '0'
  addForm.value.folderName = offlineDefaultFolder.value.folderName || '根目录'
  addForm.value.rememberDefault = false
  addDialogVisible.value = true
}

const confirmAddOfflineTask = async () => {
  const url = addForm.value.url.trim()
  if (!url) {
    ElMessage.warning('请先输入离线下载链接')
    return
  }

  adding.value = true
  try {
    const folderId = addForm.value.folderId || '0'
    const folderName = addForm.value.folderName || (folderId === '0' ? '根目录' : '')
    await pan115Api.addOfflineTask(url, folderId)
    if (addForm.value.rememberDefault) {
      await pan115Api.setOfflineDefaultFolder(folderId, folderName)
      offlineDefaultFolder.value.folderId = folderId
      offlineDefaultFolder.value.folderName = folderName || '根目录'
    }
    offlineUrl.value = ''
    addDialogVisible.value = false
    await fetchOfflineTasks()
    ElMessage.success('已添加离线任务')
  } catch (error) {
    ElMessage.error('添加离线任务失败')
  } finally {
    adding.value = false
  }
}

const handleRetryTask = async (row) => {
  const infoHash = row?.info_hash
  if (!infoHash) {
    ElMessage.warning('缺少任务标识，无法重试')
    return
  }

  try {
    await pan115Api.restartOfflineTask(infoHash)
    await fetchOfflineTasks()
    ElMessage.success('任务已提交重试')
  } catch (error) {
    ElMessage.error('重试失败')
  }
}

const handleDeleteTask = async (row) => {
  const infoHash = row?.info_hash
  if (!infoHash) {
    ElMessage.warning('缺少任务标识，无法删除')
    return
  }

  try {
    await pan115Api.deleteOfflineTasks([infoHash])
    offlineTasks.value = offlineTasks.value.filter(t => t.info_hash !== infoHash)
    ElMessage.success('已删除任务')
  } catch (error) {
    ElMessage.error('删除失败')
  }
}

const handleClearTasks = async () => {
  if (completedCount.value === 0) {
    ElMessage.info('当前没有可清空的已完成任务')
    return
  }

  try {
    const completedOnlyText = completedCount.value > 0
      ? `（当前已完成 ${completedCount.value} 个）`
      : ''
    await ElMessageBox.confirm(`确定要清空已完成离线任务吗？${completedOnlyText}`, '提示', {
      type: 'warning'
    })
    await pan115Api.clearOfflineTasks('completed')
    await fetchOfflineTasks()
    ElMessage.success('已清空已完成任务')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('操作失败')
    }
  }
}

onMounted(() => {
  fetchOfflineDefaultFolder()
  fetchOfflineTasks()
})
</script>

<style lang="scss" scoped>
.downloads-page {
  .add-card {
    margin-bottom: 16px;

    .add-form {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;

      :deep(.el-input) {
        flex: 1;
        min-width: 220px;
      }
    }

    .default-folder-tip {
      margin-top: 10px;
      font-size: 12px;
      color: #a0a0a0;
    }
  }

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;

    h2 {
      margin: 0;
      color: #e0e0e0;
    }
  }

  .tasks-card {
    .table-wrap {
      overflow-x: auto;

      .el-table {
        min-width: 840px;
      }
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  }

  .file-name {
    color: #e0e0e0;
  }
}

@media (max-width: 1024px) {
  .downloads-page {
    .page-header {
      margin-bottom: 16px;
      flex-direction: column;
      align-items: flex-start;
      gap: 10px;

      :deep(.el-button) {
        width: 100%;
      }
    }

    .add-card {
      .add-form {
        :deep(.el-input) {
          min-width: 100%;
        }

        :deep(.el-button) {
          width: 100%;
        }
      }
    }

    .tasks-card {
      .card-header {
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;

        :deep(.el-button) {
          width: 100%;
        }
      }
    }
  }
}

@media (max-width: 768px) {
  .downloads-page {
    .add-card,
    .tasks-card {
      :deep(.el-card__header),
      :deep(.el-card__body) {
        padding-inline: 16px;
      }
    }

    .add-card {
      .default-folder-tip {
        line-height: 1.5;
      }
    }

    .tasks-card {
      .table-wrap {
        .el-table {
          min-width: 720px;
        }
      }
    }
  }
}
</style>
