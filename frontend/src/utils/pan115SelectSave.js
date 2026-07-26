import { ElMessage } from 'element-plus'

import { pan115Api } from '@/api'
import {
  buildPanShareRequest,
  buildUnlockResourceFromPayload,
  sanitizeReceiveCode,
  resolveOfflineDownloadLink,
} from '@/utils/panShare'
import {
  ensureHdhiveShareLink,
  isHdhiveResourceLocked,
  normalizePan115TransferError,
  shouldRetryHdhiveUnlockForPan115,
} from '@/utils/hdhiveUnlock'

export class SelectSaveAbortError extends Error {
  constructor(message = '选集转存已取消') {
    super(message)
    this.name = 'SelectSaveAbortError'
  }
}

export const isShareVideoFile = (item) => {
  if (item?.is_video === true) return true
  const name = String(item?.name || '')
  return /\.(mp4|mkv|avi|rmvb|flv|ts|m2ts|mov|wmv|m4v|webm)$/i.test(name)
}

const filterVideoFiles = (list) => {
  const allFiles = Array.isArray(list) ? list : []
  const videoFiles = allFiles.filter((item) => isShareVideoFile(item))
  // 后端已识别为视频但扩展名非常规时，仍保留给用户选择
  if (videoFiles.length === 0) {
    const backendTagged = allFiles.filter((item) => item?.is_video === true)
    if (backendTagged.length > 0) return backendTagged
  }
  return videoFiles
}

const notifyEmptyVideoFiles = (data, allFiles) => {
  ElMessage.info(
    `未找到可选的视频文件（总文件 ${Number(data?.total_count || allFiles.length || 0)}，识别为视频 ${Number(data?.video_count || 0)}）`,
  )
}

const extractShareFileList = async (shareUrl, receiveCode) => {
  const { data } = await pan115Api.extractShareFiles(shareUrl, receiveCode)
  const allFiles = Array.isArray(data?.list) ? data.list : []
  const videoFiles = filterVideoFiles(allFiles)
  return { data, allFiles, videoFiles }
}

/**
 * 选集转存：解析分享链接并提取文件列表（含 HDHive 解锁与提取码重试）
 */
export const loadPan115SelectSaveFiles = async ({
  row,
  unlockingSlugs = null,
  actionLabel = '选集转存',
  skipHdhiveUnlock = false,
  getDefaultFolderId = async () => '0',
  buildFolderName = () => '',
  onFormUpdate = null,
  onFilesLoaded = null,
}) => {
  let { shareUrl, receiveCode } = buildPanShareRequest(row)

  if (!skipHdhiveUnlock && row?.source_service === 'hdhive' && isHdhiveResourceLocked(row)) {
    const unlockedLink = await ensureHdhiveShareLink(row, {
      actionLabel,
      unlockingSlugs,
    })
    if (!unlockedLink) throw new SelectSaveAbortError()
    ;({ shareUrl, receiveCode } = buildPanShareRequest(row, unlockedLink))
  }

  if (!shareUrl) {
    if (resolveOfflineDownloadLink(row)) {
      ElMessage.warning('该资源解锁后为离线链接（ED2K/磁力），不支持选集转存，请使用一键转存')
    } else {
      ElMessage.warning('该资源暂无分享链接')
    }
    throw new SelectSaveAbortError()
  }

  const targetFolder = await getDefaultFolderId()
  onFormUpdate?.({
    shareLink: shareUrl,
    receiveCode,
    targetFolder,
    newFolderName: buildFolderName() || '',
  })

  const applyFiles = (result) => {
    onFilesLoaded?.(result.videoFiles)
    if (result.videoFiles.length === 0) {
      notifyEmptyVideoFiles(result.data, result.allFiles)
    }
    return result
  }

  try {
    const result = await extractShareFileList(shareUrl, receiveCode)
    return applyFiles(result)
  } catch (error) {
    const detail = normalizePan115TransferError(error)
    if (row?.source_service === 'hdhive' && shouldRetryHdhiveUnlockForPan115(detail)) {
      const unlockedLink = await ensureHdhiveShareLink(row, {
        actionLabel,
        forceUnlock: true,
        reason: '115 返回“请输入访问码”，需要先进行 HDHive 解锁。',
        unlockingSlugs,
      })
      if (!unlockedLink) throw new SelectSaveAbortError()

      ;({ shareUrl, receiveCode } = buildPanShareRequest(row, unlockedLink))
      onFormUpdate?.({
        shareLink: shareUrl,
        receiveCode,
      })

      try {
        const retryResult = await extractShareFileList(shareUrl, receiveCode)
        return applyFiles(retryResult)
      } catch (retryError) {
        const retryDetail = normalizePan115TransferError(retryError)
        ElMessage.error(retryDetail || '提取文件列表失败')
        throw retryError
      }
    }

    ElMessage.error(detail || '提取文件列表失败')
    throw error
  }
}

/** 解锁成功后写回清洗过的分享/离线信息，避免杂质进入后续流程 */
export const applyUnlockedPanShareToRow = (row, payload = {}) => {
  const resource = buildUnlockResourceFromPayload(payload, row)
  const accessCode = sanitizeReceiveCode(payload?.access_code || '')
  if (accessCode) row.access_code = accessCode
  row.hdhive_locked = false
  row.hdhive_lock_code = ''
  row.hdhive_lock_message = ''
  row.pan115_savable = Boolean(resource.link)

  if (resource.kind === 'ed2k') {
    row.ed2k = resource.link
    row.magnet = ''
    row.share_link = ''
    row.pan115_share_link = ''
    return ''
  }
  if (resource.kind === 'magnet') {
    row.magnet = resource.link
    row.ed2k = ''
    row.share_link = ''
    row.pan115_share_link = ''
    return ''
  }
  if (resource.link) {
    row.share_link = resource.link
    row.pan115_share_link = resource.link
    row.ed2k = ''
  }
  return resource.link
}
