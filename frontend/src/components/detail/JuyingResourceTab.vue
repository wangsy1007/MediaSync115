<template>
  <div class="juying-resource-tab" v-loading="loading">
    <div class="resource-tools">
      <el-button type="primary" plain size="small" :loading="loading" @click="fetchResources(true)">
        {{ tried ? '刷新聚影' : `用聚影获取${isMagnet ? '磁力' : '115'}资源` }}
      </el-button>
      <span v-if="matchedMovie" class="match-info">
        匹配：{{ matchedMovie.title }}<template v-if="matchedMovie.year">（{{ matchedMovie.year }}）</template>
      </span>
    </div>

    <el-table v-if="resources.length" :data="pagedResources" stripe class="resource-table">
      <el-table-column label="资源名称" min-width="360" show-overflow-tooltip>
        <template #default="{ row }">
          <span>{{ row.title || row.name || '未命名资源' }}</span>
          <el-tag v-if="row.link_exposed === false" type="warning" size="small" class="hidden-tag">
            暂不可访问
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="130">
        <template #default="{ row }">{{ row.size || row.file_size || '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="190" align="center" fixed="right">
        <template #default="{ row }">
          <el-button
            type="primary"
            size="small"
            :disabled="row.link_exposed === false"
            :loading="Boolean(row.working)"
            @click="isMagnet ? saveMagnet(row) : savePan115(row)"
          >
            {{ isMagnet ? '离线' : '转存' }}
          </el-button>
          <el-button
            size="small"
            :disabled="row.link_exposed === false"
            :loading="Boolean(row.copying)"
            @click="copyResource(row)"
          >复制</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="resources.length > pageSize"
      v-model:current-page="page"
      background
      layout="prev, pager, next"
      :page-size="pageSize"
      :total="resources.length"
      class="pagination"
    />
    <div v-if="!loading && !resources.length && alternateCount" class="alternate-resource-tip">
      <el-empty :description="emptyDescription" />
      <el-button type="primary" plain @click="switchResourceType">
        查看 {{ alternateCount }} 条聚影{{ alternateLabel }}资源
      </el-button>
    </div>
    <el-empty v-else-if="!loading && !resources.length" :description="emptyDescription" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { juyingApi, pan115Api } from '@/api'
import { copyText } from '@/utils/clipboard'
import { executePan115SaveToFolder } from '@/utils/pan115SaveFlow'

defineOptions({ name: 'JuyingResourceTab' })

const emit = defineEmits(['switch-resource-type'])

const props = defineProps({
  mediaType: { type: String, required: true },
  tmdbId: { type: [Number, String], required: true },
  resourceType: { type: String, required: true },
  season: { type: Number, default: null },
  title: { type: String, default: '' },
  year: { type: [String, Number], default: '' },
})

const loading = ref(false)
const tried = ref(false)
const resources = ref([])
const matchedMovie = ref(null)
const pan115Count = ref(0)
const magnetCount = ref(0)
const page = ref(1)
const pageSize = 8
const isMagnet = computed(() => props.resourceType === 'magnet')
const alternateCount = computed(() => isMagnet.value ? pan115Count.value : magnetCount.value)
const alternateLabel = computed(() => isMagnet.value ? '115' : '磁力')
const pagedResources = computed(() => {
  const start = (page.value - 1) * pageSize
  return resources.value.slice(start, start + pageSize)
})
const emptyDescription = computed(() => {
  if (!tried.value) return '尚未获取聚影资源'
  if (alternateCount.value) {
    return `当前没有聚影${isMagnet.value ? '磁力' : '115'}资源，但另一分类已有结果`
  }
  return isMagnet.value ? '聚影暂无可用磁力资源' : '聚影暂无可用115资源'
})

const switchResourceType = () => {
  emit('switch-resource-type', isMagnet.value ? '115' : 'magnet')
}

const errorMessage = (error, fallback) => {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  return detail?.message || error?.message || fallback
}

