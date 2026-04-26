import axios from 'axios'
import { ElMessage } from 'element-plus'
import { BEIJING_TIMEZONE } from '@/utils/timezone'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000
})

const BACKEND_UNAVAILABLE_CODE = 'backend_unavailable'
const BACKEND_UNAVAILABLE_STATUSES = new Set([502, 503, 504])
const BACKEND_UNAVAILABLE_MESSAGE = '后端正在启动，请稍后重试'

let lastBackendUnavailableNoticeAt = 0

const sleep = (ms) => new Promise(resolve => window.setTimeout(resolve, ms))

export const isBackendUnavailableError = (error) => {
  const status = Number(error?.response?.status || 0)
  const code = String(error?.response?.data?.code || '').trim()
  return code === BACKEND_UNAVAILABLE_CODE || BACKEND_UNAVAILABLE_STATUSES.has(status)
}

export const waitForBackendReady = async (maxWaitMs = 45000, intervalMs = 1500) => {
  if (typeof window === 'undefined' || typeof fetch !== 'function') {
    return false
  }

  const deadline = Date.now() + Math.max(1000, Number(maxWaitMs) || 45000)
  const interval = Math.max(300, Number(intervalMs) || 1500)

  while (Date.now() < deadline) {
    try {
      const response = await fetch('/healthz', {
        method: 'GET',
        cache: 'no-store',
        headers: {
          Accept: 'application/json, text/plain, */*'
        }
      })
      if (response.ok) {
        return true
      }
    } catch {
      // ignore transient health probe failures while backend is warming up.
    }
    await sleep(interval)
  }

  return false
}

const showBackendUnavailableMessage = () => {
  const now = Date.now()
  if (now - lastBackendUnavailableNoticeAt < 4000) {
    return
  }
  lastBackendUnavailableNoticeAt = now
  ElMessage.warning(BACKEND_UNAVAILABLE_MESSAGE)
}

api.interceptors.request.use((config) => {
  const nextConfig = { ...config }
  nextConfig.headers = {
    ...(config.headers || {}),
    'X-Client-Timezone': BEIJING_TIMEZONE
  }
  return nextConfig
})

api.interceptors.response.use(
  response => response,
  error => {
    const detail = String(error.response?.data?.detail || '').trim()
    const requestUrl = String(error.config?.url || '')
    const isOfflineTasksRequest = requestUrl.includes('/pan115/offline/tasks')
    const isAuthSessionRequest = requestUrl.includes('/auth/session')
    const isAuthLoginRequest = requestUrl.includes('/auth/login')
    const isAuthLogoutRequest = requestUrl.includes('/auth/logout')
    const isUnauthorized = error.response?.status === 401

    // 离线任务列表错误由 Downloads 页面自己处理，避免干扰转存等场景。
    if (isOfflineTasksRequest) {
      return Promise.reject(error)
    }

    if (isAuthSessionRequest) {
      return Promise.reject(error)
    }

    if (isBackendUnavailableError(error)) {
      showBackendUnavailableMessage()
      return Promise.reject(error)
    }

    if (isUnauthorized && !isAuthLoginRequest && !isAuthLogoutRequest) {
      if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }

    let message = detail || error.message || '请求失败'
    if (
      detail.includes('离线任务列表请求过于频繁')
    ) {
      message = '115接口触发风控，请稍后重试'
    }

    ElMessage.error(message)
    return Promise.reject(error)
  }
)

