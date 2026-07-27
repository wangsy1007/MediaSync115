<template>
  <div class="logs-page">
    <div class="page-header">
      <h2>日志中心</h2>
      <div class="page-actions">
        <el-switch v-model="autoRefresh" active-text="自动刷新" />
        <el-button type="primary" :loading="loading" @click="handleSearch">刷新</el-button>
        <el-button type="danger" plain :loading="clearing" @click="handleClearLogs">清空日志</el-button>
      </div>
    </div>

    <div class="filter-bar">
      <el-select
        v-model="filters.category"
        clearable
        placeholder="全部分类"
        class="filter-select"
        @change="handleSearch"
      >
        <el-option
          v-for="item in categoryOptions"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </el-select>

      <el-input-number
        v-model="filters.limit"
        :min="20"
        :max="500"
        :step="20"
        controls-position="right"
        class="filter-limit"
        @change="handleSearch"
      />
      <span class="filter-hint">条/页</span>
    </div>

    <el-card>
      <div v-loading="loading">
        <div v-if="!logs.length" class="empty-state">
          <el-empty description="暂无日志" />
        </div>

        <div class="log-list">
          <div
            v-for="(log, index) in logs"
            :key="log.id || index"
            class="log-row"
            :class="[`status-${log.status}`, { expanded: expandedIds.has(log.id) }]"
            @click="toggleExpand(log.id)"
          >
            <span class="log-time">{{ formatTime(log.created_at) }}</span>
            <el-tag
              v-if="log.module"
              size="small"
              :type="resolveCategory(log.module).value === 'play' ? 'success' : 'info'"
              class="log-module"
            >
              {{ resolveCategory(log.module).label }}
            </el-tag>
            <span class="log-text">{{ log.message || '-' }}</span>
            <span class="log-duration" v-if="log.duration_ms">{{ log.duration_ms }}ms</span>

            <div v-show="expandedIds.has(log.id)" class="log-expand">
              <div v-if="log.request_summary" class="exp-block">
                <div class="exp-title">请求详情</div>
                <pre>{{ formatSummaryBlock(log.request_summary) }}</pre>
              </div>
              <div v-if="log.response_summary" class="exp-block">
                <div class="exp-title">响应详情</div>
                <pre>{{ formatSummaryBlock(log.response_summary) }}</pre>
              </div>
              <div v-if="log.extra" class="exp-block">
                <div class="exp-title">额外信息</div>
                <pre>{{ formatSummaryBlock(log.extra) }}</pre>
              </div>
            </div>
          </div>
        </div>
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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { logsApi } from '@/api'

const AUTO_REFRESH_MS = 5000

/** 过滤用分类：同类模块合并为一类 */
const LOG_CATEGORIES = [
  { value: 'play', label: '播放', modules: ['play'] },
  { value: 'strm', label: 'STRM', modules: ['strm'] },
  { value: 'archive', label: '归档', modules: ['archive'] },
  {
    value: 'subscriptions',
    label: '订阅',
    modules: ['subscriptions', 'chart_subscription', 'person_follow'],
  },
  {
    value: 'transfer',
    label: '转存',
    modules: ['pan115', 'manual_transfer', 'quark', 'hdhive', 'explore_queue'],
  },
  {
    value: 'sync',
    label: '同步',
    modules: ['sync', 'emby_sync', 'feiniu_sync', 'tg_sync'],
  },
  {
    value: 'scheduler',
    label: '调度',
    modules: ['scheduler', 'workflow'],
  },
  {
    value: 'system',
    label: '系统',
    modules: ['settings', 'auth', 'search', 'tmdb', 'unknown'],
  },
]

const OTHER_CATEGORY = { value: 'other', label: '其他', modules: [] }

const loading = ref(false)
const clearing = ref(false)
const autoRefresh = ref(true)
const logs = ref([])
const total = ref(0)
const currentPage = ref(1)
const expandedIds = ref(new Set())
const availableModules = ref([])
let refreshTimer = null

