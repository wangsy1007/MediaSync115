<template>
  <div class="explore-section-page">
    <div class="page-header">
      <el-button text @click="goBack">返回探索</el-button>
      <div class="title-wrap">
        <h2>{{ sectionMeta.title || '完整榜单' }}</h2>
        <el-tag size="small" type="info">{{ sectionMeta.tag || '' }}</el-tag>
        <span class="count">{{ formatExploreCount(remoteTotal) }} 部</span>
      </div>
    </div>

    <div v-if="loading && !visibleItems.length" class="skeleton-grid">
      <div v-for="n in 12" :key="`skeleton-${n}`" class="skeleton-card">
        <div class="skeleton-poster" />
        <div class="skeleton-title" />
      </div>
    </div>

    <div class="cards-grid" v-if="visibleItems.length">
      <el-card
        v-for="(item, itemIndex) in visibleItems"
        :key="`${item.id}-${item.rank}`"
        class="movie-card"
        :class="{ 'just-saved': item.justSaved }"
        shadow="hover"
        :body-style="{ padding: '0' }"
        @click="handleItemClick(item)"
      >
        <div class="poster-wrap">
          <img
            :src="getPosterUrl(item.poster_url || item.poster_path, { compact: itemIndex >= PRIORITY_POSTER_COUNT })"
            :alt="item.title"
            :loading="itemIndex < PRIORITY_POSTER_COUNT ? 'eager' : 'lazy'"
            :fetchpriority="itemIndex < PRIORITY_POSTER_COUNT ? 'high' : 'auto'"
            decoding="async"
            draggable="false"
            @error="handleImageError"
          />
          <div class="rank">#{{ item.rank }}</div>
          <div v-if="getExploreItemRating(item)" class="rating-badge">
            {{ formatExploreItemRating(item) }}
          </div>
          <LibraryBadge
            v-if="item.isInMediaLibrary"
            class="emby-badge"
            :in-emby="item.isInEmby"
            :in-feiniu="item.isInFeiniu"
          />
          <div class="explore-card-actions">
            <el-button
              class="explore-action-btn"
              :type="item.isSubscribed ? 'success' : 'primary'"
              circle
              :title="item.isSubscribed ? '取消订阅' : '订阅'"
              :loading="item.subscribing"
              @pointerdown.stop
              @click.stop="handleExploreSubscribe(item)"
              >
              <el-icon><Star /></el-icon>
            </el-button>
            <el-button
              class="explore-action-btn"
              type="warning"
              circle
              title="转存"
              :loading="item.saving"
              @pointerdown.stop
              @click.stop="handleExploreSave(item)"
            >
              <el-icon><FolderAdd /></el-icon>
            </el-button>
          </div>
        </div>
        <div class="card-info">
          <h4>{{ item.title }}</h4>
        </div>
      </el-card>
    </div>

    <div
      v-if="visibleItems.length"
      ref="loadAnchorRef"
      class="load-anchor"
      :class="{ done: !hasMoreItems }"
    >
      <span v-if="loadingMore">正在抓取下一批...</span>
      <span v-else-if="hasMoreItems">下滑继续加载</span>
      <span v-else>已显示全部内容</span>
    </div>

    <TmdbSetupPrompt
      v-else-if="exploreSource === 'tmdb' && tmdbConfigured === false"
      @configured="handleTmdbConfigured"
    />

    <el-empty v-else-if="!loading" description="暂无榜单数据" />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { searchApi, subscriptionApi } from '@/api'
import { Star, FolderAdd } from '@element-plus/icons-vue'
import LibraryBadge from '@/components/media/LibraryBadge.vue'
import TmdbSetupPrompt from '@/components/explore/TmdbSetupPrompt.vue'

defineOptions({ name: 'ExploreSection' })
import {
  getCachedExploreSectionBatch,
  getExploreSectionBatchInflight,
  setCachedExploreSectionBatch,
  setExploreSectionBatchInflight
} from '@/utils/exploreSectionBatchCache'
import { createExploreLibraryBadgeSyncer } from '@/utils/exploreLibraryBadgeSync'
const resolveExploreSpeedMode = () => {
  if (typeof window === 'undefined') return 'extreme'
  try {
    const saved = window.localStorage.getItem('explore_speed_mode')
    if (saved === 'extreme' || saved === 'balanced') return saved
  } catch {
    // ignore storage access failures
  }
  const effectiveType = window.navigator?.connection?.effectiveType || ''
  return effectiveType.includes('2g') ? 'balanced' : 'extreme'
}
const EXPLORE_SPEED_MODE = resolveExploreSpeedMode()

const route = useRoute()
const router = useRouter()
const normalizeExploreSource = (rawSource) => (String(rawSource || '').toLowerCase() === 'tmdb' ? 'tmdb' : 'douban')
const exploreSource = computed(() => normalizeExploreSource(route.params.source))

