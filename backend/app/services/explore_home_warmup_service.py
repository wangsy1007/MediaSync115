import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import logging
import time
from typing import Any

import httpx

from app.services.douban_explore_service import (
    DOUBAN_SECTION_SOURCES,
    fetch_douban_section,
)
from app.services.tmdb_explore_service import TMDB_SECTION_SOURCES, fetch_tmdb_section

logger = logging.getLogger("uvicorn.error")

EXPLORE_HOME_WARMUP_LIMIT = 12


class ExploreHomeWarmupService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._section_snapshots: dict[str, dict[str, Any]] = {}

    def _build_snapshot_key(
        self, source: str, section_key: str, start: int, limit: int
    ) -> str:
        return f"{source}:{section_key}:{start}:{limit}"

    def _should_cache_request(self, start: int, limit: int) -> bool:
        return int(start) == 0 and int(limit) == EXPLORE_HOME_WARMUP_LIMIT

    def clear_snapshots(self) -> None:
        self._section_snapshots.clear()

    def get_cached_section(
        self, source: str, section_key: str, start: int, limit: int
    ) -> dict[str, Any] | None:
        normalized_source = "tmdb" if source == "tmdb" else "douban"
        if not self._should_cache_request(start, limit):
            return None
        snapshot = self._section_snapshots.get(
            self._build_snapshot_key(
                normalized_source, section_key, int(start), int(limit)
            )
        )
        if not isinstance(snapshot, dict):
            return None
        payload = snapshot.get("payload")
        if not isinstance(payload, dict):
            return None
        return {
            "source": snapshot.get("source")
            or ("tmdb" if normalized_source == "tmdb" else "douban-frodo"),
            "fetched_at": snapshot.get("fetched_at"),
            "cache_warmed_at": snapshot.get("cache_warmed_at"),
            "section": deepcopy(payload),
            "emby_status_map": deepcopy(snapshot.get("emby_status_map") or {}),
        }

    def _replace_source_snapshots(
        self, source: str, snapshots: list[dict[str, Any]]
    ) -> None:
        prefix = f"{source}:"
        for key in list(self._section_snapshots.keys()):
            if key.startswith(prefix):
                self._section_snapshots.pop(key, None)
        for snapshot in snapshots:
            section_key = str(snapshot.get("section_key") or "").strip()
            if not section_key:
                continue
            cache_key = self._build_snapshot_key(
                source, section_key, 0, EXPLORE_HOME_WARMUP_LIMIT
            )
            self._section_snapshots[cache_key] = snapshot

    async def warmup(self, force_refresh: bool = False) -> dict[str, Any]:
        async with self._lock:
            started_at = time.perf_counter()
            logger.info("explore home warmup started force_refresh=%s", force_refresh)
            try:
                result = await self._warmup_all_sources(force_refresh=force_refresh)
                result["timed_out"] = False
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                logger.warning(
                    "explore home warmup failed after %sms: %s",
                    elapsed_ms,
                    exc,
                )
                return {
                    "success": False,
                    "timed_out": False,
                    "elapsed_ms": elapsed_ms,
                    "sources": [],
                    "message": f"explore home warmup failed: {exc}",
                }

            result["elapsed_ms"] = int((time.perf_counter() - started_at) * 1000)
            result["message"] = "explore home warmup completed"
            return result

    async def _warmup_all_sources(self, force_refresh: bool) -> dict[str, Any]:
        results = []
        for source_name in ("douban", "tmdb"):
            results.append(
                await self._warmup_source(source_name, force_refresh=force_refresh)
            )

        success = all(bool(item.get("success")) for item in results)
        return {
            "success": success,
            "sources": results,
        }

    async def _warmup_source(
        self, source_name: str, force_refresh: bool
    ) -> dict[str, Any]:
        source_rows = (
            TMDB_SECTION_SOURCES if source_name == "tmdb" else DOUBAN_SECTION_SOURCES
        )
        started_at = time.perf_counter()
        source_label = "tmdb" if source_name == "tmdb" else "douban-frodo"

        from app.utils.proxy import proxy_manager

        async with proxy_manager.create_httpx_client(
            timeout=30.0, http2=False
        ) as client:
            if source_name == "tmdb":
                tasks = [
                    fetch_tmdb_section(
                        section,
                        EXPLORE_HOME_WARMUP_LIMIT,
                        force_refresh,
                        start=0,
                        client=client,
                    )
                    for section in source_rows
                ]
            else:
                tasks = [
                    fetch_douban_section(
                        section,
                        EXPLORE_HOME_WARMUP_LIMIT,
                        force_refresh,
                        start=0,
                        client=client,
                        home_prime_limit=EXPLORE_HOME_WARMUP_LIMIT,
                    )
                    for section in source_rows
                ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = 0
        failures: list[dict[str, str]] = []
        warmed_at = datetime.now(timezone.utc).isoformat()
        snapshots: list[dict[str, Any]] = []
        for section, result in zip(source_rows, results):
            if isinstance(result, Exception):
                failures.append(
                    {
                        "key": str(section.get("key") or ""),
                        "error": str(result),
                    }
                )
                continue
            if not isinstance(result, dict):
                failures.append(
                    {
                        "key": str(section.get("key") or ""),
                        "error": "invalid section payload",
                    }
                )
                continue
            success_count += 1
            section_items = result.get("items")
            section_payload = {
                "key": result.get("key") or str(section.get("key") or ""),
                "title": result.get("title") or str(section.get("title") or ""),
                "tag": result.get("tag") or str(section.get("tag") or ""),
                "source_url": result.get("source_url") or "",
                "fetched_at": result.get("fetched_at") or warmed_at,
                "total": int(result.get("total") or 0),
                "start": 0,
                "count": EXPLORE_HOME_WARMUP_LIMIT,
                "items": section_items if isinstance(section_items, list) else [],
            }
            try:
                from app.api import search as search_api

                section_status_map = await search_api._build_emby_status_map(
                    section_payload["items"]
                )
            except Exception as exc:
                logger.warning(
                    "explore home warmup emby badge cache failed for %s/%s: %s",
                    source_name,
                    section_payload["key"],
                    exc,
                )
                section_status_map = {}
            snapshots.append(
                {
                    "section_key": section_payload["key"],
                    "source": source_label,
                    "fetched_at": section_payload["fetched_at"],
                    "cache_warmed_at": warmed_at,
                    "payload": section_payload,
                    "emby_status_map": section_status_map,
                }
            )

        if snapshots:
            self._replace_source_snapshots(source_name, snapshots)

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "explore home warmup source=%s success=%s sections=%s/%s elapsed_ms=%s failures=%s",
            source_name,
            success_count == len(source_rows),
            success_count,
            len(source_rows),
            elapsed_ms,
            failures,
        )
        return {
            "source": source_name,
            "success": success_count == len(source_rows),
            "sections_total": len(source_rows),
            "sections_warmed": success_count,
            "elapsed_ms": elapsed_ms,
            "failures": failures,
        }


explore_home_warmup_service = ExploreHomeWarmupService()
