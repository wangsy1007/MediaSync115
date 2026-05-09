import { ref } from 'vue'
import { settingsApi } from '@/api'

// All available tab definitions with display info
export const ALL_TABS = [
  { key: 'pan115', label: '115网盘', group: 'main' },
  { key: 'pan115_pansou', label: 'Pansou', group: 'pan115', parent: 'pan115' },
  { key: 'pan115_hdhive', label: 'HDHive', group: 'pan115', parent: 'pan115' },
  { key: 'pan115_tg', label: 'Telegram', group: 'pan115', parent: 'pan115' },
  { key: 'magnet', label: '磁力链接', group: 'main' },
  { key: 'magnet_seedhub', label: 'SeedHub', group: 'magnet', parent: 'magnet' },
  { key: 'magnet_butailing', label: '不太灵', group: 'magnet', parent: 'magnet' },
]

const ALL_KEYS = ALL_TABS.map(t => t.key)

// Shared reactive state — ordered array, position = display order
const visibleTabs = ref([...ALL_KEYS])
let loaded = false

export async function loadVisibleTabs() {
  if (loaded) return visibleTabs.value
  try {
    const { data } = await settingsApi.getRuntime()
    const list = data.detail_visible_tabs
    if (Array.isArray(list) && list.length > 0) {
      visibleTabs.value = [...list]
    }
  } catch {
    // keep default (all visible, default order)
  }
  loaded = true
  return visibleTabs.value
}

export function getVisibleTabs() {
  return visibleTabs
}

export async function saveVisibleTabs(keys) {
  const arr = [...keys]
  visibleTabs.value = arr
  loaded = true
  await settingsApi.updateRuntime({ detail_visible_tabs: arr })
}

export function isTabVisible(visibleArr, key) {
  const arr = Array.isArray(visibleArr) ? visibleArr : visibleArr?.value
  if (!arr) return true
  const tab = ALL_TABS.find(t => t.key === key)
  if (!tab) return true
  if (tab.parent && !arr.includes(tab.parent)) return false
  return arr.includes(key)
}

// Return visible sub-tab keys for a parent group, in the configured order
export function getOrderedVisibleSubTabs(visibleArr, parentKey) {
  const arr = Array.isArray(visibleArr) ? visibleArr : visibleArr?.value
  if (!arr) return ALL_TABS.filter(t => t.parent === parentKey).map(t => t.key)
  return arr.filter(k => {
    const tab = ALL_TABS.find(t => t.key === k)
    return tab && tab.parent === parentKey
  })
}

// Return the short name (e.g. 'pansou', 'seedhub') of the first visible sub-tab for a parent group
export function getFirstVisibleSubTabName(visibleArr, parentKey) {
  const tabs = getOrderedVisibleSubTabs(visibleArr, parentKey)
  if (tabs.length === 0) return ''
  return tabs[0].replace(parentKey + '_', '')
}

// Return visible main (top-level) tab keys in the configured order
export function getOrderedVisibleMainTabs(visibleArr) {
  const arr = Array.isArray(visibleArr) ? visibleArr : visibleArr?.value
  if (!arr) return ALL_TABS.filter(t => t.group === 'main').map(t => t.key)
  return arr.filter(k => {
    const tab = ALL_TABS.find(t => t.key === k)
    return tab && tab.group === 'main'
  })
}
