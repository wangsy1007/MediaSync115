const STORAGE_KEY = 'detail_visible_tabs'

// All available tab definitions with display info
export const ALL_TABS = [
  { key: 'pan115', label: '115网盘', group: 'main' },
  { key: 'pan115_nullbr', label: 'Nullbr', group: 'pan115', parent: 'pan115' },
  { key: 'pan115_pansou', label: 'Pansou', group: 'pan115', parent: 'pan115' },
  { key: 'pan115_hdhive', label: 'HDHive', group: 'pan115', parent: 'pan115' },
  { key: 'pan115_tg', label: 'Telegram', group: 'pan115', parent: 'pan115' },
  { key: 'magnet', label: '磁力链接', group: 'main' },
  { key: 'magnet_nullbr', label: 'Nullbr', group: 'magnet', parent: 'magnet' },
  { key: 'magnet_seedhub', label: 'SeedHub', group: 'magnet', parent: 'magnet' },
  { key: 'magnet_butailing', label: '不太灵', group: 'magnet', parent: 'magnet' },
  { key: 'ed2k', label: 'ED2K', group: 'main' },
]

const ALL_KEYS = ALL_TABS.map(t => t.key)

export function getVisibleTabs() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Set(ALL_KEYS)
    const list = JSON.parse(raw)
    if (!Array.isArray(list)) return new Set(ALL_KEYS)
    return new Set(list)
  } catch {
    return new Set(ALL_KEYS)
  }
}

export function saveVisibleTabs(keys) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...keys]))
}

export function isTabVisible(visibleSet, key) {
  const tab = ALL_TABS.find(t => t.key === key)
  if (!tab) return true
  // If it's a sub-tab, parent must also be visible
  if (tab.parent && !visibleSet.has(tab.parent)) return false
  return visibleSet.has(key)
}
