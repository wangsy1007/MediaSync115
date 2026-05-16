/** 探索榜单分页批次缓存（首页横滑与「更多」页共用） */

const BATCH_CACHE_TTL_MS = 10 * 60 * 1000
const batchCache = new Map()
const batchInflight = new Map()

export const buildExploreBatchCacheKey = (source, sectionKey, start, count) =>
  `${source}:${sectionKey}:${start}:${count}`

export const getCachedExploreSectionBatch = (source, sectionKey, start, count) => {
  const cacheKey = buildExploreBatchCacheKey(source, sectionKey, start, count)
  const cached = batchCache.get(cacheKey)
  if (!cached) return null
  if (Date.now() >= cached.expiresAt) {
    batchCache.delete(cacheKey)
    return null
  }
  const payload = cached.payload || {}
  if (
    !Object.prototype.hasOwnProperty.call(payload, 'emby_status_map') ||
    !Object.prototype.hasOwnProperty.call(payload, 'feiniu_status_map')
  ) {
    batchCache.delete(cacheKey)
    return null
  }
  return payload
}

export const setCachedExploreSectionBatch = (source, sectionKey, start, count, payload) => {
  const cacheKey = buildExploreBatchCacheKey(source, sectionKey, start, count)
  batchCache.set(cacheKey, {
    payload,
    expiresAt: Date.now() + BATCH_CACHE_TTL_MS
  })
}

export const getExploreSectionBatchInflight = (source, sectionKey, start, count) => {
  const cacheKey = buildExploreBatchCacheKey(source, sectionKey, start, count)
  return batchInflight.get(cacheKey) || null
}

export const setExploreSectionBatchInflight = (source, sectionKey, start, count, task) => {
  const cacheKey = buildExploreBatchCacheKey(source, sectionKey, start, count)
  if (task) {
    batchInflight.set(cacheKey, task)
  } else {
    batchInflight.delete(cacheKey)
  }
}
