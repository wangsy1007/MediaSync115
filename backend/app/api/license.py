"""许可证相关 API 端点。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.license_service import license_service, FeatureLockedError

router = APIRouter(prefix="/license", tags=["license"])


class LicenseKeyRequest(BaseModel):
    license_key: Optional[str] = None


@router.get("/status")
async def get_license_status():
    """获取当前许可证状态与功能可用性。"""
    return license_service.get_status()


@router.put("/activate")
async def activate_license(request: LicenseKeyRequest):
    """激活许可证密钥。"""
    key = (request.license_key or "").strip()
    license_service.set_license_key(key)

    # 同步到 runtime_settings 持久化
    from app.services.runtime_settings_service import runtime_settings_service
    runtime_settings_service.update_bulk({"license_key": key})

    status = license_service.get_status()
    if key and not status["has_license_key"]:
        raise HTTPException(status_code=400, detail="许可证密钥格式无效")

    return {
        "success": True,
        **status,
    }


@router.post("/check-feature")
async def check_feature(feature: str):
    """检查指定功能是否可用。"""
    try:
        license_service.check_feature(feature)
        return {"available": True, "feature": feature}
    except FeatureLockedError:
        raise HTTPException(
            status_code=403,
            detail=f"此功能需要 Pro 许可证才能使用: {feature}",
        )