export const searchApi = {
  search: (query, page = 1) => api.get('/search', { params: { query, page } }),
  getExploreMeta: (source = 'douban') =>
    api.get('/search/explore/meta', { params: { source } }),
  getExploreHomeSections: (source = 'douban', refresh = false) =>
    api.get('/search/explore/home', { params: { source, refresh } }),
  getExploreSections: (source = 'douban', limit = 24, refresh = false) =>
    api.get('/search/explore/sections', { params: { source, limit, refresh } }),
  getExploreSection: (source = 'douban', sectionKey, limit = 30, refresh = false, start = 0) =>
    api.get(`/search/explore/section/${sectionKey}`, { params: { source, limit, refresh, start } }),
  getEmbyStatusMap: (items = []) => api.post('/search/emby/status-map', { items }),
  getFeiniuStatusMap: (items = []) => api.post('/search/feiniu/status-map', { items }),
  resolveExploreItem: (payload) => api.post('/search/explore/resolve', payload),
  enqueueExploreSubscribeTask: (payload) => api.post('/search/explore/queue/subscribe', payload),
  enqueueExploreSaveTask: (payload) => api.post('/search/explore/queue/save', payload),
  getExploreQueueTask: (taskId) => api.get(`/search/explore/queue/tasks/${encodeURIComponent(taskId)}`),
  getExploreActiveQueueTasks: (queueType = 'all') =>
    api.get('/search/explore/queue/active', { params: { queue_type: queueType } }),
  getDoubanSubject: (doubanId, mediaType = 'movie') =>
    api.get(`/search/douban/subject/${encodeURIComponent(doubanId)}`, { params: { media_type: mediaType } }),
  getExploreDoubanSections: (limit = 24, refresh = false) =>
    api.get('/search/explore/douban-sections', { params: { limit, refresh } }),
  getExploreDoubanSection: (sectionKey, limit = 30, refresh = false, start = 0) =>
    api.get(`/search/explore/douban-section/${sectionKey}`, { params: { limit, refresh, start } }),
  getExplorePopularMovies: (limit = 30, refresh = false) =>
    api.get('/search/explore/popular', { params: { limit, refresh } }),
  getExplorePopularSections: (limit = 24, refresh = false) =>
    api.get('/search/explore/popular-sections', { params: { limit, refresh } }),
  getMovie: (tmdbId) => api.get(`/search/movie/${tmdbId}`),
  getMoviePan115: (tmdbId, page = 1, refresh = false) =>
    api.get(`/search/movie/${tmdbId}/115`, { params: { page, refresh } }),
  getMoviePan115Pansou: (tmdbId, page = 1, refresh = false) =>
    api.get(`/search/movie/${tmdbId}/115/pansou`, { params: { page, refresh } }),
  getMoviePan115Hdhive: (tmdbId, page = 1, refresh = false) =>
    api.get(`/search/movie/${tmdbId}/115/hdhive`, { params: { page, refresh } }),
  getMoviePan115Tg: (tmdbId, page = 1, refresh = false) =>
    api.get(`/search/movie/${tmdbId}/115/tg`, { params: { page, refresh } }),
  getHdhivePan115ByKeyword: (keyword, mediaType = 'movie') =>
    api.get('/search/hdhive/115/by-keyword', { params: { keyword, media_type: mediaType } }),
  getTgPan115ByKeyword: (keyword, mediaType = 'movie') =>
    api.get('/search/tg/115/by-keyword', { params: { keyword, media_type: mediaType } }),
  getSeedhubMagnetByKeyword: (keyword, mediaType = 'movie', limit = 80) =>
    api.get(`/search/seedhub/${mediaType}/magnet/by-keyword`, { params: { keyword, limit } }),
  unlockHdhiveResource: (slug) => api.post('/search/hdhive/resource/unlock', { slug }),
  getMovieMagnet: (tmdbId) => api.get(`/search/movie/${tmdbId}/magnet`),
  getMovieMagnetSeedhub: (tmdbId, limit = 80) =>
    api.get(`/search/movie/${tmdbId}/magnet`, { params: { source: 'seedhub', limit } }),
  getMovieMagnetButailing: (tmdbId) =>
    api.get(`/search/movie/${tmdbId}/magnet/butailing`),
  createMovieSeedhubMagnetTask: (tmdbId, limit = 40, forceRefresh = false) =>
    api.post(`/search/movie/${tmdbId}/magnet/seedhub/tasks`, null, { params: { limit, force_refresh: forceRefresh } }),

  getTv: (tmdbId) => api.get(`/search/tv/${tmdbId}`),
  getTvPan115: (tmdbId, page = 1, refresh = false) =>
    api.get(`/search/tv/${tmdbId}/115`, { params: { page, refresh } }),
  getTvPan115Pansou: (tmdbId, page = 1, refresh = false) =>
    api.get(`/search/tv/${tmdbId}/115/pansou`, { params: { page, refresh } }),
  getTvPan115Hdhive: (tmdbId, page = 1, refresh = false) =>
    api.get(`/search/tv/${tmdbId}/115/hdhive`, { params: { page, refresh } }),
  getTvPan115Tg: (tmdbId, page = 1, refresh = false) =>
    api.get(`/search/tv/${tmdbId}/115/tg`, { params: { page, refresh } }),

  getTvSeason: (tmdbId, seasonNumber) => api.get(`/search/tv/${tmdbId}/season/${seasonNumber}`),

  getTvEpisode: (tmdbId, seasonNumber, episodeNumber) => api.get(`/search/tv/${tmdbId}/season/${seasonNumber}/episode/${episodeNumber}`),

  getTvMagnet: (tmdbId, season, episode) => api.get(`/search/tv/${tmdbId}/magnet`, { params: { season, episode } }),
  getTvMagnetSeedhub: (tmdbId, limit = 80) =>
    api.get(`/search/tv/${tmdbId}/magnet`, { params: { source: 'seedhub', limit } }),
  getTvMagnetButailing: (tmdbId) =>
    api.get(`/search/tv/${tmdbId}/magnet/butailing`),
  createTvSeedhubMagnetTask: (tmdbId, limit = 40, forceRefresh = false) =>
    api.post(`/search/tv/${tmdbId}/magnet/seedhub/tasks`, null, { params: { limit, force_refresh: forceRefresh } }),
  getSeedhubMagnetTask: (taskId) => api.get(`/search/magnet/seedhub/tasks/${taskId}`),
  cancelSeedhubMagnetTask: (taskId) => api.delete(`/search/magnet/seedhub/tasks/${taskId}`),
  getBridgeByImdbId: (imdbId, mediaType = 'movie') => api.get(`/search/bridge/imdb/${imdbId}`, { params: { media_type: mediaType } })
}

