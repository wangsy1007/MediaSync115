<template>
  <div ref="containerRef" class="recommend-group">
    <div class="group-header">
      <div class="group-title">
        <h3>{{ section.title }}</h3>
        <el-tag size="small" type="info">{{ section.tag }}</el-tag>
        <span class="group-sub">{{ formatExploreCount(remoteTotal) }} 部</span>
      </div>
      <div class="group-actions">
        <el-button type="primary" link @click="handleOpenSection" style="font-size: 14px; padding: 8px 12px;">
          更多
        </el-button>
      </div>
    </div>

    <div v-if="loadError" class="row-state error">
      <span>{{ loadError }}</span>
      <el-button type="primary" link @click="fetchSection(true)">重试</el-button>
    </div>

    <div v-else-if="!loaded" class="skeleton-row">
      <div v-for="index in skeletonCardCount" :key="`skeleton-${index}`" class="skeleton-card">
        <div class="skeleton-poster" />
        <div class="skeleton-title" />
      </div>
    </div>

    <div v-else class="row-shell">
      <el-button
        class="side-scroll-btn left"
        circle
        size="small"
        :disabled="!scrollState.hasLeft"
        @click="scrollRow(-1)"
      >
        <el-icon><ArrowLeft /></el-icon>
      </el-button>
      <el-button
        class="side-scroll-btn right"
        circle
        size="small"
        :disabled="!scrollState.hasRight"
        @click="scrollRow(1)"
      >
        <el-icon><ArrowRight /></el-icon>
      </el-button>

      <div ref="rowRef" class="recommend-row" @scroll="updateScrollState">
        <el-card
          v-for="(item, itemIndex) in rowItems"
          :key="`${section.key}-${item.id}-${item.rank}`"
          class="recommend-card"
          :class="{ 'just-saved': item.justSaved }"
          shadow="hover"
          :body-style="{ padding: '0' }"
          @click="emit('item-click', item)"
        >
          <div class="poster-wrapper">
            <img
              :src="getPosterUrl(item.poster_url || item.poster_path, { compact: itemIndex >= PRIORITY_POSTER_COUNT })"
              :alt="item.title"
              :loading="itemIndex < PRIORITY_POSTER_COUNT ? 'eager' : 'lazy'"
              :fetchpriority="itemIndex < PRIORITY_POSTER_COUNT ? 'high' : 'auto'"
              decoding="async"
              draggable="false"
              @error="handleImageError"
            />
            <div class="rank-badge">#{{ item.rank }}</div>
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
                @click.stop="emit('subscribe', item)"
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
                @click.stop="emit('save', item)"
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

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, Star, FolderAdd } from '@element-plus/icons-vue'
import { searchApi } from '@/api'
import LibraryBadge from '@/components/media/LibraryBadge.vue'

const props = defineProps({
  source: {
    type: String,
    default: 'douban'
  },
  section: {
    type: Object,
    required: true
  },
  subscribedIdMap: {
    type: Object,
    default: () => new Map()
  },
  subscribedDoubanIds: {
    type: Object,
    default: () => new Set()
  },
  subscribedImdbIds: {
    type: Object,
    default: () => new Set()
  },
  queueActiveSubscribeKeys: {
    type: Object,
    default: () => new Set()
  },
  queueActiveSaveKeys: {
    type: Object,
    default: () => new Set()
  },
  embyStatusMap: {
    type: Object,
    default: () => new Map()
  },
  feiniuStatusMap: {
    type: Object,
    default: () => new Map()
  }
})

const emit = defineEmits(['item-click', 'subscribe', 'save', 'merge-emby-status', 'merge-feiniu-status', 'open-section'])

const HOME_SECTION_LIMIT = 12
const PRIORITY_POSTER_COUNT = 6
const DEFAULT_CARD_WIDTH = 188
const DESKTOP_ROW_GAP = 16
const MOBILE_ROW_GAP = 10
const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w500'
const rowItems = ref([])
const remoteTotal = ref(0)
const loaded = ref(false)
const loading = ref(false)
const loadError = ref('')
const rowRef = ref(null)
const containerRef = ref(null)
const containerWidth = ref(0)
const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
const scrollState = ref({ hasLeft: false, hasRight: false })
let intersectionObserver = null
let resizeObserver = null

const skeletonCardCount = computed(() => {
  const width = Math.max(containerWidth.value, 0)
  const gap = viewportWidth.value <= 768 ? MOBILE_ROW_GAP : DESKTOP_ROW_GAP
  const cardWidth = getRecommendCardWidth()
  if (!width || !cardWidth) return 6
  const estimatedCount = Math.ceil((width + gap) / (cardWidth + gap))
  return Math.max(2, Math.min(HOME_SECTION_LIMIT, estimatedCount))
})

