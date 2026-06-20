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
        <template #prefix>
          <el-icon><SearchIcon /></el-icon>
        </template>
        <template #append>
          <el-button type="primary" @click="handleSearch">
            <el-icon><SearchIcon /></el-icon>
            搜索
          </el-button>
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
        </div>
      </div>

      <div class="recommend-sections">
        <TmdbSetupPrompt
          v-if="exploreSource === 'tmdb' && !tmdbConfigured"
          @configured="handleTmdbConfigured"
        />

        <template v-else-if="exploreSections.length > 0">
          <ExploreSectionRow
            v-for="section in exploreSections"
            :key="`${exploreSource}:${section.key}`"
            :source="exploreSource"
            :card-width="cardWidth"
            :section="section"
            :preloaded-items="exploreUseLazySections ? null : section.items"
            :preloaded-total="exploreUseLazySections ? 0 : section.total"
            :subscribed-id-map="subscribedIdMap"
            :subscribed-douban-ids="subscribedDoubanIds"
            :subscribed-imdb-ids="subscribedImdbIds"
            :queue-active-save-keys="queueActiveSaveKeys"
            :emby-status-map="embyStatusMap"
            :feiniu-status-map="feiniuStatusMap"
            @merge-emby-status="mergeEmbyStatusMap"
            @merge-feiniu-status="mergeFeiniuStatusMap"
            @open-section="goToSection"
            @item-click="handleExploreItemClick"
            @subscribe="handleExploreSubscribe"
            @save="handleExploreSave"
          />
        </template>

        <template v-else-if="exploreLoading && tmdbConfigured">
          <div class="explore-skeleton">
            <div
              v-for="n in EXPLORE_SKELETON_SECTION_COUNT"
              :key="`skeleton-section-${n}`"
              class="recommend-group skeleton-group"
            >
              <div class="group-header skeleton-group-header">
                <div class="group-title">
                  <div class="skeleton-line skeleton-title-line" />
                </div>
                <div class="skeleton-line skeleton-action-line" />
              </div>
              <div class="skeleton-row">
                <div
                  v-for="m in exploreSkeletonCardCount"
                  :key="`skeleton-card-${n}-${m}`"
                  class="skeleton-card"
                >
                  <div class="skeleton-poster" />
                  <div class="skeleton-title" />
                </div>
              </div>
            </div>
          </div>
        </template>

        <el-empty v-else description="暂无影视推荐" />
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
              <LibraryBadge
                v-if="item.isInMediaLibrary"
                class="emby-badge"
                :in-emby="item.isInEmby"
                :in-feiniu="item.isInFeiniu"
              />
              <div class="media-type-tag">
                <el-tag :type="getMediaTypeTag(item.media_type)" size="small">
                  {{ getMediaTypeLabel(item.media_type) }}
                </el-tag>
              </div>
              <div class="rating-badge" :class="{ 'has-emby': item.isInMediaLibrary }" v-if="item.vote_average">
                {{ item.vote_average.toFixed(1) }}
              </div>
              <div class="action-buttons">
                <el-button
                  v-if="!item.isPansouResult && item.media_type === 'person'"
                  class="action-btn subscribe-btn"
                  :type="item.isFollowed ? 'success' : 'primary'"
                  size="small"
                  :loading="item.following"
                  @click.stop="handleFollowPerson(item)"
                >
                  <el-icon><User /></el-icon>
                  {{ item.isFollowed ? '已关注(取消)' : '关注' }}
                </el-button>
                <el-button
                  v-else-if="!item.isPansouResult && item.media_type !== 'person'"
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
                  v-if="item.media_type !== 'person'"
                  class="action-btn save-btn"
                  type="warning"
                  size="small"
                  :loading="item.saving"
                  :disabled="item.isPansouResult && !item.canSaveToPan115"
                  @click.stop="handleSave(item)"
                >
                  <el-icon><FolderAdd /></el-icon>
                  <template v-if="item.queuePosition > 1">排队中({{ item.queuePosition }})</template>
                  <template v-else>{{ item.isPansouResult ? '一键转存' : '转存' }}</template>
                </el-button>
                <el-button
                  v-if="item.isPansouResult && item.pan115_share_link"
                  class="action-btn watchlist-btn"
                  size="small"
                  @click.stop="handleCopyPanShareLink(item)"
                >
                  复制分享链接
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
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, shallowRef, triggerRef, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { clearSearchReturnContext, saveSearchReturnContext } from '@/utils/navigation'
import {
  getSearchRouteSyncToken,
  markSearchRouteLeave,
  restorePendingLeaveNavigation
} from '@/utils/searchRouteSync'
import { ElMessage } from 'element-plus'
import { searchApi, subscriptionApi, pan115Api, settingsApi, personFollowApi } from '@/api'
import ExploreSectionRow from '@/components/explore/ExploreSectionRow.vue'
import TmdbSetupPrompt from '@/components/explore/TmdbSetupPrompt.vue'
import LibraryBadge from '@/components/media/LibraryBadge.vue'
import {
  Search as SearchIcon,
  Star,
  FolderAdd,
  User
} from '@element-plus/icons-vue'
import {
  EXPLORE_CARD_GAP,
  estimateExploreContainerWidth,
  getInitialExploreCardLayout,
  resolveExploreCardLayout
} from '@/utils/exploreCardLayout'
import {
  getCachedExploreSectionBatch,
  getExploreSectionBatchInflight,
  setCachedExploreSectionBatch,
  setExploreSectionBatchInflight
} from '@/utils/exploreSectionBatchCache'
import { createExploreLibraryBadgeSyncer } from '@/utils/exploreLibraryBadgeSync'
import { copyText } from '@/utils/clipboard'
import { buildExploreQueuePayload, buildTmdbSavePayload } from '@/utils/exploreQueuePayload'

defineOptions({ name: 'Search' })

const router = useRouter()
const route = useRoute()

/** 仅探索首页处于激活展示时允许改路由，避免 keep-alive 缓存页在离开后继续 replace */
const searchPageEngaged = ref(true)
const isSearchRouteActive = () => (
  searchPageEngaged.value
  && route.name === 'Search'
  && (route.path.startsWith('/explore/') || route.path === '/' || route.path === '/search')
)

