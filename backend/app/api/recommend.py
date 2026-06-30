"""「猜你想看」AI 推荐 API。"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.services.operation_log_service import operation_log_service
from app.services.recommend_service import recommend_service
from app.services.runtime_settings_service import runtime_settings_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommend", tags=["AI 推荐"])

# 生成任务并发保护：避免手动刷新与定时任务同时跑
_refresh_lock = asyncio.Lock()


@router.get("")
async def get_recommendations():
    """读取缓存的推荐列表与新鲜度信息。"""
    return await recommend_service.get_cached()


@router.get("/status")
async def get_recommend_status():
    """返回推荐功能状态。"""
    cached = await recommend_service.get_cached()
    return {
        "enabled": cached.get("enabled"),
        "ready": cached.get("ready"),
        "generated_at": cached.get("generated_at"),
        "total": cached.get("total"),
        "error": cached.get("error"),
    }


@router.post("/refresh")
async def refresh_recommendations():
    """手动触发推荐刷新（强制重新生成）。"""
    if not runtime_settings_service.is_recommend_ready():
        raise HTTPException(
            status_code=400,
            detail="推荐功能未就绪：请在设置页配置并启用 LLM 与推荐。",
        )
    if _refresh_lock.locked():
        raise HTTPException(status_code=409, detail="推荐正在生成中，请稍后")
    async with _refresh_lock:
        try:
            result = await recommend_service.generate(force=True)
        except Exception as exc:
            logger.exception("手动刷新推荐失败")
            await operation_log_service.log_background_event(
                source_type="api",
                module="recommend",
                action="recommend.refresh.failed",
                status="failed",
                message=f"手动刷新 AI 推荐失败：{exc}",
            )
            raise HTTPException(status_code=500, detail=f"生成失败：{exc}")
        await operation_log_service.log_background_event(
            source_type="api",
            module="recommend",
            action="recommend.refresh.success",
            status="success",
            message=f"手动刷新 AI 推荐完成，共 {result.get('total') or 0} 条推荐",
        )
        return result
