/** 本地登录态提示（仅存是否已登录与用户名，真实鉴权仍依赖 HttpOnly Cookie） */
const STORAGE_KEY = 'ms-auth-session-hint'

export function readAuthSessionHint() {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    if (!data?.authenticated) return null
    return {
      authenticated: true,
      username: String(data.username || '').trim()
    }
  } catch {
    return null
  }
}

export function writeAuthSessionHint(session) {
  if (typeof window === 'undefined') return
  try {
    if (session?.authenticated) {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          authenticated: true,
          username: String(session.username || '').trim()
        })
      )
    } else {
      window.localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // ignore quota / private mode errors
  }
}

export function clearAuthSessionHint() {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}