const filters = ref({
  category: '',
  limit: 100,
})

const moduleToCategory = (() => {
  const map = new Map()
  for (const category of LOG_CATEGORIES) {
    for (const module of category.modules) {
      map.set(module, category)
    }
  }
  return map
})()

const resolveCategory = (module) => {
  const key = String(module || '').trim()
  if (!key) return OTHER_CATEGORY
  return moduleToCategory.get(key) || OTHER_CATEGORY
}

const categoryOptions = computed(() => {
  const present = new Set(
    availableModules.value.map((item) => String(item || '').trim()).filter(Boolean)
  )
  // 尚无日志时展示完整分类；有日志时只展示实际出现过的类别
  const base = !present.size
    ? LOG_CATEGORIES
    : LOG_CATEGORIES.filter((category) =>
        category.modules.some((module) => present.has(module))
      )
  const options = base.map((category) => ({
    value: category.value,
    label: category.label,
  }))
  const hasOther = [...present].some((module) => !moduleToCategory.has(module))
  if (hasOther) {
    options.push({ value: OTHER_CATEGORY.value, label: OTHER_CATEGORY.label })
  }
  return options
})

const resolveCategoryModules = (categoryValue) => {
  const key = String(categoryValue || '').trim()
  if (!key) return []
  if (key === OTHER_CATEGORY.value) {
    const known = new Set(LOG_CATEGORIES.flatMap((item) => item.modules))
    return availableModules.value
      .map((item) => String(item || '').trim())
      .filter((module) => module && !known.has(module))
  }
  const category = LOG_CATEGORIES.find((item) => item.value === key)
  return category ? [...category.modules] : []
}

