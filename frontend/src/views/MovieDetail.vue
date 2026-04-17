<template>
  <div class="movie-detail-page" v-loading="loading">
    <template v-if="movie">
      <div class="detail-header">
        <div class="poster">
          <img :src="getPosterUrl(movie.poster_path)" :alt="movie.title" />
        </div>
        <div class="info">
          <div class="title-row">
            <h1 class="title">{{ movie.title }}</h1>
            <LibraryBadge
              v-if="isInMediaLibrary"
              class="emby-badge-inline"
              inline
              :in-emby="isInEmby"
              :in-feiniu="isInFeiniu"
            />
          </div>
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
            <el-button :type="isSubscribed ? 'success' : 'primary'" :loading="subscribing" :disabled="subscribing" @click="handleSubscribe">
              <el-icon><Plus /></el-icon>
              {{ isSubscribed ? '已订阅（点击取消）' : '添加订阅' }}
            </el-button>
          </div>
          <div v-if="doubanLink" class="external-links">
            <span class="link-label">外部链接：</span>
            <a v-if="doubanLink.douban_id" :href="`https://movie.douban.com/subject/${doubanLink.douban_id}/`" target="_blank" class="external-link douban-link">
              <el-tag size="small" type="success">豆瓣</el-tag>
            </a>
            <span v-if="doubanLink.imdb_id" class="imdb-tag">IMDB: {{ doubanLink.imdb_id }}</span>
          </div>
        </div>
      </div>

      <el-tabs v-model="activeTab" class="resource-tabs">
        <el-tab-pane v-if="tabVisible('pan115')" label="115网盘" name="pan115">
          <el-tabs v-model="pan115SourceTab" class="source-tabs">
            <el-tab-pane v-if="tabVisible('pan115_pansou')" label="Pansou" name="pansou">
              <div class="resource-tools">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="pansouLoading"
                  @click="handleFetchPansouPan115(true)"
                >
                  {{ pansouTried ? '重新尝试 Pansou' : '用 Pansou 获取资源' }}
                </el-button>
              </div>
              <div v-loading="pan115Loading || pansouLoading">
                <div v-if="pan115Diagnostics.pansou.visible" class="resource-diagnostics">
                  <span class="diag-title">诊断</span>
                  <span v-if="pan115Diagnostics.pansou.keyword" class="diag-meta">
                    命中关键词: {{ pan115Diagnostics.pansou.keyword }}
                  </span>
                  <span v-if="pan115Diagnostics.pansou.attemptText" class="diag-meta">
                    {{ pan115Diagnostics.pansou.attemptText }}
                  </span>
                  <span v-if="pan115Diagnostics.pansou.error" class="diag-error">
                    {{ pan115Diagnostics.pansou.error }}
                  </span>
                </div>
                <el-table 
                  v-if="pansouPan115Resources.length > 0" 
                  :data="pagedPansouPan115Resources" 
                  stripe
                  class="resource-table"
                >
                  <el-table-column label="资源名称" min-width="300" show-overflow-tooltip>
                    <template #default="{ row }">
                      <div class="resource-name-row">
                        <span class="resource-name">{{ row.title }}</span>
                        <el-tag
                          v-if="isHdhiveResourceSuspectedInvalid(row)"
                          size="small"
                          type="danger"
                          effect="plain"
                        >
                          疑似失效
                        </el-tag>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="画质" width="160" align="center">
                    <template #default="{ row }">
                      <template v-if="row.quality && (Array.isArray(row.quality) ? row.quality.length : row.quality)">
                        <el-tag size="small">{{ Array.isArray(row.quality) ? row.quality.join(', ') : row.quality }}</el-tag>
                      </template>
                      <template v-else-if="getRowTags(row).formats.length">
                        <el-tag size="small" v-for="f in getRowTags(row).formats.slice(0, 3)" :key="f">{{ f }}</el-tag>
                      </template>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="分辨率" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info" v-if="row.resolution">{{ Array.isArray(row.resolution) ? row.resolution.join(', ') : row.resolution }}</el-tag>
                      <el-tag size="small" type="info" v-else-if="getRowTags(row).resolution">{{ getRowTags(row).resolution }}</el-tag>
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
                      <el-button
                        type="primary"
                        size="small"
                        :loading="Boolean(row?.saving) || isHdhiveUnlocking(row)"
                        :disabled="isPan115ActionDisabled(row)"
                        @click="handleSaveToPan115(row)"
                      >
                        转存
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <div v-if="pansouPan115Resources.length > pan115PageSize" class="table-pagination">
                  <el-pagination
                    background
                    layout="prev, pager, next"
                    :total="pansouPan115Resources.length"
                    :page-size="pan115PageSize"
                    :current-page="pan115Pager.pansou"
                    @current-change="(page) => (pan115Pager.pansou = page)"
                  />
                </div>
                <el-empty
                  v-else
                  :description="pansouTried ? '暂无可用115网盘资源' : '尚未获取 Pansou 资源'"
                />
              </div>
            </el-tab-pane>

            <el-tab-pane v-if="tabVisible('pan115_hdhive')" label="HDHive" name="hdhive">
              <div class="resource-tools">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="hdhiveLoading"
                  @click="handleFetchHdhivePan115(true)"
                >
                  {{ hdhiveTried ? '刷新 HDHive' : '用 HDHive 获取资源' }}
                </el-button>
              </div>
              <div v-loading="pan115Loading || hdhiveLoading">
                <div v-if="pan115Diagnostics.hdhive.visible" class="resource-diagnostics">
                  <span class="diag-title">诊断</span>
                  <span v-if="pan115Diagnostics.hdhive.attemptText" class="diag-meta">
                    {{ pan115Diagnostics.hdhive.attemptText }}
                  </span>
                  <span v-if="pan115Diagnostics.hdhive.error" class="diag-error">
                    {{ pan115Diagnostics.hdhive.error }}
                  </span>
                </div>
                <el-table
                  v-if="hdhivePan115Resources.length > 0"
                  :data="pagedHdhivePan115Resources"
                  stripe
                  class="resource-table"
                >
                  <el-table-column label="资源名称" min-width="300" show-overflow-tooltip>
                    <template #default="{ row }">
                      <div class="resource-name-row">
                        <div class="resource-name">{{ row.resource_name || row.title || row.name || '未命名资源' }}</div>
                        <el-tag
                          v-if="isHdhiveResourceSuspectedInvalid(row)"
                          size="small"
                          type="danger"
                          effect="plain"
                        >
                          疑似失效
                        </el-tag>
                      </div>
                      <div
                        v-if="row.resource_name && row.title && row.resource_name !== row.title"
                        class="text-muted"
                      >
                        {{ row.title }}
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="画质" width="160" align="center">
                    <template #default="{ row }">
                      <template v-if="row.quality && (Array.isArray(row.quality) ? row.quality.length : row.quality)">
                        <el-tag size="small">{{ Array.isArray(row.quality) ? row.quality.join(', ') : row.quality }}</el-tag>
                      </template>
                      <template v-else-if="getRowTags(row).formats.length">
                        <el-tag size="small" v-for="f in getRowTags(row).formats.slice(0, 3)" :key="f">{{ f }}</el-tag>
                      </template>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="分辨率" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info" v-if="row.resolution">{{ Array.isArray(row.resolution) ? row.resolution.join(', ') : row.resolution }}</el-tag>
                      <el-tag size="small" type="info" v-else-if="getRowTags(row).resolution">{{ getRowTags(row).resolution }}</el-tag>
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
                  <el-table-column label="操作" width="100" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        type="primary"
                        size="small"
                        :loading="Boolean(row?.saving) || isHdhiveUnlocking(row)"
                        :disabled="isPan115ActionDisabled(row)"
                        @click="handleSaveToPan115(row)"
                      >
                        转存
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <div v-if="hdhivePan115Resources.length > pan115PageSize" class="table-pagination">
                  <el-pagination
                    background
                    layout="prev, pager, next"
                    :total="hdhivePan115Resources.length"
                    :page-size="pan115PageSize"
                    :current-page="pan115Pager.hdhive"
                    @current-change="(page) => (pan115Pager.hdhive = page)"
                  />
                </div>
                <el-empty
                  v-else
                  :description="hdhiveTried ? 'HDHive 暂无可用115网盘资源' : '尚未获取 HDHive 资源'"
                />
              </div>
            </el-tab-pane>

            <el-tab-pane v-if="tabVisible('pan115_tg')" label="Telegram" name="tg">
              <div class="resource-tools">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="tgLoading"
                  @click="handleFetchTgPan115(true)"
                >
                  {{ tgTried ? '刷新 Telegram' : '用 Telegram 获取资源' }}
                </el-button>
              </div>
              <div v-loading="pan115Loading || tgLoading">
                <div v-if="pan115Diagnostics.tg.visible" class="resource-diagnostics">
                  <span class="diag-title">诊断</span>
                  <span v-if="pan115Diagnostics.tg.keyword" class="diag-meta">
                    命中关键词: {{ pan115Diagnostics.tg.keyword }}
                  </span>
                  <span v-if="pan115Diagnostics.tg.attemptText" class="diag-meta">
                    {{ pan115Diagnostics.tg.attemptText }}
                  </span>
                  <span v-if="pan115Diagnostics.tg.error" class="diag-error">
                    {{ pan115Diagnostics.tg.error }}
                  </span>
                </div>
                <el-table 
                  v-if="tgPan115Resources.length > 0"
                  :data="pagedTgPan115Resources"
                  stripe
                  class="resource-table"
                >
                  <el-table-column label="资源名称" min-width="300" show-overflow-tooltip>
                    <template #default="{ row }">
                      <div class="resource-name">{{ row.resource_name || row.title || row.name || '未命名资源' }}</div>
                    </template>
                  </el-table-column>
                  <el-table-column label="频道" width="150" align="center" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span>{{ row.tg_channel || '-' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="画质" width="160" align="center">
                    <template #default="{ row }">
                      <template v-if="getRowTags(row).formats.length">
                        <el-tag size="small" v-for="f in getRowTags(row).formats.slice(0, 3)" :key="f">{{ f }}</el-tag>
                      </template>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="分辨率" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info" v-if="getRowTags(row).resolution">{{ getRowTags(row).resolution }}</el-tag>
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
                      <el-button
                        type="primary"
                        size="small"
                        :loading="Boolean(row?.saving) || isHdhiveUnlocking(row)"
                        :disabled="isPan115ActionDisabled(row)"
                        @click="handleSaveToPan115(row)"
                      >
                        转存
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <div v-if="tgPan115Resources.length > pan115PageSize" class="table-pagination">
                  <el-pagination
                    background
                    layout="prev, pager, next"
                    :total="tgPan115Resources.length"
                    :page-size="pan115PageSize"
                    :current-page="pan115Pager.tg"
                    @current-change="(page) => (pan115Pager.tg = page)"
                  />
                </div>
                <el-empty
                  v-else
                  :description="tgTried ? 'Telegram 暂无可用115网盘资源' : '尚未获取 Telegram 资源'"
                />
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane v-if="tabVisible('magnet')" label="磁力链接" name="magnet">
          <el-tabs v-model="magnetSourceTab" class="source-tabs">
            <el-tab-pane v-if="tabVisible('magnet_seedhub')" label="SeedHub" name="seedhub">
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
                  :data="pagedSeedhubMagnetResources"
                  stripe
                  class="resource-table"
                >
                  <el-table-column label="资源名称" min-width="400" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span class="resource-name">{{ row.name }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="画质" width="160" align="center">
                    <template #default="{ row }">
                      <template v-if="getRowTags(row).formats.length">
                        <el-tag size="small" v-for="f in getRowTags(row).formats.slice(0, 3)" :key="f">{{ f }}</el-tag>
                      </template>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="分辨率" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info" v-if="getRowTags(row).resolution">{{ getRowTags(row).resolution }}</el-tag>
                      <span v-else class="text-muted">-</span>
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
                <div v-if="seedhubMagnetResources.length > pan115PageSize" class="table-pagination">
                  <el-pagination
                    background
                    layout="prev, pager, next"
                    :total="seedhubMagnetResources.length"
                    :page-size="pan115PageSize"
                    :current-page="magnetPager.seedhub"
                    @current-change="(page) => (magnetPager.seedhub = page)"
                  />
                </div>
                <el-empty
                  v-else
                  :description="seedhubMagnetTried ? 'SeedHub 暂无磁力资源' : '尚未获取 SeedHub 资源'"
                />
              </div>
            </el-tab-pane>

            <el-tab-pane v-if="tabVisible('magnet_butailing')" label="不太灵" name="butailing">
              <div class="resource-tools">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="butailingMagnetLoading"
                  @click="handleFetchButailingMagnet"
                >
                  {{ butailingMagnetTried ? '刷新不太灵' : '用不太灵获取磁链' }}
                </el-button>
              </div>
              <div v-loading="butailingMagnetLoading">
                <el-table
                  v-if="butailingMagnetResources.length > 0"
                  :data="pagedButailingMagnetResources"
                  stripe
                  class="resource-table"
                >
                  <el-table-column label="资源名称" min-width="400" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span class="resource-name">{{ row.name }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="画质" width="160" align="center">
                    <template #default="{ row }">
                      <template v-if="row.quality">
                        <el-tag size="small">{{ row.quality }}</el-tag>
                      </template>
                      <template v-else-if="getRowTags(row).formats.length">
                        <el-tag size="small" v-for="f in getRowTags(row).formats.slice(0, 3)" :key="f">{{ f }}</el-tag>
                      </template>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="分辨率" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info" v-if="getRowTags(row).resolution">{{ getRowTags(row).resolution }}</el-tag>
                      <span v-else class="text-muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="大小" width="120" align="center">
                    <template #default="{ row }">
                      <span class="resource-size">{{ row.size || '-' }}</span>
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
                <div v-if="butailingMagnetResources.length > pan115PageSize" class="table-pagination">
                  <el-pagination
                    background
                    layout="prev, pager, next"
                    :total="butailingMagnetResources.length"
                    :page-size="pan115PageSize"
                    :current-page="magnetPager.butailing"
                    @current-change="(page) => (magnetPager.butailing = page)"
                  />
                </div>
                <el-empty
                  v-else
                  :description="butailingMagnetTried ? '不太灵暂无磁力资源' : '尚未获取不太灵资源'"
                />
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

      </el-tabs>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { searchApi, subscriptionApi, pan115Api } from '@/api'
import { Star, Plus } from '@element-plus/icons-vue'
import LibraryBadge from '@/components/media/LibraryBadge.vue'
import { getVisibleTabs, loadVisibleTabs, isTabVisible } from '@/utils/detailTabs'
import { extractTags } from '@/utils/resourceTags'

const _visibleTabs = getVisibleTabs()
const tabVisible = (key) => isTabVisible(_visibleTabs.value, key)

const _tagCache = new WeakMap()
const getRowTags = (row) => {
  if (_tagCache.has(row)) return _tagCache.get(row)
  const tags = extractTags(row)
  _tagCache.set(row, tags)
  return tags
}

const route = useRoute()

const movie = ref(null)
const loading = ref(true)
const activeTab = ref('pan115')

const pan115Resources = ref([])
const pan115SourceTab = ref('pansou')
const magnetSourceTab = ref('seedhub')
const magnetResources = ref([])

const pan115Loading = ref(false)
const pansouLoading = ref(false)
const pansouTried = ref(false)
const hdhiveLoading = ref(false)
const hdhiveTried = ref(false)
const tgLoading = ref(false)
const tgTried = ref(false)
const magnetLoading = ref(false)
const seedhubMagnetLoading = ref(false)
const seedhubMagnetTried = ref(false)
const butailingMagnetLoading = ref(false)
const butailingMagnetTried = ref(false)
const isSubscribed = ref(false)
const isInEmby = ref(false)
const isInFeiniu = ref(false)
const isInMediaLibrary = computed(() => isInEmby.value || isInFeiniu.value)
const subscriptionId = ref(null)
const subscribing = ref(false)
const doubanLink = ref(null)

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w500'
const PAN115_CACHE_TTL_MS = 30 * 60 * 1000
const PAN115_CACHE_VERSION = 2

// 转存相关
const saving = ref(false)
const hdhiveUnlockingSlugs = ref(new Set())
const pan115Diagnostics = ref({
  pansou: { visible: false, keyword: '', attemptText: '', error: '' },
  hdhive: { visible: false, keyword: '', attemptText: '', error: '' },
  tg: { visible: false, keyword: '', attemptText: '', error: '' }
})

const getPosterUrl = (path) => {
  if (!path) return new URL('/no-poster.png', import.meta.url).href
  return TMDB_IMAGE_BASE + path
}

const getPan115CacheKey = () => `movie_pan115_${route.params.id}`

const resetPan115Diagnostics = () => {
  pan115Diagnostics.value = {
    pansou: { visible: false, keyword: '', attemptText: '', error: '' },
    hdhive: { visible: false, keyword: '', attemptText: '', error: '' },
    tg: { visible: false, keyword: '', attemptText: '', error: '' }
  }
}

const buildAttemptText = (attempts) => {
  if (!Array.isArray(attempts) || attempts.length === 0) return ''
  const pieces = attempts.slice(0, 8).map((item) => {
    const service = String(item?.service || '').trim() || 'unknown'
    const status = String(item?.status || '').trim() || 'unknown'
    const keyword = String(item?.keyword || '').trim()
    const count = Number(item?.count || 0)
    if (status === 'ok') {
      return keyword ? `${service}(${keyword})=${count}` : `${service}=${count}`
    }
    const error = String(item?.error || '').trim()
    if (keyword) return `${service}(${keyword})失败${error ? `:${error}` : ''}`
    return `${service}失败${error ? `:${error}` : ''}`
  })
  return pieces.join(' | ')
}

const updatePan115Diagnostics = (source, payload = {}) => {
  const normalizedSource = String(source || '').trim()
  if (!pan115Diagnostics.value[normalizedSource]) return
  const keyword = String(payload?.keyword || '').trim()
  const attempts = Array.isArray(payload?.attempts) ? payload.attempts : []
  const attemptText = buildAttemptText(attempts)
  const error = String(payload?.error || '').trim()
  pan115Diagnostics.value[normalizedSource] = {
    visible: true,
    keyword,
    attemptText,
    error
  }
}

const readPan115Cache = () => {
  try {
    const raw = sessionStorage.getItem(getPan115CacheKey())
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || !Array.isArray(parsed.list) || !parsed.ts) return null
    if (Number(parsed.version || 0) !== PAN115_CACHE_VERSION) return null
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
        version: PAN115_CACHE_VERSION,
        ts: Date.now(),
        list: Array.isArray(list) ? list : []
      })
    )
  } catch {
    // ignore cache write errors
  }
}