const fetchResources = async (refresh = false) => {
  if (loading.value) return
  loading.value = true
  tried.value = true
  try {
    const { data } = await juyingApi.getResources(
      props.mediaType,
      props.tmdbId,
      props.resourceType,
      props.season,
      refresh,
    )
    resources.value = Array.isArray(data?.list) ? data.list : []
    matchedMovie.value = data?.movie || null
    pan115Count.value = Number(data?.pan115_count || 0)
    magnetCount.value = Number(data?.magnet_count || 0)
    page.value = 1
  } catch (error) {
    resources.value = []
    matchedMovie.value = null
    pan115Count.value = 0
    magnetCount.value = 0
    ElMessage.error(errorMessage(error, '聚影资源加载失败'))
  } finally {
    loading.value = false
  }
}

const resolve = async (row) => {
  const { data } = await juyingApi.resolveResource(row.juying_resource_id || row.id)
  return data || {}
}

const folderName = () => {
  const suffix = String(props.year || '').trim()
  return suffix ? `${props.title} (${suffix})` : (props.title || '聚影资源')
}

const savePan115 = async (row) => {
  if (row.working) return
  row.working = true
  try {
    const access = await resolve(row)
    if (!access.share_link) throw new Error('聚影未返回115分享链接')
    let parentId = '0'
    try {
      const { data } = await pan115Api.getDefaultFolder()
      parentId = data?.folder_id || '0'
    } catch {}
    const { data } = await executePan115SaveToFolder({
      shareUrl: access.share_link,
      folderName: folderName(),
      parentId,
      receiveCode: access.access_code || '',
      tmdbId: Number(props.tmdbId) || null,
    })
    if (data?.success === false || data?.state === false) {
      throw new Error(data?.message || '转存失败')
    }
    ElMessage.success(data?.message || '聚影115资源转存成功')
  } catch (error) {
    ElMessage.error(errorMessage(error, '聚影115资源转存失败'))
  } finally {
    row.working = false
  }
}

const saveMagnet = async (row) => {
  if (row.working) return
  row.working = true
  try {
    const access = await resolve(row)
    if (!access.magnet) throw new Error('聚影未返回磁力链接')
    let folderId = '0'
    try {
      const { data } = await pan115Api.getOfflineDefaultFolder()
      folderId = data?.folder_id || '0'
    } catch {}
    await pan115Api.addOfflineTask(access.magnet, folderId, folderName())
    ElMessage.success('聚影磁力已添加到115离线任务')
  } catch (error) {
    ElMessage.error(errorMessage(error, '聚影磁力离线任务创建失败'))
  } finally {
    row.working = false
  }
}

const copyResource = async (row) => {
  if (row.copying) return
  row.copying = true
  try {
    const access = await resolve(row)
    const target = access.target || access.share_link || access.magnet
    if (!target) throw new Error('聚影资源链接为空')
    const suffix = access.access_code ? ` 提取码: ${access.access_code}` : ''
    await copyText(`${target}${suffix}`)
    ElMessage.success('资源链接已复制')
  } catch (error) {
    ElMessage.error(errorMessage(error, '复制聚影资源失败'))
  } finally {
    row.copying = false
  }
}

watch(
  () => `${props.mediaType}|${props.tmdbId}|${props.season || 0}|${props.resourceType}`,
  () => {
    resources.value = []
    matchedMovie.value = null
    pan115Count.value = 0
    magnetCount.value = 0
    tried.value = false
    fetchResources()
  },
)

onMounted(() => fetchResources())
</script>

<style scoped>
.resource-tools {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.match-info {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.hidden-tag {
  margin-left: 8px;
}
.pagination {
  margin-top: 16px;
  justify-content: center;
}
.alternate-resource-tip {
  text-align: center;
  padding-bottom: 20px;
}
.alternate-resource-tip :deep(.el-empty) {
  padding-bottom: 12px;
}
</style>