const normalizeExploreSource = (rawSource) => (String(rawSource || '').toLowerCase() === 'tmdb' ? 'tmdb' : 'douban')
const exploreSource = computed(() => normalizeExploreSource(route.params.source))
const exploreSourceLabel = computed(() => (exploreSource.value === 'tmdb' ? 'TMDB 榜单探索' : '豆瓣榜单探索'))

const searchQuery = ref('')
const results = ref([])
const loading = ref(false)
const searched = ref(false)
const currentPage = ref(1)
const totalPages = ref(0)

const exploreLoading = ref(false)
const tmdbConfigured = ref(true)
const exploreSections = shallowRef([])
const exploreUseLazySections = ref(false)
let exploreSectionsRequestId = 0
const exploreContainerRef = ref(null)
const sectionRowRefs = ref({})
const sectionScrollStates = ref({})
const initialExploreCardLayout = getInitialExploreCardLayout()
const cardWidth = ref(initialExploreCardLayout.cardWidth)
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

const resourcePriority = ref(['hdhive', 'pansou', 'tg'])

const loadResourcePriority = async () => {
  try {
    const { data } = await settingsApi.getRuntime()
    const list = data?.subscription_resource_priority
    if (Array.isArray(list) && list.length) {
      resourcePriority.value = list
    }
  } catch { /* use default */ }
}

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
const subscribedDoubanIds = ref(new Set()) // 存储豆瓣ID订阅集合
const followedPersonIds = ref(new Set())
const subscribedImdbIds = ref(new Set()) // 存储IMDB ID订阅集合
const embyStatusMap = ref(new Map())
const feiniuStatusMap = ref(new Map())
const EXPLORE_QUEUE_POLL_INTERVAL_MS = 1800
const queueActiveSaveKeys = ref(new Set())
let exploreQueuePollTimer = null
let exploreQueuePolling = false

// 探索页转存队列状态（与后端 explore queue 同步）
const buildSubscribedKey = (mediaType, tmdbId) => {
  const normalizedType = mediaType === 'tv' ? 'tv' : (mediaType === 'movie' ? 'movie' : '')
  const normalizedTmdbId = toValidTmdbId(tmdbId)
  if (!normalizedType || !normalizedTmdbId) return ''
  return `${normalizedType}:${normalizedTmdbId}`
}

const markEmbyOnItem = (item) => {
  if (!item || typeof item !== 'object') return
  const key = buildSubscribedKey(item.media_type, item.tmdb_id || item.tmdbid)
  const inEmby = Boolean(key) && Boolean(embyStatusMap.value.get(key)?.exists_in_emby)
  const inFeiniu = Boolean(key) && Boolean(feiniuStatusMap.value.get(key)?.exists_in_feiniu)
  item.isInEmby = inEmby
  item.isInFeiniu = inFeiniu
  item.isInMediaLibrary = inEmby || inFeiniu
}

const isSubscribedMedia = (mediaType, tmdbId) => {
  const key = buildSubscribedKey(mediaType, tmdbId)
  return Boolean(key) && subscribedKeys.value.has(key)
}

const isSubscribedByDoubanId = (doubanId) => {
  if (!doubanId) return false
  return subscribedDoubanIds.value.has(String(doubanId))
}

const isSubscribedByImdbId = (imdbId) => {
  if (!imdbId) return false
  return subscribedImdbIds.value.has(String(imdbId).toLowerCase())
}

const markSubscribedOnItem = (item) => {
  if (!item || typeof item !== 'object') return
  const mediaType = item.media_type
  const tmdbId = toValidTmdbId(item.tmdb_id || item.tmdbid)
  const doubanId = item.douban_id || item.id
  const imdbId = item.imdb_id
  item.isSubscribed = isSubscribedMedia(mediaType, tmdbId) ||
                      isSubscribedByDoubanId(doubanId) ||
                      isSubscribedByImdbId(imdbId)
}

const mergeEmbyStatusMap = (rawMap = {}) => {
  if (!rawMap || typeof rawMap !== 'object') return
  const nextMap = new Map(embyStatusMap.value)
  for (const [key, value] of Object.entries(rawMap)) {
    nextMap.set(key, value || {})
  }
  embyStatusMap.value = nextMap
}

const mergeFeiniuStatusMap = (rawMap = {}) => {
  if (!rawMap || typeof rawMap !== 'object') return
  const nextMap = new Map(feiniuStatusMap.value)
  for (const [key, value] of Object.entries(rawMap)) {
    nextMap.set(key, value || {})
  }
  feiniuStatusMap.value = nextMap
}

let libraryBadgeSyncer = null
libraryBadgeSyncer = createExploreLibraryBadgeSyncer({
  getEmbyStatusMap: () => embyStatusMap.value,
  getFeiniuStatusMap: () => feiniuStatusMap.value,
  mergeEmbyStatusMap,
  mergeFeiniuStatusMap
})

const collectExploreSectionItems = () => (
  exploreSections.value.flatMap((section) => (
    Array.isArray(section?.items) ? section.items : []
  ))
)

const scheduleLibraryBadgeSync = (items) => {
  const rows = items ?? collectExploreSectionItems()
  libraryBadgeSyncer?.schedule(rows)
}

const normalizeExploreQueueMediaType = (rawType) => {
  return String(rawType || '').toLowerCase() === 'tv' ? 'tv' : 'movie'
}

const buildExploreQueueItemKeyFromItem = (item) => {
  const mediaType = normalizeExploreQueueMediaType(item?.media_type)
  const tmdbId = toValidTmdbId(item?.tmdb_id || item?.tmdbid)
  if (tmdbId) return `tmdb:${mediaType}:${tmdbId}`
  const doubanId = String(item?.douban_id || item?.id || '').trim()
  if (doubanId) return `douban:${mediaType}:${doubanId}`
  return ''
}

