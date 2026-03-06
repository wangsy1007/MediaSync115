<template>
  <div class="explore-page">
    <div class="search-header">
      <el-input
        v-model="searchQuery"
        placeholder="搜索电影、电视剧、合集..."
        size="large"
        clearable
        @clear="handleBackToExplore"
        @keyup.enter="handleSearch"
      >
        <template #prepend>
          <el-button v-if="showBackToExploreButton" @click="handleBackToExplore">返回探索</el-button>
        </template>
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
          <template #append>
            <el-button type="primary" @click="handleSearch" :loading="loading">搜索</el-button>
          </template>
        </el-input>
      </div>

    <section
      v-show="!isSearchMode"
      ref="exploreContainerRef"
      class="explore-section"
      :style="{ '--recommend-card-width': `${cardWidth}px` }"
    >
      <div class="section-header">
        <div class="section-title">
          <h2>{{ exploreSourceLabel }}</h2>
          <el-tag type="warning" size="small">{{ exploreSourceTag }}</el-tag>
        </div>
        <p>榜单支持横向拖动浏览，按住卡片区域左右拖动即可完整查看。</p>
      </div>

      <div class="recommend-sections" v-loading="exploreLoading">
        <template v-if="exploreSections.length > 0">
          <div
            v-for="(section, sectionIndex) in exploreSections"
            :key="section.key"
            class="recommend-group"
          >
            <div class="group-header">
              <div class="group-title">
                <h3>{{ section.title }}</h3>
                <el-tag size="small" type="info">{{ section.tag }}</el-tag>
                <span class="group-sub">{{ formatExploreCount(section.total) }} 部</span>
              </div>
              <div class="group-actions">
                <el-button
                  type="primary"
                  link
                  size="small"
                  @click="goToSection(section.key)"
                >
                  更多
                </el-button>
              </div>
            </div>

            <div class="row-shell">
              <div
                class="edge-mask left"
                v-if="getSectionScrollState(section.key).hasLeft"
              />
              <div
                class="edge-mask right"
                v-if="getSectionScrollState(section.key).hasRight"
              />
              <el-button
                class="side-scroll-btn left"
                circle
                size="small"
                @click="scrollSection(section.key, -1)"
                @mousedown="startPressScroll(section.key, -1, $event)"
                @mouseup="stopPressScroll"
                @mouseleave="stopPressScroll"
                @touchstart.prevent="startPressScroll(section.key, -1, $event)"
                @touchend="stopPressScroll"
                @touchcancel="stopPressScroll"
                :disabled="!getSectionScrollState(section.key).hasLeft"
              >
                <el-icon><ArrowLeft /></el-icon>
              </el-button>
              <el-button
                class="side-scroll-btn right"
                circle
                size="small"
                @click="scrollSection(section.key, 1)"
                @mousedown="startPressScroll(section.key, 1, $event)"
                @mouseup="stopPressScroll"
                @mouseleave="stopPressScroll"
                @touchstart.prevent="startPressScroll(section.key, 1, $event)"
                @touchend="stopPressScroll"
                @touchcancel="stopPressScroll"
                :disabled="!getSectionScrollState(section.key).hasRight"
              >
                <el-icon><ArrowRight /></el-icon>
              </el-button>

              <div
                :ref="el => setSectionRowRef(section.key, el)"
                class="recommend-row"
                :class="{ dragging: dragState.active && dragState.sectionKey === section.key }"
                @scroll="handleSectionScroll(section.key)"
                @pointerdown="startDrag(section.key, $event)"
                @pointermove="onDrag($event)"
                @pointerup="endDrag"
                @pointercancel="endDrag"
                @pointerleave="endDrag"
                @dragstart.prevent
              >
                <el-card
                  v-for="(item, itemIndex) in section.displayItems"
                  :key="`${section.key}-${item.id}-${item.rank}`"
                  class="recommend-card"
                  :class="{ 'just-saved': item.justSaved }"
                  shadow="hover"
                  :body-style="{ padding: '0' }"
                  @click="handleExploreItemClick(item)"
                >
                  <div class="poster-wrapper">
                    <img
                      :src="getPosterUrl(item.poster_url || item.poster_path, { compact: !isPriorityExplorePoster(sectionIndex, itemIndex) })"
                      :alt="item.title"
                      :loading="isPriorityExplorePoster(sectionIndex, itemIndex) ? 'eager' : 'lazy'"
                      :fetchpriority="isPriorityExplorePoster(sectionIndex, itemIndex) ? 'high' : 'auto'"
                      decoding="async"
                      draggable="false"
                      @error="handleImageError"
                    />
                    <div class="rank-badge">#{{ item.rank }}</div>
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
                  <h4 class="title">{{ item.title }}</h4>
                </div>
                </el-card>
              </div>
            </div>
          </div>
        </template>

        <el-empty v-else-if="!exploreLoading" description="暂无影视推荐" />
      </div>
    </section>

    <section
      v-show="isSearchMode"
      class="search-results"
      v-loading="loading"
      element-loading-text="搜索中..."
    >
      <div class="results-header" v-if="searched">
        <h3>搜索结果</h3>
        <div class="results-meta">
          <el-tag size="small" type="info">{{ lastSearchKeyword }}</el-tag>
          <el-tag v-if="activeSearchService" size="small" type="success">
            {{ getServiceLabel(activeSearchService) }}
          </el-tag>
        </div>
      </div>

      <template v-if="loading && results.length === 0">
        <div class="results-skeleton-grid">
          <div
            v-for="n in 12"
            :key="`search-skeleton-${n}`"
            class="skeleton-card"
          >
            <div class="skeleton-poster" />
            <div class="skeleton-title" />
          </div>
        </div>
      </template>

      <template v-else-if="results.length > 0">
        <div class="results-grid">
          <el-card
            v-for="item in results"
            :key="`${item.source_service}-${item.id}`"
            class="media-card"
            :class="{ 'pansou-card': item.isPansouResult }"
            :body-style="{ padding: '0' }"
            shadow="hover"
            @click="handleItemClick(item)"
          >
            <div class="poster-wrapper">
              <img
                :src="getPosterUrl(item.poster_path)"
                :alt="item.name || item.title"
                loading="lazy"
                decoding="async"
                @error="handleImageError"
              />
              <div class="media-type-tag">
                <el-tag :type="getMediaTypeTag(item.media_type)" size="small">
                  {{ getMediaTypeLabel(item.media_type) }}
                </el-tag>
              </div>
              <div class="rating-badge" v-if="item.vote_average">
                {{ item.vote_average.toFixed(1) }}
              </div>
              <div class="action-buttons">
                <el-button
                  v-if="!item.isPansouResult"
                  class="action-btn subscribe-btn"
                  :type="item.isSubscribed ? 'success' : 'primary'"
                  size="small"
                  :loading="item.subscribing"
                  @click.stop="handleSubscribe(item)"
                >
                  <el-icon><Star /></el-icon>
                  {{ item.isSubscribed ? '已订阅(取消)' : '订阅' }}
                </el-button>
                <el-button
                  class="action-btn save-btn"
                  type="warning"
                  size="small"
                  :loading="item.saving"
                  :disabled="item.isPansouResult && !item.canSaveToPan115"
                  @click.stop="handleSave(item)"
                >
                  <el-icon><FolderAdd /></el-icon>
                  {{ item.isPansouResult ? '一键转存' : '转存' }}
                </el-button>
              </div>
            </div>
            <div class="media-info">
              <h3 class="title">{{ item.name || item.title }}</h3>
              <p class="year">
                <span>{{ getYear(item) || '-' }}</span>
                <el-tag size="small" type="info">{{ getServiceLabel(item.source_service) }}</el-tag>
              </p>
              <p class="overview" v-if="item.overview">{{ truncateText(item.overview, 80) }}</p>
            </div>
          </el-card>
        </div>

        <div class="pagination-wrapper" v-if="totalPages > 1">
          <el-pagination
            v-model:current-page="currentPage"
            :page-size="20"
            :total="totalPages * 20"
            layout="prev, pager, next"
            @current-change="handlePageChange"
          />
        </div>
      </template>

      <el-empty v-else-if="!loading && searched" description="没有找到相关内容" />
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { searchApi, subscriptionApi, pan115Api } from '@/api'