const loading = ref(false)
const tmdbConfigured = ref(true)
const loadingMore = ref(false)
const allItems = ref([])
const displayCount = ref(0)
const loadAnchorRef = ref(null)
const remoteTotal = ref(0)
const nextOffset = ref(0)
const fetchedOnce = ref(false)
const isLoadAnchorIntersecting = ref(false)
const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w342'
const PRIORITY_POSTER_COUNT = 8
const API_BATCH_SIZE = 30
const RENDER_BATCH_SIZE = EXPLORE_SPEED_MODE === 'extreme' ? 30 : 24
const PREFETCH_BATCH_WINDOW = EXPLORE_SPEED_MODE === 'extreme' ? 4 : 3
const PREFETCH_CONCURRENCY = EXPLORE_SPEED_MODE === 'extreme' ? 3 : 2
const PREFETCH_DELAY_MS = EXPLORE_SPEED_MODE === 'extreme' ? 0 : 16
/** 触底加载哨兵：尽早触发下一轮请求（略大于 prefetch 占位逻辑） */
const LOAD_ANCHOR_ROOT_MARGIN = EXPLORE_SPEED_MODE === 'extreme'
  ? '3000px 0px'
  : '1600px 0px'
let loadObserver = null
let prefetchTimer = null
let prefetchCursor = 0
let autoLoadScheduled = false
const prefetchedOffsets = new Set()
const prefetchOffsetsInFlight = new Set()
let activeSectionToken = 0
const subscribedIdMap = ref(new Map())
const subscribedDoubanIds = ref(new Set()) // 存储豆瓣ID订阅集合
const subscribedImdbIds = ref(new Set()) // 存储IMDB ID订阅集合
const embyStatusMap = ref(new Map())
const feiniuStatusMap = ref(new Map())
let libraryBadgeSyncer = null
const EXPLORE_QUEUE_POLL_INTERVAL_MS = 1800
const queueActiveSaveKeys = ref(new Set())
let exploreQueuePollTimer = null
let exploreQueuePolling = false

const toValidTmdbId = (rawId) => {
  const id = Number(rawId)
  if (!Number.isFinite(id) || id <= 0) return null
  return Math.trunc(id)
}

const buildSubscribedKey = (mediaType, tmdbId) => {
  const type = mediaType === 'tv' ? 'tv' : (mediaType === 'movie' ? 'movie' : '')
  const id = toValidTmdbId(tmdbId)
  if (!type || !id) return ''
  return `${type}:${id}`
}

const markEmbyOnItem = (item) => {
  if (!item || typeof item !== 'object') return
  const key = buildSubscribedKey(item.media_type, item.tmdb_id)
  const inEmby = Boolean(key) && Boolean(embyStatusMap.value.get(key)?.exists_in_emby)
  const inFeiniu = Boolean(key) && Boolean(feiniuStatusMap.value.get(key)?.exists_in_feiniu)
  item.isInEmby = inEmby
  item.isInFeiniu = inFeiniu
  item.isInMediaLibrary = inEmby || inFeiniu
}

const applySubscribedFlag = (item) => {
  if (!item || typeof item !== 'object') return
  const key = buildSubscribedKey(item.media_type, item.tmdb_id)
  const doubanId = item.douban_id || item.id
  const imdbId = item.imdb_id
  const isConfirmedSubscribed = (Boolean(key) && subscribedIdMap.value.has(key)) ||
                       (doubanId && subscribedDoubanIds.value.has(String(doubanId))) ||
                       (imdbId && subscribedImdbIds.value.has(String(imdbId).toLowerCase()))
  item.isSubscribed = isConfirmedSubscribed
  item.subscribing = false
  markEmbyOnItem(item)
}

const applySubscribedFlags = () => {
  for (const item of allItems.value) {
    applySubscribedFlag(item)
  }
}

/** 仅更新本次状态映射涉及的 TMDB key，避免长列表滚动时全表遍历 */
const applySubscribedFlagsForTmdbKeys = (tmdbKeys) => {
  if (!tmdbKeys || !tmdbKeys.size) return
  for (const item of allItems.value) {
    const key = buildSubscribedKey(item.media_type, item.tmdb_id)
    if (key && tmdbKeys.has(key)) applySubscribedFlag(item)
  }
}

const mergeEmbyStatusMap = (rawMap = {}) => {
  if (!rawMap || typeof rawMap !== 'object') return
  const entries = Object.entries(rawMap)
  if (!entries.length) return
  const touched = new Set()
  const nextMap = new Map(embyStatusMap.value)
  for (const [key, value] of entries) {
    nextMap.set(key, value || {})
    touched.add(key)
  }
  embyStatusMap.value = nextMap
  applySubscribedFlagsForTmdbKeys(touched)
}

const mergeFeiniuStatusMap = (rawMap = {}) => {
  if (!rawMap || typeof rawMap !== 'object') return
  const entries = Object.entries(rawMap)
  if (!entries.length) return
  const touched = new Set()
  const nextMap = new Map(feiniuStatusMap.value)
  for (const [key, value] of entries) {
    nextMap.set(key, value || {})
    touched.add(key)
  }
  feiniuStatusMap.value = nextMap
  applySubscribedFlagsForTmdbKeys(touched)
}

libraryBadgeSyncer = createExploreLibraryBadgeSyncer({
  getEmbyStatusMap: () => embyStatusMap.value,
  getFeiniuStatusMap: () => feiniuStatusMap.value,
  mergeEmbyStatusMap,
  mergeFeiniuStatusMap
})

const normalizeExploreQueueMediaType = (rawType) => {
  return String(rawType || '').toLowerCase() === 'tv' ? 'tv' : 'movie'
}