const getRecommendCardWidth = () => {
  if (typeof window === 'undefined' || !containerRef.value) return DEFAULT_CARD_WIDTH
  const rawValue = window.getComputedStyle(containerRef.value).getPropertyValue('--recommend-card-width')
  const numericValue = Number.parseFloat(rawValue)
  return Number.isFinite(numericValue) && numericValue > 0 ? numericValue : DEFAULT_CARD_WIDTH
}

const updateSkeletonMetrics = () => {
  containerWidth.value = containerRef.value?.clientWidth || 0
  if (typeof window !== 'undefined') {
    viewportWidth.value = window.innerWidth
  }
}

const toValidTmdbId = (rawId) => {
  const id = Number(rawId)
  if (!Number.isFinite(id) || id <= 0) return null
  return Math.trunc(id)
}

const buildSubscribedKey = (mediaType, tmdbId) => {
  const normalizedType = mediaType === 'tv' ? 'tv' : (mediaType === 'movie' ? 'movie' : '')
  const normalizedTmdbId = toValidTmdbId(tmdbId)
  if (!normalizedType || !normalizedTmdbId) return ''
  return `${normalizedType}:${normalizedTmdbId}`
}

const buildExploreQueueItemKeyFromItem = (item) => {
  const mediaType = String(item?.media_type || '').toLowerCase() === 'tv' ? 'tv' : 'movie'
  const tmdbId = toValidTmdbId(item?.tmdb_id || item?.tmdbid)
  if (tmdbId) return `tmdb:${mediaType}:${tmdbId}`
  const doubanId = String(item?.douban_id || item?.id || '').trim()
  if (doubanId) return `douban:${mediaType}:${doubanId}`
  return ''
}

const markEmbyOnItem = (item) => {
  const key = buildSubscribedKey(item.media_type, item.tmdb_id || item.tmdbid)
  item.isInEmby = Boolean(key) && Boolean(props.embyStatusMap?.get?.(key)?.exists_in_emby)
  item.isInFeiniu = Boolean(key) && Boolean(props.feiniuStatusMap?.get?.(key)?.exists_in_feiniu)
  item.isInMediaLibrary = item.isInEmby || item.isInFeiniu
}

const applySubscribedFlag = (item) => {
  const key = buildSubscribedKey(item.media_type, item.tmdb_id || item.tmdbid)
  const doubanId = item.douban_id || item.id
  const imdbId = item.imdb_id
  item.isSubscribed = (
    Boolean(key) && props.subscribedIdMap?.has?.(key)
  ) || (
    doubanId && props.subscribedDoubanIds?.has?.(String(doubanId))
  ) || (
    imdbId && props.subscribedImdbIds?.has?.(String(imdbId).toLowerCase())
  )
  markEmbyOnItem(item)
  const itemKey = buildExploreQueueItemKeyFromItem(item)
  item.subscribing = Boolean(itemKey) && props.queueActiveSubscribeKeys?.has?.(itemKey)
  item.saving = Boolean(itemKey) && props.queueActiveSaveKeys?.has?.(itemKey)
}

const applyStateToItems = () => {
  for (const item of rowItems.value) {
    applySubscribedFlag(item)
  }
}

const normalizeItems = (items = [], rankStart = 1) => {
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
      subscribing: false,
      saving: false,
      justSaved: false
    }
    applySubscribedFlag(normalized)
    return normalized
  })
}

const formatExploreCount = (value) => {
  const total = Number(value) || 0
  if (total > 100) return '100+'
  return String(total)
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
  if (source.startsWith('/')) return rewriteTmdbPosterSize(`${TMDB_IMAGE_BASE}${source}`, compact)
  return new URL('/no-poster.png', import.meta.url).href
}

const handleImageError = (event) => {
  event.target.src = new URL('/no-poster.png', import.meta.url).href
}

const updateScrollState = () => {
  const row = rowRef.value
  if (!row) return
  const maxScrollLeft = Math.max(row.scrollWidth - row.clientWidth, 0)
  scrollState.value = {
    hasLeft: row.scrollLeft > 2,
    hasRight: row.scrollLeft < maxScrollLeft - 2
  }
}

const scrollRow = (direction) => {
  const row = rowRef.value
  if (!row) return
  const distance = Math.max(480, row.clientWidth * 0.85)
  row.scrollBy({
    left: direction * distance,
    behavior: 'smooth'
  })
}

const disconnectObserver = () => {
  if (intersectionObserver) {
    intersectionObserver.disconnect()
    intersectionObserver = null
  }
}

