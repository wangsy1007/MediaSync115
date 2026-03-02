from typing import Any

import httpx

from app.core.config import settings
from app.utils.proxy import proxy_manager


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

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{settings.TMDB_BASE_URL}{path}"
        client = proxy_manager.create_httpx_client(timeout=15.0, http2=True)
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            # Some environments/proxies present a mismatched certificate for TMDB.
            # Fallback once with verify=False to keep subscription/detail flows available.
            if not self._is_tls_hostname_error(exc):
                raise
        finally:
            await client.aclose()

        # Fallback without verification
        insecure_client = proxy_manager.create_httpx_client(timeout=15.0, http2=True, verify=False)
        try:
            response = await insecure_client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        finally:
            await insecure_client.aclose()

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

    async def search_multi(self, query: str, page: int = 1) -> dict[str, Any]:
        params = self._required_params(page=page)
        params["query"] = query
        params["include_adult"] = False

        payload = await self._get("/search/multi", params)
        raw_items = payload.get("results") if isinstance(payload.get("results"), list) else []

        items: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            media_type = str(raw.get("media_type") or "").strip().lower()
            if media_type not in {"movie", "tv", "collection", "person"}:
                continue

            title = raw.get("title") or raw.get("name") or ""
            item = {
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

    async def get_movie_detail(self, tmdb_id: int) -> dict[str, Any]:
        params = self._required_params()
        params["append_to_response"] = "credits,release_dates,videos"
        return await self._get(f"/movie/{tmdb_id}", params)

    async def get_tv_detail(self, tmdb_id: int) -> dict[str, Any]:
        params = self._required_params()
        params["append_to_response"] = "aggregate_credits,content_ratings,videos"
        return await self._get(f"/tv/{tmdb_id}", params)

    async def get_tv_season_detail(self, tmdb_id: int, season_number: int) -> dict[str, Any]:
        params = self._required_params()
        return await self._get(f"/tv/{tmdb_id}/season/{season_number}", params)

    async def get_tv_episode_detail(self, tmdb_id: int, season_number: int, episode_number: int) -> dict[str, Any]:
        params = self._required_params()
        return await self._get(f"/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}", params)


tmdb_service = TmdbService()
