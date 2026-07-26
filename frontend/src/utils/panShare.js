/** 清洗 115 提取码，仅保留 4 位字母数字 */
export const sanitizeReceiveCode = (value) => {
  const cleaned = String(value || '').replace(/[^A-Za-z0-9]/g, '')
  const match = cleaned.match(/[A-Za-z0-9]{4}/)
  return match ? match[0] : ''
}

export const isEd2kLink = (value) => String(value || '').trim().toLowerCase().startsWith('ed2k://')

export const isMagnetLink = (value) => String(value || '').trim().toLowerCase().startsWith('magnet:')

export const isOfflineDownloadLink = (value) => isEd2kLink(value) || isMagnetLink(value)

export const isPan115ShareLink = (value) => {
  const raw = String(value || '').trim()
  if (!/^https?:\/\//i.test(raw)) return false
  return /115\.(?:com|cn)|115cdn\.com|anxia\.com/i.test(raw)
}

/** 规范化 ED2K / 磁力离线链接 */
export const sanitizeOfflineDownloadLink = (value) => {
  const raw = String(value || '').trim().replace(/\s+/g, '')
  if (!isOfflineDownloadLink(raw)) return ''
  return raw
}

/** 从文本中提取并规范化 115 分享链接（拒绝 ed2k/magnet） */
export const sanitizePanShareUrl = (shareUrl) => {
  let raw = String(shareUrl || '').trim()
  if (!raw || isOfflineDownloadLink(raw)) return ''

  const urlMatch = raw.match(/https?:\/\/[^\s<>"']+/i)
  if (urlMatch) {
    raw = urlMatch[0]
  }

  if (!/^https?:\/\//i.test(raw)) return ''

  try {
    const url = new URL(raw)
    for (const key of ['password', 'pwd', 'receive_code']) {
      const current = url.searchParams.get(key)
      if (!current) continue
      const cleaned = sanitizeReceiveCode(current)
      if (cleaned) {
        url.searchParams.set(key, cleaned)
      } else {
        url.searchParams.delete(key)
      }
    }
    return url.toString()
  } catch {
    return raw.replace(/[^\x20-\x7E\u4e00-\u9fff/?=&:%._-]/g, '').trim()
  }
}

export const parseReceiveCodeFromShareLink = (shareLink) => {
  const rawLink = sanitizePanShareUrl(shareLink)
  if (!rawLink) return ''

  const shortMatch = rawLink.match(/^[A-Za-z0-9]+-([A-Za-z0-9]{4})$/)
  if (shortMatch) return sanitizeReceiveCode(shortMatch[1])

  const queryMatch = rawLink.match(/[?&](?:password|pwd|receive_code)=([^&#]+)/i)
  if (queryMatch) {
    try {
      return sanitizeReceiveCode(decodeURIComponent(queryMatch[1]))
    } catch {
      return sanitizeReceiveCode(queryMatch[1])
    }
  }

  const textMatch = rawLink.match(/(?:提取码|提取碼|密码|密碼|password|pwd)\s*[:：=]?\s*([A-Za-z0-9]{4})/i)
  if (textMatch) return sanitizeReceiveCode(textMatch[1])

  return ''
}

export const resolvePanShareLink = (row) => (
  sanitizePanShareUrl(String(row?.share_link || row?.share_url || row?.pan115_share_link || '').trim())
)

/** 从资源行提取 ED2K / 磁力离线链接 */
export const resolveOfflineDownloadLink = (row) => {
  const candidates = [
    row?.ed2k,
    row?.ed2k_link,
    row?.ed2k_url,
    row?.magnet,
    row?.magnet_link,
    row?.magnet_url,
    row?.share_link,
    row?.share_url,
    row?.full_url,
    row?.pan115_share_link,
  ]
  for (const candidate of candidates) {
    const link = sanitizeOfflineDownloadLink(candidate)
    if (link) return link
  }
  return ''
}

export const classifyResourceLink = (value) => {
  const offline = sanitizeOfflineDownloadLink(value)
  if (isEd2kLink(offline)) return { kind: 'ed2k', link: offline }
  if (isMagnetLink(offline)) return { kind: 'magnet', link: offline }
  const share = sanitizePanShareUrl(value)
  if (share) return { kind: 'pan115', link: share }
  return { kind: '', link: '' }
}

/** 构建选集/转存请求使用的分享链接与提取码 */
export const buildPanShareRequest = (row, shareLink = '') => {
  const shareUrl = sanitizePanShareUrl(shareLink || resolvePanShareLink(row))
  const linkCode = parseReceiveCodeFromShareLink(shareUrl)
  const rowCode = sanitizeReceiveCode(row?.access_code || row?.hdhive_access_code || '')
  const receiveCode = linkCode || rowCode
  return { shareUrl, receiveCode }
}

/** 从 HDHive 解锁响应或资源行数据拼装完整 115 分享链接 */
export const buildShareLinkFromUnlockPayload = (payload = {}, row = {}) => {
  const direct = classifyResourceLink(payload?.share_link || payload?.full_url || '')
  if (direct.kind === 'pan115') return direct.link

  const resourceUrl = sanitizePanShareUrl(
    payload?.resource_url || row?.hdhive_resource_url || row?.hdhive_media_url || '',
  )
  const accessCode = sanitizeReceiveCode(
    payload?.access_code || row?.access_code || row?.hdhive_access_code || '',
  )
  if (resourceUrl && accessCode) {
    const joiner = resourceUrl.includes('?') ? '&' : '?'
    return sanitizePanShareUrl(`${resourceUrl}${joiner}password=${encodeURIComponent(accessCode)}`)
  }
  return resourceUrl
}

/** 从 HDHive 解锁响应解析可转存资源（115 分享 或 ed2k/magnet） */
export const buildUnlockResourceFromPayload = (payload = {}, row = {}) => {
  const candidates = [
    payload?.share_link,
    payload?.full_url,
    payload?.resource_url,
    row?.ed2k,
    row?.magnet,
    row?.share_link,
  ]
  for (const candidate of candidates) {
    const classified = classifyResourceLink(candidate)
    if (classified.link) return classified
  }

  const shareLink = buildShareLinkFromUnlockPayload(payload, row)
  if (shareLink) return { kind: 'pan115', link: shareLink }
  return { kind: '', link: '' }
}
