const toValidTmdbId = (rawId) => {
  const id = Number(rawId)
  if (!Number.isFinite(id) || id <= 0) return null
  return Math.trunc(id)
}

const normalizeExploreQueueMediaType = (rawType) => {
  return String(rawType || '').toLowerCase() === 'tv' ? 'tv' : 'movie'
}

/**
 * 解析探索卡片上的真实豆瓣 subject ID。
 * 豆瓣 Frodo 条目会带 douban_id；备用热门榜单只有 tmdb_id，且 id === tmdb_id，
 * 绝不能把后者误当成豆瓣 ID 去打开 /douban/... 详情（否则会串台）。
 * 注意：前端 normalize 若用 item.id 回填 douban_id，也会把 TMDB ID 伪造成 douban_id，这里一并拦截。
 */
export const resolveDoubanExploreId = (item) => {
  const tmdbId = toValidTmdbId(item?.tmdb_id ?? item?.tmdbid)
  const explicit = String(item?.douban_id ?? '').trim()
  if (explicit) {
    if (tmdbId && String(tmdbId) === explicit) return ''
    return explicit
  }

  const rawId = item?.id === undefined || item?.id === null ? '' : String(item.id).trim()
  if (!rawId) return ''

  if (tmdbId && String(tmdbId) === rawId) {
    return ''
  }
  return rawId
}

const resolveItemYear = (item) => {
  const direct = String(item?.year || '').trim()
  if (direct) return direct.slice(0, 4)
  const date = String(item?.release_date || item?.first_air_date || item?.credit_date || '').trim()
  return date ? date.slice(0, 4) : ''
}

/**
 * 构建探索/转存队列 payload，严格区分 TMDB ID 与豆瓣 ID，避免误识别。
 */
export const buildExploreQueuePayload = (item, options = {}) => {
  const source = String(options.source || options.exploreSource || 'douban').trim().toLowerCase()
  const mediaType = normalizeExploreQueueMediaType(item?.media_type)
  const explicitTmdbId = toValidTmdbId(item?.tmdb_id ?? item?.tmdbid)
  const explicitDoubanId = String(item?.douban_id || '').trim()
  const rawId = item?.id === undefined || item?.id === null ? '' : String(item.id).trim()

  let tmdbId = explicitTmdbId
  let doubanId = explicitDoubanId

  if (source === 'tmdb') {
    if (!tmdbId) {
      tmdbId = toValidTmdbId(rawId)
    }
    doubanId = explicitDoubanId || ''
  } else if (source === 'maoyan') {
    tmdbId = explicitTmdbId
    doubanId = explicitDoubanId || ''
  } else {
    doubanId = resolveDoubanExploreId(item)
    // 豆瓣源不信任 item.id 作为 TMDB ID，仅使用显式 tmdb_id/tmdbid
    tmdbId = explicitTmdbId
  }

  return {
    source,
    id: source === 'douban'
      ? (doubanId || null)
      : source === 'maoyan'
        ? (String(item?.maoyan_id || rawId || '').trim() || null)
        : (tmdbId ? String(tmdbId) : (rawId || null)),
    douban_id: doubanId || null,
    title: String(item?.title || item?.name || '').trim(),
    name: String(item?.name || item?.title || '').trim(),
    original_title: String(item?.original_title || '').trim(),
    original_name: String(item?.original_name || '').trim(),
    aliases: Array.isArray(item?.aliases) ? item.aliases : [],
    year: resolveItemYear(item),
    media_type: mediaType,
    tmdb_id: tmdbId,
    poster_path: String(item?.poster_path || '').trim(),
    poster_url: String(item?.poster_url || '').trim(),
    overview: String(item?.overview || item?.intro || '').trim(),
    intro: String(item?.intro || '').trim(),
    rating: item?.rating ?? item?.vote_average ?? null,
    vote_average: item?.vote_average ?? item?.rating ?? null
  }
}

export const buildTmdbSavePayload = (item) => {
  return buildExploreQueuePayload(item, { source: 'tmdb' })
}
