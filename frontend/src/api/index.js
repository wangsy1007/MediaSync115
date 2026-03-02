import axios from 'axios'
import { ElMessage } from 'element-plus'
import { BEIJING_TIMEZONE } from '@/utils/timezone'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000
})

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

    // 离线任务列表错误由 Downloads 页面自己处理，避免干扰转存等场景。
    if (isOfflineTasksRequest) {
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
  getExploreSections: (source = 'douban', limit = 24, refresh = false) =>
    api.get('/search/explore/sections', { params: { source, limit, refresh } }),
  getExploreSection: (source = 'douban', sectionKey, limit = 30, refresh = false, start = 0) =>
    api.get(`/search/explore/section/${sectionKey}`, { params: { source, limit, refresh, start } }),
  resolveExploreItem: (payload) => api.post('/search/explore/resolve', payload),
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
  getMoviePan115: (tmdbId, page = 1) => api.get(`/search/movie/${tmdbId}/115`, { params: { page } }),
  getMoviePan115Pansou: (tmdbId, page = 1) => api.get(`/search/movie/${tmdbId}/115/pansou`, { params: { page } }),
  getMoviePan115Hdhive: (tmdbId, page = 1) => api.get(`/search/movie/${tmdbId}/115/hdhive`, { params: { page } }),
  getMoviePan115Tg: (tmdbId, page = 1) => api.get(`/search/movie/${tmdbId}/115/tg`, { params: { page } }),
  getHdhivePan115ByKeyword: (keyword, mediaType = 'movie') =>
    api.get('/search/hdhive/115/by-keyword', { params: { keyword, media_type: mediaType } }),
  getTgPan115ByKeyword: (keyword, mediaType = 'movie') =>
    api.get('/search/tg/115/by-keyword', { params: { keyword, media_type: mediaType } }),
  unlockHdhiveResource: (slug) => api.post('/search/hdhive/resource/unlock', { slug }),
  getMovieMagnet: (tmdbId) => api.get(`/search/movie/${tmdbId}/magnet`),
  getMovieMagnetSeedhub: (tmdbId) => api.get(`/search/movie/${tmdbId}/magnet`, { params: { source: 'seedhub' } }),
  createMovieSeedhubMagnetTask: (tmdbId, limit = 40, forceRefresh = false) =>
    api.post(`/search/movie/${tmdbId}/magnet/seedhub/tasks`, null, { params: { limit, force_refresh: forceRefresh } }),
  getMovieEd2k: (tmdbId) => api.get(`/search/movie/${tmdbId}/ed2k`),
  getMovieVideo: (tmdbId) => api.get(`/search/movie/${tmdbId}/video`),

  getTv: (tmdbId) => api.get(`/search/tv/${tmdbId}`),
  getTvPan115: (tmdbId, page = 1) => api.get(`/search/tv/${tmdbId}/115`, { params: { page } }),
  getTvPan115Pansou: (tmdbId, page = 1) => api.get(`/search/tv/${tmdbId}/115/pansou`, { params: { page } }),
  getTvPan115Hdhive: (tmdbId, page = 1) => api.get(`/search/tv/${tmdbId}/115/hdhive`, { params: { page } }),
  getTvPan115Tg: (tmdbId, page = 1) => api.get(`/search/tv/${tmdbId}/115/tg`, { params: { page } }),

  getTvSeason: (tmdbId, seasonNumber) => api.get(`/search/tv/${tmdbId}/season/${seasonNumber}`),
  getTvSeasonMagnet: (tmdbId, seasonNumber) => api.get(`/search/tv/${tmdbId}/season/${seasonNumber}/magnet`),

  getTvEpisode: (tmdbId, seasonNumber, episodeNumber) => api.get(`/search/tv/${tmdbId}/season/${seasonNumber}/episode/${episodeNumber}`),
  getTvEpisodeMagnet: (tmdbId, seasonNumber, episodeNumber) => api.get(`/search/tv/${tmdbId}/season/${seasonNumber}/episode/${episodeNumber}/magnet`),
  getTvEpisodeEd2k: (tmdbId, seasonNumber, episodeNumber) => api.get(`/search/tv/${tmdbId}/season/${seasonNumber}/episode/${episodeNumber}/ed2k`),
  getTvEpisodeVideo: (tmdbId, seasonNumber, episodeNumber) => api.get(`/search/tv/${tmdbId}/season/${seasonNumber}/episode/${episodeNumber}/video`),

  getTvMagnet: (tmdbId, season, episode) => api.get(`/search/tv/${tmdbId}/magnet`, { params: { season, episode } }),
  getTvMagnetSeedhub: (tmdbId) => api.get(`/search/tv/${tmdbId}/magnet`, { params: { source: 'seedhub' } }),
  createTvSeedhubMagnetTask: (tmdbId, limit = 40, forceRefresh = false) =>
    api.post(`/search/tv/${tmdbId}/magnet/seedhub/tasks`, null, { params: { limit, force_refresh: forceRefresh } }),
  getSeedhubMagnetTask: (taskId) => api.get(`/search/magnet/seedhub/tasks/${taskId}`),
  cancelSeedhubMagnetTask: (taskId) => api.delete(`/search/magnet/seedhub/tasks/${taskId}`),
  getTvEd2k: (tmdbId, season, episode) => api.get(`/search/tv/${tmdbId}/ed2k`, { params: { season, episode } }),
  getTvVideo: (tmdbId, season, episode) => api.get(`/search/tv/${tmdbId}/video`, { params: { season, episode } }),

  getCollection: (collectionId) => api.get(`/search/collection/${collectionId}`),
  getCollectionPan115: (collectionId, page = 1) => api.get(`/search/collection/${collectionId}/115`, { params: { page } })
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
  updateRuntime: (payload) => api.put('/settings/runtime', payload),
  checkNullbr: () => api.get('/settings/nullbr/check'),
  checkHdhive: () => api.get('/settings/hdhive/check'),
  checkTg: () => api.get('/settings/tg/check'),
  tgSendCode: (phone) => api.post('/settings/tg/login/send-code', { phone }),
  tgVerifyCode: (payload) => api.post('/settings/tg/login/verify-code', payload),
  tgVerifyPassword: (payload) => api.post('/settings/tg/login/verify-password', payload),
  tgLogout: () => api.post('/settings/tg/logout')
}

export const subscriptionApi = {
  list: (params) => api.get('/subscriptions', { params }),
  get: (id) => api.get(`/subscriptions/${id}`),
  create: (data) => api.post('/subscriptions', data),
  update: (id, data) => api.put(`/subscriptions/${id}`, data),
  delete: (id) => api.delete(`/subscriptions/${id}`),
  
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
  }
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

  // ==================== 用户信息 ====================
  getUserInfo: () => api.get('/pan115/user'),
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
