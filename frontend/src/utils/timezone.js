export const BEIJING_TIMEZONE = 'Asia/Shanghai'

const DEFAULT_FORMAT_OPTIONS = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false
}

const formatterCache = new Map()

const toDate = (value) => {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  const candidate = new Date(value)
  if (!Number.isNaN(candidate.getTime())) return candidate

  if (typeof value === 'string' && value.includes(' ')) {
    const normalized = new Date(value.replace(' ', 'T'))
    if (!Number.isNaN(normalized.getTime())) return normalized
  }

  return null
}

const getFormatter = (options = {}) => {
  const merged = { ...DEFAULT_FORMAT_OPTIONS, ...options, timeZone: BEIJING_TIMEZONE }
  const key = JSON.stringify(merged)
  if (!formatterCache.has(key)) {
    formatterCache.set(key, new Intl.DateTimeFormat('zh-CN', merged))
  }
  return formatterCache.get(key)
}

export const formatBeijingDateTime = (value, options = {}) => {
  const date = toDate(value)
  if (!date) return '-'
  return getFormatter(options).format(date)
}

export const formatBeijingTableCell = (_row, _column, value) => formatBeijingDateTime(value)

export const applyBeijingTimezone = () => {
  if (typeof window !== 'undefined') {
    window.__MEDIA_SYNC_TIMEZONE__ = BEIJING_TIMEZONE
  }
}
