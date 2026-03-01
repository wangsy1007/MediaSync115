<template>
  <div class="tv-detail-page" v-loading="loading">
    <template v-if="tv">
      <div class="detail-header">
        <div class="poster">
          <img :src="getPosterUrl(tv.poster_path)" :alt="tv.name" />
        </div>
        <div class="info">
          <h1 class="title">{{ tv.name }}</h1>
          <p class="original-title" v-if="tv.original_name !== tv.name">
            {{ tv.original_name }}
          </p>
          <div class="meta">
            <span class="year">{{ tv.first_air_date?.split('-')[0] }}</span>
            <span class="rating">
              <el-icon><Star /></el-icon>
              {{ tv.vote_average?.toFixed(1) }}
            </span>
            <span class="seasons" v-if="tv.number_of_seasons">
              {{ tv.number_of_seasons }} 季            </span>
          </div>
          <div class="genres">
            <el-tag v-for="genre in tv.genres" :key="genre.id" size="small">
              {{ genre.name }}
            </el-tag>
          </div>
          <p class="overview">{{ tv.overview }}</p>
          <div class="actions">
            <el-button :type="isSubscribed ? 'success' : 'primary'" @click="handleSubscribe">
              <el-icon><Plus /></el-icon>
              {{ isSubscribed ? '已订阅（点击取消）' : '添加订阅' }}
            </el-button>
          </div>
        </div>
      </div>

      <div class="season-selector" v-if="seasonsList.length > 0">
        <el-select v-model="selectedSeason" placeholder="选择季度" @change="handleSeasonChange">
          <el-option
            v-for="seasonNum in seasonsList"
            :key="seasonNum"
            :label="`第${seasonNum}季`"
            :value="seasonNum"
          />
        </el-select>
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
                      <div class="resource-name">{{ row.resource_name || row.title }}</div>
                      <div v-if="row.resource_name && row.title && row.resource_name !== row.title" class="text-muted">
                        {{ row.title }}
                      </div>
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
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" size="small" @click="handleSaveToPan115(row)">
                        一键转存
                      </el-button>
                      <el-button size="small" @click="handleSelectSave(row)">
                        选集
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
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" size="small" @click="handleSaveToPan115(row)">
                        一键转存
                      </el-button>
                      <el-button size="small" @click="handleSelectSave(row)">
                        选集
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

            <el-tab-pane label="HDHive" name="hdhive">
              <div class="resource-tools">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="hdhiveLoading"
                  @click="handleFetchHdhivePan115"
                >
                  {{ hdhiveTried ? '刷新 HDHive' : '用 HDHive 获取资源' }}
                </el-button>
              </div>
              <div v-loading="pan115Loading || hdhiveLoading">
                <el-table
                  v-if="hdhivePan115Resources.length > 0"
                  :data="hdhivePan115Resources"
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
                      <el-tag size="small" type="info" v-if="row.resolution">{{ Array.isArray(row.resolution) ? row.resolution.join(', ') : row.resolution }}</el-tag>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="大小" width="100" align="center">
                    <template #default="{ row }">
                      <span class="resource-size">{{ row.size || '-' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="积分" width="80" align="center">
                    <template #default="{ row }">
                      <span>{{ Number(row.unlock_points || 0) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" size="small" :disabled="row.pan115_savable === false" @click="handleSaveToPan115(row)">
                        一键转存
                      </el-button>
                      <el-button size="small" :disabled="row.pan115_savable === false" @click="handleSelectSave(row)">
                        选集
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty
                  v-else
                  :description="hdhiveTried ? 'HDHive 暂无可用115网盘资源' : '尚未获取 HDHive 资源'"
                />
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="磁力链接" name="magnet">
          <el-tabs v-model="magnetSourceTab" class="source-tabs">
            <el-tab-pane label="Nullbr" name="nullbr">
              <div v-loading="magnetLoading">
                <el-table
                  v-if="nullbrMagnetResources.length > 0"
                  :data="nullbrMagnetResources"
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
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" size="small" @click="handleSaveMagnet(row)">
                        离线下载
                      </el-button>
                      <el-button size="small" @click="handleCopyMagnet(row.magnet)">
                        复制
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-else description="Nullbr 暂无磁力资源" />
              </div>
            </el-tab-pane>

            <el-tab-pane label="SeedHub" name="seedhub">
              <div class="resource-tools">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="seedhubMagnetLoading"
                  @click="handleFetchSeedhubMagnet"
                >
                  {{ seedhubMagnetTried ? '重新尝试 SeedHub' : '用 SeedHub 获取磁链' }}
                </el-button>
              </div>
              <div v-loading="seedhubMagnetLoading">
                <el-table
                  v-if="seedhubMagnetResources.length > 0"
                  :data="seedhubMagnetResources"
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
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" size="small" @click="handleSaveMagnet(row)">
                        离线下载
                      </el-button>
                      <el-button size="small" @click="handleCopyMagnet(row.magnet)">
                        复制
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty
                  v-else
                  :description="seedhubMagnetTried ? 'SeedHub 暂无磁力资源' : '尚未获取 SeedHub 资源'"
                />
              </div>
            </el-tab-pane>
          </el-tabs>
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
              <el-table-column label="操作" width="180" align="center" fixed="right">
                <template #default="{ row }">
                  <el-button type="primary" size="small" @click="handleSaveEd2k(row)">
                    离线下载
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

    <!-- 选集转存对话框 -->
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
          @click="confirmSelectSave" 
          :loading="saving"
          :disabled="selectedFiles.length === 0 || extractingFiles"
        >
          确认转存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onBeforeUnmount, onMounted, watch, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { searchApi, subscriptionApi, pan115Api } from '@/api'

const route = useRoute()

const tv = ref(null)
const loading = ref(true)
const activeTab = ref('pan115')
const pan115SourceTab = ref('nullbr')
const magnetSourceTab = ref('nullbr')
const selectedSeason = ref(1)

// 生成季度列表
const seasonsList = computed(() => {
  if (!tv.value) return []
  if (tv.value.seasons && tv.value.seasons.length > 0) {
    return tv.value.seasons.map(s => s.season_number)
  }
  if (tv.value.number_of_seasons) {
    return Array.from({ length: tv.value.number_of_seasons }, (_, i) => i + 1)
  }
  return []
})

const pan115Resources = ref([])
const magnetResources = ref([])
const ed2kResources = ref([])

const pan115Loading = ref(false)
const pansouLoading = ref(false)
const pansouTried = ref(false)
const hdhiveLoading = ref(false)
const hdhiveTried = ref(false)
const magnetLoading = ref(false)
const seedhubMagnetLoading = ref(false)
const seedhubMagnetTried = ref(false)
const seedhubMagnetTaskId = ref('')
let seedhubPollTimer = null
const ed2kLoading = ref(false)
const isSubscribed = ref(false)
const subscriptionId = ref(null)

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w500'
const PAN115_CACHE_TTL_MS = 30 * 60 * 1000

// 转存对话框相关
// 转存相关
const saving = ref(false)

// 选集转存相关
const selectSaveDialogVisible = ref(false)
const extractingFiles = ref(false)
const shareFilesList = ref([])
const selectedFiles = ref([])
const fileNameSortOrder = ref('asc')
const selectSaveForm = ref({
  shareLink: '',
  targetFolder: '0',
  newFolderName: ''
})

const getPosterUrl = (path) => {
  if (!path) return new URL('/no-poster.png', import.meta.url).href
  return TMDB_IMAGE_BASE + path
}

const getPan115CacheKey = () => `tv_pan115_${route.params.id}`

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

const hdhivePan115Resources = computed(() =>
  pan115Resources.value.filter((item) => item?.source_service === 'hdhive')
)

const nullbrMagnetResources = computed(() =>
  magnetResources.value.filter((item) => (item?.source_service || 'nullbr') === 'nullbr')
)

const seedhubMagnetResources = computed(() =>
  magnetResources.value.filter((item) => item?.source_service === 'seedhub')
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
  if (service === 'hdhive') return 'HDHive'
  if (service === 'nullbr') return 'Nullbr'
  return service || '未知'
}

const fetchTv = async () => {
  const tmdbId = route.params.id
  loading.value = true

  try {
    const { data } = await searchApi.getTv(tmdbId)
    // 适配后端返回字段名
    tv.value = {
      ...data,
      poster_path: data.poster || data.poster_path,
      vote_average: data.vote || data.vote_average,
      first_air_date: data.release_date || data.first_air_date,
      name: data.title || data.name
    }
    // 生成季度列表（如果有 seasons 数据）
    if (data.seasons && data.seasons.length > 0) {
      selectedSeason.value = data.seasons[data.seasons.length - 1].season_number
    } else if (data.number_of_seasons) {
      // 根据 number_of_seasons 生成季度列表
      selectedSeason.value = data.number_of_seasons
    }
  } catch (error) {
    ElMessage.error('获取电视剧信息失败')
  } finally {
    loading.value = false
  }
}

const fetchPan115 = async () => {
  const cachedList = readPan115Cache()
  if (cachedList && cachedList.length > 0) {
    pan115Resources.value = cachedList
    pansouTried.value = cachedList.some((item) => item?.source_service === 'pansou')
    hdhiveTried.value = cachedList.some((item) => item?.source_service === 'hdhive')
    pan115Loading.value = false
  } else {
    pansouTried.value = false
    hdhiveTried.value = false
    pan115Loading.value = true
  }

  try {
    const { data } = await searchApi.getTvPan115(route.params.id)
    const nullbrList = Array.isArray(data.list) ? data.list : []
    const cachedPansouList = pan115Resources.value.filter((item) => item?.source_service === 'pansou')
    const cachedHdhiveList = pan115Resources.value.filter((item) => item?.source_service === 'hdhive')
    const mergedList = mergePan115Resources(nullbrList, mergePan115Resources(cachedPansouList, cachedHdhiveList))
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
    const { data } = await searchApi.getTvPan115Pansou(route.params.id)
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

const handleFetchHdhivePan115 = async () => {
  if (hdhiveLoading.value) return
  hdhiveLoading.value = true
  hdhiveTried.value = true
  try {
    const { data } = await searchApi.getTvPan115Hdhive(route.params.id)
    const hdhiveList = Array.isArray(data.list) ? data.list : []
    const mergedList = mergePan115Resources(pan115Resources.value, hdhiveList)
    pan115Resources.value = mergedList
    writePan115Cache(mergedList)
    if (hdhiveList.length === 0) {
      ElMessage.info('HDHive 暂未找到可用资源')
    }
  } catch (error) {
    console.error('Failed to fetch hdhive pan115:', error)
  } finally {
    hdhiveLoading.value = false
  }
}

const fetchMagnet = async () => {
  magnetLoading.value = true
  try {
    const { data } = await searchApi.getTvMagnet(route.params.id, selectedSeason.value)
    const nullbrList = Array.isArray(data.list) ? data.list : []
    const markedNullbrList = nullbrList.map((item) => ({ ...item, source_service: item?.source_service || 'nullbr' }))
    const existingSeedhub = magnetResources.value.filter((item) => item?.source_service === 'seedhub')
    magnetResources.value = mergeMagnetResources(markedNullbrList, existingSeedhub)
  } catch (error) {
    console.error('Failed to fetch magnet:', error)
  } finally {
    magnetLoading.value = false
  }
}

const handleFetchSeedhubMagnet = async () => {
  if (seedhubMagnetLoading.value) return
  seedhubMagnetLoading.value = true
  seedhubMagnetTried.value = true

  stopSeedhubTaskPolling()
  try {
    const { data } = await searchApi.createTvSeedhubMagnetTask(route.params.id)
    const taskId = String(data?.task_id || '')
    if (!taskId) {
      throw new Error('未获取到任务ID')
    }
    seedhubMagnetTaskId.value = taskId
    await pollSeedhubMagnetTask(taskId)
  } catch (error) {
    console.error('Failed to fetch seedhub magnet:', error)
    ElMessage.error(error.response?.data?.detail || error.message || 'SeedHub 磁链获取失败')
    seedhubMagnetLoading.value = false
    stopSeedhubTaskPolling()
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

const fetchEd2k = async () => {
  ed2kLoading.value = true
  try {
    const { data } = await searchApi.getTvEd2k(route.params.id, selectedSeason.value)
    ed2kResources.value = data.list || []
  } catch (error) {
    console.error('Failed to fetch ed2k:', error)
  } finally {
    ed2kLoading.value = false
  }
}

const handleSeasonChange = () => {
  magnetSourceTab.value = 'nullbr'
  magnetResources.value = []
  ed2kResources.value = []
  seedhubMagnetTried.value = false

  if (activeTab.value === 'magnet') fetchMagnet()
  else if (activeTab.value === 'ed2k') fetchEd2k()
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
      tmdb_id: tv.value.id,
      title: tv.value.name,
      media_type: 'tv',
      poster_path: tv.value.poster_path,
      overview: tv.value.overview,
      year: tv.value.first_air_date?.split('-')[0],
      rating: tv.value.vote_average
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
    const { data } = await subscriptionApi.list({ media_type: 'tv' })
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
  // 检查是否有分享链接
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

  const seasonSuffix = selectedSeason.value ? ` S${String(selectedSeason.value).padStart(2, '0')}` : ''
  const folderName = tv.value.name + ' (' + tv.value.first_air_date?.split('-')[0] + ')' + seasonSuffix
  
  try {
    // 由后端统一解析分享链接并执行转存
    const { data } = await pan115Api.saveShareToFolder(
      item.share_link,
      folderName,
      defaultFolderId,
      '',
      Number(route.params.id)
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

// 选集转存相关方法
const handleSelectSave = async (item) => {
  if (!item.share_link) {
    ElMessage.warning('该资源暂无分享链接')
    return
  }

  let defaultFolderId = '0'
  try {
    const { data } = await pan115Api.getDefaultFolder()
    defaultFolderId = data.folder_id || '0'
  } catch (error) {
    console.error('Failed to get default folder:', error)
  }

  const seasonSuffix = selectedSeason.value ? ` S${String(selectedSeason.value).padStart(2, '0')}` : ''
  selectSaveForm.value = {
    shareLink: item.share_link,
    targetFolder: defaultFolderId,
    newFolderName: tv.value.name + ' (' + tv.value.first_air_date?.split('-')[0] + ')' + seasonSuffix
  }

  shareFilesList.value = []
  selectedFiles.value = []
  fileNameSortOrder.value = 'asc'
  selectSaveDialogVisible.value = true
  extractingFiles.value = true

  try {
    const { data } = await pan115Api.extractShareFiles(item.share_link)
    if (data && Array.isArray(data.list)) {
      // 过滤视频文件
      const videoRegex = /\.(mp4|mkv|avi|rmvb|flv|ts|mov|wmv)$/i
      shareFilesList.value = data.list.filter(f => videoRegex.test(f.name || ''))
      sortShareFilesByName(fileNameSortOrder.value)
    } else {
      ElMessage.warning('提取文件列表失败，分享可能已失效')
    }
  } catch (error) {
    ElMessage.error('提取文件列表失败')
  } finally {
    extractingFiles.value = false
  }
}

const handleSelectionChange = (val) => {
  selectedFiles.value = val.map(f => f.fid)
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
  
  saving.value = true
  try {
    const { data } = await pan115Api.saveShareFilesToFolder(
      selectSaveForm.value.shareLink,
      selectedFiles.value,
      selectSaveForm.value.newFolderName,
      selectSaveForm.value.targetFolder
    )
    
    if (data?.success || data?.result?.success) {
      ElMessage.success(`成功转存 ${data?.file_count || selectedFiles.value.length} 个文件`)
      selectSaveDialogVisible.value = false
    } else {
      throw new Error(data?.message || '转存失败')
    }
  } catch (error) {
    const detail = String(error.response?.data?.detail || '').trim()
    if (detail.includes('离线任务列表请求过于频繁')) {
      ElMessage.error('115接口触发风控，请稍后重试')
      return
    }
    ElMessage.error(detail || error.message || '转存失败')
  } finally {
    saving.value = false
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

  const seasonSuffix = selectedSeason.value ? ` S${String(selectedSeason.value).padStart(2, '0')}` : ''
  const folderName = tv.value.name + ' (' + tv.value.first_air_date?.split('-')[0] + ')' + seasonSuffix

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

  const seasonSuffix = selectedSeason.value ? ` S${String(selectedSeason.value).padStart(2, '0')}` : ''
  const folderName = tv.value.name + ' (' + tv.value.first_air_date?.split('-')[0] + ')' + seasonSuffix

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

watch(magnetSourceTab, (tab) => {
  if (tab === 'seedhub' && seedhubMagnetResources.value.length === 0 && !seedhubMagnetLoading.value) {
    handleFetchSeedhubMagnet()
  }
})

watch(pan115SourceTab, (tab) => {
  if (tab === 'pansou' && pansouPan115Resources.value.length === 0 && !pansouLoading.value && !pansouTried.value) {
    handleFetchPansouPan115()
  } else if (tab === 'hdhive' && hdhivePan115Resources.value.length === 0 && !hdhiveLoading.value && !hdhiveTried.value) {
    handleFetchHdhivePan115()
  }
})

watch(() => route.params.id, () => {
  resetSeedhubTaskState()
  pan115SourceTab.value = 'nullbr'
  magnetSourceTab.value = 'nullbr'
  pan115Resources.value = []
  pansouTried.value = false
  pansouLoading.value = false
  hdhiveTried.value = false
  hdhiveLoading.value = false
  seedhubMagnetTried.value = false
  seedhubMagnetLoading.value = false
  magnetResources.value = []
  ed2kResources.value = []
  fetchTv()
  fetchPan115()
  checkSubscribed()
})

onMounted(() => {
  fetchTv()
  fetchPan115()
  checkSubscribed()
})

onBeforeUnmount(() => {
  resetSeedhubTaskState()
})
</script>

<style lang="scss" scoped>
.tv-detail-page {
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
        
        .year, .seasons {
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

  .season-selector {
    margin-bottom: 24px;
    
    :deep(.el-select) {
      width: 160px;
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
          background: rgba(17, 37, 72, 0.34);
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
