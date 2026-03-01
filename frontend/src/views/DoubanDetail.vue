<template>
  <div class="douban-detail-page" v-loading="loading">
    <template v-if="detail">
      <div class="detail-header">
        <div class="poster">
          <img :src="getPosterUrl(detail.poster_url)" :alt="detail.title" @error="handlePosterError" />
        </div>
        <div class="info">
          <h1 class="title">{{ detail.title }}</h1>
          <p class="original-title" v-if="detail.original_title && detail.original_title !== detail.title">
            {{ detail.original_title }}
          </p>
          <div class="meta">
            <span v-if="detail.year">{{ detail.year }}</span>
            <span v-if="detail.rating">豆瓣 {{ Number(detail.rating).toFixed(1) }}</span>
            <span>{{ detail.media_type === 'tv' ? '剧集' : '电影' }}</span>
          </div>
          <div class="genres" v-if="detail.genres.length">
            <el-tag v-for="genre in detail.genres" :key="genre" size="small">{{ genre }}</el-tag>
          </div>
          <p class="overview">{{ detail.intro || '暂无简介' }}</p>
          <div class="actions">
            <el-button type="primary" :loading="mappingLoading" @click="handleRematchTmdb">
              {{ mappedTmdbId ? '重新匹配 TMDB' : '匹配 TMDB' }}
            </el-button>
            <el-button :type="isSubscribed ? 'success' : 'primary'" :disabled="!mappedTmdbId" :loading="subscribing" @click="handleSubscribe">
              {{ isSubscribed ? '已订阅（点击取消）' : '添加订阅' }}
            </el-button>
            <el-button v-if="detail.source_url" @click="openDoubanPage">在豆瓣打开</el-button>
          </div>
          <p class="mapping-tip">
            <span v-if="mappedTmdbId">已匹配 TMDB：{{ mappedTmdbId }}</span>
            <span v-else>未匹配 TMDB，115 资源使用豆瓣关键词方案；磁链/ED2K 需先匹配 TMDB。</span>
          </p>
        </div>
      </div>

      <el-tabs v-model="activeTab" class="resource-tabs">
        <el-tab-pane label="115网盘" name="pan115">
          <el-tabs v-model="pan115SourceTab" class="source-tabs">
            <el-tab-pane label="Nullbr" name="nullbr">
              <div v-loading="pan115Loading">
                <el-table v-if="nullbrPan115Resources.length" :data="nullbrPan115Resources" stripe class="resource-table">
                  <el-table-column label="资源名称" min-width="360" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span class="resource-name">{{ row.title || row.name || '未命名资源' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="来源" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info">{{ row.source_service || 'nullbr' }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="大小" width="110" align="center">
                    <template #default="{ row }">{{ row.size || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" size="small" :loading="Boolean(row.saving)" @click="savePan115Resource(row)">转存</el-button>
                      <el-button
                        v-if="mediaType === 'tv'"
                        size="small"
                        :loading="Boolean(row.extracting)"
                        @click="openSelectSaveDialog(row)"
                      >
                        选集
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-else :description="mappedTmdbId ? 'Nullbr 暂无115网盘资源' : '请先匹配 TMDB 后查看 Nullbr 资源'" />
              </div>
            </el-tab-pane>

            <el-tab-pane label="Pansou" name="pansou">
              <div class="resource-tools">
                <el-button size="small" type="primary" plain :loading="pansouLoading" @click="fetchPansouPan115">
                  {{ pansouTried ? '重新尝试 Pansou' : '用 Pansou 获取资源' }}
                </el-button>
              </div>
              <div v-loading="pan115Loading || pansouLoading">
                <el-table v-if="pansouPan115Resources.length" :data="pansouPan115Resources" stripe class="resource-table">
                  <el-table-column label="资源名称" min-width="360" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span class="resource-name">{{ row.title || row.name || '未命名资源' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="来源" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info">{{ row.source_service || 'pansou' }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="大小" width="110" align="center">
                    <template #default="{ row }">{{ row.size || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" size="small" :loading="Boolean(row.saving)" @click="savePan115Resource(row)">转存</el-button>
                      <el-button
                        v-if="mediaType === 'tv'"
                        size="small"
                        :loading="Boolean(row.extracting)"
                        @click="openSelectSaveDialog(row)"
                      >
                        选集
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-else :description="pansouTried ? '暂无可用115网盘资源' : '尚未获取 Pansou 资源'" />
              </div>
            </el-tab-pane>

            <el-tab-pane label="HDHive" name="hdhive">
              <div class="resource-tools">
                <el-button size="small" type="primary" plain :loading="hdhiveLoading" @click="fetchHdhivePan115">
                  {{ hdhiveTried ? '刷新 HDHive' : '用 HDHive 获取资源' }}
                </el-button>
              </div>
              <div v-loading="pan115Loading || hdhiveLoading">
                <el-table v-if="hdhivePan115Resources.length" :data="hdhivePan115Resources" stripe class="resource-table">
                  <el-table-column label="资源名称" min-width="360" show-overflow-tooltip>
                    <template #default="{ row }">
                      <div class="resource-name">{{ row.resource_name || row.title || row.name || '未命名资源' }}</div>
                      <div
                        v-if="row.resource_name && row.title && row.resource_name !== row.title"
                        class="text-muted"
                      >
                        {{ row.title }}
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="来源" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info">{{ row.source_service || 'hdhive' }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="画质" width="120" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" v-if="row.quality">
                        {{ Array.isArray(row.quality) ? row.quality.join(', ') : row.quality }}
                      </el-tag>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="分辨率" width="110" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info" v-if="row.resolution">
                        {{ Array.isArray(row.resolution) ? row.resolution.join(', ') : row.resolution }}
                      </el-tag>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="大小" width="110" align="center">
                    <template #default="{ row }">
                      <span class="resource-size">{{ row.size || '-' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="积分" width="80" align="center">
                    <template #default="{ row }">{{ Number(row.unlock_points || 0) }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        type="primary"
                        size="small"
                        :disabled="row.pan115_savable === false"
                        :loading="Boolean(row.saving)"
                        @click="savePan115Resource(row)"
                      >
                        转存
                      </el-button>
                      <el-button
                        v-if="mediaType === 'tv'"
                        size="small"
                        :disabled="row.pan115_savable === false"
                        :loading="Boolean(row.extracting)"
                        @click="openSelectSaveDialog(row)"
                      >
                        选集
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-else :description="hdhiveTried ? 'HDHive 暂无可用115网盘资源' : '尚未获取 HDHive 资源'" />
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="磁力链接" name="magnet">
          <el-tabs v-model="magnetSourceTab" class="source-tabs">
            <el-tab-pane label="Nullbr" name="nullbr">
              <div v-loading="magnetLoading">
                <el-table v-if="mappedTmdbId && nullbrMagnetResources.length" :data="nullbrMagnetResources" stripe class="resource-table">
                  <el-table-column label="资源名称" min-width="380" show-overflow-tooltip>
                    <template #default="{ row }">{{ row.name || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="大小" width="120" align="center">
                    <template #default="{ row }">{{ formatSize(row.size) || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" size="small" @click="saveMagnet(row)">离线</el-button>
                      <el-button size="small" @click="copyMagnet(row.magnet)">复制</el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-else :description="mappedTmdbId ? 'Nullbr 暂无磁力资源' : '请先匹配 TMDB 后再查看磁力资源'" />
              </div>
            </el-tab-pane>

            <el-tab-pane label="SeedHub" name="seedhub">
              <div class="resource-tools">
                <el-button size="small" type="primary" plain :loading="seedhubMagnetLoading" @click="fetchSeedhubMagnet">
                  {{ seedhubMagnetTried ? '重新尝试 SeedHub' : '用 SeedHub 获取磁链' }}
                </el-button>
              </div>
              <div v-loading="seedhubMagnetLoading">
                <el-table v-if="mappedTmdbId && seedhubMagnetResources.length" :data="seedhubMagnetResources" stripe class="resource-table">
                  <el-table-column label="资源名称" min-width="380" show-overflow-tooltip>
                    <template #default="{ row }">{{ row.name || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="大小" width="120" align="center">
                    <template #default="{ row }">{{ formatSize(row.size) || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" size="small" @click="saveMagnet(row)">离线</el-button>
                      <el-button size="small" @click="copyMagnet(row.magnet)">复制</el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-else :description="seedhubMagnetTried ? 'SeedHub 暂无磁力资源' : '尚未获取 SeedHub 资源'" />
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="ED2K" name="ed2k">
          <div v-loading="ed2kLoading">
            <el-table v-if="mappedTmdbId && ed2kResources.length" :data="ed2kResources" stripe class="resource-table">
              <el-table-column label="资源名称" min-width="380" show-overflow-tooltip>
                <template #default="{ row }">{{ row.title || row.name || '-' }}</template>
              </el-table-column>
              <el-table-column label="操作" width="180" align="center" fixed="right">
                <template #default="{ row }">
                  <el-button type="primary" size="small" @click="saveEd2k(row)">离线</el-button>
                  <el-button size="small" @click="copyMagnet(row.ed2k || row.url)">复制</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else :description="mappedTmdbId ? '暂无 ED2K 资源' : '请先匹配 TMDB 后再查看 ED2K 资源'" />
          </div>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-dialog v-model="selectSaveDialogVisible" title="选集转存" width="700px">
      <el-form :model="selectSaveForm" label-width="100px" style="margin-bottom: 20px;">
        <el-form-item label="新建文件夹">
          <el-input v-model="selectSaveForm.newFolderName" placeholder="可选，输入名称自动创建" />
        </el-form-item>
      </el-form>
      <div style="margin-bottom: 10px; display: flex; gap: 8px;">
        <el-button size="small" :type="fileNameSortOrder === 'asc' ? 'primary' : 'default'" @click="setFileNameSortOrder('asc')">
          名称升序
        </el-button>
        <el-button size="small" :type="fileNameSortOrder === 'desc' ? 'primary' : 'default'" @click="setFileNameSortOrder('desc')">
          名称降序
        </el-button>
      </div>

      <div v-loading="extractingFiles">
        <el-table
          :data="shareFilesList"
          row-key="fid"
          :reserve-selection="true"
          @selection-change="handleSelectionChange"
          height="400"
          style="width: 100%"
          border
        >
          <el-table-column type="selection" width="55" />
          <el-table-column prop="name" label="文件名称" show-overflow-tooltip />
          <el-table-column prop="size" label="大小" width="120">
            <template #default="{ row }">
              {{ formatSize(row.size) }}
            </template>
          </el-table-column>
        </el-table>
        <div style="margin-top: 10px; color: var(--ms-text-muted); font-size: 13px;">
          已自动过滤非视频文件，共选中 {{ selectedFiles.length }} 个文件
        </div>
      </div>

      <template #footer>
        <el-button @click="selectSaveDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="selectSaving"
          :disabled="selectedFiles.length === 0 || extractingFiles"
          @click="confirmSelectSave"
        >
          确认转存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { pansouApi, pan115Api, searchApi, subscriptionApi } from '@/api'

const route = useRoute()
const loading = ref(false)
const mappingLoading = ref(false)
const subscribing = ref(false)
const detail = ref(null)

const activeTab = ref('pan115')
const pan115SourceTab = ref('nullbr')
const magnetSourceTab = ref('nullbr')

const pan115Resources = ref([])
const magnetResources = ref([])
const ed2kResources = ref([])
const isSubscribed = ref(false)

const pan115Loading = ref(false)
const pansouLoading = ref(false)
const pansouTried = ref(false)
const hdhiveLoading = ref(false)
const hdhiveTried = ref(false)
const magnetLoading = ref(false)
const seedhubMagnetLoading = ref(false)
const seedhubMagnetTried = ref(false)
const ed2kLoading = ref(false)
const seedhubMagnetTaskId = ref('')
const selectSaveDialogVisible = ref(false)
const extractingFiles = ref(false)
const selectSaving = ref(false)
const shareFilesList = ref([])
const selectedFiles = ref([])
const fileNameSortOrder = ref('asc')
const selectSaveForm = ref({
  shareLink: '',
  receiveCode: '',
  targetFolder: '0',
  newFolderName: ''
})
let seedhubPollTimer = null

const mediaType = computed(() => (String(route.params.mediaType || '').toLowerCase() === 'tv' ? 'tv' : 'movie'))
const doubanId = computed(() => String(route.params.id || '').trim())
const mappedTmdbId = computed(() => {
  const value = Number(detail.value?.tmdb_mapping?.tmdb_id || 0)
  return Number.isFinite(value) && value > 0 ? Math.trunc(value) : null
})

const nullbrPan115Resources = computed(() =>
  pan115Resources.value.filter((item) => (item?.source_service || 'nullbr') === 'nullbr')
)
const pansouPan115Resources = computed(() =>
  pan115Resources.value.filter((item) => item?.source_service === 'pansou')
)
const hdhivePan115Resources = computed(() =>
  pan115Resources.value.filter((item) => item?.source_service === 'hdhive')
)
const nullbrMagnetResources = computed(() =>
  magnetResources.value.filter((item) => (item?.source_service || 'nullbr') === 'nullbr')
)
const seedhubMagnetResources = computed(() =>
  magnetResources.value.filter((item) => item?.source_service === 'seedhub')
)

const rewriteTmdbPosterSize = (url) => String(url).replace(/\/t\/p\/[^/]+\//, '/t/p/w500/')

const getPosterUrl = (path) => {
  if (!path) return new URL('/no-poster.png', import.meta.url).href
  const source = String(path).trim()
  const raw = source.startsWith('//') ? `https:${source}` : source
  if (raw.startsWith('http://') || raw.startsWith('https://')) {
    if (raw.includes('doubanio.com')) {
      return `/api/search/explore/poster?url=${encodeURIComponent(raw)}&size=medium`
    }
    if (raw.includes('image.tmdb.org')) {
      return rewriteTmdbPosterSize(raw)
    }
    return raw
  }
  return new URL('/no-poster.png', import.meta.url).href
}

const handlePosterError = (event) => {
  event.target.src = new URL('/no-poster.png', import.meta.url).href
}

const mergePan115Resources = (primaryList = [], secondaryList = []) => {
  const merged = []
  const seen = new Set()
  for (const item of [...primaryList, ...secondaryList]) {
    if (!item || typeof item !== 'object') continue
    const shareLink = String(item.share_link || item.share_url || '').trim()
    const title = String(item.title || item.name || '').trim()
    const key = `${shareLink}|${title}`
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }
  return merged
}

const mergeMagnetResources = (primaryList = [], secondaryList = []) => {
  const merged = []
  const seen = new Set()
  for (const item of [...primaryList, ...secondaryList]) {
    if (!item || typeof item !== 'object') continue
    const magnet = String(item.magnet || '').trim()
    if (!magnet) continue
    const key = magnet.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }
  return merged
}

const formatSize = (value) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = parsed
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size.toFixed(index === 0 ? 0 : 2)} ${units[index]}`
}

const copyMagnet = async (text) => {
  const value = String(text || '').trim()
  if (!value) {
    ElMessage.warning('链接为空')
    return
  }
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
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

const resolvePan115ShareLink = (row) => {
  return String(row?.share_link || row?.share_url || row?.pan115_share_link || row?.url || '').trim()
}

const buildPansouKeywords = () => {
  const title = String(detail.value?.title || '').trim()
  const year = String(detail.value?.year || '').trim()
  const candidates = []
  if (title && year) candidates.push(`${title} ${year}`)
  if (title) candidates.push(title)
  return candidates
}

const fetchPan115Nullbr = async () => {
  if (!mappedTmdbId.value) return
  pan115Loading.value = true
  try {
    const response = mediaType.value === 'tv'
      ? await searchApi.getTvPan115(mappedTmdbId.value)
      : await searchApi.getMoviePan115(mappedTmdbId.value)
    const nullbrList = (Array.isArray(response.data?.list) ? response.data.list : [])
      .map((item) => ({ ...item, source_service: item.source_service || 'nullbr' }))
    pan115Resources.value = mergePan115Resources(nullbrList, mergePan115Resources(pansouPan115Resources.value, hdhivePan115Resources.value))
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '115资源获取失败')
  } finally {
    pan115Loading.value = false
  }
}

const fetchPansouPan115 = async () => {
  if (!detail.value || pansouLoading.value) return
  pansouLoading.value = true
  pansouTried.value = true
  try {
    let pansouList = []
    if (mappedTmdbId.value) {
      const response = mediaType.value === 'tv'
        ? await searchApi.getTvPan115Pansou(mappedTmdbId.value)
        : await searchApi.getMoviePan115Pansou(mappedTmdbId.value)
      pansouList = Array.isArray(response.data?.list) ? response.data.list : []
    } else {
      const keywords = buildPansouKeywords()
      const rows = []
      for (const keyword of keywords) {
        const { data } = await pansouApi.search(keyword, ['115'], 'results', false)
        const entries = Array.isArray(data?.items) ? data.items : []
        rows.push(...entries)
        if (rows.length >= 20) break
      }
      const dedup = new Map()
      for (const row of rows) {
        const link = resolvePan115ShareLink(row)
        if (!link) continue
        const key = link.toLowerCase()
        if (!dedup.has(key)) {
          dedup.set(key, { ...row, source_service: row.source_service || 'pansou' })
        }
      }
      pansouList = Array.from(dedup.values()).slice(0, 30)
    }
    const normalized = pansouList.map((item) => ({ ...item, source_service: item.source_service || 'pansou' }))
    pan115Resources.value = mergePan115Resources(mergePan115Resources(nullbrPan115Resources.value, hdhivePan115Resources.value), normalized)
    if (!normalized.length) {
      ElMessage.info('Pansou 暂未找到可用资源')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || 'Pansou 资源获取失败')
  } finally {
    pansouLoading.value = false
  }
}

const fetchHdhivePan115 = async () => {
  if (!mappedTmdbId.value || hdhiveLoading.value) return
  hdhiveLoading.value = true
  hdhiveTried.value = true
  try {
    const response = mediaType.value === 'tv'
      ? await searchApi.getTvPan115Hdhive(mappedTmdbId.value)
      : await searchApi.getMoviePan115Hdhive(mappedTmdbId.value)
    const hdhiveList = (Array.isArray(response.data?.list) ? response.data.list : [])
      .map((item) => ({ ...item, source_service: item.source_service || 'hdhive' }))
    pan115Resources.value = mergePan115Resources(
      mergePan115Resources(nullbrPan115Resources.value, pansouPan115Resources.value),
      hdhiveList
    )
    if (!hdhiveList.length) {
      ElMessage.info('HDHive 暂未找到可用资源')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || 'HDHive 资源获取失败')
  } finally {
    hdhiveLoading.value = false
  }
}

const fetchMagnetNullbr = async () => {
  if (!mappedTmdbId.value) return
  magnetLoading.value = true
  try {
    const magnetResp = mediaType.value === 'tv'
      ? await searchApi.getTvMagnet(mappedTmdbId.value)
      : await searchApi.getMovieMagnet(mappedTmdbId.value)
    const nullbrList = (Array.isArray(magnetResp.data?.list) ? magnetResp.data.list : [])
      .map((item) => ({ ...item, source_service: item?.source_service || 'nullbr' }))
    magnetResources.value = mergeMagnetResources(nullbrList, seedhubMagnetResources.value)
  } catch {
    magnetResources.value = seedhubMagnetResources.value.slice()
  } finally {
    magnetLoading.value = false
  }
}

const stopSeedhubTaskPolling = () => {
  if (seedhubPollTimer) {
    clearTimeout(seedhubPollTimer)
    seedhubPollTimer = null
  }
}

const resetSeedhubTaskState = async () => {
  stopSeedhubTaskPolling()
  const taskId = seedhubMagnetTaskId.value
  seedhubMagnetTaskId.value = ''
  if (!taskId) return
  try {
    await searchApi.cancelSeedhubMagnetTask(taskId)
  } catch {
    // ignore cleanup failures
  }
}

const pollSeedhubMagnetTask = async (taskId) => {
  try {
    const { data } = await searchApi.getSeedhubMagnetTask(taskId)
    const seedhubList = Array.isArray(data?.items) ? data.items : []
    magnetResources.value = mergeMagnetResources(magnetResources.value, seedhubList)

    const status = String(data?.status || '')
    if (status === 'queued' || status === 'running') {
      seedhubPollTimer = setTimeout(() => {
        seedhubPollTimer = null
        pollSeedhubMagnetTask(taskId)
      }, 1200)
      return
    }

    seedhubMagnetLoading.value = false
    if ((status === 'success' || status === 'partial_success') && seedhubList.length === 0) {
      ElMessage.info('SeedHub 暂未找到可用磁链')
    }
    if (status === 'failed') {
      ElMessage.error(data?.error || 'SeedHub 检索失败')
    }
  } catch (error) {
    stopSeedhubTaskPolling()
    seedhubMagnetLoading.value = false
    ElMessage.error(error.response?.data?.detail || error.message || 'SeedHub 磁链获取失败')
  } finally {
    if (seedhubMagnetLoading.value && !seedhubPollTimer) {
      seedhubMagnetLoading.value = false
    }
  }
}

const fetchSeedhubMagnet = async () => {
  if (!mappedTmdbId.value || seedhubMagnetLoading.value) return
  seedhubMagnetLoading.value = true
  seedhubMagnetTried.value = true
  stopSeedhubTaskPolling()
  try {
    const request = mediaType.value === 'tv'
      ? searchApi.createTvSeedhubMagnetTask(mappedTmdbId.value)
      : searchApi.createMovieSeedhubMagnetTask(mappedTmdbId.value)
    const { data } = await request
    const taskId = String(data?.task_id || '')
    if (!taskId) throw new Error('未获取到任务ID')
    seedhubMagnetTaskId.value = taskId
    await pollSeedhubMagnetTask(taskId)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || 'SeedHub 磁链获取失败')
    seedhubMagnetLoading.value = false
    stopSeedhubTaskPolling()
  }
}

const fetchEd2kResources = async () => {
  if (!mappedTmdbId.value) return
  ed2kLoading.value = true
  try {
    const ed2kResp = mediaType.value === 'tv'
      ? await searchApi.getTvEd2k(mappedTmdbId.value)
      : await searchApi.getMovieEd2k(mappedTmdbId.value)
    ed2kResources.value = Array.isArray(ed2kResp.data?.list) ? ed2kResp.data.list : []
  } catch {
    ed2kResources.value = []
  } finally {
    ed2kLoading.value = false
  }
}

const ensureActiveTabLoaded = async () => {
  if (!detail.value) return
  if (activeTab.value === 'pan115') {
    if (pan115SourceTab.value === 'pansou') {
      if (pansouPan115Resources.value.length === 0 && !pansouLoading.value && !pansouTried.value) {
        await fetchPansouPan115()
      }
      return
    }
    if (pan115SourceTab.value === 'hdhive') {
      if (hdhivePan115Resources.value.length === 0 && !hdhiveLoading.value && !hdhiveTried.value && mappedTmdbId.value) {
        await fetchHdhivePan115()
      }
      return
    }
    if (nullbrPan115Resources.value.length === 0 && !pan115Loading.value && mappedTmdbId.value) {
      await fetchPan115Nullbr()
    }
    return
  }

  if (activeTab.value === 'magnet') {
    if (!mappedTmdbId.value) return
    if (magnetSourceTab.value === 'seedhub') {
      if (seedhubMagnetResources.value.length === 0 && !seedhubMagnetLoading.value && !seedhubMagnetTried.value) {
        await fetchSeedhubMagnet()
      }
      return
    }
    if (nullbrMagnetResources.value.length === 0 && !magnetLoading.value) {
      await fetchMagnetNullbr()
    }
    return
  }

  if (activeTab.value === 'ed2k' && mappedTmdbId.value && ed2kResources.value.length === 0 && !ed2kLoading.value) {
    await fetchEd2kResources()
  }
}

const loadDetail = async () => {
  if (!doubanId.value) return
  loading.value = true
  try {
    const { data } = await searchApi.getDoubanSubject(doubanId.value, mediaType.value)
    detail.value = {
      ...data,
      genres: Array.isArray(data?.genres) ? data.genres : [],
      casts: Array.isArray(data?.casts) ? data.casts : []
    }
    pan115SourceTab.value = mappedTmdbId.value ? 'nullbr' : 'pansou'
    await refreshSubscribeState()
    await ensureActiveTabLoaded()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '豆瓣详情获取失败')
  } finally {
    loading.value = false
  }
}

const getDefaultTransferFolderId = async () => {
  try {
    const { data } = await pan115Api.getDefaultFolder()
    return data.folder_id || '0'
  } catch {
    return '0'
  }
}

const isVideoFile = (filename) => {
  const value = String(filename || '').trim()
  if (!value) return false
  return /\.(mp4|mkv|avi|rmvb|flv|ts|mov|wmv|m4v)$/i.test(value)
}

const savePan115Resource = async (row) => {
  const shareLink = resolvePan115ShareLink(row)
  if (!shareLink) {
    ElMessage.warning('资源缺少分享链接')
    return
  }
  row.saving = true
  try {
    const folderId = await getDefaultTransferFolderId()
    const folderName = detail.value?.title || '豆瓣资源'
    const receiveCode = parseReceiveCodeFromShareLink(shareLink)
    const { data } = await pan115Api.saveShareToFolder(
      shareLink,
      folderName,
      folderId,
      receiveCode,
      mappedTmdbId.value && mediaType.value === 'tv' ? mappedTmdbId.value : null
    )
    const success = data?.success === true || data?.state === true || data?.result?.success === true || data?.result?.state === true
    if (!success) throw new Error(data?.message || data?.error || data?.result?.error || '转存失败')
    ElMessage.success(data?.message || '转存成功')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '转存失败')
  } finally {
    row.saving = false
  }
}

const openSelectSaveDialog = async (row) => {
  const shareLink = resolvePan115ShareLink(row)
  if (!shareLink) {
    ElMessage.warning('资源缺少分享链接')
    return
  }
  if (mediaType.value !== 'tv') {
    ElMessage.warning('仅剧集资源支持选集转存')
    return
  }

  row.extracting = true
  extractingFiles.value = true
  shareFilesList.value = []
  selectedFiles.value = []
  fileNameSortOrder.value = 'asc'
  selectSaveDialogVisible.value = true

  try {
    const folderId = await getDefaultTransferFolderId()
    const folderName = detail.value?.title || '豆瓣剧集'
    const receiveCode = parseReceiveCodeFromShareLink(shareLink)
    selectSaveForm.value = {
      shareLink,
      receiveCode,
      targetFolder: folderId,
      newFolderName: folderName
    }

    const { data } = await pan115Api.extractShareFiles(shareLink, receiveCode)
    const allFiles = Array.isArray(data?.list) ? data.list : []
    shareFilesList.value = allFiles.filter((item) => isVideoFile(item?.name))
    sortShareFilesByName(fileNameSortOrder.value)
    if (shareFilesList.value.length === 0) {
      ElMessage.info('未找到可选的视频文件')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提取文件列表失败')
  } finally {
    row.extracting = false
    extractingFiles.value = false
  }
}

const handleSelectionChange = (rows) => {
  const list = Array.isArray(rows) ? rows : []
  selectedFiles.value = list
    .map((item) => String(item?.fid || '').trim())
    .filter(Boolean)
}

const sortShareFilesByName = (order = 'asc') => {
  const direction = order === 'desc' ? -1 : 1
  shareFilesList.value = [...shareFilesList.value].sort((a, b) => {
    const aName = String(a?.name || '')
    const bName = String(b?.name || '')
    return aName.localeCompare(bName, 'zh-Hans-CN', { numeric: true, sensitivity: 'base' }) * direction
  })
}

const setFileNameSortOrder = (order) => {
  const nextOrder = order === 'desc' ? 'desc' : 'asc'
  fileNameSortOrder.value = nextOrder
  sortShareFilesByName(nextOrder)
}

const confirmSelectSave = async () => {
  if (selectedFiles.value.length === 0) {
    ElMessage.warning('请先选择要转存的文件')
    return
  }

  selectSaving.value = true
  try {
    const { data } = await pan115Api.saveShareFilesToFolder(
      selectSaveForm.value.shareLink,
      selectedFiles.value,
      selectSaveForm.value.newFolderName || (detail.value?.title || '豆瓣剧集'),
      selectSaveForm.value.targetFolder,
      selectSaveForm.value.receiveCode
    )
    const success = data?.success === true || data?.state === true || data?.result?.success === true || data?.result?.state === true
    if (!success) {
      throw new Error(data?.message || data?.error || data?.result?.error || '转存失败')
    }
    ElMessage.success(data?.message || `成功转存 ${selectedFiles.value.length} 个文件`)
    selectSaveDialogVisible.value = false
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '转存失败')
  } finally {
    selectSaving.value = false
  }
}

const saveMagnet = async (row) => {
  const url = String(row?.magnet || '').trim()
  if (!url) {
    ElMessage.warning('磁链为空')
    return
  }
  try {
    const folderId = await getDefaultTransferFolderId()
    await pan115Api.addOfflineTask(url, folderId)
    ElMessage.success('已提交离线任务')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '离线失败')
  }
}

const saveEd2k = async (row) => {
  const url = String(row?.ed2k || row?.url || '').trim()
  if (!url) {
    ElMessage.warning('ED2K 链接为空')
    return
  }
  try {
    const folderId = await getDefaultTransferFolderId()
    await pan115Api.addOfflineTask(url, folderId)
    ElMessage.success('已提交离线任务')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '离线失败')
  }
}

const refreshSubscribeState = async () => {
  if (!mappedTmdbId.value) {
    isSubscribed.value = false
    return
  }
  try {
    const { data } = await subscriptionApi.list({ media_type: mediaType.value, is_active: true })
    const list = Array.isArray(data) ? data : []
    isSubscribed.value = list.some((item) => Number(item.tmdb_id) === mappedTmdbId.value && item.media_type === mediaType.value)
  } catch {
    isSubscribed.value = false
  }
}

const handleSubscribe = async () => {
  if (!mappedTmdbId.value || !detail.value) {
    ElMessage.warning('请先匹配 TMDB 后再订阅')
    return
  }
  subscribing.value = true
  try {
    if (isSubscribed.value) {
      const { data } = await subscriptionApi.list({ media_type: mediaType.value, is_active: true })
      const list = Array.isArray(data) ? data : []
      const target = list.find((item) => Number(item.tmdb_id) === mappedTmdbId.value && item.media_type === mediaType.value)
      if (!target?.id) {
        ElMessage.warning('未找到订阅记录')
        return
      }
      await subscriptionApi.delete(target.id)
      isSubscribed.value = false
      ElMessage.success('已取消订阅')
      return
    }

    await subscriptionApi.create({
      douban_id: detail.value.douban_id,
      tmdb_id: mappedTmdbId.value,
      title: detail.value.title,
      media_type: mediaType.value,
      poster_path: '',
      overview: detail.value.intro || '',
      year: detail.value.year || '',
      rating: detail.value.rating || null
    })
    isSubscribed.value = true
    ElMessage.success('订阅成功')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '订阅失败')
  } finally {
    subscribing.value = false
  }
}

const resetResources = () => {
  pan115Resources.value = []
  magnetResources.value = []
  ed2kResources.value = []
  pan115Loading.value = false
  pansouLoading.value = false
  pansouTried.value = false
  hdhiveLoading.value = false
  hdhiveTried.value = false
  magnetLoading.value = false
  seedhubMagnetLoading.value = false
  seedhubMagnetTried.value = false
  ed2kLoading.value = false
  selectSaveDialogVisible.value = false
  extractingFiles.value = false
  selectSaving.value = false
  shareFilesList.value = []
  selectedFiles.value = []
  fileNameSortOrder.value = 'asc'
}

const handleRematchTmdb = async () => {
  if (!detail.value) return
  mappingLoading.value = true
  try {
    const payload = {
      source: 'douban',
      id: detail.value.douban_id,
      douban_id: detail.value.douban_id,
      title: detail.value.title,
      year: detail.value.year || '',
      media_type: mediaType.value,
      tmdb_id: null
    }
    const { data } = await searchApi.resolveExploreItem(payload)
    detail.value.tmdb_mapping = {
      resolved: Boolean(data?.resolved && data?.tmdb_id),
      tmdb_id: data?.tmdb_id || null,
      reason: data?.reason || '',
      confidence: Number(data?.confidence || 0)
    }
    if (mappedTmdbId.value) {
      ElMessage.success('TMDB 匹配成功')
      await refreshSubscribeState()
      if (pan115SourceTab.value === 'nullbr') {
        await fetchPan115Nullbr()
      }
      await ensureActiveTabLoaded()
      return
    }
    ElMessage.warning('仍未匹配到 TMDB，可继续使用豆瓣关键词 115 方案')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '重试匹配失败')
  } finally {
    mappingLoading.value = false
  }
}

const openDoubanPage = () => {
  const url = String(detail.value?.source_url || '').trim()
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

watch(activeTab, async () => {
  await ensureActiveTabLoaded()
})

watch(pan115SourceTab, async (tab) => {
  if (tab === 'pansou' && pansouPan115Resources.value.length === 0 && !pansouLoading.value && !pansouTried.value) {
    await fetchPansouPan115()
    return
  }
  if (tab === 'hdhive' && hdhivePan115Resources.value.length === 0 && mappedTmdbId.value && !hdhiveLoading.value && !hdhiveTried.value) {
    await fetchHdhivePan115()
    return
  }
  if (tab === 'nullbr' && nullbrPan115Resources.value.length === 0 && mappedTmdbId.value && !pan115Loading.value) {
    await fetchPan115Nullbr()
  }
})

watch(magnetSourceTab, async (tab) => {
  if (tab === 'seedhub' && seedhubMagnetResources.value.length === 0 && mappedTmdbId.value && !seedhubMagnetLoading.value && !seedhubMagnetTried.value) {
    await fetchSeedhubMagnet()
    return
  }
  if (tab === 'nullbr' && nullbrMagnetResources.value.length === 0 && mappedTmdbId.value && !magnetLoading.value) {
    await fetchMagnetNullbr()
  }
})

watch(() => `${route.params.mediaType || ''}:${route.params.id || ''}`, async () => {
  await resetSeedhubTaskState()
  activeTab.value = 'pan115'
  pan115SourceTab.value = 'nullbr'
  magnetSourceTab.value = 'nullbr'
  resetResources()
  await loadDetail()
})

onMounted(async () => {
  await loadDetail()
})

onBeforeUnmount(async () => {
  await resetSeedhubTaskState()
})
</script>

<style scoped lang="scss">
.douban-detail-page {
  padding: 20px;

  .detail-header {
    display: flex;
    gap: 20px;
    margin-bottom: 18px;

    .poster {
      width: 220px;
      flex-shrink: 0;

      img {
        width: 100%;
        border-radius: 12px;
        object-fit: cover;
      }
    }

    .info {
      flex: 1;

      .title {
        margin: 0;
        font-size: 28px;
      }

      .original-title {
        margin-top: 6px;
        color: #606266;
      }

      .meta {
        display: flex;
        gap: 14px;
        margin-top: 8px;
        color: #606266;
      }

      .genres {
        margin-top: 10px;
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }

      .overview {
        margin-top: 14px;
        line-height: 1.7;
      }

      .actions {
        margin-top: 14px;
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
      }

      .mapping-tip {
        margin-top: 10px;
        color: #909399;
        font-size: 13px;
      }
    }
  }

  .resource-tools {
    margin-bottom: 10px;
  }

  :deep(.resource-table) {
    --el-table-tr-bg-color: transparent;
    --el-table-row-hover-bg-color: rgba(61, 119, 188, 0.12);
    --el-table-header-bg-color: rgba(79, 145, 226, 0.12);
    --el-table-border-color: rgba(79, 145, 226, 0.18);
  }

  .resource-name {
    font-weight: 500;
  }

  .resource-size {
    color: var(--ms-text-secondary);
    font-weight: 500;
  }

  .text-muted {
    color: var(--ms-text-muted);
    font-size: 12px;
    line-height: 1.4;
    margin-top: 2px;
  }
}

@media (max-width: 900px) {
  .douban-detail-page .detail-header {
    flex-direction: column;

    .poster {
      width: 170px;
    }
  }
}
</style>
