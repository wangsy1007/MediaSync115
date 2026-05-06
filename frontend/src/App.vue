<template>
  <el-config-provider :locale="zhCn">
    <router-view v-if="isLoginRoute" v-slot="{ Component }">
      <transition name="page-fade" mode="out-in">
        <component :is="Component" />
      </transition>
    </router-view>

    <el-container v-else class="app-container" :class="{ 'is-compact': isCompact }">
      <el-aside v-if="!isCompact" width="240px" class="app-aside">
        <div
          class="logo"
          role="button"
          tabindex="0"
          @click="handleGoHome"
          @keydown.enter.prevent="handleGoHome"
          @keydown.space.prevent="handleGoHome"
        >
          <div class="logo-icon">
            <svg viewBox="0 0 48 48" class="brand-mark" aria-hidden="true">
              <rect x="4" y="4" width="40" height="40" rx="12" class="brand-shell" />
              <path
                d="M13 31V17h4.6l6.4 7.6 6.4-7.6H35v14h-4.3v-8l-5.9 6.8h-1.6L17.3 23v8H13Z"
                class="brand-letter"
              />
              <path d="M14 36h20" class="brand-track" />
            </svg>
          </div>
          <div class="logo-text">
            <div class="logo-heading">
              <span class="logo-title">MediaSync</span>
              <span class="logo-badge">115</span>
            </div>
            <span class="logo-subtitle">Search • Save • Sync</span>
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
          <el-menu-item index="/archive">
            <el-icon><FolderOpened /></el-icon>
            <span>归档刮削</span>
          </el-menu-item>
          <el-menu-item index="/strm">
            <el-icon><Link /></el-icon>
            <span>STRM</span>
          </el-menu-item>
          <el-menu-item index="/logs">
            <el-icon><Document /></el-icon>
            <span>日志</span>
          </el-menu-item>
          <el-menu-item index="/settings">
            <el-icon><Setting /></el-icon>
            <span>设置</span>
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
            <span>{{ appVersionLabel }}</span>
          </div>
          <el-button class="logout-btn" plain @click="handleLogout">退出登录</el-button>
        </div>
      </el-aside>

      <el-container class="app-content-container">
        <header v-if="isCompact" class="mobile-topbar">
          <div class="mobile-brand" role="button" tabindex="0" @click="mobileMenuOpen = true" @keydown.enter.prevent="mobileMenuOpen = true" @keydown.space.prevent="mobileMenuOpen = true">
            <svg viewBox="0 0 48 48" class="mobile-brand-icon" aria-hidden="true">
              <rect x="4" y="4" width="40" height="40" rx="12" class="brand-shell" />
              <path
                d="M13 31V17h4.6l6.4 7.6 6.4-7.6H35v14h-4.3v-8l-5.9 6.8h-1.6L17.3 23v8H13Z"
                class="brand-letter"
              />
              <path d="M14 36h20" class="brand-track" />
            </svg>
            <span class="mobile-brand-text">MediaSync 115</span>
          </div>
        </header>

        <el-main class="app-main">
          <router-view v-slot="{ Component }">
            <transition name="page-fade" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </el-main>
      </el-container>
    </el-container>

    <el-drawer
      v-model="mobileMenuOpen"
      direction="ltr"
      :with-header="false"
      size="280px"
      class="mobile-nav-drawer"
    >
      <div class="mobile-nav-body">
        <div class="logo" role="button" tabindex="0" @click="handleDrawerGoHome">
          <div class="logo-icon">
            <svg viewBox="0 0 48 48" class="brand-mark" aria-hidden="true">
              <rect x="4" y="4" width="40" height="40" rx="12" class="brand-shell" />
              <path
                d="M13 31V17h4.6l6.4 7.6 6.4-7.6H35v14h-4.3v-8l-5.9 6.8h-1.6L17.3 23v8H13Z"
                class="brand-letter"
              />
              <path d="M14 36h20" class="brand-track" />
            </svg>
          </div>
          <div class="logo-text">
            <div class="logo-heading">
              <span class="logo-title">MediaSync</span>
              <span class="logo-badge">115</span>
            </div>
            <span class="logo-subtitle">Search • Save • Sync</span>
          </div>
        </div>
        <el-menu :default-active="activeMenu" router @select="handleDrawerNavigate">
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
          <el-menu-item index="/archive">
            <el-icon><FolderOpened /></el-icon>
            <span>归档刮削</span>
          </el-menu-item>
          <el-menu-item index="/strm">
            <el-icon><Link /></el-icon>
            <span>STRM</span>
          </el-menu-item>
          <el-menu-item index="/logs">
            <el-icon><Document /></el-icon>
            <span>日志</span>
          </el-menu-item>
          <el-menu-item index="/settings">
            <el-icon><Setting /></el-icon>
            <span>设置</span>
          </el-menu-item>
        </el-menu>
        <div class="aside-footer">
          <el-radio-group v-model="themeMode" size="small" class="theme-mode-group mobile-drawer-theme-mode">
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
            <span>{{ appVersionLabel }}</span>
          </div>
          <el-button class="logout-btn" plain @click="handleLogout">退出登录</el-button>
        </div>
      </div>
    </el-drawer>
  </el-config-provider>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { authApi, settingsApi } from '@/api'
