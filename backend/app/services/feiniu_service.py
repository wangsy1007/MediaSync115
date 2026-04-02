import hashlib
import time
from typing import Any, Optional

import httpx

from app.core.config import settings


class FeiniuService:
    def __init__(self):
        self.base_url = settings.FEINIU_URL.rstrip("/") if settings.FEINIU_URL else ""
        self.secret = settings.FEINIU_SECRET
        self.api_key = settings.FEINIU_API_KEY

    def set_config(self, base_url: str, secret: str, api_key: str) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.secret = str(secret or "").strip()
        self.api_key = str(api_key or "").strip()

    def _compute_authx(self, timestamp: Optional[str] = None) -> str:
        if timestamp is None:
            timestamp = str(int(time.time()))
        raw = f"{self.secret}{timestamp}{self.api_key}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _auth_headers(self) -> dict[str, str]:
        timestamp = str(int(time.time()))
        authx = self._compute_authx(timestamp)
        return {
            "authx": authx,
            "authn": timestamp,
        }

    async def check_connection(self) -> dict[str, Any]:
        if not self.base_url or not self.secret or not self.api_key:
            return {
                "valid": False,
                "message": "飞牛影视 URL、Secret 或 API Key 未配置",
                "user": None,
            }

        url = f"{self.base_url}/mdb/count"
        headers = self._auth_headers()
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, timeout=10.0)
                if response.status_code == 200:
                    return {
                        "valid": True,
                        "message": "飞牛影视连接成功",
                        "user": {"server": "feiniu"},
                    }
                return {
                    "valid": False,
                    "message": f"连接失败 (HTTP {response.status_code})",
                    "user": None,
                }
            except Exception as exc:
                return {
                    "valid": False,
                    "message": str(exc),
                    "user": None,
                }

    async def check_connection_with_config(
        self, base_url: str, secret: str, api_key: str
    ) -> dict[str, Any]:
        normalized_base_url = str(base_url or "").strip().rstrip("/")
        normalized_secret = str(secret or "").strip()
        normalized_api_key = str(api_key or "").strip()

        if not normalized_base_url or not normalized_secret or not normalized_api_key:
            return {
                "valid": False,
                "message": "飞牛影视 URL、Secret 或 API Key 未配置",
                "user": None,
            }

        url = f"{normalized_base_url}/mdb/count"
        timestamp = str(int(time.time()))
        raw = f"{normalized_secret}{timestamp}{normalized_api_key}"
        authx = hashlib.md5(raw.encode("utf-8")).hexdigest()
        headers = {
            "authx": authx,
            "authn": timestamp,
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, timeout=10.0)
                if response.status_code == 200:
                    return {
                        "valid": True,
                        "message": "飞牛影视连接成功",
                        "user": {"server": "feiniu"},
                    }
                return {
                    "valid": False,
                    "message": f"连接失败 (HTTP {response.status_code})",
                    "user": None,
                }
            except Exception as exc:
                return {
                    "valid": False,
                    "message": str(exc),
                    "user": None,
                }

    async def get_movie_status_by_tmdb(self, tmdb_id: int) -> dict[str, Any]:
        if not self.base_url or not self.secret or not self.api_key:
            return {
                "status": "not_configured",
                "message": "飞牛影视未配置",
                "exists": False,
                "item_ids": [],
            }

        url = f"{self.base_url}/mdb/search"
        headers = self._auth_headers()
        params = {
            "type": "movie",
            "tmdb": str(tmdb_id),
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url, headers=headers, params=params, timeout=15.0
                )
                if response.status_code != 200:
                    return {
                        "status": "request_failed",
                        "message": f"请求失败 (HTTP {response.status_code})",
                        "exists": False,
                        "item_ids": [],
                    }
                payload = response.json() if response.content else {}
                items = payload.get("data") or payload.get("items") or []
                item_ids = [
                    str(item.get("id") or "") for item in items if item.get("id")
                ]
                return {
                    "status": "ok",
                    "message": "查询成功"
                    if item_ids
                    else "飞牛影视中未匹配到该 TMDB 电影",
                    "exists": bool(item_ids),
                    "item_ids": item_ids,
                }
            except Exception as exc:
                return {
                    "status": "request_failed",
                    "message": str(exc),
                    "exists": False,
                    "item_ids": [],
                }

    async def get_tv_episode_status_by_tmdb(self, tmdb_id: int) -> dict[str, Any]:
        if not self.base_url or not self.secret or not self.api_key:
            return {
                "status": "not_configured",
                "message": "飞牛影视未配置",
                "existing_episodes": set(),
            }

        url = f"{self.base_url}/mdb/search"
        headers = self._auth_headers()
        params = {
            "type": "tv",
            "tmdb": str(tmdb_id),
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url, headers=headers, params=params, timeout=15.0
                )
                if response.status_code != 200:
                    return {
                        "status": "request_failed",
                        "message": f"请求失败 (HTTP {response.status_code})",
                        "existing_episodes": set(),
                    }
                payload = response.json() if response.content else {}
                items = payload.get("data") or payload.get("items") or []

                existing_episodes: set[tuple[int, int]] = set()
                for item in items:
                    season = int(item.get("season") or item.get("seasonNumber") or 1)
                    episode = int(item.get("episode") or item.get("episodeNumber") or 0)
                    if episode > 0:
                        existing_episodes.add((season, episode))

                return {
                    "status": "ok",
                    "message": "查询成功",
                    "existing_episodes": existing_episodes,
                }
            except Exception as exc:
                return {
                    "status": "request_failed",
                    "message": str(exc),
                    "existing_episodes": set(),
                }

    async def refresh_library(self, path: Optional[str] = None) -> dict[str, Any]:
        if not self.base_url or not self.secret or not self.api_key:
            return {
                "status": "not_configured",
                "message": "飞牛影视未配置",
            }

        url = f"{self.base_url}/mdb/scan"
        headers = self._auth_headers()
        payload: dict[str, Any] = {}
        if path:
            payload["path"] = path

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url, headers=headers, json=payload, timeout=30.0
                )
                if response.status_code == 200:
                    return {
                        "status": "ok",
                        "message": "扫描任务已触发",
                    }
                error_text = response.text
                if "-14" in error_text:
                    return {
                        "status": "duplicate",
                        "message": "扫描任务冲突，请稍后重试",
                    }
                return {
                    "status": "error",
                    "message": f"扫描失败 (HTTP {response.status_code}): {error_text}",
                }
            except Exception as exc:
                return {
                    "status": "request_failed",
                    "message": str(exc),
                }


feiniu_service = FeiniuService()
