<template>
  <div class="recommend-page">
    <div class="page-header">
      <div class="header-title">
        <h2>猜你想看</h2>
        <span v-if="generatedAtText" class="header-meta">上次生成：{{ generatedAtText }} · 共 {{ totalCount }} 部</span>
      </div>
      <div class="header-actions">
        <el-button
          type="primary"
          :loading="refreshing"
          :disabled="!ready"
          @click="handleRefresh"
        >
          刷新推荐
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!ready"
      type="warning"
      :closable="false"
      show-icon
      class="recommend-alert"
    >
      <span>推荐功能未启用或 LLM 未配置，请前往「设置 → AI 推荐」开启后再使用。</span>
    </el-alert>
    <el-alert
      v-else-if="error && !items.length"
      type="error"
      :closable="false"
      show-icon
      class="recommend-alert"
    >
      <span>{{ error }}</span>
    </el-alert>
    <el-alert
      v-else-if="profileSummary && !initialLoading"
      type="info"
      :closable="false"
      show-icon
      class="recommend-alert"
    >
      <span>本次画像：{{ profileSummary }}</span>
    </el-alert>

    <!-- 初始加载骨架 -->
    <div v-if="initialLoading" class="waterfall">
      <div v-for="n in PAGE_SIZE" :key="`sk-${n}`" class="waterfall-item skeleton-item">
        <div class="skeleton-poster" />
        <div class="skeleton-title" />
        <div class="skeleton-line" />
      </div>
    </div>

    <!-- 瀑布流 -->
    <div v-else-if="items.length" class="waterfall">
      <div
        v-for="(item, idx) in items"
        :key="`${item.media_type}-${item.tmdb_id}`"
        class="waterfall-item"
        :style="{ animationDelay: `${Math.min(idx % 10, 5) * 0.06}s` }"
      >
        <el-card
          class="recommend-card"
          shadow="hover"
          :body-style="{ padding: '0' }"
          @click="openDetail(item)"
        >
          <div class="poster-wrapper">
            <img
              :src="getPosterUrl(item.poster_url)"
              :alt="item.title"
              loading="lazy"
              decoding="async"
              @error="handleImageError"
            />
            <div v-if="item.rank" class="rank-badge">{{ item.rank }}</div>
            <div v-if="item.rating" class="rating-badge">{{ formatRating(item.rating) }}</div>
          </div>
          <div class="card-info">
            <h4 class="title">{{ item.title }}</h4>
            <div class="meta">
              <span v-if="item.year" class="year">{{ item.year }}</span>
              <span class="type-tag">{{ item.media_type === 'tv' ? '剧集' : '电影' }}</span>
            </div>
            <p v-if="item.reason" class="reason">{{ item.reason }}</p>
          </div>
        </el-card>
      </div>
    </div>

    <!-- 加载更多骨架（瀑布流底部） -->
    <div v-if="loadingMore" class="waterfall">
      <div v-for="n in 4" :key="`lm-${n}`" class="waterfall-item skeleton-item">
        <div class="skeleton-poster" />
        <div class="skeleton-title" />
        <div class="skeleton-line" />
      </div>
    </div>

    <!-- 全部加载完毕 -->
    <div v-if="allLoaded && items.length > 0" class="waterfall-end">
      <span>已展示全部 {{ totalCount }} 条推荐</span>
      <el-button type="primary" link @click="handleRefresh">换一批</el-button>
    </div>

    <!-- 空状态 -->
    <el-empty
      v-if="!initialLoading && !items.length"
      :description="ready ? '暂无推荐，点击「刷新推荐」生成' : '尚未生成推荐'"
    />

    <!-- 滚动哨兵 -->
    <div ref="sentinelRef" class="scroll-sentinel" />
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { recommendApi } from '@/api'

const router = useRouter()
const route = useRoute()

const PAGE_SIZE = 12

const items = ref([])
const initialLoading = ref(false)
const loadingMore = ref(false)
const refreshing = ref(false)
const ready = ref(false)
const error = ref('')
const profileSummary = ref('')
const generatedAt = ref(null)
const totalCount = ref(0)
const hasMore = ref(false)
const allLoaded = ref(false)

const sentinelRef = ref(null)
let observer = null

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w500'
const POSTER_FALLBACK_URL = new URL('/no-poster.png', import.meta.url).href

