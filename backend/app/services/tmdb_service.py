import asyncio
import time
from typing import Any

import httpx

from app.core.config import settings
from app.utils.proxy import proxy_manager

_TMDB_CACHE_TTL_SECONDS = 60 * 60
_TMDB_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TMDB_CACHE_LOCK = asyncio.Lock()
_TMDB_HTTP_CLIENT: httpx.AsyncClient | None = None
_TMDB_HTTP_CLIENT_LOCK = asyncio.Lock()


async def _get_tmdb_http_client(*, verify: bool = True) -> httpx.AsyncClient:
    global _TMDB_HTTP_CLIENT
    if verify:
        async with _TMDB_HTTP_CLIENT_LOCK:
            if _TMDB_HTTP_CLIENT is None or _TMDB_HTTP_CLIENT.is_closed:
                _TMDB_HTTP_CLIENT = proxy_manager.create_httpx_client(
                    timeout=15.0, http2=True
                )
            return _TMDB_HTTP_CLIENT
    return proxy_manager.create_httpx_client(timeout=15.0, http2=True, verify=False)


class TmdbService:
    def _required_params(self, page: int | None = None) -> dict[str, Any]:
        if not settings.TMDB_API_KEY:
            raise ValueError("TMDB_API_KEY is not configured")

        params: dict[str, Any] = {
            "api_key": settings.TMDB_API_KEY,
            "language": settings.TMDB_LANGUAGE,
            "region": settings.TMDB_REGION,
        }
        if page is not None:
            params["page"] = page
        return params

    @staticmethod
    def _check_api_key_error(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise ValueError("TMDB API Key 无效，请前往设置页重新配置正确的 API Key")
        if response.status_code == 403:
            raise ValueError("TMDB API Key 权限不足或已被禁用，请检查后重新配置")

    async def _request_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        client = await _get_tmdb_http_client()
        try:
            response = await client.get(url, params=params)
            self._check_api_key_error(response)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except ValueError:
            raise
        except Exception as exc:
            # Some environments/proxies present a mismatched certificate for TMDB.
            # Fallback once with verify=False to keep subscription/detail flows available.
            if not self._is_tls_hostname_error(exc):
                raise

        insecure_client = await _get_tmdb_http_client(verify=False)
        try:
            response = await insecure_client.get(url, params=params)
            self._check_api_key_error(response)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        finally:
            if insecure_client is not _TMDB_HTTP_CLIENT:
                await insecure_client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{settings.TMDB_BASE_URL}{path}"
        return await self._request_json(url, params)

    @staticmethod
    def _format_configuration_result(payload: dict[str, Any]) -> dict[str, Any]:
        image_config = payload.get("images")
        change_keys = payload.get("change_keys")
        return {
            "images_configured": isinstance(image_config, dict) and bool(image_config),
            "change_keys_count": len(change_keys)
            if isinstance(change_keys, list)
            else 0,
            "configuration": payload,
        }

    async def check_connection(self) -> dict[str, Any]:
        """Validate TMDB API connectivity with a lightweight real API request."""
        payload = await self._get("/configuration", self._required_params())
        return self._format_configuration_result(payload)

    async def check_connection_with_config(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        language: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """使用指定配置检测 TMDB API Key 是否可用（无需先保存）。"""
        normalized_key = str(api_key or "").strip()
        if not normalized_key:
            raise ValueError("TMDB API Key 未配置")

        resolved_base = str(
            base_url or settings.TMDB_BASE_URL or "https://api.themoviedb.org/3"
        ).strip().rstrip("/")
        params: dict[str, Any] = {
            "api_key": normalized_key,
            "language": str(language or settings.TMDB_LANGUAGE or "zh-CN").strip(),
            "region": str(region or settings.TMDB_REGION or "CN").strip(),
        }
        url = f"{resolved_base}/configuration"
        payload = await self._request_json(url, params)
        return self._format_configuration_result(payload)

    @staticmethod
    def _is_tls_hostname_error(exc: Exception) -> bool:
        text = str(exc or "").lower()
        if not text:
            return False
        tokens = (
            "certificate_verify_failed",
            "hostname mismatch",
            "certificate verify failed",
            "ssl",
        )
        return any(token in text for token in tokens)

    async def _get_cached(
        self, cache_key: str, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        now = time.time()
        async with _TMDB_CACHE_LOCK:
            cached = _TMDB_CACHE.get(cache_key)
            if cached and cached[0] > now:
                return dict(cached[1])

        result = await self._get(path, params)

        async with _TMDB_CACHE_LOCK:
            _TMDB_CACHE[cache_key] = (
                time.time() + _TMDB_CACHE_TTL_SECONDS,
                dict(result),
            )
            if len(_TMDB_CACHE) > 2000:
                oldest_key = min(_TMDB_CACHE.items(), key=lambda item: item[1][0])[0]
                _TMDB_CACHE.pop(oldest_key)

        return result

    async def search_multi(self, query: str, page: int = 1) -> dict[str, Any]:
        params = self._required_params(page=page)
        params["query"] = query
        params["include_adult"] = False

        payload = await self._get("/search/multi", params)
        raw_items = (
            payload.get("results") if isinstance(payload.get("results"), list) else []
        )

        items: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            media_type = str(raw.get("media_type") or "").strip().lower()
            if media_type not in {"movie", "tv", "collection", "person"}:
                continue

            title = raw.get("title") or raw.get("name") or ""
            profile_path = str(raw.get("profile_path") or "").strip()
            poster_path = str(raw.get("poster_path") or "").strip()
            if media_type == "person" and profile_path:
                poster_path = profile_path
            item = {
                "id": raw.get("id"),
                "tmdb_id": raw.get("id"),
                "media_type": media_type,
                "title": title,
                "name": title,
                "overview": raw.get("overview") or "",
                "poster_path": poster_path,
                "profile_path": profile_path,
                "known_for_department": raw.get("known_for_department") or "",
                "vote_average": raw.get("vote_average"),
                "release_date": raw.get("release_date") or "",
                "first_air_date": raw.get("first_air_date") or "",
                "source_service": "tmdb",
            }
            items.append(item)

        return {
            "query": query,
            "page": payload.get("page") or page,
            "total_pages": payload.get("total_pages") or (1 if items else 0),
            "total_results": payload.get("total_results") or len(items),
            "items": items,
            "results": items,
            "search_service": "tmdb",
            "search_services": ["tmdb"] if items else [],
            "source_counts": {"tmdb": len(items)} if items else {},
            "fallback_used": False,
            "attempts": [{"service": "tmdb", "status": "ok", "count": len(items)}],
        }

    async def search_by_media_type(
        self,
        query: str,
        media_type: str,
        page: int = 1,
        year: int | None = None,
    ) -> dict[str, Any]:
        normalized_type = "tv" if media_type == "tv" else "movie"
        params = self._required_params(page=page)
        params["query"] = query
        params["include_adult"] = False
        if isinstance(year, int) and year > 1800:
            if normalized_type == "movie":
                params["primary_release_year"] = year
            else:
                params["first_air_date_year"] = year

        payload = await self._get(f"/search/{normalized_type}", params)
        raw_items = (
            payload.get("results") if isinstance(payload.get("results"), list) else []
        )

        items: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            title = raw.get("title") or raw.get("name") or ""
            item = {
                "id": raw.get("id"),
                "tmdb_id": raw.get("id"),
                "media_type": normalized_type,
                "title": title,
                "name": title,
                "overview": raw.get("overview") or "",
                "poster_path": raw.get("poster_path") or "",
                "vote_average": raw.get("vote_average"),
                "release_date": raw.get("release_date") or "",
                "first_air_date": raw.get("first_air_date") or "",
                "source_service": "tmdb",
            }
            items.append(item)

        return {
            "query": query,
            "page": payload.get("page") or page,
            "total_pages": payload.get("total_pages") or (1 if items else 0),
            "total_results": payload.get("total_results") or len(items),
            "items": items,
            "results": items,
            "search_service": "tmdb",
            "search_services": ["tmdb"] if items else [],
            "source_counts": {"tmdb": len(items)} if items else {},
            "fallback_used": False,
            "attempts": [{"service": "tmdb", "status": "ok", "count": len(items)}],
        }

    async def find_by_external_id(
        self, external_id: str, external_source: str
    ) -> dict[str, Any]:
        normalized_id = str(external_id or "").strip()
        if not normalized_id:
            return {
                "external_id": "",
                "external_source": external_source,
                "items": [],
                "results": [],
            }

        params = self._required_params()
        params["external_source"] = str(external_source or "").strip()
        payload = await self._get(f"/find/{normalized_id}", params)

        items: list[dict[str, Any]] = []
        for media_key, media_type in (
            ("movie_results", "movie"),
            ("tv_results", "tv"),
            ("person_results", "person"),
            ("tv_episode_results", "tv"),
            ("tv_season_results", "tv"),
        ):
            rows = payload.get(media_key)
            if not isinstance(rows, list):
                continue
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                title = raw.get("title") or raw.get("name") or ""
                items.append(
                    {
                        "id": raw.get("id"),
                        "tmdb_id": raw.get("id"),
                        "media_type": media_type,
                        "title": title,
                        "name": title,
                        "overview": raw.get("overview") or "",
                        "poster_path": raw.get("poster_path") or "",
                        "vote_average": raw.get("vote_average"),
                        "release_date": raw.get("release_date") or "",
                        "first_air_date": raw.get("first_air_date") or "",
                        "source_service": "tmdb_find",
                    }
                )

        return {
            "external_id": normalized_id,
            "external_source": params["external_source"],
            "items": items,
            "results": items,
            "raw": payload,
        }

    async def get_movie_external_ids(self, tmdb_id: int) -> dict[str, Any]:
        params = self._required_params()
        return await self._get(f"/movie/{tmdb_id}/external_ids", params)

    async def get_tv_external_ids(self, tmdb_id: int) -> dict[str, Any]:
        params = self._required_params()
        return await self._get(f"/tv/{tmdb_id}/external_ids", params)

    async def get_movie_detail(self, tmdb_id: int) -> dict[str, Any]:
        params = self._required_params()
        params["append_to_response"] = "credits,release_dates,videos,external_ids"
        cache_key = f"movie:{tmdb_id}"
        return await self._get_cached(cache_key, f"/movie/{tmdb_id}", params)

    async def get_tv_detail(self, tmdb_id: int) -> dict[str, Any]:
        params = self._required_params()
        params["append_to_response"] = (
            "aggregate_credits,content_ratings,videos,external_ids"
        )
        cache_key = f"tv:{tmdb_id}"
        return await self._get_cached(cache_key, f"/tv/{tmdb_id}", params)

    async def get_tv_episode_counts(self, tmdb_id: int) -> dict[str, Any]:
        """轻量获取剧集季/集数信息，不含 append_to_response。"""
        params = self._required_params()
        cache_key = f"tv_episodes:{tmdb_id}"
        return await self._get_cached(cache_key, f"/tv/{tmdb_id}", params)

    async def get_tv_season_detail(
        self, tmdb_id: int, season_number: int
    ) -> dict[str, Any]:
        params = self._required_params()
        cache_key = f"tv_season:{tmdb_id}:{season_number}"
        return await self._get_cached(
            cache_key, f"/tv/{tmdb_id}/season/{season_number}", params
        )

    async def get_tv_episode_detail(
        self, tmdb_id: int, season_number: int, episode_number: int
    ) -> dict[str, Any]:
        params = self._required_params()
        cache_key = f"tv_episode:{tmdb_id}:{season_number}:{episode_number}"
        return await self._get_cached(
            cache_key,
            f"/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}",
            params,
        )

    async def get_collection_detail(self, collection_id: int) -> dict[str, Any]:
        params = self._required_params()
        cache_key = f"collection:{collection_id}"
        return await self._get_cached(
            cache_key, f"/collection/{collection_id}", params
        )

    async def get_list_detail(self, list_id: int) -> dict[str, Any]:
        params = self._required_params()
        cache_key = f"tmdb_list:{list_id}"
        return await self._get_cached(cache_key, f"/list/{list_id}", params)

    async def get_keyword_movies(self, keyword_id: int, page: int = 1) -> dict[str, Any]:
        params = self._required_params(page=page)
        cache_key = f"keyword_movies:{keyword_id}:{page}"
        return await self._get_cached(
            cache_key, f"/keyword/{keyword_id}/movies", params
        )

    async def search_collections(self, query: str, page: int = 1) -> dict[str, Any]:
        params = self._required_params(page=page)
        params["query"] = str(query or "").strip()
        cache_key = f"search_collection:{params['query']}:{page}"
        return await self._get_cached(cache_key, "/search/collection", params)

    async def search_lists(self, query: str, page: int = 1) -> dict[str, Any]:
        params = self._required_params(page=page)
        params["query"] = str(query or "").strip()
        cache_key = f"search_list:{params['query']}:{page}"
        return await self._get_cached(cache_key, "/search/list", params)

    async def get_watch_providers(
        self,
        media_type: str,
        *,
        watch_region: str | None = None,
    ) -> dict[str, Any]:
        scope = str(media_type or "movie").strip().lower()
        path = "/watch/providers/movie" if scope == "movie" else "/watch/providers/tv"
        region = str(watch_region or settings.TMDB_REGION or "US").strip().upper() or "US"
        params = self._required_params()
        params["watch_region"] = region
        cache_key = f"watch_providers:{scope}:{region}"
        return await self._get_cached(cache_key, path, params)

    async def discover_movies(
        self,
        *,
        page: int = 1,
        watch_region: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = self._required_params(page=page)
        params["watch_region"] = str(watch_region or settings.TMDB_REGION or "US").strip().upper() or "US"
        if extra_params:
            params.update(extra_params)
        cache_key = f"discover_movie:{page}:{sorted(params.items())}"
        return await self._get_cached(cache_key, "/discover/movie", params)

    async def discover_tv(
        self,
        *,
        page: int = 1,
        watch_region: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = self._required_params(page=page)
        params["watch_region"] = str(watch_region or settings.TMDB_REGION or "US").strip().upper() or "US"
        if extra_params:
            params.update(extra_params)
        cache_key = f"discover_tv:{page}:{sorted(params.items())}"
        return await self._get_cached(cache_key, "/discover/tv", params)

    async def get_person_detail(self, person_id: int) -> dict[str, Any]:
        params = self._required_params()
        params["append_to_response"] = "combined_credits,external_ids"
        cache_key = f"person:{person_id}"
        return await self._get_cached(cache_key, f"/person/{person_id}", params)

    async def get_person_combined_credits(self, person_id: int) -> dict[str, Any]:
        params = self._required_params()
        cache_key = f"person_credits:{person_id}"
        return await self._get_cached(
            cache_key, f"/person/{person_id}/combined_credits", params
        )

    async def find_by_imdb_id(self, imdb_id: str) -> dict[str, Any]:
        """通过 IMDB ID 查找影片（电影或剧集）

        Args:
            imdb_id: IMDB ID，如 "tt1375666"

        Returns:
            包含查找结果的字典，结构如下：
            {
                "imdb_id": "tt1375666",
                "found": True,
                "movie": {...} or None,
                "tv": {...} or None,
                "media_type": "movie" | "tv" | None
            }
        """
        normalized_id = str(imdb_id or "").strip()
        if not normalized_id:
            return {
                "imdb_id": "",
                "found": False,
                "movie": None,
                "tv": None,
                "media_type": None,
            }

        result = await self.find_by_external_id(normalized_id, "imdb_id")
        items = result.get("items", [])

        movie_item = None
        tv_item = None

        for item in items:
            media_type = item.get("media_type")
            if media_type == "movie" and movie_item is None:
                movie_item = item
            elif media_type == "tv" and tv_item is None:
                tv_item = item

        # 确定媒体类型
        media_type = None
        if movie_item and tv_item:
            # 如果同时找到电影和剧集，优先返回电影（通常 IMDB ID 更精确对应电影）
            media_type = "movie"
        elif movie_item:
            media_type = "movie"
        elif tv_item:
            media_type = "tv"

        return {
            "imdb_id": normalized_id,
            "found": movie_item is not None or tv_item is not None,
            "movie": movie_item,
            "tv": tv_item,
            "media_type": media_type,
            "all_results": items,
        }


tmdb_service = TmdbService()
