import { onBeforeUnmount, onMounted, ref } from 'vue'

const DESKTOP_CARD_MIN_WIDTH = '(min-width: 769px)'
const ACTION_BUTTON_SELECTOR = '.explore-action-btn, .action-btn'

/**
 * 移动端窄屏触控：第一次点海报展开订阅/转存，再点进入详情；点标题直接进详情。
 * PC / 宽屏：海报任意位置一次点击进入详情；悬停仅展示操作按钮，不挡点击。
 */
export function useCardActionReveal() {
  const revealedKey = ref('')
  const isTouchUi = ref(false)
  const mediaQueries = []
  let lastPointerType = ''

  const isDesktopCardUi = () => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return true
    }
    return window.matchMedia(DESKTOP_CARD_MIN_WIDTH).matches
  }

  const syncTouchUi = () => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      isTouchUi.value = false
      return
    }
    if (isDesktopCardUi()) {
      isTouchUi.value = false
      return
    }
    const noAnyHover = !window.matchMedia('(any-hover: hover)').matches
    const coarseOnly =
      window.matchMedia('(pointer: coarse)').matches &&
      !window.matchMedia('(any-pointer: fine)').matches
    isTouchUi.value = noAnyHover || coarseOnly
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

  const isActionButtonTarget = (event) => {
    const target = event?.target
    return target instanceof Element && Boolean(target.closest(ACTION_BUTTON_SELECTOR))
  }

  const notePointer = (event) => {
    const type = event?.pointerType
    if (type) {
      lastPointerType = String(type)
      return
    }
    if (event?.type === 'mousedown' || typeof event?.button === 'number') {
      lastPointerType = 'mouse'
    }
  }

  const isDirectNavigatePointer = (event) => {
    if (isDesktopCardUi()) return true

    notePointer(event)
    const type = String(
      event?.pointerType || lastPointerType || ''
    ).toLowerCase()
    if (type === 'mouse' || type === 'pen') return true
    if (type === 'touch') return false
    return !isTouchUi.value
  }

  /**
   * 点海报：PC 一次进详情；窄屏触控两段式。
   * @returns {boolean} 是否已触发导航
   */
  const handlePosterActivate = (key, onNavigate, event) => {
    if (isActionButtonTarget(event)) {
      return false
    }
    if (isDirectNavigatePointer(event)) {
      clearRevealed()
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
    notePointer(event)
    if (!isTouchUi.value || !revealedKey.value) return
    const target = event?.target
    if (!(target instanceof Element)) {
      clearRevealed()
      return
    }
    if (target.closest('[data-card-actions-host="1"]')) return
    clearRevealed()
  }

  const onDocumentMouseDown = (event) => {
    if (!event?.pointerType) {
      lastPointerType = 'mouse'
    }
  }

  const onViewportChange = () => syncTouchUi()

  onMounted(() => {
    syncTouchUi()
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      for (const query of [
        DESKTOP_CARD_MIN_WIDTH,
        '(any-hover: hover)',
        '(pointer: coarse)',
        '(any-pointer: fine)'
      ]) {
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
    window.addEventListener('resize', onViewportChange)
    document.addEventListener('pointerdown', onDocumentPointerDown, true)
    document.addEventListener('mousedown', onDocumentMouseDown, true)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', onViewportChange)
    document.removeEventListener('pointerdown', onDocumentPointerDown, true)
    document.removeEventListener('mousedown', onDocumentMouseDown, true)
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
    notePointer,
    isDesktopCardUi,
    handlePosterActivate,
    handleDetailActivate,
    handleCardActivate
  }
}
