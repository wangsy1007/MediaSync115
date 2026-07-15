import { pan115Api } from '@/api'

const SAVE_WAIT_POLL_MS = 2500
const SAVE_WAIT_MAX_MS = 600000

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))

const isTransferConflict = (error) => {
  const status = Number(error?.response?.status || 0)
  const detail = String(error?.response?.data?.detail || '')
  return status === 409 && detail.includes('已有转存任务正在执行')
}

const isTransferGatewayTimeout = (error) => {
  const status = Number(error?.response?.status || 0)
  if (status === 504) return true
  if (error?.code === 'ECONNABORTED') return true
  return String(error?.message || '').toLowerCase().includes('timeout')
}

const isRecentTransferResult = (recent, sinceMs) => {
  if (!recent?.created_at) return false
  const recentAt = Date.parse(recent.created_at)
  if (Number.isNaN(recentAt)) return false
  return recentAt >= sinceMs - 10000
}

const buildSaveResponseFromLog = (recent) => ({
  data: {
    success: recent.status === 'success',
    message: String(recent.message || '')
      .replace(/^\[[^\]]+\]\s*一键转存(成功|失败)：/, '')
      .trim() || (recent.status === 'success' ? '转存成功' : '转存失败'),
  },
})

/** 轮询转存互斥锁，直到任务结束并返回匹配的最近操作日志 */
export const waitForPan115TransferCompletion = async ({
  folderName,
  sinceMs = Date.now(),
  maxWaitMs = SAVE_WAIT_MAX_MS,
} = {}) => {
  const deadline = Date.now() + maxWaitMs

  while (Date.now() < deadline) {
    const { data } = await pan115Api.getTransferStatus(folderName, { silentError: true })
    const recent = data?.recent_result

    if (!data?.in_progress) {
      if (isRecentTransferResult(recent, sinceMs)) {
        return recent
      }
      await sleep(500)
      const { data: recheck } = await pan115Api.getTransferStatus(folderName, { silentError: true })
      if (isRecentTransferResult(recheck?.recent_result, sinceMs)) {
        return recheck.recent_result
      }
      return null
    }

    if (isRecentTransferResult(recent, sinceMs) && recent.status === 'success') {
      return recent
    }

    await sleep(SAVE_WAIT_POLL_MS)
  }

  throw new Error('等待转存完成超时，请稍后在日志页查看结果')
}

/** 115 转存：网关/客户端超时或 409 冲突时自动等待后台任务并回填结果 */
export const executePan115SaveToFolder = async ({
  shareUrl,
  folderName,
  parentId = '0',
  receiveCode = '',
  tmdbId = null,
  requestConfig = {},
} = {}) => {
  const startedAt = Date.now()

  try {
    return await pan115Api.saveShareToFolder(
      shareUrl,
      folderName,
      parentId,
      receiveCode,
      tmdbId,
      requestConfig,
    )
  } catch (error) {
    if (!isTransferConflict(error) && !isTransferGatewayTimeout(error)) {
      throw error
    }

    const recent = await waitForPan115TransferCompletion({
      folderName,
      sinceMs: startedAt,
    })

    if (recent?.status === 'success') {
      return buildSaveResponseFromLog(recent)
    }

    if (recent?.status === 'failed') {
      const failMsg = String(recent.message || '')
        .replace(/^.*转存失败：/, '')
        .trim() || '转存失败'
      throw new Error(failMsg)
    }

    if (isTransferConflict(error)) {
      throw new Error('转存正在进行中，请稍后再试')
    }

    throw new Error('转存请求超时，未能确认最终结果，请稍后在日志页查看')
  }
}