export const authApi = {
  getSession: () => api.get('/auth/session'),
  login: (payload) => api.post('/auth/login', payload),
  logout: () => api.post('/auth/logout'),
  changeCredentials: (payload) => api.post('/auth/change-credentials', payload)
}

export const pansouApi = {
  health: () => api.get('/pansou/health'),
  search: (keyword, cloudTypes = ['115'], res = 'results', refresh = false) =>
    api.post('/pansou/search', { keyword, cloud_types: cloudTypes, res, refresh }),
  getConfig: () => api.get('/pansou/config'),
  updateConfig: (baseUrl) => api.put('/pansou/config', { base_url: baseUrl })
}

export const settingsApi = {
  getRuntime: () => api.get('/settings/runtime'),
  getAppInfo: () => api.get('/settings/app-info'),
  updateRuntime: (payload) => api.put('/settings/runtime', payload),
  checkUpdates: () => api.get('/settings/update-check'),
  checkHdhive: () => api.get('/settings/hdhive/check'),
  runHdhiveCheckin: (payload) => api.post('/settings/hdhive/checkin', payload),
  checkTg: () => api.get('/settings/tg/check'),
  checkTmdb: () => api.get('/settings/tmdb/check'),
  checkPansou: () => api.get('/settings/pansou/check'),
  checkEmby: (params) => api.get('/settings/emby/check', { params }),
  checkFeiniu: (params) => api.get('/settings/feiniu/check', { params }),
  feiniuLogin: (username, password, url) => api.post('/settings/feiniu/login', { username, password, url }),
  getEmbySyncStatus: () => api.get('/settings/emby/sync/status'),
  runEmbySync: () => api.post('/settings/emby/sync/run'),
  getFeiniuSyncStatus: () => api.get('/settings/feiniu/sync/status'),
  runFeiniuSync: () => api.post('/settings/feiniu/sync/run'),
  checkAllHealth: () => api.get('/settings/health/all'),
  getProxy: () => api.get('/settings/proxy'),
  tgVerifyPassword: (payload) => api.post('/settings/tg/login/verify-password', payload),
  tgStartQrLogin: () => api.post('/settings/tg/login/qr/start'),
  tgCheckQrLogin: (token) => api.post('/settings/tg/login/qr/status', { token }),
  tgLogout: () => api.post('/settings/tg/logout'),
  getTgIndexStatus: () => api.get('/settings/tg/index/status'),
  refreshTgIndexStatus: () => api.post('/settings/tg/index/status/refresh'),
  startTgIndexBackfill: (rebuild = false) => api.post('/settings/tg/index/backfill/start', { rebuild }),
  runTgIndexIncremental: () => api.post('/settings/tg/index/incremental/run'),
  getTgIndexJob: (jobId) => api.get(`/settings/tg/index/jobs/${encodeURIComponent(jobId)}`),
  rebuildTgIndex: () => api.post('/settings/tg/index/rebuild'),
  // TG Bot
  getTgBotStatus: () => api.get('/settings/tg-bot/status'),
  restartTgBot: () => api.post('/settings/tg-bot/restart'),
  stopTgBot: () => api.post('/settings/tg-bot/stop'),
  // 榜单订阅
  getAvailableCharts: () => api.get('/settings/chart-subscription/charts'),
  runChartSubscription: () => api.post('/settings/chart-subscription/run', null, { timeout: 120000 }),
}

