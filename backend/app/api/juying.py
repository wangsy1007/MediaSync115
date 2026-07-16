"""聚影普通账号网页资源接口。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.services.juying_web_service import JuyingWebError, juying_web_service
from app.services.tmdb_service import tmdb_service


router = APIRouter(prefix="/juying", tags=["聚影"])


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, JuyingWebError):
        status = 429 if exc.code == "juying_rate_limited" else 400
        if exc.code in {"juying_request_failed", "juying_schema_changed"}:
            status = 502
        raise HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": str(exc)},
        )
    raise HTTPException(status_code=502, detail=f"聚影请求失败: {str(exc)}")


async def _media_context(tmdb_id: int, media_type: str) -> dict:
    if media_type == "tv":
        payload = await tmdb_service.get_tv_detail(tmdb_id)
        title = payload.get("name") or payload.get("title")
        date_value = payload.get("first_air_date") or payload.get("release_date")
    else:
        payload = await tmdb_service.get_movie_detail(tmdb_id)
        title = payload.get("title") or payload.get("name")
        date_value = payload.get("release_date") or payload.get("first_air_date")
    if not title:
        raise HTTPException(status_code=404, detail="未找到目标影视信息")
    return {
        "title": str(title),
        "year": str(date_value or "")[:4],
        "media_type": media_type,
        "tmdb_id": tmdb_id,
    }


@router.get("/{media_type}/{tmdb_id}/resources")
async def get_juying_resources(
    media_type: Literal["movie", "tv"],
    tmdb_id: int,
    season: int | None = Query(None, ge=1),
    resource_type: Literal["all", "115", "magnet"] = "all",
    refresh: bool = False,
):
    try:
        context = await _media_context(tmdb_id, media_type)
        result = await juying_web_service.search_resources(
            **context,
            season=season,
            force=refresh,
        )
        if resource_type == "115":
            rows = result.get("pan115") or []
        elif resource_type == "magnet":
            rows = result.get("magnets") or []
        else:
            rows = result.get("list") or []
        return {
            "id": tmdb_id,
            "media_type": media_type,
            "movie": result.get("movie"),
            "list": rows,
            "pan115_count": len(result.get("pan115") or []),
            "magnet_count": len(result.get("magnets") or []),
            "search_service": "juying",
        }
    except HTTPException:
        raise
    except Exception as exc:
        _raise_http(exc)


@router.post("/resource/{resource_id}/resolve")
async def resolve_juying_resource(resource_id: str):
    try:
        return await juying_web_service.resolve_resource(resource_id)
    except Exception as exc:
        _raise_http(exc)

