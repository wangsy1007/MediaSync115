<template>
  <div class="subscriptions-page">
    <div class="page-header">
      <h2>我的订阅</h2>
      <div class="header-actions">
        <el-radio-group v-if="activeTab === 'subscriptions'" v-model="filterType" @change="handleFilterChange">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="movie">电影</el-radio-button>
          <el-radio-button value="tv">电视剧</el-radio-button>
        </el-radio-group>
        <template v-else>
          <el-switch v-model="missingOnly" active-text="仅看缺集" @change="() => fetchTvMissingStatus(false)" />
          <el-button type="primary" :loading="missingLoading" @click="() => fetchTvMissingStatus(true)">
            刷新缺集状态
          </el-button>
        </template>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="main-tabs">
      <el-tab-pane label="订阅列表" name="subscriptions">
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
      </el-tab-pane>

      <el-tab-pane label="缺集状态" name="missing">
        <div class="missing-panel" v-loading="missingLoading">
          <el-table v-if="missingRows.length > 0" :data="missingRows" stripe>
            <el-table-column label="剧集" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <div class="missing-title">{{ row.title }}</div>
                <div class="missing-year" v-if="row.year">{{ row.year }}</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120" align="center">
              <template #default="{ row }">
                <el-tag :type="row.status === 'ok' ? 'success' : 'warning'" size="small">
                  {{ row.status === 'ok' ? '可比对' : '异常' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="总集数" width="90" align="center">
              <template #default="{ row }">{{ row.total_count || 0 }}</template>
            </el-table-column>
            <el-table-column label="已入库" width="90" align="center">
              <template #default="{ row }">{{ row.existing_count || 0 }}</template>
            </el-table-column>
            <el-table-column label="缺失" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="(row.missing_count || 0) > 0 ? 'danger' : 'success'" size="small">
                  {{ row.missing_count || 0 }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="缺集明细" min-width="260" show-overflow-tooltip>
              <template #default="{ row }">
                <span>{{ formatMissingBySeason(row.missing_by_season) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="说明" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <span>{{ row.message || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180" align="center" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="refreshMissingRow(row)">刷新</el-button>
                <el-button size="small" type="primary" @click="goToTvDetail(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="当前没有缺集或暂无可用数据" />
        </div>
      </el-tab-pane>
    </el-tabs>
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
const activeTab = ref('subscriptions')
const missingRows = ref([])
const missingLoading = ref(false)
const missingOnly = ref(true)
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
    missingRows.value = missingRows.value.filter((row) => Number(row.subscription_id) !== Number(sub.id))
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

const goToTvDetail = (row) => {
  const tmdbId = Number(row?.tmdb_id)
  if (!Number.isFinite(tmdbId) || tmdbId <= 0) {
    ElMessage.warning('缺少 TMDB ID，无法跳转详情')
    return
  }
  router.push(`/tv/${tmdbId}`)
}

const formatMissingBySeason = (missingBySeason) => {
  if (!missingBySeason || typeof missingBySeason !== 'object') return '-'
  const segments = Object.keys(missingBySeason)
    .sort((a, b) => Number(a) - Number(b))
    .map((season) => {
      const episodes = Array.isArray(missingBySeason[season]) ? missingBySeason[season] : []
      if (episodes.length === 0) return ''
      return `S${String(season).padStart(2, '0')}: ${episodes.map(ep => `E${String(ep).padStart(2, '0')}`).join(', ')}`
    })
    .filter(Boolean)
  return segments.length > 0 ? segments.join(' | ') : '-'
}

const fetchTvMissingStatus = async (refresh = false) => {
  missingLoading.value = true
  try {
    const params = {
      only_missing: missingOnly.value,
      limit: 120,
      refresh: refresh === true
    }
    const { data } = await subscriptionApi.getTvMissingStatus(params)
    const rows = Array.isArray(data?.items) ? data.items : []
    missingRows.value = rows
  } catch (error) {
    ElMessage.error('获取缺集状态失败')
  } finally {
    missingLoading.value = false
  }
}

const refreshMissingRow = async (row) => {
  const subscriptionId = Number(row?.subscription_id)
  if (!Number.isFinite(subscriptionId) || subscriptionId <= 0) return
  try {
    const { data } = await subscriptionApi.getSubscriptionTvMissingStatus(subscriptionId, { refresh: true })
    const counts = data?.counts || {}
    const nextRow = {
      subscription_id: data?.subscription_id,
      tmdb_id: data?.tmdb_id,
      title: data?.title,
      year: data?.year,
      poster_path: data?.poster_path,
      status: data?.status,
      message: data?.message,
      total_count: Number(counts.total || counts.aired || 0),
      aired_count: Number(counts.aired || 0),
      existing_count: Number(counts.existing || 0),
      missing_count: Number(counts.missing || 0),
      missing_by_season: data?.missing_by_season || {}
    }
    const index = missingRows.value.findIndex((item) => Number(item.subscription_id) === subscriptionId)
    if (missingOnly.value && nextRow.missing_count === 0) {
      if (index >= 0) missingRows.value.splice(index, 1)
      return
    }
    if (index >= 0) {
      missingRows.value.splice(index, 1, nextRow)
    } else {
      missingRows.value.unshift(nextRow)
    }
  } catch (error) {
    ElMessage.error('刷新缺集状态失败')
  }
}

onMounted(() => {
  fetchSubscriptions()
  fetchTvMissingStatus()
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

    .header-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }
  }

  .main-tabs {
    :deep(.el-tabs__content) {
      padding-top: 8px;
    }
  }

  .missing-panel {
    .missing-title {
      font-weight: 600;
      color: var(--ms-text-primary);
    }

    .missing-year {
      margin-top: 2px;
      font-size: 12px;
      color: var(--ms-text-muted);
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
    .page-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 10px;

      .header-actions {
        width: 100%;
      }
    }

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
