<template>
  <div class="tv-detail-page" v-loading="loading">
    <template v-if="tv">
      <div class="back-button-container">
        <el-button @click="handleBack" class="back-button" text>
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
      </div>
      <div class="detail-header">
        <div class="poster">
          <img :src="getPosterUrl(tv.poster_path)" :alt="tv.name" />
        </div>
        <div class="info">
          <div class="title-row">
            <h1 class="title">{{ tv.name }}</h1>
            <LibraryBadge
              v-if="isInMediaLibrary"
              class="emby-badge-inline"
              inline
              :in-emby="isInEmby"
              :in-feiniu="isInFeiniu"
            />
          </div>
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

      <el-tabs v-model="activeTab" class="resource-tabs" lazy>
        <template v-for="key in orderedMainTabs" :key="key">
          <el-tab-pane v-if="key === 'pan115'" label="115网盘" name="pan115">
          <el-tabs v-model="pan115SourceTab" class="source-tabs" lazy>
            <template v-for="key in orderedPan115SubTabs" :key="key">
              <el-tab-pane v-if="key === 'pan115_pansou'" label="Pansou" name="pansou">
              <div class="resource-tools resource-tools-split">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="pansouLoading"
                  @click="handleFetchPansouPan115(true)"
                >
                  {{ pansouTried ? '重新尝试 Pansou' : '用 Pansou 获取资源' }}
                </el-button>
                <el-button size="small" @click="openManualPanDialog">导入 115 分享</el-button>
              </div>
              <div v-loading="pansouLoading">
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
                  <el-table-column label="操作" width="250" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        type="primary"
                        size="small"
                        :loading="Boolean(row?.saving) || checkHdhiveUnlocking(row)"
                        :disabled="checkPan115ActionDisabled(row)"
                        @click="handleSaveToPan115(row)"
                      >
                        一键转存
                      </el-button>
                      <el-button
                        size="small"
                        :disabled="!resolvePanShareLink(row)"
                        @click="handleCopyPanShareLink(row)"
                      >
                        复制链接
                      </el-button>
                      <el-button
                        size="small"
                        :loading="Boolean(row?.extracting)"
                        :disabled="checkPan115SelectSaveDisabled(row)"
                        @click="handleSelectSave(row)"
                      >
                        选集
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
                <div v-else class="resource-empty-state">
                  <el-empty :description="pansouTried ? '暂无可用115网盘资源' : '尚未获取 Pansou 资源'" />
                  <el-button size="small" @click="openManualPanDialog">导入 115 分享</el-button>
                </div>
              </div>
            </el-tab-pane>
              <el-tab-pane v-else-if="key === 'pan115_juying'" label="聚影" name="juying">
                <JuyingResourceTab
                  media-type="tv"
                  :tmdb-id="tvId"
                  resource-type="115"
                  :season="selectedSeason || null"
                  :title="tv?.name || ''"
                  :year="tv?.first_air_date?.split('-')[0] || ''"
                  @switch-resource-type="handleJuyingResourceTypeSwitch"
                />
              </el-tab-pane>
              <el-tab-pane v-else-if="key === 'pan115_hdhive'" label="HDHive" name="hdhive">
              <div class="resource-tools resource-tools-split">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="hdhiveLoading"
                  @click="handleFetchHdhivePan115(true)"
                >
                  {{ hdhiveTried ? '刷新 HDHive' : '用 HDHive 获取资源' }}
                </el-button>
                <el-button size="small" @click="openManualPanDialog">导入 115 分享</el-button>
              </div>
              <div v-loading="hdhiveLoading">
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
                          v-if="isHdhiveOfficialResource(row)"
                          size="small"
                          type="warning"
                          effect="plain"
                        >
                          官组
                        </el-tag>
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
                  <el-table-column label="操作" width="250" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        type="primary"
                        size="small"
                        :loading="Boolean(row?.saving) || checkHdhiveUnlocking(row)"
                        :disabled="checkPan115ActionDisabled(row)"
                        @click="handleSaveToPan115(row)"
                      >
                        一键转存
                      </el-button>
                      <el-button
                        size="small"
                        :disabled="!resolvePanShareLink(row)"
                        @click="handleCopyPanShareLink(row)"
                      >
                        复制链接
                      </el-button>
                      <el-button
                        size="small"
                        :loading="Boolean(row?.extracting)"
                        :disabled="checkPan115SelectSaveDisabled(row)"
                        @click="handleSelectSave(row)"
                      >
                        选集
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
                <div v-else class="resource-empty-state">
                  <el-empty :description="hdhiveTried ? 'HDHive 暂无可用115网盘资源' : '尚未获取 HDHive 资源'" />
                  <el-button size="small" @click="openManualPanDialog">导入 115 分享</el-button>
                </div>
              </div>
            </el-tab-pane>
              <el-tab-pane v-else-if="key === 'pan115_tg'" label="Telegram" name="tg">
              <div class="resource-tools resource-tools-split">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="tgLoading"
                  @click="handleFetchTgPan115(true)"
                >
                  {{ tgTried ? '刷新 Telegram' : '用 Telegram 获取资源' }}
                </el-button>
                <el-button size="small" @click="openManualPanDialog">导入 115 分享</el-button>
              </div>
              <div v-loading="tgLoading">
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
                  <el-table-column label="操作" width="250" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        type="primary"
                        size="small"
                        :loading="Boolean(row?.saving) || checkHdhiveUnlocking(row)"
                        :disabled="checkPan115ActionDisabled(row)"
                        @click="handleSaveToPan115(row)"
                      >
                        一键转存
                      </el-button>
                      <el-button
                        size="small"
                        :disabled="!resolvePanShareLink(row)"
                        @click="handleCopyPanShareLink(row)"
                      >
                        复制链接
                      </el-button>
                      <el-button
                        size="small"
                        :loading="Boolean(row?.extracting)"
                        :disabled="checkPan115SelectSaveDisabled(row)"
                        @click="handleSelectSave(row)"
                      >
                        选集
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
                <div v-else class="resource-empty-state">
                  <el-empty :description="tgTried ? 'Telegram 暂无可用115网盘资源' : '尚未获取 Telegram 资源'" />
                  <el-button size="small" @click="openManualPanDialog">导入 115 分享</el-button>
                </div>
              </div>
            </el-tab-pane>
            </template>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane v-else-if="key === 'quark'" name="quark">
          <template #label>
            <span>夸克网盘<el-tag v-if="!quarkConfigured" type="info" size="small" style="margin-left: 6px">未配置</el-tag></span>
          </template>
          <QuarkResourceTab
            :media-type="'tv'"
            :tmdb-id="tvId"
            :visible="activeTab === 'quark'"
            :skip-initial-auto-fetch="skipQuarkAutoFetch"
            :quark-configured="quarkConfigured"
            :season="quarkSeason"
            :title="tv?.name || tv?.title || ''"
          />
        </el-tab-pane>

        <el-tab-pane v-else-if="key === 'magnet'" label="磁力链接" name="magnet">
          <el-tabs v-model="magnetSourceTab" class="source-tabs" lazy>
            <template v-for="key in orderedMagnetSubTabs" :key="key">
              <el-tab-pane v-if="key === 'magnet_seedhub'" label="SeedHub" name="seedhub">
              <div class="resource-tools resource-tools-split">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="seedhubMagnetLoading"
                  @click="handleFetchSeedhubMagnet"
                >
                  {{ seedhubMagnetTried ? '重新尝试 SeedHub' : '用 SeedHub 获取磁链' }}
                </el-button>
                <el-button size="small" @click="openManualMagnetDialog">导入磁链</el-button>
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
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        type="primary"
                        size="small"
                        :loading="Boolean(row?.offlineSaving)"
                        @click="handleSaveMagnet(row)"
                      >
                        离线下载
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
                <div v-else class="resource-empty-state">
                  <el-empty :description="seedhubMagnetTried ? 'SeedHub 暂无磁力资源' : '尚未获取 SeedHub 资源'" />
                  <el-button size="small" @click="openManualMagnetDialog">导入磁链</el-button>
                </div>
              </div>
              </el-tab-pane>
              <el-tab-pane v-else-if="key === 'magnet_juying'" label="聚影" name="juying">
                <JuyingResourceTab
                  media-type="tv"
                  :tmdb-id="tvId"
                  resource-type="magnet"
                  :season="selectedSeason || null"
                  :title="tv?.name || ''"
                  :year="tv?.first_air_date?.split('-')[0] || ''"
                  @switch-resource-type="handleJuyingResourceTypeSwitch"
                />
              </el-tab-pane>
              <el-tab-pane v-else-if="key === 'magnet_butailing'" label="不太灵" name="butailing">
              <div class="resource-tools resource-tools-split">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="butailingMagnetLoading"
                  @click="handleFetchButailingMagnet"
                >
                  {{ butailingMagnetTried ? '刷新不太灵' : '用不太灵获取磁链' }}
                </el-button>
                <el-button size="small" @click="openManualMagnetDialog">导入磁链</el-button>
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
                      <el-button
                        type="primary"
                        size="small"
                        :loading="Boolean(row?.offlineSaving)"
                        @click="handleSaveMagnet(row)"
                      >
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
                <div v-else class="resource-empty-state">
                  <el-empty :description="butailingMagnetTried ? '不太灵暂无磁力资源' : '尚未获取不太灵资源'" />
                  <el-button size="small" @click="openManualMagnetDialog">导入磁链</el-button>
                </div>
              </div>
            </el-tab-pane>
            </template>
          </el-tabs>
        </el-tab-pane>
        </template>

      </el-tabs>
    </template>

    <!-- 选集转存对话框 -->
    <el-dialog
      v-model="selectSaveDialogVisible"
      title="选集转存"
      width="700px"
      append-to-body
      align-center
      :close-on-click-modal="!extractingFiles"
      :close-on-press-escape="!extractingFiles"
    >
      <el-form :model="selectSaveForm" label-width="100px" style="margin-bottom: 20px;">
        <el-form-item label="新建文件夹">
          <el-input v-model="selectSaveForm.newFolderName" placeholder="可选，输入名称自动创建" />
        </el-form-item>
      </el-form>
      <el-alert
        v-if="selectSaveError"
        :title="selectSaveError"
        type="error"
        :closable="false"
        show-icon
        style="margin-bottom: 12px;"
      />
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
          v-if="shareFilesList.length > 0"
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
        <el-empty
          v-else-if="!extractingFiles"
          description="未找到可选视频文件，请检查分享链接或提取码是否有效"
        />
        <div v-if="shareFilesList.length > 0" style="margin-top: 10px; color: var(--ms-text-muted); font-size: 13px;">
          已自动过滤非视频文件，共选中 {{ selectedFiles.length }} 个文件
        </div>
      </div>
      
      <template #footer>
        <el-button :disabled="saving" @click="selectSaveDialogVisible = false">取消</el-button>
        <el-button 
          type="primary" 
          @click="confirmSelectSave" 
          :loading="saving"
          :disabled="saving || selectedFiles.length === 0 || extractingFiles"
        >
          确认转存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="manualPanDialogVisible" title="导入 115 分享链接" width="520px">
      <el-form label-width="88px">
        <el-form-item label="分享链接">
          <el-input
            v-model="manualPanForm.shareLink"
            type="textarea"
            :rows="4"
            placeholder="粘贴 115 分享链接，支持带提取码文本"
          />
        </el-form-item>
        <el-form-item label="文件夹名称">
          <el-input v-model="manualPanForm.folderName" placeholder="默认按剧集标题生成" />
        </el-form-item>
        <el-form-item label="提取码">
          <el-input v-model="manualPanForm.receiveCode" placeholder="可留空，若链接里带提取码会自动解析" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualPanDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="manualPanSubmitting" @click="submitManualPanShare">
          开始转存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="manualMagnetDialogVisible" title="导入磁力链接" width="520px">
      <el-form label-width="88px">
        <el-form-item label="磁力链接">
          <el-input
            v-model="manualMagnetForm.magnet"
            type="textarea"
            :rows="4"
            placeholder="粘贴 magnet:?xt=urn:btih:..."
          />
        </el-form-item>
        <el-form-item label="任务名称">
          <el-input v-model="manualMagnetForm.title" placeholder="默认按剧集标题生成" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualMagnetDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="manualMagnetSubmitting" @click="submitManualMagnet">
          添加离线任务
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { searchApi, subscriptionApi, pan115Api, quarkApi } from '@/api'
import { Star, Plus, ArrowLeft } from '@element-plus/icons-vue'
import LibraryBadge from '@/components/media/LibraryBadge.vue'
import QuarkResourceTab from '@/components/detail/QuarkResourceTab.vue'
import JuyingResourceTab from '@/components/detail/JuyingResourceTab.vue'
import { getVisibleTabs, loadVisibleTabs, isTabVisible, getOrderedVisibleSubTabs, getFirstVisibleSubTabName, getOrderedVisibleMainTabs } from '@/utils/detailTabs'
import { useDetailResourceTabAutoFetch } from '@/utils/detailResourceTabAutoFetch'
import { extractTags } from '@/utils/resourceTags'
import { navigateBackFromDetail } from '@/utils/navigation'
import { copyText } from '@/utils/clipboard'
import { parseReceiveCodeFromShareLink, resolvePanShareLink } from '@/utils/panShare'
import { executePan115SaveToFolder } from '@/utils/pan115SaveFlow'
import {
  isHdhiveResourceLocked,
  isHdhiveResourceSuspectedInvalid,
  isHdhiveOfficialResource,
  isHdhiveUnlocking,
  isPan115HdhiveActionDisabled,
  isPan115SelectSaveDisabled,
  normalizePan115TransferError,
  runHdhivePan115SaveFlow,
} from '@/utils/hdhiveUnlock'
import {
  loadPan115SelectSaveFiles,
  SelectSaveAbortError,
} from '@/utils/pan115SelectSave'
import {
  notifyDetailOfflineInProgress,
  notifyDetailOfflineStarted,
  notifyDetailTransferInProgress,
  notifyDetailTransferStarted,
} from '@/utils/detailActionToast'

