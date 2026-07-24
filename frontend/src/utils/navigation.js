/** 详情页返回快照（sessionStorage，同一时间只保留一个来源上下文） */
const DETAIL_RETURN_KEY = 'mediasync115:detail-return'
const LEGACY_SEARCH_RETURN_KEY = 'mediasync115:search-return'
const DETAIL_RETURN_TTL_MS = 30 * 60 * 1000

const removeStorageItem = (key) => {
  try {
    sessionStorage.removeItem(key)
  } catch {
    // ignore storage access failures
  }
}

const readDetailReturnContext = () => {
  try {
    const raw = sessionStorage.getItem(DETAIL_RETURN_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    const savedAt = Number(data?.savedAt) || 0
    if (!savedAt || Date.now() - savedAt > DETAIL_RETURN_TTL_MS) {
      removeStorageItem(DETAIL_RETURN_KEY)
      return null
    }
    return data
  } catch {
    removeStorageItem(DETAIL_RETURN_KEY)
    return null
  }
}

const writeDetailReturnContext = (payload) => {
  try {
    sessionStorage.setItem(DETAIL_RETURN_KEY, JSON.stringify({
      ...payload,
      savedAt: Date.now()
    }))
    removeStorageItem(LEGACY_SEARCH_RETURN_KEY)
  } catch {
    // ignore quota errors
  }
}

/**
 * 进入详情前保存搜索上下文，返回时恢复。
 */
export const saveSearchReturnContext = (context) => {
  const keyword = String(context?.keyword || '').trim()
  if (!keyword) return
  writeDetailReturnContext({
    type: 'search',
    path: String(context.path || '/explore/douban'),
    keyword,
    page: Math.max(1, Number(context.page) || 1)
  })
}

/**
 * 读取并清除搜索返回上下文。
 */
export const clearSearchReturnContext = () => {
  removeStorageItem(DETAIL_RETURN_KEY)
  removeStorageItem(LEGACY_SEARCH_RETURN_KEY)
}

export const consumeSearchReturnContext = () => {
  const current = readDetailReturnContext()
  if (current?.type === 'search') {
    removeStorageItem(DETAIL_RETURN_KEY)
    const keyword = String(current.keyword || '').trim()
    if (!keyword) return null
    return {
      path: String(current.path || '/explore/douban'),
      keyword,
      page: Math.max(1, Number(current.page) || 1)
    }
  }

  if (current) return null

  // 兼容升级前已写入的搜索快照。
  try {
    const raw = sessionStorage.getItem(LEGACY_SEARCH_RETURN_KEY)
    removeStorageItem(LEGACY_SEARCH_RETURN_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    const keyword = String(data?.keyword || '').trim()
    if (!keyword) return null
    return {
      path: String(data.path || '/explore/douban'),
      keyword,
      page: Math.max(1, Number(data.page) || 1)
    }
  } catch {
    removeStorageItem(LEGACY_SEARCH_RETURN_KEY)
    return null
  }
}

/**
 * 进入详情前保存榜单加载进度与点击条目，返回时由对应榜单消费。
 */
export const saveExploreSectionReturnContext = (context) => {
  const source = String(context?.source || '').trim().toLowerCase()
  const sectionKey = String(context?.sectionKey || '').trim()
  const itemKey = String(context?.itemKey || '').trim()
  const path = String(context?.path || '').trim()
  if (!['douban', 'tmdb', 'maoyan'].includes(source)) return
  if (!sectionKey || !itemKey || !path.startsWith('/') || path.startsWith('//')) return

  writeDetailReturnContext({
    type: 'explore-section',
    source,
    sectionKey,
    path,
    itemKey,
    itemIndex: Math.max(0, Number(context.itemIndex) || 0),
    loadedUntil: Math.max(1, Number(context.loadedUntil) || 1),
    displayCount: Math.max(1, Number(context.displayCount) || 1),
    scrollY: Math.max(0, Number(context.scrollY) || 0)
  })
}

/**
 * 仅由原来源、原栏目消费榜单快照，避免其他探索页误用旧位置。
 */
export const consumeExploreSectionReturnContext = (source, sectionKey) => {
  const normalizedSource = String(source || '').trim().toLowerCase()
  const normalizedSectionKey = String(sectionKey || '').trim()
  const current = readDetailReturnContext()
  if (
    current?.type !== 'explore-section'
    || current.source !== normalizedSource
    || current.sectionKey !== normalizedSectionKey
  ) {
    return null
  }

  removeStorageItem(DETAIL_RETURN_KEY)
  return {
    source: current.source,
    sectionKey: current.sectionKey,
    path: String(current.path || ''),
    itemKey: String(current.itemKey || ''),
    itemIndex: Math.max(0, Number(current.itemIndex) || 0),
    loadedUntil: Math.max(1, Number(current.loadedUntil) || 1),
    displayCount: Math.max(1, Number(current.displayCount) || 1),
    scrollY: Math.max(0, Number(current.scrollY) || 0)
  }
}

/**
 * 解析探索页 from 参数（榜单等非搜索场景）。
 */
export const parseExploreFromLocation = (rawFrom) => {
  const from = String(rawFrom || '').trim()
  if (!from.startsWith('/') || from.startsWith('//')) {
    return null
  }
  try {
    const url = new URL(from, 'http://local')
    const query = {}
    url.searchParams.forEach((value, key) => {
      query[key] = value
    })
    return { path: url.pathname, query }
  } catch {
    const [path = '/explore/douban', search = ''] = from.split('?')
    const query = {}
    if (search) {
      const params = new URLSearchParams(search)
      params.forEach((value, key) => {
        query[key] = value
      })
    }
    return { path, query }
  }
}

/**
 * 详情页返回：
 * 1. 搜索快照 → 回到搜索结果
 * 2. 探索 from 参数 → 回到探索/榜单
 * 3. 否则 history.back
 */
export const navigateBackFromDetail = (router, route, fallback = '/explore/douban') => {
  const searchReturn = consumeSearchReturnContext()
  if (searchReturn) {
    const query = { q: searchReturn.keyword }
    if (searchReturn.page > 1) {
      query.page = String(searchReturn.page)
    }
    router.replace({
      path: searchReturn.path,
      query
    })
    return
  }

  const exploreFrom = parseExploreFromLocation(route.query?.from)
  if (exploreFrom) {
    router.replace(exploreFrom)
    return
  }

  if (window.history.length > 1) {
    router.back()
    return
  }

  router.replace(fallback)
}
