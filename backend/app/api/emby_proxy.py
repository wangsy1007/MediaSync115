"""Emby 代理端口上的 STRM 直链跳转。

对齐 MediaWarp 的成功路径：
1. 改写 PlaybackInfo：强制 DirectPlay，DirectStreamUrl 仍指向 /videos/{id}/stream
2. 拦截 /videos/*/stream：按客户端 UA 解析 115 直链，单次 302（避免双重跳转）
3. HosPlayer 等不跟随 302 的客户端回退 Emby 中转
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from app.services.playback_log_service import playback_log_service
from app.services.runtime_settings_service import runtime_settings_service
from app.utils.proxy import create_direct_httpx_client
from app.utils.request_utils import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emby", tags=["Emby代理"])

_EMBY_PATH_PREFIXES = (
    "/media/strm",
    "/strm",
    "/data/strm",
    "/app/strm",
)

# 直链已按客户端 UA 解析（115 CDN 绑定 UA），绝大多数播放器都能跟随 302。
# 仅保留确认无法跟随 302 的客户端；目前为空。
_STREAM_REDIRECT_BLOCKLIST_UA = re.compile(
    r"$^",
)

# 已知的视频容器扩展名（用于从真实源文件名回填 Container 信息，
# 让 VidHub/SenPlayer 等客户端正确识别 ISO 原盘并以磁盘镜像方式播放）。
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
    return "/api/strm/play/" in (parsed.path or "")


def extract_filename_from_play_token(play_url: str) -> str:
    """从 STRM 播放令牌中读取源文件名（若生成时已写入）。"""
    if not _is_strm_play_url(play_url):
        return ""
    try:
        from app.services.strm_service import strm_service

        token = strm_service._extract_token_from_url(play_url)
        payload = strm_service._decode_token(token)
        return str(payload.get("fn") or "").strip()
    except Exception:
        return ""


def _collect_source_name_candidates(
    source: dict[str, Any] | None,
    *,
    item_path: str = "",
    play_url: str = "",
) -> list[str]:
    names: list[str] = []
    for value in (
        str((source or {}).get("Path") or "").strip(),
        str(item_path or "").strip(),
        extract_filename_from_play_token(play_url),
    ):
        if value and value not in names:
            names.append(value)
    local = _map_emby_strm_path(str((source or {}).get("Path") or item_path or ""))
    if local is not None:
        local_name = local.name
        if local_name and local_name not in names:
            names.append(local_name)
    return names


async def _lookup_index_source_filename(play_url: str) -> str:
    """通过 STRM 索引库反查源文件名（旧令牌不含 fn 时使用）。"""
    if not _is_strm_play_url(play_url):
        return ""
    try:
        from pathlib import PurePosixPath

        from sqlalchemy import select

        from app.core.database import async_session_maker
        from app.models.strm_index import StrmFileIndex
        from app.services.strm_service import strm_service

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
    """确定 STRM 源的真实容器格式（如 iso/mkv），供客户端识别。

    优先级：真实源文件名扩展名 > 令牌 fn > Emby 探测到的 Container。
    """
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


def _should_proxy_disc_stream(container: str) -> bool:
    """ISO/IMG 原盘会频繁 Range 寻址，302 每次换链会导致严重限速。"""
    return str(container or "").strip().lower() in {"iso", "img"}


def _extract_api_pairs_from_direct_url(direct_url: str) -> dict[str, str]:
    """从原始 DirectStreamUrl 里保留 api_key / X-Emby-Token 等鉴权参数。"""
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
    """MediaWarp 风格：让客户端继续请求 /videos/{id}/stream，再由代理 302。

    container 非空时生成 /Videos/{id}/stream.{container}，让客户端从 URL
    扩展名感知真实格式（对 ISO 原盘尤其重要）。
    """
    params: dict[str, str] = {
        "MediaSourceId": media_source_id,
        "Static": "true",
    }
    params.update(_extract_api_pairs_from_direct_url(original_direct_url))
    if extra_query:
        for key, value in extra_query.items():
            if value:
                params[str(key)] = str(value)
    ext = str(container or "").strip().lstrip(".").lower()
    suffix = f".{ext}" if ext else ""
    # MediaWarp / Emby 客户端习惯大写 Videos
    return f"/Videos/{item_id}/stream{suffix}?{urlencode(params)}"


def _extract_container_from_filename(filename: str) -> str:
    """从真实源文件名提取容器扩展名（不含点）。"""
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
            if _is_strm_play_url(candidate):
                return candidate
            continue
        play_url = resolve_local_strm_play_url(candidate)
        if play_url:
            return play_url
    return ""


async def resolve_stream_play_context(
    item_id: str, *, media_source_id: str | None = None
) -> dict[str, Any]:
    """解析 Emby 条目播放上下文（含片名等元数据）。"""
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
        container = await resolve_source_container_async(
            source, play_url=play_url
        )
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
    """解析 Emby 条目对应的 STRM 播放地址；非 STRM 返回空字符串。"""
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
    """把单个 MediaSource 改写成强制 DirectPlay + 代理 302 的形式。"""
    media_source_id = str(source.get("Id") or f"mediasource_{item_id}").strip()
    original_direct = str(source.get("DirectStreamUrl") or "")
    extra = {}
    if fallback_api_key and "api_key" not in _extract_api_pairs_from_direct_url(
        original_direct
    ):
        extra["api_key"] = fallback_api_key

    # 对齐 MediaWarp：不改 Path（避免 Emby/客户端用 Lavf 去探网关），
    # 只改 DirectStreamUrl 为 /Videos/{id}/stream.{container}，由代理再 302。
    # 回填真实 Container（尤其 iso），VidHub/SenPlayer 等按容器选择解封装方式。
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
    """强制 STRM DirectPlay（同步版，容器信息仅取自令牌 fn / Emby 探测）。"""
    sources = payload.get("MediaSources")
    if not isinstance(sources, list):
        return False

    changed = False
    for source in sources:
        if not isinstance(source, dict):
            continue
        play_url = extract_strm_play_url_from_source(
            source, item_path=item_path
        )
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
) -> bool:
    """异步版 PlaybackInfo 改写，可回查 STRM 索引库确定真实容器（ISO 等）。"""
    sources = payload.get("MediaSources")
    if not isinstance(sources, list):
        return False

    changed = False
    for source in sources:
        if not isinstance(source, dict):
            continue
        play_url = extract_strm_play_url_from_source(
            source, item_path=item_path
        )
        if not play_url:
            continue
        container = await resolve_source_container_async(
            source, play_url=play_url
        )
        if container == "iso":
            logger.info(
                "Rewriting ISO source for direct play item=%s container=%s",
                item_id,
                container,
            )
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


async def _resolve_final_redirect_url(play_url: str, *, user_agent: str) -> str:
    """把 STRM 网关地址解析成最终 115 CDN，避免客户端需要跟两次 302。"""
    from app.services.strm_service import strm_service

    if not _is_strm_play_url(play_url):
        return play_url

    token = strm_service._extract_token_from_url(play_url)
    info = await strm_service.resolve_download_url_with_ua(
        token, user_agent=user_agent
    )
    if info.get("mode") == "proxy":
        # 需要 Cookie 的链接无法裸 302，退回网关由服务端代理
        return play_url
    return str(info.get("download_url") or play_url)


async def _resolve_final_redirect_info(
    play_url: str, *, user_agent: str
) -> tuple[str, str]:
    """返回 (最终跳转地址, play_mode)。"""
    final_url = await _resolve_final_redirect_url(play_url, user_agent=user_agent)
    play_mode = "proxy" if _is_strm_play_url(final_url) else "redirect"
    return final_url, play_mode


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
    """将 Emby stream 请求 302 到 115 直链（单跳）。"""
    ua = request.headers.get("user-agent") or ""
    if _should_skip_stream_redirect(ua):
        logger.info(
            "Skip stream 302 for UA=%s item=%s, fallback to Emby",
            ua[:80],
            item_id,
        )
        raise HTTPException(status_code=404, detail="ua_fallback")

    media_source_id = MediaSourceId or mediaSourceId
    try:
        context = await resolve_stream_play_context(
            item_id, media_source_id=media_source_id
        )
        play_url = str(context.get("play_url") or "")
        if not play_url:
            raise HTTPException(status_code=404, detail="not_strm")

        container = str(context.get("container") or "").strip().lower()
        if _should_proxy_disc_stream(container):
            from app.services.strm_service import strm_service

            token = strm_service._extract_token_from_url(play_url)
            if request.method == "GET":
                await _log_playback_start(
                    request=request,
                    context=context,
                    play_mode="proxy",
                    path=request.url.path,
                )
            logger.info(
                "Emby stream proxy (disc image) item=%s container=%s ua=%s",
                item_id,
                container,
                ua[:80],
            )
            return await strm_service.resolve_play_response_with_headers(
                token=token,
                method=request.method,
                request_headers=_filter_request_headers(request),
                client_ip=get_client_ip(request),
                request_path=request.url.path,
                force_proxy=True,
            )

        final_url, play_mode = await _resolve_final_redirect_info(
            play_url, user_agent=ua
        )
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
        "Emby stream redirect item=%s -> %s ua=%s",
        item_id,
        final_url[:160],
        ua[:80],
    )
    return RedirectResponse(url=final_url, status_code=302)


@router.api_route(
    "/playbackinfo/{item_id}",
    methods=["GET", "POST"],
)
async def emby_playbackinfo_proxy(item_id: str, request: Request) -> Response:
    """代理 PlaybackInfo，并对 STRM 强制 DirectPlay + Emby 风格 DirectStreamUrl。"""
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
        )
        if changed:
            logger.info(
                "Rewrote PlaybackInfo for item=%s to MediaWarp-style DirectStreamUrl",
                item_id,
            )
        return JSONResponse(content=payload, status_code=response.status_code)

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=content_type or "application/json",
    )
