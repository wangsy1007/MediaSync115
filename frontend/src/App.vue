<template>
  <el-config-provider :locale="zhCn">
    <el-container class="app-container">
      <el-aside width="240px" class="app-aside">
        <div
          class="logo"
          role="button"
          tabindex="0"
          @click="handleGoHome"
          @keydown.enter.prevent="handleGoHome"
          @keydown.space.prevent="handleGoHome"
        >
          <div class="logo-icon">
            <el-icon :size="24"><VideoCamera /></el-icon>
          </div>
          <div class="logo-text">
            <span class="logo-title">MediaSync</span>
            <span class="logo-badge">115</span>
          </div>
        </div>
        <el-menu
          :default-active="activeMenu"
          router
        >
          <el-sub-menu index="/explore">
            <template #title>
              <el-icon><Search /></el-icon>
              <span>探索</span>
            </template>
            <el-menu-item index="/explore/douban">豆瓣榜单</el-menu-item>
            <el-menu-item index="/explore/tmdb">TMDB榜单</el-menu-item>
          </el-sub-menu>
          <el-menu-item index="/subscriptions">
            <el-icon><Star /></el-icon>
            <span>订阅</span>
          </el-menu-item>
          <el-menu-item index="/downloads">
            <el-icon><Download /></el-icon>
            <span>离线下载</span>
          </el-menu-item>
          <el-menu-item index="/logs">
            <el-icon><Document /></el-icon>
            <span>日志</span>
          </el-menu-item>
          <el-menu-item index="/settings">
            <el-icon><Setting /></el-icon>
            <span>设置</span>
          </el-menu-item>
          <el-menu-item index="/scheduler">
            <el-icon><Clock /></el-icon>
            <span>调度中心</span>
          </el-menu-item>
          <el-menu-item index="/workflow">
            <el-icon><Connection /></el-icon>
            <span>工作流</span>
          </el-menu-item>
        </el-menu>
        <div class="aside-footer">
          <el-radio-group v-model="themeMode" size="small" class="theme-mode-group">
            <el-radio-button label="auto">
              <el-icon><Monitor /></el-icon>
            </el-radio-button>
            <el-radio-button label="light">
              <el-icon><Sunny /></el-icon>
            </el-radio-button>
            <el-radio-button label="dark">
              <el-icon><MoonNight /></el-icon>
            </el-radio-button>
          </el-radio-group>
          <div class="timezone-info">
            <span class="timezone-label">北京时间</span>
            <span class="timezone-value">{{ beijingNow }}</span>
          </div>
          <div class="version-info">
            <span>v1.0.0</span>
          </div>
        </div>
      </el-aside>
      <el-main class="app-main">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-config-provider>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { formatBeijingDateTime } from '@/utils/timezone'

const route = useRoute()
const router = useRouter()
const THEME_STORAGE_KEY = 'ms-theme-mode'
const supportsMatchMedia = typeof window !== 'undefined' && typeof window.matchMedia === 'function'

const themeMode = ref(getInitialThemeMode())
const systemDark = ref(supportsMatchMedia ? window.matchMedia('(prefers-color-scheme: dark)').matches : true)
const beijingNow = ref(formatBeijingDateTime(new Date()))

const activeMenu = computed(() => {
  if (route.path.startsWith('/explore/tmdb')) return '/explore/tmdb'
  if (route.path.startsWith('/explore/douban')) return '/explore/douban'
  return route.path
})

const resolvedTheme = computed(() => {
  if (themeMode.value === 'light' || themeMode.value === 'dark') return themeMode.value
  return systemDark.value ? 'dark' : 'light'
})

let systemThemeMedia = null
let clockTimer = null

function getInitialThemeMode() {
  if (typeof window === 'undefined') return 'auto'
  const saved = window.localStorage.getItem(THEME_STORAGE_KEY)
  if (saved === 'light' || saved === 'dark' || saved === 'auto') return saved
  return 'auto'
}

function applyTheme(mode) {
  document.documentElement.setAttribute('data-theme', mode)
  document.documentElement.style.colorScheme = mode
}

function handleSystemThemeChange(event) {
  systemDark.value = !!event.matches
}