export const licenseApi = {
  getStatus: () => api.get('/license/status'),
  activate: (licenseKey) => api.put('/license/activate', { license_key: licenseKey }),
  checkFeature: (feature) => api.post('/license/check-feature', null, { params: { feature } }),
}

export const logsApi = {
  list: (params) => api.get('/logs', { params }),
  modules: () => api.get('/logs/modules'),
  prune: (days = 30) => api.post('/logs/prune', null, { params: { days } }),
  clear: () => api.delete('/logs/clear')
}

export const archiveApi = {
  getConfig: () => api.get('/archive/config'),
  updateConfig: (payload) => api.put('/archive/config', payload),
  listFolders: (cid = '0') => api.get('/archive/folders', { params: { cid } }),
  listTasks: (params) => api.get('/archive/tasks', { params }),
  runScan: () => api.post('/archive/scan', null, { timeout: 300000 }),
  retryTask: (taskId) => api.post(`/archive/tasks/${taskId}/retry`, null, { timeout: 300000 }),
  clearTasks: (includeFailed = false) => api.delete('/archive/tasks/clear', { params: { include_failed: includeFailed } })
}

export const strmApi = {
  getConfig: () => api.get('/strm/config'),
  updateConfig: (payload) => api.put('/strm/config', payload),
  generate: () => api.post('/strm/generate', null, { timeout: 300000 }),
  diagnose: () => api.get('/strm/diagnose', { timeout: 30000 })
}

