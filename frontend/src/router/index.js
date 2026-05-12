import { createRouter, createWebHistory } from 'vue-router'
import { authApi, isBackendUnavailableError, waitForBackendReady } from '@/api'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true }
  },
  {
    path: '/',
    redirect: '/explore/douban'
  },
  {
    path: '/search',
    redirect: '/explore/douban'
  },
  {
    path: '/explore/:source(douban|tmdb)',
    name: 'Search',
    component: () => import('@/views/Search.vue')
  },
  {
    path: '/explore/section/:key',
    redirect: to => `/explore/douban/section/${encodeURIComponent(to.params.key)}`
  },
  {
    path: '/explore/:source(douban|tmdb)/section/:key',
    name: 'ExploreSection',
    component: () => import('@/views/ExploreSection.vue')
  },
  {
    path: '/subscriptions',
    name: 'Subscriptions',
    component: () => import('@/views/Subscriptions.vue')
  },
  {
    path: '/downloads',
    name: 'Downloads',
    component: () => import('@/views/Downloads.vue')
  },
  {
    path: '/archive',
    name: 'Archive',
    component: () => import('@/views/Archive.vue')
  },
  {
    path: '/strm',
    name: 'Strm',
    component: () => import('@/views/Strm.vue')
  },
  {
    path: '/subscription-logs',
    redirect: '/logs'
  },
  {
    path: '/logs',
    name: 'Logs',
    component: () => import('@/views/Logs.vue')
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/Settings.vue')
  },
  {
    path: '/scheduler',
    name: 'Scheduler',
    component: () => import('@/views/Scheduler.vue')
  },
  {
    path: '/workflow',
    name: 'Workflow',
    component: () => import('@/views/Workflow.vue')
  },
  {
    path: '/movie/:id',
    name: 'MovieDetail',
    component: () => import('@/views/MovieDetail.vue')
  },
  {
    path: '/tv/:id',
    name: 'TvDetail',
    component: () => import('@/views/TvDetail.vue')
  },
  {
    path: '/douban/:mediaType(movie|tv)/:id',
    name: 'DoubanDetail',
    component: () => import('@/views/DoubanDetail.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

import { ref } from 'vue'

let authSessionCache = null
let authSessionPromise = null

// 导出供 App.vue 使用，在认证检查期间显示加载动画
export const isAuthChecking = ref(false)

const getAuthSession = async (force = false) => {
  if (!force && authSessionCache) return authSessionCache
  if (!force && authSessionPromise) return authSessionPromise

  authSessionPromise = authApi.getSession()
    .then(({ data }) => {
      authSessionCache = data || { authenticated: false, username: '' }
      return authSessionCache
    })
    .catch(async (error) => {
      if (isBackendUnavailableError(error)) {
        const ready = await waitForBackendReady()
        if (ready) {
          try {
            const { data } = await authApi.getSession()
            authSessionCache = data || { authenticated: false, username: '' }
            return authSessionCache
          } catch {
            // Fall back to unauthenticated below.
          }
        }
      }
      authSessionCache = { authenticated: false, username: '' }
      return authSessionCache
    })
    .finally(() => {
      authSessionPromise = null
    })

  return authSessionPromise
}

export const resetAuthSessionCache = () => {
  authSessionCache = null
  authSessionPromise = null
}

router.beforeEach(async (to) => {
  // 公开路由（如 /login）：已有缓存且已登录时才重定向，否则立即放行不阻塞后端
  if (to.meta?.public) {
    if (authSessionCache?.authenticated) {
      if (to.path === '/login') {
        return to.query.redirect ? String(to.query.redirect) : '/'
      }
      return true
    }
    // 无缓存时：先放行显示页面，后台静默检查认证状态
    if (!authSessionCache) {
      getAuthSession().then((session) => {
        if (session?.authenticated && router.currentRoute.value.path === '/login') {
          router.replace(
            router.currentRoute.value.query.redirect
              ? String(router.currentRoute.value.query.redirect)
              : '/'
          )
        }
      }).catch(() => {})
    }
    return true
  }

  // 受保护路由：阻塞式检查认证
  isAuthChecking.value = true
  let session
  try {
    session = await getAuthSession()
  } finally {
    isAuthChecking.value = false
  }
  if (session?.authenticated) return true
  return {
    path: '/login',
    query: {
      redirect: to.fullPath
    }
  }
})

export default router
