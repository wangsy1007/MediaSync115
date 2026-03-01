<template>
  <div class="settings-page">
    <h2>系统设置</h2>

    <el-tabs v-model="activeSettingsTab" class="settings-tabs">
      <el-tab-pane label="115网盘" name="pan115">
        <el-card class="settings-card">
          <template #header>
            <div class="card-header">
              <span>115网盘配置</span>
              <div class="status-tags">
                <el-tag v-if="cookieStatus.valid" type="success" size="small">已连接</el-tag>
                <el-tag v-else-if="cookieStatus.checked" type="danger" size="small">未连接</el-tag>
                <el-tag v-if="riskHealth.checked" :type="riskHealthTagType" size="small">{{ riskHealthTagText }}</el-tag>
              </div>
            </div>
          </template>

          <el-form :model="settingsForm" label-width="120px">
            <el-form-item label="Cookie状态">
              <div class="cookie-status">
                <span v-if="cookieInfo.configured">{{ cookieInfo.masked_cookie }}</span>
                <span v-else class="not-configured">未配置</span>
              </div>
            </el-form-item>
            <el-form-item label="更新Cookie">
              <el-input
                v-model="settingsForm.cookie"
                type="textarea"
                :rows="3"
                placeholder="请输入115网盘Cookie（格式：UID=xxx; CID=xxx; SEID=xxx）"
              />
              <div class="cookie-tips">
                <el-text size="small" type="info">
                  获取方法：登录115网盘网页版 → 按F12打开开发者工具 → Network → 刷新页面 → 点击任意请求 → Headers → 找到Cookie字段
                </el-text>
              </div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="handleSaveCookie" :loading="saving">保存Cookie</el-button>
              <el-button @click="handleTestConnection" :loading="testing">测试连接</el-button>
              <el-button @click="handleTestRiskHealth" :loading="testingRiskHealth">检测风控</el-button>
            </el-form-item>
          </el-form>

          <div
            v-if="connectionResult.checked"
            class="connection-result"
            :class="connectionResult.success ? 'is-success' : 'is-failed'"
          >
            <div class="result-title">连接检测结果</div>
            <div class="result-message">{{ connectionResult.message }}</div>
          </div>

          <el-alert
            v-if="riskHealth.checked"
            :title="riskHealth.summary || '115状态检测完成'"
            :description="riskHealth.detail || undefined"
            :type="riskHealthAlertType"
            :closable="false"
            show-icon
            style="margin-top: 12px"
          />

          <div v-if="cookieStatus.valid && cookieStatus.user_info" class="user-info">
            <el-divider />
            <h4>用户信息</h4>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="用户名">{{ cookieStatus.user_info.user_name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="用户ID">{{ cookieStatus.user_info.user_id || '-' }}</el-descriptions-item>
              <el-descriptions-item label="会员状态">
                <el-tag v-if="cookieStatus.user_info.is_vip && cookieStatus.user_info.is_vip > 0" type="warning" size="small">
                  VIP{{ cookieStatus.user_info.is_vip > 1 ? cookieStatus.user_info.is_vip : '' }}
                </el-tag>
                <el-tag v-else type="info" size="small">普通用户</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="已用空间">{{ formatSize(cookieStatus.user_info.space_used) }}</el-descriptions-item>
              <el-descriptions-item label="总空间">{{ formatSize(cookieStatus.user_info.space_total) }}</el-descriptions-item>
            </el-descriptions>
          </div>

          <div v-if="cookieStatus.valid" class="default-folder-section">
            <el-divider />
            <h4>转存设置</h4>
            <el-form :model="defaultFolderForm" label-width="120px">
              <el-form-item label="默认保存位置">
                <div class="folder-selector">
                  <el-tree-select
                    v-model="defaultFolderForm.folderId"
                    class="default-folder-select"
                    :data="folderTree"
                    :props="folderTreeProps"
                    placeholder="选择默认转存目录"
                    check-strictly
                    lazy
                    :load="loadFolderChildren"
                    :render-after-expand="false"
                    clearable
                    @change="handleDefaultFolderChange"
                  />
                  <el-button type="primary" @click="handleSaveDefaultFolder" :loading="savingFolder">
                    保存设置
                  </el-button>
                </div>
                <div class="current-folder">
                  <el-text size="small">当前默认转存位置：{{ currentDefaultFolderText }}</el-text>
                </div>
                <div class="folder-tips">
                  <el-text size="small" type="info">
                    设置后，转存资源时将默认保存到此目录
                  </el-text>
                </div>
              </el-form-item>
            </el-form>
          </div>

          <div v-if="cookieStatus.valid" class="offline-folder-section">
            <el-divider />
            <h4>离线下载设置</h4>
            <el-form label-width="120px">
              <el-form-item label="默认离线目录">
                <div class="current-folder">
                  <el-text>{{ currentOfflineDefaultFolderText }}</el-text>
                </div>
                <div class="folder-action">
                  <el-button type="primary" @click="handleOpenOfflineFolderDialog">
                    修改默认设置
                  </el-button>
                </div>
                <div class="folder-tips">
                  <el-text size="small" type="info">
                    添加离线任务时会默认使用此目录
                  </el-text>
                </div>
              </el-form-item>
            </el-form>
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="Nullbr" name="nullbr">
        <el-card class="settings-card">
          <template #header>
            <span>Nullbr API 配置</span>
          </template>

          <el-form :model="nullbrForm" label-width="120px">
            <el-form-item label="APP ID">
              <el-input v-model="nullbrForm.appId" placeholder="Nullbr APP ID" />
            </el-form-item>
            <el-form-item label="API Key">
              <el-input v-model="nullbrForm.apiKey" placeholder="Nullbr API Key" type="password" show-password />
            </el-form-item>
            <el-form-item label="Base URL">
              <el-input v-model="nullbrForm.baseUrl" placeholder="例如: https://api.nullbr.eu.org/" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingNullbr" @click="handleSaveNullbr">保存</el-button>
              <el-button :loading="testingNullbr" @click="handleTestNullbr">测试凭证</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="HDHive" name="hdhive">
        <el-card class="settings-card">
          <template #header>
            <div class="card-header">
              <span>HDHive 配置</span>
              <el-tag v-if="hdhiveStatus.checked" :type="hdhiveStatus.valid ? 'success' : 'danger'" size="small">
                {{ hdhiveStatus.valid ? '已连接' : '未连接' }}
              </el-tag>
            </div>
          </template>

          <el-form :model="hdhiveForm" label-width="120px">
            <el-form-item label="Cookie">
              <el-input
                v-model="hdhiveForm.cookie"
                type="textarea"
                :rows="3"
                placeholder="请输入 HDHive Cookie（示例：token=xxxx）"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingHdhive" @click="handleSaveHdhive">保存</el-button>
              <el-button :loading="testingHdhive" @click="handleTestHdhive">测试连接</el-button>
            </el-form-item>
          </el-form>

          <div
            v-if="hdhiveStatus.checked"
            class="connection-result"
            :class="hdhiveStatus.valid ? 'is-success' : 'is-failed'"
          >
            <div class="result-title">连接检测结果</div>
            <div class="result-message">{{ hdhiveStatus.message }}</div>
          </div>

          <div v-if="hdhiveStatus.valid && hdhiveStatus.user" class="user-info">
            <el-divider />
            <h4>用户信息</h4>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="用户名">
                {{ hdhiveStatus.user.username || hdhiveStatus.user.nickname || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="会员状态">
                <el-tag v-if="hdhiveStatus.user.is_vip" type="warning" size="small">会员</el-tag>
                <el-tag v-else type="info" size="small">非会员</el-tag>
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="TMDB" name="tmdb">
        <el-card class="settings-card">
          <template #header>
            <span>TMDB 配置</span>
          </template>

          <el-form :model="tmdbForm" label-width="120px">
            <el-form-item label="API Key">
              <el-input v-model="tmdbForm.apiKey" placeholder="TMDB API Key" type="password" show-password />
            </el-form-item>
            <el-form-item label="语言">
              <el-input v-model="tmdbForm.language" placeholder="例如: zh-CN" />
            </el-form-item>
            <el-form-item label="地区">
              <el-input v-model="tmdbForm.region" placeholder="例如: CN" />
            </el-form-item>
            <el-form-item label="API 地址">
              <el-input v-model="tmdbForm.baseUrl" placeholder="例如: https://api.themoviedb.org/3" />
            </el-form-item>
            <el-form-item label="图片地址">
              <el-input v-model="tmdbForm.imageBaseUrl" placeholder="例如: https://image.tmdb.org/t/p/w500" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingTmdb" @click="handleSaveTmdb">保存</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="Pansou" name="pansou">
        <el-card class="settings-card">
          <template #header>
            <div class="card-header">
              <span>Pansou 接口配置</span>
              <el-tag
                v-if="pansouHealthStatus === 'healthy'"
                type="success"
                size="small"
              >
                可用
              </el-tag>
              <el-tag
                v-else-if="pansouHealthStatus === 'error' || pansouHealthStatus === 'unhealthy'"
                type="danger"
                size="small"
              >
                不可用
              </el-tag>
            </div>
          </template>

          <el-form :model="pansouForm" label-width="120px">
            <el-form-item label="服务地址">
              <el-input
                v-model="pansouForm.baseUrl"
                placeholder="例如: http://127.0.0.1:8088/"
              />
              <el-text size="small" type="info">
                修改后会立即应用到后端 Pansou 搜索服务
              </el-text>
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                :loading="savingPansou"
                @click="handleSavePansouConfig"
              >
                保存
              </el-button>
              <el-button
                :loading="testingPansou"
                @click="handleTestPansou"
              >
                测试连接
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="订阅任务" name="scheduler">
        <el-card class="settings-card">
          <template #header>
            <span>订阅定时任务配置</span>
          </template>

          <el-form :model="schedulerForm" label-width="120px">
            <el-divider content-position="left">资源查找优先级</el-divider>
            <el-form-item label="来源顺序">
              <div class="priority-list">
                <div
                  v-for="(source, index) in resourcePriority"
                  :key="source"
                  class="priority-item"
                >
                  <div class="priority-item-left">
                    <span class="priority-order">{{ index + 1 }}</span>
                    <span class="priority-name">{{ sourceLabelMap[source] || source }}</span>
                    <el-tag
                      size="small"
                      :type="sourceConfigStatus[source]?.ok ? 'success' : 'warning'"
                    >
                      {{ sourceConfigStatus[source]?.text || '待检查' }}
                    </el-tag>
                  </div>
                  <div class="priority-actions">
                    <el-button size="small" text :disabled="index === 0" @click="movePriority(source, -1)">上移</el-button>
                    <el-button
                      size="small"
                      text
                      :disabled="index === resourcePriority.length - 1"
                      @click="movePriority(source, 1)"
                    >
                      下移
                    </el-button>
                  </div>
                </div>
              </div>
              <div class="priority-tips">
                <el-text size="small" type="info">
                  保存后，订阅资源会按以上顺序依次查找；保存时会校验所选来源的必要配置和连通性。
                </el-text>
              </div>
            </el-form-item>

            <el-divider content-position="left">Nullbr 渠道</el-divider>
            <el-form-item label="启用任务">
              <el-switch v-model="schedulerForm.nullbr.enabled" />
            </el-form-item>
            <el-form-item label="检查间隔(小时)">
              <el-input-number
                v-model="schedulerForm.nullbr.intervalHours"
                :min="1"
                :max="24"
                :disabled="!schedulerForm.nullbr.enabled"
              />
            </el-form-item>
            <el-form-item label="执行时间">
              <el-time-picker
                v-model="schedulerForm.nullbr.runTime"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="选择时间"
                :disabled="!schedulerForm.nullbr.enabled"
              />
            </el-form-item>

            <el-divider content-position="left">Pansou 渠道</el-divider>
            <el-form-item label="启用任务">
              <el-switch v-model="schedulerForm.pansou.enabled" />
            </el-form-item>
            <el-form-item label="检查间隔(小时)">
              <el-input-number
                v-model="schedulerForm.pansou.intervalHours"
                :min="1"
                :max="24"
                :disabled="!schedulerForm.pansou.enabled"
              />
            </el-form-item>
            <el-form-item label="执行时间">
              <el-time-picker
                v-model="schedulerForm.pansou.runTime"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="选择时间"
                :disabled="!schedulerForm.pansou.enabled"
              />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="savingScheduler" @click="handleSaveScheduler">保存</el-button>
              <el-button :loading="runningNullbr" :disabled="runningSubscriptionChannel !== ''" @click="handleRunSubscriptionChannel('nullbr')">立即执行 Nullbr</el-button>
              <el-button :loading="runningPansou" :disabled="runningSubscriptionChannel !== ''" @click="handleRunSubscriptionChannel('pansou')">立即执行 Pansou</el-button>
            </el-form-item>
            <el-form-item v-if="runningSubscriptionChannel">
              <el-alert
                :title="runningTaskMessage || `正在执行 ${runningSubscriptionChannel} 任务`"
                type="info"
                :closable="false"
                show-icon
              />
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="执行日志" name="taskLogs">
        <el-card class="settings-card">
          <template #header>
            <div class="card-header">
              <span>订阅执行日志</span>
              <el-button text type="primary" :loading="loadingSubscriptionLogs" @click="fetchSubscriptionLogs">刷新</el-button>
            </div>
          </template>

          <el-table :data="subscriptionLogs" size="small" v-loading="loadingSubscriptionLogs">
            <el-table-column prop="started_at" label="开始时间" min-width="170" :formatter="formatBeijingTableCell" />
            <el-table-column prop="channel" label="渠道" width="100" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.status === 'success' ? 'success' : row.status === 'partial' ? 'warning' : 'danger'" size="small">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="checked_count" label="检查订阅" width="100" />
            <el-table-column prop="new_resource_count" label="新增资源" width="100" />
            <el-table-column prop="failed_count" label="失败数" width="90" />
            <el-table-column label="失败分组" min-width="240">
              <template #default="{ row }">
                <span>{{ formatFailureGroups(row.failure_groups) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="摘要" min-width="260" />
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="关于" name="about">
        <el-card class="settings-card">
          <template #header>
            <span>关于</span>
          </template>

          <div class="about-info">
            <p><strong>MediaSync115</strong></p>
            <p>版本: 1.0.0</p>
            <p>影视自动化网盘系统</p>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="offlineFolderDialogVisible"
      title="修改默认离线目录"
      width="560px"
      destroy-on-close
    >
      <el-form :model="offlineDefaultFolderForm" label-width="120px">
        <el-form-item label="离线目录">
          <el-tree-select
            v-model="offlineDefaultFolderForm.folderId"
            :data="folderTree"
            :props="folderTreeProps"
            placeholder="选择默认离线下载目录"
            check-strictly
            lazy
            :load="loadFolderChildren"
            :render-after-expand="false"
            clearable
            @change="handleOfflineDefaultFolderChange"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="offlineFolderDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingOfflineFolder" @click="handleSaveOfflineDefaultFolder">
          保存设置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { pan115Api, pansouApi, settingsApi, subscriptionApi } from '@/api'
import { formatBeijingTableCell } from '@/utils/timezone'

const settingsForm = ref({
  cookie: ''
})

const activeSettingsTab = ref('pan115')

const nullbrForm = ref({
  appId: '',
  apiKey: '',
  baseUrl: ''
})

const hdhiveForm = ref({
  cookie: ''
})

const tmdbForm = ref({
  apiKey: '',
  language: 'zh-CN',
  region: 'CN',
  baseUrl: 'https://api.themoviedb.org/3',
  imageBaseUrl: 'https://image.tmdb.org/t/p/w500'
})

const schedulerForm = ref({
  nullbr: {
    enabled: false,
    intervalHours: 24,
    runTime: '03:00'
  },
  pansou: {
    enabled: false,
    intervalHours: 24,
    runTime: '03:30'
  }
})
const sourceLabelMap = {
  nullbr: 'Nullbr',
  hdhive: 'HDHive',
  pansou: 'Pansou',
}
const resourcePriority = ref(['nullbr', 'hdhive', 'pansou'])

const pansouForm = ref({
  baseUrl: ''
})

const saving = ref(false)
const testing = ref(false)
const testingRiskHealth = ref(false)
const savingPansou = ref(false)
const testingPansou = ref(false)
const savingNullbr = ref(false)
const testingNullbr = ref(false)
const savingHdhive = ref(false)
const testingHdhive = ref(false)
const savingTmdb = ref(false)
const savingScheduler = ref(false)
const runningNullbr = ref(false)
const runningPansou = ref(false)
const runningSubscriptionChannel = ref('')
const runningTaskId = ref('')
const runningTaskMessage = ref('')
const pansouHealthStatus = ref('')
const subscriptionLogs = ref([])
const loadingSubscriptionLogs = ref(false)

const cookieInfo = ref({
  configured: false,
  masked_cookie: ''
})

const cookieStatus = reactive({
  valid: false,
  checked: false,
  user_info: null
})

const connectionResult = reactive({
  checked: false,
  success: false,
  message: ''
})

const riskHealth = reactive({
  checked: false,
  status: '',
  summary: '',
  detail: ''
})

const hdhiveStatus = reactive({
  checked: false,
  valid: false,
  message: '',
  user: null
})

const riskHealthTagType = computed(() => {
  if (riskHealth.status === 'healthy') return 'success'
  if (riskHealth.status === 'rate_limited') return 'warning'
  if (riskHealth.status === 'auth_invalid') return 'danger'
  if (riskHealth.status) return 'info'
  return 'info'
})

const riskHealthTagText = computed(() => {
  if (riskHealth.status === 'healthy') return '风控检测: 正常'
  if (riskHealth.status === 'rate_limited') return '风控检测: 临时受限'
  if (riskHealth.status === 'auth_invalid') return '风控检测: 凭证失效'
  if (riskHealth.status) return '风控检测: 异常'
  return '风控检测: 未检测'
})

const riskHealthAlertType = computed(() => {
  if (riskHealth.status === 'healthy') return 'success'
  if (riskHealth.status === 'rate_limited') return 'warning'
  if (riskHealth.status === 'auth_invalid') return 'error'
  return 'info'
})

const sourceConfigStatus = computed(() => {
  const nullbrOk = Boolean(
    String(nullbrForm.value.appId || '').trim() &&
    String(nullbrForm.value.apiKey || '').trim() &&
    String(nullbrForm.value.baseUrl || '').trim()
  )
  const hdhiveOk = Boolean(String(hdhiveForm.value.cookie || '').trim())
  const pansouOk = Boolean(String(pansouForm.value.baseUrl || '').trim())
  return {
    nullbr: { ok: nullbrOk, text: nullbrOk ? '配置完整' : '缺少配置' },
    hdhive: { ok: hdhiveOk, text: hdhiveOk ? '配置完整' : '缺少 Cookie' },
    pansou: { ok: pansouOk, text: pansouOk ? '配置完整' : '缺少地址' },
  }
})

// 默认转存文件夹相关
const defaultFolderForm = ref({
  folderId: '0',
  folderName: '根目录'
})
const savingFolder = ref(false)
const savingOfflineFolder = ref(false)
const offlineFolderDialogVisible = ref(false)
const folderTree = ref([])
const folderTreeProps = {
  label: 'name',
  value: 'id',
  children: 'children',
  isLeaf: (data) => data.isLeaf === true
}

const currentDefaultFolderText = computed(() => {
  const folderId = defaultFolderForm.value.folderId || '0'
  const folderName = defaultFolderForm.value.folderName || ''
  if (folderId === '0') return '根目录'
  return folderName ? `${folderName} (ID: ${folderId})` : `ID: ${folderId}`
})

const offlineDefaultFolderForm = ref({
  folderId: '0',
  folderName: '根目录'
})

const currentOfflineDefaultFolderText = computed(() => {
  const folderId = offlineDefaultFolderForm.value.folderId || '0'
  const folderName = offlineDefaultFolderForm.value.folderName || ''
  if (folderId === '0') return '根目录'
  return folderName ? `${folderName} (ID: ${folderId})` : `ID: ${folderId}`
})

const formatSize = (bytes) => {
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = parseFloat(bytes)
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(2)} ${units[unitIndex]}`
}

const fetchCookieInfo = async () => {
  try {
    const { data } = await pan115Api.getCookieInfo()
    cookieInfo.value = data
  } catch (error) {
    console.error('Failed to fetch cookie info:', error)
  }
}

const checkCookie = async () => {
  try {
    const { data } = await pan115Api.checkCookie()
    cookieStatus.valid = data.valid
    cookieStatus.checked = true
    cookieStatus.user_info = data.user_info
    connectionResult.checked = true
    connectionResult.success = !!data.valid
    connectionResult.message = data.valid
      ? `连接正常：${data.user_info?.user_name || '用户信息已获取'}`
      : `连接异常：${data.message || '请检查Cookie配置'}`
  } catch (error) {
    cookieStatus.valid = false
    cookieStatus.checked = true
    cookieStatus.user_info = null
    connectionResult.checked = true
    connectionResult.success = false
    connectionResult.message = error.response?.data?.detail || '连接检测失败，请检查Cookie配置'
  }
}

const fetchRiskHealth = async (notify = false) => {
  try {
    const { data } = await pan115Api.getRiskHealth()
    riskHealth.checked = true
    riskHealth.status = data.status || ''
    riskHealth.summary = data.summary || ''
    const checks = data.checks || {}
    riskHealth.detail =
      checks.file_list?.message ||
      checks.offline_tasks?.message ||
      checks.cookie?.message ||
      ''
    if (notify) {
      if (data.status === 'healthy') {
        ElMessage.success(data.summary || '115接口状态正常')
      } else {
        ElMessage.warning(data.summary || '115接口存在临时问题')
      }
    }
  } catch (error) {
    riskHealth.checked = true
    riskHealth.status = 'unavailable'
    riskHealth.summary = error.response?.data?.detail || '115状态检测失败'
    riskHealth.detail = ''
    if (notify) {
      ElMessage.error(riskHealth.summary)
    }
  }
}

const handleTestRiskHealth = async () => {
  testingRiskHealth.value = true
  try {
    await fetchRiskHealth(true)
  } finally {
    testingRiskHealth.value = false
  }
}

const handleSaveCookie = async () => {
  if (!settingsForm.value.cookie.trim()) {
    ElMessage.warning('请输入Cookie')
    return
  }

  saving.value = true
  try {
    const { data } = await pan115Api.updateCookie(settingsForm.value.cookie)
    ElMessage.success('Cookie保存成功')
    settingsForm.value.cookie = ''
    await fetchCookieInfo()
    await checkCookie()
    await fetchRiskHealth()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'Cookie保存失败')
  } finally {
    saving.value = false
  }
}

const handleTestConnection = async () => {
  testing.value = true
  try {
    const { data } = await pan115Api.checkCookie()
    if (data.valid) {
      cookieStatus.valid = true
      cookieStatus.checked = true
      cookieStatus.user_info = data.user_info
      connectionResult.checked = true
      connectionResult.success = true
      connectionResult.message = `连接成功：${data.user_info?.user_name || '用户信息已获取'}`
      ElMessage.success(`连接成功: ${data.user_info?.user_name || '用户'}`)
    } else {
      cookieStatus.valid = false
      cookieStatus.checked = true
      cookieStatus.user_info = null
      connectionResult.checked = true
      connectionResult.success = false
      connectionResult.message = `连接失败：${data.message || '请检查Cookie'}`
      ElMessage.error('连接失败: ' + (data.message || '请检查Cookie'))
    }
  } catch (error) {
    cookieStatus.valid = false
    cookieStatus.checked = true
    cookieStatus.user_info = null
    connectionResult.checked = true
    connectionResult.success = false
    connectionResult.message = '连接失败，请检查Cookie配置'
    ElMessage.error('连接失败，请检查Cookie配置')
  } finally {
    testing.value = false
  }
}

const fetchPansouConfig = async () => {
  try {
    const { data } = await pansouApi.getConfig()
    pansouForm.value.baseUrl = data.base_url || ''
    pansouHealthStatus.value = data.health?.status || ''
  } catch (error) {
    console.error('Failed to fetch pansou config:', error)
  }
}

const handleSavePansouConfig = async () => {
  if (!String(pansouForm.value.baseUrl || '').trim()) {
    ElMessage.warning('请输入 Pansou 服务地址')
    return
  }

  savingPansou.value = true
  try {
    const { data } = await pansouApi.updateConfig(pansouForm.value.baseUrl)
    pansouForm.value.baseUrl = data.base_url || pansouForm.value.baseUrl
    pansouHealthStatus.value = data.health?.status || ''
    ElMessage.success('Pansou 配置已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'Pansou 配置保存失败')
  } finally {
    savingPansou.value = false
  }
}

const handleTestPansou = async () => {
  testingPansou.value = true
  try {
    const { data } = await pansouApi.health()
    pansouHealthStatus.value = data.status || ''
    if (data.status === 'healthy') {
      ElMessage.success('Pansou 服务连接成功')
    } else {
      ElMessage.error('Pansou 服务不可用')
    }
  } catch (error) {
    pansouHealthStatus.value = 'error'
    ElMessage.error('Pansou 服务连接失败')
  } finally {
    testingPansou.value = false
  }
}

const handleSaveNullbr = () => {
  if (!String(nullbrForm.value.appId || '').trim()) {
    ElMessage.warning('请输入 Nullbr APP ID')
    return
  }
  if (!String(nullbrForm.value.apiKey || '').trim()) {
    ElMessage.warning('请输入 Nullbr API Key')
    return
  }
  if (!String(nullbrForm.value.baseUrl || '').trim()) {
    ElMessage.warning('请输入 Nullbr Base URL')
    return
  }

  savingNullbr.value = true
  settingsApi.updateRuntime({
    nullbr_app_id: nullbrForm.value.appId,
    nullbr_api_key: nullbrForm.value.apiKey,
    nullbr_base_url: nullbrForm.value.baseUrl
  }).then(() => {
    ElMessage.success('Nullbr 配置已保存')
  }).catch((error) => {
    ElMessage.error(error.response?.data?.detail || 'Nullbr 配置保存失败')
  }).finally(() => {
    savingNullbr.value = false
  })
}

const checkHdhive = async (notify = false) => {
  try {
    const { data } = await settingsApi.checkHdhive()
    hdhiveStatus.checked = true
    hdhiveStatus.valid = !!data.valid
    hdhiveStatus.user = data.user || null
    hdhiveStatus.message = data.valid
      ? `连接成功：${data.user?.username || data.user?.nickname || '用户信息已获取'}`
      : `连接失败：${data.message || '请检查 Cookie'}`

    if (notify) {
      if (data.valid) {
        ElMessage.success(hdhiveStatus.message)
      } else {
        ElMessage.error(hdhiveStatus.message)
      }
    }
  } catch (error) {
    hdhiveStatus.checked = true
    hdhiveStatus.valid = false
    hdhiveStatus.user = null
    hdhiveStatus.message = error.response?.data?.detail || '连接失败，请检查 Cookie 配置'
    if (notify) {
      ElMessage.error(hdhiveStatus.message)
    }
  }
}

const handleSaveHdhive = async () => {
  if (!String(hdhiveForm.value.cookie || '').trim()) {
    ElMessage.warning('请输入 HDHive Cookie')
    return
  }

  savingHdhive.value = true
  try {
    await settingsApi.updateRuntime({
      hdhive_cookie: hdhiveForm.value.cookie
    })
    ElMessage.success('HDHive Cookie 已保存')
    await checkHdhive(false)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'HDHive 配置保存失败')
  } finally {
    savingHdhive.value = false
  }
}

const handleTestHdhive = async () => {
  testingHdhive.value = true
  try {
    await checkHdhive(true)
  } finally {
    testingHdhive.value = false
  }
}

const handleTestNullbr = async () => {
  testingNullbr.value = true
  try {
    const { data } = await settingsApi.checkNullbr()
    if (data.valid) {
      ElMessage.success('Nullbr 凭证有效，资源接口可访问')
    } else {
      const message = String(data.message || 'Nullbr 凭证不可用')
      ElMessage.error(`Nullbr 凭证不可用：${message}`)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'Nullbr 凭证检测失败')
  } finally {
    testingNullbr.value = false
  }
}

const handleSaveTmdb = () => {
  if (!String(tmdbForm.value.apiKey || '').trim()) {
    ElMessage.warning('请输入 TMDB API Key')
    return
  }
  if (!String(tmdbForm.value.language || '').trim()) {
    ElMessage.warning('请输入 TMDB 语言')
    return
  }
  if (!String(tmdbForm.value.region || '').trim()) {
    ElMessage.warning('请输入 TMDB 地区')
    return
  }
  if (!String(tmdbForm.value.baseUrl || '').trim()) {
    ElMessage.warning('请输入 TMDB API 地址')
    return
  }
  if (!String(tmdbForm.value.imageBaseUrl || '').trim()) {
    ElMessage.warning('请输入 TMDB 图片地址')
    return
  }

  savingTmdb.value = true
  settingsApi.updateRuntime({
    tmdb_api_key: tmdbForm.value.apiKey,
    tmdb_language: tmdbForm.value.language,
    tmdb_region: tmdbForm.value.region,
    tmdb_base_url: tmdbForm.value.baseUrl,
    tmdb_image_base_url: tmdbForm.value.imageBaseUrl
  }).then(() => {
    ElMessage.success('TMDB 配置已保存')
  }).catch((error) => {
    ElMessage.error(error.response?.data?.detail || 'TMDB 配置保存失败')
  }).finally(() => {
    savingTmdb.value = false
  })
}

const fetchRuntimeSettings = async () => {
  try {
    const { data } = await settingsApi.getRuntime()
    hdhiveForm.value.cookie = data.hdhive_cookie || ''
    nullbrForm.value.appId = data.nullbr_app_id || ''
    nullbrForm.value.apiKey = data.nullbr_api_key || ''
    nullbrForm.value.baseUrl = data.nullbr_base_url || ''

    tmdbForm.value.apiKey = data.tmdb_api_key || ''
    tmdbForm.value.language = data.tmdb_language || 'zh-CN'
    tmdbForm.value.region = data.tmdb_region || 'CN'
    tmdbForm.value.baseUrl = data.tmdb_base_url || 'https://api.themoviedb.org/3'
    tmdbForm.value.imageBaseUrl = data.tmdb_image_base_url || 'https://image.tmdb.org/t/p/w500'

    if (!pansouForm.value.baseUrl) {
      pansouForm.value.baseUrl = data.pansou_base_url || ''
    }

    schedulerForm.value.nullbr.enabled = !!data.subscription_nullbr_enabled
    schedulerForm.value.nullbr.intervalHours = Number(data.subscription_nullbr_interval_hours || 24)
    schedulerForm.value.nullbr.runTime = data.subscription_nullbr_run_time || '03:00'

    schedulerForm.value.pansou.enabled = !!data.subscription_pansou_enabled
    schedulerForm.value.pansou.intervalHours = Number(data.subscription_pansou_interval_hours || 24)
    schedulerForm.value.pansou.runTime = data.subscription_pansou_run_time || '03:30'

    const priority = Array.isArray(data.subscription_resource_priority)
      ? data.subscription_resource_priority.map(item => String(item || '').trim().toLowerCase())
      : []
    const deduped = []
    for (const source of priority) {
      if (!sourceLabelMap[source]) continue
      if (!deduped.includes(source)) deduped.push(source)
    }
    for (const source of ['nullbr', 'hdhive', 'pansou']) {
      if (!deduped.includes(source)) deduped.push(source)
    }
    resourcePriority.value = deduped
  } catch (error) {
    console.error('Failed to fetch runtime settings:', error)
  }
}

const movePriority = (source, direction) => {
  const current = [...resourcePriority.value]
  const index = current.indexOf(source)
  if (index < 0) return
  const target = index + direction
  if (target < 0 || target >= current.length) return
  const [item] = current.splice(index, 1)
  current.splice(target, 0, item)
  resourcePriority.value = current
}

const handleSaveScheduler = async () => {
  savingScheduler.value = true
  try {
    await settingsApi.updateRuntime({
      subscription_nullbr_enabled: schedulerForm.value.nullbr.enabled,
      subscription_nullbr_interval_hours: Number(schedulerForm.value.nullbr.intervalHours || 24),
      subscription_nullbr_run_time: schedulerForm.value.nullbr.runTime || '03:00',
      subscription_pansou_enabled: schedulerForm.value.pansou.enabled,
      subscription_pansou_interval_hours: Number(schedulerForm.value.pansou.intervalHours || 24),
      subscription_pansou_run_time: schedulerForm.value.pansou.runTime || '03:30',
      subscription_resource_priority: resourcePriority.value
    })
    ElMessage.success('订阅任务与资源优先级配置已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    savingScheduler.value = false
  }
}

const fetchSubscriptionLogs = async () => {
  loadingSubscriptionLogs.value = true
  try {
    const { data } = await subscriptionApi.listLogs({ limit: 5 })
    subscriptionLogs.value = Array.isArray(data) ? data : []
  } catch (error) {
    console.error('Failed to fetch subscription logs:', error)
  } finally {
    loadingSubscriptionLogs.value = false
  }
}

const formatFailureGroups = (groups) => {
  const summary = groups && typeof groups === 'object' ? groups : {}
  const permission = Number(summary.permission || 0)
  const risk = Number(summary.risk || 0)
  const invalidLink = Number(summary.invalid_link || 0)
  const other = Number(summary.other || 0)
  const total = permission + risk + invalidLink + other
  if (total <= 0) return '-'
  return `权限 ${permission} / 风控 ${risk} / 链接失效 ${invalidLink} / 其他 ${other}`
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const pollSubscriptionTask = async (taskId) => {
  const maxChecks = 180
  for (let i = 0; i < maxChecks; i++) {
    const { data } = await subscriptionApi.getRunTask(taskId)
    runningTaskMessage.value = data?.message || ''
    const status = String(data?.status || '')
    if (status === 'success') {
      return { ok: true, task: data }
    }
    if (status === 'failed') {
      return { ok: false, task: data }
    }
    await wait(2000)
  }
  return { ok: false, task: { error: '任务执行超时，请稍后查看日志' } }
}

const handleRunSubscriptionChannel = async (channel) => {
  if (runningSubscriptionChannel.value) return
  runningSubscriptionChannel.value = channel
  runningTaskMessage.value = '任务已提交，等待执行...'
  const loadingRef = channel === 'nullbr' ? runningNullbr : runningPansou
  loadingRef.value = true
  try {
    const { data } = await subscriptionApi.runChannelCheckBackground(channel, true)
    if (data?.already_running) {
      ElMessage.info(`${channel} 已有任务在执行，正在跟踪当前任务进度`)
    }
    runningTaskId.value = data?.task_id || ''
    const taskResult = await pollSubscriptionTask(runningTaskId.value)
    if (taskResult.ok) {
      const message = taskResult.task?.result?.message || taskResult.task?.message || `${channel} 执行完成`
      ElMessage.success(message)
    } else {
      const errorMessage = taskResult.task?.error || taskResult.task?.message || `${channel} 执行失败`
      ElMessage.error(errorMessage)
    }
    await fetchSubscriptionLogs()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || `${channel} 执行失败`)
  } finally {
    loadingRef.value = false
    runningSubscriptionChannel.value = ''
    runningTaskId.value = ''
    runningTaskMessage.value = ''
  }
}

// 获取文件夹列表
const fetchFolders = async (cid = '0') => {
  try {
    const { data } = await pan115Api.getFileList(cid, 0, 50)
    // API 返回 data.data 是数组，文件夹用 cid 字段标识
    const list = data.data || []
    return list
      .filter(item => item.cid) // 只要有 cid 就是文件夹
      .map(item => ({
        id: String(item.cid),
        name: item.n,
        isLeaf: false
      }))
  } catch (error) {
    console.error('Failed to fetch folders:', error)
    return []
  }
}

// 懒加载子文件夹
const loadFolderChildren = async (node, resolve) => {
  // node.level === 0 表示根级别，需要返回根目录
  const cid = node.level === 0 ? '0' : node.data?.id || '0'
  const folders = await fetchFolders(cid)
  
  if (node.level === 0) {
    // 根级别，添加根目录选项
    resolve([
      { id: '0', name: '根目录', isLeaf: false },
      ...folders
    ])
  } else {
    resolve(folders)
  }
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

const handleDefaultFolderChange = (value) => {
  const folderId = value ? String(value) : '0'
  defaultFolderForm.value.folderId = folderId
  defaultFolderForm.value.folderName = findFolderNameById(folderTree.value, folderId)
}

const handleOfflineDefaultFolderChange = (value) => {
  const folderId = value ? String(value) : '0'
  offlineDefaultFolderForm.value.folderId = folderId
  offlineDefaultFolderForm.value.folderName = findFolderNameById(folderTree.value, folderId)
}

const handleOpenOfflineFolderDialog = async () => {
  await fetchOfflineDefaultFolder()
  offlineFolderDialogVisible.value = true
}

// 获取默认转存文件夹设置
const fetchDefaultFolder = async () => {
  try {
    const { data } = await pan115Api.getDefaultFolder()
    defaultFolderForm.value.folderId = data.folder_id || '0'
    defaultFolderForm.value.folderName = data.folder_name || (defaultFolderForm.value.folderId === '0' ? '根目录' : '')
  } catch (error) {
    console.error('Failed to fetch default folder:', error)
  }
}

const fetchOfflineDefaultFolder = async () => {
  try {
    const { data } = await pan115Api.getOfflineDefaultFolder()
    offlineDefaultFolderForm.value.folderId = data.folder_id || '0'
    offlineDefaultFolderForm.value.folderName = data.folder_name || (offlineDefaultFolderForm.value.folderId === '0' ? '根目录' : '')
  } catch (error) {
    console.error('Failed to fetch offline default folder:', error)
  }
}

// 保存默认转存文件夹设置
const handleSaveDefaultFolder = async () => {
  savingFolder.value = true
  try {
    const folderId = defaultFolderForm.value.folderId || '0'
    const folderName = defaultFolderForm.value.folderName || (folderId === '0' ? '根目录' : '')
    await pan115Api.setDefaultFolder(folderId, folderName)
    ElMessage.success('默认保存位置设置成功')
  } catch (error) {
    ElMessage.error('设置失败')
  } finally {
    savingFolder.value = false
  }
}

const handleSaveOfflineDefaultFolder = async () => {
  savingOfflineFolder.value = true
  try {
    const folderId = offlineDefaultFolderForm.value.folderId || '0'
    const folderName = offlineDefaultFolderForm.value.folderName || (folderId === '0' ? '根目录' : '')
    await pan115Api.setOfflineDefaultFolder(folderId, folderName)
    offlineFolderDialogVisible.value = false
    ElMessage.success('默认离线目录设置成功')
  } catch (error) {
    ElMessage.error('设置失败')
  } finally {
    savingOfflineFolder.value = false
  }
}

onMounted(() => {
  fetchRuntimeSettings().then(() => {
    if (String(hdhiveForm.value.cookie || '').trim()) {
      checkHdhive(false)
    }
  })
  fetchCookieInfo()
  checkCookie()
  fetchRiskHealth()
  fetchDefaultFolder()
  fetchOfflineDefaultFolder()
  fetchPansouConfig()
  fetchSubscriptionLogs()
})
</script>

<style lang="scss" scoped>
.settings-page {
  .settings-tabs {
    :deep(.el-tabs__content) {
      padding-top: 14px;
    }
  }

  h2 {
    margin: 0 0 24px;
    color: var(--ms-text-primary);
  }

  .settings-card {
    margin-bottom: 20px;

    .card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;

      .status-tags {
        display: flex;
        gap: 8px;
      }
    }

    .cookie-status {
      .not-configured {
        color: var(--ms-text-muted);
      }
    }

    .cookie-tips {
      margin-top: 8px;
    }

    .user-info {
      h4 {
        margin: 0 0 12px;
        color: var(--ms-text-primary);
      }

      :deep(.el-descriptions__body) {
        background: transparent;
      }

      :deep(.el-descriptions__label.el-descriptions__cell) {
        background: rgba(79, 145, 226, 0.16);
      }

      :deep(.el-descriptions__content.el-descriptions__cell) {
        background: rgba(61, 119, 188, 0.1);
      }
    }

    .connection-result {
      margin-top: 4px;
      border-radius: 10px;
      padding: 10px 14px;
      border: 1px solid transparent;

      .result-title {
        font-size: 12px;
        font-weight: 600;
        margin-bottom: 4px;
      }

      .result-message {
        color: var(--ms-text-primary);
        line-height: 1.4;
      }

      &.is-success {
        background: rgba(43, 175, 117, 0.15);
        border-color: rgba(52, 190, 129, 0.36);

        .result-title {
          color: var(--ms-accent-success);
        }
      }

      &.is-failed {
        background: rgba(230, 100, 120, 0.14);
        border-color: rgba(236, 116, 136, 0.3);

        .result-title {
          color: var(--ms-accent-danger);
        }
      }
    }

    .default-folder-section {
      h4 {
        margin: 0 0 12px;
        color: var(--ms-text-primary);
      }

      .folder-selector {
        display: flex;
        align-items: center;
        gap: 10px;

        .default-folder-select {
          flex: 1 1 520px;
          min-width: 460px;
        }
      }

      .folder-tips {
        margin-top: 8px;
      }

      .current-folder {
        margin-top: 8px;
      }
    }

    .offline-folder-section {
      h4 {
        margin: 0 0 12px;
        color: var(--ms-text-primary);
      }

      .folder-action {
        margin-top: 10px;
      }

      .folder-tips {
        margin-top: 8px;
      }

      .current-folder {
        margin-top: 4px;
      }
    }

    .about-info {
      color: var(--ms-text-secondary);
      line-height: 1.8;

      strong {
        color: var(--ms-text-primary);
        font-size: 16px;
      }
    }

    .priority-list {
      width: 100%;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .priority-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      border: 1px solid rgba(61, 119, 188, 0.22);
      border-radius: 8px;
      padding: 8px 10px;
      background: rgba(61, 119, 188, 0.08);
    }

    .priority-item-left {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .priority-order {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      background: rgba(79, 145, 226, 0.2);
      color: var(--ms-text-primary);
      font-size: 12px;
      font-weight: 600;
    }

    .priority-name {
      color: var(--ms-text-primary);
      font-weight: 600;
    }

    .priority-actions {
      display: flex;
      align-items: center;
      gap: 4px;
    }

    .priority-tips {
      margin-top: 8px;
    }
  }
}

@media (max-width: 900px) {
  .settings-page {
    .settings-card {
      .default-folder-section {
        .folder-selector {
          flex-direction: column;
          align-items: stretch;

          .default-folder-select {
            min-width: 100%;
          }
        }
      }
    }
  }
}
</style>
