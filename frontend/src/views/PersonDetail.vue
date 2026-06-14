<template>
  <div class="person-detail-page" v-loading="loading">
    <template v-if="person">
      <div class="back-button-container">
        <el-button text @click="handleBack">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
      </div>

      <div class="detail-header">
        <div class="avatar">
          <img v-if="person.profile_path" :src="getProfileUrl(person.profile_path)" :alt="person.name" />
          <div v-else class="avatar-placeholder">{{ person.name?.slice(0, 1) || '?' }}</div>
        </div>
        <div class="info">
          <h1>{{ person.name }}</h1>
          <div class="meta">
            <span v-if="person.known_for_department">{{ getDepartmentLabel(person.known_for_department) }}</span>
            <span v-if="person.birthday">生于 {{ person.birthday }}</span>
            <span v-if="person.place_of_birth">{{ person.place_of_birth }}</span>
          </div>
          <p class="biography" v-if="person.biography">{{ person.biography }}</p>
          <el-button
            :type="isFollowed ? 'success' : 'primary'"
            :loading="toggling"
            @click="handleToggleFollow"
          >
            {{ isFollowed ? '已关注（点击取消）' : '关注演职员' }}
          </el-button>
        </div>
      </div>

      <div class="credits-section">
        <h3>作品列表</h3>
        <VirtualList
          v-if="credits.length"
          :items="credits"
          :item-height="360"
          class="credits-virtual-list"
        >
          <template #default="{ item: credit }">
            <el-card
              :key="`${credit.media_type}-${credit.tmdb_id}`"
              class="credit-card"
              shadow="hover"
              @click="goToWork(credit)"
            >
              <div class="poster">
                <img
                  v-if="credit.poster_path"
                  :src="getProfileUrl(credit.poster_path)"
                  :alt="credit.title"
                  loading="lazy"
                  decoding="async"
                />
                <div v-else class="poster-placeholder">暂无海报</div>
              </div>
              <div class="credit-info">
                <div class="title">{{ credit.title }}</div>
                <div class="meta">
                  <el-tag size="small" :type="credit.media_type === 'movie' ? 'primary' : 'success'">
                    {{ credit.media_type === 'movie' ? '电影' : '电视剧' }}
                  </el-tag>
                  <span>{{ credit.release_date || credit.first_air_date || '-' }}</span>
                </div>
                <div class="role" v-if="credit.character || credit.job">
                  {{ credit.character || credit.job }}
                </div>
              </div>
            </el-card>
          </template>
        </VirtualList>
        <el-empty v-else description="暂无作品" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { personFollowApi, searchApi } from '@/api'
import { getDepartmentLabel, getTmdbProfileUrl } from '@/utils/tmdbProfile'
import VirtualList from '@/components/VirtualList.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const toggling = ref(false)
const person = ref(null)
const followedPersonIds = ref(new Set())

const personId = computed(() => Number(route.params.id || 0))
const isFollowed = computed(() => followedPersonIds.value.has(String(personId.value)))
const credits = computed(() => {
  const rows = person.value?.credits
  return Array.isArray(rows) ? rows : []
})

const getProfileUrl = (path) => getTmdbProfileUrl(path)

const refreshFollowStatus = async () => {
  try {
    const { data } = await personFollowApi.getStatusMap()
    const map = data?.person_id_map || {}
    followedPersonIds.value = new Set(Object.keys(map))
  } catch {
    followedPersonIds.value = new Set()
  }
}

const fetchPerson = async () => {
  if (!personId.value) return
  loading.value = true
  try {
    const { data } = await searchApi.getPerson(personId.value)
    person.value = data
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载演职员详情失败')
  } finally {
    loading.value = false
  }
}

const handleToggleFollow = async () => {
  if (!person.value) return
  toggling.value = true
  try {
    const { data } = await personFollowApi.toggle({
      tmdb_person_id: person.value.tmdb_person_id || personId.value,
      name: person.value.name,
      profile_path: person.value.profile_path,
      known_for_department: person.value.known_for_department
    })
    if (data.followed) {
      followedPersonIds.value.add(String(personId.value))
      ElMessage.success('已关注')
    } else {
      followedPersonIds.value.delete(String(personId.value))
      ElMessage.success('已取消关注')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '操作失败')
  } finally {
    toggling.value = false
  }
}

const goToWork = (credit) => {
  const path = credit.media_type === 'tv' ? `/tv/${credit.tmdb_id}` : `/movie/${credit.tmdb_id}`
  router.push({ path, query: { from: route.fullPath } })
}

const handleBack = () => {
  const from = String(route.query.from || '').trim()
  router.push(from || '/person-follows')
}

onMounted(async () => {
  await Promise.all([fetchPerson(), refreshFollowStatus()])
})
</script>

<style scoped lang="scss">
.person-detail-page {
  .back-button-container {
    margin-bottom: 12px;
  }

  .detail-header {
    display: flex;
    gap: 24px;
    margin-bottom: 28px;

    .avatar {
      width: 180px;
      height: 180px;
      border-radius: 16px;
      overflow: hidden;
      flex-shrink: 0;
      background: var(--ms-surface-muted);

      img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
    }

    .avatar-placeholder {
      width: 100%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 48px;
      color: var(--ms-text-muted);
    }

    .info {
      flex: 1;

      h1 {
        margin: 0 0 10px;
      }

      .meta {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        color: var(--ms-text-muted);
        font-size: 13px;
        margin-bottom: 12px;
      }

      .biography {
        color: var(--ms-text-secondary);
        line-height: 1.6;
        margin-bottom: 16px;
      }
    }
  }

  .credits-section {
    h3 {
      margin: 0 0 14px;
    }
  }

  .credits-virtual-list {
    height: min(70vh, 960px);
  }

  .credits-virtual-list :deep(.virtual-list-item) {
    padding-bottom: 12px;
  }

  .credit-card {
    cursor: pointer;

    .poster {
      aspect-ratio: 2 / 3;
      overflow: hidden;
      border-radius: 8px;
      background: var(--ms-surface-muted);

      img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
    }

    .poster-placeholder {
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--ms-text-muted);
      font-size: 12px;
    }

    .credit-info {
      margin-top: 10px;

      .title {
        font-weight: 600;
        margin-bottom: 6px;
      }

      .meta {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--ms-text-muted);
        font-size: 12px;
        margin-bottom: 4px;
      }

      .role {
        color: var(--ms-text-muted);
        font-size: 12px;
      }
    }
  }
}
</style>
