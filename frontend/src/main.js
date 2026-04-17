import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

import App from './App.vue'
import router from './router'
import './styles/main.scss'
import { applyBeijingTimezone } from './utils/timezone'
import { initPerformanceMonitor } from './utils/performance'

const installZoomLock = () => {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return
  }

  const zoomKeys = new Set(['+', '-', '=', '_', '0'])

  const handleKeydown = (event) => {
    if (!(event.ctrlKey || event.metaKey)) {
      return
    }
    if (zoomKeys.has(String(event.key || '').toLowerCase())) {
      event.preventDefault()
    }
  }

  const handleWheel = (event) => {
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault()
    }
  }

  const preventGesture = (event) => {
    event.preventDefault()
  }

  document.addEventListener('keydown', handleKeydown, { passive: false })
  window.addEventListener('wheel', handleWheel, { passive: false })
  document.addEventListener('gesturestart', preventGesture, { passive: false })
  document.addEventListener('gesturechange', preventGesture, { passive: false })
  document.addEventListener('gestureend', preventGesture, { passive: false })
}

const app = createApp(App)

applyBeijingTimezone()
installZoomLock()

// 初始化性能监控（开发环境）
initPerformanceMonitor()

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
