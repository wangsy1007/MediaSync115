import { ElLoading, ElMessage } from 'element-plus'

import { pan115Api, searchApi } from '@/api'
import { executePan115SaveToFolder } from '@/utils/pan115SaveFlow'
import {
  resolvePanShareLink,
  resolveOfflineDownloadLink,
  buildUnlockResourceFromPayload,
  sanitizeReceiveCode,
  isOfflineDownloadLink,
} from '@/utils/panShare'
import { openPan115ProgressDialog } from '@/utils/pan115ProgressDialog'
import { showHdhiveUnlockDialog } from '@/utils/showHdhiveUnlockDialog'

const applyUnlockResourceToRow = (row, resource, payload = {}) => {
  const kind = resource?.kind || ''
  const link = String(resource?.link || '').trim()
  row.hdhive_locked = false
  row.hdhive_lock_code = ''
  row.hdhive_lock_message = ''
  row.access_code = sanitizeReceiveCode(payload?.access_code || row?.access_code || '')

  if (kind === 'ed2k') {
    row.ed2k = link
    row.magnet = ''
    row.share_link = ''
    row.pan115_share_link = ''
    row.pan115_savable = true
    return
  }
  if (kind === 'magnet') {
    row.magnet = link
    row.ed2k = ''
    row.share_link = ''
    row.pan115_share_link = ''
    row.pan115_savable = true
    return
  }

  row.share_link = link
  row.pan115_share_link = link
  row.ed2k = ''
  row.pan115_savable = true
}

/** HDHive 资源是否仍需解锁（无 115 分享且无离线链接） */
export const isHdhiveResourceLocked = (row) => {
  if (!row || row.source_service !== 'hdhive') return false
  return !resolvePanShareLink(row) && !resolveOfflineDownloadLink(row)
}

export const isHdhiveUnlocking = (unlockingSlugs, row) => {
  const slug = String(row?.slug || '').trim()
  if (!slug || !unlockingSlugs) return false
  return unlockingSlugs.has(slug)
}

export const isHdhiveResourceSuspectedInvalid = (row) => {
  if (!row) return false
  if (row.hdhive_suspected_invalid === true) return true
  const validateStatus = String(row.hdhive_validate_status || '').trim().toLowerCase()
  return ['invalid', 'suspected_invalid', 'suspect_invalid'].includes(validateStatus)
}

/** HDHive 资源是否为官组发布 */
export const isHdhiveOfficialResource = (row) => row?.is_official === true

export const isPan115HdhiveActionDisabled = (row, unlockingSlugs, extraDisabled = false) => {
  if (
    extraDisabled
    || Boolean(row?.saving)
    || Boolean(row?.extracting)
    || isHdhiveUnlocking(unlockingSlugs, row)
  ) {
    return true
  }
  if (isHdhiveResourceLocked(row)) return false
  return row?.pan115_savable === false
}

/** 选集转存按钮禁用判断：不因 pan115_savable 拦截，允许解锁后选集 */
export const isPan115SelectSaveDisabled = (row, unlockingSlugs, extraDisabled = false) => (
  extraDisabled
  || Boolean(row?.saving)
  || Boolean(row?.extracting)
  || isHdhiveUnlocking(unlockingSlugs, row)
)

const getHdhiveUnlockPoints = (row) => Number(row?.unlock_points || 0)

export const getHdhiveResourceLabel = (row) => (
  String(row?.resource_name || row?.title || row?.name || '').trim()
)

export const showHdhiveUnlockConfirm = async (row, reason = '') => {
  if (getHdhiveUnlockPoints(row) <= 0) return true
  try {
    return await showHdhiveUnlockDialog(row, reason)
  } catch {
    return false
  }
}

const performHdhiveUnlock = async (row, options = {}) => {
  const {
    unlockingSlugs = null,
    unlockApi = searchApi.unlockHdhiveResource,
  } = options

  const slug = String(row?.slug || '').trim()
  if (!slug) {
    return { ok: false, message: '缺少 HDHive 资源标识，无法解锁' }
  }
  if (unlockingSlugs?.has(slug)) {
    return { ok: false, message: '正在解锁该资源，请稍候' }
  }

  unlockingSlugs?.add(slug)
  try {
    const { data } = await unlockApi(slug)
    const resource = buildUnlockResourceFromPayload(data, row)
    if (!resource.link) {
      throw new Error(data?.message || '未获取到可转存链接')
    }
    applyUnlockResourceToRow(row, resource, data)
    return {
      ok: true,
      kind: resource.kind,
      link: resource.link,
      shareLink: resource.kind === 'pan115' ? resource.link : '',
      offlineUrl: isOfflineDownloadLink(resource.link) ? resource.link : '',
    }
  } catch (error) {
    const detail = String(error.response?.data?.detail || error.message || '').trim()
    return { ok: false, message: detail || 'HDHive 解锁失败' }
  } finally {
    unlockingSlugs?.delete(slug)
  }
}

