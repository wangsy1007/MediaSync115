"""
许可证与功能门控服务。

当前阶段：所有功能对免费用户开放。
将来收费时，只需将 FEATURE_GATES 中对应功能的值改为 TIER_PRO，
即可要求用户输入有效的许可证密钥才能使用该功能。
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

TIER_FREE = "free"
TIER_PRO = "pro"

# ──────────────────────────────────────────────
# 功能门控配置
# 值为 TIER_FREE 表示免费可用；改为 TIER_PRO 即需付费
# ──────────────────────────────────────────────
FEATURE_GATES: dict[str, str] = {
    "explore":              TIER_FREE,   # 影视探索 / 首页导览
    "subscription":         TIER_FREE,   # 订阅管理
    "transfer":             TIER_FREE,   # 资源转存（手动 & 订阅）
    "scheduler":            TIER_FREE,   # 定时任务 / 调度器
    "workflow":             TIER_FREE,   # 工作流
    "hdhive":               TIER_FREE,   # HDHive 集成
    "telegram":             TIER_FREE,   # Telegram 集成
    "quality_preference":   TIER_FREE,   # 画质偏好排序
    "emby_sync":            TIER_FREE,   # Emby 同步
    "tg_bot":               TIER_FREE,   # Telegram Bot 推送
}


class LicenseService:
    """许可证管理与功能可用性检查。"""

    def __init__(self) -> None:
        self._license_key: str = ""

    # ── 许可证密钥管理 ──────────────────────────

    def set_license_key(self, key: str) -> None:
        self._license_key = (key or "").strip()

    def get_license_key(self) -> str:
        return self._license_key

    # ── 等级判断 ─────────────────────────────────

    def get_current_tier(self) -> str:
        """返回当前用户的等级。有有效密钥 → pro，否则 → free。"""
        if self._license_key and self._validate_key(self._license_key):
            return TIER_PRO
        return TIER_FREE

    def is_pro(self) -> bool:
        return self.get_current_tier() == TIER_PRO

    # ── 功能可用性检查 ───────────────────────────

    def is_feature_available(self, feature: str) -> bool:
        """检查指定功能对当前等级是否可用。"""
        required = FEATURE_GATES.get(feature, TIER_FREE)
        if required == TIER_FREE:
            return True
        return self.is_pro()

    def get_feature_status(self) -> dict[str, bool]:
        """返回所有功能的可用状态。"""
        return {f: self.is_feature_available(f) for f in FEATURE_GATES}

    def check_feature(self, feature: str) -> None:
        """
        检查功能是否可用，不可用则抛出 FeatureLockedError。
        在 API 层可 catch 后返回 HTTP 403。
        """
        if not self.is_feature_available(feature):
            raise FeatureLockedError(feature)

    # ── 许可证状态汇总 ───────────────────────────

    def get_status(self) -> dict[str, Any]:
        return {
            "tier": self.get_current_tier(),
            "has_license_key": bool(self._license_key),
            "features": self.get_feature_status(),
        }

    # ── 密钥验证（内部） ─────────────────────────

    @staticmethod
    def _validate_key(key: str) -> bool:
        """
        验证许可证密钥。
        TODO: 将来接入真实验证逻辑（签名校验 / 远程验证）。
        当前：只要密钥非空且长度 >= 16 即视为有效。
        """
        return bool(key and len(key.strip()) >= 16)


class FeatureLockedError(Exception):
    """功能未解锁异常。"""

    def __init__(self, feature: str) -> None:
        self.feature = feature
        label = FEATURE_GATES.get(feature, feature)
        super().__init__(f"此功能需要 Pro 许可证：{feature}")


# 单例
license_service = LicenseService()
