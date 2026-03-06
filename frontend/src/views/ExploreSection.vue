<template>
  <div class="explore-section-page" v-loading="loading">
    <div class="page-header">
      <el-button text @click="goBack">返回探索</el-button>
      <div class="title-wrap">
        <h2>{{ sectionMeta.title || '完整榜单' }}</h2>
        <el-tag size="small" type="info">{{ sectionMeta.tag || '' }}</el-tag>
        <span class="count">{{ formatExploreCount(remoteTotal) }} 部</span>
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

    <el-empty v-else-if="!loading" description="暂无榜单数据" />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { searchApi, subscriptionApi, pan115Api } from '@/api'

const SECTION_BATCH_CACHE_TTL_MS = 5 * 60 * 1000
const sectionBatchCache = new Map()
const sectionBatchInflight = new Map()
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
const loadingMore = ref(false)
const allItems = ref([])
const displayCount = ref(0)
const loadAnchorRef = ref(null)
const remoteTotal = ref(0)
const nextOffset = ref(0)
const fetchedOnce = ref(false)
const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w500'
const PRIORITY_POSTER_COUNT = 8
const API_BATCH_SIZE = 30
const RENDER_BATCH_SIZE = EXPLORE_SPEED_MODE === 'extreme' ? 30 : 24
const PREFETCH_BUFFER_SIZE = EXPLORE_SPEED_MODE === 'extreme' ? 96 : 48
const PREFETCH_ROUNDS = EXPLORE_SPEED_MODE === 'extreme' ? 5 : 3
const PREFETCH_DELAY_MS = EXPLORE_SPEED_MODE === 'extreme' ? 0 : 24
const PREFETCH_ROOT_MARGIN = EXPLORE_SPEED_MODE === 'extreme' ? '1800px 0px' : '1000px 0px'
let loadObserver = null
let prefetchTimer = null
let batchLoadPromise = null
const subscribedIdMap = ref(new Map())

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

const applySubscribedFlag = (item) => {
  if (!item || typeof item !== 'object') return
  const key = buildSubscribedKey(item.media_type, item.tmdb_id)
  item.isSubscribed = Boolean(key) && subscribedIdMap.value.has(key)
}

const applySubscribedFlags = () => {
  for (const item of allItems.value) {
    applySubscribedFlag(item)
  }
}

