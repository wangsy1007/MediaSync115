<template>
  <div class="movie-detail-page" v-loading="loading">
    <template v-if="movie">
      <div class="detail-header">
        <div class="poster">
          <img :src="getPosterUrl(movie.poster_path)" :alt="movie.title" />
        </div>
        <div class="info">
          <h1 class="title">{{ movie.title }}</h1>
          <p class="original-title" v-if="movie.original_title !== movie.title">
            {{ movie.original_title }}
          </p>
          <div class="meta">
            <span class="year">{{ movie.release_date?.split('-')[0] }}</span>
            <span class="rating">
              <el-icon><Star /></el-icon>
              {{ movie.vote_average?.toFixed(1) }}
            </span>
            <span class="runtime" v-if="movie.runtime">{{ movie.runtime }} 分钟</span>
          </div>
          <div class="genres">
            <el-tag v-for="genre in movie.genres" :key="genre.id" size="small">
              {{ genre.name }}
            </el-tag>
          </div>
          <p class="overview">{{ movie.overview }}</p>
          <div class="actions">
            <el-button :type="isSubscribed ? 'success' : 'primary'" @click="handleSubscribe">
              <el-icon><Plus /></el-icon>
              {{ isSubscribed ? '已订阅（点击取消）' : '添加订阅' }}
            </el-button>
          </div>
        </div>
      </div>

      <el-tabs v-model="activeTab" class="resource-tabs">
        <el-tab-pane label="115网盘" name="pan115">
          <el-tabs v-model="pan115SourceTab" class="source-tabs">
            <el-tab-pane label="Nullbr" name="nullbr">
              <div v-loading="pan115Loading">
                <el-table 
                  v-if="nullbrPan115Resources.length > 0" 
                  :data="nullbrPan115Resources" 
                  stripe
                  class="resource-table"
                >
                  <el-table-column label="资源名称" min-width="300" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span class="resource-name">{{ row.title }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="画质" width="120" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" v-if="row.quality">{{ Array.isArray(row.quality) ? row.quality.join(', ') : row.quality }}</el-tag>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="分辨率" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info" v-if="row.resolution">{{ row.resolution }}</el-tag>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="大小" width="100" align="center">
                    <template #default="{ row }">
                      <span class="resource-size">{{ row.size || '-' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="100" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" size="small" @click="handleSaveToPan115(row)">
                        转存
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-else description="Nullbr 暂无115网盘资源" />
              </div>
            </el-tab-pane>

            <el-tab-pane label="Pansou" name="pansou">
              <div class="resource-tools">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="pansouLoading"
                  @click="handleFetchPansouPan115"
                >
                  {{ pansouTried ? '重新尝试 Pansou' : '用 Pansou 获取资源' }}
                </el-button>
              </div>
              <div v-loading="pan115Loading || pansouLoading">
                <el-table 
                  v-if="pansouPan115Resources.length > 0" 
                  :data="pansouPan115Resources" 
                  stripe
                  class="resource-table"
                >
                  <el-table-column label="资源名称" min-width="300" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span class="resource-name">{{ row.title }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="画质" width="120" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" v-if="row.quality">{{ Array.isArray(row.quality) ? row.quality.join(', ') : row.quality }}</el-tag>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="分辨率" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info" v-if="row.resolution">{{ row.resolution }}</el-tag>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="大小" width="100" align="center">
                    <template #default="{ row }">
                      <span class="resource-size">{{ row.size || '-' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="100" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" size="small" @click="handleSaveToPan115(row)">
                        转存
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty
                  v-else
                  :description="pansouTried ? '暂无可用115网盘资源' : '尚未获取 Pansou 资源'"
                />
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="磁力链接" name="magnet">
          <div v-loading="magnetLoading">
            <el-table 
              v-if="magnetResources.length > 0" 
              :data="magnetResources" 
              stripe
              class="resource-table"
            >
              <el-table-column label="资源名称" min-width="400" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="resource-name">{{ row.name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="120" align="center">
                <template #default="{ row }">
                  <span class="resource-size">{{ formatSize(row.size) || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="160" align="center" fixed="right">
                <template #default="{ row }">
                  <el-button type="primary" size="small" @click="handleSaveMagnet(row)">
                    离线
                  </el-button>
                  <el-button size="small" @click="handleCopyMagnet(row.magnet)">
                    复制
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无磁力资源" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="ED2K" name="ed2k">
          <div v-loading="ed2kLoading">
            <el-table 
              v-if="ed2kResources.length > 0" 
              :data="ed2kResources" 
              stripe
              class="resource-table"
            >
              <el-table-column label="资源名称" min-width="400" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="resource-name">{{ row.name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="120" align="center">
                <template #default="{ row }">
                  <span class="resource-size">{{ formatSize(row.size) || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="160" align="center" fixed="right">
                <template #default="{ row }">
                  <el-button type="primary" size="small" @click="handleSaveEd2k(row)">
                    离线
                  </el-button>
                  <el-button size="small" @click="handleCopyEd2k(row.ed2k)">
                    复制
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无ED2K资源" />
          </div>
        </el-tab-pane>

      </el-tabs>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { searchApi, subscriptionApi, pan115Api } from '@/api'

const route = useRoute()

const movie = ref(null)
const loading = ref(true)
const activeTab = ref('pan115')

const pan115Resources = ref([])
const pan115SourceTab = ref('nullbr')
const magnetResources = ref([])
const ed2kResources = ref([])

const pan115Loading = ref(false)
const pansouLoading = ref(false)
const pansouTried = ref(false)
const magnetLoading = ref(false)
const ed2kLoading = ref(false)
const isSubscribed = ref(false)
const subscriptionId = ref(null)

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w500'
const PAN115_CACHE_TTL_MS = 30 * 60 * 1000

// 转存相关
const saving = ref(false)

const getPosterUrl = (path) => {
  if (!path) return new URL('/no-poster.png', import.meta.url).href
  return TMDB_IMAGE_BASE + path
}

const getPan115CacheKey = () => `movie_pan115_${route.params.id}`

const readPan115Cache = () => {
  try {
    const raw = sessionStorage.getItem(getPan115CacheKey())
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || !Array.isArray(parsed.list) || !parsed.ts) return null
    if (Date.now() - parsed.ts > PAN115_CACHE_TTL_MS) return null
    return parsed.list
  } catch {
    return null
  }
}

const writePan115Cache = (list) => {
  try {
    sessionStorage.setItem(
      getPan115CacheKey(),
      JSON.stringify({
        ts: Date.now(),
        list: Array.isArray(list) ? list : []
      })
    )
  } catch {
    // ignore cache write errors
  }
}

const nullbrPan115Resources = computed(() =>
  pan115Resources.value.filter((item) => (item?.source_service || 'nullbr') === 'nullbr')
)

const pansouPan115Resources = computed(() =>
  pan115Resources.value.filter((item) => item?.source_service === 'pansou')
)

const mergePan115Resources = (primaryList = [], secondaryList = []) => {
  const merged = []
  const seen = new Set()
  for (const item of [...primaryList, ...secondaryList]) {
    if (!item || typeof item !== 'object') continue
    const shareLink = String(item.share_link || '').trim()
    const title = String(item.title || '').trim()
    const key = `${shareLink}|${title}`
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }
  return merged
}

const formatSize = (bytes) => {
  if (!bytes) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = parseFloat(bytes)
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(2)} ${units[unitIndex]}`
}

const getResourceSourceLabel = (service) => {
  if (service === 'pansou') return 'Pansou'
  if (service === 'nullbr') return 'Nullbr'
  return service || '未知'
}

const fetchMovie = async () => {
  const tmdbId = route.params.id
  loading.value = true

  try {
    const { data } = await searchApi.getMovie(tmdbId)
    // 适配后端返回字段名
    movie.value = {
      ...data,
      poster_path: data.poster || data.poster_path,
      vote_average: data.vote || data.vote_average,
      release_date: data.release_date || data.release
    }
  } catch (error) {
    ElMessage.error('获取电影信息失败')
  } finally {
    loading.value = false
  }
}

const fetchPan115 = async () => {
  const cachedList = readPan115Cache()
  if (cachedList && cachedList.length > 0) {
    pan115Resources.value = cachedList
    pansouTried.value = cachedList.some((item) => item?.source_service === 'pansou')
    pan115Loading.value = false
  }
  pansouTried.value = false
  pan115Loading.value = true

  try {
    const { data } = await searchApi.getMoviePan115(route.params.id)
    const nullbrList = Array.isArray(data.list) ? data.list : []
    const cachedPansouList = pan115Resources.value.filter((item) => item?.source_service === 'pansou')
    const mergedList = mergePan115Resources(nullbrList, cachedPansouList)
    pan115Resources.value = mergedList
    writePan115Cache(mergedList)
  } catch (error) {
    if (!cachedList || cachedList.length === 0) {
      console.error('Failed to fetch pan115:', error)
    }
  } finally {
    pan115Loading.value = false
  }
}

const handleFetchPansouPan115 = async () => {
  if (pansouLoading.value) return
  pansouLoading.value = true
  pansouTried.value = true
  try {
    const { data } = await searchApi.getMoviePan115Pansou(route.params.id)
    const pansouList = Array.isArray(data.list) ? data.list : []
    const mergedList = mergePan115Resources(pan115Resources.value, pansouList)
    pan115Resources.value = mergedList
    writePan115Cache(mergedList)
    if (pansouList.length === 0) {
      ElMessage.info('Pansou 暂未找到可用资源')
    }
  } catch (error) {
    console.error('Failed to fetch pansou pan115:', error)
  } finally {
    pansouLoading.value = false
  }
}

const fetchMagnet = async () => {
  magnetLoading.value = true
  try {
    const { data } = await searchApi.getMovieMagnet(route.params.id)
    magnetResources.value = data.list || []
    if (data?.error) {
      ElMessage.warning(`磁力资源暂不可用：${data.error}`)
    }
  } catch (error) {
    console.error('Failed to fetch magnet:', error)
  } finally {
    magnetLoading.value = false
  }
}

const fetchEd2k = async () => {
  ed2kLoading.value = true
  try {
    const { data } = await searchApi.getMovieEd2k(route.params.id)
    ed2kResources.value = data.list || []
    if (data?.error) {
      ElMessage.warning(`ED2K 资源暂不可用：${data.error}`)
    }
  } catch (error) {
    console.error('Failed to fetch ed2k:', error)
  } finally {
    ed2kLoading.value = false
  }
}

const handleSubscribe = async () => {
  try {
    if (isSubscribed.value) {
      if (!subscriptionId.value) {
        await checkSubscribed()
      }
      if (!subscriptionId.value) {
        ElMessage.warning('未找到订阅记录，请刷新后重试')
        return
      }
      await subscriptionApi.delete(subscriptionId.value)
      isSubscribed.value = false
      subscriptionId.value = null
      ElMessage.success('已取消订阅')
      return
    }

    const { data } = await subscriptionApi.create({
      tmdb_id: movie.value.id,
      title: movie.value.title,
      media_type: 'movie',
      poster_path: movie.value.poster_path,
      overview: movie.value.overview,
      year: movie.value.release_date?.split('-')[0],
      rating: movie.value.vote_average
    })
    isSubscribed.value = true
    subscriptionId.value = Number(data?.id || 0) || null
    ElMessage.success('订阅成功')
  } catch (error) {
    if (error.response?.status === 400) {
      await checkSubscribed()
      ElMessage.info(isSubscribed.value ? '该影视已在订阅列表中' : '订阅状态已更新，请重试')
      return
    }
    ElMessage.error(error.response?.data?.detail || error.message || '订阅操作失败')
  }
}

const checkSubscribed = async () => {
  const tmdbId = Number(route.params.id)
  if (!Number.isFinite(tmdbId) || tmdbId <= 0) {
    isSubscribed.value = false
    subscriptionId.value = null
    return
  }
  try {
    const { data } = await subscriptionApi.list({ media_type: 'movie' })
    const items = Array.isArray(data) ? data : []
    const matched = items.find((sub) => Number(sub.tmdb_id) === tmdbId) || null
    isSubscribed.value = Boolean(matched)
    subscriptionId.value = Number(matched?.id || 0) || null
  } catch {
    isSubscribed.value = false
    subscriptionId.value = null
  }
}

const handleSaveToPan115 = async (item) => {
  if (!item.share_link) {
    ElMessage.warning('该资源暂无分享链接')
    return
  }

  // 获取默认转存文件夹
  let defaultFolderId = '0'
  try {
    const { data } = await pan115Api.getDefaultFolder()
    defaultFolderId = data.folder_id || '0'
  } catch (error) {
    console.error('Failed to get default folder:', error)
  }

  try {
    // 由后端统一解析分享链接并执行转存
    const { data } = await pan115Api.saveShareToFolder(
      item.share_link,
      movie.value.title + ' (' + movie.value.release_date?.split('-')[0] + ')',
      defaultFolderId,
      ''
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
    const detail = String(error.response?.data?.detail || '').trim()
    if (detail.includes('离线任务列表请求过于频繁')) {
      ElMessage.error('115接口触发风控，请稍后重试')
      return
    }
    ElMessage.error(detail || error.message || '转存失败')
  }
}

const handleCopyMagnet = (magnet) => {
  navigator.clipboard.writeText(magnet)
  ElMessage.success('已复制到剪贴板')
}

const handleCopyEd2k = (ed2k) => {
  navigator.clipboard.writeText(ed2k)
  ElMessage.success('已复制到剪贴板')
}

const handleSaveMagnet = async (item) => {
  if (!item.magnet) {
    ElMessage.warning('无效的磁力链接')
    return
  }

  let defaultFolderId = '0'
  try {
    const { data } = await pan115Api.getOfflineDefaultFolder()
    defaultFolderId = data.folder_id || '0'
  } catch (error) {
    console.error('Failed to get offline default folder:', error)
  }

  const folderName = movie.value.title + ' (' + movie.value.release_date?.split('-')[0] + ')'

  try {
    await pan115Api.addOfflineTask(item.magnet, defaultFolderId)
    ElMessage.success(`已添加到离线下载任务，保存至: ${defaultFolderId === '0' ? '根目录' : folderName}`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '添加离线任务失败')
  }
}

const handleSaveEd2k = async (item) => {
  if (!item.ed2k) {
    ElMessage.warning('无效的ED2K链接')
    return
  }

  let defaultFolderId = '0'
  try {
    const { data } = await pan115Api.getOfflineDefaultFolder()
    defaultFolderId = data.folder_id || '0'
  } catch (error) {
    console.error('Failed to get offline default folder:', error)
  }

  const folderName = movie.value.title + ' (' + movie.value.release_date?.split('-')[0] + ')'

  try {
    await pan115Api.addOfflineTask(item.ed2k, defaultFolderId)
    ElMessage.success(`已添加到离线下载任务，保存至: ${defaultFolderId === '0' ? '根目录' : folderName}`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '添加离线任务失败')
  }
}

watch(activeTab, (tab) => {
  if (tab === 'pan115' && pan115Resources.value.length === 0) {
    fetchPan115()
  } else if (tab === 'magnet' && magnetResources.value.length === 0) {
    fetchMagnet()
  } else if (tab === 'ed2k' && ed2kResources.value.length === 0) {
    fetchEd2k()
  }
})

watch(() => route.params.id, () => {
  pan115SourceTab.value = 'nullbr'
  pan115Resources.value = []
  pansouTried.value = false
  pansouLoading.value = false
  magnetResources.value = []
  ed2kResources.value = []
  fetchMovie()
  fetchPan115()
  checkSubscribed()
})

onMounted(() => {
  fetchMovie()
  fetchPan115()
  checkSubscribed()
})
</script>

<style lang="scss" scoped>
.movie-detail-page {
  animation: fadeIn 0.4s ease;
  
  .detail-header {
    display: flex;
    gap: 32px;
    margin-bottom: 32px;
    padding: 28px;
    background: var(--ms-gradient-card);
    border: 1px solid var(--ms-glass-border);
    border-radius: 20px;
    position: relative;
    overflow: hidden;
    
    // 装饰光效
    &::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 1px;
      background: linear-gradient(90deg, transparent, rgba(45, 153, 255, 0.5), transparent);
    }

    .poster {
      width: 220px;
      flex-shrink: 0;

      img {
        width: 100%;
        border-radius: 12px;
        box-shadow: var(--ms-shadow-md), 0 0 0 1px var(--ms-border-color);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        
        &:hover {
          transform: scale(1.02);
          box-shadow: var(--ms-shadow-lg), 0 0 30px rgba(45, 153, 255, 0.22);
        }
      }
    }

    .info {
      flex: 1;
      display: flex;
      flex-direction: column;

      .title {
        margin: 0 0 8px;
        font-size: 32px;
        font-weight: 700;
        background: linear-gradient(135deg, var(--ms-text-primary) 0%, var(--ms-text-secondary) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -0.5px;
      }

      .original-title {
        margin: 0 0 16px;
        font-size: 14px;
        color: var(--ms-text-muted);
        font-weight: 500;
      }

      .meta {
        display: flex;
        align-items: center;
        gap: 20px;
        margin-bottom: 16px;
        color: var(--ms-text-secondary);
        font-size: 14px;

        .rating {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: rgba(245, 181, 68, 0.16);
          border-radius: 8px;
          color: var(--ms-accent-warning);
          font-weight: 600;
          
          .el-icon {
            font-size: 16px;
          }
        }
        
        .year, .runtime {
          padding: 6px 12px;
          background: rgba(45, 153, 255, 0.12);
          border-radius: 8px;
          color: var(--ms-text-secondary);
          font-weight: 500;
        }
      }

      .genres {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 20px;
        
        .el-tag {
          border-radius: 6px;
          font-weight: 500;
        }
      }

      .overview {
        color: var(--ms-text-secondary);
        line-height: 1.75;
        margin-bottom: 24px;
        font-size: 14px;
        max-height: 100px;
        overflow-y: auto;
        padding-right: 8px;
      }

      .actions {
        display: flex;
        gap: 12px;
        margin-top: auto;
        
        .el-button {
          padding: 12px 24px;
          font-size: 14px;
          font-weight: 600;
        }
      }
    }
  }

  .resource-tabs {
    background: var(--ms-gradient-card);
    border: 1px solid var(--ms-glass-border);
    border-radius: 16px;
    padding: 20px;
    
    :deep(.el-tabs__content) {
      padding: 16px 0 0;
    }
  }

  .resource-tools {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }

  .resource-table {
    background: transparent;
    border-radius: 12px;
    overflow: hidden;
    
    :deep(.el-table__inner-wrapper::before) {
      display: none;
    }
    
    :deep(.el-table__header) {
      th {
        background: rgba(67, 123, 198, 0.2);
        color: var(--ms-text-primary);
        font-weight: 600;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        border-bottom: 1px solid var(--ms-border-color);
        padding: 14px 0;
      }
    }
    
    :deep(.el-table__body) {
      tr {
        background: rgba(17, 37, 72, 0.34);
        transition: all 0.2s ease;
        
        &:hover > td {
          background: rgba(45, 153, 255, 0.12) !important;
        }
        
        &.el-table__row--striped td {
          background: rgba(15, 30, 58, 0.38);
        }
      }
      
      td {
        border-bottom: 1px solid var(--ms-border-color);
        padding: 14px 0;
      }
    }
    
    :deep(.el-table__empty-block) {
      background: rgba(17, 37, 72, 0.34);
    }
  }

  .resource-name {
    color: var(--ms-text-primary);
    font-size: 14px;
    font-weight: 500;
  }

  .resource-size {
    color: var(--ms-text-secondary);
    font-size: 13px;
  }

  .text-muted {
    color: var(--ms-text-muted);
  }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>