const generatedAtText = computed(() => {
  if (!generatedAt.value) return ''
  try {
    const d = new Date(generatedAt.value)
    if (Number.isNaN(d.getTime())) return ''
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return ''
  }
})

const getPosterUrl = (path) => {
  if (!path) return POSTER_FALLBACK_URL
  const source = String(path).trim()
  const rawUrl = source.startsWith('//') ? `https:${source}` : source
  if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://')) {
    if (rawUrl.includes('image.tmdb.org')) {
      return rawUrl.replace(/\/t\/p\/[^/]+\//, '/t/p/w500/')
    }
    return rawUrl
  }
  if (source.startsWith('/')) return `${TMDB_IMAGE_BASE}${source}`
  return POSTER_FALLBACK_URL
}

const formatRating = (rating) => {
  const v = Number(rating)
  return Number.isFinite(v) && v > 0 ? v.toFixed(1) : ''
}

const handleImageError = (event) => {
  const target = event?.target
  if (!target) return
  target.onerror = null
  if (target.src === POSTER_FALLBACK_URL) return
  target.src = POSTER_FALLBACK_URL
}

const openDetail = (item) => {
  const path = item.media_type === 'tv' ? `/tv/${item.tmdb_id}` : `/movie/${item.tmdb_id}`
  router.push({ path, query: { from: route.fullPath } })
}

const fetchPage = async (start = 0) => {
  const isFirstPage = start === 0
  if (isFirstPage) {
    initialLoading.value = true
  } else {
    loadingMore.value = true
  }
  error.value = ''

  try {
    const { data } = await recommendApi.getList({
      start,
      limit: PAGE_SIZE,
    })
    if (isFirstPage) {
      items.value = Array.isArray(data?.items) ? data.items : []
      ready.value = Boolean(data?.ready)
      generatedAt.value = data?.generated_at || null
      profileSummary.value = data?.profile_summary || ''
      totalCount.value = data?.total || items.value.length
    } else {
      const newItems = Array.isArray(data?.items) ? data.items : []
      items.value.push(...newItems)
      // 给新加载的条目设 rank 偏移
      newItems.forEach((it, i) => {
        it.rank = start + i + 1
      })
    }
    hasMore.value = Boolean(data?.has_more)
    if (!hasMore.value && items.value.length > 0) {
      allLoaded.value = true
    }
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '加载推荐失败'
    if (!isFirstPage) {
      // 加载更多失败时不覆盖已有数据
    } else {
      items.value = []
    }
  } finally {
    initialLoading.value = false
    loadingMore.value = false
  }
}

const loadMore = async () => {
  if (loadingMore.value || allLoaded.value) return
  await fetchPage(items.value.length)
}

const handleRefresh = async () => {
  if (refreshing.value) return
  refreshing.value = true
  items.value = []
  totalCount.value = 0
  allLoaded.value = false
  hasMore.value = false
  try {
    await recommendApi.refresh()
    // 刷新成功后重新加载首页
    await fetchPage(0)
    ElMessage.success(`已生成 ${totalCount.value} 条推荐`)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '刷新失败')
  } finally {
    refreshing.value = false
  }
}

// IntersectionObserver 监听哨兵元素，触底加载更多
const setupObserver = () => {
  if (typeof IntersectionObserver === 'undefined') return
  observer = new IntersectionObserver(
    (entries) => {
      const entry = entries[0]
      if (entry?.isIntersecting && hasMore.value && !loadingMore.value) {
        loadMore()
      }
    },
    { rootMargin: '400px 0px' }
  )
  nextTick(() => {
    if (sentinelRef.value) {
      observer.observe(sentinelRef.value)
    }
  })
}

onMounted(async () => {
  await fetchPage(0)
  setupObserver()
})

onBeforeUnmount(() => {
  if (observer) {
    observer.disconnect()
    observer = null
  }
})
</script>

