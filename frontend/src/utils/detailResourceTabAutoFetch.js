import { computed, ref, watch } from 'vue'

/**
 * 详情页资源 Tab 懒加载策略：
 * - 进入页面时的默认 Tab（主 Tab + 子 Tab）需手动点击按钮获取
 * - 切换到其他 Tab 后自动获取（若尚未获取过）
 */
export function useDetailResourceTabAutoFetch({
  activeTab,
  pan115SourceTab,
  magnetSourceTab,
  onPan115SubTab,
  onMagnetSubTab,
}) {
  const initialMainTab = ref('')
  const initialPan115SubTab = ref('')
  const initialMagnetSubTab = ref('')

  const captureInitialTabs = () => {
    initialMainTab.value = String(activeTab.value || '')
    initialPan115SubTab.value = String(pan115SourceTab.value || '')
    initialMagnetSubTab.value = String(magnetSourceTab.value || '')
  }

  const isInitialResourceView = computed(() => {
    if (activeTab.value !== initialMainTab.value) return false
    if (activeTab.value === 'pan115' && pan115SourceTab.value !== initialPan115SubTab.value) {
      return false
    }
    if (activeTab.value === 'magnet' && magnetSourceTab.value !== initialMagnetSubTab.value) {
      return false
    }
    return Boolean(initialMainTab.value)
  })

  const skipQuarkAutoFetch = computed(
    () => activeTab.value === 'quark' && isInitialResourceView.value
  )

  const triggerCurrentTabFetch = () => {
    if (!initialMainTab.value) return
    if (isInitialResourceView.value) return
    const main = activeTab.value
    if (main === 'pan115') {
      onPan115SubTab?.(pan115SourceTab.value)
      return
    }
    if (main === 'magnet') {
      onMagnetSubTab?.(magnetSourceTab.value)
    }
  }

  const setupAutoFetchWatchers = () => {
    watch([activeTab, pan115SourceTab, magnetSourceTab], () => {
      triggerCurrentTabFetch()
    })
  }

  return {
    captureInitialTabs,
    isInitialResourceView,
    skipQuarkAutoFetch,
    setupAutoFetchWatchers,
    triggerCurrentTabFetch,
  }
}
