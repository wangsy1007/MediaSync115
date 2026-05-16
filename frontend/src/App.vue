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
          @select="handleSideMenuSelect"
        >
          <el-sub-menu index="explore-group">
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
        <!-- 手机端顶部标题栏 -->
        <header v-if="isCompact" class="compact-topbar">
          <div class="compact-brand" @click="handleGoHome">
            <svg viewBox="0 0 48 48" class="compact-brand-icon" aria-hidden="true">
              <rect x="4" y="4" width="40" height="40" rx="12" class="brand-shell" />
              <path d="M13 31V17h4.6l6.4 7.6 6.4-7.6H35v14h-4.3v-8l-5.9 6.8h-1.6L17.3 23v8H13Z" class="brand-letter" />
              <path d="M14 36h20" class="brand-track" />
            </svg>
            <span class="compact-brand-text">MediaSync</span>
          </div>
        </header>
        <el-main class="app-main" :class="{ 'has-dock': isCompact }">
          <router-view v-slot="{ Component, route: currentRoute }">
            <transition name="page-fade" mode="out-in">
              <component :is="Component" :key="currentRoute.fullPath" />
            </transition>
          </router-view>
        </el-main>
      </el-container>
    </el-container>

    <!-- 手机端底部 Dock 导航栏 -->
    <nav v-if="isCompact" class="mobile-dock" :class="{ 'dock-visible': isCompact }">
      <button
        v-for="tab in dockTabs"
        :key="tab.key"
        class="dock-tab"
        :class="{ active: tab.active }"
        @click="handleDockTab(tab)"
        :aria-label="tab.label"
      >
        <el-icon class="dock-icon"><component :is="tab.icon" /></el-icon>
        <span class="dock-label">{{ tab.label }}</span>
      </button>
    </nav>

    <!-- 手机端「我的」操作面板 -->
    <teleport to="body">
      <transition name="action-sheet">
        <div v-if="showMoreMenu" class="more-overlay" @click.self="showMoreMenu = false">
          <div class="more-sheet">
            <div class="more-sheet-header">
              <span class="more-sheet-title">更多操作</span>
            </div>
            <div class="more-sheet-body">
              <button class="more-item" @click="handleMoreNav('/settings')">
                <el-icon><Setting /></el-icon>
                <span>设置</span>
              </button>
              <button class="more-item" @click="handleMoreNav('/strm')">
                <el-icon><Link /></el-icon>
                <span>STRM 管理</span>
              </button>
              <button class="more-item" @click="handleMoreNav('/logs')">
                <el-icon><Document /></el-icon>
                <span>日志</span>
              </button>
              <button class="more-item" @click="handleMoreNav('/scheduler')">
                <el-icon><Clock /></el-icon>
                <span>调度任务</span>
              </button>
              <button class="more-item" @click="handleMoreNav('/workflow')">
                <el-icon><Operation /></el-icon>
                <span>工作流</span>
              </button>
            </div>
            <div class="more-sheet-footer">
              <div class="more-theme-row">
                <span class="more-theme-label">主题</span>
                <el-radio-group v-model="themeMode" size="small">
                  <el-radio-button label="auto">自动</el-radio-button>
                  <el-radio-button label="light">浅色</el-radio-button>
                  <el-radio-button label="dark">深色</el-radio-button>
                </el-radio-group>
              </div>
              <button class="more-item more-logout" @click="handleMoreLogout">
                <el-icon><SwitchButton /></el-icon>
                <span>退出登录</span>
              </button>
            </div>
            <button class="more-cancel" @click="showMoreMenu = false">取消</button>
          </div>
        </div>
      </transition>
    </teleport>

    <!-- 手机端「发现」探索页选择面板 -->
    <teleport to="body">
      <transition name="action-sheet">
        <div v-if="showExploreMenu" class="more-overlay" @click.self="showExploreMenu = false">
          <div class="more-sheet">
            <div class="more-sheet-header">
              <span class="more-sheet-title">选择探索页</span>
            </div>
            <div class="more-sheet-body">
              <button
                class="more-item"
                :class="{ 'more-item-active': lastExplorePage === '/explore/douban' }"
                @click="handleExploreNav('/explore/douban')"
              >
                <el-icon><Search /></el-icon>
                <span>豆瓣榜单</span>
              </button>
              <button
                class="more-item"
                :class="{ 'more-item-active': lastExplorePage === '/explore/tmdb' }"
                @click="handleExploreNav('/explore/tmdb')"
              >
                <el-icon><Search /></el-icon>
                <span>TMDB 榜单</span>
              </button>
            </div>
            <button class="more-cancel" @click="showExploreMenu = false">取消</button>
          </div>
        </div>
      </transition>
    </teleport>
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
  MoonNight,
  Clock,
  Operation,
  SwitchButton
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const THEME_STORAGE_KEY = 'ms-theme-mode'
const supportsMatchMedia = typeof window !== 'undefined' && typeof window.matchMedia === 'function'