const buildExploreQueueItemKeyFromTask = (task) => {
  const key = String(task?.item_key || '').trim()
  if (key) return key
  const mediaType = normalizeExploreQueueMediaType(task?.media_type)
  const tmdbId = toValidTmdbId(task?.tmdb_id)
  if (tmdbId) return `tmdb:${mediaType}:${tmdbId}`
  const doubanId = String(task?.douban_id || '').trim()
  if (doubanId) return `douban:${mediaType}:${doubanId}`
  return ''
}

const syncExploreQueueItemStates = () => {
  for (const section of exploreSections.value) {
    for (const item of section.items || []) {
      const itemKey = buildExploreQueueItemKeyFromItem(item)
      item.saving = Boolean(itemKey) && queueActiveSaveKeys.value.has(itemKey)
    }
  }
  for (const item of results.value) {
    const itemKey = buildExploreQueueItemKeyFromItem(item)
    item.saving = Boolean(itemKey) && queueActiveSaveKeys.value.has(itemKey)
    if (!item.saving) {
      item.queuePosition = null
    }
  }
  triggerRef(exploreSections)
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
  scheduleExploreQueuePolling()
}

const stopExploreQueuePolling = () => {
  if (exploreQueuePollTimer) {
    clearInterval(exploreQueuePollTimer)
    exploreQueuePollTimer = null
  }
}

const scheduleExploreQueuePolling = () => {
  if (exploreQueuePollTimer) return
  exploreQueuePollTimer = window.setInterval(() => {
    fetchExploreQueueActiveTasks()
  }, EXPLORE_QUEUE_POLL_INTERVAL_MS)
}

const fetchExploreQueueActiveTasks = async () => {
  if (exploreQueuePolling) return
  exploreQueuePolling = true
  try {
    const { data } = await searchApi.getExploreActiveQueueTasks('save')
    const tasks = Array.isArray(data?.tasks) ? data.tasks : []
    applyExploreQueueTaskSnapshot(tasks)
    const hasActiveTasks = tasks.length > 0 || queueActiveSaveKeys.value.size > 0
    if (hasActiveTasks) {
      scheduleExploreQueuePolling()
    } else {
      stopExploreQueuePolling()
    }
  } catch (error) {
    console.error('Failed to poll explore queue tasks:', error)
  } finally {
    exploreQueuePolling = false
  }
}

const startExploreQueuePolling = () => {
  fetchExploreQueueActiveTasks()
}

const applySubscribedFlags = () => {
  for (const item of results.value) {
    markSubscribedOnItem(item)
    markEmbyOnItem(item)
  }
  for (const section of exploreSections.value) {
    for (const item of section.items || []) {
      markSubscribedOnItem(item)
      markEmbyOnItem(item)
    }
  }
  triggerRef(exploreSections)
}

const refreshSubscribedKeys = async () => {
  try {
    const { data } = await subscriptionApi.listForStatus()

    // 处理新的返回格式：{ items: [], douban_id_map: {}, imdb_id_map: {} }
    const items = Array.isArray(data) ? data : (data.items || [])
    const doubanIdMap = data.douban_id_map || {}
    const imdbIdMap = data.imdb_id_map || {}

    const next = new Set()
    const nextMap = new Map()
    const nextDoubanIds = new Set()
    const nextImdbIds = new Set()

    // 处理 tmdb_id 订阅
    for (const sub of items) {
      const key = buildSubscribedKey(sub.media_type, sub.tmdb_id)
      const id = Number(sub.id || 0)
      if (key) {
        next.add(key)
        if (id > 0) nextMap.set(key, id)
      }
      // 同时收集 douban_id 和 imdb_id
      if (sub.douban_id) {
        nextDoubanIds.add(String(sub.douban_id))
      }
      if (sub.imdb_id) {
        nextImdbIds.add(String(sub.imdb_id).toLowerCase())
      }
    }

    // 从 douban_id_map 补充豆瓣ID（兼容旧数据）
    for (const [doubanId, info] of Object.entries(doubanIdMap)) {
      nextDoubanIds.add(String(doubanId))
    }

    // 从 imdb_id_map 补充 IMDB ID
    for (const [imdbId, info] of Object.entries(imdbIdMap)) {
      nextImdbIds.add(String(imdbId).toLowerCase())
    }

    subscribedKeys.value = next
    subscribedIdMap.value = nextMap
    subscribedDoubanIds.value = nextDoubanIds
    subscribedImdbIds.value = nextImdbIds
    applySubscribedFlags()
  } catch (error) {
    console.error('Failed to refresh subscribed keys:', error)
  }
}

const goToDetail = (mediaType, tmdbId) => {
  if (!tmdbId) return
  clearSearchReturnContext()
  let path = `/movie/${tmdbId}`
  if (mediaType === 'tv') path = `/tv/${tmdbId}`
  if (mediaType === 'person') path = `/person/${tmdbId}`
  router.push({
    path,
    query: { from: route.fullPath }
  })
}

const goToDoubanDetail = (item) => {
  const doubanId = String(item?.douban_id || item?.id || '').trim()
  if (!doubanId) return false
  const mediaType = item?.media_type === 'tv' ? 'tv' : 'movie'
  clearSearchReturnContext()
  router.push({
    path: `/douban/${mediaType}/${encodeURIComponent(doubanId)}`,
    query: { from: route.fullPath }
  })
  return true
}

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w500'
const POSTER_FALLBACK_URL = new URL('/no-poster.png', import.meta.url).href
const CARD_GAP = EXPLORE_CARD_GAP
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
let exploreContainerResizeObserver = null
let sectionResizeObserver = null
let pressScrollTimer = null
let scrollStateRafId = 0
const pendingScrollStateKeys = new Set()
const cardsPerViewRef = ref(initialExploreCardLayout.cardsPerView)
const EXPLORE_SKELETON_SECTION_COUNT = 4
const exploreSkeletonCardCount = computed(() => {
  const perView = Number(cardsPerViewRef.value) || 6
  return Math.max(4, Math.min(8, perView))
})
const homeSectionMetaMap = new Map()
const homeSectionLoadPromises = new Map()
const homeSectionPrefetchTimers = new Map()

