/**
 * 解析详情页返回路径，仅允许站内相对路径。
 */
export const resolveInternalBackPath = (rawFrom) => {
  const from = String(rawFrom || '').trim()
  if (!from.startsWith('/') || from.startsWith('//')) {
    return null
  }
  return from
}

/**
 * 将 from 字符串解析为 vue-router 可用的 location 对象。
 */
export const parseInternalRouteLocation = (rawFrom) => {
  const from = resolveInternalBackPath(rawFrom)
  if (!from) return null

  try {
    const url = new URL(from, 'http://local')
    const query = {}
    url.searchParams.forEach((value, key) => {
      query[key] = value
    })
    return {
      path: url.pathname,
      query
    }
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
 * 详情页返回：优先 replace 到 from，避免历史栈叠加引发反复跳转。
 */
export const navigateBackFromDetail = (router, route, fallback = '/explore/douban') => {
  const location = parseInternalRouteLocation(route.query?.from)
  if (location) {
    router.replace(location)
    return
  }
  if (window.history.length > 1) {
    router.back()
    return
  }
  router.replace(fallback)
}