<style lang="scss" scoped>
.recommend-page {
  padding: 4px 4px 24px;

  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;

    .header-title {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;

      h2 {
        margin: 0;
        font-size: 20px;
        font-weight: 600;
        color: var(--ms-text-primary);
      }

      .header-meta {
        font-size: 12px;
        color: var(--ms-text-muted);
      }
    }
  }

  .recommend-alert {
    margin-bottom: 16px;
  }

  // ====== 瀑布流 ======
  .waterfall {
    column-count: 5;
    column-gap: 16px;
    transition: column-count 0.3s ease;

    .waterfall-item {
      break-inside: avoid;
      margin-bottom: 16px;
      animation: fadeUp 0.35s ease both;
    }
  }

  // ====== 骨架 ======
  .skeleton-item {
    .skeleton-poster {
      aspect-ratio: 2 / 3;
      border-radius: var(--ms-radius-md, 8px);
      background: var(--ms-bg-hover);
      animation: shimmer 1.2s ease-in-out infinite;
    }

    .skeleton-title {
      height: 16px;
      margin: 10px 12px 6px;
      border-radius: 4px;
      background: var(--ms-bg-hover);
      animation: shimmer 1.2s ease-in-out infinite;
    }

    .skeleton-line {
      height: 12px;
      margin: 0 12px 8px;
      border-radius: 4px;
      background: var(--ms-bg-hover);
      animation: shimmer 1.2s ease-in-out infinite;
      width: 60%;
    }
  }

  // ====== 卡片 ======
  .recommend-card {
    border-radius: var(--ms-radius-md, 8px);
    cursor: pointer;
    border: 1px solid var(--ms-border-color);
    background: var(--ms-bg-card);
    transition: border-color 0.2s ease, background-color 0.2s ease, transform 0.2s ease;
    overflow: hidden;

    &:hover {
      border-color: var(--ms-border-light);
      background: var(--ms-bg-elevated);
      transform: translateY(-2px);
    }

    .poster-wrapper {
      position: relative;
      background: var(--ms-bg-elevated);
      overflow: hidden;

      img {
        width: 100%;
        height: auto;
        display: block;
      }

      .rank-badge {
        position: absolute;
        top: 8px;
        left: 8px;
        z-index: 2;
        width: 26px;
        height: 26px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 6px;
        background: rgba(0, 0, 0, 0.65);
        color: #fff;
        font-size: 13px;
        font-weight: 700;
        line-height: 1;
        backdrop-filter: blur(4px);
      }

      .rating-badge {
        position: absolute;
        top: 8px;
        right: 8px;
        z-index: 2;
        display: flex;
        align-items: center;
        justify-content: center;
        min-width: 40px;
        height: 24px;
        padding: 0 8px;
        border-radius: 4px;
        background: var(--ms-accent-warning, #e6a23c);
        color: #fff;
        font-size: 12px;
        font-weight: 700;
        line-height: 1;
      }
    }

    .card-info {
      padding: 10px 14px 14px;

      .title {
        margin: 0 0 6px;
        font-size: 14px;
        font-weight: 600;
        line-height: 1.4;
        color: var(--ms-text-primary);
        display: -webkit-box;
        -webkit-line-clamp: 1;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }

      .meta {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 12px;
        color: var(--ms-text-muted);
        margin-bottom: 8px;

        .type-tag {
          padding: 1px 6px;
          border-radius: 4px;
          font-size: 11px;
          background: var(--ms-bg-hover, #f0f0f0);
          color: var(--ms-text-muted);
        }
      }

      .reason {
        margin: 0;
        font-size: 12px;
        line-height: 1.5;
        color: var(--ms-text-secondary, var(--ms-text-muted));
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
    }
  }

  // ====== 底部提示 ======
  .waterfall-end {
    text-align: center;
    padding: 28px 0 16px;
    color: var(--ms-text-muted);
    font-size: 13px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }

  .scroll-sentinel {
    height: 1px;
    width: 100%;
  }
}

// ====== 响应式列数 ======
@media (max-width: 1400px) {
  .recommend-page .waterfall { column-count: 4; }
}
@media (max-width: 1100px) {
  .recommend-page .waterfall { column-count: 3; }
}
@media (max-width: 768px) {
  .recommend-page {
    .waterfall {
      column-count: 2;
      column-gap: 10px;

      .waterfall-item {
        margin-bottom: 10px;
      }
    }

    .recommend-card .card-info {
      padding: 9px 9px 11px;

      .title { font-size: 12px; }
      .reason { font-size: 11px; }
    }
  }
}
@media (max-width: 480px) {
  .recommend-page .waterfall { column-count: 2; }
}

// ====== 动画 ======
@keyframes fadeUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes shimmer {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
</style>
