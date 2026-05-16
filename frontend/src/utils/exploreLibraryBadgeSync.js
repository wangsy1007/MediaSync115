import { searchApi } from '@/api'

const DEFAULT_BATCH_SIZE = 24
const DEFAULT_DEBOUNCE_MS = 80
const DEFAULT_MAX_IN_FLIGHT = 2

const toValidTmdbId = (rawId) => {
  const id = Number(rawId)
  if (!Number.isFinite(id) || id <= 0) return null
  return Math.trunc(id)
}

const buildStatusKey = (item) => {
  const mediaType = item?.media_type === 'tv' ? 'tv' : (item?.media_type === 'movie' ? 'movie' : '')
  const tmdbId = toValidTmdbId(item?.tmdb_id ?? item?.tmdbid)
  if (!mediaType || !tmdbId) return ''
  return `${mediaType}:${tmdbId}`
}

const toStatusPayloadItems = (items) => {
  const seen = new Set()
  const rows = []
  for (const item of items) {
    const mediaType = item?.media_type === 'tv' ? 'tv' : (item?.media_type === 'movie' ? 'movie' : '')
    const tmdbId = toValidTmdbId(item?.tmdb_id ?? item?.tmdbid)
    if (!mediaType || !tmdbId) continue
    const key = `${mediaType}:${tmdbId}`
    if (seen.has(key)) continue
    seen.add(key)
    rows.push({ media_type: mediaType, tmdb_id: tmdbId })
  }
  return rows
}

/**
 * 探索页在库角标异步补齐：首屏仍依赖 section 接口内嵌的 status_map，未覆盖条目后台分批查询。
 */
export function createExploreLibraryBadgeSyncer({
  getEmbyStatusMap,
  getFeiniuStatusMap,
  mergeEmbyStatusMap,
  mergeFeiniuStatusMap,
  batchSize = DEFAULT_BATCH_SIZE,
  debounceMs = DEFAULT_DEBOUNCE_MS,
  maxInFlight = DEFAULT_MAX_IN_FLIGHT
} = {}) {
  const queuedItems = []
  const queuedKeySet = new Set()
  const inFlightKeys = new Set()
  let debounceTimer = null
  let disposed = false

  const hasResolvedStatus = (key) => {
    const embyMap = getEmbyStatusMap?.()
    const feiniuMap = getFeiniuStatusMap?.()
    if (!(embyMap instanceof Map) || !(feiniuMap instanceof Map)) return false
    return embyMap.has(key) && feiniuMap.has(key)
  }

  const enqueueItems = (items = []) => {
    if (disposed || !Array.isArray(items) || !items.length) return
    for (const item of items) {
      const key = buildStatusKey(item)
      if (!key || hasResolvedStatus(key) || inFlightKeys.has(key) || queuedKeySet.has(key)) {
        continue
      }
      queuedKeySet.add(key)
      queuedItems.push(item)
    }
  }

  const flushQueue = async () => {
    if (disposed || inFlightKeys.size >= maxInFlight) return

    const batch = []
    const batchKeys = new Set()
    while (queuedItems.length && batch.length < batchSize) {
      const item = queuedItems.shift()
      const key = buildStatusKey(item)
      if (!key) continue
      queuedKeySet.delete(key)
      if (hasResolvedStatus(key) || inFlightKeys.has(key)) continue
      batch.push(item)
      batchKeys.add(key)
    }

    if (!batch.length) return

    for (const key of batchKeys) {
      inFlightKeys.add(key)
    }

    const payloadItems = toStatusPayloadItems(batch)
    try {
      const [embyResult, feiniuResult] = await Promise.all([
        searchApi.getEmbyStatusMap(payloadItems),
        searchApi.getFeiniuStatusMap(payloadItems)
      ])
      if (!disposed) {
        mergeEmbyStatusMap?.(embyResult?.data?.items || {})
        mergeFeiniuStatusMap?.(feiniuResult?.data?.items || {})
      }
    } catch {
      // 角标补齐失败不影响主流程
    } finally {
      for (const key of batchKeys) {
        inFlightKeys.delete(key)
      }
      if (!disposed && queuedItems.length) {
        void flushQueue()
      }
    }
  }

  const scheduleFlush = () => {
    if (disposed) return
    if (debounceTimer) {
      clearTimeout(debounceTimer)
    }
    debounceTimer = setTimeout(() => {
      debounceTimer = null
      void flushQueue()
      if (inFlightKeys.size < maxInFlight && queuedItems.length) {
        void flushQueue()
      }
    }, debounceMs)
  }

  return {
    schedule(items = []) {
      enqueueItems(items)
      if (queuedItems.length) {
        scheduleFlush()
      }
    },
    dispose() {
      disposed = true
      if (debounceTimer) {
        clearTimeout(debounceTimer)
        debounceTimer = null
      }
      queuedItems.length = 0
      queuedKeySet.clear()
      inFlightKeys.clear()
    }
  }
}

export { buildStatusKey as buildExploreLibraryStatusKey }
