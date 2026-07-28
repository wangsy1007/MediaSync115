import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * 移动端影视卡片：先点一次展开订阅/转存，再点按钮操作；
 * 已展开时再点卡片本体则进入详情。桌面端（可 hover）不拦截导航。
 */
export function useCardActionReveal() {
  const revealedKey = ref('')
  const isTouchUi = ref(false)
  let hoverMedia = null

  const syncTouchUi = () => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      isTouchUi.value = false
      return
    }
    isTouchUi.value = window.matchMedia('(hover: none)').matches
  }

  const cardKey = (value) => String(value ?? '')

  const isActionsRevealed = (key) => {
    const id = cardKey(key)
    return Boolean(id) && revealedKey.value === id
  }

  const clearRevealed = () => {
    revealedKey.value = ''
  }

  const revealActions = (key) => {
    const id = cardKey(key)
    if (!id) return
    revealedKey.value = id
  }

  /**
   * @param {string|number} key
   * @param {() => void} onNavigate 进入详情
   * @returns {boolean} 是否已触发导航
   */
  const handleCardActivate = (key, onNavigate) => {
    if (!isTouchUi.value) {
      onNavigate?.()
      return true
    }
    const id = cardKey(key)
    if (!id) {
      onNavigate?.()
      return true
    }
    if (revealedKey.value === id) {
      onNavigate?.()
      return true
    }
    revealedKey.value = id
    return false
  }

  const onDocumentPointerDown = (event) => {
    if (!isTouchUi.value || !revealedKey.value) return
    const target = event?.target
    if (!(target instanceof Element)) {
      clearRevealed()
      return
    }
    if (target.closest('[data-card-actions-host="1"]')) return
    clearRevealed()
  }

  onMounted(() => {
    syncTouchUi()
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      hoverMedia = window.matchMedia('(hover: none)')
      const onChange = () => syncTouchUi()
      if (typeof hoverMedia.addEventListener === 'function') {
        hoverMedia.addEventListener('change', onChange)
      } else if (typeof hoverMedia.addListener === 'function') {
        hoverMedia.addListener(onChange)
      }
      hoverMedia._onChange = onChange
    }
    document.addEventListener('pointerdown', onDocumentPointerDown, true)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('pointerdown', onDocumentPointerDown, true)
    if (hoverMedia?._onChange) {
      if (typeof hoverMedia.removeEventListener === 'function') {
        hoverMedia.removeEventListener('change', hoverMedia._onChange)
      } else if (typeof hoverMedia.removeListener === 'function') {
        hoverMedia.removeListener(hoverMedia._onChange)
      }
    }
    hoverMedia = null
  })

  return {
    revealedKey,
    isTouchUi,
    isActionsRevealed,
    revealActions,
    clearRevealed,
    handleCardActivate
  }
}