export const subscriptionApi = {
  list: (params) => api.get('/subscriptions', { params }),
  listForStatus: (params) => api.get('/subscriptions/status-map', {
    params: {
      is_active: true,
      ...(params || {})
    }
  }),
  get: (id) => api.get(`/subscriptions/${id}`),
  create: (data) => api.post('/subscriptions', data),
  update: (id, data) => api.put(`/subscriptions/${id}`, data),
  delete: (id) => api.delete(`/subscriptions/${id}`),
  deleteByType: (mediaType) => api.delete(`/subscriptions/batch/${mediaType}`),
  
  // 下载记录相关
  getDownloads: (id, status = null) => api.get(`/subscriptions/${id}/downloads`, { params: { status } }),
  createDownload: (id, data) => api.post(`/subscriptions/${id}/downloads`, data),
  getDownload: (id, recordId) => api.get(`/subscriptions/${id}/downloads/${recordId}`),
  updateDownload: (id, recordId, data) => api.put(`/subscriptions/${id}/downloads/${recordId}`, data),
  deleteDownload: (id, recordId) => api.delete(`/subscriptions/${id}/downloads/${recordId}`),
  markDownloadComplete: (id, recordId) => api.post(`/subscriptions/${id}/downloads/${recordId}/complete`),
  markDownloadFailed: (id, recordId, errorMessage = null) => 
    api.post(`/subscriptions/${id}/downloads/${recordId}/fail`, null, { params: { error_message: errorMessage } }),

  runChannelCheck: (channel) => api.post('/subscriptions/system/run', { channel }, { timeout: 300000 }),
  runChannelCheckBackground: (channel, forceAutoDownload = false) =>
    api.post('/subscriptions/system/run/background', { channel, force_auto_download: forceAutoDownload }),
  runAllChannelsCheckBackground: (forceAutoDownload = false) =>
    api.post('/subscriptions/system/run/background', { channel: 'all', force_auto_download: forceAutoDownload }),
  getRunTask: (taskId) => api.get(`/subscriptions/system/run/tasks/${taskId}`),
  listLogs: async (params) => {
    try {
      return await api.get('/subscriptions/system/logs', { params })
    } catch (error) {
      if (error?.response?.status === 404) {
        return api.get('/subscriptions/actions/logs', { params })
      }
      throw error
    }
  },
  listStepLogs: async (params) => {
    try {
      return await api.get('/subscriptions/system/logs/steps', { params })
    } catch (error) {
      if (error?.response?.status === 404) {
        return api.get('/subscriptions/actions/logs/steps', { params })
      }
      throw error
    }
  },
  getTvMissingStatus: (params) => api.get('/subscriptions/missing-status/tv', { params }),
  getSubscriptionTvMissingStatus: (id, params) => api.get(`/subscriptions/${id}/tv/missing-status`, { params })
}

export const schedulerApi = {
  listJobKeys: () => api.get('/scheduler/job-keys'),
  listJobs: () => api.get('/scheduler/jobs'),
  runJob: (jobId) => api.post(`/scheduler/run/${encodeURIComponent(jobId)}`),
  listTasks: () => api.get('/scheduler/tasks'),
  createTask: (data) => api.post('/scheduler/tasks', data),
  updateTask: (taskId, data) => api.put(`/scheduler/tasks/${taskId}`, data),
  enableTask: (taskId) => api.post(`/scheduler/tasks/${taskId}/enable`),
  pauseTask: (taskId) => api.post(`/scheduler/tasks/${taskId}/pause`),
  deleteTask: (taskId) => api.delete(`/scheduler/tasks/${taskId}`)
}

export const workflowApi = {
  list: () => api.get('/workflow'),
  get: (id) => api.get(`/workflow/${id}`),
  create: (data) => api.post('/workflow', data),
  update: (id, data) => api.put(`/workflow/${id}`, data),
  delete: (id) => api.delete(`/workflow/${id}`),
  run: (id) => api.post(`/workflow/${id}/run`),
  start: (id) => api.post(`/workflow/${id}/start`),
  pause: (id) => api.post(`/workflow/${id}/pause`),
  reset: (id) => api.post(`/workflow/${id}/reset`),
  listEventTypes: () => api.get('/workflow/event-types'),
  triggerEvent: (payload) => api.post('/workflow/events/trigger', payload)
}