function tickBeijingClock() {
  beijingNow.value = formatBeijingDateTime(new Date(), {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

function handleGoHome() {
  router.push('/')
}

watch(themeMode, (value) => {
  window.localStorage.setItem(THEME_STORAGE_KEY, value)
})

watch(resolvedTheme, (value) => {
  applyTheme(value)
}, { immediate: true })

onMounted(() => {
  if (supportsMatchMedia) {
    systemThemeMedia = window.matchMedia('(prefers-color-scheme: dark)')
    systemThemeMedia.addEventListener('change', handleSystemThemeChange)
  }

  tickBeijingClock()
  clockTimer = window.setInterval(tickBeijingClock, 1000)
})

onBeforeUnmount(() => {
  if (systemThemeMedia) {
    systemThemeMedia.removeEventListener('change', handleSystemThemeChange)
  }
  if (clockTimer) {
    window.clearInterval(clockTimer)
  }
})
</script>

<style lang="scss">
html, body, #app {
  margin: 0;
  padding: 0;
  height: 100%;
  background: var(--ms-bg-primary);
  color: var(--ms-text-primary);
  font-family: 'SF Pro Display', 'Segoe UI', 'PingFang SC', sans-serif;
}

.app-container {
  height: 100%;
}

.app-aside {
  background: var(--ms-glass-bg-heavy);
  border-right: 1px solid var(--ms-glass-border);
  backdrop-filter: blur(20px);
  display: flex;
  flex-direction: column;
  position: relative;
  
  // 装饰性光效
  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 200px;
    background: radial-gradient(ellipse at 50% 0%, rgba(45, 153, 255, 0.22) 0%, transparent 70%);
    pointer-events: none;
  }

  .logo {
    height: 72px;
    display: flex;
    align-items: center;
    padding: 0 20px;
    gap: 12px;
    border-bottom: 1px solid var(--ms-glass-border);
    position: relative;
    cursor: pointer;

    &:focus-visible {
      outline: 2px solid var(--ms-accent-primary);
      outline-offset: -2px;
    }
    
    .logo-icon {
      width: 42px;
      height: 42px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--ms-gradient-primary);
      border-radius: 12px;
      color: #fff;
      box-shadow: var(--ms-shadow-md);
    }
    
    .logo-text {
      display: flex;
      align-items: baseline;
      gap: 6px;
      
      .logo-title {
        font-size: 20px;
        font-weight: 700;
        background: linear-gradient(120deg, var(--ms-text-primary) 0%, var(--ms-text-secondary) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -0.5px;
      }
      
      .logo-badge {
        font-size: 12px;
        font-weight: 700;
        padding: 2px 6px;
        background: var(--ms-gradient-soft);
        color: var(--ms-accent-primary);
        border-radius: 4px;
      }
    }
  }

  .el-menu {
    flex: 1;
    border-right: none;
    background: transparent;
    padding: 16px 0;
  }
  
  .aside-footer {
    padding: 16px 20px;
    border-top: 1px solid var(--ms-glass-border);

    .theme-mode-group {
      width: 100%;
      margin-bottom: 12px;

      .el-radio-button {
        flex: 1;
      }

      .el-radio-button__inner {
        width: 100%;
      }
    }

    .timezone-info {
      margin-bottom: 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;

      .timezone-label {
        color: var(--ms-text-muted);
      }

      .timezone-value {
        color: var(--ms-text-secondary);
        font-variant-numeric: tabular-nums;
      }
    }
    
    .version-info {
      display: flex;
      align-items: center;
      justify-content: center;
      
      span {
        font-size: 12px;
        color: var(--ms-text-muted);
        font-weight: 500;
      }
    }
  }
}

.app-main {
  background: var(--ms-bg-primary);
  padding: 24px 32px;
  overflow-y: auto;
  position: relative;
  
  // 背景装饰
  &::before {
    content: '';
    position: fixed;
    top: -50%;
    right: -20%;
    width: 60%;
    height: 100%;
    background: radial-gradient(ellipse, rgba(36, 137, 255, 0.16) 0%, transparent 60%);
    pointer-events: none;
  }
  
  &::after {
    content: '';
    position: fixed;
    bottom: -30%;
    left: -10%;
    width: 50%;
    height: 80%;
    background: radial-gradient(ellipse, rgba(116, 188, 255, 0.15) 0%, transparent 60%);
    pointer-events: none;
  }
}

// 页面切换动画
.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.page-fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.page-fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
