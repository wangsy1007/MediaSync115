<template>
  <div class="subscriptions-page">
    <div class="page-header">
      <h2>我的订阅</h2>
      <el-radio-group v-model="filterType" @change="handleFilterChange">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="movie">电影</el-radio-button>
        <el-radio-button value="tv">电视剧</el-radio-button>
      </el-radio-group>
    </div>

    <div class="subscriptions-grid" v-loading="loading">
      <template v-if="subscriptions.length > 0">
        <el-card v-for="sub in subscriptions" :key="sub.id" class="subscription-item">
          <div class="card-content" @click="goToDetail(sub)">
            <div class="poster">
              <div
                class="poster-skeleton"
                :class="{ hidden: isPosterLoaded(sub), static: !hasPosterSource(sub) }"
              />
              <img
                v-if="hasPosterSource(sub)"
                class="poster-main"
                :class="{ loaded: isPosterLoaded(sub) }"
                :src="getPosterUrl(sub)"
                :alt="sub.title"
                loading="lazy"
                decoding="async"
                @load="handlePosterLoad(sub)"
                @error="handlePosterError($event, sub)"
              />
              <div v-if="!isPosterLoaded(sub)" class="poster-placeholder-text">暂无海报</div>
              <div class="poster-hover">
                <el-button type="primary" size="small" @click.stop="goToDetail(sub)">快速查看详情</el-button>
              </div>
            </div>
            <div class="info">
              <div class="title-row">
                <h3 class="title">{{ sub.title }}</h3>
                <el-tag :type="sub.media_type === 'movie' ? 'primary' : 'success'" size="small">
                  {{ sub.media_type === 'movie' ? '电影' : '电视剧' }}
                </el-tag>
              </div>
              <div class="meta">
                <span v-if="sub.year">{{ sub.year }}</span>
                <span v-if="sub.rating">
                  <el-icon><Star /></el-icon>
                  {{ sub.rating?.toFixed(1) }}
                </span>
              </div>
              <div class="actions" @click.stop>
                <el-button type="danger" size="small" plain @click="handleDelete(sub)">
                  取消订阅
                </el-button>
              </div>
            </div>
          </div>
        </el-card>
      </template>
      <el-empty v-else description="暂无订阅" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { settingsApi, subscriptionApi } from '@/api'

const subscriptions = ref([])
const loading = ref(false)
const filterType = ref('all')
const router = useRouter()

const tmdbImageBaseUrl = ref('https://image.tmdb.org/t/p/w500')
let activeFetchToken = 0
const posterLoadedState = ref({})
const posterFailedState = ref({})

const getPosterUrl = (sub) => {
  if (!sub || typeof sub !== 'object') return ''
  if (posterFailedState.value[sub.id]) return ''

  const resolvedTmdbPath = String(sub._resolvedPosterPath || '').trim()
  if (resolvedTmdbPath.startsWith('/')) {
    return `${tmdbImageBaseUrl.value}${resolvedTmdbPath}`
  }

  const raw = String(sub.poster_path || '').trim()
  if (!raw) return ''
  if (raw.startsWith('/')) return `${tmdbImageBaseUrl.value}${raw}`
  if (/^https?:\/\//i.test(raw)) {
    // 统一优先 TMDB 图源，非 TMDB 的历史海报仅作为兜底。
    if (/image\.tmdb\.org/i.test(raw)) return raw
    return ''
  }
  if (raw.startsWith('//') && /image\.tmdb\.org/i.test(raw)) return `https:${raw}`
  return ''
}

const hasPosterSource = (sub) => Boolean(getPosterUrl(sub))

const resetPosterLoadedState = (items) => {
  const nextLoadedState = {}
  const nextFailedState = {}
  for (const sub of Array.isArray(items) ? items : []) {
    if (!sub || sub.id == null) continue
    nextLoadedState[sub.id] = false
    nextFailedState[sub.id] = false
  }
  posterLoadedState.value = nextLoadedState
  posterFailedState.value = nextFailedState
}

const isPosterLoaded = (sub) => Boolean(posterLoadedState.value[sub?.id])

const handlePosterLoad = (sub) => {
  if (!sub || sub.id == null) return
  posterLoadedState.value[sub.id] = true
}

const handlePosterError = (event, sub) => {
  if (!sub || sub.id == null) return
  posterFailedState.value[sub.id] = true
  posterLoadedState.value[sub.id] = false
}

