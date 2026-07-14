<template>
  <div class="strm-page">
    <div class="page-header">
      <div>
        <h2>STRM 设置</h2>
        <p class="page-subtitle">镜像 115 归档输出目录，生成可被 Emby、飞牛影视和支持 HTTP STRM 的播放器直接挂载的 `.strm` 文件。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="refreshing" @click="refreshAll">刷新</el-button>
      </div>
    </div>

    <el-alert
      title="兼容性前提"
      type="info"
      :closable="false"
      show-icon
      class="tip-alert"
      description="STRM 文件里只会写一个播放地址，所以这个地址必须对播放器所在网络可达。如果既要内网也要公网共用同一套 STRM，建议使用固定域名/DDNS，并在内网配合回环 NAT 或 split DNS。"
    />

    <el-card class="section-card">
      <template #header>
        <div class="card-title-row">
          <span class="card-title">STRM 配置</span>
          <div class="status-tags">
            <el-tag :type="config.strm_enabled ? 'success' : 'info'">{{ config.strm_enabled ? '已启用' : '未启用' }}</el-tag>
            <el-tag :type="runtime.generate_running ? 'warning' : 'info'">{{ runtime.generate_running ? '生成中' : '空闲' }}</el-tag>
          </div>
        </div>
      </template>

      <el-form label-width="150px" class="config-form">
        <div class="config-grid">
          <el-form-item label="启用 STRM">
            <el-switch v-model="config.strm_enabled" />
          </el-form-item>

          <el-form-item label="归档后自动生成">
            <el-switch v-model="config.strm_auto_after_archive" :disabled="!config.strm_enabled" />
            <div class="form-hint">归档成功（或跳过重复项）后自动增量生成 STRM，默认开启</div>
          </el-form-item>

          <el-form-item label="播放模式">
            <el-select v-model="config.strm_redirect_mode" style="width: 220px">
              <el-option label="自动（推荐）" value="auto" />
              <el-option label="302 直链播放" value="redirect" />
              <el-option label="服务器代理" value="proxy" />
            </el-select>
            <div class="form-hint">302 直链会绑定当前播放器的 User-Agent；如果 115 链接要求额外 Cookie（f=3），系统会自动回退代理。</div>
          </el-form-item>

          <el-form-item label="生成后刷新 Emby">
            <el-switch v-model="config.strm_refresh_emby_after_generate" />
          </el-form-item>

          <el-form-item label="生成后刷新飞牛">
            <el-switch v-model="config.strm_refresh_feiniu_after_generate" />
          </el-form-item>

          <el-form-item label="定时增量生成">
            <el-switch v-model="config.strm_schedule_enabled" />
          </el-form-item>

          <el-form-item label="增量生成间隔">
            <el-input-number
              v-model="config.strm_incremental_interval_minutes"
              :min="30"
              :step="30"
              :disabled="!config.strm_schedule_enabled"
              style="width: 180px"
            />
            <span class="input-suffix">分钟</span>
          </el-form-item>

          <el-form-item label="每周全量生成">
            <el-switch v-model="config.strm_full_schedule_enabled" />
          </el-form-item>

          <el-form-item label="全量生成时间">
            <div class="schedule-time-row">
              <el-select
                v-model="config.strm_full_schedule_day"
                :disabled="!config.strm_full_schedule_enabled"
                style="width: 110px"
              >
                <el-option v-for="item in weekOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-time-select
                v-model="config.strm_full_schedule_time"
                start="00:00"
                step="00:30"
                end="23:30"
                :disabled="!config.strm_full_schedule_enabled"
                style="width: 130px"
              />
            </div>
          </el-form-item>

          <el-form-item label="STRM 输出目录" class="grid-span-2">
            <el-select
              v-model="config.strm_output_dir"
              filterable
              allow-create
              default-first-option
              placeholder="选择或输入目录路径"
              style="width: 100%"
            >
              <el-option
                v-for="item in mountPaths"
                :key="item.path"
                :label="item.writable ? `${item.path}（${item.label}，可写）` : `${item.path}（${item.label}，不可写）`"
                :value="item.path"
                :disabled="!item.writable"
              />
            </el-select>
            <div class="form-hint">列表为容器内已挂载的可写路径，也可手动输入其他路径。Docker 部署时建议选 `/app/strm`。</div>
          </el-form-item>

          <el-form-item label="播放根地址" class="grid-span-2">
            <el-input v-model="config.strm_base_url" :placeholder="suggestedBaseUrl || '例如：http://192.168.1.100:9008'" />
            <div class="form-hint">STRM 播放地址使用端口 `9008`（或代理端口）。生成格式为 `/api/115/url/video.扩展名?pickcode=...`（旧 token 链接仍兼容）。</div>
          </el-form-item>

          <el-form-item label="Emby 代理">
            <el-switch v-model="config.strm_proxy_enabled" />
            <div class="form-hint">启用后 STRM 文件将指向代理端口。Emby 客户端必须连接 `IP:8099`（不要用 8096），播放时才会 302 到 115 直链，服务器不再中转视频流量。</div>
          </el-form-item>

          <el-form-item v-if="config.strm_proxy_enabled" label="代理端口">
            <el-input-number v-model="config.strm_proxy_port" :min="1024" :max="65535" :step="1" style="width: 160px" />
            <div class="form-hint">默认为 8099。Emby 客户端请连接此端口的代理地址。</div>
          </el-form-item>

          <el-form-item v-if="config.strm_proxy_enabled" label="优化首播速度">
            <el-switch v-model="config.strm_early_redirect" />
            <div class="form-hint">SmartStrm 风格：PlaybackInfo 阶段提前返回 115 CDN 直链，缩短 ISO/原盘起播等待（实验性，部分客户端可能不兼容）。</div>
          </el-form-item>
        </div>

        <div class="config-actions">
          <el-button type="primary" :loading="saving" @click="saveConfig">保存配置</el-button>
          <el-button type="primary" :loading="generating && generatingMode === 'incremental'" :disabled="generating && generatingMode !== 'incremental'" @click="generateFiles('incremental')">增量生成</el-button>
          <el-button type="danger" plain :loading="generating && generatingMode === 'full'" :disabled="generating && generatingMode !== 'full'" @click="confirmFullGenerate">全量生成</el-button>
          <el-button :loading="diagnosing" @click="diagnoseStrm">STRM 诊断</el-button>
        </div>
        <div class="form-hint" style="margin-top: 8px">
          清空本地 STRM 目录后请点「全量生成」重建；仅点增量可能因快照未变而不补写文件。
        </div>
      </el-form>
    </el-card>

    <el-card class="section-card">
      <template #header>
        <div class="card-title">运行状态</div>
      </template>

      <div class="status-grid">
        <div class="status-item">
          <span class="status-label">归档输出目录</span>
          <span class="status-value">{{ config.archive_output_name || config.archive_output_cid || '未配置' }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">播放模式</span>
          <span class="status-value">{{ redirectModeLabel }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">当前生成模式</span>
          <span class="status-value">{{ generateModeLabel }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">索引规模</span>
          <span class="status-value">{{ indexCountsText }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">最近增量生成</span>
          <span class="status-value">{{ formatRuntimeTime(lastIncrementalAt) }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">最近全量生成</span>
          <span class="status-value">{{ formatRuntimeTime(lastFullAt) }}</span>
        </div>
        <div class="status-item status-item-full">
          <span class="status-label">输出目录</span>
          <span class="status-value">{{ config.strm_output_dir || '未配置' }}</span>
        </div>
        <div class="status-item status-item-full">
          <span class="status-label">播放地址模板</span>
          <span class="status-value break-all">{{ playUrlTemplate }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">开始时间</span>
          <span class="status-value">{{ runtime.last_generate_started_at ? formatBeijingTableCell(null, null, runtime.last_generate_started_at) : '-' }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">结束时间</span>
          <span class="status-value">{{ runtime.last_generate_finished_at ? formatBeijingTableCell(null, null, runtime.last_generate_finished_at) : '-' }}</span>
        </div>
        <div class="status-item status-item-full">
          <span class="status-label">最近结果</span>
          <span class="status-value">{{ summaryText }}</span>
        </div>
        <div v-if="runtime.last_generate_error" class="status-item status-item-full">
          <span class="status-label">失败原因</span>
          <span class="status-value status-error">{{ runtime.last_generate_error }}</span>
        </div>
      </div>

      <div v-if="diagnosis" class="diagnosis-block">
        <el-divider />
        <div class="card-title">STRM 诊断</div>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="样本文件">
            <span class="break-all">{{ diagnosis.sample_file || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="当前 UA">
            <span class="break-all">{{ diagnosis.player_user_agent || '空' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="配置模式">
            {{ getModeLabel(diagnosis.configured_mode) }}
          </el-descriptions-item>
          <el-descriptions-item label="实际模式">
            {{ getModeLabel(diagnosis.effective_mode) }}
          </el-descriptions-item>
          <el-descriptions-item label="115 要求">
            {{ getRequirementLabel(diagnosis.direct_requirement) }}
          </el-descriptions-item>
          <el-descriptions-item label="直链探测">
            {{ getProbeText(diagnosis.direct_probe) }}
          </el-descriptions-item>
          <el-descriptions-item label="样本链接">
            <span class="break-all">{{ diagnosis.sample_url || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="115 直链">
            <span class="break-all">{{ diagnosis.download_url || '-' }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-alert
          :closable="false"
          type="info"
          show-icon
          class="diagnosis-alert"
          :title="diagnosis.reason || '已完成 STRM 诊断'"
          :description="diagnosis.note || ''"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { strmApi } from '@/api'
import { formatBeijingTableCell } from '@/utils/timezone'

const refreshing = ref(false)
const saving = ref(false)
const generating = ref(false)
const generatingMode = ref('')
const diagnosing = ref(false)
const mountPaths = ref([])
const suggestedBaseUrl = ref('')
const diagnosis = ref(null)
let pollingTimer = null
const weekOptions = [
  { label: '周一', value: 'mon' },
  { label: '周二', value: 'tue' },
  { label: '周三', value: 'wed' },
  { label: '周四', value: 'thu' },
  { label: '周五', value: 'fri' },
  { label: '周六', value: 'sat' },
  { label: '周日', value: 'sun' }
]

const config = reactive({
  strm_enabled: false,
  strm_output_dir: '',
  strm_base_url: '',
  strm_redirect_mode: 'auto',
  strm_auto_after_archive: true,
  strm_refresh_emby_after_generate: false,
  strm_refresh_feiniu_after_generate: false,
  strm_proxy_enabled: false,
  strm_proxy_port: 8099,
  strm_early_redirect: true,
  strm_schedule_enabled: false,
  strm_incremental_interval_minutes: 360,
  strm_full_schedule_enabled: false,
  strm_full_schedule_day: 'sun',
  strm_full_schedule_time: '03:00',
  archive_output_cid: '',
  archive_output_name: ''
})

const runtime = reactive({
  generate_running: false,
  last_generate_started_at: '',
  last_generate_finished_at: '',
  last_generate_error: '',
  last_generate_summary: null,
  last_generate_trigger: '',
  current_mode: '',
  last_generate_mode: '',
  index_file_count: 0,
  index_directory_count: 0,
  last_incremental_at: '',
  last_full_at: ''
})

const redirectModeLabel = computed(() => {
  if (config.strm_redirect_mode === 'redirect') return '302 直链播放'
  if (config.strm_redirect_mode === 'proxy') return '服务器代理'
  return '自动（推荐）'
})

const playUrlTemplate = computed(() => {
  if (!config.strm_base_url) return '未配置'
  let base = config.strm_base_url.replace(/\/$/, '')
  if (config.strm_proxy_enabled) {
    const url = new URL(base)
    base = `${url.protocol}//${url.hostname}:${config.strm_proxy_port || 8099}`
  }
  return `${base}/api/strm/play/<token>`
})

const summaryText = computed(() => {
  const summary = runtime.last_generate_summary
  if (!summary) return '暂无生成记录'
  return `扫描 ${summary.scanned_video_count || 0} 个视频，写入 ${summary.written_count || 0} 个，未改动 ${summary.unchanged_count || 0} 个，删除 ${summary.removed_count || 0} 个`
})

const generateModeLabel = computed(() => {
  const mode = runtime.current_mode
    || runtime.generate_mode
    || runtime.last_generate_mode
    || runtime.last_generate_summary?.mode
    || runtime.index_stats?.last_mode
  if (mode === 'incremental') return runtime.generate_running ? '增量生成中' : '增量生成'
  if (mode === 'full') return runtime.generate_running ? '全量生成中' : '全量生成'
  return runtime.generate_running ? '生成中' : '-'
})

const indexCountsText = computed(() => {
  const files = runtime.index_stats?.file_count
    ?? runtime.index_file_count
    ?? runtime.indexed_file_count
    ?? runtime.index_count
    ?? 0
  const directories = runtime.index_stats?.folder_count
    ?? runtime.index_directory_count
    ?? runtime.indexed_directory_count
    ?? runtime.directory_count
  return directories == null ? `${files} 个文件` : `${files} 个文件，${directories} 个目录`
})

const lastIncrementalAt = computed(() => (
  runtime.last_incremental_at
  || runtime.last_incremental_finished_at
  || (runtime.last_generate_summary?.mode === 'incremental' ? runtime.last_generate_finished_at : '')
))
const lastFullAt = computed(() => (
  runtime.last_full_at
  || runtime.last_full_finished_at
  || (runtime.last_generate_summary?.mode === 'full' ? runtime.last_generate_finished_at : '')
))
const formatRuntimeTime = (value) => (
  value ? formatBeijingTableCell(null, null, value) : '-'
)

const getModeLabel = (mode) => {
  if (mode === 'redirect') return '302 直链播放'
  if (mode === 'proxy') return '服务器代理'
  return '自动（推荐）'
}

const getRequirementLabel = (requirement) => {
  if (requirement === '1') return 'f=1，要求绑定 User-Agent'
  if (requirement === '3') return 'f=3，要求额外 Cookie'
  return '无特殊要求'
}

const getProbeText = (probe) => {
  if (!probe) return '-'
  if (!probe.ok) {
    return probe.status_code ? `失败 (${probe.status_code})` : `失败 (${probe.error || '未知错误'})`
  }
  const sizeText = probe.content_length ? `，长度 ${probe.content_length}` : ''
  return `成功 (${probe.status_code}${sizeText})`
}

const applyConfig = (data) => {
  const wasGenerating = runtime.generate_running || generating.value

  config.strm_enabled = !!data.strm_enabled
  config.strm_output_dir = data.strm_output_dir || ''
  config.strm_base_url = data.strm_base_url || ''
  config.strm_redirect_mode = data.strm_redirect_mode || 'auto'
  config.strm_auto_after_archive = data.strm_auto_after_archive !== false
  config.strm_refresh_emby_after_generate = !!data.strm_refresh_emby_after_generate
  config.strm_refresh_feiniu_after_generate = !!data.strm_refresh_feiniu_after_generate
  config.strm_proxy_enabled = !!data.strm_proxy_enabled
  config.strm_proxy_port = Number(data.strm_proxy_port) || 8099
  config.strm_early_redirect = data.strm_early_redirect !== false
  config.strm_schedule_enabled = !!data.strm_schedule_enabled
  config.strm_incremental_interval_minutes = Number(data.strm_incremental_interval_minutes) || 360
  config.strm_full_schedule_enabled = !!data.strm_full_schedule_enabled
  config.strm_full_schedule_day = data.strm_full_schedule_day || 'sun'
  config.strm_full_schedule_time = data.strm_full_schedule_time || '03:00'
  config.archive_output_cid = data.archive_output_cid || ''
  config.archive_output_name = data.archive_output_name || ''
  mountPaths.value = Array.isArray(data.mount_paths) ? data.mount_paths : []
  suggestedBaseUrl.value = data.suggested_base_url || ''

  const nextRuntime = data.runtime || {}
  Object.assign(runtime, nextRuntime)
  runtime.generate_running = !!nextRuntime.generate_running
  runtime.last_generate_started_at = nextRuntime.last_generate_started_at || ''
  runtime.last_generate_finished_at = nextRuntime.last_generate_finished_at || ''
  runtime.last_generate_error = nextRuntime.last_generate_error || ''
  runtime.last_generate_summary = nextRuntime.last_generate_summary || null
  runtime.last_generate_trigger = nextRuntime.last_generate_trigger || ''

  generating.value = runtime.generate_running
  if (runtime.generate_running) {
    generatingMode.value = nextRuntime.current_mode || nextRuntime.generate_mode || nextRuntime.last_generate_mode || generatingMode.value
  }
  if (wasGenerating && !runtime.generate_running) {
    if (runtime.last_generate_error) {
      ElMessage.error(runtime.last_generate_error)
    } else if (runtime.last_generate_summary) {
      ElMessage.success(
        `STRM 后台生成完成：写入 ${runtime.last_generate_summary.written_count || 0} 个，删除 ${runtime.last_generate_summary.removed_count || 0} 个`
      )
    }
    generatingMode.value = ''
  }
}

const loadConfig = async () => {
  const { data } = await strmApi.getConfig()
  applyConfig(data)
  setupPolling()
}

const refreshAll = async () => {
  refreshing.value = true
  try {
    await loadConfig()
  } finally {
    refreshing.value = false
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    const { data } = await strmApi.updateConfig({
      strm_enabled: config.strm_enabled,
      strm_output_dir: config.strm_output_dir,
      strm_base_url: config.strm_base_url,
      strm_redirect_mode: config.strm_redirect_mode,
      strm_auto_after_archive: config.strm_auto_after_archive,
      strm_refresh_emby_after_generate: config.strm_refresh_emby_after_generate,
      strm_refresh_feiniu_after_generate: config.strm_refresh_feiniu_after_generate,
      strm_proxy_enabled: config.strm_proxy_enabled,
      strm_proxy_port: config.strm_proxy_port,
      strm_early_redirect: config.strm_early_redirect,
      strm_schedule_enabled: config.strm_schedule_enabled,
      strm_incremental_interval_minutes: config.strm_incremental_interval_minutes,
      strm_full_schedule_enabled: config.strm_full_schedule_enabled,
      strm_full_schedule_day: config.strm_full_schedule_day,
      strm_full_schedule_time: config.strm_full_schedule_time
    })
    applyConfig(data)
    ElMessage.success('STRM 配置已保存')
  } finally {
    saving.value = false
  }
}

const generateFiles = async (mode = 'incremental') => {
  generating.value = true
  generatingMode.value = mode
  try {
    const { data } = await strmApi.generate(mode)
    const label = mode === 'full' ? '全量生成' : '增量生成'
    ElMessage.success(data.started ? `STRM ${label}任务已启动` : `STRM ${label}任务已提交`)
    await loadConfig()
    setupPolling()
  } catch (error) {
    generating.value = false
    generatingMode.value = ''
    throw error
  }
}

const confirmFullGenerate = async () => {
  try {
    await ElMessageBox.confirm(
      '全量生成会重新扫描整个 115 归档目录并重建全部 STRM 文件，适合清空本地 STRM 目录后使用，耗时可能较长。确定继续吗？',
      '确认全量生成',
      {
        confirmButtonText: '开始全量生成',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return
  }
  await generateFiles('full')
}

const diagnoseStrm = async () => {
  diagnosing.value = true
  try {
    const { data } = await strmApi.diagnose()
    diagnosis.value = data || null
    ElMessage.success('STRM 诊断完成')
  } finally {
    diagnosing.value = false
  }
}

const stopPolling = () => {
  if (pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
}

const setupPolling = () => {
  stopPolling()
  if (!runtime.generate_running) return
  pollingTimer = setInterval(async () => {
    try {
      const { data } = await strmApi.getConfig()
      applyConfig(data)
      if (!data.runtime?.generate_running) {
        stopPolling()
      }
    } catch (error) {
      console.error('Failed to poll STRM status:', error)
    }
  }, 4000)
}

onMounted(loadConfig)
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.strm-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.page-header h2 {
  margin: 0;
  font-size: 24px;
}

.page-subtitle {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.tip-alert {
  margin-top: -4px;
}

.section-card {
  border-radius: 18px;
}

.card-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.card-title {
  font-weight: 600;
}

.status-tags {
  display: flex;
  gap: 8px;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 20px;
}

.grid-span-2 {
  grid-column: span 2;
}

.config-actions {
  margin-top: 8px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.form-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.input-suffix {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
}

.schedule-time-row {
  display: flex;
  gap: 8px;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 20px;
}

.status-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
  border-radius: 14px;
  background: var(--el-fill-color-light);
}

.status-item-full {
  grid-column: span 2;
}

.status-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.status-value {
  font-size: 14px;
  line-height: 1.6;
  color: var(--el-text-color-primary);
}

.status-error {
  color: var(--el-color-danger);
}

.break-all {
  word-break: break-all;
}

.diagnosis-block {
  margin-top: 16px;
}

.diagnosis-alert {
  margin-top: 12px;
}

@media (max-width: 900px) {
  .page-header {
    flex-direction: column;
  }

  .header-actions {
    width: 100%;
  }

  .header-actions :deep(.el-button) {
    flex: 1;
  }

  .config-grid,
  .status-grid {
    grid-template-columns: 1fr;
  }

  .grid-span-2,
  .status-item-full {
    grid-column: span 1;
  }
}
</style>