const _visibleTabs = getVisibleTabs()
const tabVisible = (key) => isTabVisible(_visibleTabs.value, key)

const orderedMainTabs = computed(() => getOrderedVisibleMainTabs(_visibleTabs.value))
const orderedPan115SubTabs = computed(() => getOrderedVisibleSubTabs(_visibleTabs.value, 'pan115'))
const orderedMagnetSubTabs = computed(() => getOrderedVisibleSubTabs(_visibleTabs.value, 'magnet'))

const _tagCache = new WeakMap()
const getRowTags = (row) => {
  if (_tagCache.has(row)) return _tagCache.get(row)
  const tags = extractTags(row)
  _tagCache.set(row, tags)
  return tags
}

const route = useRoute()
const router = useRouter()

const handleBack = () => {
  navigateBackFromDetail(router, route)
}

const tv = ref(null)
const loading = ref(true)
const activeTab = ref(getOrderedVisibleMainTabs(_visibleTabs.value)[0] || 'pan115')

const tvId = computed(() => route.params.id)
const quarkConfigured = ref(false)

const refreshQuarkConfigured = async () => {
  try {
    const { data } = await quarkApi.getCookieInfo()
    quarkConfigured.value = Boolean(data?.is_configured)
  } catch {
    quarkConfigured.value = false
  }
}
const pan115SourceTab = ref(getFirstVisibleSubTabName(_visibleTabs.value, 'pan115') || 'pansou')
const magnetSourceTab = ref(getFirstVisibleSubTabName(_visibleTabs.value, 'magnet') || 'seedhub')
const selectedSeason = ref(1)

