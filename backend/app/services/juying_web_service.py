"""聚影网页会话适配器。

通过聚影普通用户网页所使用的 JSON 接口搜索影片、读取资源元数据，并在实际
转存前按需换取短时有效的 115 分享链接或磁力链接。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.utils.proxy import proxy_manager


logger = logging.getLogger(__name__)


class JuyingWebError(RuntimeError):
    """聚影网页接口调用失败。"""

    def __init__(self, message: str, *, code: str = "juying_web_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class _CacheEntry:
    expires_at: float
    value: Any


class JuyingWebService:
    """维护普通账号会话并适配聚影站内接口。"""

    _SEARCH_TTL_SECONDS = 15 * 60
    _EMPTY_TTL_SECONDS = 2 * 60
    _RESOURCE_TTL_SECONDS = 5 * 60
    _MAX_RESOURCE_PAGES = 10

    def __init__(self) -> None:
        self.base_url = "https://www.jying.top"
        self.username = ""
        self.password = ""
        self.enabled = False
        self.pan115_enabled = True
        self.magnet_enabled = True
        self._token = ""
        self._client = self._build_client()
        self._login_lock = asyncio.Lock()
        self._request_semaphore = asyncio.Semaphore(2)
        self._access_lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()
        self._search_cache: dict[str, _CacheEntry] = {}
        self._resource_cache: dict[str, _CacheEntry] = {}
        self._resource_context: dict[str, dict[str, Any]] = {}
        self._circuit_open_until = 0.0

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        cleaned = str(value or "").strip().rstrip("/")
        if not cleaned:
            return "https://www.jying.top"
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("聚影地址必须是有效的 HTTP/HTTPS 地址")
        return cleaned

    def _build_client(self) -> httpx.AsyncClient:
        return proxy_manager.create_httpx_client(
            base_url=self.base_url,
            timeout=30.0,
            follow_redirects=True,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": "MediaSync115-JuyingWeb/1.0",
            },
        )

    def configure(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        enabled: bool,
        pan115_enabled: bool = True,
        magnet_enabled: bool = True,
    ) -> None:
        normalized_url = self._normalize_base_url(base_url)
        next_username = str(username or "").strip()
        next_password = str(password or "")
        changed = (
            normalized_url != self.base_url
            or next_username != self.username
            or next_password != self.password
        )
        old_client = self._client if changed else None
        self.base_url = normalized_url
        self.username = next_username
        self.password = next_password
        self.enabled = bool(enabled)
        self.pan115_enabled = bool(pan115_enabled)
        self.magnet_enabled = bool(magnet_enabled)
        if changed:
            self._token = ""
            self._search_cache.clear()
            self._resource_cache.clear()
            self._resource_context.clear()
            self._client = self._build_client()
            if old_client is not None:
                try:
                    asyncio.get_running_loop().create_task(old_client.aclose())
                except RuntimeError:
                    pass

    async def close(self) -> None:
        await self._client.aclose()

    def is_configured(self) -> bool:
        return bool(self.username and self.password)

    def _ensure_available(self, *, allow_disabled: bool = False) -> None:
        if not allow_disabled and not self.enabled:
            raise JuyingWebError("聚影渠道未启用", code="juying_disabled")
        if not self.is_configured():
            raise JuyingWebError("聚影账号或密码未配置", code="juying_not_configured")
        if self._circuit_open_until > time.monotonic():
            raise JuyingWebError("聚影请求暂时受限，请稍后重试", code="juying_rate_limited")

    def _csrf_headers(self) -> dict[str, str]:
        token = str(self._client.cookies.get("csrftoken") or "")
        headers = {
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
        }
        if token:
            headers["X-CSRFToken"] = token
        return headers

    @staticmethod
    def _is_json_response(response: httpx.Response) -> bool:
        return "application/json" in str(response.headers.get("content-type") or "").lower()

    async def _login(self, *, force: bool = False, allow_disabled: bool = False) -> None:
        self._ensure_available(allow_disabled=allow_disabled)
        if self._token and not force:
            return
        async with self._login_lock:
            if self._token and not force:
                return
            csrf_response = await self._client.get("/api/csrf/")
            if csrf_response.status_code != 200:
                raise JuyingWebError(
                    f"聚影 CSRF 初始化失败（HTTP {csrf_response.status_code}）",
                    code="juying_login_failed",
                )
            response = await self._client.post(
                "/api/app/login/",
                json={"username": self.username, "password": self.password},
                headers=self._csrf_headers(),
            )
            if response.status_code != 200 or not self._is_json_response(response):
                raise JuyingWebError(
                    f"聚影登录失败（HTTP {response.status_code}）",
                    code="juying_login_failed",
                )
            payload = response.json()
            token = str(payload.get("token") or "").strip() if isinstance(payload, dict) else ""
            if not token:
                message = payload.get("message") if isinstance(payload, dict) else ""
                raise JuyingWebError(
                    str(message or "聚影登录未返回会话令牌"),
                    code="juying_login_failed",
                )
            self._token = token
            logger.info("聚影网页账号登录成功")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        retry_auth: bool = True,
        allow_disabled: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        await self._login(allow_disabled=allow_disabled)
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.update(self._csrf_headers())
        headers["X-App-User-Token"] = self._token

        async with self._request_semaphore:
            response = await self._client.request(method, path, headers=headers, **kwargs)

        refreshed = str(response.headers.get("x-refreshed-token") or "").strip()
        if refreshed:
            self._token = refreshed

        if response.status_code == 401 and retry_auth:
            self._token = ""
            await self._login(force=True, allow_disabled=allow_disabled)
            return await self._request(
                method,
                path,
                retry_auth=False,
                allow_disabled=allow_disabled,
                **kwargs,
            )

        if response.status_code == 429:
            retry_after = response.headers.get("retry-after") or ""
            try:
                seconds = max(60, min(600, int(float(retry_after))))
            except (TypeError, ValueError):
                seconds = 300
            self._circuit_open_until = time.monotonic() + seconds
            raise JuyingWebError("聚影请求过于频繁，已临时暂停该渠道", code="juying_rate_limited")

        if response.status_code >= 400:
            message = ""
            if self._is_json_response(response):
                try:
                    body = response.json()
                    message = str(body.get("message") or body.get("detail") or "")
                except Exception:
                    message = ""
            raise JuyingWebError(
                message or f"聚影请求失败（HTTP {response.status_code}）",
                code="juying_request_failed",
            )

        if not self._is_json_response(response):
            raise JuyingWebError(
                "聚影返回了非 JSON 页面，可能触发了站点验证或接口已改版",
                code="juying_schema_changed",
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise JuyingWebError("聚影返回数据格式异常", code="juying_schema_changed")
        return payload

    async def check_connection(self) -> dict[str, Any]:
        try:
            self._token = ""
            await self._login(force=True, allow_disabled=True)
            payload = await self._request(
                "GET", "/api/app/profile/", allow_disabled=True
            )
            user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
            return {
                "valid": True,
                "message": "聚影账号登录成功",
                "user": {
                    "username": str(user.get("username") or user.get("nickname") or ""),
                    "level": user.get("level"),
                },
            }
        except Exception as exc:
            return {
                "valid": False,
                "message": str(exc) or type(exc).__name__,
                "user": None,
            }

    @staticmethod
    def _fingerprint(value: Any) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").casefold())

    @classmethod
    def _movie_score(
        cls,
        row: dict[str, Any],
        *,
        title: str,
        year: str,
        media_type: str,
        tmdb_id: int | None,
    ) -> int:
        score = 0
        if tmdb_id and int(row.get("tmdb_id") or 0) == int(tmdb_id):
            score += 1000
        expected = cls._fingerprint(title)
        actual = cls._fingerprint(row.get("title"))
        if expected and actual == expected:
            score += 250
        elif expected and (expected in actual or actual in expected):
            score += 80
        row_year = str(row.get("release_year") or row.get("year") or "").strip()
        if year and row_year == str(year):
            score += 60
        row_type = str(row.get("movie_type") or "").strip().lower()
        if media_type == "tv" and row_type == "tv":
            score += 40
        elif media_type == "movie" and row_type in {"movie", "anime", "doc"}:
            score += 30
        return score

    async def _find_movie(
        self,
        *,
        title: str,
        year: str,
        media_type: str,
        tmdb_id: int | None,
        season: int | None,
    ) -> dict[str, Any] | None:
        query = str(title or "").strip()
        if media_type == "tv" and season:
            query = f"{query} S{int(season):02d}".strip()
        params: dict[str, Any] = {"q": query, "page": 1, "page_size": 30}
        if year:
            params["year"] = year
        payload = await self._request("GET", "/api/app/movies/", params=params)
        rows = payload.get("results") or []
        if not isinstance(rows, list) or not rows:
            if query != str(title or "").strip():
                params["q"] = str(title or "").strip()
                payload = await self._request("GET", "/api/app/movies/", params=params)
                rows = payload.get("results") or []
        candidates = [row for row in rows if isinstance(row, dict)]
        if not candidates:
            return None
        ranked = sorted(
            candidates,
            key=lambda row: self._movie_score(
                row,
                title=title,
                year=year,
                media_type=media_type,
                tmdb_id=tmdb_id,
            ),
            reverse=True,
        )
        best = ranked[0]
        if self._movie_score(
            best,
            title=title,
            year=year,
            media_type=media_type,
            tmdb_id=tmdb_id,
        ) < 200:
            return None
        return best

    async def _load_movie_resources(self, movie_id: int) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        page = 1
        while page <= self._MAX_RESOURCE_PAGES:
            page_size = 120 if page == 1 else 200
            payload = await self._request(
                "GET",
                f"/api/app/movie/{movie_id}/resources/",
                params={"page": page, "page_size": page_size},
            )
            rows = payload.get("resources") or []
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                resource_id = str(row.get("id") or "").strip()
                if not resource_id or resource_id in seen_ids:
                    continue
                seen_ids.add(resource_id)
                resources.append(row)
            if not payload.get("has_more"):
                break
            page += 1
        return resources

    @staticmethod
    def _public_resource(row: dict[str, Any]) -> dict[str, Any] | None:
        raw_type = str(row.get("resource_type") or "").strip()
        normalized_type = raw_type.casefold()
        if normalized_type == "115":
            resource_type = "115"
        elif normalized_type in {"magnetlink", "magnet"}:
            resource_type = "MagnetLink"
        else:
            return None
        resource_id = str(row.get("id") or "").strip()
        if not resource_id:
            return None
        title = str(
            row.get("title")
            or row.get("description")
            or row.get("resource_description")
            or f"聚影资源 #{resource_id}"
        ).strip()
        size = str(row.get("file_size") or "").strip()
        return {
            "id": f"juying-{resource_id}",
            "juying_resource_id": resource_id,
            "title": title,
            "name": title,
            "resource_name": title,
            "size": size,
            "file_size": size,
            "resource_type": resource_type,
            "source_service": "juying",
            "link_exposed": bool(row.get("link_exposed")),
            "link_hidden_reason": str(row.get("link_hidden_reason") or ""),
            "share_link": "",
            "magnet": "",
        }

    async def search_resources(
        self,
        *,
        title: str,
        year: str = "",
        media_type: str = "movie",
        tmdb_id: int | None = None,
        season: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        self._ensure_available()
        normalized_type = "tv" if str(media_type).lower() == "tv" else "movie"
        cache_key = "|".join(
            [normalized_type, str(tmdb_id or 0), self._fingerprint(title), str(year), str(season or 0)]
        )
        now = time.monotonic()
        if not force:
            cached = self._search_cache.get(cache_key)
            if cached and cached.expires_at > now:
                return cached.value

        async with self._cache_lock:
            if not force:
                cached = self._search_cache.get(cache_key)
                if cached and cached.expires_at > time.monotonic():
                    return cached.value
            movie = await self._find_movie(
                title=title,
                year=str(year or ""),
                media_type=normalized_type,
                tmdb_id=tmdb_id,
                season=season,
            )
            if not movie:
                result = {"movie": None, "list": [], "pan115": [], "magnets": []}
                self._search_cache[cache_key] = _CacheEntry(
                    time.monotonic() + self._EMPTY_TTL_SECONDS, result
                )
                return result

            movie_id = int(movie.get("id"))
            raw_resources = await self._load_movie_resources(movie_id)
            public_rows: list[dict[str, Any]] = []
            for raw in raw_resources:
                public = self._public_resource(raw)
                if public is None:
                    continue
                public_rows.append(public)
                rid = str(public["juying_resource_id"])
                self._resource_cache[rid] = _CacheEntry(
                    time.monotonic() + self._RESOURCE_TTL_SECONDS, raw
                )
                self._resource_context[rid] = {
                    "title": title,
                    "year": str(year or ""),
                    "media_type": normalized_type,
                    "tmdb_id": tmdb_id,
                    "season": season,
                }

            pan115 = [row for row in public_rows if row["resource_type"] == "115"]
            magnets = [row for row in public_rows if row["resource_type"] == "MagnetLink"]
            if not self.pan115_enabled:
                pan115 = []
            if not self.magnet_enabled:
                magnets = []
            result = {
                "movie": {
                    "id": movie_id,
                    "title": movie.get("title"),
                    "year": movie.get("release_year") or movie.get("year"),
                    "tmdb_id": movie.get("tmdb_id"),
                    "movie_type": movie.get("movie_type"),
                },
                "list": pan115 + magnets,
                "pan115": pan115,
                "magnets": magnets,
            }
            ttl = self._SEARCH_TTL_SECONDS if public_rows else self._EMPTY_TTL_SECONDS
            self._search_cache[cache_key] = _CacheEntry(time.monotonic() + ttl, result)
            logger.info(
                "聚影资源搜索完成 movie_id=%s tmdb_id=%s pan115=%s magnet=%s",
                movie_id,
                tmdb_id,
                len(pan115),
                len(magnets),
            )
            return result

    async def _reload_resource(self, resource_id: str) -> dict[str, Any] | None:
        context = self._resource_context.get(resource_id)
        if not context:
            return None
        await self.search_resources(**context, force=True)
        cached = self._resource_cache.get(resource_id)
        return cached.value if cached and cached.expires_at > time.monotonic() else None

    @staticmethod
    def _validate_target(resource_type: str, target: str) -> None:
        if resource_type == "115":
            parsed = urlparse(target)
            host = str(parsed.hostname or "").casefold()
            if parsed.scheme != "https" or not (host == "115.com" or host.endswith(".115.com") or host == "115cdn.com" or host.endswith(".115cdn.com")):
                raise JuyingWebError("聚影返回的 115 链接格式异常", code="juying_invalid_link")
        elif resource_type == "MagnetLink" and not target.casefold().startswith("magnet:?"):
            raise JuyingWebError("聚影返回的磁力链接格式异常", code="juying_invalid_link")

    async def resolve_resource(self, resource_id: str) -> dict[str, Any]:
        self._ensure_available()
        rid = str(resource_id or "").removeprefix("juying-").strip()
        cached = self._resource_cache.get(rid)
        raw = cached.value if cached and cached.expires_at > time.monotonic() else None
        if raw is None:
            raw = await self._reload_resource(rid)
        if not isinstance(raw, dict):
            raise JuyingWebError("聚影资源票据已失效，请重新搜索", code="juying_ticket_expired")
        if not raw.get("link_exposed"):
            raise JuyingWebError(
                str(raw.get("link_hidden_reason") or "当前账号不可访问该资源"),
                code="juying_link_hidden",
            )
        ticket = str(raw.get("access_ticket") or "").strip()
        if not ticket:
            raise JuyingWebError("聚影资源缺少访问票据", code="juying_ticket_expired")

        try:
            async with self._access_lock:
                payload = await self._request(
                    "POST",
                    f"/api/app/resource/{rid}/access/",
                    json={"access_ticket": ticket},
                )
        except JuyingWebError as exc:
            if exc.code != "juying_request_failed":
                raise
            refreshed_raw = await self._reload_resource(rid)
            refreshed_ticket = (
                str(refreshed_raw.get("access_ticket") or "").strip()
                if isinstance(refreshed_raw, dict)
                else ""
            )
            if not refreshed_ticket or refreshed_ticket == ticket:
                raise
            async with self._access_lock:
                payload = await self._request(
                    "POST",
                    f"/api/app/resource/{rid}/access/",
                    json={"access_ticket": refreshed_ticket},
                )
        target = str(payload.get("target") or "").strip()
        if not target:
            raise JuyingWebError("聚影资源链接为空", code="juying_empty_link")
        resource_type = "MagnetLink" if target.casefold().startswith("magnet:") else "115"
        self._validate_target(resource_type, target)
        return {
            "id": f"juying-{rid}",
            "juying_resource_id": rid,
            "resource_type": resource_type,
            "target": target,
            "share_link": target if resource_type == "115" else "",
            "magnet": target if resource_type == "MagnetLink" else "",
            "access_code": str(payload.get("access_code") or "").strip(),
            "extraction_code": str(payload.get("access_code") or "").strip(),
            "access_mode": str(payload.get("access_mode") or ""),
            "expires_in": int(payload.get("expires_in") or 0),
            "source_service": "juying",
        }

    @staticmethod
    def stable_magnet_id(magnet: str) -> str:
        digest = hashlib.sha256(str(magnet or "").encode("utf-8")).hexdigest()[:16]
        return f"juying-magnet-{digest}"


juying_web_service = JuyingWebService()
