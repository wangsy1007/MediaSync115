/** 探索榜单 section key → source 映射（与后端 TMDB/豆瓣/猫眼 section 定义对齐） */

const TMDB_SECTION_KEYS = new Set([
  'trending_all_week',
  'trending_movie_week',
  'trending_tv_week',
  'movie_popular',
  'movie_top_rated',
  'movie_now_playing',
  'movie_upcoming',
  'tv_popular',
  'tv_top_rated',
  'tv_on_the_air',
  'tv_airing_today',
  'discover_movie_score',
  'discover_tv_score'
])

const DOUBAN_SECTION_KEYS = new Set([
  'movie_hot',
  'movie_showing',
  'movie_latest',
  'movie_top250',
  'tv_hot',
  'tv_variety',
  'tv_domestic',
  'tv_american',
  'tv_animation'
])

const MAOYAN_SECTION_KEYS = new Set([
  'movie_on_show',
  'movie_coming',
  'box_office'
])

/** 根据 section key 推断数据源；未知 key 时默认 douban（兼容旧链接） */
export const resolveExploreSectionSource = (sectionKey, fallback = 'douban') => {
  const key = String(sectionKey || '').trim()
  if (!key) return fallback
  if (TMDB_SECTION_KEYS.has(key)) return 'tmdb'
  if (MAOYAN_SECTION_KEYS.has(key)) return 'maoyan'
  if (DOUBAN_SECTION_KEYS.has(key)) return 'douban'
  return fallback
}

/** 尝试从首页横滑/批量接口写入的分页缓存中读取首屏数据 */
export const findCachedExploreSectionFirstBatch = (source, sectionKey, getBatch) => {
  for (const count of [30, 24, 12]) {
    const payload = getBatch(source, sectionKey, 0, count)
    const items = Array.isArray(payload?.items) ? payload.items : []
    if (items.length) {
      return payload
    }
  }
  return null
}