export const pan115Api = {
  // ==================== Cookie管理 ====================
  checkCookie: () => api.get('/pan115/cookie/check'),
  updateCookie: (cookie) => api.post('/pan115/cookie/update', { cookie }),
  getCookieInfo: () => api.get('/pan115/cookie'),
  startQrLogin: (app = 'alipaymini') => api.post('/pan115/login/qr/start', { app }),
  checkQrLogin: (token) => api.post('/pan115/login/qr/status', { token }),
  cancelQrLogin: (token) => api.post('/pan115/login/qr/cancel', { token }),

  // ==================== 用户信息 ====================
  getUserInfo: () => api.get('/pan115/user'),
  getOfflineQuota: () => api.get('/pan115/offline/quota'),
  getRiskHealth: () => api.get('/pan115/health/risk'),

  // ==================== 文件操作 ====================
  getFileList: (cid = '0', offset = 0, limit = 50) => 
    api.get('/pan115/files', { params: { cid, offset, limit } }),
  
  createFolder: (pid, name) => 
    api.post('/pan115/folder', { pid, name }),
  
  renameFile: (fid, name) => 
    api.post('/pan115/rename', { fid, name }),
  
  deleteFile: (fid) => 
    api.delete('/pan115/files', { params: { fid } }),
  
  copyFile: (fid, pid) => 
    api.post('/pan115/copy', null, { params: { fid, pid } }),
  
  moveFile: (fid, pid) => 
    api.post('/pan115/move', null, { params: { fid, pid } }),
  
  getFileInfo: (fid) => 
    api.get(`/pan115/files/${fid}`),
  
  searchFile: (searchValue, cid = '0') => 
    api.get('/pan115/search', { params: { search_value: searchValue, cid } }),
  
  getDownloadUrl: (pickCode) => 
    api.get(`/pan115/download/${pickCode}`),

  // ==================== 离线下载 ====================
  addOfflineTask: (url, wpPathId = '') => 
    api.post('/pan115/offline/task', { url, wp_path_id: wpPathId }),
  
  getOfflineTasks: (page = 1) => 
    api.get('/pan115/offline/tasks', { params: { page } }),
  
  deleteOfflineTasks: (hashList) => {
    const list = Array.isArray(hashList) ? hashList : [hashList]
    const params = new URLSearchParams()
    list.filter(Boolean).forEach((hash) => params.append('hash_list', String(hash)))
    return api.delete('/pan115/offline/tasks', { params })
  },

  restartOfflineTask: (infoHash) =>
    api.post('/pan115/offline/restart', null, { params: { info_hash: infoHash } }),
  
  clearOfflineTasks: (mode = 'completed') => 
    api.post('/pan115/offline/clear', null, { params: { mode } }),

  getOfflineDefaultFolder: () => api.get('/pan115/offline/default-folder'),
  setOfflineDefaultFolder: (folderId, folderName = '') =>
    api.post('/pan115/offline/default-folder', { folder_id: folderId, folder_name: folderName }),

  // ==================== 分享链接操作 ====================
  parseShareLink: (shareUrl) => 
    api.post('/pan115/share/parse', null, { params: { share_url: shareUrl } }),
  
  getShareFileList: (shareCode, receiveCode = '', cid = '0', offset = 0, limit = 50) => 
    api.get('/pan115/share/files', { params: { share_code: shareCode, receive_code: receiveCode, cid, offset, limit } }),
  
  saveShareFile: (shareCode, fileId, pid = '0', receiveCode = '') => 
    api.post('/pan115/share/save', { share_code: shareCode, file_id: fileId, pid, receive_code: receiveCode }),
  
  saveShareFiles: (shareCode, fileIds, pid = '0', receiveCode = '') => 
    api.post('/pan115/share/save-batch', { share_code: shareCode, file_ids: fileIds, pid, receive_code: receiveCode }),
  
  saveShareAll: (shareCode, pid = '0', receiveCode = '') => 
    api.post('/pan115/share/save-all', null, { params: { share_code: shareCode, pid, receive_code: receiveCode } }),
  
  saveShareToFolder: (shareUrl, folderName, parentId = '0', receiveCode = '', tmdbId = null) => 
    api.post('/pan115/share/save-to-folder', { share_url: shareUrl, folder_name: folderName, parent_id: parentId, receive_code: receiveCode, tmdb_id: tmdbId }),

  extractShareFiles: (shareUrl, receiveCode = '') => 
    api.post('/pan115/share/extract-files', { share_url: shareUrl, receive_code: receiveCode }),

  saveShareFilesToFolder: (shareUrl, fileIds, folderName, parentId = '0', receiveCode = '') => 
    api.post('/pan115/share/save-files-to-folder', { share_url: shareUrl, file_ids: fileIds, folder_name: folderName, parent_id: parentId, receive_code: receiveCode }),

  // ==================== 默认转存文件夹 ====================
  getDefaultFolder: () => api.get('/pan115/default-folder'),
  setDefaultFolder: (folderId, folderName = '') => 
    api.post('/pan115/default-folder', { folder_id: folderId, folder_name: folderName })
}

export default api
