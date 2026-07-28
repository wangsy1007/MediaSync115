import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * 移动端影视卡片交互：
 * - 第一次点海报：展开订阅/转存按钮（不进详情）
 * - 再点一次海报：进入详情
 * - 点标题区：直接进详情
 * - 点空白处：收起按钮
 * 桌面端 / 有鼠标悬停能力的设备：点击直接进详情。
 * Windows 触摸屏笔记本常把 primary 报成 hover:none，但 any-hover:hover 仍成立，必须走一键进详情。
 */
export function useCardActionReveal() {
  const revealedKey = ref('')
  /** 是否启用「先展开再进详情」的触控两段式 */
  const isTouchUi = ref(false)
  const mediaQueries = []
  let lastPointerType = ''

  const syncTouchUi = () => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      isTouchUi.value = false
      return
    }
    // 与 CSS @media (hover: none) 对齐，但额外用 any-hover：
    // 只要有任一可悬停指针（鼠标），就不走两段式，避免 PC 要点两次。
    const primaryNoHover = window.matchMedia('(hover: none)').matches
    const anyHover = window.matchMedia('(any-hover: hover)').matches
    isTouchUi.value = primaryNoHover && !anyHover
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

  const notePointer = (event) => {
    const type = event?.pointerType
    if (type) {
      lastPointerType = String(type)
      return
    }
    // 部分环境只有 mouse 事件、没有 PointerEvent
    if (event?.type === 'mousedown' || event?.button === 0) {
      lastPointerType = 'mouse'
    }
  }

  const isDirectNavigatePointer = (event) => {
    notePointer(event)
    const type = String(
      event?.pointerType || lastPointerType || ''
    ).toLowerCase()
    if (type === 'mouse' || type === 'pen') return true
    if (type === 'touch') return false
    // 无指针类型时：能悬停的设备一律一键进详情
    return !isTouchUi.value
  }

  /**
   * 点海报：触控两段式；鼠标/桌面端直接进详情。
   * @returns {boolean} 是否已触发导航
   */
  const handlePosterActivate = (key, onNavigate, event) => {
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
    // 兜底：无 PointerEvent 时仍能识别鼠标
    if (!event?.pointerType) {
      lastPointerType = 'mouse'
    }
  }

  onMounted(() => {
    syncTouchUi()
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      for (const query of ['(hover: none)', '(any-hover: hover)']) {
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
    document.addEventListener('mousedown', onDocumentMouseDown, true)
  })

  onBeforeUnmount(() => {
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
    handlePosterActivate,
    handleDetailActivate,
    handleCardActivate
  }
}