const buildExploreQueueItemKeyFromItem = (item) => {
  const mediaType = normalizeExploreQueueMediaType(item?.media_type)
  const tmdbId = toValidTmdbId(item?.tmdb_id)
  if (tmdbId) return `tmdb:${mediaType}:${tmdbId}`
  const doubanId = String(item?.douban_id || item?.id || '').trim()
  if (doubanId) return `douban:${mediaType}:${doubanId}`
  return ''
}

const buildExploreQueueItemKeyFromTask = (task) => {
  const itemKey = String(task?.item_key || '').trim()
  if (itemKey) return itemKey
  const mediaType = normalizeExploreQueueMediaType(task?.media_type)
  const tmdbId = toValidTmdbId(task?.tmdb_id)
  if (tmdbId) return `tmdb:${mediaType}:${tmdbId}`
  const doubanId = String(task?.douban_id || '').trim()
  if (doubanId) return `douban:${mediaType}:${doubanId}`
  return ''
}

const buildExploreQueuePayload = (item) => {
  const mediaType = normalizeExploreQueueMediaType(item?.media_type)
  const tmdbId = toValidTmdbId(item?.tmdb_id)
  const idValue = item?.id === undefined || item?.id === null ? '' : String(item.id).trim()
  const doubanId = String(item?.douban_id || idValue || '').trim()
  return {
    source: exploreSource.value,
    id: idValue || null,
    douban_id: doubanId || null,
    title: String(item?.title || '').trim(),
    name: String(item?.name || item?.title || '').trim(),
    original_title: String(item?.original_title || '').trim(),
    original_name: String(item?.original_name || '').trim(),
    aliases: Array.isArray(item?.aliases) ? item.aliases : [],
    year: String(item?.year || '').trim(),
    media_type: mediaType,
    tmdb_id: tmdbId,
    poster_path: String(item?.poster_path || '').trim(),
    poster_url: String(item?.poster_url || '').trim(),
    overview: String(item?.overview || '').trim(),
    intro: String(item?.intro || '').trim(),
    rating: item?.rating ?? item?.vote_average ?? null,
    vote_average: item?.vote_average ?? item?.rating ?? null
  }
}

const syncExploreQueueItemStates = () => {
  for (const item of allItems.value) {
    const itemKey = buildExploreQueueItemKeyFromItem(item)
    item.saving = Boolean(itemKey) && queueActiveSaveKeys.value.has(itemKey)
  }
}

const applyExploreQueueTaskSnapshot = (tasks = []) => {
  const nextSave = new Set()
  for (const task of tasks) {
    if (!task || typeof task !== 'object') continue
    const itemKey = buildExploreQueueItemKeyFromTask(task)
    if (!itemKey) continue
    if (task.queue_type === 'save') {
      nextSave.add(itemKey)
    }
  }
  queueActiveSaveKeys.value = nextSave
  syncExploreQueueItemStates()
}

const markExploreQueueTaskActive = (task) => {
  if (!task || typeof task !== 'object') return
  const queueType = String(task.queue_type || '').trim().toLowerCase()
  const itemKey = buildExploreQueueItemKeyFromTask(task)
  if (!itemKey) return
  if (queueType === 'save') {
    queueActiveSaveKeys.value = new Set([...queueActiveSaveKeys.value, itemKey])
  }
  syncExploreQueueItemStates()
}

const fetchExploreQueueActiveTasks = async () => {
  if (exploreQueuePolling) return
  exploreQueuePolling = true
  try {
    const { data } = await searchApi.getExploreActiveQueueTasks('save')
    const tasks = Array.isArray(data?.tasks) ? data.tasks : []
    applyExploreQueueTaskSnapshot(tasks)
  } catch {
    // ignore queue polling errors
  } finally {
    exploreQueuePolling = false
  }
}

const stopExploreQueuePolling = () => {
  if (exploreQueuePollTimer) {
    clearInterval(exploreQueuePollTimer)
    exploreQueuePollTimer = null
  }
}

const startExploreQueuePolling = () => {
  stopExploreQueuePolling()
  fetchExploreQueueActiveTasks()
  exploreQueuePollTimer = window.setInterval(() => {
    fetchExploreQueueActiveTasks()
  }, EXPLORE_QUEUE_POLL_INTERVAL_MS)
}

const refreshSubscribedMap = async () => {
  try {
    const { data } = await subscriptionApi.listForStatus()

    // 处理新的返回格式：{ items: [], douban_id_map: {}, imdb_id_map: {} }
    const items = Array.isArray(data) ? data : (data.items || [])
    const doubanIdMap = data.douban_id_map || {}
    const imdbIdMap = data.imdb_id_map || {}

    const nextMap = new Map()
    const nextDoubanIds = new Set()
    const nextImdbIds = new Set()

    for (const sub of items) {
      const key = buildSubscribedKey(sub.media_type, sub.tmdb_id)
      const id = Number(sub.id || 0)
      if (key && id > 0) nextMap.set(key, id)
      // 同时收集 douban_id 和 imdb_id
      if (sub.douban_id) {
        nextDoubanIds.add(String(sub.douban_id))
      }
      if (sub.imdb_id) {
        nextImdbIds.add(String(sub.imdb_id).toLowerCase())
      }
    }

    // 从 douban_id_map 补充豆瓣ID
    for (const doubanId of Object.keys(doubanIdMap)) {
      nextDoubanIds.add(String(doubanId))
    }

    // 从 imdb_id_map 补充 IMDB ID
    for (const imdbId of Object.keys(imdbIdMap)) {
      nextImdbIds.add(String(imdbId).toLowerCase())
    }

    subscribedIdMap.value = nextMap
    subscribedDoubanIds.value = nextDoubanIds
    subscribedImdbIds.value = nextImdbIds
    applySubscribedFlags()
  } catch {
    // ignore subscription sync errors
  }
}