const pansouPan115Resources = computed(() =>
  pan115Resources.value.filter((item) => item?.source_service === 'pansou')
)

const hdhivePan115Resources = computed(() =>
  pan115Resources.value.filter((item) => item?.source_service === 'hdhive')
)

const tgPan115Resources = computed(() =>
  pan115Resources.value.filter((item) => item?.source_service === 'tg')
)
const pan115PageSize = 10
const seedhubFetchLimit = 80
const pan115Pager = ref({
  pansou: 1,
  hdhive: 1,
  tg: 1
})
const magnetPager = ref({
  seedhub: 1,
  butailing: 1
})
const slicePan115Page = (list, page) => {
  const currentPage = Math.max(1, Number(page || 1))
  const start = (currentPage - 1) * pan115PageSize
  return list.slice(start, start + pan115PageSize)
}
const pagedPansouPan115Resources = computed(() => slicePan115Page(pansouPan115Resources.value, pan115Pager.value.pansou))
const pagedHdhivePan115Resources = computed(() => slicePan115Page(hdhivePan115Resources.value, pan115Pager.value.hdhive))
const pagedTgPan115Resources = computed(() => slicePan115Page(tgPan115Resources.value, pan115Pager.value.tg))

const seedhubMagnetResources = computed(() =>
  magnetResources.value.filter((item) => item?.source_service === 'seedhub')
)
const butailingMagnetResources = computed(() =>
  magnetResources.value.filter((item) => item?.source_service === 'butailing')
)
const pagedSeedhubMagnetResources = computed(() => slicePan115Page(seedhubMagnetResources.value, magnetPager.value.seedhub))
const pagedButailingMagnetResources = computed(() => slicePan115Page(butailingMagnetResources.value, magnetPager.value.butailing))

