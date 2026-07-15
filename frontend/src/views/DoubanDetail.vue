<template>
  <div class="douban-detail-page" v-loading="loading">
    <template v-if="detail">
      <div class="back-button-container">
        <el-button @click="handleBack" class="back-button" text>
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
      </div>
      <div class="detail-header">
        <div class="poster">
          <img :src="getPosterUrl(detail.poster_url)" :alt="detail.title" @error="handlePosterError" />
        </div>
        <div class="info">
          <div class="title-row">
            <h1 class="title">{{ detail.title }}</h1>
            <LibraryBadge
              v-if="isInMediaLibrary"
              class="emby-badge-inline"
              inline
              :in-emby="isInEmby"
              :in-feiniu="isInFeiniu"
            />
          </div>
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
            <span v-if="mappedTmdbId">
              已匹配 TMDB：
              <router-link :to="`/${mediaType === 'tv' ? 'tv' : 'movie'}/${mappedTmdbId}`" class="tmdb-link">
                {{ mappedTmdbId }}
              </router-link>
              <span v-if="detail.imdb_id" class="imdb-tag">IMDB: {{ detail.imdb_id }}</span>
            </span>
            <span v-else>
              未匹配 TMDB，当前页面可使用豆瓣名称关键词手动检索 115 与磁链资源。
              <span v-if="detail.imdb_id" class="imdb-tag">IMDB: {{ detail.imdb_id }}</span>
            </span>
          </p>
        </div>
      </div>

      <div v-if="hasCollection" v-loading="collectionLoading" class="collection-section">
        <template v-if="collection?.parts?.length">
          <div class="collection-header">
            <h3 class="collection-title">合集：{{ collection.name }}</h3>
            <span class="collection-count">共 {{ collection.parts.length }} 部</span>
          </div>
          <div class="collection-scroll">
            <div
              v-for="part in collection.parts"
              :key="part.id"
              class="collection-card"
              :class="{ 'is-current': part.id === mappedTmdbId }"
              @click="part.id !== mappedTmdbId && router.push({ path: `/movie/${part.id}`, query: { from: route.query.from } })"
            >
              <div class="collection-poster">
                <img v-if="part.poster_path" :src="'https://image.tmdb.org/t/p/w500' + part.poster_path" :alt="part.title" />
                <div v-else class="collection-poster-placeholder">
                  <el-icon><VideoCamera /></el-icon>
                </div>
              </div>
              <span class="collection-card-title">{{ part.title }}</span>
              <span class="collection-card-year" v-if="part.release_date">{{ part.release_date.split('-')[0] }}</span>
            </div>
          </div>
        </template>
      </div>

      <el-tabs v-model="activeTab" class="resource-tabs" lazy>
        <template v-for="key in orderedMainTabs" :key="key">
          <el-tab-pane v-if="key === 'pan115'" label="115网盘" name="pan115">
          <el-tabs v-model="pan115SourceTab" class="source-tabs" lazy>
            <template v-for="key in orderedPan115SubTabs" :key="key">
              <el-tab-pane v-if="key === 'pan115_pansou'" label="Pansou" name="pansou">
              <div class="resource-tools resource-tools-split">
                <el-button size="small" type="primary" plain :loading="pansouLoading" @click="fetchPansouPan115">
                  {{ pansouTried ? '重新尝试 Pansou' : '用 Pansou 获取资源' }}
                </el-button>
                <el-button size="small" @click="openManualPanDialog">导入 115 分享</el-button>
              </div>
              <div v-loading="pan115Loading || pansouLoading">
                <el-table v-if="pansouPan115Resources.length" :data="pagedPansouPan115Resources" stripe class="resource-table">
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
                  <el-table-column label="大小" width="110" align="center">
                    <template #default="{ row }">{{ row.size || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="250" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        type="primary"
                        size="small"
                        :disabled="checkPan115ActionDisabled(row)"
                        :loading="Boolean(row.saving) || checkHdhiveUnlocking(row)"
                        @click="savePan115Resource(row)"
                      >
                        转存
                      </el-button>
                      <el-button size="small" :disabled="!resolvePanShareLink(row)" @click="handleCopyPanShareLink(row)">
                        复制链接
                      </el-button>
                      <el-button
                        v-if="mediaType === 'tv'"
                        size="small"
                        :disabled="checkPan115SelectSaveDisabled(row)"
                        :loading="Boolean(row.extracting)"
                        @click="openSelectSaveDialog(row)"
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
              <el-tab-pane v-else-if="key === 'pan115_hdhive'" label="HDHive" name="hdhive">
              <div class="resource-tools resource-tools-split">
                <el-button size="small" type="primary" plain :loading="hdhiveLoading" @click="fetchHdhivePan115">
                  {{ hdhiveTried ? '刷新 HDHive' : '用 HDHive 获取资源' }}
                </el-button>
                <el-button size="small" @click="openManualPanDialog">导入 115 分享</el-button>
              </div>
              <div v-loading="pan115Loading || hdhiveLoading">
                <el-table v-if="hdhivePan115Resources.length" :data="pagedHdhivePan115Resources" stripe class="resource-table">
                  <el-table-column label="资源名称" min-width="360" show-overflow-tooltip>
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
                  <el-table-column label="来源" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info">{{ row.source_service || 'hdhive' }}</el-tag>
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
                  <el-table-column label="分辨率" width="110" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" type="info" v-if="row.resolution">
                        {{ Array.isArray(row.resolution) ? row.resolution.join(', ') : row.resolution }}
                      </el-tag>
                      <el-tag size="small" type="info" v-else-if="getRowTags(row).resolution">{{ getRowTags(row).resolution }}</el-tag>
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
                  <el-table-column label="操作" width="250" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        type="primary"
                        size="small"
                        :disabled="checkPan115ActionDisabled(row)"
                        :loading="Boolean(row.saving) || checkHdhiveUnlocking(row)"
                        @click="savePan115Resource(row)"
                      >
                        转存
                      </el-button>
                      <el-button size="small" :disabled="!resolvePanShareLink(row)" @click="handleCopyPanShareLink(row)">
                        复制链接
                      </el-button>
                      <el-button
                        v-if="mediaType === 'tv'"
                        size="small"
                        :disabled="checkPan115SelectSaveDisabled(row)"
                        :loading="Boolean(row.extracting)"
                        @click="openSelectSaveDialog(row)"
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
                <el-button size="small" type="primary" plain :loading="tgLoading" @click="fetchTgPan115">
                  {{ tgTried ? '刷新 Telegram' : '用 Telegram 获取资源' }}
                </el-button>
                <el-button size="small" @click="openManualPanDialog">导入 115 分享</el-button>
              </div>
              <div v-loading="pan115Loading || tgLoading">
                <el-table v-if="tgPan115Resources.length" :data="pagedTgPan115Resources" stripe class="resource-table">
                  <el-table-column label="资源名称" min-width="360" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span class="resource-name">{{ row.resource_name || row.title || row.name || '未命名资源' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="频道" width="150" align="center" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span>{{ row.tg_channel || '-' }}</span>
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
                  <el-table-column label="大小" width="110" align="center">
                    <template #default="{ row }">{{ row.size || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="250" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        type="primary"
                        size="small"
                        :disabled="checkPan115ActionDisabled(row)"
                        :loading="Boolean(row.saving) || checkHdhiveUnlocking(row)"
                        @click="savePan115Resource(row)"
                      >
                        一键转存
                      </el-button>
                      <el-button size="small" :disabled="!resolvePanShareLink(row)" @click="handleCopyPanShareLink(row)">
                        复制链接
                      </el-button>
                      <el-button
                        v-if="mediaType === 'tv'"
                        size="small"
                        :disabled="checkPan115SelectSaveDisabled(row)"
                        :loading="Boolean(row.extracting)"
                        @click="openSelectSaveDialog(row)"
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
          <div v-if="!mappedTmdbId" class="quark-empty-tip">
            <el-empty description="请先匹配 TMDB 后再查看夸克资源" />
          </div>
          <QuarkResourceTab
            v-else
            :media-type="mediaType"
            :tmdb-id="mappedTmdbId"
            :visible="activeTab === 'quark'"
            :skip-initial-auto-fetch="skipQuarkAutoFetch"
            :quark-configured="quarkConfigured"
            :title="detail?.title || ''"
          />
        </el-tab-pane>

        <el-tab-pane v-else-if="key === 'magnet'" label="磁力链接" name="magnet">
          <el-tabs v-model="magnetSourceTab" class="source-tabs" lazy>
            <template v-for="key in orderedMagnetSubTabs" :key="key">
              <el-tab-pane v-if="key === 'magnet_seedhub'" label="SeedHub" name="seedhub">
              <div class="resource-tools resource-tools-split">
                <el-button size="small" type="primary" plain :loading="seedhubMagnetLoading" @click="fetchSeedhubMagnet">
                  {{ seedhubMagnetTried ? '重新尝试 SeedHub' : '用 SeedHub 获取磁链' }}
                </el-button>
                <el-button size="small" @click="openManualMagnetDialog">导入磁链</el-button>
              </div>
              <div v-loading="seedhubMagnetLoading">
                <el-table v-if="seedhubMagnetResources.length" :data="pagedSeedhubMagnetResources" stripe class="resource-table">
                  <el-table-column label="资源名称" min-width="380" show-overflow-tooltip>
                    <template #default="{ row }">{{ row.name || '-' }}</template>
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
                    <template #default="{ row }">{{ formatSize(row.size) || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        type="primary"
                        size="small"
                        :loading="Boolean(row?.offlineSaving)"
                        @click="saveMagnet(row)"
                      >
                        离线
                      </el-button>
                      <el-button size="small" @click="copyMagnet(row.magnet)">复制</el-button>
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
              <el-tab-pane v-else-if="key === 'magnet_butailing'" label="不太灵" name="butailing">
              <div class="resource-tools resource-tools-split">
                <el-button size="small" type="primary" plain :loading="butailingMagnetLoading" @click="fetchButailingMagnet">
                  {{ butailingMagnetTried ? '刷新不太灵' : '用不太灵获取磁链' }}
                </el-button>
                <el-button size="small" @click="openManualMagnetDialog">导入磁链</el-button>
              </div>
              <div v-loading="butailingMagnetLoading">
                <el-table v-if="butailingMagnetResources.length" :data="pagedButailingMagnetResources" stripe class="resource-table">
                  <el-table-column label="资源名称" min-width="380" show-overflow-tooltip>
                    <template #default="{ row }">{{ row.name || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="大小" width="120" align="center">
                    <template #default="{ row }">{{ row.size || '-' }}</template>
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
                  <el-table-column label="操作" width="180" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        type="primary"
                        size="small"
                        :loading="Boolean(row?.offlineSaving)"
                        @click="saveMagnet(row)"
                      >
                        离线
                      </el-button>
                      <el-button size="small" @click="copyMagnet(row.magnet)">复制</el-button>
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
          <el-input v-model="manualPanForm.folderName" placeholder="默认按豆瓣标题生成" />
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
          <el-input v-model="manualMagnetForm.title" placeholder="默认按豆瓣标题生成" />
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
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { pansouApi, pan115Api, searchApi, subscriptionApi, quarkApi } from '@/api'
import { ArrowLeft, VideoCamera } from '@element-plus/icons-vue'
import LibraryBadge from '@/components/media/LibraryBadge.vue'
import QuarkResourceTab from '@/components/detail/QuarkResourceTab.vue'
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

const orderedPan115SubTabs = computed(() => getOrderedVisibleSubTabs(_visibleTabs.value, 'pan115'))
const orderedMagnetSubTabs = computed(() => getOrderedVisibleSubTabs(_visibleTabs.value, 'magnet'))
const orderedMainTabs = computed(() => getOrderedVisibleMainTabs(_visibleTabs.value))

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

const loading = ref(false)
const mappingLoading = ref(false)
const subscribing = ref(false)
const detail = ref(null)
const quarkConfigured = ref(false)

const refreshQuarkConfigured = async () => {
  try {
    const { data } = await quarkApi.getCookieInfo()
    quarkConfigured.value = Boolean(data?.is_configured)
  } catch {
    quarkConfigured.value = false
  }
}

const activeTab = ref(getOrderedVisibleMainTabs(_visibleTabs.value)[0] || 'pan115')
const pan115SourceTab = ref(getFirstVisibleSubTabName(_visibleTabs.value, 'pan115') || 'pansou')
const magnetSourceTab = ref(getFirstVisibleSubTabName(_visibleTabs.value, 'magnet') || 'seedhub')

const pan115Resources = ref([])
const magnetResources = ref([])
const isSubscribed = ref(false)
const isInEmby = ref(false)
const isInFeiniu = ref(false)
const isInMediaLibrary = computed(() => isInEmby.value || isInFeiniu.value)
const subscriptionId = ref(null)

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
const selectSaveDialogVisible = ref(false)
const extractingFiles = ref(false)
const selectSaving = ref(false)
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
const hdhiveUnlockingSlugs = ref(new Set())

const checkHdhiveUnlocking = (row) => isHdhiveUnlocking(hdhiveUnlockingSlugs.value, row)
const checkPan115ActionDisabled = (row) => isPan115HdhiveActionDisabled(row, hdhiveUnlockingSlugs.value)
const checkPan115SelectSaveDisabled = (row) => isPan115SelectSaveDisabled(row, hdhiveUnlockingSlugs.value, selectSaving.value)
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

const mediaType = computed(() => (String(route.params.mediaType || '').toLowerCase() === 'tv' ? 'tv' : 'movie'))
const doubanId = computed(() => String(route.params.id || '').trim())
const mappedTmdbId = computed(() => {
  const value = Number(detail.value?.tmdb_mapping?.tmdb_id || 0)
  return Number.isFinite(value) && value > 0 ? Math.trunc(value) : null
})

const collection = ref(null)
const collectionLoading = ref(false)
const hasCollection = computed(() => mediaType.value === 'movie' && !!collection.value?.parts?.length)

const fetchCollection = async () => {
  if (!mappedTmdbId.value || mediaType.value !== 'movie') return
  collectionLoading.value = true
  try {
    const { data: movieData } = await searchApi.getMovie(mappedTmdbId.value)
    const collId = movieData?.belongs_to_collection?.id
    if (!collId) { collection.value = null; return }
    const { data } = await searchApi.getCollection(collId)
    collection.value = data
  } catch {
    collection.value = null
  } finally {
    collectionLoading.value = false
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

const buildPan115MergeKey = (item = {}) => {
  const sourceService = String(item?.source_service || 'pansou').trim() || 'pansou'
  const slug = String(item?.slug || '').trim()
  if (slug) return `${sourceService}|slug:${slug}`
  const shareLink = String(item?.share_link || item?.share_url || item?.pan115_share_link || '').trim()
  const title = String(item?.title || item?.name || '').trim()
  return `${sourceService}|${shareLink}|${title}`
}

const mergePan115Resources = (primaryList = [], secondaryList = []) => {
  const merged = []
  const seen = new Set()
  for (const item of [...primaryList, ...secondaryList]) {
    if (!item || typeof item !== 'object') continue
    const key = buildPan115MergeKey(item)
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
    await copyText(value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
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
  } catch {
    ElMessage.error('复制失败')
  }
}

const resolvePanReceiveCode = (row, shareLink = '') => {
  const resolvedLink = String(shareLink || resolvePanShareLink(row)).trim()
  const linkCode = parseReceiveCodeFromShareLink(resolvedLink)
  if (linkCode) return linkCode
  return String(row?.access_code || row?.hdhive_access_code || '').trim()
}

const resolvePan115ShareLink = (row) => {
  return String(row?.share_link || row?.share_url || row?.pan115_share_link || '').trim()
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

const buildPansouKeywords = () => {
  const title = String(detail.value?.title || '').trim()
  const originalTitle = String(detail.value?.original_title || '').trim()
  const aliases = Array.isArray(detail.value?.aliases) ? detail.value.aliases : []
  const year = String(detail.value?.year || '').trim()
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
  for (const alias of aliases) {
    add(alias)
    if (year) add(`${alias} ${year}`)
  }
  return candidates
}

const buildHdhiveKeywords = () => {
  const title = String(detail.value?.title || '').trim()
  const originalTitle = String(detail.value?.original_title || '').trim()
  const aliases = Array.isArray(detail.value?.aliases) ? detail.value.aliases : []
  const year = String(detail.value?.year || '').trim()
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
  for (const alias of aliases) {
    add(alias)
    if (year) add(`${alias} ${year}`)
  }
  return candidates
}

const buildTgKeywords = () => {
  const title = String(detail.value?.title || '').trim()
  const originalTitle = String(detail.value?.original_title || '').trim()
  const aliases = Array.isArray(detail.value?.aliases) ? detail.value.aliases : []
  const year = String(detail.value?.year || '').trim()
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
  for (const alias of aliases) {
    add(alias)
    if (year) add(`${alias} ${year}`)
  }
  return candidates
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
        const link = resolvePanShareLink(row)
        if (!link) continue
        const key = link.toLowerCase()
        if (!dedup.has(key)) {
          dedup.set(key, { ...row, source_service: row.source_service || 'pansou' })
        }
      }
      pansouList = Array.from(dedup.values()).slice(0, 30)
    }
    const normalized = pansouList.map((item) => ({ ...item, source_service: item.source_service || 'pansou' }))
    pan115Resources.value = mergePan115Resources(
      mergePan115Resources(hdhivePan115Resources.value, tgPan115Resources.value),
      normalized
    )
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
  if (hdhiveLoading.value) return
  hdhiveLoading.value = true
  hdhiveTried.value = true
  try {
    let hdhiveList = []
    if (mappedTmdbId.value) {
      const response = mediaType.value === 'tv'
        ? await searchApi.getTvPan115Hdhive(mappedTmdbId.value)
        : await searchApi.getMoviePan115Hdhive(mappedTmdbId.value)
      hdhiveList = (Array.isArray(response.data?.list) ? response.data.list : [])
    } else {
      const keywords = buildHdhiveKeywords()
      const dedup = new Map()
      for (const keyword of keywords) {
        const { data } = await searchApi.getHdhivePan115ByKeyword(keyword, mediaType.value)
        const rows = Array.isArray(data?.list) ? data.list : []
        for (const row of rows) {
          const key = `${String(row?.slug || '')}|${String(row?.share_link || '')}`.toLowerCase()
          if (!dedup.has(key)) {
            dedup.set(key, row)
          }
        }
        if (dedup.size >= 30) break
      }
      hdhiveList = Array.from(dedup.values()).slice(0, 30)
    }

    const normalizedHdhiveList = hdhiveList
      .map((item) => ({ ...item, source_service: item.source_service || 'hdhive' }))
    pan115Resources.value = mergePan115Resources(
      mergePan115Resources(pansouPan115Resources.value, tgPan115Resources.value),
      normalizedHdhiveList
    )
    if (!normalizedHdhiveList.length) {
      ElMessage.info('HDHive 暂未找到可用资源')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || 'HDHive 资源获取失败')
  } finally {
    hdhiveLoading.value = false
  }
}

const fetchTgPan115 = async () => {
  if (tgLoading.value) return
  tgLoading.value = true
  tgTried.value = true
  try {
    let tgList = []
    if (mappedTmdbId.value) {
      const response = mediaType.value === 'tv'
        ? await searchApi.getTvPan115Tg(mappedTmdbId.value)
        : await searchApi.getMoviePan115Tg(mappedTmdbId.value)
      tgList = Array.isArray(response.data?.list) ? response.data.list : []
    } else {
      const keywords = buildTgKeywords()
      const dedup = new Map()
      for (const keyword of keywords) {
        const { data } = await searchApi.getTgPan115ByKeyword(keyword, mediaType.value)
        const rows = Array.isArray(data?.list) ? data.list : []
        for (const row of rows) {
          const key = `${String(row?.tg_channel || '')}|${String(row?.tg_message_id || '')}|${String(row?.share_link || row?.pan115_share_link || '')}`.toLowerCase()
          if (!dedup.has(key)) {
            dedup.set(key, row)
          }
        }
        if (dedup.size >= 30) break
      }
      tgList = Array.from(dedup.values()).slice(0, 30)
    }
    const normalizedTgList = tgList.map((item) => ({ ...item, source_service: item.source_service || 'tg' }))
    pan115Resources.value = mergePan115Resources(
      mergePan115Resources(pansouPan115Resources.value, hdhivePan115Resources.value),
      normalizedTgList
    )
    if (!normalizedTgList.length) {
      ElMessage.info('Telegram 暂未找到可用资源')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || 'Telegram 资源获取失败')
  } finally {
    tgLoading.value = false
  }
}

const fetchSeedhubMagnet = async () => {
  if (!detail.value || seedhubMagnetLoading.value) return
  seedhubMagnetLoading.value = true
  seedhubMagnetTried.value = true
  magnetPager.value.seedhub = 1
  try {
    if (mappedTmdbId.value) {
      const request = mediaType.value === 'tv'
        ? searchApi.getTvMagnetSeedhub(mappedTmdbId.value, seedhubFetchLimit)
        : searchApi.getMovieMagnetSeedhub(mappedTmdbId.value, seedhubFetchLimit)
      const { data } = await request
      const rows = Array.isArray(data?.list) ? data.list : []
      const normalizedRows = rows.map((item) => ({ ...item, source_service: item?.source_service || 'seedhub' }))
      magnetResources.value = mergeMagnetResources(magnetResources.value, normalizedRows)
      if (normalizedRows.length === 0) {
        ElMessage.info('SeedHub 暂未找到可用磁链')
      }
      return
    }

    const keyword = buildPansouKeywords()[0] || ''
    if (!keyword) {
      magnetResources.value = magnetResources.value.slice()
      ElMessage.info('缺少可用关键词，无法从 SeedHub 获取磁链')
      return
    }
    const { data } = await searchApi.getSeedhubMagnetByKeyword(keyword, mediaType.value, seedhubFetchLimit)
    const rows = Array.isArray(data?.list) ? data.list : []
    const normalizedRows = rows.map((item) => ({ ...item, source_service: item?.source_service || 'seedhub' }))
    magnetResources.value = mergeMagnetResources(magnetResources.value, normalizedRows)
    if (seedhubMagnetResources.value.length === 0) {
      ElMessage.info('SeedHub 暂未找到可用磁链')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || 'SeedHub 磁链获取失败')
  } finally {
    seedhubMagnetLoading.value = false
  }
}

const fetchButailingMagnet = async () => {
  if (!detail.value || butailingMagnetLoading.value) return
  butailingMagnetLoading.value = true
  butailingMagnetTried.value = true
  magnetPager.value.butailing = 1
  try {
    if (mappedTmdbId.value) {
      const request = mediaType.value === 'tv'
        ? searchApi.getTvMagnetButailing(mappedTmdbId.value)
        : searchApi.getMovieMagnetButailing(mappedTmdbId.value)
      const { data } = await request
      const rows = Array.isArray(data?.list) ? data.list : []
      const normalizedRows = rows.map((item) => ({ ...item, source_service: item?.source_service || 'butailing' }))
      magnetResources.value = mergeMagnetResources(magnetResources.value, normalizedRows)
      if (normalizedRows.length === 0) {
        ElMessage.info('不太灵暂未找到可用磁链')
      }
      return
    }
    ElMessage.info('当前影视缺少 TMDB 映射，无法通过不太灵搜索')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '不太灵磁链获取失败')
  } finally {
    butailingMagnetLoading.value = false
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
    pan115SourceTab.value = getFirstVisibleSubTabName(_visibleTabs.value, 'pan115') || 'pansou'
    void hydrateDoubanAuxiliaryData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '豆瓣详情获取失败')
  } finally {
    loading.value = false
  }
}

const hydrateDoubanAuxiliaryData = async () => {
  await Promise.allSettled([
    refreshSubscribeState(),
    refreshEmbyStatus(),
    refreshFeiniuStatus(),
    fetchCollection()
  ])
}

const getDefaultTransferFolderId = async () => {
  try {
    const { data } = await pan115Api.getDefaultFolder()
    return data.folder_id || '0'
  } catch {
    return '0'
  }
}

const getDefaultOfflineFolderId = async () => {
  try {
    const { data } = await pan115Api.getOfflineDefaultFolder()
    return data.folder_id || '0'
  } catch {
    return '0'
  }
}

const buildDefaultDetailFolderName = () => String(detail.value?.title || '豆瓣资源').trim()

const openManualPanDialog = () => {
  manualPanForm.value = {
    shareLink: '',
    folderName: buildDefaultDetailFolderName(),
    receiveCode: ''
  }
  manualPanDialogVisible.value = true
}

const openManualMagnetDialog = () => {
  manualMagnetForm.value = {
    magnet: '',
    title: buildDefaultDetailFolderName()
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
    const folderId = await getDefaultTransferFolderId()
    const folderName = String(manualPanForm.value.folderName || '').trim() || buildDefaultDetailFolderName()
    const receiveCode = String(manualPanForm.value.receiveCode || '').trim() || parseReceiveCodeFromShareLink(shareLink)
    const { data } = await executePan115SaveToFolder({
      shareUrl: shareLink,
      folderName,
      parentId: folderId,
      receiveCode,
    })
    const success = data?.success === true || data?.state === true || data?.result?.success === true || data?.result?.state === true
    if (!success) throw new Error(data?.message || data?.error || data?.result?.error || '转存失败')
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
    const folderId = await getDefaultOfflineFolderId()
    const title = String(manualMagnetForm.value.title || '').trim() || buildDefaultDetailFolderName()
    await pan115Api.addOfflineTask(magnet, folderId, title)
    ElMessage.success('已提交离线任务')
    manualMagnetDialogVisible.value = false
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '离线失败')
  } finally {
    manualMagnetSubmitting.value = false
  }
}

const savePan115Resource = async (row) => {
  if (row?.saving || row?.extracting || checkHdhiveUnlocking(row)) {
    notifyDetailTransferInProgress()
    return
  }

  row.saving = true
  if (row?.source_service !== 'hdhive') {
    notifyDetailTransferStarted(row)
  }
  try {
    const folderName = detail.value?.title || '豆瓣资源'

    if (row?.source_service === 'hdhive') {
      const folderId = await getDefaultTransferFolderId()
      await runHdhivePan115SaveFlow({
        row,
        folderName,
        folderId,
        resolveReceiveCode: resolvePanReceiveCode,
        unlockingSlugs: hdhiveUnlockingSlugs.value,
      })
      return
    }

    const shareLink = resolvePanShareLink(row)
    if (!shareLink) {
      ElMessage.warning('资源缺少分享链接')
      return
    }

    const folderId = await getDefaultTransferFolderId()
    const receiveCode = resolvePanReceiveCode(row, shareLink)
    const { data } = await executePan115SaveToFolder({
      shareUrl: shareLink,
      folderName,
      parentId: folderId,
      receiveCode,
    })
    const success = data?.success === true
      || data?.state === true
      || data?.result?.success === true
      || data?.result?.state === true
    if (!success) {
      throw new Error(data?.message || data?.error || data?.result?.error || '转存失败')
    }
    if (data?.saved_count === 0) {
      ElMessage.warning(data?.message || '所有剧集均已存在，无需转存')
    } else {
      ElMessage.success(data?.message || '转存成功')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '转存失败')
  } finally {
    row.saving = false
  }
}

const openSelectSaveDialog = async (row) => {
  if (row?.saving || row?.extracting || checkHdhiveUnlocking(row)) return
  if (mediaType.value !== 'tv') {
    ElMessage.warning('仅剧集资源支持选集转存')
    return
  }
  selectSaveError.value = ''

  if (row?.source_service === 'hdhive' && isHdhiveResourceLocked(row)) {
    row.extracting = true
    try {
      const unlockedLink = await ensureHdhiveShareLink(row, {
        actionLabel: '选集转存',
        unlockingSlugs: hdhiveUnlockingSlugs.value,
      })
      if (!unlockedLink) return
    } finally {
      row.extracting = false
    }
  }

  row.extracting = true
  extractingFiles.value = true
  shareFilesList.value = []
  selectedFiles.value = []
  fileNameSortOrder.value = 'asc'
  selectSaveDialogVisible.value = true
  selectSaveForm.value = {
    shareLink: '',
    receiveCode: '',
    targetFolder: '0',
    newFolderName: buildDefaultDetailFolderName(),
  }

  try {
    await loadPan115SelectSaveFiles({
      row,
      unlockingSlugs: hdhiveUnlockingSlugs.value,
      actionLabel: '选集转存',
      skipHdhiveUnlock: row?.source_service === 'hdhive',
      buildFolderName: buildDefaultDetailFolderName,
      getDefaultFolderId: getDefaultTransferFolderId,
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
  if (row?.offlineSaving) {
    notifyDetailOfflineInProgress()
    return
  }

  row.offlineSaving = true
  notifyDetailOfflineStarted(row)
  try {
    const folderId = await getDefaultOfflineFolderId()
    const title = detail.value?.title || '豆瓣资源'
    await pan115Api.addOfflineTask(url, folderId, title)
    ElMessage.success('已提交离线任务')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '离线失败')
  } finally {
    row.offlineSaving = false
  }
}

const refreshSubscribeState = async () => {
  if (!mappedTmdbId.value) {
    isSubscribed.value = false
    subscriptionId.value = null
    return
  }
  try {
    const { data } = await subscriptionApi.listForStatus({ media_type: mediaType.value })
    // 处理新的返回格式：{ items: [], douban_id_map: {}, imdb_id_map: {} }
    const list = Array.isArray(data) ? data : (data?.items || [])
    const matched = list.find((item) => Number(item.tmdb_id) === mappedTmdbId.value && item.media_type === mediaType.value) || null
    isSubscribed.value = Boolean(matched)
    subscriptionId.value = Number(matched?.id || 0) || null
  } catch {
    isSubscribed.value = false
    subscriptionId.value = null
  }
}

const refreshEmbyStatus = async () => {
  if (!mappedTmdbId.value) {
    isInEmby.value = false
    return
  }
  try {
    const { data } = await searchApi.getEmbyStatusMap([{ media_type: mediaType.value, tmdb_id: mappedTmdbId.value }])
    const payload = data?.items || {}
    isInEmby.value = Boolean(payload[`${mediaType.value}:${mappedTmdbId.value}`]?.exists_in_emby)
  } catch {
    isInEmby.value = false
  }
}

const refreshFeiniuStatus = async () => {
  if (!mappedTmdbId.value) {
    isInFeiniu.value = false
    return
  }
  try {
    const { data } = await searchApi.getFeiniuStatusMap([{ media_type: mediaType.value, tmdb_id: mappedTmdbId.value }])
    const payload = data?.items || {}
    isInFeiniu.value = Boolean(payload[`${mediaType.value}:${mappedTmdbId.value}`]?.exists_in_feiniu)
  } catch {
    isInFeiniu.value = false
  }
}

const handleSubscribe = async () => {
  if (!mappedTmdbId.value || !detail.value) {
    ElMessage.warning('请先匹配 TMDB 后再订阅')
    return
  }
  subscribing.value = true
  const previousSubscribed = Boolean(isSubscribed.value)
  const previousSubscriptionId = subscriptionId.value
  try {
    if (isSubscribed.value) {
      if (!subscriptionId.value) {
        await refreshSubscribeState()
      }
      if (!subscriptionId.value) {
        ElMessage.warning('未找到订阅记录')
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
      douban_id: detail.value.douban_id,
      tmdb_id: mappedTmdbId.value,
      title: detail.value.title,
      media_type: mediaType.value,
      poster_path: '',
      overview: detail.value.intro || '',
      year: detail.value.year || '',
      rating: detail.value.rating || null
    })
    subscriptionId.value = Number(data?.id || 0) || null
    ElMessage.success('订阅成功')
  } catch (error) {
    if (error.response?.status === 400) {
      isSubscribed.value = true
      refreshSubscribeState()
      ElMessage.info('该影视已在订阅列表中')
      return
    }
    isSubscribed.value = previousSubscribed
    subscriptionId.value = previousSubscriptionId
    ElMessage.error(error.response?.data?.detail || error.message || '订阅失败')
  } finally {
    subscribing.value = false
  }
}

const resetResources = () => {
  pan115Resources.value = []
  pan115Pager.value = { pansou: 1, hdhive: 1, tg: 1 }
  magnetPager.value = { seedhub: 1, butailing: 1 }
  magnetResources.value = []
  pan115Loading.value = false
  pansouLoading.value = false
  pansouTried.value = false
  hdhiveLoading.value = false
  hdhiveTried.value = false
  tgLoading.value = false
  tgTried.value = false
  magnetLoading.value = false
  seedhubMagnetLoading.value = false
  seedhubMagnetTried.value = false
  butailingMagnetLoading.value = false
  butailingMagnetTried.value = false
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
      original_title: detail.value.original_title,
      aliases: Array.isArray(detail.value.aliases) ? detail.value.aliases : [],
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
      await Promise.allSettled([
        refreshSubscribeState(),
        refreshEmbyStatus(),
        refreshFeiniuStatus()
      ])
      return
    }
    ElMessage.warning('仍未匹配到 TMDB，可继续使用豆瓣关键词资源搜索')
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

const autoFetchPan115SubTab = (tab) => {
  if (tab === 'pansou' && !pansouTried.value) {
    void fetchPansouPan115()
    return
  }
  if (tab === 'hdhive' && !hdhiveTried.value) {
    void fetchHdhivePan115()
    return
  }
  if (tab === 'tg' && !tgTried.value) {
    void fetchTgPan115()
  }
}

const autoFetchMagnetSubTab = (tab) => {
  if (tab === 'seedhub' && !seedhubMagnetTried.value) {
    void fetchSeedhubMagnet()
    return
  }
  if (tab === 'butailing' && !butailingMagnetTried.value) {
    void fetchButailingMagnet()
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

watch(pan115SourceTab, async (tab) => {
  if (tab === 'pansou') pan115Pager.value.pansou = 1
  if (tab === 'hdhive') pan115Pager.value.hdhive = 1
  if (tab === 'tg') pan115Pager.value.tg = 1
})

watch(magnetSourceTab, async (tab) => {
  if (tab === 'seedhub') magnetPager.value.seedhub = 1
  if (tab === 'butailing') magnetPager.value.butailing = 1
})

watch(() => `${route.params.mediaType || ''}:${route.params.id || ''}`, async () => {
  isInEmby.value = false
  isInFeiniu.value = false
  activeTab.value = getOrderedVisibleMainTabs(_visibleTabs.value)[0] || 'pan115'
  pan115SourceTab.value = getFirstVisibleSubTabName(_visibleTabs.value, 'pan115') || 'pansou'
  magnetSourceTab.value = getFirstVisibleSubTabName(_visibleTabs.value, 'magnet') || 'seedhub'
  resetResources()
  await loadDetail()
  captureInitialTabs()
})

onMounted(async () => {
  await loadVisibleTabs()
  activeTab.value = getOrderedVisibleMainTabs(_visibleTabs.value)[0] || 'pan115'
  pan115SourceTab.value = getFirstVisibleSubTabName(_visibleTabs.value, 'pan115') || 'pansou'
  magnetSourceTab.value = getFirstVisibleSubTabName(_visibleTabs.value, 'magnet') || 'seedhub'
  await loadDetail()
  refreshQuarkConfigured()
  captureInitialTabs()
})
</script>

<style scoped lang="scss">
.douban-detail-page {
  padding: 8px;

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
        margin: 0;
        font-size: 28px;
      }

      .original-title {
        margin-top: 6px;
        color: var(--ms-text-secondary);
      }

      .meta {
        display: flex;
        gap: 14px;
        margin-top: 8px;
        color: var(--ms-text-secondary);
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
        color: var(--ms-text-muted);
        font-size: 13px;

        .tmdb-link {
          color: #409eff;
          text-decoration: none;
          font-weight: 500;

          &:hover {
            text-decoration: underline;
          }
        }

        .imdb-tag {
          margin-left: 10px;
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

  .collection-section {
    margin-bottom: 24px;
    background: var(--ms-gradient-card);
    border: 1px solid var(--ms-glass-border);
    border-radius: 16px;
    padding: 20px;

    .collection-header {
      display: flex;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 16px;

      .collection-title {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
        color: var(--ms-text-primary);
      }

      .collection-count {
        font-size: 13px;
        color: var(--ms-text-muted);
      }
    }

    .collection-scroll {
      display: flex;
      gap: 12px;
      overflow-x: auto;
      padding-bottom: 8px;
      scroll-behavior: smooth;
      -webkit-overflow-scrolling: touch;

      &::-webkit-scrollbar {
        height: 4px;
      }

      &::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.15);
        border-radius: 2px;
      }
    }

    .collection-card {
      flex-shrink: 0;
      width: 130px;
      cursor: pointer;
      border-radius: 10px;
      overflow: hidden;
      background: rgba(255, 255, 255, 0.04);
      border: 2px solid transparent;
      transition: all 0.2s ease;

      &:hover {
        background: rgba(45, 153, 255, 0.08);
        border-color: rgba(45, 153, 255, 0.3);
        transform: translateY(-2px);
      }

      &.is-current {
        border-color: var(--ms-accent, #2d99ff);
        background: rgba(45, 153, 255, 0.08);
        cursor: default;

        .collection-card-title {
          color: var(--ms-accent, #2d99ff);
        }
      }

      .collection-poster {
        width: 130px;
        height: 195px;
        overflow: hidden;
        background: rgba(0, 0, 0, 0.2);

        img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
      }

      .collection-poster-placeholder {
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 32px;
        color: var(--ms-text-muted);
      }

      .collection-card-title {
        display: block;
        padding: 8px 8px 2px;
        font-size: 13px;
        font-weight: 500;
        color: var(--ms-text-primary);
        line-height: 1.3;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .collection-card-year {
        display: block;
        padding: 0 8px 8px;
        font-size: 11px;
        color: var(--ms-text-muted);
      }
    }
  }

  .resource-tools {
    margin-bottom: 10px;
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }

  .resource-empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding-bottom: 8px;
  }

  .resource-tabs {
    background: var(--ms-gradient-card);
    border: 1px solid var(--ms-glass-border);
    border-radius: 16px;
    padding: 20px;

    :deep(.el-tabs__content) {
      padding-top: 12px;
    }
  }

  .resource-tools-split {
    justify-content: space-between;
  }

  .table-pagination {
    margin-top: 12px;
    display: flex;
    justify-content: flex-end;
  }

  :deep(.resource-table) {
    --el-table-row-hover-bg-color: rgba(45, 153, 255, 0.12);
    --el-table-header-bg-color: rgba(67, 123, 198, 0.2);
    --el-table-border-color: rgba(79, 145, 226, 0.18);

    .el-table__inner-wrapper::before {
      display: none;
    }

    .el-table__header th {
      background: rgba(67, 123, 198, 0.2);
      color: var(--ms-text-primary);
      border-bottom: 1px solid var(--ms-border-color);
      font-weight: 600;
    }

    .el-table__body tr > td {
      background: rgba(17, 37, 72, 0.34);
      border-bottom: 1px solid var(--ms-border-color);
    }

    .el-table__body tr.el-table__row--striped > td {
      background: rgba(17, 37, 72, 0.34);
    }

    .el-table__body tr:hover > td {
      background: rgba(45, 153, 255, 0.12) !important;
    }

    .el-table__empty-block {
      background: rgba(17, 37, 72, 0.34);
    }
  }

  .resource-name {
    font-weight: 500;
  }

  .resource-name-row {
    display: inline-flex;
    align-items: center;
    gap: 8px;
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

@media (max-width: 1024px) {
  .douban-detail-page {
    padding: 0;

    .detail-header {
      gap: 18px;

      .poster {
        width: 190px;
      }

      .info {
        .title {
          font-size: 26px;
        }

        .meta,
        .actions {
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

@media (max-width: 900px) {
  .douban-detail-page {
    .detail-header {
      flex-direction: column;

      .poster {
        width: min(200px, 58vw);
        margin: 0 auto;
      }

      .info {
        .title {
          font-size: 24px;
        }

        .meta {
          gap: 10px;
          flex-wrap: wrap;
        }

        .actions {
          .el-button {
            flex: 1 1 100%;
            margin-left: 0;
          }
        }
      }
    }

    .resource-tabs {
      padding: 14px;
    }

    :deep(.resource-table) {
      display: block;
      overflow-x: auto;

      .el-table__inner-wrapper {
        min-width: 700px;
      }
    }
  }
}
</style>
