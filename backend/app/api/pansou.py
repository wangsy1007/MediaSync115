from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from app.services.pansou_service import pansou_service
from app.services.runtime_settings_service import runtime_settings_service
from typing import Optional, List, Union

router = APIRouter(prefix="/pansou", tags=["盘搜"])


class SearchRequest(BaseModel):
    """搜索请求"""
    keyword: str
    cloud_types: Union[str, List[str]] = "115"
    res: Optional[str] = "results"
    refresh: Optional[bool] = False


class PansouConfigRequest(BaseModel):
    """Pansou 配置请求"""
    base_url: str


@router.get("/health")
async def health_check(base_url: Optional[str] = None):
    """
    检查 pansou 服务健康状态。
    可传入 base_url 参数检测指定地址，不传则使用已保存的配置。
    """
    target = str(base_url or "").strip() or runtime_settings_service.get_pansou_base_url()
    result = await pansou_service.health_check(base_url=target)
    return result


@router.get("/config")
async def get_pansou_config():
    """获取 Pansou 配置（不做健康检查，快速返回）"""
    base_url = runtime_settings_service.get_pansou_base_url()
    return {
        "base_url": base_url,
        "health": None,
    }


@router.put("/config")
async def update_pansou_config(request: PansouConfigRequest):
    """更新 Pansou 配置（仅保存，不阻塞做健康检查）"""
    try:
        base_url = runtime_settings_service.update_pansou_base_url(request.base_url)
        pansou_service.set_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "base_url": base_url,
        "health": None,
    }


@router.post("/search")
async def search(request: SearchRequest):
    """
    搜索网盘资源

    - **keyword**: 搜索关键词（必填）
    - **cloud_types**: 网盘类型过滤 (baidu/aliyun/quark/xunlei/uc/115/tianyiyun/123 等)
    - **res**: 结果类型 (all/results/merge)
    - **refresh**: 是否强制刷新缓存
    """
    pansou_service.set_base_url(runtime_settings_service.get_pansou_base_url())
    result = await pansou_service.search(
        keyword=request.keyword,
        cloud_types=request.cloud_types,
        res=request.res,
        refresh=request.refresh
    )
    return result


@router.get("/search")
async def search_get(
    keyword: str = Query(..., description="搜索关键词"),
    cloud_types: str = Query("115", description="网盘类型过滤"),
    res: str = Query("results", description="结果类型"),
    refresh: bool = Query(False, description="是否强制刷新缓存")
):
    """
    搜索网盘资源 (GET)

    - **keyword**: 搜索关键词（必填）
    - **cloud_types**: 网盘类型过滤 (baidu/aliyun/quark/xunlei/uc/115/tianyiyun/123 等)
    - **res**: 结果类型 (all/results/merge)
    - **refresh**: 是否强制刷新缓存
    """
    pansou_service.set_base_url(runtime_settings_service.get_pansou_base_url())
    result = await pansou_service.search(
        keyword=keyword,
        cloud_types=cloud_types,
        res=res,
        refresh=refresh
    )
    return result