export const ensureHdhiveShareLink = async (row, options = {}) => {
  const {
    reason = '',
    forceUnlock = false,
    unlockingSlugs = null,
  } = options

  const currentLink = resolvePanShareLink(row)
  const locked = isHdhiveResourceLocked(row)
  if (!forceUnlock && currentLink && !locked) return currentLink
  if (!forceUnlock && !locked) {
    if (resolveOfflineDownloadLink(row)) {
      ElMessage.warning('该资源解锁后为离线链接（ED2K/磁力），不支持选集转存，请使用一键转存')
      return ''
    }
    return currentLink
  }

  const points = getHdhiveUnlockPoints(row)
  if (points > 0) {
    const confirmed = await showHdhiveUnlockConfirm(row, reason)
    if (!confirmed) return ''
  }

  const result = await performHdhiveUnlock(row, { unlockingSlugs })
  if (!result.ok) {
    if (result.message) ElMessage.error(result.message)
    return ''
  }
  if (result.kind !== 'pan115') {
    ElMessage.warning('该资源解锁后为离线链接（ED2K/磁力），不支持选集转存，请使用一键转存')
    return ''
  }
  return result.shareLink
}

export const parsePan115SaveResponse = (data) => {
  const saveSuccess = data?.success === true
    || data?.state === true
    || data?.result?.success === true
    || data?.result?.state === true

  const message = String(
    data?.message || data?.error || data?.result?.error || '',
  ).trim()

  if (!saveSuccess) {
    return { ok: false, status: 'failed', message: message || '转存失败' }
  }

  if (Number(data?.saved_count) === 0) {
    return {
      ok: true,
      status: 'warning',
      message: message || '所有文件均已存在，无需转存',
    }
  }

  return {
    ok: true,
    status: 'success',
    message: message || '转存成功',
  }
}

export const normalizePan115TransferError = (error) => {
  const status = Number(error?.response?.status || 0)
  const detail = String(error?.response?.data?.detail || error?.message || '').trim()
  if (status === 504 || error?.code === 'ECONNABORTED') {
    return '转存耗时较长，连接已断开，后台可能仍在处理，请稍候'
  }
  if (status === 409 && detail.includes('已有转存任务正在执行')) {
    return '已有转存任务进行中，请等待完成后再试'
  }
  if (detail.includes('离线任务列表请求过于频繁')) {
    return '115 接口触发风控，请稍后重试'
  }
  return detail || '转存失败'
}

export const shouldRetryHdhiveUnlockForPan115 = (detail) => (
  detail.includes('4100012') || detail.includes('请输入访问码')
)

const buildTransferStatusMessage = ({
  result,
  resourceLabel = '',
  afterUnlock = false,
  viaOffline = false,
}) => {
  const prefix = resourceLabel ? `「${resourceLabel}」` : '资源'
  const unlockSuffix = afterUnlock ? '（HDHive 解锁后）' : ''

  if (viaOffline) {
    if (result?.status === 'success') {
      return result.message || `${prefix}已提交 115 离线下载${unlockSuffix}`
    }
    return result?.message || `${prefix}离线下载提交失败${unlockSuffix}`
  }

  if (result?.status === 'success') {
    return result.message || `${prefix}已成功转存到 115 网盘${unlockSuffix}`
  }
  if (result?.status === 'warning') {
    return result.message || `${prefix}无需重复转存${unlockSuffix}`
  }
  return result?.message || `${prefix}转存失败${unlockSuffix}`
}

const finishProgressDialog = async (progress, status, message) => {
  progress.setResult(status, message)
  await progress.waitClose()
  progress.destroy()
}

const resolveCurrentResource = (row) => {
  const shareLink = resolvePanShareLink(row)
  if (shareLink) return { kind: 'pan115', link: shareLink }
  const offlineUrl = resolveOfflineDownloadLink(row)
  if (offlineUrl) {
    return {
      kind: offlineUrl.toLowerCase().startsWith('ed2k://') ? 'ed2k' : 'magnet',
      link: offlineUrl,
    }
  }
  return { kind: '', link: '' }
}

