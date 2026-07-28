import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * 移动端影视卡片交互：
 * - 第一次点海报：展开订阅/转存按钮（不进详情）
 * - 再点一次海报：进入详情
 * - 点标题区：直接进详情
 * - 点空白处：收起按钮
 * 桌面端点海报或标题均可进详情，悬停显示操作按钮。
 */
export function useCardActionReveal() {
  const revealedKey = ref('')
  const isTouchUi = ref(false)
  const mediaQueries = []

  const syncTouchUi = () => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      isTouchUi.value = false
      return
    }
    const noHover = window.matchMedia('(hover: none)').matches
    const coarse = window.matchMedia('(pointer: coarse)').matches
    const maxTouchPoints = Number(navigator.maxTouchPoints || 0) > 0
    isTouchUi.value = noHover || coarse || maxTouchPoints
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
   * 点海报：移动端首次展开操作，再次点击进入详情；桌面端直接进入详情。
   * @returns {boolean} 是否已触发导航
   */
  const handlePosterActivate = (key, onNavigate) => {
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
      clearRevealed()
      onNavigate?.()
      return true
    }
    revealedKey.value = id
    return false
  }

  /** 点标题区：始终进入详情。 */
  const handleDetailActivate = (onNavigate) => {
    clearRevealed()
    onNavigate?.()
  }

  /** @deprecated 兼容旧调用，等同 handlePosterActivate */
  const handleCardActivate = handlePosterActivate

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
      for (const query of ['(hover: none)', '(pointer: coarse)']) {
        const media = window.matchMedia(query)
        const onChange = () => syncTouchUi()
        if (typeof media.addEventListener === 'function') {
          media.addEventListener('change', onChange)
        } else if (typeof media.addListener === 'function') {
          media.addListener(onChange)
        }
        mediaQueries.push({ media, onChange })
      }
    }
    document.addEventListener('pointerdown', onDocumentPointerDown, true)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('pointerdown', onDocumentPointerDown, true)
    for (const entry of mediaQueries) {
      if (typeof entry.media.removeEventListener === 'function') {
        entry.media.removeEventListener('change', entry.onChange)
      } else if (typeof entry.media.removeListener === 'function') {
        entry.media.removeListener(entry.onChange)
      }
    }
    mediaQueries.length = 0
  })

  return {
    revealedKey,
    isTouchUi,
    isActionsRevealed,
    revealActions,
    clearRevealed,
    handlePosterActivate,
    handleDetailActivate,
    handleCardActivate
  }
}
