export const parseReceiveCodeFromShareLink = (shareLink) => {
  const rawLink = String(shareLink || '').trim()
  if (!rawLink) return ''

  const shortMatch = rawLink.match(/^[A-Za-z0-9]+-([A-Za-z0-9]{4})$/)
  if (shortMatch) return shortMatch[1]

  const queryMatch = rawLink.match(/[?&](?:password|pwd|receive_code)=([^&#]+)/i)
  if (queryMatch) {
    try {
      const decoded = decodeURIComponent(queryMatch[1])
      return /^[A-Za-z0-9]{4}$/.test(decoded) ? decoded : ''
    } catch {
      return /^[A-Za-z0-9]{4}$/.test(queryMatch[1]) ? queryMatch[1] : ''
    }
  }

  const textMatch = rawLink.match(/(?:提取码|提取碼|密码|密碼|password|pwd)\s*[:：=]?\s*([A-Za-z0-9]{4})/i)
  if (textMatch) return textMatch[1]

  return ''
}

export const resolvePanShareLink = (row) => String(row?.share_link || row?.share_url || row?.pan115_share_link || '').trim()
