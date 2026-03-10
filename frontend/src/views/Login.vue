<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <h1>MediaSync 115</h1>
        <p>登录后访问系统功能</p>
      </div>

      <el-form @submit.prevent="handleLogin" label-position="top">
        <el-form-item label="账号">
          <el-input v-model="form.username" placeholder="请输入账号" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="请输入密码"
            autocomplete="current-password"
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loggingIn" class="login-submit" @click="handleLogin">
            登录
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-tip">
        默认账号：<code>admin</code>
        默认密码：<code>password</code>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api'
import { resetAuthSessionCache } from '@/router'

const router = useRouter()
const route = useRoute()
const loggingIn = ref(false)
const form = reactive({
  username: 'admin',
  password: 'password'
})

const handleLogin = async () => {
  const username = String(form.username || '').trim()
  const password = String(form.password || '')
  if (!username) {
    ElMessage.warning('请输入账号')
    return
  }
  if (!password) {
    ElMessage.warning('请输入密码')
    return
  }

  loggingIn.value = true
  try {
    await authApi.login({ username, password })
    resetAuthSessionCache()
    ElMessage.success('登录成功')
    const redirect = String(route.query.redirect || '/').trim() || '/'
    await router.replace(redirect)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '登录失败')
  } finally {
    loggingIn.value = false
  }
}
</script>

<style scoped lang="scss">
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at top, rgba(24, 144, 255, 0.14), transparent 35%),
    linear-gradient(180deg, rgba(16, 24, 40, 0.02), rgba(16, 24, 40, 0.08));

  .login-card {
    width: min(420px, 100%);
    padding: 28px;
    border-radius: 20px;
    border: 1px solid var(--ms-border-color);
    background: var(--ms-glass-bg);
    box-shadow: 0 20px 60px rgba(15, 23, 42, 0.14);
  }

  .login-brand {
    margin-bottom: 20px;

    h1 {
      margin: 0 0 8px;
      font-size: 28px;
    }

    p {
      margin: 0;
      color: var(--ms-text-secondary);
    }
  }

  .login-submit {
    width: 100%;
  }

  .login-tip {
    margin-top: 12px;
    color: var(--ms-text-secondary);
    font-size: 13px;

    code {
      padding: 2px 6px;
      border-radius: 6px;
      background: rgba(15, 23, 42, 0.08);
    }
  }
}
</style>