const sectionMeta = reactive({
  key: '',
  title: '',
  tag: '',
  source_url: '',
  fetched_at: ''
})

const visibleItems = computed(() => allItems.value.slice(0, displayCount.value))
const scheduleLibraryBadgeSync = (items) => {
  const target = Array.isArray(items) ? items : visibleItems.value
  libraryBadgeSyncer?.schedule(target)
}
const hasHiddenLocal = computed(() => displayCount.value < allItems.value.length)
const hasMoreRemote = computed(() => {
  if (remoteTotal.value <= 0) return false
  return allItems.value.length < remoteTotal.value
})
const hasMoreItems = computed(() => hasHiddenLocal.value || hasMoreRemote.value)

const formatExploreCount = (value) => {
  const total = Number(value) || 0
  if (total > 100) return '100+'
  return String(total)
}

const getExploreItemRating = (item) => {
  const rating = Number(item?.rating ?? item?.vote_average)
  if (!Number.isFinite(rating) || rating <= 0) return null
  return rating
}

const formatExploreItemRating = (item) => {
  const rating = getExploreItemRating(item)
  return rating ? rating.toFixed(1) : ''
}

const clearPrefetchTimer = () => {
  if (prefetchTimer) {
    clearTimeout(prefetchTimer)
    prefetchTimer = null
  }
}

const requestSectionBatch = async (sectionSource, sectionKey, start, { refresh = false } = {}) => {
  const count = API_BATCH_SIZE
  if (!refresh) {
    const cachedPayload = getCachedExploreSectionBatch(sectionSource, sectionKey, start, count)
    if (cachedPayload) return cachedPayload
  }

  const inflight = getExploreSectionBatchInflight(sectionSource, sectionKey, start, count)
  if (inflight) return inflight

  const task = searchApi.getExploreSection(sectionSource, sectionKey, count, refresh, start)
    .then(({ data }) => {
      const payload = {
        ...(data.section || {}),
        emby_status_map: data?.emby_status_map || {},
        feiniu_status_map: data?.feiniu_status_map || {}
      }
      setCachedExploreSectionBatch(sectionSource, sectionKey, start, count, payload)
      return payload
    })
    .finally(() => {
      setExploreSectionBatchInflight(sectionSource, sectionKey, start, count, null)
    })

  setExploreSectionBatchInflight(sectionSource, sectionKey, start, count, task)
  return task
}

const goBack = () => {
  router.push(`/explore/${exploreSource.value}`)
}

const goToDoubanDetail = (item) => {
  const doubanId = String(item?.douban_id || item?.id || '').trim()
  if (!doubanId) return false
  const mediaType = item?.media_type === 'tv' ? 'tv' : 'movie'
  router.push(`/douban/${mediaType}/${encodeURIComponent(doubanId)}`)
  return true
}

