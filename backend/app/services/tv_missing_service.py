from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.services.emby_service import emby_service
from app.services.tmdb_service import tmdb_service


class TvMissingService:
    async def get_tv_missing_status(self, tmdb_id: int, include_specials: bool = False) -> dict[str, Any]:
        normalized_tmdb_id = int(tmdb_id or 0)
        if normalized_tmdb_id <= 0:
            return {
                "status": "invalid_tmdb",
                "message": "无效的 TMDB ID",
                "aired_episodes": [],
                "existing_episodes": [],
                "missing_episodes": [],
                "missing_by_season": {},
                "counts": {"aired": 0, "existing": 0, "missing": 0},
            }

        emby_result = await emby_service.get_downloaded_episodes_with_status(normalized_tmdb_id)
        if emby_result.get("status") != "ok":
            return {
                "status": str(emby_result.get("status") or "emby_error"),
                "message": str(emby_result.get("message") or "Emby 查询失败"),
                "aired_episodes": [],
                "existing_episodes": [],
                "missing_episodes": [],
                "missing_by_season": {},
                "counts": {"aired": 0, "existing": 0, "missing": 0},
            }

        existing_pairs_all = {
            (int(pair[0]), int(pair[1]))
            for pair in (emby_result.get("episodes") or [])
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        }
        if not include_specials:
            existing_pairs_all = {pair for pair in existing_pairs_all if pair[0] > 0}

        try:
            aired_pairs = await self._collect_aired_episodes(normalized_tmdb_id, include_specials=include_specials)
        except Exception as exc:
            return {
                "status": "tmdb_error",
                "message": f"TMDB 查询失败: {str(exc)}",
                "aired_episodes": [],
                "existing_episodes": self._sorted_pairs(existing_pairs_all),
                "missing_episodes": [],
                "missing_by_season": {},
                "counts": {"aired": 0, "existing": len(existing_pairs_all), "missing": 0},
            }

        # “已入库集数”只统计已播出范围内，避免未播出/特别篇干扰统计。
        existing_pairs = existing_pairs_all & aired_pairs
        missing_pairs = aired_pairs - existing_pairs

        return {
            "status": "ok",
            "message": "缺集状态计算完成",
            "aired_episodes": self._sorted_pairs(aired_pairs),
            "existing_episodes": self._sorted_pairs(existing_pairs),
            "missing_episodes": self._sorted_pairs(missing_pairs),
            "missing_by_season": self._to_season_map(missing_pairs),
            "counts": {
                "aired": len(aired_pairs),
                "existing": len(existing_pairs),
                "missing": len(missing_pairs),
            },
        }

    async def _collect_aired_episodes(self, tmdb_id: int, include_specials: bool = False) -> set[tuple[int, int]]:
        detail = await tmdb_service.get_tv_detail(tmdb_id)
        seasons = detail.get("seasons") if isinstance(detail, dict) else []
        if not isinstance(seasons, list):
            seasons = []

        today = date.today()
        aired_pairs: set[tuple[int, int]] = set()
        for season in seasons:
            if not isinstance(season, dict):
                continue
            season_number = self._to_positive_int(season.get("season_number"))
            if season_number is None:
                continue
            if season_number == 0 and not include_specials:
                continue

            season_air_date = self._parse_iso_date(str(season.get("air_date") or ""))
            if season_air_date and season_air_date > today:
                continue

            season_detail = await tmdb_service.get_tv_season_detail(tmdb_id, season_number)
            episodes = season_detail.get("episodes") if isinstance(season_detail, dict) else []
            if not isinstance(episodes, list):
                continue

            for episode in episodes:
                if not isinstance(episode, dict):
                    continue
                episode_number = self._to_positive_int(episode.get("episode_number"))
                if episode_number is None:
                    continue
                air_date = self._parse_iso_date(str(episode.get("air_date") or ""))
                if air_date and air_date > today:
                    continue
                aired_pairs.add((season_number, episode_number))
        return aired_pairs

    @staticmethod
    def _parse_iso_date(value: str) -> date | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except Exception:
            return None

    @staticmethod
    def _to_positive_int(value: Any) -> int | None:
        try:
            number = int(value)
        except Exception:
            return None
        if number < 0:
            return None
        return number

    @staticmethod
    def _sorted_pairs(pairs: set[tuple[int, int]]) -> list[tuple[int, int]]:
        return sorted(pairs, key=lambda item: (item[0], item[1]))

    @staticmethod
    def _to_season_map(pairs: set[tuple[int, int]]) -> dict[str, list[int]]:
        output: dict[str, list[int]] = {}
        for season, episode in sorted(pairs, key=lambda item: (item[0], item[1])):
            key = str(season)
            output.setdefault(key, [])
            output[key].append(episode)
        return output


tv_missing_service = TvMissingService()
