const FOLDER_TYPE_VALUES = new Set(['dir', 'dirs', 'folder', 'directory'])

const toTrimmedString = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const pickFirstString = (source, keys) => {
  for (const key of keys) {
    const value = toTrimmedString(source?.[key])
    if (value) return value
  }
  return ''
}

const isFolderLikeItem = (item) => {
  if (!item || typeof item !== 'object') return false
  if (toTrimmedString(item.cid)) return true
  if (toTrimmedString(item.is_directory) === '1') return true

  const folderFlags = [item.is_dir, item.isdir, item.is_folder, item.folder, item.directory]
  if (folderFlags.some(value => value === true || value === 1 || value === '1' || value === 'true')) {
    return true
  }

  const typeValue = pickFirstString(item, ['type', 'item_type', 'file_type', 'kind', 'category']).toLowerCase()
  if (FOLDER_TYPE_VALUES.has(typeValue)) return true

  const fileMarkers = [
    item.sha1,
    item.fs,
    item.size,
    item.file_size,
    item.pick_code,
    item.pc,
    item.ico,
    item.ftype,
    item.play_long
  ]
  const hasStrongFileMarker = fileMarkers.some(value => toTrimmedString(value))
  if (hasStrongFileMarker) {
    return !toTrimmedString(item.sha1) && !toTrimmedString(item.fs) && !toTrimmedString(item.size) && !toTrimmedString(item.file_size) && !toTrimmedString(item.ico) && !toTrimmedString(item.ftype)
  }

  return !!pickFirstString(item, ['cid', 'fid', 'id', 'folder_id', 'file_id'])
}

export const normalizePan115FolderOptions = (list = []) => {
  const deduped = new Map()

  for (const item of Array.isArray(list) ? list : []) {
    if (!isFolderLikeItem(item)) continue

    const id = pickFirstString(item, ['cid', 'fid', 'id', 'folder_id', 'file_id'])
    const name = pickFirstString(item, ['n', 'fn', 'name', 'folder_name', 'file_name'])
    if (!id || !name) continue
    if (id === '0') continue

    deduped.set(id, {
      id,
      name,
      isLeaf: false
    })
  }

  return Array.from(deduped.values())
}