const themeMode = ref(getInitialThemeMode())
const systemDark = ref(supportsMatchMedia ? window.matchMedia('(prefers-color-scheme: dark)').matches : true)
const beijingNow = ref(formatBeijingDateTime(new Date()))
const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
const showMoreMenu = ref(false)
const showExploreMenu = ref(false)
const lastExplorePage = ref('/explore/douban')
const appVersionLabel = ref('v1.1.30')
const isLoginRoute = computed(() => route.path === '/login')

const activeMenu = computed(() => {
  // 处理首页重定向
  if (route.path === '/' || route.path === '/search') return '/explore/douban'
  if (route.path.startsWith('/explore/tmdb')) return '/explore/tmdb'
  if (route.path.startsWith('/explore/douban')) return '/explore/douban'
  // 处理详情页等其他页面，返回最近访问的探索页面
  if (route.path.startsWith('/movie/') || route.path.startsWith('/tv/') || route.path.startsWith('/douban/')) {
    return '/explore/douban'
  }
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
  const homePath = route.path.startsWith('/explore/tmdb') ? '/explore/tmdb' : '/explore/douban'
  router.replace({ path: homePath, query: {} })
}

/** 侧栏菜单导航（不用 el-menu router，避免子菜单 index 与 /explore 路由冲突） */
function handleSideMenuSelect(index) {
  const path = String(index || '').trim()
  if (!path.startsWith('/')) return
  if (path === route.path) return
  router.push(path).catch(() => {})
}

const dockTabs = computed(() => {
  const path = route.path
  return [
    { key: 'explore', label: '发现', icon: Search, route: lastExplorePage.value, active: path === '/' || path === '/search' || path.startsWith('/explore') || path.startsWith('/movie/') || path.startsWith('/tv/') || path.startsWith('/douban/') || showExploreMenu.value },
    { key: 'subscriptions', label: '订阅', icon: Star, route: '/subscriptions', active: path.startsWith('/subscriptions') },
    { key: 'downloads', label: '下载', icon: Download, route: '/downloads', active: path.startsWith('/downloads') },
    { key: 'archive', label: '归档', icon: FolderOpened, route: '/archive', active: path.startsWith('/archive') },
    { key: 'more', label: '我的', icon: Setting, route: null, active: showMoreMenu.value }
  ]
})

function handleDockTab(tab) {
  showExploreMenu.value = false
  showMoreMenu.value = false
  if (tab.key === 'more') {
    showMoreMenu.value = true
  } else if (tab.key === 'explore') {
    if (route.path.startsWith('/explore')) {
      showExploreMenu.value = true
    } else {
      router.push(lastExplorePage.value)
    }
  } else {
    router.push(tab.route)
  }
}

function handleExploreNav(path) {
  showExploreMenu.value = false
  lastExplorePage.value = path
  router.push(path)
}

function handleMoreNav(path) {
  showMoreMenu.value = false
  router.push(path)
}

async function handleMoreLogout() {
  showMoreMenu.value = false
  await handleLogout()
}

async function handleLogout() {
  try {
    await authApi.logout()
  } catch {
    // ignore logout failures
  } finally {
    resetAuthSessionCache()
    showMoreMenu.value = false
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
  showMoreMenu.value = false
  showExploreMenu.value = false
  if (route.path.startsWith('/explore/douban')) lastExplorePage.value = '/explore/douban'
  else if (route.path.startsWith('/explore/tmdb')) lastExplorePage.value = '/explore/tmdb'
})

watch(isCompact, (compact) => {
  if (!compact) {
    showMoreMenu.value = false
    showExploreMenu.value = false
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
  position: relative;
  z-index: 30;
  background: var(--ms-glass-bg-heavy);
  border-right: 1px solid transparent;
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
    min-height: 64px;
    height: auto;
    display: flex;
    align-items: center;
    padding: 12px 14px;
    gap: 11px;
    border-bottom: 1px solid var(--ms-glass-border);
    position: relative;
    cursor: pointer;
    box-sizing: border-box;
    overflow: hidden;

    &:focus-visible {
      outline: 2px solid var(--ms-accent-primary);
      outline-offset: -2px;
    }

    .logo-icon {
      width: 40px;
      height: 40px;
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      background:
        radial-gradient(circle at 30% 25%, rgba(255, 255, 255, 0.2), transparent 45%),
        linear-gradient(145deg, #1f78ff 0%, #0f4cb7 100%);
      border-radius: 12px;
      box-shadow: 0 10px 24px rgba(12, 62, 148, 0.2);

      .brand-mark {
        width: 26px;
        height: 26px;
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
      justify-content: center;
      gap: 3px;
      flex: 1;
      min-width: 0;

      .logo-heading {
        display: flex;
        align-items: center;
        gap: 8px;
        line-height: 1.15;
        min-width: 0;
      }

      .logo-title {
        font-size: 18px;
        font-weight: 800;
        line-height: 1.15;
        color: var(--ms-text-primary);
        letter-spacing: -0.4px;
        white-space: nowrap;
      }

      .logo-badge {
        flex-shrink: 0;
        font-size: 10px;
        font-weight: 800;
        line-height: 1;
        padding: 3px 7px;
        background: rgba(43, 123, 255, 0.1);
        color: var(--ms-accent-primary);
        border: 1px solid rgba(43, 123, 255, 0.18);
        border-radius: 999px;
      }

      .logo-subtitle {
        font-size: 10.5px;
        font-weight: 600;
        line-height: 1.25;
        color: var(--ms-text-muted);
        letter-spacing: 0.02em;
        text-transform: uppercase;
        white-space: nowrap;
        max-width: 100%;
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

/* 手机端顶部标题栏 */
.compact-topbar {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 48px;
  min-height: 48px;
  padding: 0 16px;
  border-bottom: 1px solid var(--ms-glass-border);
  background: var(--ms-glass-bg-heavy);
  @supports (backdrop-filter: blur(12px)) {
    backdrop-filter: blur(12px);
  }

  .compact-brand {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;

    .compact-brand-icon {
      width: 28px;
      height: 28px;
      flex-shrink: 0;

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
    }

    .compact-brand-text {
      font-size: 17px;
      font-weight: 800;
      color: var(--ms-text-primary);
      letter-spacing: -0.5px;
    }
  }
}

/* 手机端底部 Dock 导航栏 */
.mobile-dock {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  display: flex;
  justify-content: space-around;
  align-items: center;
  height: 64px;
  padding-bottom: env(safe-area-inset-bottom);
  background: var(--ms-glass-bg-heavy);
  border-top: 1px solid var(--ms-glass-border);
  @supports (backdrop-filter: blur(20px)) {
    backdrop-filter: blur(20px);
  }
}

.dock-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  flex: 1;
  min-width: 0;
  padding: 4px 2px;
  border: none;
  background: transparent;
  color: var(--ms-text-muted);
  cursor: pointer;
  transition: color 0.2s ease;
  -webkit-tap-highlight-color: transparent;

  .dock-icon {
    font-size: 22px;
    transition: transform 0.2s ease;
  }

  .dock-label {
    font-size: 11px;
    font-weight: 500;
  }

  &.active {
    color: var(--ms-accent-primary);

    .dock-icon {
      transform: scale(1.1);
    }
  }
}

/* 内容区为 Dock 留出空间 */
.app-main.has-dock {
  padding-bottom: calc(64px + env(safe-area-inset-bottom) + 16px);
}

/* 「我的」操作面板 (Action Sheet) */
.more-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  background: rgba(0, 0, 0, 0.35);
  @supports (backdrop-filter: blur(6px)) {
    backdrop-filter: blur(6px);
  }
}

.more-sheet {
  width: 100%;
  max-width: 480px;
  background: var(--ms-bg-secondary);
  border-radius: 20px 20px 0 0;
  padding: 8px 16px calc(16px + env(safe-area-inset-bottom));
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.more-sheet-header {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px 0 8px;

  .more-sheet-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--ms-text-muted);
  }
}

.more-sheet-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.more-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 14px 16px;
  border: none;
  border-radius: 12px;
  background: transparent;
  color: var(--ms-text-primary);
  font-size: 15px;
  cursor: pointer;
  transition: background 0.15s ease;
  -webkit-tap-highlight-color: transparent;

  .el-icon {
    font-size: 20px;
    color: var(--ms-text-secondary);
  }

  &:active {
    background: var(--ms-glass-bg-heavy);
  }

  &.more-logout {
    color: var(--ms-accent-danger, #e74c3c);

    .el-icon {
      color: var(--ms-accent-danger, #e74c3c);
    }
  }

  &.more-item-active {
    background: var(--ms-glass-bg-heavy);
    color: var(--ms-primary);

    .el-icon {
      color: var(--ms-primary);
    }
  }
}

.more-sheet-footer {
  border-top: 1px solid var(--ms-glass-border);
  padding-top: 12px;
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.more-theme-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 16px;

  .more-theme-label {
    font-size: 14px;
    color: var(--ms-text-secondary);
    font-weight: 500;
  }
}

.more-cancel {
  width: 100%;
  padding: 14px;
  margin-top: 8px;
  border: none;
  border-radius: 12px;
  background: var(--ms-glass-bg-heavy);
  color: var(--ms-text-secondary);
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;

  &:active {
    opacity: 0.7;
  }
}

/* Action Sheet 过渡动画 */
.action-sheet-enter-active {
  transition: opacity 0.25s ease;

  .more-sheet {
    transition: transform 0.3s cubic-bezier(0.32, 0.72, 0, 1);
  }
}

.action-sheet-leave-active {
  transition: opacity 0.2s ease;

  .more-sheet {
    transition: transform 0.25s cubic-bezier(0.32, 0.72, 0, 1);
  }
}

.action-sheet-enter-from {
  opacity: 0;

  .more-sheet {
    transform: translateY(100%);
  }
}

.action-sheet-leave-to {
  opacity: 0;

  .more-sheet {
    transform: translateY(100%);
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
  .app-main {
    padding: 14px 12px;
  }

  .mobile-dock {
    height: 56px;
  }

  .dock-tab {
    .dock-icon {
      font-size: 20px;
    }

    .dock-label {
      font-size: 10px;
    }
  }

  .app-main.has-dock {
    padding-bottom: calc(56px + env(safe-area-inset-bottom) + 12px);
  }
}
</style>