const setupObserver = () => {
  disconnectObserver()
  if (!containerRef.value || typeof IntersectionObserver === 'undefined') {
    return
  }
  intersectionObserver = new IntersectionObserver((entries) => {
    const entry = entries[0]
    if (!entry?.isIntersecting) return
    fetchSection()
    disconnectObserver()
  }, {
    rootMargin: '320px 0px'
  })
  intersectionObserver.observe(containerRef.value)
}

const fetchSection = async (force = false) => {
  if (loading.value) return
  if (loaded.value && !force) return
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await searchApi.getExploreSection(props.source, props.section.key, HOME_SECTION_LIMIT, force, 0)
    emit('merge-emby-status', data?.emby_status_map || {})
    emit('merge-feiniu-status', data?.feiniu_status_map || {})
    const payload = data?.section || {}
    const items = Array.isArray(payload.items) ? payload.items : []
    rowItems.value = normalizeItems(items, 1)
    remoteTotal.value = Number(payload.total) || rowItems.value.length
    loaded.value = true
    await nextTick()
    applyStateToItems()
    updateScrollState()
  } catch (error) {
    loadError.value = error.response?.data?.detail || error.message || '分区加载失败'
  } finally {
    loading.value = false
  }
}

const handleOpenSection = () => {
  emit('open-section', props.section.key)
}

watch(
  () => [
    props.subscribedIdMap,
    props.subscribedDoubanIds,
    props.subscribedImdbIds,
    props.queueActiveSubscribeKeys,
    props.queueActiveSaveKeys,
    props.embyStatusMap,
    props.feiniuStatusMap
  ],
  () => {
    applyStateToItems()
  }
)

watch(
  () => `${props.source}:${props.section?.key || ''}`,
  async () => {
    rowItems.value = []
    remoteTotal.value = 0
    loaded.value = false
    loading.value = false
    loadError.value = ''
    await nextTick()
    fetchSection()
  }
)

onMounted(() => {
  updateSkeletonMetrics()
  fetchSection()
  if (typeof ResizeObserver !== 'undefined' && containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      updateSkeletonMetrics()
    })
    resizeObserver.observe(containerRef.value)
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('resize', updateSkeletonMetrics)
  }
})

onBeforeUnmount(() => {
  disconnectObserver()
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', updateSkeletonMetrics)
  }
})
</script>

<style lang="scss" scoped>
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
  }

  .row-state {
    min-height: 120px;
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--ms-text-muted);
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
      border-radius: 14px;
      background: linear-gradient(
        90deg,
        rgba(89, 151, 226, 0.22) 25%,
        rgba(148, 205, 255, 0.34) 37%,
        rgba(89, 151, 226, 0.22) 63%
      );
      background-size: 300% 100%;
      animation: shimmer 1.2s ease-in-out infinite;
    }

    .skeleton-title {
      height: 14px;
      margin: 10px 12px 0;
      border-radius: 6px;
      background: linear-gradient(
        90deg,
        rgba(89, 151, 226, 0.22) 25%,
        rgba(148, 205, 255, 0.34) 37%,
        rgba(89, 151, 226, 0.22) 63%
      );
      background-size: 300% 100%;
      animation: shimmer 1.2s ease-in-out infinite;
    }
  }

  .row-shell {
    position: relative;

    .side-scroll-btn {
      position: absolute;
      top: 50%;
      transform: translateY(-50%);
      z-index: 3;
      border-color: rgba(45, 153, 255, 0.34);
      background: rgba(13, 35, 69, 0.85);
      color: var(--ms-text-primary);
      backdrop-filter: blur(8px);
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
    scrollbar-width: none;
    -ms-overflow-style: none;
    padding-bottom: 8px;
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

    .poster-wrapper {
      position: relative;
      aspect-ratio: 2 / 3;
      background: var(--ms-bg-elevated);
      overflow: hidden;

      img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        transition: transform 0.4s ease;
      }

      &:hover img {
        transform: scale(1.05);
      }

      .emby-badge {
        position: absolute;
        top: 10px;
        right: 10px;
        z-index: 4;
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
  }
}

@media (max-width: 768px) {
  .recommend-group {
    .skeleton-row {
      gap: 10px;
    }

    .recommend-row {
      gap: 10px;
    }

    .recommend-card {
      .card-info {
        padding: 9px 9px 11px;

        .title {
          font-size: 11px;
          -webkit-line-clamp: 1;
        }
      }
    }
  }

  .recommend-group .recommend-card .poster-wrapper .explore-card-actions {
    opacity: 1;
    transform: translate(-50%, 0);
  }
}

@media (hover: none) {
  .recommend-group .recommend-card .poster-wrapper .explore-card-actions {
    opacity: 1;
    transform: translate(-50%, 0);
  }
}

@keyframes shimmer {
  0% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0 50%;
  }
}
</style>
