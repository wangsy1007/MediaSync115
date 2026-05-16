/** 探索页横向榜单卡片宽度计算（与 Search.vue 布局一致） */

export const EXPLORE_CARD_GAP = 14
export const EXPLORE_CARD_MIN_WIDTH = 150
export const EXPLORE_CARD_MAX_WIDTH = 210
export const EXPLORE_CARD_MIN_PER_VIEW = 2
export const EXPLORE_CARD_MAX_PER_VIEW = 9
export const EXPLORE_DEFAULT_CARD_WIDTH = 188

const COMPACT_VIEWPORT_MAX = 1024
const MOBILE_VIEWPORT_MAX = 768

/** 估算探索区可用宽度（侧栏 + main padding 与 App.vue 对齐） */
export function estimateExploreContainerWidth(viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1280) {
  const width = Number(viewportWidth) || 1280
  const sidebar = width <= COMPACT_VIEWPORT_MAX ? 0 : 240
  const mainPadding = width <= MOBILE_VIEWPORT_MAX ? 40 : (width <= COMPACT_VIEWPORT_MAX ? 40 : 64)
  return Math.max(320, width - sidebar - mainPadding)
}

/**
 * 根据容器宽度计算卡片宽度与每屏可见数量。
 * @returns {{ cardWidth: number, cardsPerView: number }}
 */
export function resolveExploreCardLayout(containerWidth, viewportWidth = containerWidth) {
  const width = Math.max(0, Number(containerWidth) || 0)
  const viewport = Number(viewportWidth) || width

  if (viewport <= MOBILE_VIEWPORT_MAX) {
    const mobileGap = 10
    const availableWidth = Math.max(width - 30, 0)
    const mobileWidth = Math.floor((availableWidth - mobileGap * 1.5) / 2.5)
    return {
      cardWidth: Math.max(96, Math.min(132, mobileWidth || EXPLORE_DEFAULT_CARD_WIDTH)),
      cardsPerView: 2.5
    }
  }

  const estimated = Math.floor((width + EXPLORE_CARD_GAP) / (EXPLORE_CARD_MIN_WIDTH + EXPLORE_CARD_GAP))
  const cardsPerView = Math.max(
    EXPLORE_CARD_MIN_PER_VIEW,
    Math.min(EXPLORE_CARD_MAX_PER_VIEW, estimated || EXPLORE_CARD_MIN_PER_VIEW)
  )
  const raw = width > 0
    ? Math.floor((width - EXPLORE_CARD_GAP * (cardsPerView - 1)) / cardsPerView)
    : EXPLORE_DEFAULT_CARD_WIDTH

  return {
    cardWidth: Math.max(EXPLORE_CARD_MIN_WIDTH, Math.min(EXPLORE_CARD_MAX_WIDTH, raw)),
    cardsPerView
  }
}

export function getInitialExploreCardLayout() {
  if (typeof window === 'undefined') {
    return { cardWidth: EXPLORE_DEFAULT_CARD_WIDTH, cardsPerView: 4 }
  }
  const estimatedWidth = estimateExploreContainerWidth(window.innerWidth)
  return resolveExploreCardLayout(estimatedWidth, window.innerWidth)
}