const rewriteTmdbPosterSize = (url, compact = false) => {
  const targetSegment = compact ? '/t/p/w185/' : '/t/p/w342/'
  return String(url).replace(/\/t\/p\/[^/]+\//, targetSegment)
}

const getPosterUrl = (path, options = {}) => {
  const compact = options.compact !== false
  if (!path) return new URL('/no-poster.png', import.meta.url).href
  const source = String(path).trim()
  const raw = source.startsWith('//') ? `https:${source}` : source
  if (raw.startsWith('http://') || raw.startsWith('https://')) {
    if (raw.includes('doubanio.com')) {
      const size = compact ? 'small' : 'medium'
      return `/api/search/explore/poster?url=${encodeURIComponent(raw)}&size=${size}`
    }
    if (raw.includes('image.tmdb.org')) {
      return rewriteTmdbPosterSize(raw, compact)
    }
    return raw
  }
  if (raw.startsWith('/')) return rewriteTmdbPosterSize(`${TMDB_IMAGE_BASE}${raw}`, compact)
  return new URL('/no-poster.png', import.meta.url).href
}

const handleImageError = (event) => {
  event.target.src = new URL('/no-poster.png', import.meta.url).href
}

const getExploreItemTitle = (item) => {
  const raw = String(item?.title || item?.name || '').trim()
  return raw || '该影视'
}

const withTitleHint = (item, message) => {
  return `《${getExploreItemTitle(item)}》${message}`
}

const getResolveFailureMessage = (reason) => {
  const normalizedReason = String(reason || '')
  if (normalizedReason === 'low_confidence_or_ambiguous') {
    return 'TMDB 匹配冲突，请换个条目或稍后重试'
  }
  if (normalizedReason === 'search_failed') {
    return '上游搜索失败，请稍后重试'
  }
  if (normalizedReason.startsWith('subject_cache_unresolved')) {
    return '缓存未命中，已尝试重新匹配，请稍后重试'
  }
  return '未能唯一匹配到 TMDB 详情，请稍后重试'
}

const resolveItemRoute = async (item) => {
  const directTmdbId = toValidTmdbId(item.tmdb_id)
  const directType = item.media_type === 'tv' ? 'tv' : 'movie'
  if (exploreSource.value === 'tmdb' && directTmdbId) {
    return { mediaType: directType, tmdbId: directTmdbId }
  }

  try {
    const payload = {
      source: exploreSource.value,
      id: item.id,
      douban_id: item.douban_id || item.id,
      title: item.title || '',
      year: item.year || '',
      media_type: directType,
      tmdb_id: exploreSource.value === 'tmdb' ? directTmdbId : null
    }
    let { data } = await searchApi.resolveExploreItem(payload)

    // Legacy backend may cache unresolved douban_id aggressively; retry once without douban_id.
    if (!data?.resolved && String(data?.reason || '').startsWith('subject_cache_unresolved')) {
      const retryPayload = {
        ...payload,
        id: '',
        douban_id: ''
      }
      const retryResponse = await searchApi.resolveExploreItem(retryPayload)
      data = retryResponse?.data || data
    }

    const resolvedTmdbId = toValidTmdbId(data?.tmdb_id)
    if (!data?.resolved || !resolvedTmdbId) {
      return {
        mediaType: data?.media_type === 'tv' ? 'tv' : directType,
        tmdbId: null,
        reason: String(data?.reason || 'low_confidence_or_ambiguous')
      }
    }
    const resolvedType = data.media_type === 'tv' ? 'tv' : 'movie'
    return { mediaType: resolvedType, tmdbId: resolvedTmdbId }
  } catch {
    return {
      mediaType: directType,
      tmdbId: null,
      reason: 'search_failed'
    }
  }
}

const warmupPan115 = (mediaType, tmdbId) => {
  if (!tmdbId) return
  if (mediaType === 'tv') {
    searchApi.getTvPan115(tmdbId).catch(() => {})
    return
  }
  searchApi.getMoviePan115(tmdbId).catch(() => {})
}

const handleItemClick = async (item) => {
  if (exploreSource.value === 'douban' && goToDoubanDetail(item)) {
    return
  }

  const routeInfo = await resolveItemRoute(item)
  if (!routeInfo?.tmdbId) {
    ElMessage.warning(getResolveFailureMessage(routeInfo?.reason))
    return
  }

  warmupPan115(routeInfo.mediaType, routeInfo.tmdbId)
  if (routeInfo.mediaType === 'tv') {
    router.push(`/tv/${routeInfo.tmdbId}`)
    return
  }
  router.push(`/movie/${routeInfo.tmdbId}`)
}

const handleExploreSubscribe = async (item) => {
  if (!item) return
  const mediaType = item.media_type === 'tv' ? 'tv' : 'movie'
  const tmdbId = toValidTmdbId(item.tmdb_id)
  const doubanId = String(item.douban_id || item.id || '').trim() || null
  if (!tmdbId && !doubanId) {
    ElMessage.warning(withTitleHint(item, '缺少可用条目标识，无法操作订阅'))
    return
  }

  item.subscribing = true
  try {
    const { data } = await subscriptionApi.toggle({
      tmdb_id: tmdbId,
      douban_id: doubanId,
      title: String(item.title || item.name || '').trim(),
      media_type: mediaType,
      poster_path: String(item.poster_path || item.poster_url || '').trim() || null,
      overview: String(item.overview || item.intro || '').trim() || null,
      year: String(item.year || '').trim() || null,
      rating: item.rating ?? item.vote_average ?? null
    })
    const message = String(data?.message || '').trim()
    if (data?.subscribed) {
      item.isSubscribed = true
      ElMessage.success(withTitleHint(item, message || '订阅成功'))
    } else {
      item.isSubscribed = false
      ElMessage.info(withTitleHint(item, message || '已取消订阅'))
    }
    await refreshSubscribedMap()
  } catch (error) {
    item.isSubscribed = !item.isSubscribed
    ElMessage.error(error.response?.data?.detail || error.message || '操作失败')
  } finally {
    item.subscribing = false
  }
}

const handleExploreSave = async (item) => {
  if (!item) return
  const payload = buildExploreQueuePayload(item)
  if (!payload.tmdb_id && !payload.douban_id && !payload.id) {
    ElMessage.warning(withTitleHint(item, '缺少可用条目标识，无法加入转存队列'))
    return
  }
  item.saving = true
  try {
    const { data } = await searchApi.enqueueExploreSaveTask(payload)
    markExploreQueueTaskActive(data)
    const message = String(data?.message || '').trim()
    if (message.includes('已在转存队列')) {
      ElMessage.info(withTitleHint(item, message))
    } else {
      ElMessage.success(withTitleHint(item, message || '已加入转存队列'))
    }
  } catch (error) {
    item.saving = false
    const reason = error.response?.data?.detail || error.message || '加入转存队列失败'
    ElMessage.error(withTitleHint(item, reason))
  }
}

const disconnectLoadObserver = () => {
  if (loadObserver) {
    loadObserver.disconnect()
    loadObserver = null
  }
}

const resetPrefetchState = () => {
  prefetchedOffsets.clear()
  prefetchOffsetsInFlight.clear()
  prefetchCursor = 0
}

const resetSectionState = () => {
  allItems.value = []
  displayCount.value = 0
  remoteTotal.value = 0
  nextOffset.value = 0
  fetchedOnce.value = false
  loadingMore.value = false
  embyStatusMap.value = new Map()
  sectionMeta.key = ''
  sectionMeta.title = ''
  sectionMeta.tag = ''
  sectionMeta.source_url = ''
  sectionMeta.fetched_at = ''
  isLoadAnchorIntersecting.value = false
  autoLoadScheduled = false
  resetPrefetchState()
  clearPrefetchTimer()
  disconnectLoadObserver()
}

const updateSectionMetaFromPayload = (payload, requestStart = 0) => {
  const batchItems = Array.isArray(payload?.items) ? payload.items : []
  const payloadTotal = Number(payload?.total) || 0
  const payloadStart = Number(payload?.start ?? requestStart) || 0
  const payloadCount = Number(payload?.count) || batchItems.length

  sectionMeta.key = payload?.key || sectionMeta.key
  sectionMeta.title = payload?.title || sectionMeta.title
  sectionMeta.tag = payload?.tag || sectionMeta.tag
  sectionMeta.source_url = payload?.source_url || sectionMeta.source_url
  sectionMeta.fetched_at = payload?.fetched_at || sectionMeta.fetched_at
  if (payloadTotal > 0) {
    remoteTotal.value = payloadTotal
  } else if (batchItems.length >= API_BATCH_SIZE) {
    remoteTotal.value = Math.max(remoteTotal.value, payloadStart + batchItems.length + 1)
  } else {
    remoteTotal.value = Math.max(remoteTotal.value, payloadStart + batchItems.length)
  }

  return {
    batchItems,
    payloadStart,
    payloadCount
  }
}

const appendUniqueItems = (items) => {
  if (!Array.isArray(items) || !items.length) return 0
  const exists = new Set(allItems.value.map((item) => `${item.id}|${item.rank}|${item.title}`))
  const nextItems = []
  for (const item of items) {
    const normalizedTmdbId = toValidTmdbId(item.tmdb_id)
    const mediaType = item.media_type === 'tv' ? 'tv' : 'movie'
    const normalizedItem = {
      ...item,
      tmdb_id: normalizedTmdbId,
      media_type: mediaType,
      isSubscribed: false,
      isInEmby: false,
      isInFeiniu: false,
      isInMediaLibrary: false,
      embyChecking: false,
      subscribing: false,
      saving: false,
      justSaved: false
    }
    applySubscribedFlag(normalizedItem)
    const itemKey = buildExploreQueueItemKeyFromItem(normalizedItem)
    normalizedItem.saving = Boolean(itemKey) && queueActiveSaveKeys.value.has(itemKey)
    const key = `${item.id}|${item.rank}|${item.title}`
    if (exists.has(key)) continue
    exists.add(key)
    nextItems.push(normalizedItem)
  }
  if (!nextItems.length) return 0
  allItems.value = [...allItems.value, ...nextItems]
  return nextItems.length
}

const revealNextCards = () => {
  if (!hasHiddenLocal.value) return false
  displayCount.value = Math.min(displayCount.value + RENDER_BATCH_SIZE, allItems.value.length)
  return true
}

const fetchNextBatch = async ({ refresh = false, silent = false } = {}) => {
  const sectionKey = route.params.key
  if (!sectionKey) return 0
  if (fetchedOnce.value && !hasMoreRemote.value) return 0
  const requestStart = nextOffset.value
  const sectionSource = exploreSource.value
  prefetchedOffsets.delete(requestStart)

  if (!silent) loadingMore.value = true
  try {
    const payload = await requestSectionBatch(sectionSource, sectionKey, requestStart, { refresh })
    prefetchedOffsets.delete(requestStart)
    mergeEmbyStatusMap(payload?.emby_status_map || {})
    mergeFeiniuStatusMap(payload?.feiniu_status_map || {})
    const { batchItems, payloadStart, payloadCount } = updateSectionMetaFromPayload(payload, requestStart)
    scheduleLibraryBadgeSync(batchItems)
    nextOffset.value = Math.max(nextOffset.value, payloadStart + payloadCount)
    prefetchCursor = Math.max(prefetchCursor, nextOffset.value)
    fetchedOnce.value = true
    return appendUniqueItems(batchItems)
  } finally {
    if (!silent) loadingMore.value = false
  }
}

const queuePrefetchBatch = (sectionSource, sectionKey, start, sectionToken) => {
  if (!sectionKey || start < 0) return
  if (prefetchedOffsets.has(start) || prefetchOffsetsInFlight.has(start)) return

  const cachedPayload = getCachedExploreSectionBatch(sectionSource, sectionKey, start, API_BATCH_SIZE)
  if (cachedPayload) {
    prefetchedOffsets.add(start)
    return
  }

  prefetchOffsetsInFlight.add(start)
  requestSectionBatch(sectionSource, sectionKey, start, { refresh: false })
    .then((payload) => {
      if (sectionToken !== activeSectionToken) return
      mergeEmbyStatusMap(payload?.emby_status_map || {})
      mergeFeiniuStatusMap(payload?.feiniu_status_map || {})
      const { batchItems } = updateSectionMetaFromPayload(payload, start)
      scheduleLibraryBadgeSync(batchItems)
      prefetchedOffsets.add(start)
    })
    .catch(() => {
      prefetchedOffsets.delete(start)
    })
    .finally(() => {
      prefetchOffsetsInFlight.delete(start)
      if (sectionToken === activeSectionToken) {
        schedulePrefetch()
      }
    })
}

const ensurePrefetchBuffer = async () => {
  if (loading.value) {
    schedulePrefetch()
    return
  }
  if (!hasMoreRemote.value) return
  const sectionKey = route.params.key
  const sectionSource = exploreSource.value
  if (!sectionKey) return

  prefetchCursor = Math.max(prefetchCursor, nextOffset.value)
  const sectionToken = activeSectionToken

  while (prefetchedOffsets.size + prefetchOffsetsInFlight.size < PREFETCH_BATCH_WINDOW) {
    if (prefetchOffsetsInFlight.size >= PREFETCH_CONCURRENCY) break
    if (remoteTotal.value > 0 && prefetchCursor >= remoteTotal.value) break
    const start = prefetchCursor
    prefetchCursor += API_BATCH_SIZE
    queuePrefetchBatch(sectionSource, sectionKey, start, sectionToken)
  }
}

const schedulePrefetch = () => {
  if (prefetchTimer) return
  prefetchTimer = setTimeout(async () => {
    prefetchTimer = null
    await ensurePrefetchBuffer()
  }, PREFETCH_DELAY_MS)
}

const scheduleAutoLoadMore = () => {
  if (autoLoadScheduled) return
  if (loading.value || loadingMore.value) return
  if (!isLoadAnchorIntersecting.value || !hasMoreItems.value) return

  autoLoadScheduled = true
  setTimeout(async () => {
    autoLoadScheduled = false
    if (loading.value || loadingMore.value) return
    if (!isLoadAnchorIntersecting.value || !hasMoreItems.value) return
    await loadMoreData()
  }, 0)
}

const loadMoreData = async () => {
  if (loading.value || loadingMore.value) return
  let progressed = false
  try {
    if (revealNextCards()) {
      progressed = true
      return
    }
    if (!hasMoreRemote.value && fetchedOnce.value) return

    const appended = await fetchNextBatch()
    // 远程追加后 allItems 变长但 displayCount 未变，hasHiddenLocal 恒为 true，必须直接展开否则会卡多轮 reveal
    if (appended > 0) {
      displayCount.value = allItems.value.length
      progressed = true
    } else if (displayCount.value === 0) {
      displayCount.value = Math.min(RENDER_BATCH_SIZE, allItems.value.length)
      progressed = displayCount.value > 0
    }
  } finally {
    schedulePrefetch()
    if (progressed) {
      scheduleAutoLoadMore()
    }
  }
}

const setupLoadObserver = () => {
  disconnectLoadObserver()
  if (typeof IntersectionObserver === 'undefined') return
  if (!loadAnchorRef.value || !hasMoreItems.value) return

  loadObserver = new IntersectionObserver((entries) => {
    const isIntersecting = entries.some((entry) => entry.isIntersecting)
    isLoadAnchorIntersecting.value = isIntersecting
    if (!isIntersecting) return
    loadMoreData()
  }, {
    root: null,
    rootMargin: LOAD_ANCHOR_ROOT_MARGIN,
    threshold: 0.01
  })

  loadObserver.observe(loadAnchorRef.value)
}

const checkTmdbConfigured = async () => {
  if (exploreSource.value !== 'tmdb') {
    tmdbConfigured.value = true
    return true
  }
  try {
    const { data } = await searchApi.getExploreMeta('tmdb')
    tmdbConfigured.value = data?.tmdb_configured !== false
  } catch {
    tmdbConfigured.value = true
  }
  return tmdbConfigured.value
}

const handleTmdbConfigured = async () => {
  tmdbConfigured.value = true
  await fetchSection()
}

const fetchSection = async () => {
  const sectionKey = route.params.key
  if (!sectionKey) return
  activeSectionToken += 1
  loading.value = true
  resetSectionState()
  try {
    const configured = await checkTmdbConfigured()
    if (!configured) {
      return
    }
    // 订阅状态后台刷新，不阻塞首屏
    refreshSubscribedMap()
    const appended = await fetchNextBatch({ refresh: false, silent: false })
    if (appended > 0) {
      displayCount.value = allItems.value.length
    }
    prefetchCursor = Math.max(prefetchCursor, nextOffset.value)
    schedulePrefetch()
    await nextTick()
    // 确保首批条目的角标状态被正确应用（emby/feiniu status map 已在 fetchNextBatch 中 merge）
    applySubscribedFlags()
    setupLoadObserver()
  } catch (error) {
    resetSectionState()
    ElMessage.error(error.response?.data?.detail || '获取榜单失败')
  } finally {
    loading.value = false
    schedulePrefetch()
  }
}

watch(() => route.params.key, () => {
  fetchSection()
})

watch(() => route.params.source, () => {
  fetchSection()
})

watch(() => hasMoreItems.value, async () => {
  await nextTick()
  setupLoadObserver()
})

watch(() => [displayCount.value, allItems.value.length, hasMoreRemote.value], () => {
  schedulePrefetch()
  scheduleAutoLoadMore()
  scheduleLibraryBadgeSync()
})

watch(visibleItems, (items) => {
  scheduleLibraryBadgeSync(items)
})

watch(loadAnchorRef, () => {
  if (!loadAnchorRef.value) {
    isLoadAnchorIntersecting.value = false
  }
  setupLoadObserver()
})

onMounted(() => {
  startExploreQueuePolling()
  fetchSection()
})

onBeforeUnmount(() => {
  stopExploreQueuePolling()
  clearPrefetchTimer()
  disconnectLoadObserver()
  libraryBadgeSyncer?.dispose()
})
</script>

<style scoped lang="scss">
.explore-section-page {
  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;

    .title-wrap {
      display: flex;
      align-items: center;
      gap: 8px;

      h2 {
        margin: 0;
      }

      .count {
        font-size: 12px;
        color: var(--ms-text-muted);
      }
    }
  }

  .skeleton-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 14px;

    .skeleton-card {
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid var(--ms-border-color);
      background: var(--ms-glass-bg);
    }

    .skeleton-poster {
      aspect-ratio: 2 / 3;
      background: linear-gradient(
        90deg,
        var(--ms-bg-elevated) 25%,
        var(--ms-bg-hover) 50%,
        var(--ms-bg-elevated) 75%
      );
      background-size: 300% 100%;
      animation: explore-skeleton-shimmer 1.2s ease-in-out infinite;
    }

    .skeleton-title {
      height: 14px;
      margin: 10px 12px 12px;
      border-radius: 6px;
      background: linear-gradient(
        90deg,
        var(--ms-bg-elevated) 25%,
        var(--ms-bg-hover) 50%,
        var(--ms-bg-elevated) 75%
      );
      background-size: 300% 100%;
      animation: explore-skeleton-shimmer 1.2s ease-in-out infinite;
    }
  }

  .cards-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 14px;
  }

  .movie-card {
    border-radius: 12px;
    cursor: pointer;
    border: 1px solid var(--ms-border-color);
    background: var(--ms-glass-bg);
    transition: transform 0.2s, box-shadow 0.2s;

    &:hover {
      transform: translateY(-4px);
      box-shadow: var(--ms-shadow-md);
    }

    &.just-saved {
      border-color: rgba(52, 199, 89, 0.78);
      box-shadow: 0 0 0 1px rgba(52, 199, 89, 0.6), 0 0 26px rgba(52, 199, 89, 0.35);
      animation: card-save-flash 1.5s ease;
    }

    .poster-wrap {
      position: relative;
      aspect-ratio: 2 / 3;
      background: var(--ms-bg-elevated);

      .emby-badge {
        position: absolute;
        right: 8px;
        bottom: 8px;
        z-index: 4;
      }

      .rating-badge {
        position: absolute;
        top: 8px;
        right: 8px;
        z-index: 4;
        display: flex;
        align-items: center;
        justify-content: center;
        min-width: 48px;
        height: 28px;
        padding: 0 10px;
        border: none;
        border-radius: 999px;
        background: rgba(14, 32, 54, 0.78);
        color: var(--ms-accent-warning);
        font-size: 13px;
        font-weight: 700;
        line-height: 1;
        box-shadow: 0 4px 12px rgba(4, 16, 30, 0.22);
        backdrop-filter: blur(6px);
      }

      img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }

      .explore-card-actions {
        position: absolute;
        left: 50%;
        bottom: 12px;
        transform: translate(-50%, 10px);
        display: flex;
        align-items: center;
        gap: 10px;
        z-index: 3;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.22s ease, transform 0.22s ease;

        .explore-action-btn {
          margin: 0;
          width: 38px;
          height: 38px;
          padding: 0;
          pointer-events: auto;
          box-shadow: 0 6px 18px rgba(0, 0, 0, 0.36);
        }
      }

      &:hover .explore-card-actions,
      &:focus-within .explore-card-actions {
        opacity: 1;
        transform: translate(-50%, 0);
      }

      .rank {
        position: absolute;
        top: 8px;
        left: 8px;
        padding: 3px 8px;
        border-radius: 999px;
        background: rgba(8, 20, 40, 0.7);
        color: var(--ms-accent-warning);
        font-size: 12px;
        font-weight: 700;
      }
    }

    .card-info {
      padding: 10px;

      h4 {
        margin: 0;
        color: var(--ms-text-primary);
        font-size: 14px;
        font-weight: 600;
        line-height: 1.35;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
    }
  }

  .load-anchor {
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 18px 0 8px;
    font-size: 13px;
    color: var(--ms-text-muted);
  }

  .load-anchor.done {
    color: var(--ms-text-muted);
  }
}

@keyframes card-save-flash {
  0% {
    box-shadow: 0 0 0 1px rgba(52, 199, 89, 0.8), 0 0 30px rgba(52, 199, 89, 0.42);
  }
  100% {
    box-shadow: 0 0 0 1px rgba(52, 199, 89, 0), 0 0 0 rgba(52, 199, 89, 0);
  }
}

@keyframes explore-skeleton-shimmer {
  0% {
    background-position: 100% 0;
  }
  100% {
    background-position: -100% 0;
  }
}

@media (max-width: 768px) {
  .explore-section-page .movie-card .poster-wrap .explore-card-actions {
    opacity: 1;
    transform: translate(-50%, 0);
  }

  .explore-section-page .movie-card .poster-wrap .explore-card-actions .explore-action-btn {
    width: 36px;
    height: 36px;
  }
}

@media (hover: none) {
  .explore-section-page .movie-card .poster-wrap .explore-card-actions {
    opacity: 1;
    transform: translate(-50%, 0);
  }
}
</style>
