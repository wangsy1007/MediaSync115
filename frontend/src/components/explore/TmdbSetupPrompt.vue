<template>
  <div class="tmdb-setup-prompt">
    <div class="prompt-icon" aria-hidden="true">
      <el-icon :size="40"><Key /></el-icon>
    </div>
    <h3>尚未配置 TMDB API Key</h3>
    <p class="prompt-desc">
      TMDB 榜单需要 API Key 才能拉取数据。填写后即可浏览热门电影、剧集等榜单，无需跳转设置页。
    </p>
    <el-form class="prompt-form" label-position="top" @submit.prevent="handleSave">
      <el-form-item label="API Key" required>
        <el-input
          v-model="apiKey"
          type="password"
          show-password
          placeholder="在 themoviedb.org 申请后粘贴"
          clearable
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="handleSave">保存并加载榜单</el-button>
        <el-button @click="goSettings">前往设置页</el-button>
      </el-form-item>
    </el-form>
    <p class="prompt-hint">
      申请地址：
      <a href="https://www.themoviedb.org/settings/api" target="_blank" rel="noopener noreferrer">
        themoviedb.org/settings/api
      </a>
    </p>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Key } from '@element-plus/icons-vue'
import { settingsApi } from '@/api'
import {
  TMDB_DEFAULT_BASE_URL,
  TMDB_DEFAULT_IMAGE_BASE_URL,
  TMDB_DEFAULT_LANGUAGE,
  TMDB_DEFAULT_REGION
} from '@/utils/tmdb'

const emit = defineEmits(['configured'])

const router = useRouter()
const apiKey = ref('')
const saving = ref(false)

const goSettings = () => {
  router.push('/settings')
}

const handleSave = async () => {
  const trimmedKey = String(apiKey.value || '').trim()
  if (!trimmedKey) {
    ElMessage.warning('请输入 TMDB API Key')
    return
  }

  saving.value = true
  try {
    await settingsApi.updateRuntime({
      tmdb_api_key: trimmedKey,
      tmdb_language: TMDB_DEFAULT_LANGUAGE,
      tmdb_region: TMDB_DEFAULT_REGION,
      tmdb_base_url: TMDB_DEFAULT_BASE_URL,
      tmdb_image_base_url: TMDB_DEFAULT_IMAGE_BASE_URL
    })
    ElMessage.success('TMDB 配置已保存')
    emit('configured')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'TMDB 配置保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped lang="scss">
.tmdb-setup-prompt {
  max-width: 520px;
  margin: 32px auto 48px;
  padding: 32px 28px;
  text-align: center;
  border: 1px solid var(--ms-glass-border, rgba(255, 255, 255, 0.08));
  border-radius: 20px;
  background: var(--ms-gradient-card, rgba(255, 255, 255, 0.03));

  .prompt-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 72px;
    height: 72px;
    margin-bottom: 16px;
    border-radius: 50%;
    background: rgba(45, 153, 255, 0.12);
    color: var(--el-color-primary);
  }

  h3 {
    margin: 0 0 12px;
    font-size: 20px;
    font-weight: 600;
  }

  .prompt-desc {
    margin: 0 0 24px;
    line-height: 1.6;
    color: var(--el-text-color-secondary);
    font-size: 14px;
  }

  .prompt-form {
    text-align: left;

    :deep(.el-form-item__label) {
      font-weight: 500;
    }
  }

  .prompt-hint {
    margin: 16px 0 0;
    font-size: 13px;
    color: var(--el-text-color-secondary);

    a {
      color: var(--el-color-primary);
      text-decoration: none;

      &:hover {
        text-decoration: underline;
      }
    }
  }
}
</style>