const router = useRouter()
const route = useRoute()

const normalizeExploreSource = (rawSource) => (String(rawSource || '').toLowerCase() === 'tmdb' ? 'tmdb' : 'douban')
const exploreSource = computed(() => normalizeExploreSource(route.params.source))
const exploreSourceLabel = computed(() => (exploreSource.value === 'tmdb' ? 'TMDB 榜单探索' : '豆瓣榜单探索'))
const exploreSourceTag = computed(() => (exploreSource.value === 'tmdb' ? 'TMDB' : 'Douban Frodo'))

const searchQuery = ref('')
const results = ref([])
const loading = ref(false)
const searched = ref(false)
const currentPage = ref(1)
const totalPages = ref(0)

const exploreLoading = ref(false)
const exploreSections = ref([])
const exploreContainerRef = ref(null)
const sectionRowRefs = ref({})
const sectionScrollStates = ref({})
const cardWidth = ref(188)
const dragState = ref({
  active: false,
  sectionKey: '',
  startX: 0,
  startScrollLeft: 0,
  pointerId: null,
  moved: false,
  movedDistance: 0
})
const lastDragAt = ref(0)
const homePrefetchPaused = ref(false)
const lastSearchKeyword = ref('')
const activeSearchService = ref('')
const isSearchMode = computed(() => searched.value && Boolean(lastSearchKeyword.value))
const showBackToExploreButton = computed(() => isSearchMode.value)

const nullbrCheckCache = ref({})

const getExplorePan115CheckTarget = (item) => {
  if (!item || typeof item !== 'object') return null
  const mediaType = item.media_type === 'tv'
    ? 'tv'
    : (item.media_type === 'movie' ? 'movie' : '')
  if (!mediaType) return null
  const tmdbId = Number(item.tmdb_id || 0)
  if (!Number.isFinite(tmdbId) || tmdbId <= 0) return null
  return {
    key: `${mediaType}:${tmdbId}`,
    mediaType,
    tmdbId
  }
}

const toValidTmdbId = (rawId) => {
  const id = Number(rawId)
  if (!Number.isFinite(id) || id <= 0) return null
  return Math.trunc(id)
}

const subscribedKeys = ref(new Set())
const subscribedIdMap = ref(new Map())

const buildSubscribedKey = (mediaType, tmdbId) => {
  const normalizedType = mediaType === 'tv' ? 'tv' : (mediaType === 'movie' ? 'movie' : '')
  const normalizedTmdbId = toValidTmdbId(tmdbId)
  if (!normalizedType || !normalizedTmdbId) return ''
  return `${normalizedType}:${normalizedTmdbId}`
}

const isSubscribedMedia = (mediaType, tmdbId) => {
  const key = buildSubscribedKey(mediaType, tmdbId)
  return Boolean(key) && subscribedKeys.value.has(key)
}

const markSubscribedOnItem = (item) => {
  if (!item || typeof item !== 'object') return
  const mediaType = item.media_type
  const tmdbId = toValidTmdbId(item.tmdb_id || item.tmdbid)
  item.isSubscribed = isSubscribedMedia(mediaType, tmdbId)
}

const applySubscribedFlags = () => {
  for (const item of results.value) {
    markSubscribedOnItem(item)
  }
  for (const section of exploreSections.value) {
    for (const item of section.items || []) {
      markSubscribedOnItem(item)
    }
  }
}

const refreshSubscribedKeys = async () => {
  try {
    const { data } = await subscriptionApi.listForStatus()
    const next = new Set()
    const nextMap = new Map()
    for (const sub of Array.isArray(data) ? data : []) {
      const key = buildSubscribedKey(sub.media_type, sub.tmdb_id)
      const id = Number(sub.id || 0)
      if (!key) continue
      next.add(key)
      if (id > 0) nextMap.set(key, id)
    }
    subscribedKeys.value = next
    subscribedIdMap.value = nextMap
    applySubscribedFlags()
  } catch (error) {
    console.error('Failed to refresh subscribed keys:', error)
  }
}

const goToDetail = (mediaType, tmdbId) => {
  if (!tmdbId) return
  const path = mediaType === 'tv' ? `/tv/${tmdbId}` : `/movie/${tmdbId}`
  router.push(path)
}

const goToDoubanDetail = (item) => {
  const doubanId = String(item?.douban_id || item?.id || '').trim()
  if (!doubanId) return false
  const mediaType = item?.media_type === 'tv' ? 'tv' : 'movie'
  router.push(`/douban/${mediaType}/${encodeURIComponent(doubanId)}`)
  return true
}

const hasNullbrResources = async (target) => {
  if (!target) return
  const cacheValue = nullbrCheckCache.value[target.key]
  if (cacheValue !== undefined) {
    return cacheValue
  }

  try {
    const response = target.mediaType === 'tv'
      ? await searchApi.getTvPan115(target.tmdbId)
      : await searchApi.getMoviePan115(target.tmdbId)
    const list = Array.isArray(response.data?.list) ? response.data.list : []
    nullbrCheckCache.value = {
      ...nullbrCheckCache.value,
      [target.key]: list.length > 0
    }
    return list.length > 0
  } catch (error) {
    console.error('Failed to detect nullbr resources:', error)
    return null
  }
}

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w500'
const CARD_GAP = 14
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
const HOME_SECTION_BATCH_SIZE = 30
const EXPLORE_HERO_POSTER_COUNT = 6
const HOME_SECTION_PREFETCH_ROUNDS = EXPLORE_SPEED_MODE === 'extreme' ? 3 : 1
const HOME_SECTION_PREFETCH_DELAY_MS = EXPLORE_SPEED_MODE === 'extreme' ? 12 : 36
const HOME_SECTION_CACHE_TTL_MS = 5 * 60 * 1000
const HOME_CARD_MIN_WIDTH = 150
const HOME_CARD_MAX_WIDTH = 210
const HOME_CARD_MIN_PER_VIEW = 2
const HOME_CARD_MAX_PER_VIEW = 9
let sectionResizeObserver = null
let pressScrollTimer = null
let scrollStateRafId = 0
const pendingScrollStateKeys = new Set()
const cardsPerViewRef = ref(4)
const homeSectionBatchCache = new Map()
const homeSectionBatchInflight = new Map()
const homeSectionMetaMap = new Map()
const homeSectionLoadPromises = new Map()
const homeSectionPrefetchTimers = new Map()

