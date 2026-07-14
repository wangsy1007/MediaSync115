"""对齐 qmediasync 的 115 直链解析与本地反代。

- GET /api/115/url/video{ext}?pickcode=...&force=0|1
- GET|HEAD /api/proxy-115?url=...
"""

from __future__ import annotations

import logging
from urllib.parse import quote, urlparse

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.services.runtime_settings_service import runtime_settings_service
from app.services.strm_service import strm_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["115直链播放"])

# 本地反代时使用固定 UA（对齐 qmediasync DEFAULTUA 思路）
PROXY_115_DEFAULT_UA = "MediaSync115/1.0"


def _normalize_ext(ext: str) -> str:
    text = str(ext or "").strip().lower()
    if not text:
        return ".mp4"
    if not text.startswith("."):
        text = f".{text}"
    # 限制扩展名长度，避免路径注入
    body = text[1:]
    if not body or len(body) > 8 or not body.isalnum():
        return ".mp4"
    return f".{body}"


def _should_use_local_proxy(*, force: int) -> bool:
    """force=0 且 strm 模式为 proxy 时，走本地反代。"""
    if int(force or 0) != 0:
        return False
    mode = runtime_settings_service.get_strm_redirect_mode()
    return mode == "proxy"


@router.api_route(
    "/115/url/video.{ext}",
    methods=["GET", "HEAD"],
)
async def get_115_url_by_pickcode(
    ext: str,
    request: Request,
    pickcode: str = Query(..., min_length=1, description="115 pickcode"),
    force: int = Query(0, description="1=强制 302 到 CDN；0 时若开启本地代理则走 proxy-115"),
) -> Response:
    """按 UA 解析 115 直链并 302（对齐 qmediasync /115/url）。"""
    pick_code = str(pickcode or "").strip()
    if not pick_code:
        raise HTTPException(status_code=400, detail="缺少 pickcode")

    use_local_proxy = _should_use_local_proxy(force=force)
    player_ua = request.headers.get("user-agent") or ""
    bind_ua = PROXY_115_DEFAULT_UA if use_local_proxy else player_ua

    try:
        info = await strm_service._fetch_pick_code_download_info(
            pick_code, user_agent=bind_ua
        )
    except Exception as exc:
        logger.exception("115 url resolve failed pickcode=%s", pick_code)
        raise HTTPException(status_code=502, detail=f"获取 115 下载地址失败: {exc}") from exc

    download_url = str(info.get("download_url") or "").strip()
    if not download_url:
        raise HTTPException(status_code=502, detail="未能解析 115 下载地址")

    normalized_ext = _normalize_ext(ext)
    if use_local_proxy:
        # 相对路径，客户端会打到当前 Emby 代理主机
        target = f"/api/proxy-115?url={quote(download_url, safe='')}"
        logger.info(
            "115 url -> local proxy ext=%s pickcode=%s force=%s",
            normalized_ext,
            pick_code,
            force,
        )
        return RedirectResponse(url=target, status_code=302)

    logger.info(
        "115 url -> CDN ext=%s pickcode=%s force=%s",
        normalized_ext,
        pick_code,
        force,
    )
    return RedirectResponse(url=download_url, status_code=302)


@router.api_route(
    "/proxy-115",
    methods=["GET", "HEAD"],
)
async def proxy_115_cdn(
    request: Request,
    url: str = Query(..., min_length=1, description="115 CDN 直链"),
) -> Response:
    """Range 反代 115 CDN（对齐 qmediasync /proxy-115）。"""
    target = str(url or "").strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        raise HTTPException(status_code=400, detail="url 必须是 http(s) 地址")

    parsed = urlparse(target)
    host = (parsed.hostname or "").lower()
    # 粗略限制：仅允许 115 CDN / 常见网盘域名，避免开放代理
    allowed_suffixes = (
        "115cdn.net",
        "115.com",
        "acgvideo.com",
    )
    if not any(host == s or host.endswith("." + s) for s in allowed_suffixes):
        raise HTTPException(status_code=403, detail="仅允许反代 115 CDN 链接")

    filename = (parsed.path.rsplit("/", 1)[-1] or "video").split("?")[0] or "video"
    request_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in {"range", "if-range", "cookie", "referer"}
    }
    # 固定 UA，与申请直链时 bind_ua 一致
    required_headers = {"User-Agent": PROXY_115_DEFAULT_UA}

    try:
        return await strm_service._build_proxy_response(
            method=request.method,
            download_url=target,
            filename=filename,
            required_headers=required_headers,
            request_headers=request_headers,
        )
    except Exception as exc:
        logger.exception("proxy-115 failed")
        raise HTTPException(status_code=502, detail=f"反代失败: {exc}") from exc
