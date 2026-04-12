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

// Shared reactive state — loaded once, used by all detail pages
const visibleTabs = ref(new Set(ALL_KEYS))
let loaded = false

export async function loadVisibleTabs() {
  if (loaded) return visibleTabs.value
  try {
    const { data } = await settingsApi.getRuntime()
    const list = data.detail_visible_tabs
    if (Array.isArray(list)) {
      visibleTabs.value = new Set(list)
    }
  } catch {
    // keep default (all visible)
  }
  loaded = true
  return visibleTabs.value
}

export function getVisibleTabs() {
  return visibleTabs
}

export async function saveVisibleTabs(keys) {
  const arr = [...keys]
  visibleTabs.value = new Set(arr)
  loaded = true
  await settingsApi.updateRuntime({ detail_visible_tabs: arr })
}

export function isTabVisible(visibleSet, key) {
  const set = visibleSet instanceof Set ? visibleSet : visibleSet?.value
  if (!set) return true
  const tab = ALL_TABS.find(t => t.key === key)
  if (!tab) return true
  if (tab.parent && !set.has(tab.parent)) return false
  return set.has(key)
}