const handleJuyingResourceTypeSwitch = (resourceType) => {
  if (resourceType === 'magnet') {
    activeTab.value = 'magnet'
    magnetSourceTab.value = 'juying'
    return
  }
  activeTab.value = 'pan115'
  pan115SourceTab.value = 'juying'
}
const quarkSeason = computed(() => Number(selectedSeason.value || 0) || null)

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

const pan115Diagnostics = ref({
  pansou: { visible: false, keyword: '', attemptText: '', error: '' },
  hdhive: { visible: false, keyword: '', attemptText: '', error: '' },
  tg: { visible: false, keyword: '', attemptText: '', error: '' }
})

const magnetLoading = ref(false)
const pansouLoading = ref(false)
const pansouTried = ref(false)
const hdhiveLoading = ref(false)
const hdhiveTried = ref(false)
const tgLoading = ref(false)
const tgTried = ref(false)
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

// 转存对话框相关
// 转存相关
const saving = ref(false)
const hdhiveUnlockingSlugs = ref(new Set())

const checkHdhiveUnlocking = (row) => isHdhiveUnlocking(hdhiveUnlockingSlugs.value, row)
const checkPan115ActionDisabled = (row) => isPan115HdhiveActionDisabled(row, hdhiveUnlockingSlugs.value, saving.value)
const checkPan115SelectSaveDisabled = (row) => isPan115SelectSaveDisabled(row, hdhiveUnlockingSlugs.value, saving.value)