const refreshSubscribedMap = async () => {
  try {
    const { data } = await subscriptionApi.listForStatus()
    const nextMap = new Map()
    for (const sub of Array.isArray(data) ? data : []) {
      const key = buildSubscribedKey(sub.media_type, sub.tmdb_id)
      const id = Number(sub.id || 0)
      if (key && id > 0) nextMap.set(key, id)
    }
    subscribedIdMap.value = nextMap
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

const clearPrefetchTimer = () => {
  if (prefetchTimer) {
    clearTimeout(prefetchTimer)
    prefetchTimer = null
  }
}

const buildBatchCacheKey = (sectionKey, start, count) => `${sectionKey}:${start}:${count}`

const getCachedBatchPayload = (sectionKey, start, count) => {
  const cacheKey = buildBatchCacheKey(sectionKey, start, count)
  const cached = sectionBatchCache.get(cacheKey)
  if (!cached) return null
  if (Date.now() >= cached.expiresAt) {
    sectionBatchCache.delete(cacheKey)
    return null
  }
  return cached.payload
}

const setCachedBatchPayload = (sectionKey, start, count, payload) => {
  const cacheKey = buildBatchCacheKey(sectionKey, start, count)
  sectionBatchCache.set(cacheKey, {
    payload,
    expiresAt: Date.now() + SECTION_BATCH_CACHE_TTL_MS
  })
}

const requestSectionBatch = async (sectionKey, start, { refresh = false } = {}) => {
  const count = API_BATCH_SIZE
  const cacheKey = buildBatchCacheKey(sectionKey, start, count)
  if (!refresh) {
    const cachedPayload = getCachedBatchPayload(sectionKey, start, count)
    if (cachedPayload) return cachedPayload
  }

  const inflight = sectionBatchInflight.get(cacheKey)
  if (inflight) return inflight

  const task = searchApi.getExploreSection(exploreSource.value, sectionKey, count, refresh, start)
    .then(({ data }) => {
      const payload = data.section || {}
      setCachedBatchPayload(sectionKey, start, count, payload)
      return payload
    })
    .finally(() => {
      sectionBatchInflight.delete(cacheKey)
    })

  sectionBatchInflight.set(cacheKey, task)
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
  const targetSegment = compact ? '/t/p/w342/' : '/t/p/w500/'
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

const extractPan115ShareLink = (resource) => {
  return String(resource?.share_link || resource?.share_url || '').trim()
}

const buildMediaFolderName = (title, year) => {
  const safeTitle = String(title || '').trim() || '未命名资源'
  const safeYear = String(year || '').trim()
  return safeYear ? `${safeTitle} (${safeYear})` : safeTitle
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

const getDefaultTransferFolderId = async () => {
  try {
    const { data } = await pan115Api.getDefaultFolder()
    return data.folder_id || '0'
  } catch {
    return '0'
  }
}

const fetchPan115ShareCandidates = async (mediaType, tmdbId) => {
  const primaryResp = mediaType === 'tv'
    ? await searchApi.getTvPan115(tmdbId)
    : await searchApi.getMoviePan115(tmdbId)
  const primaryList = Array.isArray(primaryResp.data?.list) ? primaryResp.data.list : []
  if (primaryList.some((row) => extractPan115ShareLink(row))) {
    return primaryList
  }

  const pansouResp = mediaType === 'tv'
    ? await searchApi.getTvPan115Pansou(tmdbId)
    : await searchApi.getMoviePan115Pansou(tmdbId)
  const pansouList = Array.isArray(pansouResp.data?.list) ? pansouResp.data.list : []
  return primaryList.concat(pansouList)
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
  if (!item || item.subscribing) return

  const routeInfo = await resolveItemRoute(item)
  if (!routeInfo?.tmdbId || (routeInfo.mediaType !== 'movie' && routeInfo.mediaType !== 'tv')) {
    if (exploreSource.value === 'douban' && goToDoubanDetail(item)) {
      ElMessage.info('已跳转豆瓣详情，可在详情页继续匹配 TMDB 后订阅')
      return
    }
    ElMessage.warning(getResolveFailureMessage(routeInfo?.reason))
    return
  }

  item.subscribing = true
  try {
    const subscribedKey = buildSubscribedKey(routeInfo.mediaType, routeInfo.tmdbId)
    if (item.isSubscribed) {
      let existingId = subscribedKey ? subscribedIdMap.value.get(subscribedKey) : null
      if (!existingId) {
        await refreshSubscribedMap()
        existingId = subscribedKey ? subscribedIdMap.value.get(subscribedKey) : null
      }
      if (!existingId) {
        ElMessage.warning('未找到订阅记录，请刷新后重试')
        return
      }
      await subscriptionApi.delete(existingId)
      if (subscribedKey) subscribedIdMap.value.delete(subscribedKey)
      item.isSubscribed = false
      ElMessage.success('已取消订阅')
      return
    }

    const title = item.title || ''
    const year = item.year || ''
    const subscriptionData = {
      tmdb_id: routeInfo.tmdbId,
      title,
      media_type: routeInfo.mediaType,
      poster_path: item.poster_path || item.poster_url || '',
      overview: item.intro || '',
      year,
      rating: item.rating || item.vote_average || null
    }

    try {
      const { data } = await subscriptionApi.create(subscriptionData)
      item.isSubscribed = true
      const createdId = Number(data?.id || 0)
      if (subscribedKey && createdId > 0) subscribedIdMap.value.set(subscribedKey, createdId)
      ElMessage.success('订阅成功')
    } catch (error) {
      if (error.response?.status === 400) {
        await refreshSubscribedMap()
        item.isSubscribed = Boolean(subscribedKey && subscribedIdMap.value.has(subscribedKey))
        ElMessage.info(item.isSubscribed ? '该影视已在订阅列表中' : '订阅状态已更新，请重试')
      } else {
        throw error
      }
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '订阅失败')
  } finally {
    item.subscribing = false
  }
}

const handleExploreSave = async (item) => {
  if (!item || item.saving) return

  const routeInfo = await resolveItemRoute(item)
  if (!routeInfo?.tmdbId || (routeInfo.mediaType !== 'movie' && routeInfo.mediaType !== 'tv')) {
    if (exploreSource.value === 'douban' && goToDoubanDetail(item)) {
      ElMessage.info(withTitleHint(item, '已跳转豆瓣详情，可直接使用豆瓣关键词 115 转存'))
      return
    }
    ElMessage.warning(withTitleHint(item, getResolveFailureMessage(routeInfo?.reason)))
    return
  }

  item.saving = true
  try {
    const title = item.title || ''
    const year = item.year || ''
    const candidates = await fetchPan115ShareCandidates(routeInfo.mediaType, routeInfo.tmdbId)
    const targetResource = candidates.find((row) => extractPan115ShareLink(row))
    if (!targetResource) {
      ElMessage.warning(withTitleHint(item, '暂未找到可转存资源'))
      return
    }

    const folderId = await getDefaultTransferFolderId()
    const shareLink = extractPan115ShareLink(targetResource)
    const folderName = buildMediaFolderName(title, year)
    const { data } = await pan115Api.saveShareToFolder(
      shareLink,
      folderName,
      folderId,
      '',
      routeInfo.mediaType === 'tv' ? routeInfo.tmdbId : null
    )
    const transferSuccess = data?.success === true
      || data?.state === true
      || data?.result?.success === true
      || data?.result?.state === true
    if (!transferSuccess) {
      throw new Error(data?.message || data?.error || data?.result?.error || '转存失败')
    }

    markExploreItemSaved(item)
    ElMessage.success(withTitleHint(item, '已提交转存任务'))
  } catch (error) {
    const reason = error.response?.data?.detail || error.message || '转存失败'
    ElMessage.error(withTitleHint(item, `转存失败：${reason}`))
  } finally {
    item.saving = false
  }
}

const markExploreItemSaved = (item) => {
  if (!item) return
  item.justSaved = true
  window.setTimeout(() => {
    item.justSaved = false
  }, 1500)
}

const disconnectLoadObserver = () => {
  if (loadObserver) {
    loadObserver.disconnect()
    loadObserver = null
  }
}

const resetSectionState = () => {
  allItems.value = []
  displayCount.value = 0
  remoteTotal.value = 0
  nextOffset.value = 0
  fetchedOnce.value = false
  loadingMore.value = false
  sectionMeta.key = ''
  sectionMeta.title = ''
  sectionMeta.tag = ''
  sectionMeta.source_url = ''
  sectionMeta.fetched_at = ''
  clearPrefetchTimer()
  disconnectLoadObserver()
}

const appendUniqueItems = (items) => {
  if (!Array.isArray(items) || !items.length) return 0
  const exists = new Set(allItems.value.map((item) => `${item.id}|${item.rank}|${item.title}`))
  const nextItems = []
  for (const item of items) {
    const normalizedTmdbId = toValidTmdbId(item.tmdb_id)
    const mediaType = item.media_type === 'tv' ? 'tv' : 'movie'
    const subscribedKey = buildSubscribedKey(mediaType, normalizedTmdbId)
    const normalizedItem = {
      ...item,
      tmdb_id: normalizedTmdbId,
      media_type: mediaType,
      isSubscribed: Boolean(subscribedKey) && subscribedIdMap.value.has(subscribedKey),
      subscribing: false,
      saving: false,
      justSaved: false
    }
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

  if (!batchLoadPromise) {
    const requestStart = nextOffset.value
    batchLoadPromise = (async () => {
      const payload = await requestSectionBatch(sectionKey, requestStart, { refresh })
      const batchItems = Array.isArray(payload.items) ? payload.items : []
      const payloadTotal = Number(payload.total) || 0
      const payloadStart = Number(payload.start ?? requestStart) || 0
      const payloadCount = Number(payload.count) || batchItems.length

      sectionMeta.key = payload.key || sectionKey
      sectionMeta.title = payload.title || sectionMeta.title
      sectionMeta.tag = payload.tag || sectionMeta.tag
      sectionMeta.source_url = payload.source_url || sectionMeta.source_url
      sectionMeta.fetched_at = payload.fetched_at || sectionMeta.fetched_at
      if (payloadTotal > 0) {
        remoteTotal.value = payloadTotal
      } else if (batchItems.length >= API_BATCH_SIZE) {
        remoteTotal.value = Math.max(remoteTotal.value, payloadStart + batchItems.length + 1)
      } else {
        remoteTotal.value = Math.max(remoteTotal.value, payloadStart + batchItems.length)
      }
      nextOffset.value = Math.max(nextOffset.value, payloadStart + payloadCount)

      fetchedOnce.value = true
      return appendUniqueItems(batchItems)
    })().finally(() => {
      batchLoadPromise = null
    })
  }

  if (!silent) loadingMore.value = true
  try {
    return await batchLoadPromise
  } finally {
    if (!silent) loadingMore.value = false
  }
}

const ensurePrefetchBuffer = async () => {
  if (loading.value) return
  if (!hasMoreRemote.value) return

  // Aggressively prefetch a few batches to keep buffer filled ahead of the viewport.
  for (let i = 0; i < PREFETCH_ROUNDS; i += 1) {
    const hiddenCount = allItems.value.length - displayCount.value
    if (!hasMoreRemote.value || hiddenCount >= PREFETCH_BUFFER_SIZE) break
    const appended = await fetchNextBatch({ silent: true })
    if (appended <= 0) break
  }
}

const schedulePrefetch = () => {
  if (prefetchTimer) return
  prefetchTimer = setTimeout(async () => {
    prefetchTimer = null
    await ensurePrefetchBuffer()
  }, PREFETCH_DELAY_MS)
}

const loadMoreData = async () => {
  if (loading.value || loadingMore.value) return
  if (revealNextCards()) {
    schedulePrefetch()
    return
  }
  if (!hasMoreRemote.value && fetchedOnce.value) return

  const appended = await fetchNextBatch()
  if (appended > 0 && !hasHiddenLocal.value) {
    displayCount.value = Math.min(displayCount.value + RENDER_BATCH_SIZE, allItems.value.length)
  } else if (displayCount.value === 0) {
    displayCount.value = Math.min(RENDER_BATCH_SIZE, allItems.value.length)
  }
  schedulePrefetch()
}

const setupLoadObserver = () => {
  disconnectLoadObserver()
  if (typeof IntersectionObserver === 'undefined') return
  if (!loadAnchorRef.value || !hasMoreItems.value) return

  loadObserver = new IntersectionObserver((entries) => {
    if (!entries.some((entry) => entry.isIntersecting)) return
    loadMoreData()
  }, {
    root: null,
    rootMargin: PREFETCH_ROOT_MARGIN,
    threshold: 0.01
  })

  loadObserver.observe(loadAnchorRef.value)
}

const fetchSection = async () => {
  const sectionKey = route.params.key
  if (!sectionKey) return
  loading.value = true
  resetSectionState()
  try {
    await refreshSubscribedMap()
    const appended = await fetchNextBatch({ refresh: false })
    if (appended > 0) {
      displayCount.value = Math.min(RENDER_BATCH_SIZE, allItems.value.length)
    }
    schedulePrefetch()
    await nextTick()
    setupLoadObserver()
  } catch (error) {
    resetSectionState()
    ElMessage.error(error.response?.data?.detail || '获取榜单失败')
  } finally {
    loading.value = false
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
})

watch(loadAnchorRef, () => {
  setupLoadObserver()
})

onMounted(() => {
  fetchSection()
})

onBeforeUnmount(() => {
  clearPrefetchTimer()
  disconnectLoadObserver()
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
