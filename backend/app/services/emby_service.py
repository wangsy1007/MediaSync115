import time
from typing import Any, Set, Tuple

import httpx
from app.core.config import settings
from app.utils.proxy import create_direct_httpx_client

_EMBY_HTTP_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
_EMBY_HTTP_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)


class EmbyService:
    def __init__(self):
        self.base_url = settings.EMBY_URL.rstrip('/')
        self.api_key = settings.EMBY_API_KEY
        self._http_client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = create_direct_httpx_client(
                timeout=_EMBY_HTTP_TIMEOUT,
                limits=_EMBY_HTTP_LIMITS,
            )
        return self._http_client

    def set_config(self, base_url: str, api_key: str) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()
        if self._http_client is not None and not self._http_client.is_closed:
            old_client = self._http_client
            self._http_client = None
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(old_client.aclose())
            except RuntimeError:
                pass

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

        client = self._get_client()
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

    async def get_tv_episode_status_by_tmdb(self, tmdb_id: int) -> dict[str, Any]:
        """
        基于 Emby API 直接获取剧集已入库集信息。
        """
        from app.services.emby_sync_index_service import emby_sync_index_service

        indexed_status = await emby_sync_index_service.get_tv_existing_episodes(tmdb_id)
        if indexed_status is not None:
            return indexed_status

        if not self.base_url or not self.api_key:
            return {
                "status": "not_configured",
                "message": "Emby 未配置",
                "existing_episodes": set(),
            }

        client = self._get_client()
        try:
            series_ids = await self._find_series_ids_by_tmdb(client, tmdb_id)
            if not series_ids:
                return {
                    "status": "ok",
                    "message": "Emby 中未匹配到该 TMDB 剧集",
                    "existing_episodes": set(),
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
                for pair in self._extract_episode_pairs(episodes):
                    existing_episodes.add(pair)

            return {
                "status": "ok",
                "message": "查询成功",
                "existing_episodes": existing_episodes,
            }
        except Exception as e:
            print(f"Error fetching tv status from Emby: {e}")
            return {
                "status": "request_failed",
                "message": str(e),
                "existing_episodes": set(),
            }

    async def get_movie_status_by_tmdb(self, tmdb_id: int) -> dict[str, Any]:
        """基于 Emby API 直接判断电影是否已入库。"""
        from app.services.emby_sync_index_service import emby_sync_index_service

        indexed_status = await emby_sync_index_service.get_movie_status(tmdb_id)
        if indexed_status is not None:
            return indexed_status

        if not self.base_url or not self.api_key:
            return {
                "status": "not_configured",
                "message": "Emby 未配置",
                "exists": False,
                "item_ids": [],
            }

        client = self._get_client()
        try:
            movie_ids = await self._find_movie_ids_by_tmdb(client, tmdb_id)
            return {
                "status": "ok",
                "message": "查询成功" if movie_ids else "Emby 中未匹配到该 TMDB 电影",
                "exists": bool(movie_ids),
                "item_ids": movie_ids,
            }
        except Exception as e:
            print(f"Error fetching movie status from Emby: {e}")
            return {
                "status": "request_failed",
                "message": str(e),
                "exists": False,
                "item_ids": [],
            }

    async def list_all_movies(self) -> list[dict[str, Any]]:
        if not self.base_url or not self.api_key:
            return []
        return await self.list_all_movies_with_client(self._get_client())

    async def list_all_series(self) -> list[dict[str, Any]]:
        if not self.base_url or not self.api_key:
            return []
        return await self.list_all_series_with_client(self._get_client())

    async def list_series_episodes(self, series_id: str) -> list[dict[str, Any]]:
        normalized_id = str(series_id or "").strip()
        if not normalized_id or not self.base_url or not self.api_key:
            return []
        return await self.list_series_episodes_with_client(self._get_client(), normalized_id)

    # —— 用户行为数据（供「猜你想看」画像使用）——

    async def list_users(self) -> list[dict[str, Any]]:
        """获取 Emby 所有用户列表。"""
        if not self.base_url or not self.api_key:
            return []
        client = self._get_client()
        url = f"{self.base_url}/emby/Users"
        try:
            response = await client.get(
                url, params={"api_key": self.api_key}, timeout=15.0
            )
            response.raise_for_status()
            payload = response.json() if response.content else []
            if isinstance(payload, list):
                return [row for row in payload if isinstance(row, dict)]
            return []
        except Exception as e:
            print(f"Error fetching Emby users: {e}")
            return []

    async def pick_user_id(self) -> str | None:
        """选取用于推荐画像的用户 id。

        优先使用运行时配置的 emby_recommend_user_id；否则取第一个非系统用户。
        结果在进程内缓存 10 分钟。
        """
        now = time.time()
        cached = getattr(self, "_picked_user_cache", None)
        if cached and now < cached[1]:
            return cached[0]

        configured = ""
        try:
            from app.services.runtime_settings_service import runtime_settings_service
            configured = runtime_settings_service.get_emby_recommend_user_id()
        except Exception:
            configured = ""
        if configured:
            self._picked_user_cache = (configured, now + 600)
            return configured

        users = await self.list_users()
        for user in users:
            user_id = str(user.get("Id") or "").strip()
            if not user_id:
                continue
            self._picked_user_cache = (user_id, now + 600)
            return user_id
        return None

    async def list_recent_movies(self, limit: int = 30) -> list[dict[str, Any]]:
        """获取最近入库的电影（按 DateCreated 倒序），用于分析入库偏好。"""
        if not self.base_url or not self.api_key:
            return []
        return await self._fetch_items(
            self._get_client(),
            {
                "IncludeItemTypes": "Movie",
                "Recursive": "true",
                "SortBy": "DateCreated",
                "SortOrder": "Descending",
                "Fields": "ProviderIds,Genres,ProductionYear,Studios,People,DateCreated,RunTimeTicks,PlaybackPositionTicks,PlayedPercentage",
                "Limit": str(limit),
            },
        )

    async def list_recent_series(self, limit: int = 15) -> list[dict[str, Any]]:
        """获取最近入库的剧集（按 DateCreated 倒序）。"""
        if not self.base_url or not self.api_key:
            return []
        return await self._fetch_items(
            self._get_client(),
            {
                "IncludeItemTypes": "Series",
                "Recursive": "true",
                "SortBy": "DateCreated",
                "SortOrder": "Descending",
                "Fields": "ProviderIds,Genres,ProductionYear,Studios,People,DateCreated,RunTimeTicks,PlaybackPositionTicks,PlayedPercentage",
                "Limit": str(limit),
            },
        )

    async def _fetch_user_items(
        self,
        client: httpx.AsyncClient,
        user_id: str,
        endpoint: str,
        extra_params: dict[str, Any],
        timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """拉取 /emby/Users/{uid}/... 下的条目，复用分页逻辑。"""
        if not self.base_url or not self.api_key or not user_id:
            return []
        params: dict[str, Any] = {
            "api_key": self.api_key,
            "Recursive": "true",
            "Fields": "ProviderIds,Genres,ProductionYear,Studios,People,RunTimeTicks,PlaybackPositionTicks,PlayedPercentage",
        }
        params.update(extra_params)
        url = f"{self.base_url}/emby/Users/{user_id}{endpoint}"
        start_index = 0
        limit = 200
        merged: list[dict[str, Any]] = []
        while True:
            query = dict(params)
            query["StartIndex"] = start_index
            query["Limit"] = limit
            response = await client.get(url, params=query, timeout=timeout)
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
            # 用户行为数据按需取最近一批即可，避免拉全量
            if start_index >= limit:
                break
        return merged

    async def get_user_played(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """用户已看完的影视（按最近播放倒序）。"""
        if not user_id or not self.base_url or not self.api_key:
            return []
        return await self._fetch_user_items(
            self._get_client(),
            user_id,
            "/Items",
            {
                "Filters": "IsPlayed",
                "IncludeItemTypes": "Movie,Series",
                "SortBy": "DatePlayed",
                "SortOrder": "Descending",
                "Limit": str(limit),
            },
        )

    async def get_user_resume(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """用户在看/续播的影视。"""
        if not user_id or not self.base_url or not self.api_key:
            return []
        client = self._get_client()
        url = f"{self.base_url}/emby/Users/{user_id}/Items/Resume"
        try:
            response = await client.get(
                url,
                params={
                    "api_key": self.api_key,
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie,Series",
                    "Fields": "ProviderIds,Genres,ProductionYear,Studios,People,RunTimeTicks,PlaybackPositionTicks,PlayedPercentage",
                    "Limit": str(limit),
                },
                timeout=15.0,
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
            rows = payload.get("Items") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                return []
            return [row for row in rows if isinstance(row, dict)]
        except Exception as e:
            print(f"Error fetching Emby resume: {e}")
            return []

    async def get_user_favorites(self, user_id: str, limit: int = 30) -> list[dict[str, Any]]:
        """用户收藏的影视。"""
        if not user_id or not self.base_url or not self.api_key:
            return []
        return await self._fetch_user_items(
            self._get_client(),
            user_id,
            "/Items",
            {
                "Filters": "IsFavorite",
                "IncludeItemTypes": "Movie,Series",
                "SortBy": "SortName",
                "SortOrder": "Ascending",
                "Limit": str(limit),
            },
        )

    async def get_user_latest(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """用户最近添加到库的影视（/Items/Latest 返回数组）。"""
        if not user_id or not self.base_url or not self.api_key:
            return []
        client = self._get_client()
        url = f"{self.base_url}/emby/Users/{user_id}/Items/Latest"
        try:
            response = await client.get(
                url,
                params={
                    "api_key": self.api_key,
                    "IncludeItemTypes": "Movie,Series",
                    "Fields": "ProviderIds,Genres,ProductionYear,Studios,People,RunTimeTicks,PlaybackPositionTicks,PlayedPercentage",
                    "Limit": str(limit),
                },
                timeout=15.0,
            )
            response.raise_for_status()
            payload = response.json() if response.content else []
            if isinstance(payload, list):
                return [row for row in payload if isinstance(row, dict)]
            return []
        except Exception as e:
            print(f"Error fetching Emby latest: {e}")
            return []

    async def list_all_movies_with_client(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        return await self._fetch_items(
            client,
            {
                "IncludeItemTypes": "Movie",
                "Recursive": "true",
                "Fields": "ProviderIds",
            },
        )

    async def list_all_series_with_client(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        return await self._fetch_items(
            client,
            {
                "IncludeItemTypes": "Series",
                "Recursive": "true",
                "Fields": "ProviderIds",
            },
        )

    async def list_series_episodes_with_client(
        self,
        client: httpx.AsyncClient,
        series_id: str,
    ) -> list[dict[str, Any]]:
        normalized_id = str(series_id or "").strip()
        if not normalized_id:
            return []
        return await self._fetch_items(
            client,
            {
                "ParentId": normalized_id,
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Fields": "ParentIndexNumber,IndexNumber,IndexNumberEnd,SeriesId",
            },
        )

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
            provider_ids = item.get("ProviderIds")
            if not isinstance(provider_ids, dict):
                provider_ids = {}
            provider_tmdb = str(
                provider_ids.get("Tmdb")
                or provider_ids.get("TMDB")
                or provider_ids.get("tmdb")
                or ""
            ).strip()
            if provider_tmdb != target:
                continue
            series_id = str(item.get("Id") or "").strip()
            if not series_id or series_id in seen:
                continue
            seen.add(series_id)
            series_ids.append(series_id)
        return series_ids

    async def _find_movie_ids_by_tmdb(self, client: httpx.AsyncClient, tmdb_id: int) -> list[str]:
        target = str(int(tmdb_id))
        movie_items = await self._fetch_items(
            client,
            {
                "IncludeItemTypes": "Movie",
                "Recursive": "true",
                "Fields": "ProviderIds",
                "AnyProviderIdEquals": f"Tmdb.{target}",
            },
        )
        if not movie_items:
            movie_items = await self._fetch_items(
                client,
                {
                    "IncludeItemTypes": "Movie",
                    "Recursive": "true",
                    "Fields": "ProviderIds",
                    "ProviderIds.Tmdb": target,
                },
            )

        movie_ids: list[str] = []
        seen: set[str] = set()
        for item in movie_items:
            if not isinstance(item, dict):
                continue
            provider_ids = item.get("ProviderIds")
            if not isinstance(provider_ids, dict):
                provider_ids = {}
            provider_tmdb = str(
                provider_ids.get("Tmdb")
                or provider_ids.get("TMDB")
                or provider_ids.get("tmdb")
                or ""
            ).strip()
            if provider_tmdb != target:
                continue
            movie_id = str(item.get("Id") or "").strip()
            if not movie_id or movie_id in seen:
                continue
            seen.add(movie_id)
            movie_ids.append(movie_id)
        return movie_ids

    async def _fetch_items(self, client: httpx.AsyncClient, params: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._fetch_items_by_endpoint(client, "/emby/Items", params)

    async def _fetch_items_by_endpoint(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        params: dict[str, Any],
        timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        if not self.base_url or not self.api_key:
            return []

        url = f"{self.base_url}{endpoint}"
        start_index = 0
        page_size = 200
        # 若调用方指定了 Limit，用它作为单页大小及总上限
        caller_limit = self._safe_int(params.get("Limit"))
        max_items = caller_limit if caller_limit else None

        merged: list[dict[str, Any]] = []
        while True:
            query = dict(params)
            query["api_key"] = self.api_key
            query["StartIndex"] = start_index
            # 如果设置了上限，单页大小取上限和默认页大小的较小值
            effective_limit = min(max_items, page_size) if max_items else page_size
            query["Limit"] = effective_limit
            response = await client.get(url, params=query, timeout=timeout)
            response.raise_for_status()
            payload = response.json() if response.content else {}
            if not isinstance(payload, dict):
                break
            rows = payload.get("Items")
            if not isinstance(rows, list):
                rows = []
            dict_rows = [row for row in rows if isinstance(row, dict)]
            merged.extend(dict_rows)

            # 达到调用方要求的上限即停止
            if max_items and len(merged) >= max_items:
                merged = merged[:max_items]
                break

            total = self._safe_int(payload.get("TotalRecordCount"), default=0) or 0
            if not dict_rows:
                break
            start_index += len(dict_rows)
            if total > 0 and start_index >= total:
                break
            if len(dict_rows) < effective_limit:
                break
        return merged

    def _extract_episode_pairs(self, items: list[dict[str, Any]]) -> set[tuple[int, int]]:
        pairs: set[tuple[int, int]] = set()
        for item in items:
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
                pairs.add((season_number, episode_number))
        return pairs

    def extract_episode_pairs(self, items: list[dict[str, Any]]) -> set[tuple[int, int]]:
        return self._extract_episode_pairs(items)

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
        
        client = self._get_client()
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
        async with create_direct_httpx_client() as client:
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