const formatTime = (val) => {
  if (!val) return '-'
  const d = new Date(val)
  if (isNaN(d.getTime())) return '-'
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

const tryParseJson = (value) => {
  if (typeof value !== 'string') return value
  const text = value.trim()
  if (!text) return value
  if (!(text.startsWith('{') || text.startsWith('['))) return value
  try { return JSON.parse(text) } catch { return value }
}

const formatSummaryBlock = (value) => {
  if (!value) return '-'
  const parsed = tryParseJson(value)
  try {
    return JSON.stringify(parsed, null, 2)
  } catch {
    return String(parsed)
  }
}

const hasDetail = (log) => {
  return log.request_summary || log.response_summary || log.extra
}

const toggleExpand = (id) => {
  if (!hasDetail(logs.value.find(l => l.id === id))) return
  const set = expandedIds.value
  if (set.has(id)) set.delete(id)
  else set.add(id)
}

const fetchModules = async () => {
  try {
    const { data } = await logsApi.modules()
    availableModules.value = Array.isArray(data?.modules) ? data.modules : []
  } catch {
    // 分类选项加载失败时仍可用内置分类筛选
  }
}

const fetchLogs = async ({ silent = false } = {}) => {
  if (!silent) loading.value = true
  try {
    const params = {
      limit: Number(filters.value.limit || 100),
      offset: (currentPage.value - 1) * Number(filters.value.limit || 100),
      exclude_source_type: 'api',
    }
    const modules = resolveCategoryModules(filters.value.category)
    if (modules.length) {
      params.module = modules.join(',')
      const { data } = await logsApi.list(params)
      logs.value = Array.isArray(data?.items) ? data.items : []
      total.value = Number(data?.total || 0)
    } else if (String(filters.value.category || '').trim()) {
      // 选中分类但当前无对应模块（如「其他」为空）
      logs.value = []
      total.value = 0
    } else {
      const { data } = await logsApi.list(params)
      logs.value = Array.isArray(data?.items) ? data.items : []
      total.value = Number(data?.total || 0)
    }
  } catch (error) {
    if (!silent) {
      ElMessage.error(error.response?.data?.detail || '日志获取失败')
    }
  } finally {
    if (!silent) loading.value = false
  }
}

const stopAutoRefresh = () => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

const startAutoRefresh = () => {
  stopAutoRefresh()
  if (!autoRefresh.value) return
  refreshTimer = setInterval(() => {
    fetchLogs({ silent: true })
  }, AUTO_REFRESH_MS)
}

watch(autoRefresh, (enabled) => {
  if (enabled) startAutoRefresh()
  else stopAutoRefresh()
})

const handleSearch = async () => {
  currentPage.value = 1
  expandedIds.value.clear()
  await fetchLogs()
}

const handlePageChange = async (page) => {
  currentPage.value = Number(page || 1)
  await fetchLogs()
}

const handleClearLogs = async () => {
  clearing.value = true
  try {
    const { data } = await logsApi.clear()
    logs.value = []
    total.value = 0
    currentPage.value = 1
    expandedIds.value.clear()
    await fetchModules()
    ElMessage.success(`已清空 ${Number(data?.removed || 0)} 条日志`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '清空日志失败')
  } finally {
    clearing.value = false
  }
}

onMounted(async () => {
  await Promise.all([fetchModules(), fetchLogs()])
  startAutoRefresh()
})

onBeforeUnmount(stopAutoRefresh)
</script>

<style lang="scss" scoped>
.logs-page {
  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;

    h2 {
      margin: 0;
      color: var(--ms-text-primary);
      white-space: nowrap;
    }

    .page-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
  }

  .filter-bar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 16px;
  }

  .filter-select {
    width: 160px;
  }

  .filter-limit {
    width: 120px;
  }

  .filter-hint {
    font-size: 13px;
    color: var(--ms-text-secondary);
  }

  .empty-state {
    padding: 60px 0;
  }

  .log-list {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }

  .log-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    font-size: 13px;
    line-height: 1.4;
    cursor: pointer;
    border-radius: 4px;
    transition: background 0.15s;
    flex-wrap: wrap;

    &:hover {
      background: var(--ms-bg-hover);
    }

    &.status-success { border-left: 3px solid var(--el-color-success); }
    &.status-failed { border-left: 3px solid var(--el-color-danger); }
    &.status-warning { border-left: 3px solid var(--el-color-warning); }
    &.status-partial { border-left: 3px solid var(--el-color-warning); }
    &.status-info { border-left: 3px solid var(--el-color-info); }

    &.expanded {
      background: var(--ms-bg-hover);
    }
  }

  .log-time {
    color: var(--ms-text-secondary);
    font-size: 12px;
    font-family: monospace;
    flex-shrink: 0;
    min-width: 60px;
  }

  .log-module {
    flex-shrink: 0;
  }

  .log-text {
    color: var(--ms-text-primary);
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .log-duration {
    color: var(--ms-text-secondary);
    font-size: 12px;
    font-family: monospace;
    flex-shrink: 0;
  }

  .log-expand {
    width: 100%;
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px solid var(--ms-border-color);
  }

  .exp-block {
    background: var(--ms-bg-card);
    border: 1px solid var(--ms-border-color);
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 6px;

    &:last-child { margin-bottom: 0; }
  }

  .exp-title {
    font-size: 11px;
    font-weight: 600;
    color: var(--ms-text-primary);
    margin-bottom: 4px;
  }

  .exp-block pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 11px;
    line-height: 1.5;
    color: var(--ms-text-secondary);
  }

  .pager-wrap {
    margin-top: 16px;
    display: flex;
    justify-content: flex-end;
  }
}

@media (max-width: 768px) {
  .logs-page {
    .page-header {
      flex-direction: column;
      align-items: stretch;

      .page-actions {
        justify-content: flex-start;
      }
    }

    .filter-bar {
      .filter-select,
      .filter-limit {
        width: 100%;
      }
    }

    .log-row {
      padding: 5px 8px;
      font-size: 12px;
    }

    .pager-wrap {
      justify-content: center;
      overflow-x: auto;
    }
  }
}
</style>
