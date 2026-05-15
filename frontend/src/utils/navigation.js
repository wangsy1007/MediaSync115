/** 搜索结果页返回快照（sessionStorage） */
const SEARCH_RETURN_KEY = 'mediasync115:search-return'

/**
 * 进入详情前保存搜索上下文，返回时恢复。
 */
export const saveSearchReturnContext = (context) => {
  const keyword = String(context?.keyword || '').trim()
  if (!keyword) return
  const payload = {
    path: String(context.path || '/explore/douban'),
    keyword,
    page: Math.max(1, Number(context.page) || 1)
  }
  try {
    sessionStorage.setItem(SEARCH_RETURN_KEY, JSON.stringify(payload))
  } catch {
    // ignore quota errors
  }
}

/**
 * 读取并清除搜索返回上下文。
 */
export const clearSearchReturnContext = () => {
  try {
    sessionStorage.removeItem(SEARCH_RETURN_KEY)
  } catch {
    // ignore
  }
}

export const consumeSearchReturnContext = () => {
  try {
    const raw = sessionStorage.getItem(SEARCH_RETURN_KEY)
    sessionStorage.removeItem(SEARCH_RETURN_KEY)
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
    sessionStorage.removeItem(SEARCH_RETURN_KEY)
    return null
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
