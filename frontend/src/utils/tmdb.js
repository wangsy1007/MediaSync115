export const TMDB_DEFAULT_BASE_URL = 'https://api.themoviedb.org/3'
export const TMDB_DEFAULT_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p/w500'
export const TMDB_DEFAULT_LANGUAGE = 'zh-CN'
export const TMDB_DEFAULT_REGION = 'CN'
export const TMDB_API_KEY_MISSING_MESSAGE = 'TMDB API Key 未配置'

/** 根据运行时配置判断 TMDB API Key 是否已配置 */
export const isTmdbApiKeyConfigured = (runtime = {}) => {
  return Boolean(String(runtime?.tmdb_api_key || '').trim())
}