// 选集转存相关
const selectSaveDialogVisible = ref(false)
const extractingFiles = ref(false)
const shareFilesList = ref([])
const selectedFiles = ref([])
const fileNameSortOrder = ref('asc')
const selectSaveForm = ref({
  shareLink: '',
  receiveCode: '',
  targetFolder: '0',
  newFolderName: ''
})
const selectSaveError = ref('')
const manualPanDialogVisible = ref(false)
const manualPanSubmitting = ref(false)
const manualPanForm = ref({
  shareLink: '',
  folderName: '',
  receiveCode: ''
})
const manualMagnetDialogVisible = ref(false)
const manualMagnetSubmitting = ref(false)
const manualMagnetForm = ref({
  magnet: '',
  title: ''
})

const getPosterUrl = (path) => {
  if (!path) return new URL('/no-poster.png', import.meta.url).href
  return TMDB_IMAGE_BASE + path
}

const getPan115CacheKey = (season = null) => `tv_pan115_${route.params.id}_s${season || 'all'}`

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

const readPan115Cache = (season = null) => {
  try {
    const raw = sessionStorage.getItem(getPan115CacheKey(season))
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

const writePan115Cache = (list, season = null) => {
  try {
    sessionStorage.setItem(
      getPan115CacheKey(season),
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

const resolvePanReceiveCode = (row, shareLink = '') => {
  const resolvedLink = String(shareLink || resolvePanShareLink(row)).trim()
  const linkCode = parseReceiveCodeFromShareLink(resolvedLink)
  if (linkCode) return linkCode
  return String(row?.access_code || row?.hdhive_access_code || '').trim()
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
  const title = String(tv.value?.name || tv.value?.title || '').trim()
  const originalTitle = String(tv.value?.original_name || tv.value?.original_title || '').trim()
  const year = String(tv.value?.first_air_date || '').split('-')[0]
  const season = Number(selectedSeason.value || 0)
  const seasonSuffix = season > 0 ? ` S${String(season).padStart(2, '0')}` : ''
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
  if (title && seasonSuffix) add(`${title}${seasonSuffix}`)
  if (title && year) add(`${title} ${year}`)
  if (title && year && seasonSuffix) add(`${title} ${year}${seasonSuffix}`)
  add(originalTitle)
  if (originalTitle && seasonSuffix) add(`${originalTitle}${seasonSuffix}`)
  if (originalTitle && year) add(`${originalTitle} ${year}`)
  return candidates
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
    void hydrateTvAuxiliaryData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '获取电视剧信息失败')
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
    const { data } = await searchApi.getEmbyStatusMap([{ media_type: 'tv', tmdb_id: tmdbId }])
    const payload = data?.items || {}
    isInEmby.value = Boolean(payload[`tv:${tmdbId}`]?.exists_in_emby)
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
    const { data } = await searchApi.getFeiniuStatusMap([{ media_type: 'tv', tmdb_id: tmdbId }])
    const payload = data?.items || {}
    isInFeiniu.value = Boolean(payload[`tv:${tmdbId}`]?.exists_in_feiniu)
  } catch {
    isInFeiniu.value = false
  }
}

const hydrateTvAuxiliaryData = async () => {
  await Promise.allSettled([
    fetchExternalIds(),
    refreshEmbyStatus(),
    refreshFeiniuStatus()
  ])
}

const fetchExternalIds = async () => {
  const imdbId = String(tv.value?.imdb_id || tv.value?.external_ids?.imdb_id || '').trim()
  if (!imdbId) {
    doubanLink.value = null
    return
  }
  try {
    const { data } = await searchApi.getBridgeByImdbId(imdbId, 'tv')
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

const handleFetchPansouPan115 = async (forceRefresh = false) => {
  if (pansouLoading.value) return
  const cacheKey = `s${selectedSeason.value}`
  pansouLoading.value = true
  pansouTried.value = true
  try {
    const { data } = await searchApi.getTvPan115Pansou(route.params.id, 1, forceRefresh, selectedSeason.value)
    updatePan115Diagnostics('pansou', data)
    const pansouList = Array.isArray(data.list) ? data.list : []
    const mergedList = mergePan115Resources(pan115Resources.value, pansouList)
    pan115Resources.value = mergedList
    writePan115Cache(mergedList, cacheKey)
    if (pansouList.length === 0) {
      ElMessage.info('Pansou 暂未找到可用资源')
    }
  } catch (error) {
    console.error('Failed to fetch pansou pan115:', error)
    ElMessage.error(error.response?.data?.detail || error.message || 'Pansou 资源获取失败')
  } finally {
    pansouLoading.value = false
  }
}

const handleFetchHdhivePan115 = async (forceRefresh = false) => {
  if (hdhiveLoading.value) return
  const cacheKey = `s${selectedSeason.value}`
  hdhiveLoading.value = true
  hdhiveTried.value = true
  try {
    const { data } = await searchApi.getTvPan115Hdhive(route.params.id, 1, forceRefresh, selectedSeason.value)
    updatePan115Diagnostics('hdhive', data)
    let hdhiveList = Array.isArray(data.list) ? data.list : []
    hdhiveList = hdhiveList.map((item) => ({ ...item, source_service: item?.source_service || 'hdhive' }))

    if (hdhiveList.length === 0) {
      const keywordCandidates = buildHdhiveKeywords()
      const results = await Promise.allSettled(
        keywordCandidates.map((kw) => searchApi.getHdhivePan115ByKeyword(kw, 'tv'))
      )
      const dedup = new Map()
      for (const r of results) {
        if (r.status !== 'fulfilled') continue
        const rows = Array.isArray(r.value?.data?.list) ? r.value.data.list : []
        for (const row of rows) {
          const normalizedRow = { ...row, source_service: row?.source_service || 'hdhive' }
          const key = `${String(normalizedRow?.slug || '')}|${String(normalizedRow?.share_link || normalizedRow?.resource_name || normalizedRow?.title || '')}`.toLowerCase()
          if (!dedup.has(key)) {
            dedup.set(key, normalizedRow)
          }
        }
      }
      hdhiveList = Array.from(dedup.values()).slice(0, 30)
    }

    const mergedList = mergePan115Resources(pan115Resources.value, hdhiveList)
    pan115Resources.value = mergedList
    writePan115Cache(mergedList, cacheKey)
    if (hdhiveList.length === 0) {
      ElMessage.info('HDHive 暂未找到可用资源')
    }
  } catch (error) {
    console.error('Failed to fetch hdhive pan115:', error)
    ElMessage.error(error.response?.data?.detail || error.message || 'HDHive 资源获取失败')
  } finally {
    hdhiveLoading.value = false
  }
}

const handleFetchTgPan115 = async (forceRefresh = false) => {
  if (tgLoading.value) return
  const cacheKey = `s${selectedSeason.value}`
  tgLoading.value = true
  tgTried.value = true
  try {
    const { data } = await searchApi.getTvPan115Tg(route.params.id, 1, forceRefresh, selectedSeason.value)
    updatePan115Diagnostics('tg', data)
    const tgList = Array.isArray(data.list) ? data.list : []
    const mergedList = mergePan115Resources(pan115Resources.value, tgList)
    pan115Resources.value = mergedList
    writePan115Cache(mergedList, cacheKey)
    if (tgList.length === 0) {
      ElMessage.info('Telegram 暂未找到可用资源')
    }
  } catch (error) {
    console.error('Failed to fetch tg pan115:', error)
    ElMessage.error(error.response?.data?.detail || error.message || 'Telegram 资源获取失败')
  } finally {
    tgLoading.value = false
  }
}

const fetchMagnet = async () => {
  magnetLoading.value = true
  magnetPager.value.seedhub = 1
  try {
    const { data } = await searchApi.getTvMagnet(route.params.id, selectedSeason.value)
    const seedhubList = Array.isArray(data.list) ? data.list : []
    const markedSeedhubList = seedhubList.map((item) => ({ ...item, source_service: item?.source_service || 'seedhub' }))
    magnetResources.value = mergeMagnetResources(markedSeedhubList, magnetResources.value)
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
    const { data } = await searchApi.getTvMagnetSeedhub(route.params.id, selectedSeason.value, seedhubFetchLimit)
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
    const { data } = await searchApi.getTvMagnetButailing(route.params.id, selectedSeason.value)
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

const autoFetchPan115SubTab = (tab) => {
  if (tab === 'pansou' && !pansouTried.value) {
    void handleFetchPansouPan115()
    return
  }
  if (tab === 'hdhive' && !hdhiveTried.value) {
    void handleFetchHdhivePan115()
    return
  }
  if (tab === 'tg' && !tgTried.value) {
    void handleFetchTgPan115()
  }
}

const autoFetchMagnetSubTab = (tab) => {
  if (tab === 'seedhub' && !seedhubMagnetTried.value) {
    void handleFetchSeedhubMagnet()
    return
  }
  if (tab === 'butailing' && !butailingMagnetTried.value) {
    void handleFetchButailingMagnet()
  }
}

const {
  captureInitialTabs,
  skipQuarkAutoFetch,
  setupAutoFetchWatchers,
} = useDetailResourceTabAutoFetch({
  activeTab,
  pan115SourceTab,
  magnetSourceTab,
  onPan115SubTab: autoFetchPan115SubTab,
  onMagnetSubTab: autoFetchMagnetSubTab,
})
setupAutoFetchWatchers()

const handleSeasonChange = () => {
  magnetSourceTab.value = getFirstVisibleSubTabName(_visibleTabs.value, 'magnet') || 'seedhub'
  magnetPager.value = { seedhub: 1, butailing: 1 }
  magnetResources.value = []
  seedhubMagnetTried.value = false
  butailingMagnetTried.value = false
  pan115Resources.value = []
  resetPan115Diagnostics()
  pansouTried.value = false
  hdhiveTried.value = false
  tgTried.value = false
  pan115SourceTab.value = getFirstVisibleSubTabName(_visibleTabs.value, 'pan115') || 'pansou'
  captureInitialTabs()
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
      tmdb_id: tv.value.id,
      title: tv.value.name,
      media_type: 'tv',
      poster_path: tv.value.poster_path,
      overview: tv.value.overview,
      year: tv.value.first_air_date?.split('-')[0],
      rating: tv.value.vote_average
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
    const { data } = await subscriptionApi.listForStatus({ media_type: 'tv' })
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
  if (saving.value || item?.saving || item?.extracting || checkHdhiveUnlocking(item)) {
    notifyDetailTransferInProgress()
    return
  }

  item.saving = true
  saving.value = true
  if (item?.source_service !== 'hdhive') {
    notifyDetailTransferStarted(item)
  }
  try {
    let defaultFolderId = '0'
    try {
      const { data } = await pan115Api.getDefaultFolder()
      defaultFolderId = data.folder_id || '0'
    } catch (error) {
      console.error('Failed to get default folder:', error)
    }

    const seasonSuffix = selectedSeason.value ? ` S${String(selectedSeason.value).padStart(2, '0')}` : ''
    const folderName = tv.value.name + ' (' + tv.value.first_air_date?.split('-')[0] + ')' + seasonSuffix

    if (item?.source_service === 'hdhive') {
      await runHdhivePan115SaveFlow({
        row: item,
        folderName,
        folderId: defaultFolderId,
        resolveReceiveCode: resolvePanReceiveCode,
        unlockingSlugs: hdhiveUnlockingSlugs.value,
      })
      return
    }

    const shareLink = resolvePanShareLink(item)
    if (!shareLink) {
      ElMessage.warning('该资源暂无分享链接')
      return
    }

    const receiveCode = resolvePanReceiveCode(item, shareLink)
    const { data } = await executePan115SaveToFolder({
      shareUrl: shareLink,
      folderName,
      parentId: defaultFolderId,
      receiveCode,
    })

    const saveSuccess = data?.success === true
      || data?.state === true
      || data?.result?.success === true
      || data?.result?.state === true
    if (!saveSuccess) {
      throw new Error(data?.message || data?.error || data?.result?.error || '转存失败')
    }

    ElMessage.success(data?.message || '转存成功')
  } catch (error) {
    const detail = String(error.response?.data?.detail || error.message || '').trim()
    if (detail.includes('离线任务列表请求过于频繁')) {
      ElMessage.error('115接口触发风控，请稍后重试')
      return
    }
    ElMessage.error(detail || '转存失败')
  } finally {
    item.saving = false
    saving.value = false
  }
}

// 选集转存相关方法
const handleSelectSave = async (item) => {
  if (saving.value || item?.saving || item?.extracting || checkHdhiveUnlocking(item)) return
  selectSaveError.value = ''

  // HDHive 需先解锁再开弹窗，避免解锁失败/取消后弹窗闪一下就消失
  if (item?.source_service === 'hdhive' && isHdhiveResourceLocked(item)) {
    item.extracting = true
    try {
      const unlockedLink = await ensureHdhiveShareLink(item, {
        actionLabel: '选集转存',
        unlockingSlugs: hdhiveUnlockingSlugs.value,
      })
      if (!unlockedLink) return
    } finally {
      item.extracting = false
    }
  }

  item.extracting = true
  extractingFiles.value = true
  shareFilesList.value = []
  selectedFiles.value = []
  fileNameSortOrder.value = 'asc'
  selectSaveDialogVisible.value = true
  selectSaveForm.value = {
    shareLink: '',
    receiveCode: '',
    targetFolder: '0',
    newFolderName: buildDefaultTvFolderName(),
  }

  try {
    await loadPan115SelectSaveFiles({
      row: item,
      unlockingSlugs: hdhiveUnlockingSlugs.value,
      actionLabel: '选集转存',
      skipHdhiveUnlock: item?.source_service === 'hdhive',
      buildFolderName: buildDefaultTvFolderName,
      getDefaultFolderId: async () => {
        try {
          const { data } = await pan115Api.getDefaultFolder()
          return data.folder_id || '0'
        } catch (error) {
          console.error('Failed to get default folder:', error)
          return '0'
        }
      },
      onFormUpdate: (form) => {
        selectSaveForm.value = { ...selectSaveForm.value, ...form }
      },
      onFilesLoaded: (files) => {
        shareFilesList.value = files
        sortShareFilesByName(fileNameSortOrder.value)
      },
    })
  } catch (error) {
    if (error instanceof SelectSaveAbortError) {
      selectSaveDialogVisible.value = false
      return
    }
    selectSaveError.value = normalizePan115TransferError(error) || '提取文件列表失败'
  } finally {
    item.extracting = false
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
  if (saving.value) return
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
      selectSaveForm.value.targetFolder,
      selectSaveForm.value.receiveCode
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

const buildDefaultTvFolderName = () => {
  const title = String(tv.value?.name || '').trim()
  const year = String(tv.value?.first_air_date || '').split('-')[0]
  const seasonSuffix = selectedSeason.value ? ` S${String(selectedSeason.value).padStart(2, '0')}` : ''
  return `${year ? `${title} (${year})` : title}${seasonSuffix}`
}

const openManualPanDialog = () => {
  manualPanForm.value = {
    shareLink: '',
    folderName: buildDefaultTvFolderName(),
    receiveCode: ''
  }
  manualPanDialogVisible.value = true
}

const openManualMagnetDialog = () => {
  manualMagnetForm.value = {
    magnet: '',
    title: buildDefaultTvFolderName()
  }
  manualMagnetDialogVisible.value = true
}

const submitManualPanShare = async () => {
  if (manualPanSubmitting.value) return
  const shareLink = String(manualPanForm.value.shareLink || '').trim()
  if (!shareLink) {
    ElMessage.warning('请输入分享链接')
    return
  }

  manualPanSubmitting.value = true
  try {
    let defaultFolderId = '0'
    try {
      const { data } = await pan115Api.getDefaultFolder()
      defaultFolderId = data.folder_id || '0'
    } catch {
      defaultFolderId = '0'
    }
    const receiveCode = String(manualPanForm.value.receiveCode || '').trim() || parseReceiveCodeFromShareLink(shareLink)
    const folderName = String(manualPanForm.value.folderName || '').trim() || buildDefaultTvFolderName()
    const { data } = await executePan115SaveToFolder({
      shareUrl: shareLink,
      folderName,
      parentId: defaultFolderId,
      receiveCode,
    })
    const saveSuccess = data?.success === true
      || data?.state === true
      || data?.result?.success === true
      || data?.result?.state === true
    if (!saveSuccess) throw new Error(data?.message || data?.error || data?.result?.error || '转存失败')
    ElMessage.success(data?.message || '转存成功')
    manualPanDialogVisible.value = false
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '转存失败')
  } finally {
    manualPanSubmitting.value = false
  }
}

const submitManualMagnet = async () => {
  if (manualMagnetSubmitting.value) return
  const magnet = String(manualMagnetForm.value.magnet || '').trim()
  if (!magnet) {
    ElMessage.warning('请输入磁力链接')
    return
  }

  manualMagnetSubmitting.value = true
  try {
    let defaultFolderId = '0'
    try {
      const { data } = await pan115Api.getOfflineDefaultFolder()
      defaultFolderId = data.folder_id || '0'
    } catch {
      defaultFolderId = '0'
    }
    const title = String(manualMagnetForm.value.title || '').trim() || buildDefaultTvFolderName()
    await pan115Api.addOfflineTask(magnet, defaultFolderId, title)
    ElMessage.success(`已添加到离线下载任务，保存至: ${defaultFolderId === '0' ? '根目录' : title}`)
    manualMagnetDialogVisible.value = false
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '添加离线任务失败')
  } finally {
    manualMagnetSubmitting.value = false
  }
}

const handleCopyPanShareLink = async (row) => {
  const shareLink = resolvePanShareLink(row)
  if (!shareLink) {
    ElMessage.warning('该资源暂无分享链接')
    return
  }
  try {
    await copyText(shareLink)
    ElMessage.success('已复制分享链接')
  } catch (error) {
    ElMessage.error(error.message || '复制失败')
  }
}

const handleCopyMagnet = async (magnet) => {
  try {
    await copyText(magnet)
    ElMessage.success('已复制到剪贴板')
  } catch (error) {
    ElMessage.error(error.message || '复制失败')
  }
}

const handleSaveMagnet = async (item) => {
  if (!item.magnet) {
    ElMessage.warning('无效的磁力链接')
    return
  }
  if (item?.offlineSaving) {
    notifyDetailOfflineInProgress()
    return
  }

  item.offlineSaving = true
  notifyDetailOfflineStarted(item)
  try {
    let defaultFolderId = '0'
    try {
      const { data } = await pan115Api.getOfflineDefaultFolder()
      defaultFolderId = data.folder_id || '0'
    } catch (error) {
      console.error('Failed to get offline default folder:', error)
    }

    const seasonSuffix = selectedSeason.value ? ` S${String(selectedSeason.value).padStart(2, '0')}` : ''
    const folderName = tv.value.name + ' (' + tv.value.first_air_date?.split('-')[0] + ')' + seasonSuffix
    await pan115Api.addOfflineTask(item.magnet, defaultFolderId, folderName)
    ElMessage.success(`已添加到离线下载任务，保存至: ${defaultFolderId === '0' ? '根目录' : folderName}`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '添加离线任务失败')
  } finally {
    item.offlineSaving = false
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
  isInEmby.value = false
  isInFeiniu.value = false
  resetPan115Diagnostics()
  pan115SourceTab.value = getFirstVisibleSubTabName(_visibleTabs.value, 'pan115') || 'pansou'
  magnetSourceTab.value = getFirstVisibleSubTabName(_visibleTabs.value, 'magnet') || 'seedhub'
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
  fetchTv()
  checkSubscribed()
  captureInitialTabs()
})

onMounted(() => {
  loadVisibleTabs()
  activeTab.value = getOrderedVisibleMainTabs(_visibleTabs.value)[0] || 'pan115'
  pan115SourceTab.value = getFirstVisibleSubTabName(_visibleTabs.value, 'pan115') || 'pansou'
  magnetSourceTab.value = getFirstVisibleSubTabName(_visibleTabs.value, 'magnet') || 'seedhub'
  resetPan115Diagnostics()
  fetchTv()
  checkSubscribed()
  refreshQuarkConfigured()
  captureInitialTabs()
})
</script>

<style lang="scss" scoped>
.tv-detail-page {
  animation: fadeIn 0.4s ease;

  .back-button-container {
    margin-bottom: 16px;

    .back-button {
      font-size: 14px;
      color: var(--ms-text-secondary);
      transition: all 0.2s ease;

      &:hover {
        color: var(--ms-primary);
        transform: translateX(-2px);
      }

      .el-icon {
        margin-right: 4px;
      }
    }
  }

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

  .resource-empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding-bottom: 8px;
  }

  .resource-tools {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }

  .resource-tools-split {
    justify-content: space-between;
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
  .tv-detail-page {
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

    .season-selector {
      :deep(.el-select) {
        width: min(240px, 100%);
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
  .tv-detail-page {
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

    .season-selector {
      margin-bottom: 18px;

      :deep(.el-select) {
        width: 100%;
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
        min-width: 720px;
      }
    }
  }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
