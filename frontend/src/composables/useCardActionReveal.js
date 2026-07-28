import { onBeforeUnmount, onMounted, ref } from 'vue'

/** 与布局断点一致：≤768 走移动端两段式，≥769 走 PC 一次进详情 */
const MOBILE_CARD_MAX_WIDTH = '(max-width: 768px)'
const ACTION_BUTTON_SELECTOR = '.explore-action-btn, .action-btn'

/**
 * 影视卡片点击交互（PC / 移动端分离）：
 *
 * PC（宽屏）：
 * - 点海报 / 标题 → 直接进入详情
 * - 悬停展示订阅 / 转存按钮，点按钮执行对应操作
 *
 * 移动端（窄屏）：
 * - 第一次点海报 → 展开订阅 / 转存
 * - 再点一次海报 → 进入详情
 * - 点标题 → 直接进入详情
 */
export function useCardActionReveal() {
  const revealedKey = ref('')
  const isMobileCardUi = ref(false)
  const mediaQueries = []

  const syncMobileCardUi = () => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      isMobileCardUi.value = false
      return
    }
    isMobileCardUi.value = window.matchMedia(MOBILE_CARD_MAX_WIDTH).matches
  }

  const cardKey = (value) => String(value ?? '')

  const isActionButtonTarget = (event) => {
    const target = event?.target
    return target instanceof Element && Boolean(target.closest(ACTION_BUTTON_SELECTOR))
  }

  const isActionsRevealed = (key) => {
    if (!isMobileCardUi.value) return false
    const id = cardKey(key)
    return Boolean(id) && revealedKey.value === id
  }

  const clearRevealed = () => {
    revealedKey.value = ''
  }

  /**
   * 点海报。
   * @returns {boolean} 是否已触发导航
   */
  const handlePosterClick = (key, onNavigate, event) => {
    if (isActionButtonTarget(event)) {
      return false
    }

    // PC：完全不使用两段式，一次进入详情
    if (!isMobileCardUi.value) {
      clearRevealed()
      onNavigate?.()
      return true
    }

    // 移动端：两段式
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

  /** 点标题：始终进入详情 */
  const handleDetailClick = (onNavigate) => {
    clearRevealed()
    onNavigate?.()
  }

  const onDocumentPointerDown = (event) => {
    if (!isMobileCardUi.value || !revealedKey.value) return
    const target = event?.target
    if (!(target instanceof Element)) {
      clearRevealed()
      return
    }
    if (target.closest('[data-card-actions-host="1"]')) return
    clearRevealed()
  }

  const onViewportChange = () => {
    syncMobileCardUi()
    if (!isMobileCardUi.value) {
      clearRevealed()
    }
  }

  onMounted(() => {
    syncMobileCardUi()
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      const media = window.matchMedia(MOBILE_CARD_MAX_WIDTH)
      const onChange = () => onViewportChange()
      if (typeof media.addEventListener === 'function') {
        media.addEventListener('change', onChange)
      } else if (typeof media.addListener === 'function') {
        media.addListener(onChange)
      }
      mediaQueries.push({ media, onChange })
    }
    window.addEventListener('resize', onViewportChange)
    document.addEventListener('pointerdown', onDocumentPointerDown, true)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', onViewportChange)
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
    isMobileCardUi,
    isActionsRevealed,
    clearRevealed,
    handlePosterClick,
    handleDetailClick,
    /** @deprecated 兼容旧名 */
    handlePosterActivate: handlePosterClick,
    /** @deprecated 兼容旧名 */
    handleDetailActivate: handleDetailClick,
    /** @deprecated 兼容旧名 */
    handleCardActivate: handlePosterClick,
    /** @deprecated 兼容旧名 */
    isTouchUi: isMobileCardUi,
    /** @deprecated 兼容旧名 */
    isDesktopCardUi: () => !isMobileCardUi.value
  }
}