import { resetAuthSessionCache } from '@/router'
import { formatBeijingDateTime } from '@/utils/timezone'
import {
  Search,
  Star,
  Download,
  FolderOpened,
  Link,
  Document,
  Setting,
  Monitor,
  Sunny,
  MoonNight
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const THEME_STORAGE_KEY = 'ms-theme-mode'
const supportsMatchMedia = typeof window !== 'undefined' && typeof window.matchMedia === 'function'

const themeMode = ref(getInitialThemeMode())
const systemDark = ref(supportsMatchMedia ? window.matchMedia('(prefers-color-scheme: dark)').matches : true)
const beijingNow = ref(formatBeijingDateTime(new Date()))
const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
const mobileMenuOpen = ref(false)
const appVersionLabel = ref('v1.1.3')
const isLoginRoute = computed(() => route.path === '/login')

const activeMenu = computed(() => {
  if (route.path.startsWith('/explore/tmdb')) return '/explore/tmdb'
  if (route.path.startsWith('/explore/douban')) return '/explore/douban'
  return route.path
})

const resolvedTheme = computed(() => {
  if (themeMode.value === 'light' || themeMode.value === 'dark') return themeMode.value
  return systemDark.value ? 'dark' : 'light'
})

const isCompact = computed(() => viewportWidth.value <= 1024)

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

function handleDrawerGoHome() {
  mobileMenuOpen.value = false
  handleGoHome()
}

function handleDrawerNavigate() {
  mobileMenuOpen.value = false
}

async function handleLogout() {
  try {
    await authApi.logout()
  } catch {
    // ignore logout failures
  } finally {
    resetAuthSessionCache()
    mobileMenuOpen.value = false
    ElMessage.success('已退出登录')
    router.replace('/login')
  }
}

function handleResize() {
  viewportWidth.value = window.innerWidth
}

async function fetchAppVersion() {
  try {
    const { data } = await settingsApi.getAppInfo()
    const version = String(data?.current_version || '').trim()
    if (version) {
      appVersionLabel.value = version.startsWith('v') ? version : `v${version}`
    }
  } catch {
    // ignore version fetch failures
  }
}

watch(themeMode, (value) => {
  window.localStorage.setItem(THEME_STORAGE_KEY, value)
})

watch(resolvedTheme, (value) => {
  applyTheme(value)
}, { immediate: true })

watch(() => route.path, () => {
  mobileMenuOpen.value = false
})

watch(isCompact, (compact) => {
  if (!compact) {
    mobileMenuOpen.value = false
  }
})

onMounted(() => {
  fetchAppVersion()
  if (supportsMatchMedia) {
    systemThemeMedia = window.matchMedia('(prefers-color-scheme: dark)')
    systemThemeMedia.addEventListener('change', handleSystemThemeChange)
  }

  window.addEventListener('resize', handleResize)

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
  window.removeEventListener('resize', handleResize)
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

.app-content-container {
  min-width: 0;
  flex-direction: column;
}

.app-aside {
  background: var(--ms-glass-bg-heavy);
  border-right: 1px solid var(--ms-glass-border);
  /* 性能优化：条件启用 backdrop-filter */
  @supports (backdrop-filter: blur(20px)) {
    backdrop-filter: blur(20px);
  }
  display: flex;
  flex-direction: column;
  position: relative;
  /* CSS Containment 优化 */
  contain: layout style;

  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 200px;
    background: radial-gradient(ellipse at 50% 0%, rgba(45, 153, 255, 0.22) 0%, transparent 70%);
    pointer-events: none;
    /* 减少重绘 */
    will-change: transform;
  }

  .logo {
    height: 72px;
    display: flex;
    align-items: center;
    padding: 0 16px;
    gap: 12px;
    border-bottom: 1px solid var(--ms-glass-border);
    position: relative;
    cursor: pointer;

    &:focus-visible {
      outline: 2px solid var(--ms-accent-primary);
      outline-offset: -2px;
    }

    .logo-icon {
      width: 46px;
      height: 46px;
      display: flex;
      align-items: center;
      justify-content: center;
      background:
        radial-gradient(circle at 30% 25%, rgba(255, 255, 255, 0.2), transparent 45%),
        linear-gradient(145deg, #1f78ff 0%, #0f4cb7 100%);
      border-radius: 14px;
      box-shadow: 0 14px 30px rgba(12, 62, 148, 0.24);

      .brand-mark {
        width: 32px;
        height: 32px;
      }

      .brand-shell {
        fill: rgba(255, 255, 255, 0.12);
      }

      .brand-letter {
        fill: #fff;
      }

      .brand-track {
        fill: none;
        stroke: rgba(255, 255, 255, 0.72);
        stroke-width: 2.6;
        stroke-linecap: round;
      }
    }

    .logo-text {
      display: flex;
      flex-direction: column;
      gap: 2px;

      .logo-heading {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .logo-title {
        font-size: 20px;
        font-weight: 800;
        color: var(--ms-text-primary);
        letter-spacing: -0.7px;
      }

      .logo-badge {
        font-size: 11px;
        font-weight: 800;
        padding: 3px 7px;
        background: rgba(43, 123, 255, 0.1);
        color: var(--ms-accent-primary);
        border: 1px solid rgba(43, 123, 255, 0.18);
        border-radius: 999px;
      }

      .logo-subtitle {
        font-size: 11px;
        font-weight: 600;
        color: var(--ms-text-muted);
        letter-spacing: 0.04em;
        text-transform: uppercase;
        white-space: nowrap;
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
      margin-bottom: 12px;

      span {
        font-size: 12px;
        color: var(--ms-text-muted);
        font-weight: 500;
      }
    }

    .logout-btn {
      width: 100%;
    }
  }
}

.mobile-topbar {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 64px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--ms-glass-border);
  background: var(--ms-glass-bg-heavy);
  /* 性能优化：条件启用 backdrop-filter */
  @supports (backdrop-filter: blur(18px)) {
    backdrop-filter: blur(18px);
  }
  contain: layout style;

  .mobile-brand {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    font-size: 16px;
    font-weight: 700;
    color: var(--ms-text-primary);
    white-space: nowrap;
    cursor: pointer;
    max-width: 100%;

    .mobile-brand-icon {
      width: 30px;
      height: 30px;
      flex: 0 0 auto;
      filter: drop-shadow(0 10px 18px rgba(17, 79, 179, 0.18));
    }

    .brand-shell {
      fill: rgba(43, 123, 255, 0.12);
    }

    .brand-letter {
      fill: var(--ms-accent-primary);
    }

    .brand-track {
      fill: none;
      stroke: rgba(80, 137, 224, 0.75);
      stroke-width: 2.6;
      stroke-linecap: round;
    }

    .mobile-brand-text {
      white-space: nowrap;
    }
  }
}

.app-main {
  background: var(--ms-bg-primary);
  padding: 24px 32px;
  overflow-y: auto;
  position: relative;

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

.mobile-nav-body {
  height: 100%;
  display: flex;
  flex-direction: column;

  .logo {
    height: 68px;
    display: flex;
    align-items: center;
    padding: 0 12px;
    gap: 12px;
    border-bottom: 1px solid var(--ms-glass-border);
    cursor: pointer;
  }

  .logo-icon {
    width: 44px;
    height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
    background:
      radial-gradient(circle at 30% 25%, rgba(255, 255, 255, 0.2), transparent 45%),
      linear-gradient(145deg, #1f78ff 0%, #0f4cb7 100%);
    border-radius: 14px;
    box-shadow: 0 14px 30px rgba(12, 62, 148, 0.24);

    .brand-mark {
      width: 30px;
      height: 30px;
    }

    .brand-shell {
      fill: rgba(255, 255, 255, 0.12);
    }

    .brand-letter {
      fill: #fff;
    }

    .brand-track {
      fill: none;
      stroke: rgba(255, 255, 255, 0.72);
      stroke-width: 2.6;
      stroke-linecap: round;
    }
  }

  .logo-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .logo-heading {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .logo-title {
    font-size: 18px;
    font-weight: 800;
    color: var(--ms-text-primary);
    letter-spacing: -0.6px;
  }

  .logo-badge {
    font-size: 11px;
    font-weight: 800;
    padding: 3px 7px;
    background: rgba(43, 123, 255, 0.1);
    color: var(--ms-accent-primary);
    border: 1px solid rgba(43, 123, 255, 0.18);
    border-radius: 999px;
  }

  .logo-subtitle {
    font-size: 11px;
    font-weight: 600;
    color: var(--ms-text-muted);
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .el-menu {
    flex: 1;
    border-right: none;
    background: transparent;
    padding: 10px 0;
  }

  .aside-footer {
    padding: 14px 12px;
    border-top: 1px solid var(--ms-glass-border);

    .mobile-drawer-theme-mode {
      width: 100%;
      margin-bottom: 12px;

      .el-radio-button {
        flex: 1;
      }

      .el-radio-button__inner {
        width: 100%;
      }
    }
  }
}

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

@media (max-width: 1024px) {
  .mobile-topbar {
    .mobile-brand {
      min-width: 0;
    }
  }

  .app-main {
    padding: 20px;

    &::before {
      width: 80%;
      right: -36%;
    }

    &::after {
      width: 70%;
      left: -25%;
    }
  }
}

@media (max-width: 768px) {
  .mobile-topbar {
    min-height: 56px;
    padding: 10px;

    .mobile-brand {
      font-size: 15px;
      max-width: 100%;
      overflow: hidden;
      padding: 4px 8px;
      border-radius: 12px;

      .mobile-brand-icon {
        width: 28px;
        height: 28px;
      }

      .mobile-brand-text {
        overflow: hidden;
        text-overflow: ellipsis;
      }
    }
  }

  .app-main {
    padding: 14px 12px;
  }
}
</style>