const calculateCardWidth = () => {
  const width = exploreContainerRef.value?.clientWidth || 0
  if (!width) return

  const estimated = Math.floor((width + CARD_GAP) / (HOME_CARD_MIN_WIDTH + CARD_GAP))
  const cardsPerView = Math.max(HOME_CARD_MIN_PER_VIEW, Math.min(HOME_CARD_MAX_PER_VIEW, estimated))
  cardsPerViewRef.value = cardsPerView

  const raw = Math.floor((width - CARD_GAP * (cardsPerView - 1)) / cardsPerView)
  cardWidth.value = Math.max(HOME_CARD_MIN_WIDTH, Math.min(HOME_CARD_MAX_WIDTH, raw))
}

const setSectionRowRef = (sectionKey, el) => {
  if (!el) return
  sectionRowRefs.value[sectionKey] = el
  scheduleHomeSectionPrefetch(sectionKey, true)
}

const getSectionRowEl = (sectionKey) => {
  return sectionRowRefs.value[sectionKey] || null
}

const getSectionScrollState = (sectionKey) => {
  return sectionScrollStates.value[sectionKey] || { hasLeft: false, hasRight: false }
}

const formatExploreCount = (value) => {
  const total = Number(value) || 0
  if (total > 100) return '100+'
  return String(total)
}

const updateSectionScrollState = (sectionKey) => {
  const row = getSectionRowEl(sectionKey)
  if (!row) return

  const maxScrollLeft = Math.max(row.scrollWidth - row.clientWidth, 0)
  const hasLeft = row.scrollLeft > 2
  const hasRight = row.scrollLeft < maxScrollLeft - 2

  const previous = sectionScrollStates.value[sectionKey]
  if (
    previous
    && previous.hasLeft === hasLeft
    && previous.hasRight === hasRight
  ) {
    return
  }
  sectionScrollStates.value[sectionKey] = { hasLeft, hasRight }
}

const queueSectionScrollStateUpdate = (sectionKey) => {
  pendingScrollStateKeys.add(sectionKey)
  if (scrollStateRafId) return
  scrollStateRafId = requestAnimationFrame(() => {
    scrollStateRafId = 0
    const keys = Array.from(pendingScrollStateKeys)
    pendingScrollStateKeys.clear()
    for (const key of keys) {
      updateSectionScrollState(key)
    }
  })
}

const getHomeBatchCacheKey = (sectionKey, start, count) => `${sectionKey}:${start}:${count}`

const getCachedHomeSectionBatch = (sectionKey, start, count) => {
  const cacheKey = getHomeBatchCacheKey(sectionKey, start, count)
  const cached = homeSectionBatchCache.get(cacheKey)
  if (!cached) return null
  if (Date.now() >= cached.expiresAt) {
    homeSectionBatchCache.delete(cacheKey)
    return null
  }
  return cached.payload
}

const setCachedHomeSectionBatch = (sectionKey, start, count, payload) => {
  const cacheKey = getHomeBatchCacheKey(sectionKey, start, count)
  homeSectionBatchCache.set(cacheKey, {
    payload,
    expiresAt: Date.now() + HOME_SECTION_CACHE_TTL_MS
  })
}

const getExploreSectionByKey = (sectionKey) => {
  return exploreSections.value.find((section) => section.key === sectionKey) || null
}

const normalizeExploreSectionItems = (items = [], rankStart = 1) => {
  return items.map((item, index) => ({
    ...item,
    id: item.id,
    douban_id: item.douban_id || item.id,
    media_type: item.media_type || 'movie',
    rank: item.rank || rankStart + index,
    isSubscribed: isSubscribedMedia(item.media_type || 'movie', item.tmdb_id),
    subscribing: false,
    saving: false,
    justSaved: false
  }))
}