const calculateCardWidth = () => {
  const measuredWidth = exploreContainerRef.value?.clientWidth || 0
  const width = measuredWidth > 0 ? measuredWidth : estimateExploreContainerWidth()
  const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : width
  const layout = resolveExploreCardLayout(width, viewportWidth)
  if (layout.cardWidth === cardWidth.value && layout.cardsPerView === cardsPerViewRef.value) {
    return
  }
  cardWidth.value = layout.cardWidth
  cardsPerViewRef.value = layout.cardsPerView
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


const getExploreSectionByKey = (sectionKey) => {
  return exploreSections.value.find((section) => section.key === sectionKey) || null
}

const normalizeExploreSectionItems = (items = [], rankStart = 1) => {
  return items.map((item, index) => {
    const normalized = {
      ...item,
      id: item.id,
      douban_id: item.douban_id || item.id,
      media_type: item.media_type || 'movie',
      rank: item.rank || rankStart + index,
      isSubscribed: false,
      isInEmby: false,
      isInFeiniu: false,
      isInMediaLibrary: false,
      embyChecking: false,
      subscribing: false,
      saving: false,
      justSaved: false
    }
    markSubscribedOnItem(normalized)
    markEmbyOnItem(normalized)
    const itemKey = buildExploreQueueItemKeyFromItem(normalized)
    normalized.saving = Boolean(itemKey) && queueActiveSaveKeys.value.has(itemKey)
    return normalized
  })
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

const handleExploreSubscribe = async (item) => {
  if (!item) return
  const mediaType = item.media_type === 'tv' ? 'tv' : 'movie'
  const tmdbId = toValidTmdbId(item.tmdb_id || item.tmdbid)
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
    await refreshSubscribedKeys()
  } catch (error) {
    item.isSubscribed = !item.isSubscribed
    ElMessage.error(error.response?.data?.detail || error.message || '操作失败')
  } finally {
    item.subscribing = false
  }
}

const enqueueMediaSaveTask = async (item, payload) => {
  if (!item || !payload) return
  if (!payload.tmdb_id && !payload.douban_id && !payload.id) {
    ElMessage.warning(withTitleHint(item, '缺少可用条目标识，无法加入转存队列'))
    return
  }
  if (item.saving) {
    ElMessage.info(withTitleHint(item, '该条目已在转存队列中'))
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

const handleExploreSave = async (item) => {
  if (!item) return
  const payload = buildExploreQueuePayload(item, { exploreSource: exploreSource.value })
  await enqueueMediaSaveTask(item, payload)
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
  if (!section || !Array.isArray(section.displayItems)) return 0
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
  if (!section || !Array.isArray(section.displayItems)) return
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
  const sectionSource = exploreSource.value
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
    mergeEmbyStatusMap(payload?.emby_status_map || {})
    mergeFeiniuStatusMap(payload?.feiniu_status_map || {})
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
  if (!path) return POSTER_FALLBACK_URL
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
  return POSTER_FALLBACK_URL
}

const isPriorityExplorePoster = (sectionIndex, itemIndex) => {
  return Number(sectionIndex) === 0 && Number(itemIndex) < EXPLORE_HERO_POSTER_COUNT
}

const handleImageError = (e) => {
  const target = e?.target
  if (!target) return
  target.onerror = null
  if (target.src === POSTER_FALLBACK_URL || target.currentSrc === POSTER_FALLBACK_URL) return
  target.src = POSTER_FALLBACK_URL
}

const getMediaTypeLabel = (type) => {
  const labels = {
    movie: '电影',
    tv: '电视剧',
    collection: '合集',
    person: '人物',
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
  const sourceService = item.source_service || fallbackService || 'tmdb'
  const shareLink = item.pan115_share_link || item.share_link || item.share_url || item.url || item.link || ''
  const isPansouResult = sourceService === 'pansou'
  const explicitTmdbId = toValidTmdbId(item.tmdbid || item.tmdb_id)
  const normalizedId = explicitTmdbId || item.id || `${sourceService}-${index}`
  const normalized = {
    ...item,
    id: normalizedId,
    tmdb_id: explicitTmdbId || (sourceService === 'tmdb' ? toValidTmdbId(item.id) : null),
    media_type: item.media_type || (isPansouResult ? 'resource' : ''),
    poster_path: item.media_type === 'person'
      ? (item.profile_path || item.poster || item.poster_path)
      : (item.poster || item.poster_path),
    profile_path: item.profile_path || (item.media_type === 'person' ? item.poster_path : ''),
    known_for_department: item.known_for_department || '',
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
    isInEmby: false,
    isInFeiniu: false,
    isInMediaLibrary: false,
    embyChecking: false,
    subscribing: false,
    saving: false
  }
  markEmbyOnItem(normalized)
  return normalized
}

const fetchExploreSections = async () => {
  const requestId = ++exploreSectionsRequestId
  const source = exploreSource.value
  exploreLoading.value = true
  exploreUseLazySections.value = false
  try {
    // 一次性把 9 个分区 + emby/feiniu 角标全部拉回，避免 row 各自请求带来的 9 次 RTT 与重复角标查询
    const { data } = await searchApi.getExploreSections(source, 12, false)
    if (requestId !== exploreSectionsRequestId || source !== exploreSource.value) return
    const sourceSections = Array.isArray(data?.sections) ? data.sections : []

    if (source === 'tmdb') {
      const errors = Array.isArray(data?.errors) ? data.errors : []
      const hasUnconfigured = errors.some((entry) => {
        const detail = String(entry?.error || '')
        return detail.includes('TMDB_API_KEY is not configured') || detail.includes('TMDB API Key 未配置')
      })
      if (hasUnconfigured && !sourceSections.length) {
        tmdbConfigured.value = false
        exploreSections.value = []
        return
      }
      tmdbConfigured.value = true
    } else {
      tmdbConfigured.value = true
    }

    mergeEmbyStatusMap(data?.emby_status_map || {})
    mergeFeiniuStatusMap(data?.feiniu_status_map || {})

    const responseSource = String(data?.source || '')
    if (source === 'douban' && responseSource.startsWith('fallback:')) {
      ElMessage.warning('豆瓣榜单暂不可用，已展示备用榜单。请检查设置中的代理地址/端口是否正确。')
    }

    exploreSections.value = sourceSections.map((section) => {
      const items = Array.isArray(section?.items) ? section.items : []
      return {
        ...section,
        total: Number(section.total) || items.length,
        items
      }
    })
    scheduleLibraryBadgeSync()
  } catch (error) {
    if (requestId !== exploreSectionsRequestId || source !== exploreSource.value) return
    if (source === 'tmdb') {
      const detail = String(error?.response?.data?.detail || error?.message || '')
      if (detail.includes('TMDB API Key 未配置') || detail.includes('TMDB_API_KEY')) {
        tmdbConfigured.value = false
        exploreSections.value = []
        return
      }
    }
    const loaded = await loadExploreSectionsFromMeta(source)
    if (loaded) {
      ElMessage.warning('批量榜单加载失败，已切换为分区按需加载')
      return
    }
    const detail = String(error?.response?.data?.detail || error?.message || '')
    if (source === 'tmdb') {
      ElMessage.error(detail.includes('TMDB') ? detail : `TMDB 榜单加载失败：${detail || '请检查代理或 API Key 配置'}`)
    } else {
      ElMessage.error(detail || '探索榜单加载失败')
    }
    console.error('Failed to fetch explore sections:', error)
  } finally {
    if (requestId === exploreSectionsRequestId) {
      exploreLoading.value = false
    }
  }
}

const loadExploreSectionsFromMeta = async (source) => {
  try {
    const { data } = await searchApi.getExploreMeta(source)
    const rows = Array.isArray(data?.sections) ? data.sections : []
    if (!rows.length) return false
    if (source === 'tmdb') {
      tmdbConfigured.value = data?.tmdb_configured !== false
      if (!tmdbConfigured.value) {
        exploreSections.value = []
        return true
      }
    } else {
      tmdbConfigured.value = true
    }
    exploreUseLazySections.value = true
    exploreSections.value = rows.map((section) => ({
      key: section.key,
      title: section.title,
      tag: section.tag,
      total: 0,
      items: []
    }))
    return true
  } catch (metaError) {
    console.error('Failed to load explore meta fallback:', metaError)
    return false
  }
}

const handleTmdbConfigured = async () => {
  tmdbConfigured.value = true
  await initializeExploreHome()
}

const initializeExploreHome = async () => {
  const tasks = [
    fetchExploreSections(),
    refreshSubscribedKeys(),
    refreshFollowedPersonIds(),
    fetchExploreQueueActiveTasks()
  ]
  await Promise.allSettled(tasks)
  await nextTick()
  calculateCardWidth()
  setupExploreContainerResizeObserver()
  cleanupSectionResizeObserver()
  setupSectionResizeObserver()
  refreshAllSectionScrollStates()
}

const clearHomePrefetchTimers = () => {
  for (const timer of homeSectionPrefetchTimers.values()) {
    clearTimeout(timer)
  }
  homeSectionPrefetchTimers.clear()
}

/** 同步搜索关键词到地址栏（必须走 Vue Router，避免 replaceState 与路由状态脱节导致侧栏无法跳转） */
const replaceSearchBarUrl = async (keyword, page = 1) => {
  if (!isSearchRouteActive() || router.currentRoute.value.name !== 'Search') return
  const syncToken = getSearchRouteSyncToken()
  const targetPath = `/explore/${exploreSource.value}`
  const normalized = String(keyword || '').trim()
  const nextQuery = { ...route.query }
  if (normalized) {
    nextQuery.q = normalized
    if (page > 1) {
      nextQuery.page = String(page)
    } else {
      delete nextQuery.page
    }
  } else {
    delete nextQuery.q
    delete nextQuery.page
  }
  await nextTick()
  if (syncToken !== getSearchRouteSyncToken() || !isSearchRouteActive()) {
    await restorePendingLeaveNavigation(router)
    return
  }
  try {
    await router.replace({
      path: targetPath,
      query: nextQuery
    })
  } catch {
    // 忽略重复导航
  }
  if (syncToken !== getSearchRouteSyncToken()) {
    await nextTick()
    await restorePendingLeaveNavigation(router)
  }
}

const resetSearchUI = () => {
  searched.value = false
  results.value = []
  totalPages.value = 0
  currentPage.value = 1
  lastSearchKeyword.value = ''
  activeSearchService.value = ''
}

const runSearchRequest = async (keyword, page = 1) => {
  const normalized = String(keyword || '').trim()
  if (!normalized) return

  lastSearchKeyword.value = normalized
  currentPage.value = Math.max(1, Number(page) || 1)
  loading.value = true
  searched.value = true

  try {
    const { data } = await searchApi.search(normalized, currentPage.value)
    const items = data.items || data.results || []
    mergeEmbyStatusMap(data?.emby_status_map || {})
    mergeFeiniuStatusMap(data?.feiniu_status_map || {})
    activeSearchService.value = data.search_service || ''
    results.value = items.map((item, index) =>
      normalizeSearchResultItem(item, index, activeSearchService.value)
    )
    applySubscribedFlags()
    applyFollowedFlags()
    const backendPages = Number(data.total_pages) || 0
    totalPages.value = backendPages || (results.value.length > 0 ? 1 : 0)
    await replaceSearchBarUrl(normalized, currentPage.value)
  } catch (error) {
    console.error('Search failed:', error)
    ElMessage.error(error.response?.data?.detail || '搜索失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

const restoreSearchFromRoute = async () => {
  const keyword = String(route.query.q || '').trim()
  if (!keyword) return false
  const page = Math.max(1, Number(route.query.page) || 1)
  searchQuery.value = keyword
  await runSearchRequest(keyword, page)
  return true
}

const handleBackToExplore = async () => {
  clearSearchReturnContext()
  resetSearchUI()
  await replaceSearchBarUrl('')
  if (!exploreSections.value.length) {
    await initializeExploreHome()
  }
}

const handleSearch = async () => {
  const keyword = String(searchQuery.value || '').trim()
  if (!keyword) {
    ElMessage.warning('请输入关键词')
    return
  }
  currentPage.value = 1
  await runSearchRequest(keyword, 1)
}

const handlePageChange = (page) => {
  const keyword = String(lastSearchKeyword.value || searchQuery.value || '').trim()
  if (!keyword) return
  runSearchRequest(keyword, page)
}

const openSearchResultDetail = (mediaType, id) => {
  if (!id) return
  saveSearchReturnContext({
    path: route.path,
    keyword: lastSearchKeyword.value,
    page: currentPage.value
  })
  const path = mediaType === 'tv' ? `/tv/${id}` : `/movie/${id}`
  router.push({
    path,
    query: { from: route.fullPath }
  })
}

const resolveSearchResultTarget = (item) => {
  const mediaType = item?.media_type
  if (mediaType === 'collection') return { mediaType: 'collection', tmdbId: null }
  if (mediaType === 'person') {
    return {
      mediaType: 'person',
      tmdbId: toValidTmdbId(item?.tmdb_id || item?.tmdbid || item?.id)
    }
  }
  if (mediaType !== 'movie' && mediaType !== 'tv') return null
  return {
    mediaType,
    tmdbId: toValidTmdbId(item?.tmdb_id || item?.tmdbid || item?.id)
  }
}

const handleItemClick = (item) => {
  if (item.isPansouResult) return
  const target = resolveSearchResultTarget(item)
  if (!target) return

  if (target.mediaType === 'collection') {
    ElMessage.info('合集结果暂不支持直接打开详情，请选择具体电影或剧集')
    return
  }

  if (!target.tmdbId) {
    ElMessage.warning('未找到有效的详情 ID')
    return
  }

  if (target.mediaType === 'movie') {
    warmupPan115Resources('movie', target.tmdbId)
    openSearchResultDetail('movie', target.tmdbId)
  } else if (target.mediaType === 'tv') {
    warmupPan115Resources('tv', target.tmdbId)
    openSearchResultDetail('tv', target.tmdbId)
  } else if (target.mediaType === 'person') {
    saveSearchReturnContext({
      path: route.path,
      keyword: lastSearchKeyword.value,
      page: currentPage.value
    })
    router.push({ path: `/person/${target.tmdbId}`, query: { from: route.fullPath } })
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

const refreshFollowedPersonIds = async () => {
  try {
    const { data } = await personFollowApi.getStatusMap()
    const map = data?.person_id_map || {}
    followedPersonIds.value = new Set(Object.keys(map))
    applyFollowedFlags()
  } catch (error) {
    console.error('Failed to refresh followed persons:', error)
  }
}

const applyFollowedFlags = () => {
  for (const item of results.value) {
    if (item.media_type === 'person') {
      const personId = String(item.tmdb_id || item.id || '')
      item.isFollowed = followedPersonIds.value.has(personId)
    }
  }
}

const handleFollowPerson = async (item) => {
  const personId = toValidTmdbId(item.tmdb_id || item.id)
  if (!personId) {
    ElMessage.warning('未找到有效的演职员 ID')
    return
  }
  item.following = true
  try {
    const { data } = await personFollowApi.toggle({
      tmdb_person_id: personId,
      name: item.name || item.title,
      profile_path: item.profile_path || item.poster_path,
      known_for_department: item.known_for_department
    })
    if (data.followed) {
      followedPersonIds.value.add(String(personId))
      item.isFollowed = true
      ElMessage.success('已关注')
    } else {
      followedPersonIds.value.delete(String(personId))
      item.isFollowed = false
      ElMessage.success('已取消关注')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '关注操作失败')
  } finally {
    item.following = false
  }
}

const handleSubscribe = async (item) => {
  if (item.isPansouResult || item.media_type === 'resource') {
    ElMessage.warning('盘搜资源不支持订阅')
    return
  }
  if (item.media_type === 'person') {
    await handleFollowPerson(item)
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

const handleSave = async (item) => {
  if (item.isPansouResult && !item.pan115_share_link) {
    ElMessage.warning('该盘搜结果没有可转存的 115 分享链接')
    return
  }

  if (item.isPansouResult) {
    if (item.saving) {
      ElMessage.info('该条目正在转存中')
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
      ElMessage.success(`「${resourceName}」转存完成`)
    } catch (error) {
      const reason = error.response?.data?.detail || error.message || '转存失败'
      ElMessage.error(`「${item.title || item.name || ''}」${reason}`)
    } finally {
      item.saving = false
    }
    return
  }

  if (item.media_type === 'person') {
    ElMessage.warning('人物不支持转存')
    return
  }

  const payload = buildTmdbSavePayload(item)
  await enqueueMediaSaveTask(item, payload)
}

const setupExploreContainerResizeObserver = () => {
  cleanupExploreContainerResizeObserver()
  if (typeof ResizeObserver === 'undefined' || !exploreContainerRef.value) return
  exploreContainerResizeObserver = new ResizeObserver(() => {
    calculateCardWidth()
    refreshAllSectionScrollStates()
  })
  exploreContainerResizeObserver.observe(exploreContainerRef.value)
}

const cleanupExploreContainerResizeObserver = () => {
  if (exploreContainerResizeObserver) {
    exploreContainerResizeObserver.disconnect()
    exploreContainerResizeObserver = null
  }
}

const handleCopyPanShareLink = async (item) => {
  const shareLink = String(item?.pan115_share_link || item?.share_link || item?.share_url || '').trim()
  if (!shareLink) {
    ElMessage.warning('该结果没有可复制的分享链接')
    return
  }
  try {
    await copyText(shareLink)
    ElMessage.success('已复制分享链接')
  } catch (error) {
    ElMessage.error(error.message || '复制失败')
  }
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
  exploreSections.value = []
  exploreUseLazySections.value = false
}

onMounted(async () => {
  calculateCardWidth()
  loadResourcePriority()
  const restored = await restoreSearchFromRoute()
  if (!restored) {
    await initializeExploreHome()
  } else {
    await refreshFollowedPersonIds()
  }
  startExploreQueuePolling()
})

onBeforeRouteLeave((to) => {
  searchPageEngaged.value = false
  markSearchRouteLeave(to.fullPath)
  stopExploreQueuePolling()
})

onActivated(() => {
  searchPageEngaged.value = true
  startExploreQueuePolling()
})

onDeactivated(() => {
  searchPageEngaged.value = false
  stopExploreQueuePolling()
})

watch(
  () => {
    if (!isSearchRouteActive()) return null
    return `${String(route.query.q || '').trim()}|${String(route.query.page || '1')}`
  },
  async (signature, previous) => {
    if (signature === null) return
    if (previous === undefined) return
    if (signature === previous) return
    const keyword = String(route.query.q || '').trim()
    if (!keyword) {
      if (searched.value) {
        clearSearchReturnContext()
        resetSearchUI()
        await replaceSearchBarUrl('')
        if (!exploreSections.value.length) {
          await initializeExploreHome()
        }
      }
      return
    }
    if (
      keyword === lastSearchKeyword.value
      && Number(route.query.page || 1) === currentPage.value
      && searched.value
      && results.value.length > 0
    ) {
      return
    }
    await restoreSearchFromRoute()
  }
)

watch(exploreSource, async (newSource, oldSource) => {
  if (!isSearchRouteActive()) return
  if (newSource === oldSource) return
  resetExploreState()
  await initializeExploreHome()
})

onBeforeUnmount(() => {
  cleanupExploreContainerResizeObserver()
  cleanupSectionResizeObserver()
  stopExploreQueuePolling()
  libraryBadgeSyncer?.dispose()
  libraryBadgeSyncer = null
})
</script>

<style lang="scss" scoped>
.explore-page {
  animation: explorePageFadeIn 0.22s ease;
  
  .search-header {
    margin-bottom: 24px;
    padding: 0;
    border: 0;
    background: transparent;
    box-shadow: none;
    
    :deep(.el-input) {
      --search-pill-bg: var(--ms-bg-elevated);
      width: 100%;

      .el-input__wrapper {
        border-radius: 10px 0 0 10px;
        min-height: 44px;
        padding: 0 12px;
        background: var(--search-pill-bg);
        box-shadow: none;
      }

      &.is-focus .el-input__wrapper {
        box-shadow: 0 0 0 1px var(--ms-accent-primary);
      }

      .el-input-group__append {
        padding: 0;
        border-radius: 0 10px 10px 0;
        background: transparent;
        box-shadow: none;

        .el-button {
          border-radius: 0 10px 10px 0;
          height: 44px;
          padding: 0 20px;
          margin: 0;
          border: none;
          font-weight: 500;

          .el-icon {
            margin-right: 4px;
          }
        }
      }
    }
  }

  .explore-section {
    margin-bottom: 28px;
    padding: 24px;
    border: 1px solid var(--ms-border-color);
    border-radius: var(--ms-radius-lg, 10px);
    background: var(--ms-bg-card);
    position: relative;

    .section-header {
      margin-bottom: 20px;

      .section-title {
        h2 {
          margin: 0;
          font-size: 22px;
          font-weight: 700;
          line-height: 1.35;
          color: var(--ms-text-primary);
        }
      }

      p {
        margin: 10px 0 0;
        color: var(--ms-text-muted);
        font-size: 13px;
      }
    }

    .explore-skeleton {
      .skeleton-group {
        padding-top: 16px;

        &:not(:first-child) {
          margin-top: 12px;
          border-top: 1px solid var(--ms-border-color);
        }
      }

      .skeleton-group-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 14px;

        .group-title {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .skeleton-title-line {
          width: 120px;
          height: 18px;
        }

        .skeleton-action-line {
          width: 40px;
          height: 16px;
        }
      }

      .skeleton-line {
        border-radius: 6px;
        background: var(--ms-bg-hover);
        animation: explore-skeleton-shimmer 1.2s ease-in-out infinite;
      }

      .skeleton-row {
        display: flex;
        gap: 16px;
        overflow: hidden;
        padding-bottom: 8px;

        .skeleton-card {
          width: var(--recommend-card-width, 188px);
          min-width: var(--recommend-card-width, 188px);
        }

        .skeleton-poster {
          aspect-ratio: 2 / 3;
          border-radius: var(--ms-radius-md, 8px);
          background: var(--ms-bg-hover);
          animation: explore-skeleton-shimmer 1.2s ease-in-out infinite;
        }

        .skeleton-title {
          height: 14px;
          margin: 10px 12px 0;
          border-radius: 4px;
          background: var(--ms-bg-hover);
          animation: explore-skeleton-shimmer 1.2s ease-in-out infinite;
        }
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

        .group-title h3 {
          margin: 0;
          color: var(--ms-text-primary);
          font-size: 16px;
          font-weight: 600;
          line-height: 1.35;
        }

        .group-actions {
          display: flex;
          gap: 8px;
        }
      }

      .row-shell {
        position: relative;

        .side-scroll-btn {
          position: absolute;
          top: 50%;
          transform: translateY(-50%);
          z-index: 3;
          border-color: var(--ms-border-color);
          background: var(--ms-bg-card);
          color: var(--ms-text-primary);
          transition: border-color 0.2s ease, background-color 0.2s ease;
          
          &:hover {
            border-color: var(--ms-border-light);
            background: var(--ms-bg-elevated);
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
        border-radius: var(--ms-radius-md, 8px);
        cursor: pointer;
        border: 1px solid var(--ms-border-color);
        background: var(--ms-bg-card);
        transition: border-color 0.2s ease, background-color 0.2s ease;
        overflow: hidden;

        &:hover {
          border-color: var(--ms-border-light);
          background: var(--ms-bg-elevated);
        }

        &.just-saved {
          border-color: var(--ms-accent-success);
          animation: none;
        }

        .poster-wrapper {
          position: relative;
          aspect-ratio: 2 / 3;
          background: var(--ms-bg-elevated);
          overflow: hidden;

          .emby-badge {
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 4;
          }

          img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            user-select: none;
            -webkit-user-drag: none;
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
            }
          }

          &:hover .explore-card-actions,
          &:focus-within .explore-card-actions {
            opacity: 1;
            transform: translate(-50%, 0);
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
    border: 1px solid var(--ms-border-color);
    border-radius: var(--ms-radius-lg, 10px);
    padding: 20px;
    background: var(--ms-bg-card);

    .results-skeleton-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 20px;
    }

    .skeleton-card {
      border-radius: var(--ms-radius-md, 8px);
      overflow: hidden;
      border: 1px solid var(--ms-border-color);
      background: var(--ms-bg-card);
    }

    .skeleton-poster {
      aspect-ratio: 2 / 3;
      background: var(--ms-bg-hover);
      animation: search-skeleton-shimmer 1.2s ease-in-out infinite;
    }

    .skeleton-title {
      height: 14px;
      margin: 10px 12px 12px;
      border-radius: 4px;
      background: var(--ms-bg-hover);
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
    border-radius: var(--ms-radius-md, 8px);
    border: 1px solid var(--ms-border-color);
    background: var(--ms-bg-card);
    transition: border-color 0.2s ease, background-color 0.2s ease;
    overflow: hidden;

    &.pansou-card {
      cursor: default;
    }

    &:hover {
      border-color: var(--ms-border-light);
      background: var(--ms-bg-elevated);

      .action-buttons {
        opacity: 1;
      }
    }

    .poster-wrapper {
      position: relative;
      aspect-ratio: 2/3;
      background: var(--ms-bg-elevated);
      overflow: hidden;

      .emby-badge {
        position: absolute;
        top: 10px;
        right: 10px;
        z-index: 4;
      }

      img {
        width: 100%;
        height: 100%;
        object-fit: cover;
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
        background: var(--ms-accent-warning);
        color: #fff;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: 700;

        &.has-emby {
          top: 46px;
        }
      }

      .action-buttons {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        display: flex;
        justify-content: space-between;
        padding: 12px;
        background: rgba(17, 24, 39, 0.88);
        opacity: 1;
        transition: opacity 0.2s ease;

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
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

@keyframes explore-skeleton-shimmer {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

@media (max-width: 1024px) {
  .explore-page {
    .explore-section,
    .search-results {
      padding: 18px;
      border-radius: 18px;
    }

    .explore-section {
      .section-header {
        margin-bottom: 16px;

        .section-title h2 {
          font-size: 18px;
        }
      }

      .recommend-group,
      .skeleton-group {
        .group-header,
        .skeleton-group-header {
          align-items: flex-start;
          gap: 8px;
        }

        .group-title {
          flex: 1;
          min-width: 0;
        }

        .group-title h3,
        .skeleton-group-header .group-title .skeleton-title-line {
          font-size: 15px;
        }
      }
    }

    .search-results {
      .results-header {
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;

        h3 {
          font-size: 16px;
          line-height: 1.35;
        }

        .results-meta {
          flex-wrap: wrap;
          gap: 6px;
        }
      }
    }

    .results-grid {
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 16px;
    }
  }
}

@media (max-width: 768px) {
  .explore-page {
    .search-header {
      margin-bottom: 18px;
    }

    .explore-section,
    .search-results {
      padding: 14px;
      border-radius: 16px;
    }

    .explore-section {
      .section-header {
        margin-bottom: 14px;

        .section-title h2 {
          font-size: 17px;
          line-height: 1.3;
        }
      }

      .recommend-group,
      .skeleton-group {
        padding-top: 12px;
      }

      .recommend-group {
        .row-shell {
          .side-scroll-btn {
            display: none;
          }
        }

        .recommend-row {
          gap: 10px;
        }
      }
    }

    .search-results {
      min-height: 160px;

      .results-skeleton-grid,
      .results-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
      }

      .results-header {
        gap: 6px;

        h3 {
          font-size: 15px;
        }
      }
    }

    .media-card {
      border-radius: 12px;

      .poster-wrapper {
        .action-buttons {
          opacity: 1;
          gap: 4px;
          padding: 6px;

          .action-btn {
            flex: 1 1 0;
            min-width: 0;
            padding-inline: 6px;
            font-size: 10px;
          }
        }
      }

      .media-info {
        padding: 10px;

        .title {
          white-space: normal;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          font-size: 13px;
        }

        .year {
          align-items: flex-start;
          flex-direction: column;
          gap: 2px;
          margin-bottom: 0;
          font-size: 11px;
        }

        .overview {
          display: none;
        }
      }
    }

    .pagination-wrapper {
      margin-top: 20px;
      overflow-x: auto;
    }
  }

  .explore-page .search-header :deep(.el-input .el-input__wrapper) {
    min-height: 40px;
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

@media (max-width: 480px) {
  .explore-page {
    .search-results {
      padding: 10px;

      .results-skeleton-grid,
      .results-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
    }

    .media-card {
      border-radius: 12px;

      .poster-wrapper {
        .action-buttons {
          opacity: 1;
          gap: 4px;
          padding: 8px;

          .action-btn {
            flex: 1 1 0;
            min-width: 0;
            padding-inline: 4px;
            font-size: 11px;

            .el-icon {
              font-size: 13px;
            }
          }
        }

        .rating-badge {
          font-size: 11px;
          padding: 3px 7px;
        }

        .media-type-tag .el-tag {
          font-size: 10px;
          padding: 0 6px;
          height: 20px;
          line-height: 20px;
        }
      }

      .media-info {
        padding: 10px;

        .title {
          font-size: 13px;
          -webkit-line-clamp: 2;
          line-height: 1.3;
          margin-bottom: 4px;
        }

        .year {
          font-size: 11px;
        }

        .overview {
          display: none;
        }
      }
    }
  }
}

@media (hover: none) {
  .explore-page {
    .media-card .poster-wrapper .action-buttons {
      opacity: 1;
    }

    .explore-section .recommend-group .recommend-card .poster-wrapper .explore-card-actions {
      opacity: 1;
      transform: translate(-50%, 0);
    }
  }
}

@keyframes explorePageFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes skeleton-loading {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
</style>