const submitOfflineDownloadTask = async ({ url, folderName = '' }) => {
  let defaultFolderId = '0'
  let defaultFolderName = '根目录'
  try {
    const { data } = await pan115Api.getOfflineDefaultFolder()
    defaultFolderId = String(data?.folder_id || '0')
    defaultFolderName = String(data?.folder_name || '').trim() || (defaultFolderId === '0' ? '根目录' : defaultFolderId)
  } catch {
    // 回退根目录
  }

  const title = String(folderName || '').trim()
  await pan115Api.addOfflineTask(url, defaultFolderId, title)
  const locationLabel = defaultFolderId === '0' ? '根目录' : (defaultFolderName || title || defaultFolderId)
  return {
    ok: true,
    status: 'success',
    message: `已添加到离线下载任务，保存至: ${locationLabel}`,
    folderId: defaultFolderId,
  }
}

/**
 * HDHive 解锁 + 115 转存一体化流程（居中弹窗展示解锁/转存进度与结果）
 * - 解锁后若为 115 分享链接：走分享转存
 * - 解锁后若为 ed2k/磁力：走默认离线目录离线下载
 */
export const runHdhivePan115SaveFlow = async ({
  row,
  folderName,
  folderId = '0',
  resolveReceiveCode,
  unlockingSlugs = null,
  forceUnlock = false,
  unlockReason = '',
  tmdbId = null,
  mediaType = null,
}) => {
  const resourceLabel = getHdhiveResourceLabel(row)
  const progress = openPan115ProgressDialog({ resourceLabel })
  const afterUnlock = forceUnlock || isHdhiveResourceLocked(row)

  try {
    let resource = resolveCurrentResource(row)

    if (afterUnlock) {
      const points = getHdhiveUnlockPoints(row)
      if (points > 0 && !forceUnlock) {
        progress.hide()
        const confirmed = await showHdhiveUnlockConfirm(row, unlockReason)
        if (!confirmed) {
          progress.destroy()
          return { ok: false, cancelled: true }
        }
      }

      progress.setPhase('unlock', '正在解锁 HDHive 资源，请稍候...')
      const unlockResult = await performHdhiveUnlock(row, { unlockingSlugs })
      if (!unlockResult.ok) {
        await finishProgressDialog(
          progress,
          'failed',
          unlockResult.message || 'HDHive 解锁失败，未能获取可转存链接',
        )
        return { ok: false, status: 'failed' }
      }
      resource = {
        kind: unlockResult.kind,
        link: unlockResult.link,
      }
    }

    if (!resource.link) {
      await finishProgressDialog(progress, 'failed', '该资源暂无可转存链接')
      return { ok: false, status: 'failed' }
    }

    if (resource.kind === 'ed2k' || resource.kind === 'magnet') {
      progress.setPhase('offline', '检测到离线链接，正在提交 115 离线下载...')
      const offlineResult = await submitOfflineDownloadTask({
        url: resource.link,
        folderName,
      })
      const message = buildTransferStatusMessage({
        result: offlineResult,
        resourceLabel,
        afterUnlock,
        viaOffline: true,
      })
      await finishProgressDialog(progress, offlineResult.status, message)
      return offlineResult
    }

    progress.setPhase('transfer', '正在转存到 115 网盘，请稍候...')
    const receiveCode = resolveReceiveCode(row, resource.link)
    const response = await executePan115SaveToFolder({
      shareUrl: resource.link,
      folderName,
      parentId: folderId,
      receiveCode,
      tmdbId,
      mediaType,
      requestConfig: { silentError: true },
    })
    const parsed = parsePan115SaveResponse(response?.data)
    const message = buildTransferStatusMessage({
      result: parsed,
      resourceLabel,
      afterUnlock,
    })
    await finishProgressDialog(progress, parsed.status, message)
    return parsed
  } catch (error) {
    const detail = normalizePan115TransferError(error)
    if (!forceUnlock && shouldRetryHdhiveUnlockForPan115(detail)) {
      progress.destroy()
      return runHdhivePan115SaveFlow({
        row,
        folderName,
        folderId,
        resolveReceiveCode,
        unlockingSlugs,
        forceUnlock: true,
        unlockReason: '115 返回“请输入访问码”，需要先进行 HDHive 解锁。',
        tmdbId,
        mediaType,
      })
    }
    await finishProgressDialog(progress, 'failed', detail)
    return { ok: false, status: 'failed', message: detail }
  }
}

/** 轻量全屏 Loading（选集提取等场景，避免与业务弹窗冲突） */
export const runPan115Transfer = async ({ text = '正在处理，请稍候...', task }) => {
  const loading = ElLoading.service({
    lock: true,
    text,
    background: 'rgba(15, 23, 42, 0.45)',
  })
  try {
    return await task()
  } finally {
    loading.close()
  }
}
