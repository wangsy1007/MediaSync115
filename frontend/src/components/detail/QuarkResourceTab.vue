<template>
  <div class="quark-resource-tab">
    <el-tabs v-model="activeSubTab" class="source-tabs">
      <el-tab-pane label="Pansou" name="pansou">
        <div class="resource-tools">
          <el-button size="small" type="primary" plain :loading="loading.pansou"
            @click="fetchResources('pansou', true)">
            {{ tried.pansou ? '重新尝试 Pansou' : '用 Pansou 获取夸克资源' }}
          </el-button>
        </div>
        <div v-loading="loading.pansou">
          <el-table v-if="resources.pansou.length" :data="pagedResources.pansou" stripe class="resource-table">
            <el-table-column label="资源名称" min-width="320" show-overflow-tooltip>
              <template #default="{ row }">
                <a :href="row.share_link" target="_blank" rel="noopener noreferrer" class="resource-name">
                  {{ row.title || row.name || '未命名' }}
                </a>
              </template>
            </el-table-column>
            <el-table-column label="大小" width="120" prop="size" />
            <el-table-column label="分辨率" width="100" prop="resolution" />
            <el-table-column label="操作" width="140" align="center">
              <template #default="{ row }">
                <el-button type="primary" size="small"
                  :disabled="!quarkConfigured || row.cloud_savable === false"
                  :loading="Boolean(row.saving)"
                  @click="saveResource(row)">
                  转存
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="resources.pansou.length > pageSize" class="table-pagination">
            <el-pagination background layout="prev, pager, next"
              :total="resources.pansou.length" :page-size="pageSize"
              :current-page="pager.pansou"
              @current-change="(page) => (pager.pansou = page)" />
          </div>
          <el-empty v-else
            :description="tried.pansou ? '暂无可用夸克网盘资源' : '尚未获取 Pansou 资源'" />
        </div>
      </el-tab-pane>

      <el-tab-pane label="HDHive" name="hdhive">
        <div class="resource-tools">
          <el-button size="small" type="primary" plain :loading="loading.hdhive"
            @click="fetchResources('hdhive', true)">
            {{ tried.hdhive ? '刷新 HDHive' : '用 HDHive 获取夸克资源' }}
          </el-button>
        </div>
        <div v-loading="loading.hdhive">
          <el-table v-if="resources.hdhive.length" :data="pagedResources.hdhive" stripe class="resource-table">
            <el-table-column label="资源名称" min-width="320" show-overflow-tooltip>
              <template #default="{ row }">
                <a :href="row.share_link || row.share_url" target="_blank" rel="noopener noreferrer" class="resource-name">
                  {{ row.title || row.name || '未命名' }}
                </a>
              </template>
            </el-table-column>
            <el-table-column label="大小" width="120" prop="size" />
            <el-table-column label="分辨率" width="100" prop="resolution" />
            <el-table-column label="操作" width="140" align="center">
              <template #default="{ row }">
                <el-button type="primary" size="small"
                  :disabled="!quarkConfigured || row.cloud_savable === false"
                  :loading="Boolean(row.saving)"
                  @click="saveResource(row)">
                  转存
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="resources.hdhive.length > pageSize" class="table-pagination">
            <el-pagination background layout="prev, pager, next"
              :total="resources.hdhive.length" :page-size="pageSize"
              :current-page="pager.hdhive"
              @current-change="(page) => (pager.hdhive = page)" />
          </div>
          <el-empty v-else
            :description="tried.hdhive ? 'HDHive 暂无可用夸克资源' : '尚未获取 HDHive 资源'" />
        </div>
      </el-tab-pane>

      <el-tab-pane label="Telegram" name="tg">
        <div class="resource-tools">
          <el-button size="small" type="primary" plain :loading="loading.tg"
            @click="fetchResources('tg', true)">
            {{ tried.tg ? '刷新 Telegram' : '用 Telegram 获取夸克资源' }}
          </el-button>
        </div>
        <div v-loading="loading.tg">
          <el-empty
            description="TG 索引暂未支持夸克链接，将在后续版本扩展" />
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-alert v-if="!quarkConfigured" type="warning" :closable="false" class="cookie-warning">
      <template #title>
        请先在 <el-button type="primary" link @click="goSettings">设置页 → 夸克网盘</el-button> 配置 Cookie 与默认转存目录
      </template>
    </el-alert>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { searchApi, quarkApi } from '@/api'

defineOptions({ name: 'QuarkResourceTab' })

const props = defineProps({
  mediaType: { type: String, required: true },
  tmdbId: { type: [Number, String], required: true },
  visible: { type: Boolean, default: false },
  quarkConfigured: { type: Boolean, default: false },
  season: { type: Number, default: null },
  title: { type: String, default: '' },
})

const router = useRouter()