const fetchSubscriptions = async () => {
  const token = ++activeFetchToken
  loading.value = true
  try {
    const params = { exclude_transferred_success: true }
    if (filterType.value !== 'all') {
      params.media_type = filterType.value
    }
    const [listResp, runtimeResp] = await Promise.allSettled([
      subscriptionApi.list(params),
      settingsApi.getRuntime()
    ])

    if (token !== activeFetchToken) return

    if (runtimeResp.status === 'fulfilled') {
      const base = String(runtimeResp.value?.data?.tmdb_image_base_url || '').trim()
      if (base) {
        tmdbImageBaseUrl.value = base.endsWith('/') ? base.slice(0, -1) : base
      }
    }

    if (listResp.status !== 'fulfilled') {
      throw listResp.reason
    }
    const data = listResp.value?.data
    subscriptions.value = Array.isArray(data) ? data : []
    resetPosterLoadedState(subscriptions.value)
  } catch (error) {
    ElMessage.error('获取订阅列表失败')
  } finally {
    if (token === activeFetchToken) {
      loading.value = false
    }
  }
}

const handleFilterChange = () => {
  fetchSubscriptions()
}

const handleDelete = async (sub) => {
  try {
    await subscriptionApi.delete(sub.id)
    subscriptions.value = subscriptions.value.filter(s => s.id !== sub.id)
    ElMessage.success('已取消订阅')
  } catch (error) {
    ElMessage.error('操作失败')
  }
}

const goToDetail = (sub) => {
  const tmdbId = Number(sub?.tmdb_id)
  if (!Number.isFinite(tmdbId) || tmdbId <= 0) {
    ElMessage.warning('缺少 TMDB ID，无法跳转详情')
    return
  }
  if (sub?.media_type === 'tv') {
    router.push(`/tv/${tmdbId}`)
    return
  }
  router.push(`/movie/${tmdbId}`)
}

onMounted(() => {
  fetchSubscriptions()
})
</script>

<style lang="scss" scoped>
.subscriptions-page {
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;

    h2 {
      margin: 0;
      color: var(--ms-text-primary);
    }
  }

  .subscriptions-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 14px;
  }

  .subscription-item {
    overflow: hidden;
    cursor: pointer;

    .card-content {
      display: flex;
      flex-direction: column;
      height: 100%;
    }

    .poster {
      width: calc(100% + 40px);
      margin: -20px -20px 10px;
      position: relative;
      aspect-ratio: 2 / 3;

      img {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        object-fit: cover;
        background: var(--ms-bg-elevated);
      }

      .poster-skeleton {
        position: absolute;
        inset: 0;
        z-index: 1;
        background: linear-gradient(
          110deg,
          rgba(78, 145, 221, 0.2) 18%,
          rgba(142, 199, 255, 0.36) 34%,
          rgba(78, 145, 221, 0.2) 52%
        );
        background-size: 220% 100%;
        animation: poster-shimmer 1.2s ease-in-out infinite;
        transition: opacity 0.18s ease;

        &.hidden {
          opacity: 0;
          pointer-events: none;
        }

        &.static {
          animation: none;
          background: var(--ms-gradient-card);
        }
      }

      .poster-main {
        z-index: 2;
        opacity: 0;
        transition: opacity 0.2s ease;

        &.loaded {
          opacity: 1;
        }
      }

      .poster-placeholder-text {
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        z-index: 2;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 12px;
        color: var(--ms-text-secondary);
        background: var(--ms-glass-bg);
        border: 1px solid var(--ms-border-color);
      }

      .poster-hover {
        position: absolute;
        inset: 0;
        z-index: 3;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(6, 16, 33, 0.38);
        opacity: 0;
        transition: opacity 0.18s ease;
      }
    }

    .info {
      min-width: 0;

      .title-row {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 8px;

        .title {
          margin: 0;
          font-size: 15px;
          line-height: 1.4;
          color: var(--ms-text-primary);
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
      }

      .meta {
        display: flex;
        align-items: center;
        gap: 14px;
        margin-bottom: 10px;
        color: var(--ms-text-muted);
        font-size: 12px;

        .el-icon {
          color: var(--ms-accent-warning);
        }
      }

      .actions {
        display: flex;
        flex-direction: column;
        align-items: stretch;
        gap: 8px;
      }
    }

    &:hover {
      .poster .poster-hover {
        opacity: 1;
      }
    }
  }

  @media (max-width: 768px) {
    .subscriptions-grid {
      grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    }
  }
}

@keyframes poster-shimmer {
  0% {
    background-position: 120% 50%;
  }
  100% {
    background-position: -120% 50%;
  }
}
</style>
