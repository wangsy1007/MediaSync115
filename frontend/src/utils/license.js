/**
 * 许可证与功能门控工具。
 *
 * 当前阶段：所有功能对免费用户开放。
 * 将来收费时，后端 FEATURE_GATES 改为 TIER_PRO 即可限制功能。
 */
import { ref } from 'vue'
import { licenseApi } from '@/api'

/** 许可证状态（响应式，全局共享） */
const licenseStatus = ref({
  tier: 'free',
  has_license_key: false,
  features: {}
})

/** 是否已加载过 */
const loaded = ref(false)

/**
 * 从后端加载许可证状态。
 * 建议在 App 初始化或 Settings 页加载时调用。
 */
export async function loadLicenseStatus() {
  try {
    const { data } = await licenseApi.getStatus()
    licenseStatus.value = data
    loaded.value = true
  } catch {
    // 后端不可用时保持默认 free 状态
  }
  return licenseStatus.value
}

/**
 * 检查指定功能是否可用。
 * @param {string} feature - 功能标识（如 'explore', 'subscription'）
 * @returns {boolean}
 */
export function isFeatureAvailable(feature) {
  // 未加载时默认允许（免费阶段全部可用）
  if (!loaded.value) return true
  const available = licenseStatus.value.features[feature]
  // 未定义的功能默认可用
  return available !== false
}

/**
 * 获取当前等级。
 * @returns {'free' | 'pro'}
 */
export function getLicenseTier() {
  return licenseStatus.value.tier
}

/**
 * 是否为 Pro 用户。
 */
export function isPro() {
  return licenseStatus.value.tier === 'pro'
}

/**
 * 获取完整许可证状态（响应式 ref）。
 */
export function getLicenseStatus() {
  return licenseStatus
}
