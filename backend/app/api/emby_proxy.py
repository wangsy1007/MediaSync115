"""Emby 代理端口上的 STRM 直链跳转（对齐 qmediasync emby302）。

1. 改写 PlaybackInfo：强制 DirectPlay，DirectStreamUrl=/Videos/{id}/stream?Static=true
2. 拦截 /Videos/*/stream：跟随 STRM/115/url 重定向拿到最终 CDN，307 给客户端
3. 最终若为 /api/proxy-115（本地代理）则回源 Emby
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse, parse_qs

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from app.services.playback_log_service import playback_log_service
from app.services.runtime_settings_service import runtime_settings_service
from app.utils.proxy import create_direct_httpx_client
from app.utils.request_utils import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emby", tags=["Emby代理"])

_PLAY_CONTEXT_CACHE_TTL_SECONDS = 300.0
_PLAY_CONTEXT_CACHE_MAX_ITEMS = 256
_play_context_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_play_context_cache_lock = asyncio.Lock()
_FINAL_LINK_CACHE_TTL_SECONDS = 600.0  # qmediasync: 10 分钟
_FINAL_LINK_CACHE_MAX_ITEMS = 256
_final_link_cache: dict[str, tuple[float, str]] = {}
_final_link_cache_lock = asyncio.Lock()

_EMBY_PATH_PREFIXES = (
    "/media/strm",
    "/strm",
    "/data/strm",
    "/app/strm",
)

# 永不匹配的黑名单占位（r"$^" 会在空 UA 上零宽匹配成功，误判为需跳过 → 空 UA
# 的 ISO 播放被 404 回源真实 Emby 触发转码卡顿，故用 (?!) 保证永不匹配）
_STREAM_REDIRECT_BLOCKLIST_UA = re.compile(r"(?!)")

_KNOWN_VIDEO_CONTAINERS = frozenset(
    {
        "mkv",
        "mp4",
        "m4v",
        "ts",
        "m2ts",
        "webm",
        "avi",
        "mov",
        "wmv",
        "flv",
        "rmvb",
        "rm",
        "mpg",
        "mpeg",
        "vob",
        "iso",
        "img",
    }
)


def _normalize_item_id(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("mediasource_"):
        text = text[len("mediasource_") :]
    return text


def _pick_media_source(
    item: dict[str, Any], media_source_id: str | None
) -> dict[str, Any] | None:
    sources = item.get("MediaSources")
    if not isinstance(sources, list):
        sources = []
    sources = [s for s in sources if isinstance(s, dict)]
    if not sources:
        return None

    wanted = str(media_source_id or "").strip()
    if wanted:
        for source in sources:
            sid = str(source.get("Id") or "").strip()
            if sid == wanted or sid == f"mediasource_{wanted}" or wanted.endswith(sid):
                return source
            path = str(source.get("Path") or "")
            if wanted in path:
                return source
    return sources[0]


def _map_emby_strm_path(emby_path: str) -> Path | None:
    text = str(emby_path or "").strip()
    if not text.lower().endswith(".strm"):
        return None

    root = Path(runtime_settings_service.get_strm_output_dir() or "/app/strm")
    normalized = text.replace("\\", "/")
    for prefix in _EMBY_PATH_PREFIXES:
        if normalized == prefix or normalized.startswith(prefix + "/"):
            relative = normalized[len(prefix) :].lstrip("/")
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                return None
            return candidate

    try:
        candidate = Path(normalized).resolve()
        candidate.relative_to(root.resolve())
        return candidate
    except Exception:
        return None


def _extract_play_url_from_text(raw: str) -> str:
    for line in str(raw or "").splitlines():
        url = line.strip()
        if url.startswith("http://") or url.startswith("https://"):
            return url
    return ""


def _is_strm_play_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    path = parsed.path or ""
    return (
        "/api/strm/play/" in path
        or "/api/115/url/" in path
        or path.endswith("/api/proxy-115")
        or "/api/proxy-115" in path
    )


def _is_local_proxy_url(url: str) -> bool:
    """最终链仍是本站网关/proxy-115 时，对齐 qmediasync 回源处理。"""
    text = str(url or "")
    return "/api/proxy-115" in text or "/api/strm/play/" in text


def _is_remote_http(url: str) -> bool:
    text = str(url or "").strip()
    return text.startswith("http://") or text.startswith("https://")


def extract_filename_from_play_token(play_url: str) -> str:
    """从旧 STRM token 或 /115/url/video.ext 路径读取扩展名线索。"""
    try:
        parsed = urlparse(play_url)
        path = parsed.path or ""
        if "/api/strm/play/" in path:
            from app.services.strm_service import strm_service

            token = strm_service._extract_token_from_url(play_url)
            payload = strm_service._decode_token(token)
            return str(payload.get("fn") or "").strip()
        # /api/115/url/video.iso → video.iso
        name = path.rsplit("/", 1)[-1]
        if name.startswith("video.") and "." in name:
            return name
    except Exception:
        return ""
    return ""


async def _lookup_index_source_filename(play_url: str) -> str:
    if not _is_strm_play_url(play_url):
        return ""
    try:
        from pathlib import PurePosixPath
        from urllib.parse import parse_qs

        from sqlalchemy import select

        from app.core.database import async_session_maker
        from app.models.strm_index import StrmFileIndex
        from app.services.strm_service import strm_service

        pick_code = ""
        parsed = urlparse(play_url)
        if "/api/115/url/" in (parsed.path or ""):
            pick_code = str((parse_qs(parsed.query).get("pickcode") or [""])[0]).strip()
        elif "/api/strm/play/" in (parsed.path or ""):
            token = strm_service._extract_token_from_url(play_url)
            payload = strm_service._decode_token(token)
            pick_code = str(payload.get("pc") or "").strip()
        if not pick_code:
            return ""
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(StrmFileIndex.relative_path)
                    .where(StrmFileIndex.pick_code == pick_code)
                    .limit(1)
                )
            ).scalar_one_or_none()
        if not row:
            return ""
        return PurePosixPath(str(row)).name
    except Exception:
        logger.debug("Failed to look up STRM index filename", exc_info=True)
        return ""


def resolve_source_container(
    source: dict[str, Any] | None,
    *,
    resolved_filename: str = "",
    play_url: str = "",
) -> str:
    for name in (
        str(resolved_filename or ""),
        extract_filename_from_play_token(play_url),
    ):
        ext = _extract_container_from_filename(name)
        if ext in _KNOWN_VIDEO_CONTAINERS:
            return ext
    container = str((source or {}).get("Container") or "").strip().lower()
    if container in _KNOWN_VIDEO_CONTAINERS:
        return container
    return ""


async def resolve_source_container_async(
    source: dict[str, Any] | None,
    *,
    play_url: str = "",
) -> str:
    resolved = extract_filename_from_play_token(play_url)
    if not resolved:
        resolved = await _lookup_index_source_filename(play_url)
    return resolve_source_container(
        source, resolved_filename=resolved, play_url=play_url
    )


def _should_skip_stream_redirect(user_agent: str) -> bool:
    return bool(_STREAM_REDIRECT_BLOCKLIST_UA.search(user_agent or ""))


def _play_context_cache_key(item_id: str, media_source_id: str | None) -> str:
    return f"{_normalize_item_id(item_id)}\0{str(media_source_id or '').strip()}"


async def _get_cached_play_context(
    item_id: str, *, media_source_id: str | None = None
) -> dict[str, Any] | None:
    key = _play_context_cache_key(item_id, media_source_id)
    now = time.monotonic()
    async with _play_context_cache_lock:
        cached = _play_context_cache.get(key)
        if not cached:
            return None
        expires_at, payload = cached
        if expires_at <= now:
            _play_context_cache.pop(key, None)
            return None
        return dict(payload)


async def _set_cached_play_context(
    item_id: str,
    *,
    media_source_id: str | None,
    context: dict[str, Any],
) -> None:
    if not context.get("play_url"):
        return
    key = _play_context_cache_key(item_id, media_source_id)
    now = time.monotonic()
    async with _play_context_cache_lock:
        if len(_play_context_cache) >= _PLAY_CONTEXT_CACHE_MAX_ITEMS:
            oldest_key = min(_play_context_cache.items(), key=lambda item: item[1][0])[0]
            _play_context_cache.pop(oldest_key, None)
        _play_context_cache[key] = (
            now + _PLAY_CONTEXT_CACHE_TTL_SECONDS,
            dict(context),
        )


async def resolve_stream_play_context_cached(
    item_id: str, *, media_source_id: str | None = None
) -> dict[str, Any]:
    cached = await _get_cached_play_context(
        item_id, media_source_id=media_source_id
    )
    if cached is not None:
        return cached
    context = await resolve_stream_play_context(
        item_id, media_source_id=media_source_id
    )
    await _set_cached_play_context(
        item_id, media_source_id=media_source_id, context=context
    )
    return context


def _extract_api_pairs_from_direct_url(direct_url: str) -> dict[str, str]:
    keep = {}
    try:
        query = dict(parse_qsl(urlparse(str(direct_url or "")).query, keep_blank_values=True))
    except Exception:
        return keep
    for key in ("api_key", "ApiKey", "X-Emby-Token", "x-emby-token"):
        value = str(query.get(key) or "").strip()
        if value:
            keep[key] = value
    return keep


def build_emby_style_direct_stream_url(
    *,
    item_id: str,
    media_source_id: str,
    original_direct_url: str = "",
    extra_query: dict[str, str] | None = None,
    container: str = "",
) -> str:
    """qmediasync 风格：/Videos/{id}/stream?MediaSourceId=...&Static=true（不加容器后缀）。"""
    params: dict[str, str] = {
        "MediaSourceId": media_source_id,
        "Static": "true",
    }
    params.update(_extract_api_pairs_from_direct_url(original_direct_url))
    if extra_query:
        for key, value in extra_query.items():
            if value:
                params[str(key)] = str(value)
    # 对齐 qmediasync：不加 .iso / .mkv 后缀
    _ = container  # 保留参数兼容旧调用，但不写入 URL 扩展名
    return f"/Videos/{item_id}/stream?{urlencode(params)}"


def _extract_container_from_filename(filename: str) -> str:
    name = str(filename or "").strip()
    if not name:
        return ""
    lower = name.lower()
    if lower.endswith(".strm"):
        lower = lower[: -len(".strm")]
    idx = lower.rfind(".")
    if idx < 0:
        return ""
    ext = lower[idx + 1 :]
    if not ext or len(ext) > 5 or not ext.isalnum():
        return ""
    return ext


async def _fetch_emby_item(item_id: str) -> dict[str, Any]:
    base_url = runtime_settings_service.get_emby_url().rstrip("/")
    api_key = runtime_settings_service.get_emby_api_key()
    if not base_url or not api_key:
        raise HTTPException(status_code=503, detail="Emby 未配置")

    url = f"{base_url}/emby/Items"
    params = {
        "Ids": item_id,
        "Fields": "Path,MediaSources,MediaStreams,Container",
        "api_key": api_key,
    }
    headers = {"X-Emby-Token": api_key}
    client = create_direct_httpx_client(timeout=httpx.Timeout(10.0, connect=5.0))
    try:
        response = await client.get(url, params=params, headers=headers)
    finally:
        await client.aclose()

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"查询 Emby 失败: HTTP {response.status_code}"
        )
    data = response.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Emby 返回无效数据")
    items = data.get("Items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=404, detail="Emby 条目不存在")
    item = items[0]
    if not isinstance(item, dict):
        raise HTTPException(status_code=502, detail="Emby 返回无效条目")
    return item


def resolve_local_strm_play_url(emby_path: str) -> str:
    local = _map_emby_strm_path(emby_path)
    if local is None or not local.is_file():
        return ""
    try:
        return _extract_play_url_from_text(local.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("读取 STRM 文件失败: %s", local)
        return ""


def extract_strm_play_url_from_source(
    source: dict[str, Any] | None, *, item_path: str = ""
) -> str:
    candidates = [
        str((source or {}).get("Path") or "").strip(),
        str(item_path or "").strip(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate.startswith("http://") or candidate.startswith("https://"):
            if _is_strm_play_url(candidate) or _is_remote_http(candidate):
                return candidate
            continue
        play_url = resolve_local_strm_play_url(candidate)
        if play_url:
            return play_url
    return ""


async def resolve_stream_play_context(
    item_id: str, *, media_source_id: str | None = None
) -> dict[str, Any]:
    normalized_id = _normalize_item_id(item_id)
    if not normalized_id:
        return {
            "play_url": "",
            "item_id": "",
            "title": "",
            "media_type": "",
            "series_name": "",
            "container": "",
        }

    item = await _fetch_emby_item(normalized_id)
    source = _pick_media_source(item, media_source_id)
    play_url = extract_strm_play_url_from_source(
        source, item_path=str(item.get("Path") or "")
    )
    container = ""
    if play_url:
        container = await resolve_source_container_async(source, play_url=play_url)
    return {
        "play_url": play_url,
        "item_id": normalized_id,
        "title": str(item.get("Name") or "").strip(),
        "media_type": str(item.get("Type") or "").strip(),
        "series_name": str(item.get("SeriesName") or "").strip(),
        "container": container,
    }


async def resolve_stream_redirect_url(
    item_id: str, *, media_source_id: str | None = None
) -> str:
    context = await resolve_stream_play_context(
        item_id, media_source_id=media_source_id
    )
    return str(context.get("play_url") or "")


def _apply_direct_play_rewrite(
    source: dict[str, Any],
    *,
    item_id: str,
    fallback_api_key: str = "",
    container: str = "",
) -> None:
    """对齐 qmediasync：强制 DirectPlay，DirectStreamUrl 指向 /Videos/.../stream。"""
    media_source_id = str(source.get("Id") or f"mediasource_{item_id}").strip()
    original_direct = str(source.get("DirectStreamUrl") or "")
    extra = {}
    if fallback_api_key and "api_key" not in _extract_api_pairs_from_direct_url(
        original_direct
    ):
        extra["api_key"] = fallback_api_key

    source["SupportsDirectPlay"] = True
    source["SupportsDirectStream"] = True
    source["SupportsTranscoding"] = False
    source["TranscodingUrl"] = None
    source["TranscodingSubProtocol"] = None
    source["TranscodingContainer"] = None
    if container:
        source["Container"] = container
    source["DirectStreamUrl"] = build_emby_style_direct_stream_url(
        item_id=str(item_id),
        media_source_id=media_source_id,
        original_direct_url=original_direct,
        extra_query=extra,
        container=container,
    )
    source.pop("TranscodingInfo", None)


def rewrite_playback_info_for_strm(
    payload: dict[str, Any],
    *,
    item_id: str,
    fallback_api_key: str = "",
    item_path: str = "",
) -> bool:
    sources = payload.get("MediaSources")
    if not isinstance(sources, list):
        return False

    changed = False
    for source in sources:
        if not isinstance(source, dict):
            continue
        play_url = extract_strm_play_url_from_source(source, item_path=item_path)
        if not play_url:
            continue
        container = resolve_source_container(source, play_url=play_url)
        _apply_direct_play_rewrite(
            source,
            item_id=str(item_id),
            fallback_api_key=fallback_api_key,
            container=container,
        )
        changed = True
    return changed


async def rewrite_playback_info_for_strm_async(
    payload: dict[str, Any],
    *,
    item_id: str,
    fallback_api_key: str = "",
    item_path: str = "",
    user_agent: str = "",
) -> bool:
    _ = user_agent
    sources = payload.get("MediaSources")
    if not isinstance(sources, list):
        return False

    changed = False
    for source in sources:
        if not isinstance(source, dict):
            continue
        play_url = extract_strm_play_url_from_source(source, item_path=item_path)
        if not play_url:
            continue
        container = await resolve_source_container_async(source, play_url=play_url)
        _apply_direct_play_rewrite(
            source,
            item_id=str(item_id),
            fallback_api_key=fallback_api_key,
            container=container,
        )
        changed = True
    return changed


def _filter_request_headers(request: Request) -> dict[str, str]:
    skip = {
        "host",
        "content-length",
        "connection",
        "transfer-encoding",
        "accept-encoding",
    }
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        if key.lower() in skip:
            continue
        headers[key] = value
    return headers


def _with_force_query(url: str) -> str:
    """对齐 qmediasync：对 /115/url 或 /115/newurl 追加 force=1。"""
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    path = parsed.path or ""
    if "/api/115/url/" not in path and "/115/url" not in path and "/115/newurl" not in path:
        # 旧 token 播放网关：直接解析，无需 force
        return url
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["force"] = ["1"]
    flat = [(k, v) for k, values in query.items() for v in values]
    return urlunparse(parsed._replace(query=urlencode(flat)))


def _extract_ua_from_headers(request_headers: dict[str, str] | None) -> str:
    """大小写不敏感地取出播放器 UA。"""
    for key, value in (request_headers or {}).items():
        if key.lower() == "user-agent":
            return str(value or "")
    return ""


async def get_final_redirect_link(
    origin_link: str,
    request_headers: dict[str, str] | None = None,
    *,
    player_ua: str = "",
) -> str:
    """服务端跟随重定向拿到最终 CDN（对齐 qmediasync getFinalRedirectLink）。

    关键：115 CDN 直链带 f=1 时会绑定申请时的 User-Agent。本函数申请直链所用的
    UA 必须与 HosPlayer 后续 307 直连 CDN 的真实 UA 一致，否则会被 115 限速。
    因此显式锁定 player_ua，并将其纳入缓存 key，避免不同播放器串用彼此的直链。
    """
    origin = str(origin_link or "").strip()
    if not origin:
        return origin

    # 显式播放器 UA 优先；否则从透传 header 中大小写不敏感提取
    effective_ua = str(player_ua or "").strip() or _extract_ua_from_headers(
        request_headers
    )

    follow_url = _with_force_query(origin)
    # 缓存按 (follow_url, UA) 区分：CDN 直链绑定 UA，不同 UA 不可共享同一条直链
    cache_key = f"{follow_url}\0{effective_ua}"
    now = time.monotonic()
    async with _final_link_cache_lock:
        cached = _final_link_cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

    # 透传 Range/Cookie/Referer；UA 单独强制为 effective_ua，防止 httpx 注入默认 UA
    headers = {}
    for key, value in (request_headers or {}).items():
        if key.lower() in {"range", "if-range", "cookie", "referer"}:
            headers[key] = value
    if effective_ua:
        headers["User-Agent"] = effective_ua

    try:
        # trust_env=False：不受 Docker 注入的 HTTP_PROXY 影响
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=20.0, trust_env=False
        ) as client:
            # 用 HEAD；部分 CDN 不支持 HEAD 时回退 GET Range。两条路径带同一 UA
            try:
                response = await client.head(follow_url, headers=headers)
                final_url = str(response.url)
                if response.status_code >= 400 or not final_url:
                    raise httpx.HTTPError(f"HEAD status={response.status_code}")
            except Exception:
                range_headers = dict(headers)
                range_headers["Range"] = "bytes=0-0"
                response = await client.get(follow_url, headers=range_headers)
                final_url = str(response.url)
    except Exception as exc:
        logger.warning("跟随重定向失败，回退原始链接: %s err=%s", origin[:120], exc)
        return origin

    async with _final_link_cache_lock:
        if len(_final_link_cache) >= _FINAL_LINK_CACHE_MAX_ITEMS:
            oldest_key = min(_final_link_cache.items(), key=lambda item: item[1][0])[0]
            _final_link_cache.pop(oldest_key, None)
        _final_link_cache[cache_key] = (now + _FINAL_LINK_CACHE_TTL_SECONDS, final_url)
    return final_url


async def _log_playback_start(
    *,
    request: Request,
    context: dict[str, Any],
    play_mode: str,
    path: str,
) -> None:
    try:
        await playback_log_service.log_playback(
            source="emby_proxy",
            title=str(context.get("title") or ""),
            media_type=str(context.get("media_type") or ""),
            series_name=str(context.get("series_name") or ""),
            item_id=str(context.get("item_id") or ""),
            player=request.headers.get("user-agent") or "",
            client_ip=get_client_ip(request),
            play_mode=play_mode,
            http_method=request.method,
            path=path,
        )
    except Exception:
        logger.exception("写入影视播放日志失败")


@router.api_route(
    "/stream-redirect/{item_id}",
    methods=["GET", "HEAD"],
)
async def emby_stream_redirect(
    item_id: str,
    request: Request,
    MediaSourceId: str | None = Query(default=None),
    mediaSourceId: str | None = Query(default=None),
) -> Response:
    """跟随 STRM/115/url 重定向，307 到最终 115 CDN（对齐 qmediasync）。"""
    ua = request.headers.get("user-agent") or ""
    if _should_skip_stream_redirect(ua):
        raise HTTPException(status_code=404, detail="ua_fallback")

    media_source_id = MediaSourceId or mediaSourceId
    try:
        context = await resolve_stream_play_context_cached(
            item_id, media_source_id=media_source_id
        )
        play_url = str(context.get("play_url") or "")
        if not play_url:
            raise HTTPException(status_code=404, detail="not_strm")

        # 远程 Path / STRM HTTP：服务端跟随拿到最终链
        if _is_remote_http(play_url):
            # 显式锁定播放器真实 UA：申请 115 直链绑定的 UA 必须与 HosPlayer
            # 307 后直连 CDN 的 UA 一致，否则 f=1 校验失败被限速。
            final_url = await get_final_redirect_link(
                play_url,
                _filter_request_headers(request),
                player_ua=ua,
            )
            if _is_local_proxy_url(final_url):
                # 对齐 qmediasync：含 proxy-115 → 回源 Emby（走 NAS）
                logger.info(
                    "Emby stream fallback origin (local proxy) item=%s url=%s",
                    item_id,
                    final_url[:120],
                )
                raise HTTPException(status_code=404, detail="local_proxy_origin")
            play_mode = "redirect"
        else:
            raise HTTPException(status_code=404, detail="not_remote_strm")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Emby stream redirect failed for item=%s", item_id)
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc

    if request.method == "GET":
        await _log_playback_start(
            request=request,
            context=context,
            play_mode=play_mode,
            path=request.url.path,
        )

    logger.info(
        "Emby stream 307 item=%s mode=%s -> %s ua=%s",
        item_id,
        play_mode,
        final_url[:160],
        ua[:80],
    )
    return RedirectResponse(url=final_url, status_code=307)


@router.api_route(
    "/playbackinfo/{item_id}",
    methods=["GET", "POST"],
)
async def emby_playbackinfo_proxy(item_id: str, request: Request) -> Response:
    """代理 PlaybackInfo，并对 STRM 强制 DirectPlay + qmediasync 风格 DirectStreamUrl。"""
    base_url = runtime_settings_service.get_emby_url().rstrip("/")
    api_key = runtime_settings_service.get_emby_api_key()
    if not base_url or not api_key:
        raise HTTPException(status_code=503, detail="Emby 未配置")

    upstream = f"{base_url}/emby/Items/{item_id}/PlaybackInfo"
    query = dict(request.query_params)
    if "api_key" not in query and api_key:
        query["api_key"] = api_key

    headers = _filter_request_headers(request)
    if "X-Emby-Token" not in headers and "x-emby-token" not in {
        k.lower() for k in headers
    }:
        headers["X-Emby-Token"] = api_key

    body = await request.body()
    client = create_direct_httpx_client(timeout=httpx.Timeout(30.0, connect=5.0))
    try:
        response = await client.request(
            request.method,
            upstream,
            params=query,
            headers=headers,
            content=body if body else None,
        )
        if response.status_code == 404:
            user_id = (
                query.get("UserId")
                or query.get("userId")
                or request.headers.get("X-Emby-User-Id")
            )
            if user_id:
                upstream2 = (
                    f"{base_url}/emby/Users/{user_id}/Items/{item_id}/PlaybackInfo"
                )
                response = await client.request(
                    request.method,
                    upstream2,
                    params=query,
                    headers=headers,
                    content=body if body else None,
                )
    finally:
        await client.aclose()

    content_type = response.headers.get("content-type") or ""
    if response.status_code >= 400:
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=content_type or "application/json",
        )

    try:
        payload = response.json()
    except Exception:
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=content_type or "application/octet-stream",
        )

    if isinstance(payload, dict):
        item_path = ""
        try:
            item = await _fetch_emby_item(str(item_id))
            item_path = str(item.get("Path") or "")
        except Exception:
            logger.debug("PlaybackInfo rewrite skipped item path lookup", exc_info=True)
        changed = await rewrite_playback_info_for_strm_async(
            payload,
            item_id=str(item_id),
            fallback_api_key=api_key,
            item_path=item_path,
            user_agent=request.headers.get("user-agent") or "",
        )
        if changed:
            logger.info(
                "Rewrote PlaybackInfo for item=%s to qmediasync-style DirectStreamUrl",
                item_id,
            )
        return JSONResponse(content=payload, status_code=response.status_code)

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=content_type or "application/json",
    )