const SOURCE_QUARK_APIS = {
  pansou: (type) => (type === 'tv' ? searchApi.getTvQuarkPansou : searchApi.getMovieQuarkPansou),
  hdhive: (type) => (type === 'tv' ? searchApi.getTvQuarkHdhive : searchApi.getMovieQuarkHdhive),
  tg: (type) => (type === 'tv' ? searchApi.getTvQuarkTg : searchApi.getMovieQuarkTg),
}

const pageSize = 8
const activeSubTab = ref('pansou')
const resources = reactive({ pansou: [], hdhive: [], tg: [] })
const loaded = reactive({ pansou: false, hdhive: false, tg: false })
const tried = reactive({ pansou: false, hdhive: false, tg: false })
const loading = reactive({ pansou: false, hdhive: false, tg: false })
const pager = reactive({ pansou: 1, hdhive: 1, tg: 1 })

const pagedResources = computed(() => {
  const make = (sub) => {
    const list = resources[sub]
    const start = (pager[sub] - 1) * pageSize
    return list.slice(start, start + pageSize)
  }
  return {
    pansou: make('pansou'),
    hdhive: make('hdhive'),
    tg: make('tg'),
  }
})

const fetchResources = async (sub, force = false) => {
  if (loading[sub]) return
  loading[sub] = true
  tried[sub] = true
  try {
    const fn = SOURCE_QUARK_APIS[sub](props.mediaType)
    const args =
      props.mediaType === 'tv'
        ? [props.tmdbId, 1, force, props.season || null]
        : [props.tmdbId, 1, force]
    const { data } = await fn(...args)
    resources[sub] = Array.isArray(data?.list) ? data.list : []
    loaded[sub] = true
    pager[sub] = 1
  } catch (e) {
    const detail = e.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : detail?.message || e.message
    ElMessage.error(msg || '夸克资源加载失败')
    resources[sub] = []
  } finally {
    loading[sub] = false
  }
}

const goSettings = () => {
  router.push('/settings?tab=quark')
}

const saveResource = async (row) => {
  if (!props.quarkConfigured) {
    ElMessageBox.confirm(
      '请先在设置页配置夸克 Cookie 与默认转存目录后再转存',
      '夸克未配置',
      { confirmButtonText: '前往设置', cancelButtonText: '取消', type: 'warning' }
    ).then(goSettings).catch(() => {})
    return
  }

  if (row.cloud_savable === false) {
    ElMessage.warning('该资源当前无法转存')
    return
  }

  row.saving = true
  try {
    const folderName = (row.title || row.name || props.title || '').trim()
    const { data } = await quarkApi.saveShareToFolder({
      share_url: row.share_link || row.share_url,
      folder_name: folderName || null,
      tmdb_id: Number(props.tmdbId) || null,
    })
    if (data?.success) {
      row.justSaved = true
      ElMessage.success(`已转存（共 ${data.item_count || 0} 个文件）`)
    } else {
      ElMessage.warning(data?.message || '转存失败')
    }
  } catch (e) {
    const detail = e.response?.data?.detail
    const code = detail?.code
    const message = typeof detail === 'string' ? detail : detail?.message || e.message
    if (code === 'quark_default_dir_missing') {
      ElMessageBox.confirm('请先在设置页选择夸克默认转存目录', '默认目录未配置', {
        confirmButtonText: '前往设置', cancelButtonText: '取消', type: 'warning'
      }).then(goSettings).catch(() => {})
    } else if (code === 'quark_cookie_invalid' || code === 'quark_cookie_missing') {
      ElMessageBox.confirm(message || '夸克 Cookie 无效，请重新获取', '夸克 Cookie 异常', {
        confirmButtonText: '前往设置', cancelButtonText: '取消', type: 'warning'
      }).then(goSettings).catch(() => {})
    } else {
      ElMessage.error(message || '夸克转存失败')
    }
  } finally {
    row.saving = false
  }
}

// 懒加载：visible / activeSubTab 变化时按需触发
watch(
  () => [props.visible, activeSubTab.value],
  ([visible, sub]) => {
    if (!visible) return
    if (loaded[sub]) return
    fetchResources(sub)
  },
  { immediate: true }
)

watch(
  () => `${props.tmdbId}|${props.season || 0}`,
  () => {
    // tmdbId/season 变化时清空已加载状态
    Object.assign(loaded, { pansou: false, hdhive: false, tg: false })
    Object.assign(tried, { pansou: false, hdhive: false, tg: false })
    Object.assign(resources, { pansou: [], hdhive: [], tg: [] })
    if (props.visible && !loaded[activeSubTab.value]) {
      fetchResources(activeSubTab.value)
    }
  }
)
</script>

<style lang="scss" scoped>
.quark-resource-tab {
  .source-tabs {
    margin-bottom: 8px;
  }

  .resource-tools {
    margin-bottom: 12px;
  }

  .resource-name {
    color: var(--el-color-primary);
    text-decoration: none;
  }

  .resource-name:hover {
    text-decoration: underline;
  }

  .table-pagination {
    margin-top: 12px;
    display: flex;
    justify-content: center;
  }

  .cookie-warning {
    margin-top: 12px;
  }
}
</style>
