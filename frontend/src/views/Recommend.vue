<template>
  <div class="recommend-page">
    <div class="page-header">
      <div class="header-title">
        <h2>猜你想看</h2>
        <span v-if="generatedAtText" class="header-meta">上次生成：{{ generatedAtText }}</span>
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
      v-else-if="error"
      type="error"
      :closable="false"
      show-icon
      class="recommend-alert"
    >
      <span>{{ error }}</span>
    </el-alert>
    <el-alert
      v-else-if="profileSummary && !loading"
      type="info"
      :closable="false"
      show-icon
      class="recommend-alert"
    >
      <span>本次画像：{{ profileSummary }}</span>
    </el-alert>

    <div v-if="loading" class="card-grid">
      <div v-for="n in skeletonCount" :key="`sk-${n}`" class="skeleton-card">
        <div class="skeleton-poster" />
        <div class="skeleton-title" />
        <div class="skeleton-line" />
      </div>
    </div>

    <div v-else-if="items.length" class="card-grid">
      <el-card
        v-for="item in items"
        :key="`${item.media_type}-${item.tmdb_id}`"
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
          <div v-if="item.rating" class="rating-badge">{{ formatRating(item.rating) }}</div>
        </div>
        <div class="card-info">
          <h4 class="title">{{ item.title }}</h4>
          <div class="meta">
            <span v-if="item.year" class="year">{{ item.year }}</span>
            <span class="type">{{ item.media_type === 'tv' ? '剧集' : '电影' }}</span>
          </div>
          <p v-if="item.reason" class="reason">{{ item.reason }}</p>
        </div>
      </el-card>
    </div>

    <el-empty
      v-else-if="!loading"
      :description="ready ? '暂无推荐，点击右上角「刷新推荐」生成' : '尚未生成推荐'"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { recommendApi } from '@/api'

const router = useRouter()
const route = useRoute()

const items = ref([])
const loading = ref(false)
const refreshing = ref(false)
const ready = ref(false)
const enabled = ref(false)
const error = ref('')
const profileSummary = ref('')
const generatedAt = ref(null)

const skeletonCount = 8

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
      return rawUrl.replace(/\/t\/p\/[^/]+\//, '/t/p/w342/')
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

const fetchList = async () => {
  loading.value = true
  error.value = ''
  try {
    const { data } = await recommendApi.getList()
    items.value = Array.isArray(data?.items) ? data.items : []
    ready.value = Boolean(data?.ready)
    enabled.value = Boolean(data?.enabled)
    generatedAt.value = data?.generated_at || null
    profileSummary.value = data?.profile_summary || ''
    error.value = data?.error || ''
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '加载推荐失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

const handleRefresh = async () => {
  if (refreshing.value) return
  refreshing.value = true
  try {
    const { data } = await recommendApi.refresh()
    items.value = Array.isArray(data?.items) ? data.items : []
    ready.value = Boolean(data?.ready)
    generatedAt.value = data?.generated_at || null
    profileSummary.value = data?.profile_summary || ''
    error.value = data?.error || ''
    if (data?.error) {
      ElMessage.error(data.error)
    } else {
      ElMessage.success(`已生成 ${items.value.length} 条推荐`)
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '刷新失败')
  } finally {
    refreshing.value = false
  }
}

onMounted(fetchList)
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

  .card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 16px;
  }

  .skeleton-card {
    .skeleton-poster {
      aspect-ratio: 2 / 3;
      border-radius: var(--ms-radius-md, 8px);
      background: var(--ms-bg-hover);
      animation: shimmer 1.2s ease-in-out infinite;
    }

    .skeleton-title {
      height: 16px;
      margin: 10px 0 6px;
      border-radius: 4px;
      background: var(--ms-bg-hover);
      animation: shimmer 1.2s ease-in-out infinite;
    }

    .skeleton-line {
      height: 12px;
      border-radius: 4px;
      background: var(--ms-bg-hover);
      animation: shimmer 1.2s ease-in-out infinite;
    }
  }

  .recommend-card {
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

    .poster-wrapper {
      position: relative;
      aspect-ratio: 2 / 3;
      background: var(--ms-bg-elevated);
      overflow: hidden;

      img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }

      .rating-badge {
        position: absolute;
        top: 10px;
        right: 10px;
        z-index: 2;
        display: flex;
        align-items: center;
        justify-content: center;
        min-width: 44px;
        height: 26px;
        padding: 0 9px;
        border-radius: 4px;
        background: var(--ms-accent-warning);
        color: #fff;
        font-size: 12px;
        font-weight: 700;
        line-height: 1;
      }
    }

    .card-info {
      padding: 12px 14px 14px;

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
}

@media (max-width: 768px) {
  .recommend-page {
    .card-grid {
      grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
      gap: 10px;
    }

    .recommend-card .card-info {
      padding: 9px 9px 11px;

      .title {
        font-size: 12px;
      }

      .reason {
        font-size: 11px;
      }
    }
  }
}

@keyframes shimmer {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
</style>
