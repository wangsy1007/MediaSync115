import { ElMessage } from 'element-plus'

export const getDetailResourceName = (row, fallback = '资源') => {
  const name = String(row?.resource_name || row?.title || row?.name || fallback).trim()
  return name || fallback
}

export const notifyDetailTransferInProgress = () => {
  ElMessage.info('该资源正在转存中')
}

export const notifyDetailTransferStarted = (row) => {
  ElMessage.info(`正在转存「${getDetailResourceName(row)}」，请稍候...`)
}

export const notifyDetailOfflineInProgress = () => {
  ElMessage.info('该资源正在添加离线任务')
}

export const notifyDetailOfflineStarted = (row) => {
  ElMessage.info(`正在添加「${getDetailResourceName(row)}」到离线任务...`)
}
