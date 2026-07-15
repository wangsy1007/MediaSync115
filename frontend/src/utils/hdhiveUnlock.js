import { ElLoading, ElMessage } from 'element-plus'

import { pan115Api, searchApi } from '@/api'
import { executePan115SaveToFolder } from '@/utils/pan115SaveFlow'
import { resolvePanShareLink, buildShareLinkFromUnlockPayload, sanitizeReceiveCode } from '@/utils/panShare'
import { openPan115ProgressDialog } from '@/utils/pan115ProgressDialog'
import { showHdhiveUnlockDialog } from '@/utils/showHdhiveUnlockDialog'

/** HDHive 资源是否仍需解锁（无分享链接） */
export const isHdhiveResourceLocked = (row) => {
  if (!row || row.source_service !== 'hdhive') return false
  return !resolvePanShareLink(row)
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
    const shareLink = buildShareLinkFromUnlockPayload(data, row)
    if (!shareLink) {
      throw new Error(data?.message || '未获取到分享链接')
    }
    row.share_link = shareLink
    row.access_code = sanitizeReceiveCode(data?.access_code || row?.access_code || '')
    row.pan115_savable = true
    row.hdhive_locked = false
    row.hdhive_lock_code = ''
    row.hdhive_lock_message = ''
    return { ok: true, shareLink }
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
  if (!forceUnlock && !locked) return currentLink

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
}) => {
  const prefix = resourceLabel ? `「${resourceLabel}」` : '资源'
  const unlockSuffix = afterUnlock ? '（HDHive 解锁后）' : ''

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

/**
 * HDHive 解锁 + 115 转存一体化流程（居中弹窗展示解锁/转存进度与结果）
 */
export const runHdhivePan115SaveFlow = async ({
  row,
  folderName,
  folderId = '0',
  resolveReceiveCode,
  unlockingSlugs = null,
  forceUnlock = false,
  unlockReason = '',
}) => {
  const resourceLabel = getHdhiveResourceLabel(row)
  const progress = openPan115ProgressDialog({ resourceLabel })
  const afterUnlock = forceUnlock || isHdhiveResourceLocked(row)

  try {
    let shareLink = resolvePanShareLink(row)

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
          unlockResult.message || 'HDHive 解锁失败，未能获取分享链接',
        )
        return { ok: false, status: 'failed' }
      }
      shareLink = unlockResult.shareLink
    }

    if (!shareLink) {
      await finishProgressDialog(progress, 'failed', '该资源暂无分享链接')
      return { ok: false, status: 'failed' }
    }

    progress.setPhase('transfer', '正在转存到 115 网盘，请稍候...')
    const receiveCode = resolveReceiveCode(row, shareLink)
    const response = await executePan115SaveToFolder({
      shareUrl: shareLink,
      folderName,
      parentId: folderId,
      receiveCode,
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
