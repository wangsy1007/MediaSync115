import httpx
from typing import Any, Set, Tuple
from app.core.config import settings

class EmbyService:
    def __init__(self):
        self.base_url = settings.EMBY_URL.rstrip('/')
        self.api_key = settings.EMBY_API_KEY

    def set_config(self, base_url: str, api_key: str) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()

    async def get_downloaded_episodes_with_status(self, tmdb_id: int) -> dict[str, Any]:
        """
        获取 Emby 中已存在的某个剧集的具体集数
        返回格式:
        {
          "status": "ok|not_configured|request_failed",
          "message": "...",
          "episodes": {(season_num, episode_num), ...}
        }
        """
        if not self.base_url or not self.api_key:
            return {
                "status": "not_configured",
                "message": "Emby 未配置",
                "episodes": set(),
            }

        async with httpx.AsyncClient() as client:
            try:
                series_ids = await self._find_series_ids_by_tmdb(client, tmdb_id)
                if not series_ids:
                    return {
                        "status": "ok",
                        "message": "Emby 中未匹配到该 TMDB 剧集",
                        "episodes": set(),
                    }

                existing_episodes: set[tuple[int, int]] = set()
                for series_id in series_ids:
                    episodes = await self._fetch_items(
                        client,
                        {
                            "ParentId": series_id,
                            "IncludeItemTypes": "Episode",
                            "Recursive": "true",
                            "Fields": "ParentIndexNumber,IndexNumber,IndexNumberEnd,SeriesId",
                        },
                    )
                    for item in episodes:
                        if not isinstance(item, dict):
                            continue
                        episode_start = self._safe_int(item.get("IndexNumber"))
                        if episode_start is None or episode_start <= 0:
                            continue

                        season = self._safe_int(item.get("ParentIndexNumber"), default=1)
                        season_number = season if season is not None and season >= 0 else 1
                        episode_end = self._safe_int(item.get("IndexNumberEnd"), default=episode_start)
                        if episode_end is None or episode_end < episode_start:
                            episode_end = episode_start

                        for episode_number in range(episode_start, episode_end + 1):
                            existing_episodes.add((season_number, episode_number))
                return {
                    "status": "ok",
                    "message": "查询成功",
                    "episodes": existing_episodes,
                }
            except Exception as e:
                print(f"Error fetching from Emby: {e}")
                return {
                    "status": "request_failed",
                    "message": str(e),
                    "episodes": set(),
                }

    async def _find_series_ids_by_tmdb(self, client: httpx.AsyncClient, tmdb_id: int) -> list[str]:
        target = str(int(tmdb_id))
        series_items = await self._fetch_items(
            client,
            {
                "IncludeItemTypes": "Series",
                "Recursive": "true",
                "Fields": "ProviderIds",
                "AnyProviderIdEquals": f"Tmdb.{target}",
            },
        )
        if not series_items:
            # 兼容部分 Emby/Jellyfin 服务端对 AnyProviderIdEquals 支持不完整的情况
            series_items = await self._fetch_items(
                client,
                {
                    "IncludeItemTypes": "Series",
                    "Recursive": "true",
                    "Fields": "ProviderIds",
                    "ProviderIds.Tmdb": target,
                },
            )

        series_ids: list[str] = []
        seen: set[str] = set()
        for item in series_items:
            if not isinstance(item, dict):
                continue
            series_id = str(item.get("Id") or "").strip()
            if not series_id or series_id in seen:
                continue
            seen.add(series_id)
            series_ids.append(series_id)
        return series_ids

    async def _fetch_items(self, client: httpx.AsyncClient, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.base_url or not self.api_key:
            return []

        url = f"{self.base_url}/emby/Items"
        start_index = 0
        limit = 200
        merged: list[dict[str, Any]] = []
        while True:
            query = dict(params)
            query["api_key"] = self.api_key
            query["StartIndex"] = start_index
            query["Limit"] = limit
            response = await client.get(url, params=query, timeout=15.0)
            response.raise_for_status()
            payload = response.json() if response.content else {}
            if not isinstance(payload, dict):
                break
            rows = payload.get("Items")
            if not isinstance(rows, list):
                rows = []
            dict_rows = [row for row in rows if isinstance(row, dict)]
            merged.extend(dict_rows)

            total = self._safe_int(payload.get("TotalRecordCount"), default=0) or 0
            if not dict_rows:
                break
            start_index += len(dict_rows)
            if total > 0 and start_index >= total:
                break
            if len(dict_rows) < limit:
                break
        return merged

    @staticmethod
    def _safe_int(value: Any, default: int | None = None) -> int | None:
        try:
            return int(value)
        except Exception:
            return default

    async def get_downloaded_episodes(self, tmdb_id: int) -> Set[Tuple[int, int]]:
        result = await self.get_downloaded_episodes_with_status(tmdb_id)
        return set(result.get("episodes") or set())
    
    async def refresh_library(self):
        """触发 Emby 扫描库更新"""
        if not self.base_url or not self.api_key:
            return
            
        url = f"{self.base_url}/emby/Library/Refresh"
        params = {"api_key": self.api_key}
        
        async with httpx.AsyncClient() as client:
            try:
                # 触发扫描是不返回具体内容的
                await client.post(url, params=params, timeout=5.0)
            except Exception as e:
                print(f"Error triggering Emby refresh: {e}")

    async def check_connection_with_config(self, base_url: str, api_key: str) -> dict[str, Any]:
        normalized_base_url = str(base_url or "").strip().rstrip("/")
        normalized_api_key = str(api_key or "").strip()
        if not normalized_base_url or not normalized_api_key:
            return {
                "valid": False,
                "message": "Emby URL 或 API Key 未配置",
                "user": None,
            }

        url = f"{normalized_base_url}/emby/System/Info"
        params = {"api_key": normalized_api_key}
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, params=params, timeout=10.0)
                response.raise_for_status()
                payload = response.json() if response.content else {}
                if not isinstance(payload, dict):
                    payload = {}
                return {
                    "valid": True,
                    "message": "Emby 连接成功",
                    "user": {
                        "server_name": payload.get("ServerName"),
                        "version": payload.get("Version"),
                        "id": payload.get("Id"),
                    },
                }
            except Exception as exc:
                return {
                    "valid": False,
                    "message": str(exc),
                    "user": None,
                }

    async def check_connection(self) -> dict[str, Any]:
        if not self.base_url or not self.api_key:
            return {
                "valid": False,
                "message": "Emby URL 或 API Key 未配置",
                "user": None,
            }
        return await self.check_connection_with_config(self.base_url, self.api_key)

emby_service = EmbyService()
