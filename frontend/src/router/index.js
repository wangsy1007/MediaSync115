import { createRouter, createWebHistory } from 'vue-router'
import { authApi, isBackendUnavailableError, waitForBackendReady } from '@/api'
import {
  clearAuthSessionHint,
  readAuthSessionHint,
  writeAuthSessionHint
} from '@/utils/authSessionHint'

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
  routes,
  scrollBehavior(to, from, savedPosition) {
    // 浏览器后退/前进时恢复之前的滚动位置
    if (savedPosition) {
      return savedPosition
    }
    // 新导航默认滚动到顶部
    return { top: 0 }
  }
})

let authSessionCache = readAuthSessionHint()
let authSessionPromise = null

const normalizeSession = (data) => ({
  authenticated: Boolean(data?.authenticated),
  username: String(data?.username || '').trim(),
  expires_at: data?.expires_at
})

const applyAuthSession = (session) => {
  authSessionCache = normalizeSession(session)
  writeAuthSessionHint(authSessionCache)
  return authSessionCache
}

const hasOptimisticAuth = () => Boolean(authSessionCache?.authenticated)

const isTransientAuthError = (error) => {
  if (!error) return true
  if (isBackendUnavailableError(error)) return true
  const status = Number(error.response?.status || 0)
  if (!status) return true
  return status === 502 || status === 503 || status === 504
}

/**
 * @param {boolean} force
 * @param {{ preserveOnTransientError?: boolean }} options
 */
const getAuthSession = async (force = false, options = {}) => {
  const { preserveOnTransientError = false } = options
  if (!force && authSessionCache?.authenticated) return authSessionCache
  if (!force && authSessionPromise) return authSessionPromise

  authSessionPromise = authApi.getSession()
    .then(({ data }) => applyAuthSession(data || { authenticated: false, username: '' }))
    .catch(async (error) => {
      if (isBackendUnavailableError(error)) {
        const ready = await waitForBackendReady()
        if (ready) {
          try {
            const { data } = await authApi.getSession()
            return applyAuthSession(data || { authenticated: false, username: '' })
          } catch (retryError) {
            if (preserveOnTransientError && isTransientAuthError(retryError) && hasOptimisticAuth()) {
              return authSessionCache
            }
          }
        }
      }
      if (preserveOnTransientError && isTransientAuthError(error) && hasOptimisticAuth()) {
        return authSessionCache
      }
      return applyAuthSession({ authenticated: false, username: '' })
    })
    .finally(() => {
      authSessionPromise = null
    })

  return authSessionPromise
}

const redirectToLogin = (redirectPath) => {
  const redirect = String(redirectPath || '').trim() || '/'
  if (router.currentRoute.value.path === '/login') return
  router.replace({
    path: '/login',
    query: { redirect }
  })
}

const verifyAuthSessionInBackground = (redirectOnFailure) => {
  getAuthSession(true, { preserveOnTransientError: true })
    .then((session) => {
      if (session?.authenticated) return
      resetAuthSessionCache()
      if (redirectOnFailure) {
        redirectToLogin(redirectOnFailure)
      }
    })
    .catch(() => {})
}

export const markAuthSessionAuthenticated = (username) => {
  applyAuthSession({ authenticated: true, username })
}

export const resetAuthSessionCache = () => {
  authSessionCache = null
  authSessionPromise = null
  clearAuthSessionHint()
}

router.beforeEach(async (to) => {
  if (to.meta?.public) {
    if (authSessionCache?.authenticated) {
      if (to.path === '/login') {
        return to.query.redirect ? String(to.query.redirect) : '/'
      }
      return true
    }
    if (!authSessionCache) {
      getAuthSession(false, { preserveOnTransientError: true })
        .then((session) => {
          if (session?.authenticated && router.currentRoute.value.path === '/login') {
            router.replace(
              router.currentRoute.value.query.redirect
                ? String(router.currentRoute.value.query.redirect)
                : '/'
            )
          }
        })
        .catch(() => {})
    }
    return true
  }

  if (authSessionCache?.authenticated) {
    verifyAuthSessionInBackground()
    return true
  }

  const hint = readAuthSessionHint()
  if (hint?.authenticated) {
    authSessionCache = hint
    verifyAuthSessionInBackground(to.fullPath)
    return true
  }

  const session = await getAuthSession()
  if (session?.authenticated) return true
  return {
    path: '/login',
    query: {
      redirect: to.fullPath
    }
  }
})

export default router
