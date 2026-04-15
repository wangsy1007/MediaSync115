<template>
  <div class="settings-page">
    <h2>系统设置</h2>

    <el-tabs v-model="activeSettingsTab" class="settings-tabs">
      <el-tab-pane label="账号安全" name="account">
        <el-card class="settings-card">
          <template #header>
            <span>登录账号设置</span>
          </template>

          <el-form :model="accountForm" label-width="120px">
            <el-form-item label="当前用户名">
              <el-input v-model="accountForm.currentUsername" readonly />
            </el-form-item>
            <el-form-item label="新用户名">
              <el-input v-model="accountForm.newUsername" placeholder="留空表示不修改用户名" />
            </el-form-item>
            <el-form-item label="当前密码">
              <el-input
                v-model="accountForm.currentPassword"
                type="password"
                show-password
                placeholder="请输入当前密码"
              />
            </el-form-item>
            <el-form-item label="新密码">
              <el-input
                v-model="accountForm.newPassword"
                type="password"
                show-password
                placeholder="留空表示不修改密码"
              />
            </el-form-item>
            <el-form-item label="确认新密码">
              <el-input
                v-model="accountForm.confirmPassword"
                type="password"
                show-password
                placeholder="再次输入新密码"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingAccount" @click="handleSaveAccount">
                保存账号设置
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

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

          <el-form label-width="120px">
            <el-form-item label="Cookie状态">
              <div class="cookie-status">
                <span v-if="cookieInfo.configured">{{ cookieInfo.masked_cookie }}</span>
                <span v-else class="not-configured">未配置</span>
              </div>
            </el-form-item>
            <el-form-item label="扫码登录">
              <div class="pan115-qr-login">
                <div class="pan115-qr-device">
                  <el-text size="small" type="info">登录设备</el-text>
                  <el-select v-model="pan115QrApp" size="small" style="width: 180px">
                    <el-option
                      v-for="option in pan115QrAppOptions"
                      :key="option.value"
                      :label="option.label"
                      :value="option.value"
                    />
                  </el-select>
                </div>
                <div class="pan115-qr-preview" v-if="pan115QrState.qrUrl">
                  <img :src="pan115QrState.qrUrl" alt="115 Login QR" />
                </div>
                <div class="pan115-qr-placeholder" v-else>
                  <span>点击“生成二维码”开始登录</span>
                </div>
                <div class="pan115-qr-actions">
                  <el-button type="primary" @click="handleStartPan115QrLogin" :loading="startingPan115Qr">
                    生成二维码
                  </el-button>
                  <el-button @click="handleCancelPan115QrLogin" :disabled="!pan115QrState.token" :loading="cancelingPan115Qr">
                    取消扫码
                  </el-button>
                </div>
                <div class="pan115-qr-status">
                  <el-tag :type="pan115QrState.statusType" size="small">{{ pan115QrState.statusText || '未开始扫码登录' }}</el-tag>
                  <el-text v-if="pan115QrState.expiresAt" size="small" type="info">过期时间：{{ pan115QrState.expiresAt }}</el-text>
                </div>
              </div>
              <div class="cookie-tips">
                <el-text size="small" type="info">
                  请使用 115 官方客户端扫码并确认登录，成功后会自动更新系统 Cookie。
                </el-text>
              </div>
            </el-form-item>
            <el-form-item>
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

          <div v-if="cookieStatus.valid && offlineQuotaStatus.checked" class="user-info">
            <el-divider />
            <h4>离线下载配额</h4>
            <el-descriptions v-if="offlineQuotaStatus.valid && offlineQuotaStatus.quota_info" :column="2" border size="small">
              <el-descriptions-item label="总配额">{{ formatQuotaCount(offlineQuotaStatus.quota_info.total_quota) }}</el-descriptions-item>
              <el-descriptions-item label="剩余配额">{{ formatQuotaCount(offlineQuotaStatus.quota_info.remaining_quota) }}</el-descriptions-item>
              <el-descriptions-item label="已用配额">{{ formatQuotaCount(offlineQuotaStatus.quota_info.used_quota) }}</el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag type="success" size="small">可用</el-tag>
              </el-descriptions-item>
            </el-descriptions>
            <el-alert
              v-else
              :title="offlineQuotaStatus.message || '离线下载配额获取失败'"
              type="warning"
              :closable="false"
              show-icon
            />
          </div>

          <div v-if="cookieStatus.valid" class="default-folder-section">
            <el-divider />
            <h4>转存设置</h4>
            <el-form :model="defaultFolderForm" label-width="120px">
              <el-form-item label="默认保存位置">
                <div class="folder-selector">
                  <div class="folder-tag-row">
                    <el-tag v-if="defaultFolderForm.folderId" type="info">
                      {{ defaultFolderForm.folderName || defaultFolderForm.folderId }}
                    </el-tag>
                    <span v-else class="not-configured">未配置</span>
                  </div>
                  <el-button @click="openSettingsFolderPicker('default')">
                    选择目录
                  </el-button>
                  <el-button type="primary" @click="handleSaveDefaultFolder" :loading="savingFolder">
                    保存设置
                  </el-button>
                </div>
              </el-form-item>
            </el-form>
          </div>

          <div v-if="cookieStatus.valid" class="offline-folder-section">
            <el-divider />
            <h4>离线下载设置</h4>
            <el-form label-width="120px">
              <el-form-item label="默认离线目录">
                <div class="folder-selector">
                  <div class="folder-tag-row">
                    <el-tag v-if="offlineDefaultFolderForm.folderId" type="info">
                      {{ offlineDefaultFolderForm.folderName || offlineDefaultFolderForm.folderId }}
                    </el-tag>
                    <span v-else class="not-configured">未配置</span>
                  </div>
                  <el-button @click="openSettingsFolderPicker('offline')">
                    选择目录
                  </el-button>
                  <el-button type="primary" :loading="savingOfflineFolder" @click="handleSaveOfflineDefaultFolder">
                    保存设置
                  </el-button>
                </div>
              </el-form-item>
            </el-form>
          </div>
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
            <el-form-item label="API Key">
              <el-input
                v-model="hdhiveForm.apiKey"
                type="textarea"
                :rows="3"
                placeholder="请输入 HDHive Open API Key（仅 Premium 会员需要）"
              />
            </el-form-item>
            <el-form-item label="Cookie">
              <el-input
                v-model="hdhiveForm.cookie"
                type="textarea"
                :rows="3"
                placeholder="请输入 HDHive Cookie（用于 Cookie 签到）"
              />
              <el-text size="small" type="info" style="margin-top: 4px">
                从浏览器登录 HDHive 后，在开发者工具中复制 Cookie 粘贴到此处
              </el-text>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingHdhive" @click="handleSaveHdhive">保存</el-button>
              <el-button :loading="testingHdhive" @click="handleTestHdhive">测试连接</el-button>
            </el-form-item>
          </el-form>

          <el-divider />
          <h4>自动签到</h4>
          <el-form :model="hdhiveForm" label-width="120px">
            <el-form-item label="启用自动签到">
              <el-switch v-model="hdhiveForm.autoCheckinEnabled" />
            </el-form-item>
            <el-form-item label="签到方式">
              <el-select
                v-model="hdhiveForm.autoCheckinMethod"
                style="width: 220px"
                :disabled="!hdhiveForm.autoCheckinEnabled"
              >
                <el-option label="API Key（仅 Premium）" value="api" />
                <el-option label="Cookie（所有用户）" value="cookie" />
              </el-select>
              <el-text size="small" type="info" style="margin-left: 8px">
                {{ hdhiveForm.autoCheckinMethod === 'cookie' ? '使用浏览器 Cookie 签到，无需 Premium 会员' : '使用 Open API 签到，需要 Premium 会员' }}
              </el-text>
            </el-form-item>
            <el-form-item label="签到模式">
              <el-select
                v-model="hdhiveForm.autoCheckinMode"
                style="width: 220px"
                :disabled="!hdhiveForm.autoCheckinEnabled"
              >
                <el-option label="普通签到" value="normal" />
                <el-option label="赌狗签到" value="gamble" />
              </el-select>
              <el-text size="small" type="info" style="margin-left: 8px">
                赌狗签到会按官网规则随机增减积分
              </el-text>
            </el-form-item>
            <el-form-item label="每日执行时间">
              <el-time-picker
                v-model="hdhiveForm.autoCheckinRunTime"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="选择时间"
                :disabled="!hdhiveForm.autoCheckinEnabled"
              />
              <el-text size="small" type="info" style="margin-left: 8px">
                每天会在该时间自动执行一次所选签到模式
              </el-text>
            </el-form-item>
            <el-form-item label="手动签到">
              <el-button
                type="primary"
                :loading="runningHdhiveCheckin"
                @click="handleRunHdhiveCheckin"
              >
                立即签到
              </el-button>
              <el-text size="small" type="info" style="margin-left: 8px">
                会按当前选择的签到模式立即执行一次
              </el-text>
            </el-form-item>
            <el-form-item v-if="hdhiveCheckinResult.visible">
              <el-alert
                :title="hdhiveCheckinResult.title"
                :type="hdhiveCheckinResult.type"
                :description="hdhiveCheckinResult.message"
                :closable="false"
                show-icon
              />
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
              <el-descriptions-item label="当前积分">
                {{ Number.isFinite(Number(hdhiveStatus.user.points)) ? Number(hdhiveStatus.user.points) : '-' }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="媒体库" name="emby">
        <el-card class="settings-card">
          <template #header>
            <div class="card-header">
              <span>Emby 配置</span>
              <el-tag v-if="embyStatus.checked" :type="embyStatus.valid ? 'success' : 'danger'" size="small">
                {{ embyStatus.valid ? '已连接' : '未连接' }}
              </el-tag>
            </div>
          </template>

          <el-form :model="embyForm" label-width="120px">
            <el-form-item label="Emby URL">
              <el-input v-model="embyForm.url" placeholder="例如: http://127.0.0.1:8096" />
            </el-form-item>
            <el-form-item label="API Key">
              <el-input
                v-model="embyForm.apiKey"
                type="password"
                show-password
                placeholder="请输入 Emby API Key"
              />
            </el-form-item>
            <el-form-item label="定时同步">
              <el-switch v-model="embyForm.syncEnabled" />
            </el-form-item>
            <el-form-item label="同步间隔(小时)">
              <el-input-number
                v-model="embyForm.syncIntervalHours"
                :min="1"
                :max="168"
                :disabled="!embyForm.syncEnabled"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingEmby" @click="handleSaveEmby">保存</el-button>
              <el-button :loading="testingEmby" @click="handleTestEmby">测试连接</el-button>
              <el-button type="warning" :loading="runningEmbySync" @click="handleRunEmbySync">
                立即同步
              </el-button>
            </el-form-item>
          </el-form>

          <div
            v-if="embyStatus.checked"
            class="connection-result"
            :class="embyStatus.valid ? 'is-success' : 'is-failed'"
          >
            <div class="result-title">连接检测结果</div>
            <div class="result-message">{{ embyStatus.message }}</div>
          </div>

          <div v-if="embyStatus.valid && embyStatus.user" class="user-info">
            <el-divider />
            <h4>服务信息</h4>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="服务名">
                {{ embyStatus.user.server_name || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="版本">
                {{ embyStatus.user.version || '-' }}
              </el-descriptions-item>
              </el-descriptions>
          </div>

          <div class="user-info">
            <el-divider />
            <h4>同步状态</h4>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="当前状态">
                <el-tag :type="embySyncStatusTagType" size="small">
                  {{ embySyncStatusText }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="是否已有快照">
                <el-tag :type="embySyncStatus.hasSnapshot ? 'success' : 'info'" size="small">
                  {{ embySyncStatus.hasSnapshot ? '有' : '无' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="最近开始时间">
                {{ formatBeijingTableCell(null, null, embySyncStatus.lastSyncStartedAt) || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="最近完成时间">
                {{ formatBeijingTableCell(null, null, embySyncStatus.lastSyncFinishedAt) || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="最近成功时间">
                {{ formatBeijingTableCell(null, null, embySyncStatus.lastSuccessfulSyncAt) || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="最近耗时">
                {{ embySyncStatus.lastSyncDurationMs ? `${embySyncStatus.lastSyncDurationMs} ms` : '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="电影数">
                {{ embySyncStatus.movieCount }}
              </el-descriptions-item>
              <el-descriptions-item label="剧集数">
                {{ embySyncStatus.tvCount }}
              </el-descriptions-item>
              <el-descriptions-item label="已索引集数">
                {{ embySyncStatus.episodeCount }}
              </el-descriptions-item>
              <el-descriptions-item label="最近触发来源">
                {{ embySyncStatus.lastTrigger || '-' }}
              </el-descriptions-item>
            </el-descriptions>
            <el-alert
              v-if="embySyncStatus.lastSyncError"
              :closable="false"
              type="error"
              show-icon
              style="margin-top: 12px"
              :title="embySyncStatus.lastSyncError"
            />
          </div>
        </el-card>

        <el-card class="settings-card" style="margin-top: 16px">
          <template #header>
            <div class="card-header">
              <span>飞牛影视配置</span>
              <el-tag v-if="feiniuStatus.checked" :type="feiniuStatus.valid ? 'success' : 'danger'" size="small">
                {{ feiniuStatus.valid ? '已连接' : '未连接' }}
              </el-tag>
            </div>
          </template>

          <el-form :model="feiniuForm" label-width="120px">
            <el-form-item label="飞牛 URL">
              <el-input v-model="feiniuForm.url" placeholder="例如: http://192.168.1.100:5666" />
            </el-form-item>
            <el-form-item label="定时同步">
              <el-switch v-model="feiniuForm.syncEnabled" />
            </el-form-item>
            <el-form-item label="同步间隔(小时)">
              <el-input-number
                v-model="feiniuForm.syncIntervalHours"
                :min="1"
                :max="168"
                :disabled="!feiniuForm.syncEnabled"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingFeiniu" @click="handleSaveFeiniu">保存</el-button>
              <el-button :loading="testingFeiniu" @click="handleTestFeiniu">测试连接</el-button>
              <el-button type="success" :loading="loggingInFeiniu" @click="feiniuLoginDialogVisible = true">登录</el-button>
              <el-button type="warning" :loading="runningFeiniuSync" @click="handleRunFeiniuSync">
                立即同步
              </el-button>
            </el-form-item>
          </el-form>

          <div
            v-if="feiniuStatus.checked"
            class="connection-result"
            :class="feiniuStatus.valid ? 'is-success' : 'is-failed'"
          >
            <div class="result-title">连接检测结果</div>
            <div class="result-message">{{ feiniuStatus.message }}</div>
          </div>

          <div v-if="feiniuStatus.valid && feiniuStatus.user" class="user-info">
            <el-divider />
            <h4>服务信息</h4>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="用户名">
                {{ feiniuStatus.user.username || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="语言">
                {{ feiniuStatus.user.lan || '-' }}
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <div class="user-info">
            <el-divider />
            <h4>同步状态</h4>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="当前状态">
                <el-tag :type="feiniuSyncStatusTagType" size="small">
                  {{ feiniuSyncStatusText }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="是否已有快照">
                <el-tag :type="feiniuSyncStatus.hasSnapshot ? 'success' : 'info'" size="small">
                  {{ feiniuSyncStatus.hasSnapshot ? '有' : '无' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="最近开始时间">
                {{ formatBeijingTableCell(null, null, feiniuSyncStatus.lastSyncStartedAt) || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="最近完成时间">
                {{ formatBeijingTableCell(null, null, feiniuSyncStatus.lastSyncFinishedAt) || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="最近成功时间">
                {{ formatBeijingTableCell(null, null, feiniuSyncStatus.lastSuccessfulSyncAt) || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="最近耗时">
                {{ feiniuSyncStatus.lastSyncDurationMs ? `${feiniuSyncStatus.lastSyncDurationMs} ms` : '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="电影数">
                {{ feiniuSyncStatus.movieCount }}
              </el-descriptions-item>
              <el-descriptions-item label="剧集数">
                {{ feiniuSyncStatus.tvCount }}
              </el-descriptions-item>
              <el-descriptions-item label="已索引集数">
                {{ feiniuSyncStatus.episodeCount }}
              </el-descriptions-item>
              <el-descriptions-item label="最近触发来源">
                {{ feiniuSyncStatus.lastTrigger || '-' }}
              </el-descriptions-item>
            </el-descriptions>
            <el-alert
              v-if="feiniuSyncStatus.lastSyncError"
              :closable="false"
              type="error"
              show-icon
              style="margin-top: 12px"
              :title="feiniuSyncStatus.lastSyncError"
            />
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="Telegram" name="tg">
        <el-card class="settings-card">
          <template #header>
            <div class="card-header">
              <span>Telegram 渠道配置</span>
              <el-tag v-if="tgStatus.checked" :type="tgStatus.valid ? 'success' : 'danger'" size="small">
                {{ tgStatus.valid ? '已连接' : '未连接' }}
              </el-tag>
            </div>
          </template>

          <el-alert
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 16px"
          >
            <template #title>
              <span style="font-weight: 600">如何获取 API ID 和 API HASH？</span>
            </template>
            <ol style="margin: 6px 0 0; padding-left: 18px; line-height: 1.8">
              <li>用浏览器打开 <el-link type="primary" href="https://my.telegram.org" target="_blank">my.telegram.org</el-link>，使用你的 Telegram 手机号登录；</li>
              <li>登录后点击 <strong>API development tools</strong>；</li>
              <li>如果是首次使用，需要填写一个应用名称（随意填写即可，如 <em>MyApp</em>），然后提交；</li>
              <li>页面会显示 <strong>App api_id</strong> 和 <strong>App api_hash</strong>，将它们复制填入下方对应输入框即可。</li>
            </ol>
          </el-alert>

          <el-form :model="tgForm" label-width="120px">
            <el-form-item label="API ID">
              <el-input v-model="tgForm.apiId" placeholder="Telegram API ID" />
            </el-form-item>
            <el-form-item label="API HASH">
              <el-input v-model="tgForm.apiHash" placeholder="Telegram API HASH" type="password" show-password />
            </el-form-item>
            <el-form-item label="频道列表">
              <el-select
                v-model="tgForm.channelsList"
                multiple
                filterable
                allow-create
                default-first-option
                :reserve-keyword="false"
                placeholder="输入频道 username 后按回车添加（不带 @）"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="搜索窗口(天)">
              <el-input-number v-model="tgForm.searchDays" :min="1" :max="365" />
            </el-form-item>
            <el-form-item label="每频道消息上限">
              <el-input-number v-model="tgForm.maxMessagesPerChannel" :min="20" :max="2000" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingTg" @click="handleSaveTg">保存</el-button>
              <el-button :loading="testingTg" @click="handleTestTg">测试连接</el-button>
              <el-button :loading="loggingOutTg" :disabled="!tgForm.session" @click="handleTgLogout">退出登录</el-button>
            </el-form-item>
          </el-form>

          <el-divider content-position="left">账号登录</el-divider>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="推荐使用二维码登录 Telegram 账号。"
            style="margin-bottom: 12px;"
          />
          <el-form label-width="120px">
            <el-form-item label="二维码登录">
              <el-button type="primary" :loading="startingTgQr || pollingTgQr" @click="handleStartTgQrLogin">
                {{ tgQrState.active ? '重新生成二维码登录' : '生成二维码登录' }}
              </el-button>
              <el-link
                v-if="tgQrState.url"
                :href="tgQrState.url"
                target="_blank"
                type="primary"
                class="tg-link"
              >
                打开 Telegram 登录链接
              </el-link>
            </el-form-item>
            <el-form-item v-if="tgQrState.url" label="登录链接">
              <el-input :model-value="tgQrState.url" readonly />
            </el-form-item>
            <el-form-item v-if="tgQrState.imageDataUrl" label="登录二维码">
              <div class="tg-qr-preview">
                <img :src="tgQrState.imageDataUrl" alt="Telegram Login QR" />
              </div>
            </el-form-item>
            <el-form-item v-if="tgQrState.statusText" label="二维码状态">
              <el-tag
                :type="tgQrState.statusType"
                effect="plain"
              >
                {{ tgQrState.statusText }}
              </el-tag>
            </el-form-item>
          </el-form>

          <el-form v-if="tgLoginForm.needPassword" :model="tgLoginForm" label-width="120px">
            <el-form-item label="二步密码">
              <el-input v-model="tgLoginForm.password" placeholder="请输入 Telegram 二步验证密码" type="password" show-password />
            </el-form-item>
            <el-form-item>
              <el-button
                type="warning"
                :loading="verifyingTgPassword"
                @click="handleVerifyTgPassword"
              >
                提交二步密码
              </el-button>
            </el-form-item>
          </el-form>

          <div
            v-if="tgStatus.checked"
            class="connection-result"
            :class="tgStatus.valid ? 'is-success' : 'is-failed'"
          >
            <div class="result-title">连接检测结果</div>
            <div class="result-message">{{ tgStatus.message }}</div>
          </div>

          <div v-if="tgStatus.valid && tgStatus.user" class="user-info">
            <el-divider />
            <h4>账号信息</h4>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="用户名">
                {{ tgStatus.user.username || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="手机号">
                {{ tgStatus.user.phone || '-' }}
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <el-divider content-position="left">TG 索引管理</el-divider>
          <el-form :model="tgIndexForm" label-width="180px">
            <el-form-item label="启用索引搜索">
              <el-switch v-model="tgIndexForm.enabled" />
            </el-form-item>
            <el-form-item label="索引无结果时回退实时搜索">
              <el-switch v-model="tgIndexForm.realtimeFallbackEnabled" />
            </el-form-item>
            <el-form-item label="索引每频道返回上限">
              <el-input-number v-model="tgIndexForm.queryLimitPerChannel" :min="20" :max="1000" />
            </el-form-item>
            <el-form-item label="回填批次大小">
              <el-input-number v-model="tgIndexForm.backfillBatchSize" :min="50" :max="2000" />
            </el-form-item>
            <el-form-item label="建议增量间隔(分钟)">
              <el-input-number v-model="tgIndexForm.incrementalIntervalMinutes" :min="5" :max="1440" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingTgIndexConfig" @click="handleSaveTgIndexConfig">
                保存索引配置
              </el-button>
              <el-button :loading="loadingTgIndexStatus" @click="fetchTgIndexStatus">
                刷新索引状态
              </el-button>
              <el-button :loading="runningTgBackfill" @click="handleStartTgBackfill">开始全量回填</el-button>
              <el-button :loading="runningTgIncremental" @click="handleRunTgIncremental">执行一次增量同步</el-button>
              <el-button type="danger" plain :loading="rebuildingTgIndex" @click="handleRebuildTgIndex">
                重建索引
              </el-button>
            </el-form-item>
          </el-form>

          <el-alert
            :closable="false"
            type="info"
            show-icon
            style="margin-bottom: 10px;"
            :title="`当前索引资源总数: ${tgIndexStatus.totalIndexed}`"
          />
          <el-table :data="tgIndexStatus.channels" size="small" border>
            <el-table-column prop="channel" label="频道" min-width="180" />
            <el-table-column prop="indexed_count" label="索引条数" width="100" />
            <el-table-column prop="last_message_id" label="最新消息ID" width="120" />
            <el-table-column prop="backfill_completed" label="全量回填" width="100">
              <template #default="{ row }">
                <el-tag :type="row.backfill_completed ? 'success' : 'warning'" size="small">
                  {{ row.backfill_completed ? '已完成' : '未完成' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="last_synced_at" label="最近同步时间" min-width="170" :formatter="formatBeijingTableCell" />
            <el-table-column prop="last_error" label="最近错误" min-width="220" />
          </el-table>
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

      <el-tab-pane label="代理设置" name="proxy">
        <el-card class="settings-card">
          <template #header>
            <div class="card-header">
              <span>代理配置</span>
              <el-tag v-if="proxyStatus.hasProxy" type="success" size="small">已配置</el-tag>
              <el-tag v-else type="info" size="small">未配置</el-tag>
            </div>
          </template>

          <el-alert
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 16px"
          >
            <template #title>
              代理配置说明
            </template>
            <template #default>
                配置代理后，可用于检测 TMDB、HDHive、Telegram 这些目标地址的连通性。保存后会写入后端运行时配置，并持久化到 data 目录。
            </template>
          </el-alert>

          <el-form :model="proxyForm" label-width="120px">
            <el-form-item label="HTTP 代理">
              <el-input
                v-model="proxyForm.httpProxy"
                placeholder="例如: http://127.0.0.1:7890"
              />
              <el-text size="small" type="info">
                用于 HTTP 协议请求的代理地址
              </el-text>
            </el-form-item>
            <el-form-item label="HTTPS 代理">
              <el-input
                v-model="proxyForm.httpsProxy"
                placeholder="例如: http://127.0.0.1:7890"
              />
              <el-text size="small" type="info">
                用于 HTTPS 协议请求的代理地址
              </el-text>
            </el-form-item>
            <el-form-item label="通用代理">
              <el-input
                v-model="proxyForm.allProxy"
                placeholder="例如: http://127.0.0.1:7890"
              />
              <el-text size="small" type="info">
                当 HTTP/HTTPS 代理未设置时使用此代理
              </el-text>
            </el-form-item>
            <el-form-item label="SOCKS 代理">
              <el-input
                v-model="proxyForm.socksProxy"
                placeholder="例如: socks5://127.0.0.1:1080"
              />
              <el-text size="small" type="info">
                SOCKS5 代理地址，支持用户名密码: socks5://user:pass@host:port
              </el-text>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingProxy" @click="handleSaveProxy">保存代理配置</el-button>
              <el-button :loading="testingProxy" @click="handleTestProxy">检测代理状态</el-button>
            </el-form-item>
          </el-form>

          <el-divider content-position="left">服务连接状态</el-divider>
          <div v-if="healthStatus.checked" class="health-status">
            <el-row :gutter="16">
              <el-col :span="12" v-for="(service, key) in healthStatus.services" :key="key">
                <el-card shadow="never" class="service-card">
                  <div class="service-header">
                    <span class="service-name">{{ serviceNameMap[key] || key }}</span>
                    <el-tag :type="getHealthStatusTagType(service)" size="small">
                      {{ getHealthStatusText(service) }}
                    </el-tag>
                  </div>
                  <div class="service-message">{{ service.message }}</div>
                  <div v-if="service.target" class="service-detail">
                    检测目标：{{ service.target }}
                  </div>
                  <div class="service-detail">
                    已应用代理：{{ getHealthAppliedProxyText(service) }}
                  </div>
                </el-card>
              </el-col>
            </el-row>
          </div>
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
                      :type="sourceConnectionStatus[source]?.checked ? (sourceConnectionStatus[source]?.ok ? 'success' : 'danger') : 'info'"
                    >
                      {{ sourceConnectionStatus[source]?.text || '未检测' }}
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
              <div class="priority-actions-row">
                <el-button size="small" :loading="checkingSourceStatus" @click="refreshSourceConnectionStatus">
                  刷新连接状态
                </el-button>
                <el-button
                  size="small"
                  type="primary"
                  :loading="savingResourcePriority"
                  @click="handleSaveResourcePriority"
                >
                  保存优先级
                </el-button>
              </div>
              <div class="priority-tips">
                <el-text size="small" type="info">
                  保存后，订阅资源会按以上顺序依次查找；这里显示的是各渠道实时连接状态。
                </el-text>
              </div>
            </el-form-item>

            <el-divider content-position="left">资源画质偏好</el-divider>
            <el-alert type="info" :closable="false" style="margin-bottom: 12px">
              设置后，订阅转存和首页探索转存会优先选择匹配的资源。勾选顺序即为优先级（从上到下）。不勾选则不做筛选。
            </el-alert>
            <el-form-item label="分辨率偏好">
              <el-checkbox-group v-model="resourcePrefForm.resolutions" class="preference-inline-group">
                <el-checkbox v-for="r in allResolutions" :key="r" :label="r" :value="r">{{ r }}</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <el-form-item label="格式偏好">
              <el-checkbox-group v-model="resourcePrefForm.formats" class="preference-inline-group">
                <el-checkbox v-for="f in allFormats" :key="f" :label="f" :value="f">{{ f }}</el-checkbox>
              </el-checkbox-group>
            </el-form-item>

            <el-divider content-position="left">HDHive 积分解锁策略</el-divider>
            <el-form-item label="优先免费资源">
              <el-switch v-model="schedulerForm.hdhiveUnlock.preferFree" />
              <el-text size="small" type="info" style="margin-left: 8px">
                转存时优先使用免费资源，避免消耗积分
              </el-text>
            </el-form-item>
            <el-form-item label="启用自动解锁">
              <el-switch v-model="schedulerForm.hdhiveUnlock.enabled" />
            </el-form-item>
            <el-form-item label="单条积分阈值">
              <el-input-number
                v-model="schedulerForm.hdhiveUnlock.maxPointsPerItem"
                :min="1"
                :max="9999"
                :disabled="!schedulerForm.hdhiveUnlock.enabled"
              />
              <el-text size="small" type="info" style="margin-left: 8px">
                仅自动解锁积分小于等于该值的资源（<= n）
              </el-text>
            </el-form-item>
            <el-form-item label="每次任务总预算">
              <el-input-number
                v-model="schedulerForm.hdhiveUnlock.budgetPointsPerRun"
                :min="1"
                :max="99999"
                :disabled="!schedulerForm.hdhiveUnlock.enabled"
              />
              <el-text size="small" type="info" style="margin-left: 8px">
                每次订阅任务最多自动扣除的积分总额
              </el-text>
            </el-form-item>

            <el-divider content-position="left">离线转存</el-divider>
            <el-form-item label="启用离线转存">
              <el-switch v-model="schedulerForm.offlineTransferEnabled" />
              <el-text size="small" type="info" style="margin-left: 8px">
                启用后，订阅转存除 115 分享链接外，还会使用磁力资源进行离线下载（保存到离线下载目录）
              </el-text>
            </el-form-item>

            <el-divider content-position="left">HDHive 渠道</el-divider>
            <el-form-item label="启用任务">
              <el-switch v-model="schedulerForm.hdhive.enabled" />
            </el-form-item>
            <el-form-item label="检查间隔(小时)">
              <el-input-number
                v-model="schedulerForm.hdhive.intervalHours"
                :min="1"
                :max="24"
                :disabled="!schedulerForm.hdhive.enabled"
              />
            </el-form-item>
            <el-form-item label="执行时间">
              <el-time-picker
                v-model="schedulerForm.hdhive.runTime"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="选择时间"
                :disabled="!schedulerForm.hdhive.enabled"
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

            <el-divider content-position="left">Telegram 渠道</el-divider>
            <el-form-item label="启用任务">
              <el-switch v-model="schedulerForm.tg.enabled" />
            </el-form-item>
            <el-form-item label="检查间隔(小时)">
              <el-input-number
                v-model="schedulerForm.tg.intervalHours"
                :min="1"
                :max="24"
                :disabled="!schedulerForm.tg.enabled"
              />
            </el-form-item>
            <el-form-item label="执行时间">
              <el-time-picker
                v-model="schedulerForm.tg.runTime"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="选择时间"
                :disabled="!schedulerForm.tg.enabled"
              />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="savingScheduler" @click="handleSaveScheduler">保存</el-button>
              <el-button type="success" :loading="runningAllChannels" :disabled="runningSubscriptionChannel !== ''" @click="handleRunAllChannels">立即执行全部渠道</el-button>
              <el-button :loading="runningHdhive" :disabled="runningSubscriptionChannel !== '' || runningAllChannels" @click="handleRunSubscriptionChannel('hdhive')">立即执行 HDHive</el-button>
              <el-button :loading="runningPansou" :disabled="runningSubscriptionChannel !== '' || runningAllChannels" @click="handleRunSubscriptionChannel('pansou')">立即执行 Pansou</el-button>
              <el-button :loading="runningTg" :disabled="runningSubscriptionChannel !== '' || runningAllChannels" @click="handleRunSubscriptionChannel('tg')">立即执行 Telegram</el-button>
            </el-form-item>
            <el-form-item v-if="runningSubscriptionChannel || runningAllChannels">
              <el-alert
                :title="runningTaskMessage || (runningAllChannels ? '正在执行全部渠道任务' : `正在执行 ${runningSubscriptionChannel} 任务`)"
                type="info"
                :closable="false"
                show-icon
              />
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="榜单订阅" name="chartSubscription">
        <el-card class="settings-card">
          <template #header>
            <span>影视榜单订阅</span>
          </template>

          <el-alert type="info" :closable="false" style="margin-bottom: 16px">
            启用后，系统将定时抓取所选榜单中的影视内容，并自动创建订阅。新创建的订阅将由"订阅任务"中配置的转存渠道自动完成资源查找与转存。
          </el-alert>

          <el-form label-width="120px">
            <el-form-item label="启用榜单订阅">
              <el-switch v-model="chartSubForm.enabled" />
            </el-form-item>
            <el-form-item label="每榜单条数">
              <el-input-number
                v-model="chartSubForm.limit"
                :min="1"
                :max="50"
                :disabled="!chartSubForm.enabled"
              />
              <el-text size="small" type="info" style="margin-left: 8px">
                每个榜单最多订阅前 N 部影视
              </el-text>
            </el-form-item>
            <el-form-item label="检查间隔(小时)">
              <el-input-number
                v-model="chartSubForm.intervalHours"
                :min="1"
                :max="72"
                :disabled="!chartSubForm.enabled"
              />
            </el-form-item>
            <el-form-item label="执行时间">
              <el-time-picker
                v-model="chartSubForm.runTime"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="选择时间"
                :disabled="!chartSubForm.enabled"
              />
            </el-form-item>

            <el-divider content-position="left">TMDB 榜单</el-divider>
            <el-form-item label="选择榜单">
              <el-checkbox-group v-model="chartSubForm.selectedKeys" :disabled="!chartSubForm.enabled">
                <template v-for="chart in availableCharts.filter(c => c.source === 'tmdb')" :key="`tmdb:${chart.key}`">
                  <el-checkbox :label="chart.title" :value="`tmdb:${chart.key}`" />
                </template>
              </el-checkbox-group>
            </el-form-item>

            <el-divider content-position="left">豆瓣榜单</el-divider>
            <el-form-item label="选择榜单">
              <el-checkbox-group v-model="chartSubForm.selectedKeys" :disabled="!chartSubForm.enabled">
                <template v-for="chart in availableCharts.filter(c => c.source === 'douban')" :key="`douban:${chart.key}`">
                  <el-checkbox :label="chart.title" :value="`douban:${chart.key}`" />
                </template>
              </el-checkbox-group>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="savingChartSub" @click="handleSaveChartSub">保存</el-button>
              <el-button
                type="success"
                :loading="runningChartSub"
                :disabled="!chartSubForm.enabled || chartSubForm.selectedKeys.length === 0"
                @click="handleRunChartSub"
              >
                立即执行
              </el-button>
            </el-form-item>
            <el-form-item v-if="chartSubResult">
              <el-alert
                :title="chartSubResult"
                :type="chartSubResultType"
                :closable="true"
                show-icon
                @close="chartSubResult = ''"
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

      <el-tab-pane label="界面设置" name="ui">
        <el-card class="settings-card">
          <template #header>
            <span>影视详情页 Tab 显示设置</span>
          </template>

          <el-alert type="info" :closable="false" style="margin-bottom: 16px">
            自定义影视详情页中显示的资源标签页，取消勾选后对应标签页将在所有详情页中隐藏。
          </el-alert>

          <el-form label-width="120px">
            <el-divider content-position="left">115网盘</el-divider>
            <el-form-item label="115网盘">
              <el-checkbox v-model="detailTabsForm.pan115">显示整个 115网盘 标签页</el-checkbox>
            </el-form-item>
            <el-form-item label="子标签页" v-if="detailTabsForm.pan115">
              <el-checkbox-group v-model="detailTabsForm.pan115_children">
                <el-checkbox label="pan115_pansou">Pansou</el-checkbox>
                <el-checkbox label="pan115_hdhive">HDHive</el-checkbox>
                <el-checkbox label="pan115_tg">Telegram</el-checkbox>
              </el-checkbox-group>
            </el-form-item>

            <el-divider content-position="left">磁力链接</el-divider>
            <el-form-item label="磁力链接">
              <el-checkbox v-model="detailTabsForm.magnet">显示整个磁力链接标签页</el-checkbox>
            </el-form-item>
            <el-form-item label="子标签页" v-if="detailTabsForm.magnet">
              <el-checkbox-group v-model="detailTabsForm.magnet_children">
                <el-checkbox label="magnet_seedhub">SeedHub</el-checkbox>
                <el-checkbox label="magnet_butailing">不太灵</el-checkbox>
              </el-checkbox-group>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" @click="handleSaveDetailTabs">保存设置</el-button>
              <el-button @click="handleResetDetailTabs">恢复默认</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="TG Bot" name="tgbot">
        <el-card class="settings-card">
          <template #header>
            <div class="card-header">
              <span>Telegram Bot 配置</span>
              <div class="status-tags">
                <el-tag v-if="tgBotStatus.running" type="success" size="small">运行中</el-tag>
                <el-tag v-else-if="tgBotStatus.checked" type="info" size="small">已停止</el-tag>
              </div>
            </div>
          </template>

          <el-alert type="info" :closable="false" style="margin-bottom: 16px">
            <template #title>
              <span>使用 <el-link type="primary" href="https://t.me/BotFather" target="_blank">@BotFather</el-link> 创建机器人并获取 Token。</span>
            </template>
          </el-alert>

          <el-form :model="tgBotForm" label-width="140px">
            <el-form-item label="启用 Bot">
              <el-switch v-model="tgBotForm.enabled" />
            </el-form-item>
            <el-form-item label="Bot Token">
              <el-input v-model="tgBotForm.token" placeholder="输入 Bot Token" type="password" show-password />
            </el-form-item>
            <el-form-item label="授权用户 ID">
              <div>
                <el-tag
                  v-for="uid in tgBotForm.allowedUsers"
                  :key="uid"
                  closable
                  style="margin-right: 8px; margin-bottom: 4px"
                  @close="tgBotForm.allowedUsers = tgBotForm.allowedUsers.filter(u => u !== uid)"
                >{{ uid }}</el-tag>
                <el-input
                  v-model="tgBotNewUserId"
                  placeholder="输入用户 ID 后按回车（留空允许所有人）"
                  style="width: 320px"
                  @keyup.enter="addTgBotAllowedUser"
                />
              </div>
            </el-form-item>
            <el-form-item label="通知 Chat ID">
              <div>
                <el-tag
                  v-for="cid in tgBotForm.notifyChatIds"
                  :key="cid"
                  closable
                  style="margin-right: 8px; margin-bottom: 4px"
                  @close="tgBotForm.notifyChatIds = tgBotForm.notifyChatIds.filter(c => c !== cid)"
                >{{ cid }}</el-tag>
                <el-input
                  v-model="tgBotNewChatId"
                  placeholder="输入 Chat ID 后按回车（在 Bot 中发送 /id 获取）"
                  style="width: 320px"
                  @keyup.enter="addTgBotNotifyChatId"
                />
              </div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingTgBot" @click="handleSaveTgBot">保存配置</el-button>
              <el-button :loading="restartingTgBot" @click="handleRestartTgBot">重启 Bot</el-button>
              <el-button @click="handleCheckTgBotStatus">检测状态</el-button>
            </el-form-item>
          </el-form>

          <el-divider content-position="left">Bot 命令说明</el-divider>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="/s <关键词>">搜索影视</el-descriptions-item>
            <el-descriptions-item label="/subs">查看订阅列表</el-descriptions-item>
            <el-descriptions-item label="/run">触发订阅检查</el-descriptions-item>
            <el-descriptions-item label="/status">系统状态</el-descriptions-item>
            <el-descriptions-item label="/offline">离线下载任务</el-descriptions-item>
            <el-descriptions-item label="/recent">最近下载记录</el-descriptions-item>
            <el-descriptions-item label="/id">获取 Chat ID</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-tab-pane>

      <el-tab-pane v-if="false" label="许可证" name="license">
        <el-card class="settings-card">
          <template #header>
            <span>许可证管理</span>
          </template>

          <el-descriptions :column="1" border size="small" style="margin-bottom: 20px">
            <el-descriptions-item label="当前等级">
              <el-tag :type="licenseStatus.tier === 'pro' ? 'success' : 'info'" size="small">
                {{ licenseStatus.tier === 'pro' ? 'Pro' : '免费版' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="许可证状态">
              {{ licenseStatus.has_license_key ? '已激活' : '未激活' }}
            </el-descriptions-item>
          </el-descriptions>

          <el-form label-width="120px">
            <el-form-item label="许可证密钥">
              <el-input
                v-model="licenseForm.key"
                type="password"
                show-password
                placeholder="输入许可证密钥以激活 Pro 版"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingLicense" @click="handleActivateLicense">
                激活
              </el-button>
              <el-button v-if="licenseStatus.has_license_key" @click="handleDeactivateLicense" :loading="savingLicense">
                取消激活
              </el-button>
            </el-form-item>
          </el-form>

          <el-divider />

          <div>
            <h4 style="margin: 0 0 12px 0">功能可用性</h4>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item v-for="(available, feature) in licenseStatus.features" :key="feature" :label="featureLabel(feature)">
                <el-tag :type="available ? 'success' : 'danger'" size="small">
                  {{ available ? '可用' : '需要 Pro' }}
                </el-tag>
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="关于" name="about">
        <el-card class="settings-card">
          <template #header>
            <span>关于</span>
          </template>

          <div class="about-info">
            <p><strong>MediaSync115</strong></p>
            <p>影视自动化网盘系统</p>
          </div>

          <el-divider />

          <div class="about-update-section">
            <el-descriptions :column="1" border size="small" class="about-version-list">
              <el-descriptions-item label="当前版本">
                {{ currentVersionText }}
              </el-descriptions-item>
              <el-descriptions-item label="镜像标签">
                {{ currentImageTagText }}
              </el-descriptions-item>
              <el-descriptions-item label="构建提交">
                {{ currentGitShaShort }}
              </el-descriptions-item>
              <el-descriptions-item label="构建时间">
                {{ currentBuildTimeText }}
              </el-descriptions-item>
            </el-descriptions>

            <el-form label-width="120px" class="about-update-form">
              <el-form-item label="更新源类型">
                <el-select v-model="updateSourceForm.sourceType" style="width: 100%">
                  <el-option
                    v-for="option in updateSourceOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="镜像仓库">
                <el-input
                  v-model="updateSourceForm.repository"
                  :disabled="!isCustomUpdateSource"
                  placeholder="例如: wangsy1007/mediasync115"
                />
                <div class="update-source-tip">
                  <el-text size="small" type="info">
                    {{ isCustomUpdateSource ? '请输入 DockerHub 仓库名，格式为 namespace/name。' : `当前按官方仓库 ${officialUpdateRepository} 检查更新。` }}
                  </el-text>
                </div>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="savingUpdateSettings" @click="handleSaveUpdateSettings">
                  保存更新源
                </el-button>
                <el-button :loading="checkingUpdates" @click="handleCheckUpdates">
                  检查更新
                </el-button>
              </el-form-item>
            </el-form>

            <el-alert
              v-if="updateCheckState.checked"
              :title="updateCheckState.message || '更新检查完成'"
              :type="updateStatusTagType"
              :closable="false"
              show-icon
            />

            <div v-if="updateCheckState.checked" class="update-result">
              <div class="update-result-header">
                <span class="update-result-title">检查结果</span>
                <el-tag size="small" :type="updateStatusTagType">{{ updateStatusTagText }}</el-tag>
              </div>
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="检查仓库">
                  {{ updateCheckState.repository || effectiveUpdateRepository }}
                </el-descriptions-item>
                <el-descriptions-item label="最新版本">
                  {{ updateCheckState.latestVersion || '-' }}
                </el-descriptions-item>
                <el-descriptions-item label="最新标签">
                  {{ updateCheckState.latestTag || '-' }}
                </el-descriptions-item>
                <el-descriptions-item label="发布时间">
                  {{ latestPublishedAtText }}
                </el-descriptions-item>
                <el-descriptions-item label="检查时间">
                  {{ checkedAtText }}
                </el-descriptions-item>
              </el-descriptions>
              <el-text v-if="!updateCheckState.isOfficialSource" size="small" type="info" class="update-source-tip">
                当前按自定义镜像仓库检查更新，结果可能晚于官方 DockerHub 同步。
              </el-text>
            </div>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="settingsFolderPickerVisible"
      :title="settingsFolderPickerTitle"
      width="520px"
      :close-on-click-modal="false"
    >
      <div class="folder-picker-header">
        <div class="folder-picker-breadcrumb">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item v-for="crumb in settingsFolderPickerBreadcrumbs" :key="crumb.cid">
              <a @click.prevent="navigateSettingsFolderPicker(crumb.cid)">{{ getSettingsFolderDisplayName(crumb) }}</a>
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="folder-picker-toolbar">
          <el-button size="small" :loading="settingsFolderPickerCreating" @click="createSettingsFolderPickerFolder">新建文件夹</el-button>
        </div>
      </div>

      <el-table
        :data="settingsFolderPickerFolders"
        v-loading="settingsFolderPickerLoading"
        size="small"
        max-height="400px"
        @row-click="handleSettingsFolderPickerRowClick"
      >
        <el-table-column label="文件夹名称" min-width="300">
          <template #default="{ row }">
            <span>{{ getSettingsFolderDisplayName(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="cid" label="CID" width="120" show-overflow-tooltip />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" type="primary" text @click.stop="enterSettingsFolderPickerFolder(row)">进入</el-button>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <div class="folder-picker-footer">
          <span>当前目录 CID: {{ settingsFolderPickerCurrentCid }}</span>
          <div>
            <el-button @click="settingsFolderPickerVisible = false">取消</el-button>
            <el-button type="primary" @click="confirmSettingsFolderPicker">选择当前目录</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="feiniuLoginDialogVisible"
      title="飞牛影视登录"
      width="400px"
      destroy-on-close
    >
      <el-form :model="feiniuLoginForm" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="feiniuLoginForm.username" placeholder="请输入飞牛影视用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="feiniuLoginForm.password"
            type="password"
            show-password
            placeholder="请输入飞牛影视密码"
            @keyup.enter="handleFeiniuLogin"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="feiniuLoginDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="loggingInFeiniu" @click="handleFeiniuLogin">
          登录
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, reactive, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { authApi, pan115Api, pansouApi, settingsApi, subscriptionApi, licenseApi, archiveApi } from '@/api'
import { resetAuthSessionCache } from '@/router'
import { useRouter } from 'vue-router'
import { formatBeijingDateTime, formatBeijingTableCell } from '@/utils/timezone'
import { ALL_TABS, saveVisibleTabs } from '@/utils/detailTabs'
import { ALL_RESOLUTIONS, ALL_FORMATS } from '@/utils/resourceTags'

const router = useRouter()
const activeSettingsTab = ref('pan115')
const officialUpdateRepository = 'wangsy1007/mediasync115'
const TMDB_DEFAULT_BASE_URL = 'https://api.themoviedb.org/3'
const TMDB_DEFAULT_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p/w500'
const accountForm = ref({
  currentUsername: 'admin',
  newUsername: '',
  currentPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const hdhiveForm = ref({
  apiKey: '',
  cookie: '',
  autoCheckinEnabled: false,
  autoCheckinMode: 'normal',
  autoCheckinMethod: 'api',
  autoCheckinRunTime: '09:00'
})
const embyForm = ref({
  url: '',
  apiKey: '',
  syncEnabled: false,
  syncIntervalHours: 24
})
const feiniuForm = ref({
  url: '',
  syncEnabled: false,
  syncIntervalHours: 24
})
const feiniuLoginForm = ref({
  username: '',
  password: ''
})
const feiniuLoginDialogVisible = ref(false)

const tgForm = ref({
  apiId: '',
  apiHash: '',
  session: '',
  channelsList: [],
  searchDays: 30,
  maxMessagesPerChannel: 200
})
const tgIndexForm = ref({
  enabled: true,
  realtimeFallbackEnabled: true,
  queryLimitPerChannel: 120,
  backfillBatchSize: 200,
  incrementalIntervalMinutes: 30
})

const tgLoginForm = ref({
  tempSession: '',
  password: '',
  needPassword: false
})
const tgQrState = reactive({
  token: '',
  url: '',
  expiresAt: '',
  imageDataUrl: '',
  statusText: '',
  statusType: 'info',
  active: false
})

const tmdbForm = ref({
  apiKey: '',
  language: 'zh-CN',
  region: 'CN'
})

const schedulerForm = ref({
  offlineTransferEnabled: false,
  hdhive: {
    enabled: false,
    intervalHours: 24,
    runTime: '03:00'
  },
  pansou: {
    enabled: false,
    intervalHours: 24,
    runTime: '03:15'
  },
  tg: {
    enabled: false,
    intervalHours: 24,
    runTime: '03:30'
  },
  hdhiveUnlock: {
    enabled: false,
    maxPointsPerItem: 10,
    budgetPointsPerRun: 30,
    thresholdInclusive: true,
    preferFree: true
  }
})
const allResolutions = ALL_RESOLUTIONS
const allFormats = ALL_FORMATS
const resourcePrefForm = reactive({
  resolutions: [],
  formats: [],
})
const sourceLabelMap = {
  hdhive: 'HDHive',
  pansou: 'Pansou',
  tg: 'Telegram'
}
const resourcePriority = ref(['hdhive', 'pansou', 'tg'])

const pansouForm = ref({
  baseUrl: ''
})

// 代理配置
const proxyForm = ref({
  httpProxy: '',
  httpsProxy: '',
  allProxy: '',
  socksProxy: ''
})
const proxyStatus = ref({
  hasProxy: false
})
const healthStatus = ref({
  checked: false,
  allValid: false,
  validCount: 0,
  totalCount: 0,
  services: {}
})
const serviceNameMap = {
  hdhive: 'HDHive',
  tg: 'Telegram',
  tmdb: 'TMDB'
}
const savingProxy = ref(false)
const testingProxy = ref(false)
const savingAccount = ref(false)

// Detail tabs visibility
const detailTabsForm = reactive({
  pan115: true,
  pan115_children: ['pan115_pansou', 'pan115_hdhive', 'pan115_tg'],
  magnet: true,
  magnet_children: ['magnet_seedhub', 'magnet_butailing'],
})

// TG Bot state
const tgBotForm = ref({
  enabled: false,
  token: '',
  allowedUsers: [],
  notifyChatIds: [],
})
const tgBotNewUserId = ref('')
const tgBotNewChatId = ref('')
const tgBotStatus = ref({ checked: false, running: false })
const savingTgBot = ref(false)
const restartingTgBot = ref(false)

// ── 榜单订阅 ──
const chartSubForm = reactive({
  enabled: false,
  limit: 20,
  intervalHours: 24,
  runTime: '02:00',
  selectedKeys: [],
})
const availableCharts = ref([])
const savingChartSub = ref(false)
const runningChartSub = ref(false)
const chartSubResult = ref('')
const chartSubResultType = ref('success')

// ── 许可证 ──
const licenseForm = reactive({ key: '' })
const savingLicense = ref(false)
const licenseStatus = reactive({ tier: 'free', has_license_key: false, features: {} })
const featureLabelMap = {
  explore: '影视探索',
  subscription: '订阅管理',
  transfer: '资源转存',
  scheduler: '定时任务',
  workflow: '工作流',
  hdhive: 'HDHive',
  telegram: 'Telegram',
  quality_preference: '画质偏好',
  emby_sync: 'Emby 同步',
  tg_bot: 'TG Bot',
}
const featureLabel = (f) => featureLabelMap[f] || f

const testing = ref(false)
const testingRiskHealth = ref(false)
const savingPansou = ref(false)
const testingPansou = ref(false)
const savingHdhive = ref(false)
const testingHdhive = ref(false)
const runningHdhiveCheckin = ref(false)
const savingEmby = ref(false)
const testingEmby = ref(false)
const savingFeiniu = ref(false)
const testingFeiniu = ref(false)
const loggingInFeiniu = ref(false)
const runningEmbySync = ref(false)
const runningFeiniuSync = ref(false)
const savingTg = ref(false)
const testingTg = ref(false)
const verifyingTgPassword = ref(false)
const loggingOutTg = ref(false)
const startingTgQr = ref(false)
const pollingTgQr = ref(false)
const startingPan115Qr = ref(false)
const pollingPan115Qr = ref(false)
const cancelingPan115Qr = ref(false)
const savingTgIndexConfig = ref(false)
const loadingTgIndexStatus = ref(false)
const runningTgBackfill = ref(false)
const runningTgIncremental = ref(false)
const rebuildingTgIndex = ref(false)
const savingTmdb = ref(false)
const savingScheduler = ref(false)
const savingResourcePriority = ref(false)
const runningHdhive = ref(false)
const runningPansou = ref(false)
const runningTg = ref(false)
const runningAllChannels = ref(false)
const runningSubscriptionChannel = ref('')
const runningTaskId = ref('')
const runningTaskMessage = ref('')
const pansouHealthStatus = ref('')
const checkingSourceStatus = ref(false)
const subscriptionLogs = ref([])
const loadingSubscriptionLogs = ref(false)
const savingUpdateSettings = ref(false)
const checkingUpdates = ref(false)

const appInfo = ref({
  currentVersion: '1.0.5',
  currentImageTag: '',
  currentGitSha: '',
  currentBuildTime: '',
  isDockerBuild: false
})
const hdhiveCheckinResult = reactive({
  visible: false,
  type: 'success',
  title: '',
  message: ''
})
const updateSourceForm = ref({
  sourceType: 'official',
  repository: officialUpdateRepository
})
const updateCheckState = reactive({
  checked: false,
  compareStatus: '',
  hasUpdate: null,
  latestVersion: '',
  latestTag: '',
  latestPublishedAt: '',
  checkedAt: '',
  message: '',
  repository: officialUpdateRepository,
  isOfficialSource: true
})
const updateSourceOptions = [
  { label: '官方 DockerHub', value: 'official' },
  { label: '自定义 DockerHub 仓库', value: 'custom_dockerhub' }
]

const cookieInfo = ref({
  configured: false,
  masked_cookie: ''
})

const cookieStatus = reactive({
  valid: false,
  checked: false,
  user_info: null
})
const offlineQuotaStatus = reactive({
  valid: false,
  checked: false,
  quota_info: null,
  message: ''
})
const pan115QrState = reactive({
  token: '',
  qrUrl: '',
  expiresAt: '',
  statusText: '未开始扫码登录',
  statusType: 'info',
  active: false
})
const pan115QrApp = ref('alipaymini')
const pan115QrAppOptions = [
  { label: '支付宝小程序（推荐）', value: 'alipaymini' },
  { label: '网页端', value: 'web' },
  { label: '115浏览器', value: 'desktop' },
  { label: 'iOS未知(bios)', value: 'bios' },
  { label: '安卓未知(bandroid)', value: 'bandroid' },
  { label: '安卓端', value: 'android' },
  { label: '115安卓端', value: '115android' },
  { label: 'iOS端', value: 'ios' },
  { label: '115 iOS端', value: '115ios' },
  { label: 'iPad未知(bipad)', value: 'bipad' },
  { label: 'iPad端', value: 'ipad' },
  { label: '115 iPad端', value: '115ipad' },
  { label: '安卓电视端', value: 'tv' },
  { label: '苹果电视端', value: 'apple_tv' },
  { label: '115管理安卓端(qandriod)', value: 'qandriod' },
  { label: '115管理iOS端(qios)', value: 'qios' },
  { label: '115管理iPad端(qipad)', value: 'qipad' },
  { label: '微信小程序', value: 'wechatmini' },
  { label: '鸿蒙端', value: 'harmony' },
  { label: 'Windows端', value: 'os_windows' },
  { label: 'macOS端', value: 'os_mac' },
  { label: 'Linux端', value: 'os_linux' }
]

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
const tgStatus = reactive({
  checked: false,
  valid: false,
  message: '',
  user: null
})
const tgIndexStatus = reactive({
  totalIndexed: 0,
  channels: [],
  runningJobs: [],
  latestJobs: []
})
const embyStatus = reactive({
  checked: false,
  valid: false,
  message: '',
  user: null
})
const feiniuStatus = reactive({
  checked: false,
  valid: false,
  message: '',
  user: null
})
const feiniuSyncStatus = reactive({
  status: '',
  running: false,
  hasSnapshot: false,
  lastTrigger: '',
  lastSyncStartedAt: '',
  lastSyncFinishedAt: '',
  lastSuccessfulSyncAt: '',
  lastSyncDurationMs: null,
  lastSyncError: '',
  movieCount: 0,
  tvCount: 0,
  episodeCount: 0
})
const embySyncStatus = reactive({
  status: '',
  running: false,
  hasSnapshot: false,
  lastTrigger: '',
  lastSyncStartedAt: '',
  lastSyncFinishedAt: '',
  lastSuccessfulSyncAt: '',
  lastSyncDurationMs: null,
  lastSyncError: '',
  movieCount: 0,
  tvCount: 0,
  episodeCount: 0
})
let embySyncPollTimer = null
let feiniuSyncPollTimer = null
const sourceConnectionStatus = reactive({
  hdhive: { checked: false, ok: false, text: '未检测' },
  pansou: { checked: false, ok: false, text: '未检测' },
  tg: { checked: false, ok: false, text: '未检测' }
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

const embySyncStatusText = computed(() => {
  if (embySyncStatus.running) return '同步中'
  if (embySyncStatus.status === 'success') return '同步成功'
  if (embySyncStatus.status === 'failed') return '同步失败'
  return '未同步'
})

const embySyncStatusTagType = computed(() => {
  if (embySyncStatus.running) return 'warning'
  if (embySyncStatus.status === 'success') return 'success'
  if (embySyncStatus.status === 'failed') return 'danger'
  return 'info'
})

const feiniuSyncStatusText = computed(() => {
  if (feiniuSyncStatus.running) return '同步中'
  if (feiniuSyncStatus.status === 'success') return '同步成功'
  if (feiniuSyncStatus.status === 'failed') return '同步失败'
  return '未同步'
})

const feiniuSyncStatusTagType = computed(() => {
  if (feiniuSyncStatus.running) return 'warning'
  if (feiniuSyncStatus.status === 'success') return 'success'
  if (feiniuSyncStatus.status === 'failed') return 'danger'
  return 'info'
})

const isCustomUpdateSource = computed(() => updateSourceForm.value.sourceType === 'custom_dockerhub')
const effectiveUpdateRepository = computed(() => {
  if (!isCustomUpdateSource.value) return officialUpdateRepository
  return String(updateSourceForm.value.repository || '').trim()
})
const currentVersionText = computed(() => String(appInfo.value.currentVersion || '未知'))
const currentImageTagText = computed(() => String(appInfo.value.currentImageTag || '-'))
const currentGitShaShort = computed(() => {
  const value = String(appInfo.value.currentGitSha || '').trim()
  return value ? value.slice(0, 7) : '-'
})
const currentBuildTimeText = computed(() => formatBeijingDateTime(appInfo.value.currentBuildTime))
const latestPublishedAtText = computed(() => formatBeijingDateTime(updateCheckState.latestPublishedAt))
const checkedAtText = computed(() => formatBeijingDateTime(updateCheckState.checkedAt))
const updateStatusTagType = computed(() => {
  if (updateCheckState.compareStatus === 'update_available') return 'warning'
  if (updateCheckState.compareStatus === 'up_to_date') return 'success'
  if (updateCheckState.compareStatus === 'unknown') return 'info'
  return 'info'
})
const updateStatusTagText = computed(() => {
  if (updateCheckState.compareStatus === 'update_available') return '发现新版本'
  if (updateCheckState.compareStatus === 'up_to_date') return '已是最新'
  if (updateCheckState.compareStatus === 'unknown') return '无法精确比较'
  return '未检查'
})

const refreshSourceConnectionStatus = async () => {
  checkingSourceStatus.value = true
  try {
    const [hdhiveResult, pansouResult, tgResult] = await Promise.allSettled([
      settingsApi.checkHdhive(),
      pansouApi.health(),
      settingsApi.checkTg()
    ])

    if (hdhiveResult.status === 'fulfilled') {
      const payload = hdhiveResult.value?.data || {}
      const ok = !!payload.valid
      sourceConnectionStatus.hdhive.checked = true
      sourceConnectionStatus.hdhive.ok = ok
      sourceConnectionStatus.hdhive.text = ok ? '连接正常' : `连接失败: ${payload.message || '凭证不可用'}`
    } else {
      const message = hdhiveResult.reason?.response?.data?.detail || hdhiveResult.reason?.message || '请求失败'
      sourceConnectionStatus.hdhive.checked = true
      sourceConnectionStatus.hdhive.ok = false
      sourceConnectionStatus.hdhive.text = `连接失败: ${message}`
    }

    if (pansouResult.status === 'fulfilled') {
      const payload = pansouResult.value?.data || {}
      const ok = String(payload.status || '') === 'healthy'
      sourceConnectionStatus.pansou.checked = true
      sourceConnectionStatus.pansou.ok = ok
      sourceConnectionStatus.pansou.text = ok ? '连接正常' : `连接失败: ${payload.status || 'unhealthy'}`
    } else {
      const message = pansouResult.reason?.response?.data?.detail || pansouResult.reason?.message || '请求失败'
      sourceConnectionStatus.pansou.checked = true
      sourceConnectionStatus.pansou.ok = false
      sourceConnectionStatus.pansou.text = `连接失败: ${message}`
    }

    if (tgResult.status === 'fulfilled') {
      const payload = tgResult.value?.data || {}
      const ok = !!payload.valid
      sourceConnectionStatus.tg.checked = true
      sourceConnectionStatus.tg.ok = ok
      sourceConnectionStatus.tg.text = ok ? '连接正常' : `连接失败: ${payload.message || '凭证不可用'}`
    } else {
      const message = tgResult.reason?.response?.data?.detail || tgResult.reason?.message || '请求失败'
      sourceConnectionStatus.tg.checked = true
      sourceConnectionStatus.tg.ok = false
      sourceConnectionStatus.tg.text = `连接失败: ${message}`
    }
  } finally {
    checkingSourceStatus.value = false
  }
}

// 默认转存文件夹相关
const defaultFolderForm = ref({
  folderId: '0',
  folderName: '根目录'
})
const savingFolder = ref(false)
const savingOfflineFolder = ref(false)
const settingsFolderPickerVisible = ref(false)
const settingsFolderPickerTarget = ref('default')
const settingsFolderPickerFolders = ref([])
const settingsFolderPickerLoading = ref(false)
const settingsFolderPickerCreating = ref(false)
const settingsFolderPickerCurrentCid = ref('0')
const settingsFolderPickerHistory = ref([])

const offlineDefaultFolderForm = ref({
  folderId: '0',
  folderName: '根目录'
})

const settingsFolderPickerTitle = computed(() => settingsFolderPickerTarget.value === 'offline' ? '选择默认离线目录' : '选择默认保存位置')

const settingsFolderPickerBreadcrumbs = computed(() => {
  const breadcrumbs = [{ cid: '0', name: '根目录' }]
  for (const item of settingsFolderPickerHistory.value) {
    if (item?.cid && item.cid !== '0') {
      breadcrumbs.push(item)
    }
  }
  return breadcrumbs
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

const formatQuotaCount = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const count = Number(value)
  if (!Number.isFinite(count)) return String(value)
  return `${Math.trunc(count)} 个`
}

const resetOfflineQuotaStatus = () => {
  offlineQuotaStatus.valid = false
  offlineQuotaStatus.checked = false
  offlineQuotaStatus.quota_info = null
  offlineQuotaStatus.message = ''
}

const fetchOfflineQuota = async () => {
  try {
    const { data } = await pan115Api.getOfflineQuota()
    offlineQuotaStatus.valid = !!data.valid
    offlineQuotaStatus.checked = true
    offlineQuotaStatus.quota_info = data.quota_info || null
    offlineQuotaStatus.message = data.message || ''
  } catch (error) {
    offlineQuotaStatus.valid = false
    offlineQuotaStatus.checked = true
    offlineQuotaStatus.quota_info = null
    offlineQuotaStatus.message = error.response?.data?.detail || '离线下载配额获取失败'
  }
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
    if (data.valid) {
      await fetchOfflineQuota()
    } else {
      resetOfflineQuotaStatus()
    }
  } catch (error) {
    cookieStatus.valid = false
    cookieStatus.checked = true
    cookieStatus.user_info = null
    resetOfflineQuotaStatus()
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

const stopPan115QrPolling = () => {
  pan115QrState.active = false
  pollingPan115Qr.value = false
}

const pollPan115QrStatus = async (token) => {
  const normalizedToken = String(token || '').trim()
  if (!normalizedToken) return
  pollingPan115Qr.value = true
  while (pan115QrState.active && pan115QrState.token === normalizedToken) {
    try {
      const { data } = await pan115Api.checkQrLogin(normalizedToken)
      pan115QrState.expiresAt = data.expires_at || pan115QrState.expiresAt
      if (data.authorized) {
        stopPan115QrPolling()
        pan115QrState.token = ''
        pan115QrState.qrUrl = ''
        pan115QrState.statusType = 'success'
        pan115QrState.statusText = data.message || '扫码登录成功'
        await fetchCookieInfo()
        await checkCookie()
        await fetchRiskHealth()
        ElMessage.success('115 扫码登录成功')
        break
      }

      if (!data.pending) {
        stopPan115QrPolling()
        pan115QrState.token = ''
        pan115QrState.qrUrl = ''
        pan115QrState.statusType = data.status === 'expired' ? 'warning' : 'info'
        pan115QrState.statusText = data.message || '二维码会话已结束'
        break
      }

      pan115QrState.statusType = data.status === 'scanned' ? 'warning' : 'info'
      pan115QrState.statusText = data.message || '等待扫码确认'
    } catch (error) {
      stopPan115QrPolling()
      pan115QrState.statusType = 'danger'
      pan115QrState.statusText = error.response?.data?.detail || '二维码登录状态检测失败'
      ElMessage.error(pan115QrState.statusText)
      break
    }
    await wait(2000)
  }
  pollingPan115Qr.value = false
}

const handleStartPan115QrLogin = async () => {
  startingPan115Qr.value = true
  try {
    if (pan115QrState.token) {
      try {
        await pan115Api.cancelQrLogin(pan115QrState.token)
      } catch {
        // noop
      }
    }
    stopPan115QrPolling()
    const { data } = await pan115Api.startQrLogin(pan115QrApp.value)
    pan115QrState.token = data.token || ''
    pan115QrState.qrUrl = data.qr_image_url || data.qr_url || ''
    pan115QrState.expiresAt = data.expires_at || ''
    pan115QrState.statusType = 'info'
    pan115QrState.statusText = '二维码已生成，等待扫码确认'
    pan115QrState.active = true
    ElMessage.success('115 登录二维码已生成')
    pollPan115QrStatus(pan115QrState.token)
  } catch (error) {
    pan115QrState.statusType = 'danger'
    pan115QrState.statusText = error.response?.data?.detail || '二维码登录启动失败'
    ElMessage.error(pan115QrState.statusText)
  } finally {
    startingPan115Qr.value = false
  }
}

const handleCancelPan115QrLogin = async () => {
  const token = String(pan115QrState.token || '').trim()
  if (!token) return
  cancelingPan115Qr.value = true
  try {
    stopPan115QrPolling()
    await pan115Api.cancelQrLogin(token)
    pan115QrState.token = ''
    pan115QrState.qrUrl = ''
    pan115QrState.expiresAt = ''
    pan115QrState.statusType = 'info'
    pan115QrState.statusText = '已取消扫码登录'
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '取消扫码会话失败')
  } finally {
    cancelingPan115Qr.value = false
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
      await fetchOfflineQuota()
      connectionResult.checked = true
      connectionResult.success = true
      connectionResult.message = `连接成功：${data.user_info?.user_name || '用户信息已获取'}`
      ElMessage.success(`连接成功: ${data.user_info?.user_name || '用户'}`)
    } else {
      cookieStatus.valid = false
      cookieStatus.checked = true
      cookieStatus.user_info = null
      resetOfflineQuotaStatus()
      connectionResult.checked = true
      connectionResult.success = false
      connectionResult.message = `连接失败：${data.message || '请检查Cookie'}`
      ElMessage.error('连接失败: ' + (data.message || '请检查Cookie'))
    }
  } catch (error) {
    cookieStatus.valid = false
    cookieStatus.checked = true
    cookieStatus.user_info = null
    resetOfflineQuotaStatus()
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
  } catch (error) {
    console.error('Failed to fetch pansou config:', error)
  }
}

// 代理相关方法
const fetchProxyStatus = async () => {
  try {
    const { data } = await settingsApi.getProxy()
    proxyStatus.value.hasProxy = data.has_proxy || false
    proxyForm.value.httpProxy = data.http_proxy || ''
    proxyForm.value.httpsProxy = data.https_proxy || ''
    proxyForm.value.allProxy = data.all_proxy || ''
    proxyForm.value.socksProxy = data.socks_proxy || ''
  } catch (error) {
    console.error('Failed to fetch proxy status:', error)
  }
}

const fetchHealthStatus = async () => {
  try {
    const { data } = await settingsApi.checkAllHealth()
    healthStatus.value = {
      checked: true,
      allValid: data.all_valid || false,
      validCount: data.valid_count || 0,
      totalCount: data.total_count || 0,
      services: data.services || {}
    }
  } catch (error) {
    console.error('Failed to fetch health status:', error)
  }
}

const getHealthStatusTagType = (service) => {
  const status = String(service?.status || '').trim().toLowerCase()
  if (status === 'ok') {
    return 'success'
  }
  if (status === 'not_configured') {
    return 'info'
  }
  return 'danger'
}

const getHealthStatusText = (service) => {
  const status = String(service?.status || '').trim().toLowerCase()
  if (status === 'ok') {
    return '正常'
  }
  if (status === 'not_configured') {
    return '未配置'
  }
  return '异常'
}

const getHealthAppliedProxyText = (service) => {
  const appliedProxy = String(service?.applied_proxy || '').trim()
  if (!appliedProxy) {
    return '未命中代理'
  }
  return appliedProxy
}

const handleSaveProxy = async () => {
  savingProxy.value = true
  try {
    await settingsApi.updateRuntime({
      http_proxy: proxyForm.value.httpProxy || null,
      https_proxy: proxyForm.value.httpsProxy || null,
      all_proxy: proxyForm.value.allProxy || null,
      socks_proxy: proxyForm.value.socksProxy || null
    })
    ElMessage.success('代理配置已保存并生效')
    await fetchProxyStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '代理配置保存失败')
  } finally {
    savingProxy.value = false
  }
}

const handleTestProxy = async () => {
  testingProxy.value = true
  try {
    await fetchHealthStatus()
    const validCount = healthStatus.value.validCount
    const totalCount = healthStatus.value.totalCount
    const notConfiguredCount = Object.values(healthStatus.value.services || {}).filter(
      service => String(service?.status || '').trim().toLowerCase() === 'not_configured'
    ).length
    if (totalCount > 0 && validCount === totalCount) {
      ElMessage.success(`已配置服务连接正常 (${validCount}/${totalCount})，${notConfiguredCount} 项未配置`)
    } else if (totalCount === 0) {
      ElMessage.warning(`暂无已配置的可检测服务，${notConfiguredCount} 项未配置`)
    } else {
      ElMessage.warning(`部分服务连接异常 (${validCount}/${totalCount} 正常)，${notConfiguredCount} 项未配置`)
    }
  } catch (error) {
    ElMessage.error('服务状态检测失败')
  } finally {
    testingProxy.value = false
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

const checkHdhive = async (notify = false) => {
  try {
    const { data } = await settingsApi.checkHdhive()
    hdhiveStatus.checked = true
    hdhiveStatus.valid = !!data.valid
    hdhiveStatus.user = data.user || null
    hdhiveStatus.message = data.valid
      ? String(data.message || `连接成功：${data.user?.username || data.user?.nickname || 'API Key 有效'}`)
      : `连接失败：${data.message || '请检查 API Key'}`

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
    hdhiveStatus.message = error.response?.data?.detail || '连接失败，请检查 API Key 配置'
    if (notify) {
      ElMessage.error(hdhiveStatus.message)
    }
  }
}

const handleSaveHdhive = async () => {
  if (hdhiveForm.value.autoCheckinEnabled && !String(hdhiveForm.value.autoCheckinRunTime || '').trim()) {
    ElMessage.warning('请选择 HDHive 自动签到执行时间')
    return
  }

  savingHdhive.value = true
  try {
    await settingsApi.updateRuntime({
      hdhive_api_key: hdhiveForm.value.apiKey,
      hdhive_cookie: hdhiveForm.value.cookie,
      hdhive_auto_checkin_enabled: hdhiveForm.value.autoCheckinEnabled,
      hdhive_auto_checkin_mode: hdhiveForm.value.autoCheckinMode || 'normal',
      hdhive_auto_checkin_method: hdhiveForm.value.autoCheckinMethod || 'api',
      hdhive_auto_checkin_run_time: hdhiveForm.value.autoCheckinRunTime || '09:00'
    })
    await fetchRuntimeSettings()
    await refreshSourceConnectionStatus()
    ElMessage.success('HDHive 配置与自动签到已保存')
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

const handleRunHdhiveCheckin = async () => {
  const method = hdhiveForm.value.autoCheckinMethod || 'api'
  if (method === 'api' && !String(hdhiveForm.value.apiKey || '').trim()) {
    ElMessage.warning('请先填写 HDHive API Key')
    return
  }

  runningHdhiveCheckin.value = true
  try {
    const { data } = await settingsApi.runHdhiveCheckin({
      mode: hdhiveForm.value.autoCheckinMode || 'normal',
      method,
      api_key: hdhiveForm.value.apiKey
    })
    if (method === 'api') await checkHdhive(false)
    const modeLabel = hdhiveForm.value.autoCheckinMode === 'gamble' ? '赌狗签到' : '普通签到'
    const methodLabel = method === 'cookie' ? '（Cookie）' : '（API）'
    if (data?.status === 'already_checked_in') {
      hdhiveCheckinResult.visible = true
      hdhiveCheckinResult.type = 'warning'
      hdhiveCheckinResult.title = `${modeLabel}${methodLabel}今日已签到`
      hdhiveCheckinResult.message = data?.message || '今天已经签到过了，无需重复签到'
      ElMessage.warning(hdhiveCheckinResult.message)
      return
    }
    hdhiveCheckinResult.visible = true
    hdhiveCheckinResult.type = 'info'
    hdhiveCheckinResult.title = `${modeLabel}${methodLabel}已完成`
    hdhiveCheckinResult.message = data?.message || '签到成功'
    ElMessage.info(data?.message || `${modeLabel}${methodLabel}已完成`)
  } catch (error) {
    const modeLabel = hdhiveForm.value.autoCheckinMode === 'gamble' ? '赌狗签到' : '普通签到'
    const methodLabel = method === 'cookie' ? 'Cookie' : 'API'
    const reason = String(error.response?.data?.detail || error.message || '未知原因').trim()
    hdhiveCheckinResult.visible = true
    hdhiveCheckinResult.type = 'error'
    hdhiveCheckinResult.title = `${modeLabel}失败`
    hdhiveCheckinResult.message = `签到方式：${methodLabel}。失败原因：${reason}`
  } finally {
    runningHdhiveCheckin.value = false
  }
}

const checkEmby = async (notify = false) => {
  try {
    const customUrl = String(embyForm.value.url || '').trim()
    const customKey = String(embyForm.value.apiKey || '').trim()
    const { data } = await settingsApi.checkEmby(
      customUrl && customKey
        ? { emby_url: customUrl, emby_api_key: customKey }
        : undefined
    )
    embyStatus.checked = true
    embyStatus.valid = !!data.valid
    embyStatus.user = data.user || null
    embyStatus.message = data.valid
      ? `连接成功：${data.user?.server_name || 'Emby 服务可用'}`
      : `连接失败：${data.message || '请检查 URL 和 API Key'}`
    if (notify) {
      if (data.valid) ElMessage.success(embyStatus.message)
      else ElMessage.error(embyStatus.message)
    }
  } catch (error) {
    embyStatus.checked = true
    embyStatus.valid = false
    embyStatus.user = null
    embyStatus.message = error.response?.data?.detail || error.message || 'Emby 连接检测失败'
    if (notify) ElMessage.error(embyStatus.message)
  }
}

const checkFeiniu = async (notify = false) => {
  try {
    const customUrl = String(feiniuForm.value.url || '').trim()
    const { data } = await settingsApi.checkFeiniu(
      customUrl
        ? { feiniu_url: customUrl }
        : undefined
    )
    feiniuStatus.checked = true
    feiniuStatus.valid = !!data.valid
    feiniuStatus.user = data.user || null
    feiniuStatus.message = data.valid
      ? `连接成功：${data.user?.server || '飞牛影视服务可用'}`
      : `连接失败：${data.message || '请检查 URL 或重新登录飞牛'}`
    if (notify) {
      if (data.valid) ElMessage.success(feiniuStatus.message)
      else ElMessage.error(feiniuStatus.message)
    }
  } catch (error) {
    feiniuStatus.checked = true
    feiniuStatus.valid = false
    feiniuStatus.user = null
    feiniuStatus.message = error.response?.data?.detail || error.message || '飞牛影视连接检测失败'
    if (notify) ElMessage.error(feiniuStatus.message)
  }
}

const handleSaveFeiniu = async () => {
  if (!String(feiniuForm.value.url || '').trim()) {
    ElMessage.warning('请输入飞牛影视 URL')
    return
  }

  savingFeiniu.value = true
  try {
    await settingsApi.updateRuntime({
      feiniu_url: feiniuForm.value.url,
      feiniu_sync_enabled: feiniuForm.value.syncEnabled,
      feiniu_sync_interval_hours: feiniuForm.value.syncIntervalHours
    })
    await fetchRuntimeSettings()
    ElMessage.success('飞牛影视配置已保存')
    await checkFeiniu(false)
    await fetchFeiniuSyncStatus(false)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '飞牛影视配置保存失败')
  } finally {
    savingFeiniu.value = false
  }
}

const handleTestFeiniu = async () => {
  if (!String(feiniuForm.value.url || '').trim()) {
    ElMessage.warning('请输入飞牛影视 URL')
    return
  }
  testingFeiniu.value = true
  try {
    await checkFeiniu(true)
  } finally {
    testingFeiniu.value = false
  }
}

const handleFeiniuLogin = async () => {
  if (!String(feiniuLoginForm.value.username || '').trim()) {
    ElMessage.warning('请输入飞牛影视用户名')
    return
  }
  if (!String(feiniuLoginForm.value.password || '').trim()) {
    ElMessage.warning('请输入飞牛影视密码')
    return
  }
  loggingInFeiniu.value = true
  try {
    const { data } = await settingsApi.feiniuLogin(
      feiniuLoginForm.value.username,
      feiniuLoginForm.value.password,
      feiniuForm.value.url
    )
    if (data.success) {
      ElMessage.success('飞牛影视登录成功')
      feiniuLoginDialogVisible.value = false
      feiniuLoginForm.value.username = ''
      feiniuLoginForm.value.password = ''
      await checkFeiniu(false)
      await fetchFeiniuSyncStatus(false)
    } else {
      ElMessage.error(data.message || '飞牛影视登录失败')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '飞牛影视登录失败')
  } finally {
    loggingInFeiniu.value = false
  }
}

const applyFeiniuSyncStatus = (data = {}) => {
  feiniuSyncStatus.status = String(data.status || '')
  feiniuSyncStatus.running = !!data.running
  feiniuSyncStatus.hasSnapshot = !!data.has_snapshot
  feiniuSyncStatus.lastTrigger = String(data.last_trigger || '')
  feiniuSyncStatus.lastSyncStartedAt = data.last_sync_started_at || ''
  feiniuSyncStatus.lastSyncFinishedAt = data.last_sync_finished_at || ''
  feiniuSyncStatus.lastSuccessfulSyncAt = data.last_successful_sync_at || ''
  feiniuSyncStatus.lastSyncDurationMs = Number.isFinite(Number(data.last_sync_duration_ms))
    ? Number(data.last_sync_duration_ms)
    : null
  feiniuSyncStatus.lastSyncError = String(data.last_sync_error || '')
  feiniuSyncStatus.movieCount = Number(data.movie_count || 0)
  feiniuSyncStatus.tvCount = Number(data.tv_count || 0)
  feiniuSyncStatus.episodeCount = Number(data.episode_count || 0)
}

const stopFeiniuSyncPolling = () => {
  if (feiniuSyncPollTimer) {
    clearInterval(feiniuSyncPollTimer)
    feiniuSyncPollTimer = null
  }
}

const startFeiniuSyncPolling = () => {
  if (feiniuSyncPollTimer) return
  feiniuSyncPollTimer = window.setInterval(async () => {
    await fetchFeiniuSyncStatus(false)
    if (!feiniuSyncStatus.running) {
      stopFeiniuSyncPolling()
      runningFeiniuSync.value = false
    }
  }, 5000)
}

const fetchFeiniuSyncStatus = async (notifyOnError = false) => {
  try {
    const { data } = await settingsApi.getFeiniuSyncStatus()
    applyFeiniuSyncStatus(data || {})
    runningFeiniuSync.value = feiniuSyncStatus.running
    if (feiniuSyncStatus.running) startFeiniuSyncPolling()
    else stopFeiniuSyncPolling()
  } catch (error) {
    if (notifyOnError) {
      ElMessage.error(error.response?.data?.detail || error.message || '获取飞牛同步状态失败')
    }
  }
}

const handleRunFeiniuSync = async () => {
  runningFeiniuSync.value = true
  try {
    const { data } = await settingsApi.runFeiniuSync()
    applyFeiniuSyncStatus(data?.status || {})
    if (data?.started === false) {
      ElMessage.info(data.message || '飞牛同步任务已在运行')
    } else {
      ElMessage.success(data?.message || '飞牛同步任务已启动')
    }
    startFeiniuSyncPolling()
  } catch (error) {
    runningFeiniuSync.value = false
    ElMessage.error(error.response?.data?.detail || '启动飞牛同步失败')
  }
}

const applyEmbySyncStatus = (data = {}) => {
  embySyncStatus.status = String(data.status || '')
  embySyncStatus.running = !!data.running
  embySyncStatus.hasSnapshot = !!data.has_snapshot
  embySyncStatus.lastTrigger = String(data.last_trigger || '')
  embySyncStatus.lastSyncStartedAt = data.last_sync_started_at || ''
  embySyncStatus.lastSyncFinishedAt = data.last_sync_finished_at || ''
  embySyncStatus.lastSuccessfulSyncAt = data.last_successful_sync_at || ''
  embySyncStatus.lastSyncDurationMs = Number.isFinite(Number(data.last_sync_duration_ms))
    ? Number(data.last_sync_duration_ms)
    : null
  embySyncStatus.lastSyncError = String(data.last_sync_error || '')
  embySyncStatus.movieCount = Number(data.movie_count || 0)
  embySyncStatus.tvCount = Number(data.tv_count || 0)
  embySyncStatus.episodeCount = Number(data.episode_count || 0)
}

const stopEmbySyncPolling = () => {
  if (embySyncPollTimer) {
    clearInterval(embySyncPollTimer)
    embySyncPollTimer = null
  }
}

const startEmbySyncPolling = () => {
  if (embySyncPollTimer) return
  embySyncPollTimer = window.setInterval(async () => {
    await fetchEmbySyncStatus(false)
    if (!embySyncStatus.running) {
      stopEmbySyncPolling()
      runningEmbySync.value = false
    }
  }, 5000)
}

const fetchEmbySyncStatus = async (notifyOnError = false) => {
  try {
    const { data } = await settingsApi.getEmbySyncStatus()
    applyEmbySyncStatus(data || {})
    runningEmbySync.value = embySyncStatus.running
    if (embySyncStatus.running) startEmbySyncPolling()
    else stopEmbySyncPolling()
  } catch (error) {
    if (notifyOnError) {
      ElMessage.error(error.response?.data?.detail || error.message || '获取 Emby 同步状态失败')
    }
  }
}

const handleSaveEmby = async () => {
  if (!String(embyForm.value.url || '').trim()) {
    ElMessage.warning('请输入 Emby URL')
    return
  }
  if (!String(embyForm.value.apiKey || '').trim()) {
    ElMessage.warning('请输入 Emby API Key')
    return
  }

  savingEmby.value = true
  try {
    await settingsApi.updateRuntime({
      emby_url: embyForm.value.url,
      emby_api_key: embyForm.value.apiKey,
      emby_sync_enabled: embyForm.value.syncEnabled,
      emby_sync_interval_hours: Number(embyForm.value.syncIntervalHours || 24)
    })
    await fetchRuntimeSettings()
    await fetchEmbySyncStatus(false)
    ElMessage.success('Emby 配置已保存')
    await checkEmby(false)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'Emby 配置保存失败')
  } finally {
    savingEmby.value = false
  }
}

const handleTestEmby = async () => {
  if (!String(embyForm.value.url || '').trim()) {
    ElMessage.warning('请输入 Emby URL')
    return
  }
  if (!String(embyForm.value.apiKey || '').trim()) {
    ElMessage.warning('请输入 Emby API Key')
    return
  }
  testingEmby.value = true
  try {
    await checkEmby(true)
  } finally {
    testingEmby.value = false
  }
}

const handleRunEmbySync = async () => {
  runningEmbySync.value = true
  try {
    const { data } = await settingsApi.runEmbySync()
    applyEmbySyncStatus(data?.status || {})
    if (data?.started) {
      ElMessage.success(data?.message || 'Emby 同步任务已启动')
    } else {
      ElMessage.info(data?.message || 'Emby 同步任务已在运行')
    }
    startEmbySyncPolling()
  } catch (error) {
    runningEmbySync.value = false
    ElMessage.error(error.response?.data?.detail || error.message || '启动 Emby 同步失败')
  }
}

const checkTg = async (notify = false) => {
  try {
    const { data } = await settingsApi.checkTg()
    tgStatus.checked = true
    tgStatus.valid = !!data.valid
    tgStatus.user = data.user || null
    tgStatus.message = data.valid ? (data.message || 'Telegram 连接成功') : (data.message || 'Telegram 未登录')
    if (notify) {
      if (data.valid) ElMessage.success(tgStatus.message)
      else ElMessage.error(tgStatus.message)
    }
  } catch (error) {
    tgStatus.checked = true
    tgStatus.valid = false
    tgStatus.user = null
    tgStatus.message = error.response?.data?.detail || 'Telegram 连接检测失败'
    if (notify) ElMessage.error(tgStatus.message)
  }
}

const parseChannelsList = () => {
  return (tgForm.value.channelsList || []).map(item => String(item || '').trim().replace(/^@/, '')).filter(Boolean)
}

const handleSaveTg = async () => {
  if (!String(tgForm.value.apiId || '').trim()) {
    ElMessage.warning('请输入 Telegram API ID')
    return
  }
  if (!String(tgForm.value.apiHash || '').trim()) {
    ElMessage.warning('请输入 Telegram API HASH')
    return
  }
  const channels = parseChannelsList()
  if (!channels.length) {
    ElMessage.warning('请至少配置一个频道')
    return
  }

  savingTg.value = true
  try {
    await settingsApi.updateRuntime({
      tg_api_id: tgForm.value.apiId,
      tg_api_hash: tgForm.value.apiHash,
      tg_phone: '',
      tg_channel_usernames: channels,
      tg_search_days: Number(tgForm.value.searchDays || 30),
      tg_max_messages_per_channel: Number(tgForm.value.maxMessagesPerChannel || 200),
      tg_session: tgForm.value.session || ''
    })
    await fetchRuntimeSettings()
    await refreshSourceConnectionStatus()
    ElMessage.success('Telegram 配置已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'Telegram 配置保存失败')
  } finally {
    savingTg.value = false
  }
}

const handleTestTg = async () => {
  testingTg.value = true
  try {
    await checkTg(true)
  } finally {
    testingTg.value = false
  }
}

const handleVerifyTgPassword = async () => {
  if (!tgLoginForm.value.needPassword) return
  if (!String(tgLoginForm.value.password || '').trim()) {
    ElMessage.warning('请输入二步验证密码')
    return
  }
  verifyingTgPassword.value = true
  try {
    const { data } = await settingsApi.tgVerifyPassword({
      password: tgLoginForm.value.password,
      session: tgLoginForm.value.tempSession
    })
    tgLoginForm.value.needPassword = false
    tgForm.value.session = data.session || ''
    await checkTg(false)
    ElMessage.success('Telegram 二步验证成功')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '二步验证失败')
  } finally {
    verifyingTgPassword.value = false
  }
}

const stopTgQrPolling = () => {
  tgQrState.active = false
  pollingTgQr.value = false
}

const ensureTgLoginBaseConfig = async () => {
  if (!String(tgForm.value.apiId || '').trim()) {
    ElMessage.warning('请先填写 Telegram API ID')
    return false
  }
  if (!String(tgForm.value.apiHash || '').trim()) {
    ElMessage.warning('请先填写 Telegram API HASH')
    return false
  }
  await settingsApi.updateRuntime({
    tg_api_id: tgForm.value.apiId,
    tg_api_hash: tgForm.value.apiHash,
    tg_phone: ''
  })
  return true
}

const pollTgQrStatus = async (token) => {
  pollingTgQr.value = true
  tgQrState.statusText = '等待扫码确认'
  tgQrState.statusType = 'info'
  while (tgQrState.active && tgQrState.token === token) {
    try {
      const { data } = await settingsApi.tgCheckQrLogin(token)
      if (data.authorized) {
        tgForm.value.session = data.session || ''
        stopTgQrPolling()
        tgQrState.token = ''
        tgQrState.url = ''
        tgQrState.expiresAt = ''
        tgQrState.imageDataUrl = ''
        tgQrState.statusText = '已授权，登录成功'
        tgQrState.statusType = 'success'
        await checkTg(false)
        await refreshSourceConnectionStatus()
        ElMessage.success('Telegram 二维码登录成功')
        break
      }
      if (data.need_password) {
        tgLoginForm.value.needPassword = true
        tgLoginForm.value.tempSession = data.session || ''
        stopTgQrPolling()
        tgQrState.statusText = '需要二步验证密码'
        tgQrState.statusType = 'warning'
        ElMessage.info('账号开启了二步验证，请输入密码')
        break
      }
      if (!data.pending) {
        stopTgQrPolling()
        tgQrState.statusText = data.message || '二维码状态未知，请重试'
        tgQrState.statusType = 'warning'
        break
      }
      tgQrState.statusText = data.message || '等待扫码确认'
      tgQrState.statusType = 'info'
    } catch (error) {
      stopTgQrPolling()
      tgQrState.statusText = error.response?.data?.detail || '二维码状态检测失败'
      tgQrState.statusType = 'danger'
      ElMessage.error(error.response?.data?.detail || '二维码登录状态检测失败')
      break
    }
    await wait(2000)
  }
  pollingTgQr.value = false
}

const handleStartTgQrLogin = async () => {
  startingTgQr.value = true
  try {
    const ok = await ensureTgLoginBaseConfig()
    if (!ok) return
    const { data } = await settingsApi.tgStartQrLogin()
    tgQrState.token = data.token || ''
    tgQrState.url = data.url || ''
    tgQrState.expiresAt = data.expires_at || ''
    tgQrState.imageDataUrl = data.qr_image_data_url || data.qr_image_url || ''
    tgQrState.statusText = '二维码已生成，等待扫码确认'
    tgQrState.statusType = 'info'
    tgQrState.active = true
    ElMessage.success('二维码登录链接已生成，请在 Telegram 中确认登录')
    pollTgQrStatus(tgQrState.token)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '二维码登录启动失败')
  } finally {
    startingTgQr.value = false
  }
}

const handleTgLogout = async () => {
  loggingOutTg.value = true
  try {
    stopTgQrPolling()
    await settingsApi.tgLogout()
    tgForm.value.session = ''
    tgLoginForm.value = {
      tempSession: '',
      password: '',
      needPassword: false
    }
    tgQrState.token = ''
    tgQrState.url = ''
    tgQrState.expiresAt = ''
    tgQrState.imageDataUrl = ''
    tgQrState.statusText = ''
    tgQrState.statusType = 'info'
    await checkTg(false)
    await refreshSourceConnectionStatus()
    ElMessage.success('Telegram 已退出登录')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'Telegram 退出失败')
  } finally {
    loggingOutTg.value = false
  }
}

const fetchTgIndexStatus = async () => {
  loadingTgIndexStatus.value = true
  try {
    const { data } = await settingsApi.getTgIndexStatus()
    const status = data.status || {}
    const index = status.index || {}
    tgIndexStatus.totalIndexed = Number(index.total_indexed || 0)
    tgIndexStatus.channels = Array.isArray(index.channels) ? index.channels : []
    tgIndexStatus.runningJobs = Array.isArray(status.running_jobs) ? status.running_jobs : []
    tgIndexStatus.latestJobs = Array.isArray(status.latest_jobs) ? status.latest_jobs : []
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '获取 TG 索引状态失败')
  } finally {
    loadingTgIndexStatus.value = false
  }
}

const handleSaveTgIndexConfig = async () => {
  savingTgIndexConfig.value = true
  try {
    await settingsApi.updateRuntime({
      tg_index_enabled: tgIndexForm.value.enabled,
      tg_index_realtime_fallback_enabled: tgIndexForm.value.realtimeFallbackEnabled,
      tg_index_query_limit_per_channel: Number(tgIndexForm.value.queryLimitPerChannel || 120),
      tg_backfill_batch_size: Number(tgIndexForm.value.backfillBatchSize || 200),
      tg_incremental_interval_minutes: Number(tgIndexForm.value.incrementalIntervalMinutes || 30)
    })
    ElMessage.success('TG 索引配置已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'TG 索引配置保存失败')
  } finally {
    savingTgIndexConfig.value = false
  }
}

const pollTgIndexJob = async (jobId) => {
  const normalized = String(jobId || '').trim()
  if (!normalized) return
  for (let i = 0; i < 600; i++) {
    try {
      const { data } = await settingsApi.getTgIndexJob(normalized)
      const job = data.job || {}
      if (String(job.status || '') !== 'running') {
        await fetchTgIndexStatus()
        if (job.status === 'success') {
          ElMessage.success(job.message || 'TG 索引任务执行成功')
        } else if (job.status === 'partial') {
          ElMessage.warning(job.message || 'TG 索引任务部分成功')
        } else if (job.status === 'failed') {
          ElMessage.error(job.message || 'TG 索引任务失败')
        }
        return
      }
    } catch (error) {
      ElMessage.error(error.response?.data?.detail || '查询 TG 索引任务状态失败')
      return
    }
    await wait(2000)
  }
  ElMessage.warning('TG 索引任务仍在运行，请稍后刷新状态')
}

const handleStartTgBackfill = async () => {
  runningTgBackfill.value = true
  try {
    const { data } = await settingsApi.startTgIndexBackfill(false)
    const jobId = data.job?.job_id || ''
    ElMessage.success('TG 全量回填任务已启动')
    await fetchTgIndexStatus()
    if (jobId) {
      await pollTgIndexJob(jobId)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '启动 TG 全量回填失败')
  } finally {
    runningTgBackfill.value = false
  }
}

const handleRunTgIncremental = async () => {
  runningTgIncremental.value = true
  try {
    const { data } = await settingsApi.runTgIndexIncremental()
    const jobId = data.job?.job_id || ''
    ElMessage.success('TG 增量同步任务已启动')
    await fetchTgIndexStatus()
    if (jobId) {
      await pollTgIndexJob(jobId)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '启动 TG 增量同步失败')
  } finally {
    runningTgIncremental.value = false
  }
}

const handleRebuildTgIndex = async () => {
  rebuildingTgIndex.value = true
  try {
    const { data } = await settingsApi.rebuildTgIndex()
    const jobId = data.job?.job_id || ''
    ElMessage.success('TG 索引重建任务已启动')
    await fetchTgIndexStatus()
    if (jobId) {
      await pollTgIndexJob(jobId)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '启动 TG 索引重建失败')
  } finally {
    rebuildingTgIndex.value = false
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

  savingTmdb.value = true
  settingsApi.updateRuntime({
    tmdb_api_key: tmdbForm.value.apiKey,
    tmdb_language: tmdbForm.value.language,
    tmdb_region: tmdbForm.value.region,
    tmdb_base_url: TMDB_DEFAULT_BASE_URL,
    tmdb_image_base_url: TMDB_DEFAULT_IMAGE_BASE_URL
  }).then(() => {
    ElMessage.success('TMDB 配置已保存')
  }).catch((error) => {
    ElMessage.error(error.response?.data?.detail || 'TMDB 配置保存失败')
  }).finally(() => {
    savingTmdb.value = false
  })
}

const fetchAuthSession = async () => {
  try {
    const { data } = await authApi.getSession()
    if (data?.authenticated && data?.username) {
      accountForm.value.currentUsername = data.username
      if (!String(accountForm.value.newUsername || '').trim()) {
        accountForm.value.newUsername = data.username
      }
    }
  } catch (error) {
    console.error('Failed to fetch auth session:', error)
  }
}

// ── 榜单订阅相关 ──
const loadAvailableCharts = async () => {
  try {
    const { data } = await settingsApi.getAvailableCharts()
    availableCharts.value = data.charts || []
  } catch {}
}

const loadChartSubSettings = (settings) => {
  chartSubForm.enabled = !!settings.chart_subscription_enabled
  chartSubForm.limit = settings.chart_subscription_limit || 20
  chartSubForm.intervalHours = settings.chart_subscription_interval_hours || 24
  chartSubForm.runTime = settings.chart_subscription_run_time || '02:00'
  const sources = settings.chart_subscription_sources || []
  chartSubForm.selectedKeys = sources.map(s => `${s.source}:${s.key}`)
}

const handleSaveChartSub = async () => {
  savingChartSub.value = true
  try {
    const sources = chartSubForm.selectedKeys.map(k => {
      const [source, key] = k.split(':', 2)
      return { source, key }
    })
    await settingsApi.updateRuntime({
      chart_subscription_enabled: chartSubForm.enabled,
      chart_subscription_sources: sources,
      chart_subscription_limit: chartSubForm.limit,
      chart_subscription_interval_hours: chartSubForm.intervalHours,
      chart_subscription_run_time: chartSubForm.runTime,
    })
    ElMessage.success('榜单订阅设置已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    savingChartSub.value = false
  }
}

const handleRunChartSub = async () => {
  runningChartSub.value = true
  chartSubResult.value = ''
  try {
    // 先保存再执行
    const sources = chartSubForm.selectedKeys.map(k => {
      const [source, key] = k.split(':', 2)
      return { source, key }
    })
    await settingsApi.updateRuntime({
      chart_subscription_enabled: true,
      chart_subscription_sources: sources,
      chart_subscription_limit: chartSubForm.limit,
      chart_subscription_interval_hours: chartSubForm.intervalHours,
      chart_subscription_run_time: chartSubForm.runTime,
    })
    const { data } = await settingsApi.runChartSubscription()
    chartSubResult.value = data.message || '执行完成'
    chartSubResultType.value = 'success'
  } catch (error) {
    chartSubResult.value = error.response?.data?.detail || '执行失败'
    chartSubResultType.value = 'error'
  } finally {
    runningChartSub.value = false
  }
}

// ── 许可证相关 ──
const loadLicense = async () => {
  try {
    const { data } = await licenseApi.getStatus()
    Object.assign(licenseStatus, data)
  } catch {}
}
const handleActivateLicense = async () => {
  savingLicense.value = true
  try {
    const { data } = await licenseApi.activate(licenseForm.key)
    Object.assign(licenseStatus, { tier: data.tier, has_license_key: data.has_license_key, features: data.features })
    ElMessage.success(data.tier === 'pro' ? 'Pro 许可证已激活' : '许可证已保存')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '激活失败')
  } finally {
    savingLicense.value = false
  }
}
const handleDeactivateLicense = async () => {
  savingLicense.value = true
  try {
    const { data } = await licenseApi.activate('')
    Object.assign(licenseStatus, { tier: data.tier, has_license_key: data.has_license_key, features: data.features })
    licenseForm.key = ''
    ElMessage.success('许可证已取消激活')
  } catch {
    ElMessage.error('操作失败')
  } finally {
    savingLicense.value = false
  }
}

const handleSaveAccount = async () => {
  const currentUsername = String(accountForm.value.currentUsername || '').trim()
  const username = String(accountForm.value.newUsername || '').trim() || currentUsername
  const currentPassword = String(accountForm.value.currentPassword || '')
  const newPassword = String(accountForm.value.newPassword || '')
  const confirmPassword = String(accountForm.value.confirmPassword || '')

  if (!currentUsername) {
    ElMessage.warning('当前用户名不能为空')
    return
  }
  if (!username) {
    ElMessage.warning('请输入新用户名')
    return
  }
  if (!currentPassword) {
    ElMessage.warning('请输入当前密码')
    return
  }
  if (newPassword && newPassword.length < 6) {
    ElMessage.warning('新密码长度不能少于 6 位')
    return
  }
  if (newPassword !== confirmPassword) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }

  savingAccount.value = true
  try {
    await authApi.changeCredentials({
      username,
      current_password: currentPassword,
      ...(newPassword ? { new_password: newPassword } : {})
    })
    await authApi.logout().catch(() => {})
    resetAuthSessionCache()
    accountForm.value.currentUsername = username
    accountForm.value.newUsername = username
    accountForm.value.currentPassword = ''
    accountForm.value.newPassword = ''
    accountForm.value.confirmPassword = ''
    ElMessage.success('账号设置已更新，请重新登录')
    await router.replace('/login')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '账号设置保存失败')
  } finally {
    savingAccount.value = false
  }
}

const fetchAppInfo = async () => {
  try {
    const { data } = await settingsApi.getAppInfo()
    appInfo.value.currentVersion = data.current_version || 'unknown'
    appInfo.value.currentImageTag = data.current_image_tag || ''
    appInfo.value.currentGitSha = data.current_git_sha || ''
    appInfo.value.currentBuildTime = data.current_build_time || ''
    appInfo.value.isDockerBuild = !!data.is_docker_build
    updateSourceForm.value.sourceType = data.update_source_type || 'official'
    updateSourceForm.value.repository = data.update_repository || officialUpdateRepository
  } catch (error) {
    console.error('Failed to fetch app info:', error)
  }
}

// ── TG Bot handlers ──
const addTgBotAllowedUser = () => {
  const val = String(tgBotNewUserId.value || '').trim()
  if (!val) return
  const uid = Number(val)
  if (isNaN(uid)) { ElMessage.warning('请输入数字 ID'); return }
  if (!tgBotForm.value.allowedUsers.includes(uid)) {
    tgBotForm.value.allowedUsers.push(uid)
  }
  tgBotNewUserId.value = ''
}
const addTgBotNotifyChatId = () => {
  const val = String(tgBotNewChatId.value || '').trim()
  if (!val) return
  const cid = Number(val)
  if (isNaN(cid)) { ElMessage.warning('请输入数字 ID'); return }
  if (!tgBotForm.value.notifyChatIds.includes(cid)) {
    tgBotForm.value.notifyChatIds.push(cid)
  }
  tgBotNewChatId.value = ''
}
const handleSaveTgBot = async () => {
  savingTgBot.value = true
  try {
    await settingsApi.updateRuntime({
      tg_bot_enabled: tgBotForm.value.enabled,
      tg_bot_token: tgBotForm.value.token,
      tg_bot_allowed_users: tgBotForm.value.allowedUsers,
      tg_bot_notify_chat_ids: tgBotForm.value.notifyChatIds,
    })
    ElMessage.success('TG Bot 配置已保存')
    // Auto restart if enabled
    if (tgBotForm.value.enabled && tgBotForm.value.token) {
      await handleRestartTgBot()
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'TG Bot 配置保存失败')
  } finally {
    savingTgBot.value = false
  }
}
const handleRestartTgBot = async () => {
  restartingTgBot.value = true
  try {
    const { data } = await settingsApi.restartTgBot()
    tgBotStatus.value = { checked: true, running: data.running }
    ElMessage.success(data.running ? 'TG Bot 已启动' : 'TG Bot 未启动（请检查配置）')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'TG Bot 重启失败')
  } finally {
    restartingTgBot.value = false
  }
}
const handleCheckTgBotStatus = async () => {
  try {
    const { data } = await settingsApi.getTgBotStatus()
    tgBotStatus.value = { checked: true, running: data.running }
    ElMessage.info(data.running ? 'TG Bot 运行中' : 'TG Bot 未运行')
  } catch (error) {
    ElMessage.error('检测失败')
  }
}

// Detail tabs visibility handlers
const handleSaveDetailTabs = async () => {
  const keys = new Set()
  if (detailTabsForm.pan115) {
    keys.add('pan115')
    detailTabsForm.pan115_children.forEach(k => keys.add(k))
  }
  if (detailTabsForm.magnet) {
    keys.add('magnet')
    detailTabsForm.magnet_children.forEach(k => keys.add(k))
  }
  try {
    await saveVisibleTabs(keys)
    ElMessage.success('详情页标签设置已保存，刷新详情页后生效')
  } catch {
    ElMessage.error('保存失败')
  }
}

const handleResetDetailTabs = async () => {
  detailTabsForm.pan115 = true
  detailTabsForm.pan115_children = ['pan115_pansou', 'pan115_hdhive', 'pan115_tg']
  detailTabsForm.magnet = true
  detailTabsForm.magnet_children = ['magnet_seedhub', 'magnet_butailing']
  try {
    await saveVisibleTabs(new Set(ALL_TABS.map(t => t.key)))
    ElMessage.success('已恢复默认设置，刷新详情页后生效')
  } catch {
    ElMessage.error('重置失败')
  }
}

const fetchRuntimeSettings = async () => {
  try {
    const { data } = await settingsApi.getRuntime()
    accountForm.value.currentUsername = data.auth_username || 'admin'
    if (!String(accountForm.value.newUsername || '').trim()) {
      accountForm.value.newUsername = data.auth_username || 'admin'
    }
    hdhiveForm.value.apiKey = data.hdhive_api_key || ''
    hdhiveForm.value.cookie = data.hdhive_cookie || ''
    hdhiveForm.value.autoCheckinEnabled = !!data.hdhive_auto_checkin_enabled
    hdhiveForm.value.autoCheckinMode = data.hdhive_auto_checkin_mode || 'normal'
    hdhiveForm.value.autoCheckinMethod = data.hdhive_auto_checkin_method || 'api'
    hdhiveForm.value.autoCheckinRunTime = data.hdhive_auto_checkin_run_time || '09:00'
    tgForm.value.apiId = data.tg_api_id || ''
    tgForm.value.apiHash = data.tg_api_hash || ''
    tgForm.value.session = data.tg_session || ''
    tgForm.value.searchDays = Number(data.tg_search_days || 30)
    tgForm.value.maxMessagesPerChannel = Number(data.tg_max_messages_per_channel || 200)
    tgForm.value.channelsList = Array.isArray(data.tg_channel_usernames) ? data.tg_channel_usernames : []
    tgIndexForm.value.enabled = data.tg_index_enabled !== false
    tgIndexForm.value.realtimeFallbackEnabled = data.tg_index_realtime_fallback_enabled !== false
    tgIndexForm.value.queryLimitPerChannel = Number(data.tg_index_query_limit_per_channel || 120)
    tgIndexForm.value.backfillBatchSize = Number(data.tg_backfill_batch_size || 200)
    tgIndexForm.value.incrementalIntervalMinutes = Number(data.tg_incremental_interval_minutes || 30)

    tmdbForm.value.apiKey = data.tmdb_api_key || ''
    tmdbForm.value.language = data.tmdb_language || 'zh-CN'
    tmdbForm.value.region = data.tmdb_region || 'CN'
    proxyForm.value.httpProxy = data.http_proxy || ''
    proxyForm.value.httpsProxy = data.https_proxy || ''
    proxyForm.value.allProxy = data.all_proxy || ''
    proxyForm.value.socksProxy = data.socks_proxy || ''
    embyForm.value.url = data.emby_url || ''
    embyForm.value.apiKey = data.emby_api_key || ''
    embyForm.value.syncEnabled = !!data.emby_sync_enabled
    embyForm.value.syncIntervalHours = Number(data.emby_sync_interval_hours || 24)
    feiniuForm.value.url = data.feiniu_url || ''
    feiniuForm.value.syncEnabled = !!data.feiniu_sync_enabled
    feiniuForm.value.syncIntervalHours = Number(data.feiniu_sync_interval_hours || 24)

    if (!pansouForm.value.baseUrl) {
      pansouForm.value.baseUrl = data.pansou_base_url || ''
    }

    // TG Bot settings
    tgBotForm.value.enabled = !!data.tg_bot_enabled
    tgBotForm.value.token = data.tg_bot_token || ''
    tgBotForm.value.allowedUsers = Array.isArray(data.tg_bot_allowed_users) ? data.tg_bot_allowed_users : []
    tgBotForm.value.notifyChatIds = Array.isArray(data.tg_bot_notify_chat_ids) ? data.tg_bot_notify_chat_ids : []

    // Detail tabs visibility
    if (Array.isArray(data.detail_visible_tabs)) {
      const s = new Set(data.detail_visible_tabs)
      detailTabsForm.pan115 = s.has('pan115')
      detailTabsForm.pan115_children = ['pan115_pansou', 'pan115_hdhive', 'pan115_tg'].filter(k => s.has(k))
      detailTabsForm.magnet = s.has('magnet')
      detailTabsForm.magnet_children = ['magnet_seedhub', 'magnet_butailing'].filter(k => s.has(k))
    }

    schedulerForm.value.offlineTransferEnabled = !!data.subscription_offline_transfer_enabled
    schedulerForm.value.hdhive.enabled = !!data.subscription_hdhive_enabled
    schedulerForm.value.hdhive.intervalHours = Number(data.subscription_hdhive_interval_hours || 24)
    schedulerForm.value.hdhive.runTime = data.subscription_hdhive_run_time || '03:00'

    schedulerForm.value.pansou.enabled = !!data.subscription_pansou_enabled
    schedulerForm.value.pansou.intervalHours = Number(data.subscription_pansou_interval_hours || 24)
    schedulerForm.value.pansou.runTime = data.subscription_pansou_run_time || '03:15'
    schedulerForm.value.tg.enabled = !!data.subscription_tg_enabled
    schedulerForm.value.tg.intervalHours = Number(data.subscription_tg_interval_hours || 24)
    schedulerForm.value.tg.runTime = data.subscription_tg_run_time || '03:30'
    schedulerForm.value.hdhiveUnlock.enabled = !!data.subscription_hdhive_auto_unlock_enabled
    schedulerForm.value.hdhiveUnlock.maxPointsPerItem = Number(data.subscription_hdhive_unlock_max_points_per_item || 10)
    schedulerForm.value.hdhiveUnlock.budgetPointsPerRun = Number(data.subscription_hdhive_unlock_budget_points_per_run || 30)
    schedulerForm.value.hdhiveUnlock.thresholdInclusive = data.subscription_hdhive_unlock_threshold_inclusive !== false
    schedulerForm.value.hdhiveUnlock.preferFree = data.subscription_hdhive_prefer_free !== false

    // Resource quality preferences
    resourcePrefForm.resolutions = Array.isArray(data.resource_preferred_resolutions) ? data.resource_preferred_resolutions : []
    resourcePrefForm.formats = Array.isArray(data.resource_preferred_formats) ? data.resource_preferred_formats : []

    const priority = Array.isArray(data.subscription_resource_priority)
      ? data.subscription_resource_priority.map(item => String(item || '').trim().toLowerCase())
      : []
    const deduped = []
    for (const source of priority) {
      if (!sourceLabelMap[source]) continue
      if (!deduped.includes(source)) deduped.push(source)
    }
    for (const source of ['hdhive', 'pansou', 'tg']) {
      if (!deduped.includes(source)) deduped.push(source)
    }
    resourcePriority.value = deduped
    updateSourceForm.value.sourceType = data.update_source_type || 'official'
    updateSourceForm.value.repository = data.update_repository || officialUpdateRepository

    // 榜单订阅
    loadChartSubSettings(data)
  } catch (error) {
    console.error('Failed to fetch runtime settings:', error)
  }
}

const handleSaveUpdateSettings = async () => {
  const repository = effectiveUpdateRepository.value
  if (isCustomUpdateSource.value && !repository) {
    ElMessage.warning('请输入自定义 DockerHub 仓库名')
    return
  }

  savingUpdateSettings.value = true
  try {
    await settingsApi.updateRuntime({
      update_source_type: updateSourceForm.value.sourceType,
      update_repository: repository
    })
    updateSourceForm.value.repository = repository || officialUpdateRepository
    await fetchAppInfo()
    ElMessage.success('更新检查源已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '更新检查源保存失败')
  } finally {
    savingUpdateSettings.value = false
  }
}

const handleCheckUpdates = async () => {
  checkingUpdates.value = true
  try {
    const { data } = await settingsApi.checkUpdates()
    updateCheckState.checked = true
    updateCheckState.compareStatus = data.compare_status || ''
    updateCheckState.hasUpdate = data.has_update
    updateCheckState.latestVersion = data.latest_version || ''
    updateCheckState.latestTag = data.latest_tag || ''
    updateCheckState.latestPublishedAt = data.latest_published_at || ''
    updateCheckState.checkedAt = data.checked_at || ''
    updateCheckState.message = data.message || ''
    updateCheckState.repository = data.update_repository || effectiveUpdateRepository.value
    updateCheckState.isOfficialSource = data.is_official_source !== false

    appInfo.value.currentVersion = data.current_version || appInfo.value.currentVersion
    appInfo.value.currentImageTag = data.current_image_tag || appInfo.value.currentImageTag
    appInfo.value.currentGitSha = data.current_git_sha || appInfo.value.currentGitSha
    appInfo.value.currentBuildTime = data.current_build_time || appInfo.value.currentBuildTime
    appInfo.value.isDockerBuild = !!data.is_docker_build

    if (data.compare_status === 'update_available') {
      ElMessage.warning(data.message || '检测到新版本')
    } else if (data.compare_status === 'up_to_date') {
      ElMessage.success(data.message || '当前已是最新版本')
    } else {
      ElMessage.info(data.message || '已完成更新检查')
    }
  } catch (error) {
    updateCheckState.checked = true
    updateCheckState.compareStatus = 'unknown'
    updateCheckState.hasUpdate = null
    updateCheckState.message = error.response?.data?.detail || '检查更新失败'
    updateCheckState.checkedAt = new Date().toISOString()
    ElMessage.error(updateCheckState.message)
  } finally {
    checkingUpdates.value = false
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

const normalizeResourcePriority = (priorityList) => {
  const fallbackOrder = ['hdhive', 'pansou', 'tg']
  const normalized = []
  for (const item of Array.isArray(priorityList) ? priorityList : []) {
    const source = String(item || '').trim().toLowerCase()
    if (!fallbackOrder.includes(source)) continue
    if (!normalized.includes(source)) normalized.push(source)
  }
  for (const source of fallbackOrder) {
    if (!normalized.includes(source)) normalized.push(source)
  }
  return normalized
}

const handleSaveResourcePriority = async () => {
  savingResourcePriority.value = true
  try {
    const normalizedPriority = normalizeResourcePriority(resourcePriority.value)
    await settingsApi.updateRuntime({
      subscription_resource_priority: normalizedPriority
    })
    resourcePriority.value = normalizedPriority
    ElMessage.success('资源查找优先级已保存，已应用到全局订阅转存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '资源查找优先级保存失败')
  } finally {
    savingResourcePriority.value = false
  }
}

const handleSaveScheduler = async () => {
  if (schedulerForm.value.hdhiveUnlock.enabled) {
    const maxPointsPerItem = Number(schedulerForm.value.hdhiveUnlock.maxPointsPerItem || 0)
    const budgetPointsPerRun = Number(schedulerForm.value.hdhiveUnlock.budgetPointsPerRun || 0)
    if (maxPointsPerItem < 1) {
      ElMessage.warning('HDHive 单条积分阈值必须大于等于 1')
      return
    }
    if (budgetPointsPerRun < 1) {
      ElMessage.warning('HDHive 每次任务总预算必须大于等于 1')
      return
    }
  }

  savingScheduler.value = true
  try {
    const normalizedPriority = normalizeResourcePriority(resourcePriority.value)
    await settingsApi.updateRuntime({
      subscription_offline_transfer_enabled: schedulerForm.value.offlineTransferEnabled,
      subscription_hdhive_enabled: schedulerForm.value.hdhive.enabled,
      subscription_hdhive_interval_hours: Number(schedulerForm.value.hdhive.intervalHours || 24),
      subscription_hdhive_run_time: schedulerForm.value.hdhive.runTime || '03:00',
      subscription_pansou_enabled: schedulerForm.value.pansou.enabled,
      subscription_pansou_interval_hours: Number(schedulerForm.value.pansou.intervalHours || 24),
      subscription_pansou_run_time: schedulerForm.value.pansou.runTime || '03:15',
      subscription_tg_enabled: schedulerForm.value.tg.enabled,
      subscription_tg_interval_hours: Number(schedulerForm.value.tg.intervalHours || 24),
      subscription_tg_run_time: schedulerForm.value.tg.runTime || '03:30',
      subscription_resource_priority: normalizedPriority,
      subscription_hdhive_auto_unlock_enabled: schedulerForm.value.hdhiveUnlock.enabled,
      subscription_hdhive_unlock_max_points_per_item: Number(schedulerForm.value.hdhiveUnlock.maxPointsPerItem || 10),
      subscription_hdhive_unlock_budget_points_per_run: Number(schedulerForm.value.hdhiveUnlock.budgetPointsPerRun || 30),
      subscription_hdhive_unlock_threshold_inclusive: schedulerForm.value.hdhiveUnlock.thresholdInclusive !== false,
      subscription_hdhive_prefer_free: schedulerForm.value.hdhiveUnlock.preferFree !== false,
      resource_preferred_resolutions: resourcePrefForm.resolutions,
      resource_preferred_formats: resourcePrefForm.formats
    })
    resourcePriority.value = normalizedPriority
    ElMessage.success('订阅任务、资源优先级与 HDHive 解锁策略已保存')
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
  const loadingRef = channel === 'hdhive'
    ? runningHdhive
    : channel === 'pansou'
      ? runningPansou
      : runningTg
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

const handleRunAllChannels = async () => {
  if (runningAllChannels.value || runningSubscriptionChannel.value) return
  runningAllChannels.value = true
  runningTaskMessage.value = '任务已提交，等待执行...'
  try {
    const { data } = await subscriptionApi.runAllChannelsCheckBackground(true)
    if (data?.already_running) {
      const runningChannels = data?.running_channels || []
      if (runningChannels.length > 0) {
        ElMessage.info(`以下渠道正在运行中: ${runningChannels.join(', ')}`)
        runningAllChannels.value = false
        runningTaskMessage.value = ''
        return
      }
    }
    runningTaskId.value = data?.task_id || ''
    if (!runningTaskId.value) {
      ElMessage.error('未能获取任务ID')
      runningAllChannels.value = false
      runningTaskMessage.value = ''
      return
    }
    const taskResult = await pollSubscriptionTask(runningTaskId.value)
    if (taskResult.ok) {
      const result = taskResult.task?.result || {}
      const successCount = result.success_count || 0
      const failedCount = result.failed_count || 0
      const message = taskResult.task?.message || `全部渠道执行完成: ${successCount} 成功, ${failedCount} 失败`
      if (failedCount === 0) {
        ElMessage.success(message)
      } else if (successCount > 0) {
        ElMessage.warning(message)
      } else {
        ElMessage.error(message)
      }
    } else {
      const errorMessage = taskResult.task?.error || taskResult.task?.message || '执行全部渠道失败'
      ElMessage.error(errorMessage)
    }
    await fetchSubscriptionLogs()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '执行全部渠道失败')
  } finally {
    runningAllChannels.value = false
    runningTaskId.value = ''
    runningTaskMessage.value = ''
  }
}

const getSettingsFolderForm = (target = settingsFolderPickerTarget.value) => {
  return target === 'offline' ? offlineDefaultFolderForm.value : defaultFolderForm.value
}

const getSettingsFolderDisplayName = (folder) => {
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

const getSettingsFolderPickerCurrentName = () => {
  if (settingsFolderPickerCurrentCid.value === '0') return '根目录'

  const currentForm = getSettingsFolderForm()
  if (
    String(currentForm.folderId || '') === settingsFolderPickerCurrentCid.value
    && String(currentForm.folderName || '').trim()
  ) {
    return String(currentForm.folderName).trim()
  }

  const currentItem = settingsFolderPickerHistory.value.find(item => item.cid === settingsFolderPickerCurrentCid.value)
  return getSettingsFolderDisplayName(currentItem) || settingsFolderPickerCurrentCid.value
}

const loadSettingsFolderPickerFolders = async (cid) => {
  settingsFolderPickerLoading.value = true
  settingsFolderPickerCurrentCid.value = cid
  try {
    const { data } = await archiveApi.listFolders(cid)
    settingsFolderPickerFolders.value = (Array.isArray(data?.folders) ? data.folders : []).map(folder => ({
      cid: String(folder.cid || ''),
      name: getSettingsFolderDisplayName(folder)
    }))
  } catch {
    settingsFolderPickerFolders.value = []
  } finally {
    settingsFolderPickerLoading.value = false
  }
}

const openSettingsFolderPicker = (target) => {
  const currentForm = getSettingsFolderForm(target)
  const currentCid = String(currentForm.folderId || '0') || '0'
  const currentName = String(currentForm.folderName || '').trim()

  settingsFolderPickerTarget.value = target
  settingsFolderPickerCurrentCid.value = currentCid
  settingsFolderPickerHistory.value = currentCid !== '0'
    ? [{ cid: currentCid, name: currentName || currentCid }]
    : []
  settingsFolderPickerFolders.value = []
  settingsFolderPickerVisible.value = true
  loadSettingsFolderPickerFolders(currentCid)
}

const navigateSettingsFolderPicker = (cid) => {
  if (cid === settingsFolderPickerCurrentCid.value) return

  const index = settingsFolderPickerHistory.value.findIndex(item => item.cid === cid)
  if (index >= 0) {
    settingsFolderPickerHistory.value = settingsFolderPickerHistory.value.slice(0, index + 1)
  } else if (cid === '0') {
    settingsFolderPickerHistory.value = []
  }

  loadSettingsFolderPickerFolders(cid)
}

const handleSettingsFolderPickerRowClick = (row) => {
  enterSettingsFolderPickerFolder(row)
}

const enterSettingsFolderPickerFolder = (row) => {
  const rowName = getSettingsFolderDisplayName(row)
  const currentName = getSettingsFolderPickerCurrentName()

  if (
    settingsFolderPickerCurrentCid.value !== '0'
    && !settingsFolderPickerHistory.value.find(item => item.cid === settingsFolderPickerCurrentCid.value)
  ) {
    settingsFolderPickerHistory.value.push({ cid: settingsFolderPickerCurrentCid.value, name: currentName })
  }

  if (!settingsFolderPickerHistory.value.find(item => item.cid === row.cid)) {
    settingsFolderPickerHistory.value.push({ cid: row.cid, name: rowName })
  }

  loadSettingsFolderPickerFolders(row.cid)
}

const createSettingsFolderPickerFolder = async () => {
  try {
    const { value } = await ElMessageBox.prompt('请输入新文件夹名称', '新建文件夹', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPattern: /\S+/,
      inputErrorMessage: '文件夹名称不能为空'
    })

    const folderName = String(value || '').trim()
    if (!folderName) return

    settingsFolderPickerCreating.value = true
    await pan115Api.createFolder(settingsFolderPickerCurrentCid.value, folderName)
    ElMessage.success(`已创建文件夹：${folderName}`)
    await loadSettingsFolderPickerFolders(settingsFolderPickerCurrentCid.value)
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return
    }
  } finally {
    settingsFolderPickerCreating.value = false
  }
}

const confirmSettingsFolderPicker = () => {
  const targetForm = getSettingsFolderForm()
  targetForm.folderId = settingsFolderPickerCurrentCid.value
  targetForm.folderName = getSettingsFolderPickerCurrentName()
  settingsFolderPickerVisible.value = false
  ElMessage.success('目录已选择，点击保存设置生效')
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
    ElMessage.success('默认离线目录设置成功')
  } catch (error) {
    ElMessage.error('设置失败')
  } finally {
    savingOfflineFolder.value = false
  }
}

onMounted(() => {
  fetchAuthSession()
  fetchRuntimeSettings().then(() => {
    fetchAppInfo()
    if (String(hdhiveForm.value.apiKey || '').trim()) {
      checkHdhive(false)
    }
    if (String(embyForm.value.url || '').trim() && String(embyForm.value.apiKey || '').trim()) {
      checkEmby(false)
    }
    fetchEmbySyncStatus(false)
    if (String(feiniuForm.value.url || '').trim()) {
      checkFeiniu(false)
    }
    fetchFeiniuSyncStatus(false)
    if (String(tgForm.value.session || '').trim()) {
      checkTg(false)
    }
    refreshSourceConnectionStatus()
  })
  fetchCookieInfo()
  checkCookie()
  fetchDefaultFolder()
  fetchOfflineDefaultFolder()
  fetchPansouConfig()
  fetchTgIndexStatus()
  fetchSubscriptionLogs()
  fetchProxyStatus()
  fetchHealthStatus()
  loadLicense()
  loadAvailableCharts()
})

onBeforeUnmount(() => {
  stopPan115QrPolling()
  stopTgQrPolling()
  stopEmbySyncPolling()
  stopFeiniuSyncPolling()
})
</script>

<style lang="scss" scoped>
.settings-page {
  .settings-tabs {
    :deep(.el-tabs__content) {
      padding-top: 14px;
    }

    :deep(.el-tabs__nav-wrap) {
      scrollbar-width: none;
    }

    :deep(.el-tabs__nav-wrap::-webkit-scrollbar) {
      display: none;
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

    .pan115-qr-login {
      display: flex;
      flex-direction: column;
      gap: 10px;
      align-items: flex-start;
    }

    .pan115-qr-device {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .pan115-qr-preview,
    .pan115-qr-placeholder {
      width: 220px;
      height: 220px;
      border: 1px solid var(--ms-border-light, #d8e2ef);
      border-radius: 8px;
      background: var(--ms-bg-elevated);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 8px;
      color: var(--ms-text-muted);
      text-align: center;
    }

    .pan115-qr-preview img {
      width: 100%;
      height: 100%;
      object-fit: contain;
    }

    .pan115-qr-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .pan115-qr-status {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }

    .tg-link {
      margin-left: 12px;
    }

    .tg-qr-preview {
      width: 220px;
      height: 220px;
      border: 1px solid var(--ms-border-light, #d8e2ef);
      border-radius: 8px;
      padding: 8px;
      background: var(--ms-bg-elevated);

      img {
        width: 100%;
        height: 100%;
        object-fit: contain;
      }
    }

    .preference-inline-group {
      display: flex;
      flex-wrap: nowrap;
      align-items: center;
      gap: 18px;
      overflow-x: auto;
      padding-bottom: 4px;

      :deep(.el-checkbox) {
        margin-right: 0;
        white-space: nowrap;
        flex: 0 0 auto;
      }
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
        flex-wrap: wrap;
        gap: 10px;
      }

      .folder-tag-row {
        display: flex;
        align-items: center;
        min-width: 0;
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

      .folder-selector {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 10px;
      }

      .folder-tag-row {
        display: flex;
        align-items: center;
        min-width: 0;
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

    .about-update-section {
      display: flex;
      flex-direction: column;
      gap: 16px;

      .about-version-list,
      .about-update-form,
      .update-result {
        width: 100%;
      }

      .update-result-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 10px;
      }

      .update-result-title {
        color: var(--ms-text-primary);
        font-weight: 600;
      }

      .update-source-tip {
        margin-top: 8px;
        display: block;
      }
    }

    .health-status {
      .service-card {
        margin-bottom: 12px;

        .service-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;

          .service-name {
            font-weight: 600;
            color: var(--ms-text-primary);
          }
        }

        .service-message {
          font-size: 12px;
          color: var(--ms-text-secondary);
          line-height: 1.4;
        }

        .service-detail {
          margin-top: 6px;
          font-size: 12px;
          color: var(--ms-text-muted);
          line-height: 1.4;
          word-break: break-all;
        }
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

    .priority-actions-row {
      margin-top: 8px;
    }

    :deep(.el-form-item__content) {
      min-width: 0;
    }
  }
}

@media (max-width: 900px) {
  .settings-page {
    h2 {
      margin-bottom: 18px;
      font-size: 24px;
    }

    .settings-tabs {
      :deep(.el-tabs__item) {
        font-size: 13px;
      }
    }

    .settings-card {
      .card-header,
      .pan115-qr-status,
      .priority-item,
      .priority-item-left {
        align-items: flex-start;
        flex-direction: column;
      }

      .priority-actions {
        width: 100%;
        justify-content: flex-end;
      }

      .tg-link {
        margin-left: 0;
        margin-top: 8px;
      }

      .default-folder-section {
        .folder-selector {
          flex-direction: column;
          align-items: stretch;
        }
      }

      .offline-folder-section {
        .folder-selector {
          flex-direction: column;
          align-items: stretch;
        }
      }

      :deep(.el-form-item) {
        display: block;
      }

      :deep(.el-form-item__label) {
        display: block;
        width: auto !important;
        margin-bottom: 8px;
        line-height: 1.5;
        text-align: left;
      }

      :deep(.el-form-item__content) {
        margin-left: 0 !important;
      }

      :deep(.el-card__header),
      :deep(.el-card__body) {
        padding-inline: 16px;
      }

      :deep(.el-table) {
        display: block;
        overflow-x: auto;
      }

      :deep(.el-table__inner-wrapper) {
        min-width: 720px;
      }
    }
  }
}

.folder-picker-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.folder-picker-breadcrumb {
  flex: 1;
  min-width: 0;
}

.folder-picker-toolbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-shrink: 0;
}

.folder-picker-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

@media (max-width: 768px) {
  .settings-page {
    .settings-card {
      .pan115-qr-preview,
      .pan115-qr-placeholder,
      .tg-qr-preview {
        width: min(220px, 100%);
        height: auto;
        min-height: 180px;
      }

      .pan115-qr-actions {
        width: 100%;

        .el-button {
          flex: 1 1 100%;
          margin-left: 0;
        }
      }

      .health-status {
        :deep(.el-col) {
          max-width: 100%;
          flex: 0 0 100%;
        }
      }
    }
  }
}

@media (max-width: 900px) {
  .folder-picker-header {
    flex-direction: column;
    align-items: stretch;
  }

  .folder-picker-toolbar {
    justify-content: flex-start;
  }

  .folder-picker-footer {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