const buildPan115MergeKey = (item = {}) => {
  const sourceService = String(item?.source_service || 'pansou').trim() || 'pansou'
  const slug = String(item?.slug || '').trim()
  if (slug) return `${sourceService}|slug:${slug}`
  const shareLink = String(item?.share_link || '').trim()
  const title = String(item?.title || '').trim()
  return `${sourceService}|${shareLink}|${title}`
}

const mergePan115Resources = (primaryList = [], secondaryList = []) => {
  const merged = []
  const indexMap = new Map()
  for (const item of primaryList) {
    if (!item || typeof item !== 'object') continue
    const key = buildPan115MergeKey(item)
    if (indexMap.has(key)) continue
    indexMap.set(key, merged.length)
    merged.push({ ...item })
  }
  for (const item of secondaryList) {
    if (!item || typeof item !== 'object') continue
    const key = buildPan115MergeKey(item)
    if (indexMap.has(key)) {
      const index = indexMap.get(key)
      merged[index] = { ...merged[index], ...item }
      continue
    }
    indexMap.set(key, merged.length)
    merged.push({ ...item })
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
  if (service === 'tg') return 'Telegram'
  return service || '未知'
}

const resolvePanShareLink = (row) => String(row?.share_link || row?.share_url || row?.pan115_share_link || '').trim()

const parseReceiveCodeFromShareLink = (shareLink) => {
  const rawLink = String(shareLink || '').trim()
  if (!rawLink) return ''

  const shortMatch = rawLink.match(/^[A-Za-z0-9]+-([A-Za-z0-9]{4})$/)
  if (shortMatch) return shortMatch[1]

  const passwordMatch = rawLink.match(/[?&](?:password|pwd|receive_code|pickcode|code)=([^&#]+)/i)
  if (passwordMatch) {
    try {
      return decodeURIComponent(passwordMatch[1])
    } catch {
      return passwordMatch[1]
    }
  }

  return ''
}

const resolvePanReceiveCode = (row, shareLink = '') => {
  const resolvedLink = String(shareLink || resolvePanShareLink(row)).trim()
  const linkCode = parseReceiveCodeFromShareLink(resolvedLink)
  if (linkCode) return linkCode
  return String(row?.access_code || row?.hdhive_access_code || '').trim()
}

const isHdhiveResourceLocked = (row) => {
  if (!row || row.source_service !== 'hdhive') return false
  if (row.hdhive_locked === true) return true
  const shareLink = resolvePanShareLink(row)
  return !shareLink && Number(row.unlock_points || 0) > 0
}

const isHdhiveResourceSuspectedInvalid = (row) => {
  if (!row) return false
  if (row.hdhive_suspected_invalid === true) return true
  const validateStatus = String(row.hdhive_validate_status || '').trim().toLowerCase()
  return ['invalid', 'suspected_invalid', 'suspect_invalid'].includes(validateStatus)
}

const isPan115ActionDisabled = (row) => {
  if (Boolean(row?.saving) || isHdhiveUnlocking(row)) return true
  if (isHdhiveResourceLocked(row)) return false
  return row?.pan115_savable === false
}

const isHdhiveUnlocking = (row) => {
  const slug = String(row?.slug || '').trim()
  if (!slug) return false
  return hdhiveUnlockingSlugs.value.has(slug)
}

const showHdhiveNeedPointsNotice = async (row, reason = '') => {
  const points = Number(row?.unlock_points || 0)
  const lockMessage = String(row?.hdhive_lock_message || reason || '').trim()
  const lines = [
    points > 0 ? `该资源需要支付 ${points} 积分解锁提取码。` : '该资源需要先在 HDHive 解锁提取码。',
    lockMessage || '解锁后会继续当前操作。'
  ]
  try {
    await ElMessageBox.confirm(
      lines.join('\n'),
      'HDHive 积分解锁提示',
      {
        confirmButtonText: '确认解锁',
        cancelButtonText: '取消',
        type: 'warning',
        distinguishCancelAndClose: true
      }
    )
    return true
  } catch {
    return false
  }
}

const ensureHdhiveShareLink = async (row, actionLabel = '转存', options = {}) => {
  const forceUnlock = options?.forceUnlock === true
  const reason = String(options?.reason || '').trim()
  const currentLink = resolvePanShareLink(row)
  const locked = isHdhiveResourceLocked(row)
  if (!forceUnlock && currentLink && !locked) return currentLink
  if (!forceUnlock && !locked) return currentLink

  const confirmed = await showHdhiveNeedPointsNotice(row, reason)
  if (!confirmed) return ''

  const slug = String(row?.slug || '').trim()
  if (!slug) {
    ElMessage.error('缺少 HDHive 资源标识，无法自动解锁')
    return ''
  }
  if (hdhiveUnlockingSlugs.value.has(slug)) {
    ElMessage.info('正在解锁该资源，请稍候')
    return ''
  }

  hdhiveUnlockingSlugs.value.add(slug)
  try {
    const { data } = await searchApi.unlockHdhiveResource(slug)
    const shareLink = String(data?.share_link || '').trim()
    if (!shareLink) {
      throw new Error(data?.message || '未获取到分享链接')
    }
    row.share_link = shareLink
    row.access_code = String(data?.access_code || row?.access_code || '').trim()
    row.pan115_savable = true
    row.hdhive_locked = false
    row.hdhive_lock_code = ''
    row.hdhive_lock_message = ''
    ElMessage.success(data?.message || `HDHive 解锁成功，开始${actionLabel}`)
    return shareLink
  } catch (error) {
    const detail = String(error.response?.data?.detail || error.message || '').trim()
    ElMessage.error(detail || 'HDHive 自动解锁失败')
    return ''
  } finally {
    hdhiveUnlockingSlugs.value.delete(slug)
  }
}

const normalizeKeywordFingerprint = (value) => {
  const text = String(value || '').trim()
  if (!text) return ''
  return text
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[\s\-_·:：,.，。!！?？/\\'"`()\[\]]+/g, '')
    .toLowerCase()
}

const buildHdhiveKeywords = () => {
  const title = String(movie.value?.title || '').trim()
  const originalTitle = String(movie.value?.original_title || '').trim()
  const year = String(movie.value?.release_date || '').split('-')[0]
  const candidates = []
  const seen = new Set()
  const add = (keyword) => {
    const raw = String(keyword || '').trim()
    if (!raw) return
    const key = normalizeKeywordFingerprint(raw)
    if (!key || seen.has(key)) return
    seen.add(key)
    candidates.push(raw)
  }

  add(title)
  if (title && year) add(`${title} ${year}`)
  add(originalTitle)
  if (originalTitle && year) add(`${originalTitle} ${year}`)
  return candidates
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
    void hydrateMovieAuxiliaryData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '获取电影信息失败')
  } finally {
    loading.value = false
  }
}

const refreshEmbyStatus = async () => {
  const tmdbId = Number(route.params.id || 0)
  if (!Number.isFinite(tmdbId) || tmdbId <= 0) {
    isInEmby.value = false
    return
  }
  try {
    const { data } = await searchApi.getEmbyStatusMap([{ media_type: 'movie', tmdb_id: tmdbId }])
    const payload = data?.items || {}
    isInEmby.value = Boolean(payload[`movie:${tmdbId}`]?.exists_in_emby)
  } catch {
    isInEmby.value = false
  }
}

const refreshFeiniuStatus = async () => {
  const tmdbId = Number(route.params.id || 0)
  if (!Number.isFinite(tmdbId) || tmdbId <= 0) {
    isInFeiniu.value = false
    return
  }
  try {
    const { data } = await searchApi.getFeiniuStatusMap([{ media_type: 'movie', tmdb_id: tmdbId }])
    const payload = data?.items || {}
    isInFeiniu.value = Boolean(payload[`movie:${tmdbId}`]?.exists_in_feiniu)
  } catch {
    isInFeiniu.value = false
  }
}

const hydrateMovieAuxiliaryData = async () => {
  await Promise.allSettled([
    fetchExternalIds(),
    refreshEmbyStatus(),
    refreshFeiniuStatus()
  ])
}

const fetchExternalIds = async () => {
  const imdbId = String(movie.value?.imdb_id || movie.value?.external_ids?.imdb_id || '').trim()
  if (!imdbId) {
    doubanLink.value = null
    return
  }
  try {
    const { data } = await searchApi.getBridgeByImdbId(imdbId, 'movie')
    if (data?.imdb_id) {
      doubanLink.value = {
        imdb_id: data.imdb_id,
        douban_id: data.douban?.douban_id || null
      }
    }
  } catch (error) {
    // 静默失败，不影响主流程
    console.log('获取外部链接失败:', error)
  }
}

const fetchPan115 = async (forceRefresh = false) => {
  const cachedList = readPan115Cache()
  if (!forceRefresh && cachedList && cachedList.length > 0) {
    pan115Resources.value = cachedList
    pansouTried.value = cachedList.some((item) => item?.source_service === 'pansou')
    hdhiveTried.value = cachedList.some((item) => item?.source_service === 'hdhive')
    tgTried.value = cachedList.some((item) => item?.source_service === 'tg')
    pan115Loading.value = false
  }
  pansouTried.value = false
  hdhiveTried.value = false
  tgTried.value = false
  pan115Loading.value = true

  try {
    const { data } = await searchApi.getMoviePan115(route.params.id, 1, forceRefresh)
    const pansouList = Array.isArray(data.list) ? data.list : []
    updatePan115Diagnostics('pansou', data)
    const cachedPansouList = pan115Resources.value.filter((item) => item?.source_service === 'pansou')
    const cachedHdhiveList = pan115Resources.value.filter((item) => item?.source_service === 'hdhive')
    const cachedTgList = pan115Resources.value.filter((item) => item?.source_service === 'tg')
    const mergedList = mergePan115Resources(
      mergePan115Resources(mergePan115Resources(pansouList, cachedPansouList), cachedHdhiveList),
      cachedTgList
    )
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

const handleFetchPansouPan115 = async (forceRefresh = false) => {
  if (pansouLoading.value) return
  pansouLoading.value = true
  pansouTried.value = true
  try {
    const { data } = await searchApi.getMoviePan115Pansou(route.params.id, 1, forceRefresh)
    updatePan115Diagnostics('pansou', data)
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

const handleFetchHdhivePan115 = async (forceRefresh = false) => {
  if (hdhiveLoading.value) return
  hdhiveLoading.value = true
  hdhiveTried.value = true
  try {
    const { data } = await searchApi.getMoviePan115Hdhive(route.params.id, 1, forceRefresh)
    updatePan115Diagnostics('hdhive', data)
    let hdhiveList = Array.isArray(data.list) ? data.list : []
    hdhiveList = hdhiveList.map((item) => ({ ...item, source_service: item?.source_service || 'hdhive' }))

    if (hdhiveList.length === 0) {
      const keywordCandidates = buildHdhiveKeywords()
      const dedup = new Map()
      for (const keyword of keywordCandidates) {
        const { data: keywordData } = await searchApi.getHdhivePan115ByKeyword(keyword, 'movie')
        const rows = Array.isArray(keywordData?.list) ? keywordData.list : []
        for (const row of rows) {
          const normalizedRow = { ...row, source_service: row?.source_service || 'hdhive' }
          const key = `${String(normalizedRow?.slug || '')}|${String(normalizedRow?.share_link || normalizedRow?.resource_name || normalizedRow?.title || '')}`.toLowerCase()
          if (!dedup.has(key)) {
            dedup.set(key, normalizedRow)
          }
        }
        if (dedup.size >= 30) break
      }
      hdhiveList = Array.from(dedup.values()).slice(0, 30)
    }

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

const handleFetchTgPan115 = async (forceRefresh = false) => {
  if (tgLoading.value) return
  tgLoading.value = true
  tgTried.value = true
  try {
    const { data } = await searchApi.getMoviePan115Tg(route.params.id, 1, forceRefresh)
    updatePan115Diagnostics('tg', data)
    const tgList = Array.isArray(data.list) ? data.list : []
    const mergedList = mergePan115Resources(pan115Resources.value, tgList)
    pan115Resources.value = mergedList
    writePan115Cache(mergedList)
    if (tgList.length === 0) {
      ElMessage.info('Telegram 暂未找到可用资源')
    }
  } catch (error) {
    console.error('Failed to fetch tg pan115:', error)
  } finally {
    tgLoading.value = false
  }
}

const fetchMagnet = async () => {
  magnetLoading.value = true
  magnetPager.value.seedhub = 1
  try {
    const { data } = await searchApi.getMovieMagnet(route.params.id)
    const seedhubList = Array.isArray(data.list) ? data.list : []
    const markedSeedhubList = seedhubList.map((item) => ({ ...item, source_service: item?.source_service || 'seedhub' }))
    magnetResources.value = mergeMagnetResources(markedSeedhubList, magnetResources.value)
    if (data?.error) {
      ElMessage.warning(`磁力资源暂不可用：${data.error}`)
    }
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
  magnetPager.value.seedhub = 1

  try {
    const { data } = await searchApi.getMovieMagnetSeedhub(route.params.id, seedhubFetchLimit)
    const seedhubList = Array.isArray(data?.list) ? data.list : []
    const markedSeedhubList = seedhubList.map((item) => ({ ...item, source_service: item?.source_service || 'seedhub' }))
    magnetResources.value = mergeMagnetResources(magnetResources.value, markedSeedhubList)
    if (markedSeedhubList.length === 0) {
      ElMessage.info('SeedHub 暂未找到可用磁链')
    }
  } catch (error) {
    console.error('Failed to fetch seedhub magnet:', error)
    ElMessage.error(error.response?.data?.detail || error.message || 'SeedHub 磁链获取失败')
  } finally {
    seedhubMagnetLoading.value = false
  }
}

const handleFetchButailingMagnet = async () => {
  if (butailingMagnetLoading.value) return
  butailingMagnetLoading.value = true
  butailingMagnetTried.value = true
  magnetPager.value.butailing = 1

  try {
    const { data } = await searchApi.getMovieMagnetButailing(route.params.id)
    const btlList = Array.isArray(data?.list) ? data.list : []
    const markedBtlList = btlList.map((item) => ({ ...item, source_service: item?.source_service || 'butailing' }))
    magnetResources.value = mergeMagnetResources(magnetResources.value, markedBtlList)
    if (markedBtlList.length === 0) {
      ElMessage.info('不太灵暂未找到可用磁链')
    }
  } catch (error) {
    console.error('Failed to fetch butailing magnet:', error)
    ElMessage.error(error.response?.data?.detail || error.message || '不太灵磁链获取失败')
  } finally {
    butailingMagnetLoading.value = false
  }
}

const handleSubscribe = async () => {
  if (subscribing.value) return
  subscribing.value = true
  const previousSubscribed = Boolean(isSubscribed.value)
  const previousSubscriptionId = subscriptionId.value
  try {
    if (isSubscribed.value) {
      if (!subscriptionId.value) {
        await checkSubscribed()
      }
      if (!subscriptionId.value) {
        ElMessage.warning('未找到订阅记录，请刷新后重试')
        return
      }
      const targetId = subscriptionId.value
      isSubscribed.value = false
      subscriptionId.value = null
      await subscriptionApi.delete(targetId)
      ElMessage.success('已取消订阅')
      return
    }

    isSubscribed.value = true
    const { data } = await subscriptionApi.create({
      tmdb_id: movie.value.id,
      title: movie.value.title,
      media_type: 'movie',
      poster_path: movie.value.poster_path,
      overview: movie.value.overview,
      year: movie.value.release_date?.split('-')[0],
      rating: movie.value.vote_average
    })
    subscriptionId.value = Number(data?.id || 0) || null
    ElMessage.success('订阅成功')
  } catch (error) {
    if (error.response?.status === 400) {
      isSubscribed.value = true
      checkSubscribed()
      ElMessage.info('该影视已在订阅列表中')
      return
    }
    isSubscribed.value = previousSubscribed
    subscriptionId.value = previousSubscriptionId
    ElMessage.error(error.response?.data?.detail || error.message || '订阅操作失败')
  } finally {
    subscribing.value = false
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
    const { data } = await subscriptionApi.listForStatus({ media_type: 'movie' })
    // 处理新的返回格式：{ items: [], douban_id_map: {}, imdb_id_map: {} }
    const items = Array.isArray(data) ? data : (data?.items || [])
    const matched = items.find((sub) => Number(sub.tmdb_id) === tmdbId) || null
    isSubscribed.value = Boolean(matched)
    subscriptionId.value = Number(matched?.id || 0) || null
  } catch {
    isSubscribed.value = false
    subscriptionId.value = null
  }
}

const handleSaveToPan115 = async (item) => {
  if (item?.saving || isHdhiveUnlocking(item)) return
  item.saving = true
  try {
    let shareLink = resolvePanShareLink(item)
    if (item?.source_service === 'hdhive') {
      shareLink = await ensureHdhiveShareLink(item, '转存')
    }
    if (!shareLink) {
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

    const receiveCode = resolvePanReceiveCode(item, shareLink)
    // 由后端统一解析分享链接并执行转存
    const { data } = await pan115Api.saveShareToFolder(
      shareLink,
      movie.value.title + ' (' + movie.value.release_date?.split('-')[0] + ')',
      defaultFolderId,
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
    const detail = String(error.response?.data?.detail || '').trim()
    if (detail.includes('离线任务列表请求过于频繁')) {
      ElMessage.error('115接口触发风控，请稍后重试')
      return
    }
    if (item?.source_service === 'hdhive' && (detail.includes('4100012') || detail.includes('请输入访问码'))) {
      const unlockedLink = await ensureHdhiveShareLink(item, '转存', {
        forceUnlock: true,
        reason: '115 返回“请输入访问码”，需要先进行 HDHive 积分解锁。'
      })
      if (unlockedLink) {
        try {
          const unlockedReceiveCode = resolvePanReceiveCode(item, unlockedLink)
          const { data } = await pan115Api.saveShareToFolder(
            unlockedLink,
            movie.value.title + ' (' + movie.value.release_date?.split('-')[0] + ')',
            defaultFolderId,
            unlockedReceiveCode
          )
          const retrySuccess = data?.success === true
            || data?.state === true
            || data?.result?.success === true
            || data?.result?.state === true
          if (!retrySuccess) throw new Error(data?.message || data?.error || data?.result?.error || '转存失败')
          ElMessage.success(data?.message || '转存成功')
          return
        } catch (retryError) {
          const retryDetail = String(retryError.response?.data?.detail || retryError.message || '').trim()
          ElMessage.error(retryDetail || '转存失败')
          return
        }
      }
      return
    }
    ElMessage.error(detail || error.message || '转存失败')
  } finally {
    item.saving = false
  }
}

const handleCopyMagnet = (magnet) => {
  navigator.clipboard.writeText(magnet)
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

watch(magnetSourceTab, (tab) => {
  if (tab === 'seedhub') magnetPager.value.seedhub = 1
  if (tab === 'butailing') magnetPager.value.butailing = 1
})

watch(pan115SourceTab, (tab) => {
  if (tab === 'pansou') pan115Pager.value.pansou = 1
  if (tab === 'hdhive') pan115Pager.value.hdhive = 1
  if (tab === 'tg') pan115Pager.value.tg = 1
})

watch(() => route.params.id, () => {
  resetPan115Diagnostics()
  isInEmby.value = false
  isInFeiniu.value = false
  pan115SourceTab.value = 'pansou'
  magnetSourceTab.value = 'seedhub'
  pan115Resources.value = []
  pan115Pager.value = { pansou: 1, hdhive: 1, tg: 1 }
  magnetPager.value = { seedhub: 1, butailing: 1 }
  pansouTried.value = false
  pansouLoading.value = false
  hdhiveTried.value = false
  hdhiveLoading.value = false
  tgTried.value = false
  tgLoading.value = false
  seedhubMagnetTried.value = false
  seedhubMagnetLoading.value = false
  butailingMagnetTried.value = false
  butailingMagnetLoading.value = false
  magnetResources.value = []
  fetchMovie()
  checkSubscribed()
})

onMounted(() => {
  loadVisibleTabs()
  resetPan115Diagnostics()
  fetchMovie()
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

      .title-row {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
      }

      .emby-badge-inline {
        display: inline-flex;
        align-items: center;
      }

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

      .external-links {
        margin-top: 12px;
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 13px;
        color: var(--ms-text-muted);

        .link-label {
          color: var(--ms-text-secondary);
        }

        .external-link {
          text-decoration: none;
        }

        .imdb-tag {
          padding: 2px 6px;
          background: rgba(245, 166, 35, 0.15);
          border: 1px solid rgba(245, 166, 35, 0.3);
          border-radius: 4px;
          color: #f5a623;
          font-size: 12px;
          font-weight: 500;
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

  .resource-diagnostics {
    margin: 0 0 10px;
    font-size: 12px;
    line-height: 1.5;
    color: var(--ms-text-secondary);
    display: flex;
    flex-wrap: wrap;
    gap: 8px;

    .diag-title {
      font-weight: 600;
      color: var(--ms-text-primary);
    }

    .diag-meta {
      color: var(--ms-text-secondary);
    }

    .diag-error {
      color: var(--ms-danger, #e45656);
      word-break: break-word;
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

  .table-pagination {
    margin-top: 12px;
    display: flex;
    justify-content: flex-end;
  }

  .resource-name {
    color: var(--ms-text-primary);
    font-size: 14px;
    font-weight: 500;
  }

  .resource-name-row {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }

  .resource-size {
    color: var(--ms-text-secondary);
    font-size: 13px;
  }

  .text-muted {
    color: var(--ms-text-muted);
  }

}

@media (max-width: 1024px) {
  .movie-detail-page {
    .detail-header {
      gap: 24px;
      padding: 22px;

      .poster {
        width: 190px;
      }

      .info {
        .title {
          font-size: 28px;
        }

        .meta,
        .actions,
        .external-links {
          flex-wrap: wrap;
        }
      }
    }

    .resource-tabs {
      padding: 16px;
    }

    .table-pagination {
      justify-content: center;
    }
  }
}

@media (max-width: 768px) {
  .movie-detail-page {
    .detail-header {
      flex-direction: column;
      gap: 18px;
      margin-bottom: 20px;
      padding: 16px;

      .poster {
        width: min(220px, 62vw);
        margin: 0 auto;
      }

      .info {
        .title {
          font-size: 24px;
        }

        .meta {
          gap: 10px;
        }

        .overview {
          max-height: none;
          padding-right: 0;
        }

        .actions {
          width: 100%;

          .el-button {
            flex: 1 1 100%;
            margin-left: 0;
          }
        }

        .external-links {
          align-items: flex-start;
        }
      }
    }

    .resource-tabs {
      padding: 14px;
    }

    .resource-tools {
      flex-wrap: wrap;
    }

    .resource-table {
      display: block;
      overflow-x: auto;

      :deep(.el-table__inner-wrapper) {
        min-width: 680px;
      }
    }
  }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