const markExploreItemSaved = (item) => {
  if (!item) return
  item.justSaved = true
  window.setTimeout(() => {
    item.justSaved = false
  }, 1500)
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

const handleExploreSubscribe = async (item) => {
  if (!item || item.subscribing) return

  const routeInfo = await resolveExploreItemRoute(item)
  const mediaType = routeInfo?.media_type
  const tmdbId = toValidTmdbId(routeInfo?.tmdb_id)
  if (!tmdbId || (mediaType !== 'movie' && mediaType !== 'tv')) {
    if (exploreSource.value === 'douban' && goToDoubanDetail(item)) {
      ElMessage.info('已跳转豆瓣详情，可在详情页继续匹配 TMDB 后订阅')
      return
    }
    ElMessage.warning(getResolveFailureMessage(routeInfo?.reason))
    return
  }

  if (item.isSubscribed) {
    ElMessage.info('已订阅该影视')
    return
  }

  item.subscribing = true
  try {
    const title = item.title || item.name || ''
    const year = item.year || getYear(item)
    const subscribedKey = buildSubscribedKey(mediaType, tmdbId)
    if (item.isSubscribed) {
      let subscriptionId = subscribedKey ? subscribedIdMap.value.get(subscribedKey) : null
      if (!subscriptionId) {
        await refreshSubscribedKeys()
        subscriptionId = subscribedKey ? subscribedIdMap.value.get(subscribedKey) : null
      }
      if (!subscriptionId) {
        ElMessage.warning('未找到订阅记录，请刷新后重试')
        return
      }
      await subscriptionApi.delete(subscriptionId)
      item.isSubscribed = false
      if (subscribedKey) {
        subscribedKeys.value.delete(subscribedKey)
        subscribedIdMap.value.delete(subscribedKey)
      }
      ElMessage.success('已取消订阅')
      return
    }

    const subscriptionData = {
      tmdb_id: tmdbId,
      title,
      media_type: mediaType,
      poster_path: item.poster_path || item.poster_url || '',
      overview: item.overview || '',
      year,
      rating: item.vote_average || null
    }

    try {
      const { data } = await subscriptionApi.create(subscriptionData)
      item.isSubscribed = true
      if (subscribedKey) {
        subscribedKeys.value.add(subscribedKey)
        const createdId = Number(data?.id || 0)
        if (createdId > 0) subscribedIdMap.value.set(subscribedKey, createdId)
      }
      ElMessage.success('订阅成功')
    } catch (error) {
      if (error.response?.status === 400) {
        await refreshSubscribedKeys()
        item.isSubscribed = Boolean(subscribedKey && subscribedKeys.value.has(subscribedKey))
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

  const routeInfo = await resolveExploreItemRoute(item)
  const mediaType = routeInfo?.media_type
  const tmdbId = toValidTmdbId(routeInfo?.tmdb_id)
  if (!tmdbId || (mediaType !== 'movie' && mediaType !== 'tv')) {
    if (exploreSource.value === 'douban' && goToDoubanDetail(item)) {
      ElMessage.info(withTitleHint(item, '已跳转豆瓣详情，可直接使用豆瓣关键词 115 转存'))
      return
    }
    ElMessage.warning(withTitleHint(item, getResolveFailureMessage(routeInfo?.reason)))
    return
  }

  item.saving = true
  try {
    const title = item.title || item.name || ''
    const year = item.year || getYear(item)
    const candidates = await fetchPan115ShareCandidates(mediaType, tmdbId)
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
      mediaType === 'tv' ? tmdbId : null
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

const getHomeInitialRenderCount = () => {
  const perView = cardsPerViewRef.value || 4
  return EXPLORE_SPEED_MODE === 'extreme'
    ? Math.max(perView * 3, 12)
    : Math.max(perView * 2, 8)
}

const getHomeRevealStep = () => {
  const perView = cardsPerViewRef.value || 4
  return EXPLORE_SPEED_MODE === 'extreme'
    ? Math.max(perView + 2, 8)
    : Math.max(perView, 6)
}

const getHomePrefetchCardThreshold = () => {
  const perView = cardsPerViewRef.value || 4
  return EXPLORE_SPEED_MODE === 'extreme'
    ? Math.max(perView * 2, 12)
    : Math.max(Math.ceil(perView * 1.5), 8)
}

const revealLoadedSectionCards = (sectionKey) => {
  const section = getExploreSectionByKey(sectionKey)
  if (!section) return 0
  const hiddenCount = Math.max(section.items.length - section.displayItems.length, 0)
  if (!hiddenCount) return 0
  const revealCount = Math.min(getHomeRevealStep(), hiddenCount)
  const startIndex = section.displayItems.length
  const toReveal = section.items.slice(startIndex, startIndex + revealCount)
  section.displayItems = section.displayItems.concat(toReveal)
  return toReveal.length
}

const ensureSectionInitialViewportCount = (sectionKey) => {
  const section = getExploreSectionByKey(sectionKey)
  if (!section) return
  const minCount = Math.min(getHomeInitialRenderCount(), section.items.length)
  if (section.displayItems.length >= minCount) return
  section.displayItems = section.items.slice(0, minCount)
}

const appendItemsToSection = (sectionKey, incomingItems = []) => {
  const section = getExploreSectionByKey(sectionKey)
  if (!section || !incomingItems.length) return 0
  const exists = new Set(section.items.map((item) => `${item.id}|${item.rank}|${item.title}`))
  const deduped = []
  for (const item of incomingItems) {
    const key = `${item.id}|${item.rank}|${item.title}`
    if (exists.has(key)) continue
    exists.add(key)
    deduped.push(item)
  }
  if (!deduped.length) return 0
  section.items = section.items.concat(deduped)
  return deduped.length
}

const requestHomeSectionBatch = async (sectionKey, start, { refresh = false } = {}) => {
  const count = HOME_SECTION_BATCH_SIZE
  const cacheKey = getHomeBatchCacheKey(sectionKey, start, count)
  if (!refresh) {
    const cachedPayload = getCachedHomeSectionBatch(sectionKey, start, count)
    if (cachedPayload) return cachedPayload
  }

  const inflight = homeSectionBatchInflight.get(cacheKey)
  if (inflight) return inflight

  const task = searchApi.getExploreSection(exploreSource.value, sectionKey, count, refresh, start)
    .then(({ data }) => {
      const payload = data.section || {}
      setCachedHomeSectionBatch(sectionKey, start, count, payload)
      return payload
    })
    .finally(() => {
      homeSectionBatchInflight.delete(cacheKey)
    })

  homeSectionBatchInflight.set(cacheKey, task)
  return task
}

const getHomeSectionMeta = (sectionKey) => {
  return homeSectionMetaMap.get(sectionKey) || null
}

const hasMoreHomeSectionRemote = (sectionKey) => {
  const meta = getHomeSectionMeta(sectionKey)
  if (!meta) return false
  return meta.nextOffset < meta.total
}

const fetchHomeSectionNextBatch = async (sectionKey) => {
  const meta = getHomeSectionMeta(sectionKey)
  if (!meta) return 0
  if (!hasMoreHomeSectionRemote(sectionKey)) return 0

  const existingPromise = homeSectionLoadPromises.get(sectionKey)
  if (existingPromise) return existingPromise

  const start = meta.nextOffset
  const task = (async () => {
    const payload = await requestHomeSectionBatch(sectionKey, start)
    const payloadItems = normalizeExploreSectionItems(
      Array.isArray(payload.items) ? payload.items : [],
      start + 1
    )
    const payloadTotal = Number(payload.total) || meta.total || payloadItems.length
    const payloadCount = Number(payload.count) || payloadItems.length
    meta.total = Math.max(meta.total, payloadTotal)
    meta.nextOffset = Math.max(meta.nextOffset, start + payloadCount)
    return appendItemsToSection(sectionKey, payloadItems)
  })().finally(() => {
    homeSectionLoadPromises.delete(sectionKey)
  })

  homeSectionLoadPromises.set(sectionKey, task)
  return task
}

const ensureHomeSectionPrefetch = async (sectionKey, force = false) => {
  if (homePrefetchPaused.value) return
  const section = getExploreSectionByKey(sectionKey)
  const row = getSectionRowEl(sectionKey)
  if (!section || !row) return

  const thresholdPx = (cardWidth.value + CARD_GAP) * getHomePrefetchCardThreshold()
  let remainingPx = row.scrollWidth - (row.scrollLeft + row.clientWidth)
  if (!force && remainingPx > thresholdPx) return

  const revealedFromLocal = revealLoadedSectionCards(sectionKey)
  if (revealedFromLocal > 0) {
    await nextTick()
    queueSectionScrollStateUpdate(sectionKey)
  }
  remainingPx = row.scrollWidth - (row.scrollLeft + row.clientWidth)

  for (let i = 0; i < HOME_SECTION_PREFETCH_ROUNDS; i += 1) {
    if (!hasMoreHomeSectionRemote(sectionKey)) break
    if (remainingPx > thresholdPx * 1.25) break
    const appended = await fetchHomeSectionNextBatch(sectionKey)
    if (appended <= 0) break
    revealLoadedSectionCards(sectionKey)
    await nextTick()
    queueSectionScrollStateUpdate(sectionKey)
    remainingPx = row.scrollWidth - (row.scrollLeft + row.clientWidth)
  }
}

const scheduleHomeSectionPrefetch = (sectionKey, force = false) => {
  if (homePrefetchPaused.value) return
  const existingTimer = homeSectionPrefetchTimers.get(sectionKey)
  if (existingTimer) return
  const timer = setTimeout(async () => {
    homeSectionPrefetchTimers.delete(sectionKey)
    try {
      await ensureHomeSectionPrefetch(sectionKey, force)
    } catch {
      // ignore prefetch failures on home explore rows
    }
  }, force ? 0 : HOME_SECTION_PREFETCH_DELAY_MS)
  homeSectionPrefetchTimers.set(sectionKey, timer)
}

const refreshAllSectionScrollStates = () => {
  calculateCardWidth()
  for (const section of exploreSections.value) {
    ensureSectionInitialViewportCount(section.key)
    updateSectionScrollState(section.key)
  }
}

const handleSectionScroll = (sectionKey) => {
  queueSectionScrollStateUpdate(sectionKey)
  scheduleHomeSectionPrefetch(sectionKey)
}

const scrollSection = (sectionKey, direction) => {
  const row = getSectionRowEl(sectionKey)
  if (!row) return
  const distance = Math.max((cardWidth.value + CARD_GAP) * 3, row.clientWidth * 0.55)
  row.scrollBy({
    left: direction * distance,
    behavior: 'smooth'
  })
  scheduleHomeSectionPrefetch(sectionKey)
}

const stopPressScroll = () => {
  if (pressScrollTimer) {
    clearInterval(pressScrollTimer)
    pressScrollTimer = null
  }
}

const startPressScroll = (sectionKey, direction, event) => {
  if (event) {
    event.preventDefault?.()
    event.stopPropagation?.()
  }
  const row = getSectionRowEl(sectionKey)
  if (!row) return
  stopPressScroll()
  const step = Math.max(18, Math.floor((cardWidth.value + CARD_GAP) * 0.28))
  pressScrollTimer = setInterval(() => {
    const currentRow = getSectionRowEl(sectionKey)
    if (!currentRow) {
      stopPressScroll()
      return
    }
    currentRow.scrollLeft += direction * step
    queueSectionScrollStateUpdate(sectionKey)
    const state = getSectionScrollState(sectionKey)
    if ((direction < 0 && !state.hasLeft) || (direction > 0 && !state.hasRight)) {
      stopPressScroll()
    }
  }, 16)
}

const goToSection = async (sectionKey) => {
  if (!sectionKey) return
  const key = String(sectionKey)
  try {
    await router.push({
      name: 'ExploreSection',
      params: {
        source: exploreSource.value,
        key
      }
    })
  } catch (error) {
    window.location.assign(`/explore/${encodeURIComponent(exploreSource.value)}/section/${encodeURIComponent(key)}`)
  }
}

const startDrag = (sectionKey, event) => {
  if (event.button !== undefined && event.button !== 0) return
  const row = getSectionRowEl(sectionKey)
  if (!row) return
  dragState.value = {
    active: true,
    sectionKey,
    startX: event.clientX,
    startScrollLeft: row.scrollLeft,
    pointerId: event.pointerId,
    moved: false,
    movedDistance: 0
  }
}

const onDrag = (event) => {
  if (!dragState.value.active) return
  if (dragState.value.pointerId !== null && event.pointerId !== dragState.value.pointerId) return
  const row = getSectionRowEl(dragState.value.sectionKey)
  if (!row) return
  if (event.pointerType === 'mouse' && event.buttons === 0) {
    endDrag(event)
    return
  }
  const delta = event.clientX - dragState.value.startX
  const absDelta = Math.abs(delta)
  dragState.value.movedDistance = Math.max(dragState.value.movedDistance, absDelta)
  if (absDelta > 8) {
    dragState.value.moved = true
    event.preventDefault()
  }
  row.scrollLeft = dragState.value.startScrollLeft - delta
}

const endDrag = (event) => {
  if (!dragState.value.active) return
  const row = getSectionRowEl(dragState.value.sectionKey)
  const movedScrollDistance = row
    ? Math.abs(row.scrollLeft - dragState.value.startScrollLeft)
    : 0
  if (dragState.value.moved && dragState.value.movedDistance > 16 && movedScrollDistance > 10) {
    lastDragAt.value = Date.now()
  }
  dragState.value = {
    active: false,
    sectionKey: '',
    startX: 0,
    startScrollLeft: 0,
    pointerId: null,
    moved: false,
    movedDistance: 0
  }
}

const rewriteTmdbPosterSize = (url, compact = false) => {
  const targetSegment = compact ? '/t/p/w342/' : '/t/p/w500/'
  return String(url).replace(/\/t\/p\/[^/]+\//, targetSegment)
}

const getPosterUrl = (path, options = {}) => {
  const compact = options.compact !== false
  if (!path) return new URL('/no-poster.png', import.meta.url).href
  const source = String(path).trim()
  const rawUrl = source.startsWith('//') ? `https:${source}` : source
  if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://')) {
    if (rawUrl.includes('doubanio.com')) {
      const size = compact ? 'small' : 'medium'
      return `/api/search/explore/poster?url=${encodeURIComponent(rawUrl)}&size=${size}`
    }
    if (rawUrl.includes('image.tmdb.org')) {
      return rewriteTmdbPosterSize(rawUrl, compact)
    }
    return rawUrl
  }
  if (String(path).startsWith('/')) return rewriteTmdbPosterSize(`${TMDB_IMAGE_BASE}${path}`, compact)
  return new URL('/no-poster.png', import.meta.url).href
}

const isPriorityExplorePoster = (sectionIndex, itemIndex) => {
  return Number(sectionIndex) === 0 && Number(itemIndex) < EXPLORE_HERO_POSTER_COUNT
}

const handleImageError = (e) => {
  e.target.src = new URL('/no-poster.png', import.meta.url).href
}

const getMediaTypeLabel = (type) => {
  const labels = {
    movie: '电影',
    tv: '电视剧',
    collection: '合集',
    person: '浜虹墿',
    resource: '网盘资源'
  }
  return labels[type] || type
}

const getMediaTypeTag = (type) => {
  const tags = {
    movie: 'primary',
    tv: 'success',
    collection: 'warning',
    person: 'info',
    resource: 'warning'
  }
  return tags[type] || ''
}

const getServiceLabel = (service) => {
  const labels = {
    tmdb: 'TMDB',
    nullbr: 'Nullbr',
    pansou: 'Pansou',
    mixed: '混合结果'
  }
  return labels[service] || service || '未知'
}

const getYear = (item) => {
  const date = item.release_date || item.first_air_date || ''
  return date ? date.split('-')[0] : ''
}

const truncateText = (text, maxLength) => {
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength) + '...'
}

const isLikelyPan115ShareLink = (shareLink) => {
  const raw = String(shareLink || '').trim()
  if (!raw) return false
  if (raw.startsWith('http://') || raw.startsWith('https://') || raw.startsWith('//')) {
    return /(?:115(?:cdn)?\.com|share\.115\.com|anxia\.com)/i.test(raw)
  }
  return /^[A-Za-z0-9]+(?:-[A-Za-z0-9]{4})?$/.test(raw)
}

const normalizeSearchResultItem = (item, index = 0, fallbackService = '') => {
  const sourceService = item.source_service || fallbackService || 'nullbr'
  const shareLink = item.pan115_share_link || item.share_link || item.share_url || item.url || item.link || ''
  const isPansouResult = sourceService === 'pansou'
  const normalizedId = item.tmdbid || item.tmdb_id || item.id || `${sourceService}-${index}`
  return {
    ...item,
    id: normalizedId,
    media_type: item.media_type || (isPansouResult ? 'resource' : ''),
    poster_path: item.poster || item.poster_path,
    name: item.title || item.name,
    vote_average: item.vote || item.vote_average,
    source_service: sourceService,
    pan115_share_link: shareLink,
    isPansouResult,
    canSaveToPan115: Boolean(
      isPansouResult
      && (item.pan115_savable ?? isLikelyPan115ShareLink(shareLink))
    ),
    isSubscribed: isSubscribedMedia(item.media_type || (isPansouResult ? 'resource' : ''), item.tmdb_id || item.tmdbid || normalizedId),
    subscribing: false,
    saving: false
  }
}

const fetchExploreSections = async () => {
  exploreLoading.value = true
  try {
    const { data } = await searchApi.getExploreSections(exploreSource.value, HOME_SECTION_BATCH_SIZE)
    const sections = Array.isArray(data.sections) ? data.sections : []
    homeSectionMetaMap.clear()
    exploreSections.value = sections.map((section) => {
      const normalizedItems = normalizeExploreSectionItems(section.items || [], 1)
      const initialDisplayCount = Math.min(getHomeInitialRenderCount(), normalizedItems.length)
      const total = Number(section.total) || normalizedItems.length
      homeSectionMetaMap.set(section.key, {
        total,
        nextOffset: normalizedItems.length
      })

      return {
        ...section,
        items: normalizedItems,
        displayItems: normalizedItems.slice(0, initialDisplayCount)
      }
    })
    applySubscribedFlags()

    await nextTick()
    calculateCardWidth()
    refreshAllSectionScrollStates()
    for (const section of exploreSections.value) {
      scheduleHomeSectionPrefetch(section.key, true)
    }
  } catch (error) {
    console.error('Failed to fetch explore sections:', error)
  } finally {
    exploreLoading.value = false
  }
}

const clearHomePrefetchTimers = () => {
  for (const timer of homeSectionPrefetchTimers.values()) {
    clearTimeout(timer)
  }
  homeSectionPrefetchTimers.clear()
}

const handleBackToExplore = () => {
  searched.value = false
  results.value = []
  totalPages.value = 0
  currentPage.value = 1
  lastSearchKeyword.value = ''
  activeSearchService.value = ''
  homePrefetchPaused.value = false
  clearHomePrefetchTimers()
  for (const section of exploreSections.value) {
    scheduleHomeSectionPrefetch(section.key)
  }
}

const handleSearch = async () => {
  const keyword = String(searchQuery.value || '').trim()
  if (!keyword) {
    ElMessage.warning('请输入关键词')
    return
  }
  if (keyword !== lastSearchKeyword.value) {
    currentPage.value = 1
    lastSearchKeyword.value = keyword
  }

  loading.value = true
  searched.value = true
  homePrefetchPaused.value = true
  clearHomePrefetchTimers()

  try {
    const { data } = await searchApi.search(keyword, currentPage.value)
    const items = data.items || data.results || []
    activeSearchService.value = data.search_service || ''
    results.value = items.map((item, index) =>
      normalizeSearchResultItem(item, index, activeSearchService.value)
    )
    applySubscribedFlags()
    const backendPages = Number(data.total_pages) || 0
    totalPages.value = backendPages || (results.value.length > 0 ? 1 : 0)
  } catch (error) {
    console.error('Search failed:', error)
    ElMessage.error('搜索失败，请稍后重试')
  } finally {
    loading.value = false
    homePrefetchPaused.value = false
    for (const section of exploreSections.value) {
      scheduleHomeSectionPrefetch(section.key)
    }
  }
}

const handlePageChange = (page) => {
  currentPage.value = page
  handleSearch()
}

const handleItemClick = (item) => {
  if (item.isPansouResult) return
  const type = item.media_type
  const id = item.id
  if (!id) return

  if (type === 'movie') {
    warmupPan115Resources('movie', id)
    router.push(`/movie/${id}`)
  } else if (type === 'tv') {
    warmupPan115Resources('tv', id)
    router.push(`/tv/${id}`)
  } else if (type === 'collection') {
    router.push(`/movie/${id}`)
  }
}

const warmupPan115Resources = (mediaType, tmdbId) => {
  if (!tmdbId) return
  if (mediaType === 'tv') {
    searchApi.getTvPan115(tmdbId).catch(() => {})
    return
  }
  searchApi.getMoviePan115(tmdbId).catch(() => {})
}

const resolveExploreItemRoute = async (item) => {
  const directTmdbId = toValidTmdbId(item.tmdb_id)
  const directType = item.media_type === 'tv' ? 'tv' : 'movie'
  if (exploreSource.value === 'tmdb' && directTmdbId) {
    return { media_type: directType, tmdb_id: directTmdbId }
  }

  try {
    const payload = {
      source: exploreSource.value,
      id: item.id,
      douban_id: item.douban_id || item.id,
      title: item.title || item.name || '',
      year: item.year || getYear(item) || '',
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
        media_type: data?.media_type === 'tv' ? 'tv' : directType,
        tmdb_id: null,
        reason: String(data?.reason || 'low_confidence_or_ambiguous')
      }
    }
    const resolvedType = data.media_type === 'tv' ? 'tv' : 'movie'
    return { media_type: resolvedType, tmdb_id: resolvedTmdbId }
  } catch (error) {
    console.error('Failed to resolve explore item route:', error)
    return {
      media_type: directType,
      tmdb_id: null,
      reason: 'search_failed'
    }
  }
}

const handleExploreItemClick = async (item) => {
  if (Date.now() - lastDragAt.value < 100) return

  if (exploreSource.value === 'douban' && goToDoubanDetail(item)) {
    return
  }
  
  const routeInfo = await resolveExploreItemRoute(item)
  if (!routeInfo?.tmdb_id) {
    ElMessage.warning(getResolveFailureMessage(routeInfo?.reason))
    return
  }

  const target = {
    key: `${routeInfo.media_type}:${routeInfo.tmdb_id}`,
    mediaType: routeInfo.media_type,
    tmdbId: toValidTmdbId(routeInfo.tmdb_id)
  }
  if (!target.tmdbId) {
    ElMessage.warning('未找到有效的 TMDB 详情 ID')
    return
  }
  
  goToDetail(routeInfo.media_type, routeInfo.tmdb_id)
}

const handleSubscribe = async (item) => {
  if (item.isPansouResult || item.media_type === 'resource') {
    ElMessage.warning('盘搜资源不支持订阅')
    return
  }
  if (item.media_type === 'person') {
    ElMessage.warning('暂不支持订阅人物')
    return
  }

  item.subscribing = true
  try {
    const mediaType = item.media_type
    const tmdbId = toValidTmdbId(item.tmdb_id || item.tmdbid || item.id)
    if (!tmdbId || (mediaType !== 'movie' && mediaType !== 'tv')) {
      throw new Error('未找到有效的 TMDB 条目')
    }
    const subscribedKey = buildSubscribedKey(mediaType, tmdbId)
    if (item.isSubscribed) {
      let subscriptionId = subscribedKey ? subscribedIdMap.value.get(subscribedKey) : null
      if (!subscriptionId) {
        await refreshSubscribedKeys()
        subscriptionId = subscribedKey ? subscribedIdMap.value.get(subscribedKey) : null
      }
      if (!subscriptionId) {
        ElMessage.warning('未找到订阅记录，请刷新后重试')
        return
      }
      await subscriptionApi.delete(subscriptionId)
      item.isSubscribed = false
      if (subscribedKey) {
        subscribedKeys.value.delete(subscribedKey)
        subscribedIdMap.value.delete(subscribedKey)
      }
      ElMessage.success('已取消订阅')
      return
    }

    const subscriptionData = {
      tmdb_id: tmdbId,
      title: item.name || item.title,
      media_type: mediaType,
      poster_path: item.poster_path,
      overview: item.overview,
      year: getYear(item),
      rating: item.vote_average
    }
    const { data } = await subscriptionApi.create(subscriptionData)
    item.isSubscribed = true
    if (subscribedKey) {
      subscribedKeys.value.add(subscribedKey)
      const createdId = Number(data?.id || 0)
      if (createdId > 0) subscribedIdMap.value.set(subscribedKey, createdId)
    }
    ElMessage.success('订阅成功')
  } catch (error) {
    if (error.response?.status === 400) {
      await refreshSubscribedKeys()
      const key = buildSubscribedKey(item.media_type, item.tmdb_id || item.tmdbid || item.id)
      item.isSubscribed = Boolean(key && subscribedKeys.value.has(key))
      ElMessage.info(item.isSubscribed ? '该影视已在订阅列表中' : '订阅状态已更新，请重试')
    } else {
      ElMessage.error(error.response?.data?.detail || error.message || '订阅操作失败')
    }
  } finally {
    item.subscribing = false
  }
}

const parseReceiveCodeFromShareLink = (shareLink) => {
  const rawLink = String(shareLink || '').trim()
  if (!rawLink) return ''

  const passwordMatch = rawLink.match(/[?&](?:password|pwd)=([^&#]+)/i)
  if (!passwordMatch) return ''

  try {
    return decodeURIComponent(passwordMatch[1])
  } catch {
    return passwordMatch[1]
  }
}

const handleSavePansouResult = async (item) => {
  if (!item.pan115_share_link) {
    ElMessage.warning('该盘搜结果没有可转存的 115 分享链接')
    return
  }

  item.saving = true
  try {
    let folderId = '0'
    try {
      const { data } = await pan115Api.getDefaultFolder()
      folderId = data.folder_id || '0'
    } catch {
      folderId = '0'
    }

    const resourceName = item.name || item.title || lastSearchKeyword.value || 'Pansou Resource'
    const receiveCode = parseReceiveCodeFromShareLink(item.pan115_share_link)
    const { data } = await pan115Api.saveShareToFolder(
      item.pan115_share_link,
      resourceName,
      folderId,
      receiveCode
    )
    const saveSuccess = data?.success === true
      || data?.state === true
      || data?.result?.success === true
      || data?.result?.state === true
    if (!saveSuccess) {
      throw new Error(data?.message || data?.error || data?.result?.error || '转存失败')
    }
    ElMessage.success(data?.message || '转存成功')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '转存失败')
  } finally {
    item.saving = false
  }
}

const handleSave = async (item) => {
  if (item.isPansouResult) {
    await handleSavePansouResult(item)
    return
  }
  if (item.media_type === 'person') {
    ElMessage.warning('人物不支持转存')
    return
  }
  handleItemClick(item)
}

const setupSectionResizeObserver = () => {
  if (typeof ResizeObserver === 'undefined') return
  sectionResizeObserver = new ResizeObserver(() => {
    refreshAllSectionScrollStates()
  })
  for (const section of exploreSections.value) {
    const row = getSectionRowEl(section.key)
    if (row) sectionResizeObserver.observe(row)
  }
}

const cleanupSectionResizeObserver = () => {
  if (sectionResizeObserver) {
    sectionResizeObserver.disconnect()
    sectionResizeObserver = null
  }
}

const resetExploreState = () => {
  clearHomePrefetchTimers()
  homeSectionLoadPromises.clear()
  homeSectionMetaMap.clear()
  homeSectionBatchInflight.clear()
  homeSectionBatchCache.clear()
  sectionRowRefs.value = {}
  sectionScrollStates.value = {}
  exploreSections.value = []
}

onMounted(async () => {
  await refreshSubscribedKeys()
  await fetchExploreSections()
  setupSectionResizeObserver()
  window.addEventListener('resize', refreshAllSectionScrollStates)
})

watch(exploreSource, async (newSource, oldSource) => {
  if (newSource === oldSource) return
  resetExploreState()
  await fetchExploreSections()
  cleanupSectionResizeObserver()
  setupSectionResizeObserver()
})

onBeforeUnmount(() => {
  stopPressScroll()
  clearHomePrefetchTimers()
  homeSectionLoadPromises.clear()
  homeSectionMetaMap.clear()
  homeSectionBatchInflight.clear()
  homeSectionBatchCache.clear()
  if (scrollStateRafId) {
    cancelAnimationFrame(scrollStateRafId)
    scrollStateRafId = 0
  }
  pendingScrollStateKeys.clear()
  cleanupSectionResizeObserver()
  window.removeEventListener('resize', refreshAllSectionScrollStates)
})
</script>

<style lang="scss" scoped>
.explore-page {
  animation: fadeIn 0.4s ease;
  
  .search-header {
    margin-bottom: 24px;
    padding: 0;
    border: 0;
    background: transparent;
    box-shadow: none;
    
    :deep(.el-input) {
      --search-pill-bg: rgba(17, 37, 72, 0.82);
      width: 100%;

      .el-input__wrapper {
        border-radius: 10px;
        min-height: 44px;
        padding: 0 12px;
        background: var(--search-pill-bg);
        box-shadow: none;
      }

      .el-input-group__prepend,
      .el-input-group__append {
        background: var(--search-pill-bg);
        border: none;
        box-shadow: none;
      }

      .el-input-group__prepend {
        border-radius: 10px 0 0 10px;
        padding-left: 10px;
      }

      .el-input-group__append {
        border-radius: 0 10px 10px 0;
        padding-right: 6px;
      }

      .el-input-group__prepend .el-button,
      .el-input-group__append .el-button {
        border: 0;
      }

      .el-input-group__prepend .el-button {
        color: var(--ms-text-secondary);
      }

      .el-input-group__append .el-button {
        border-radius: 8px;
        padding-inline: 16px;
      }

      &.is-focus .el-input__wrapper {
        box-shadow: 0 0 0 1px rgba(45, 153, 255, 0.35), 0 0 20px rgba(45, 153, 255, 0.14);
      }
    }
  }

  .explore-section {
    margin-bottom: 28px;
    padding: 24px;
    border: 1px solid var(--ms-glass-border);
    border-radius: 20px;
    background: var(--ms-gradient-card);
    position: relative;
    overflow: hidden;
    
    // 顶部装饰光效
    &::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 1px;
      background: linear-gradient(90deg, transparent, rgba(45, 153, 255, 0.4), transparent);
    }

    .section-header {
      margin-bottom: 20px;

      .section-title {
        display: flex;
        align-items: center;
        gap: 12px;

        h2 {
          margin: 0;
          font-size: 22px;
          font-weight: 700;
          background: linear-gradient(135deg, var(--ms-text-primary) 0%, var(--ms-text-secondary) 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }
      }

      p {
        margin: 10px 0 0;
        color: var(--ms-text-muted);
        font-size: 13px;
      }
    }

    .recommend-group {
      padding-top: 16px;

      &:not(:first-child) {
        margin-top: 12px;
        border-top: 1px solid var(--ms-border-color);
      }

      .group-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 14px;

        .group-title {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .group-sub {
          color: var(--ms-text-muted);
          font-size: 12px;
          font-weight: 500;
        }

        h3 {
          margin: 0;
          color: var(--ms-text-primary);
          font-size: 16px;
          font-weight: 600;
        }

        .group-actions {
          display: flex;
          gap: 8px;
        }
      }

      .row-shell {
        position: relative;

        .edge-mask {
          position: absolute;
          top: 0;
          bottom: 0;
          width: 40px;
          pointer-events: none;
          z-index: 2;
        }

        .edge-mask.left {
          left: 0;
          background: linear-gradient(to right, rgba(10, 25, 51, 0.9), transparent);
        }

        .edge-mask.right {
          right: 0;
          background: linear-gradient(to left, rgba(10, 25, 51, 0.9), transparent);
        }

        .side-scroll-btn {
          position: absolute;
          top: 50%;
          transform: translateY(-50%);
          z-index: 3;
          border-color: rgba(45, 153, 255, 0.34);
          background: rgba(13, 35, 69, 0.85);
          color: var(--ms-text-primary);
          backdrop-filter: blur(8px);
          transition: all 0.2s ease;
          
          &:hover {
            border-color: rgba(45, 153, 255, 0.5);
            background: rgba(45, 153, 255, 0.18);
          }
        }

        .side-scroll-btn.left {
          left: 4px;
        }

        .side-scroll-btn.right {
          right: 4px;
        }
      }

      .recommend-row {
        display: flex;
        gap: 16px;
        overflow-x: auto;
        overflow-y: hidden;
        width: 100%;
        scroll-snap-type: none;
        scrollbar-width: none;
        -ms-overflow-style: none;
        cursor: grab;
        padding-bottom: 8px;
        user-select: none;
        touch-action: pan-y;

        &.dragging {
          cursor: grabbing;
          scroll-behavior: auto;
        }
      }

      .recommend-row::-webkit-scrollbar {
        width: 0;
        height: 0;
        display: none;
      }

      .recommend-card {
        width: var(--recommend-card-width, 188px);
        min-width: var(--recommend-card-width, 188px);
        border-radius: 14px;
        cursor: pointer;
        border: 1px solid var(--ms-border-color);
        background: var(--ms-glass-bg);
        transition: all 0.3s ease;
        overflow: hidden;

        &:hover {
          transform: translateY(-6px);
          border-color: rgba(45, 153, 255, 0.35);
          box-shadow: var(--ms-shadow-md), 0 0 20px rgba(45, 153, 255, 0.2);
        }

        &.just-saved {
          border-color: rgba(52, 199, 89, 0.78);
          box-shadow: 0 0 0 1px rgba(52, 199, 89, 0.6), 0 0 26px rgba(52, 199, 89, 0.35);
          animation: card-save-flash 1.5s ease;
        }

        .poster-wrapper {
          position: relative;
          aspect-ratio: 2 / 3;
          background: var(--ms-bg-elevated);
          overflow: hidden;

          img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            user-select: none;
            -webkit-user-drag: none;
            transition: transform 0.4s ease;
          }
          
          &:hover img {
            transform: scale(1.05);
          }

          .explore-card-actions {
            position: absolute;
            left: 50%;
            bottom: 14px;
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
            box-shadow: var(--ms-shadow-sm);
            }
          }

          &:hover .explore-card-actions,
          &:focus-within .explore-card-actions {
            opacity: 1;
            transform: translate(-50%, 0);
          }

          .rank-badge {
            position: absolute;
            top: 10px;
            left: 10px;
            padding: 4px 10px;
            border-radius: 8px;
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.9) 0%, rgba(251, 191, 36, 0.9) 100%);
            color: #062040;
            font-size: 12px;
            font-weight: 700;
            box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);
          }
        }

        .card-info {
          padding: 12px 14px 14px;

          .title {
            margin: 0;
            color: var(--ms-text-primary);
            font-size: 14px;
            font-weight: 600;
            line-height: 1.4;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
          }
        }
        
        .card-actions {
          margin-top: 8px;
          display: flex;
          justify-content: flex-start;
        }
      }
    }
  }

  .search-results {
    min-height: 220px;
    border: 1px solid var(--ms-glass-border);
    border-radius: 20px;
    padding: 20px;
    background: var(--ms-gradient-card);

    .results-skeleton-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 20px;
    }

    .skeleton-card {
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid var(--ms-border-color);
      background: var(--ms-glass-bg);
    }

    .skeleton-poster {
      aspect-ratio: 2 / 3;
      background: linear-gradient(
        90deg,
        rgba(89, 151, 226, 0.22) 25%,
        rgba(148, 205, 255, 0.34) 37%,
        rgba(89, 151, 226, 0.22) 63%
      );
      background-size: 300% 100%;
      animation: search-skeleton-shimmer 1.2s ease-in-out infinite;
    }

    .skeleton-title {
      height: 14px;
      margin: 10px 12px 12px;
      border-radius: 6px;
      background: linear-gradient(
        90deg,
        rgba(89, 151, 226, 0.22) 25%,
        rgba(148, 205, 255, 0.34) 37%,
        rgba(89, 151, 226, 0.22) 63%
      );
      background-size: 300% 100%;
      animation: search-skeleton-shimmer 1.2s ease-in-out infinite;
    }

    .results-header {
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;

      h3 {
        margin: 0;
        color: var(--ms-text-primary);
        font-weight: 600;
      }

      .results-meta {
        display: flex;
        align-items: center;
        gap: 6px;
      }
    }
  }

  .results-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 20px;
  }

  .media-card {
    cursor: pointer;
    border-radius: 14px;
    border: 1px solid var(--ms-border-color);
    background: var(--ms-glass-bg);
    transition: all 0.3s ease;
    overflow: hidden;

    &.pansou-card {
      cursor: default;
    }

    &:hover {
      transform: translateY(-6px);
      border-color: rgba(45, 153, 255, 0.35);
      box-shadow: var(--ms-shadow-md), 0 0 20px rgba(45, 153, 255, 0.2);

      .action-buttons {
        opacity: 1;
      }
      
      .poster-wrapper img {
        transform: scale(1.05);
      }
    }

    .poster-wrapper {
      position: relative;
      aspect-ratio: 2/3;
      background: var(--ms-bg-elevated);
      overflow: hidden;

      img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        transition: transform 0.4s ease;
      }

      .media-type-tag {
        position: absolute;
        top: 10px;
        left: 10px;
      }

      .rating-badge {
        position: absolute;
        top: 10px;
        right: 10px;
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.9) 0%, rgba(251, 191, 36, 0.9) 100%);
        color: #062040;
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
        box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);
      }

      .action-buttons {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        display: flex;
        justify-content: space-between;
        padding: 12px;
        background: linear-gradient(transparent, rgba(7, 18, 36, 0.84));
        opacity: 0;
        transition: opacity 0.3s ease;

        .action-btn {
          padding: 6px 12px;
          font-size: 12px;
          border-radius: 6px;

          .el-icon {
            margin-right: 4px;
          }
        }
      }
    }

    .media-info {
      padding: 14px;

      .title {
        margin: 0 0 6px;
        font-size: 14px;
        font-weight: 600;
        color: var(--ms-text-primary);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .year {
        margin: 0 0 8px;
        font-size: 12px;
        color: var(--ms-text-muted);
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }

      .overview {
        margin: 0;
        font-size: 12px;
        color: var(--ms-text-secondary);
        line-height: 1.5;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
    }
  }

  .pagination-wrapper {
    margin-top: 28px;
    display: flex;
    justify-content: center;
  }
}

@keyframes search-skeleton-shimmer {
  0% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0 50%;
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
  .explore-page .search-header :deep(.el-input .el-input__wrapper) {
    min-height: 40px;
  }

  .explore-page .search-header :deep(.el-input-group__prepend) {
    padding-left: 6px;
  }

  .explore-page .search-header :deep(.el-input-group__append .el-button) {
    padding-inline: 12px;
  }

  .explore-page .explore-section .recommend-group .recommend-card .poster-wrapper .explore-card-actions {
    opacity: 1;
    transform: translate(-50%, 0);
  }

  .explore-page .explore-section .recommend-group .recommend-card .poster-wrapper .explore-card-actions .explore-action-btn {
    width: 36px;
    height: 36px;
  }
}

@media (hover: none) {
  .explore-page .explore-section .recommend-group .recommend-card .poster-wrapper .explore-card-actions {
    opacity: 1;
    transform: translate(-50%, 0);
  }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>

