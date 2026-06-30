"""「猜你想看」推荐服务。

流程：Emby 用户行为画像 → LLM 推算片名 → TMDB 解析为可展示条目
→ 过滤已入库/已看过 → 归一化 → 缓存到 recommendation_cache 表。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from typing import Any

from sqlalchemy import select

from app.core.database import async_session_maker
from app.core.timezone_utils import beijing_now
from app.models.recommendation import RecommendationCache
from app.services.emby_service import emby_service
from app.services.llm_service import llm_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.tmdb_service import tmdb_service

logger = logging.getLogger(__name__)

_PROFILE_PLAYED_LIMIT = 40
_PROFILE_RESUME_LIMIT = 16
_PROFILE_FAVORITE_LIMIT = 24
_PROFILE_LATEST_LIMIT = 16
_TOP_GENRES = 8
_TOP_PEOPLE = 6


def _extract_tmdb_id(item: dict[str, Any]) -> int | None:
    provider_ids = item.get("ProviderIds")
    if not isinstance(provider_ids, dict):
        return None
    for key in ("Tmdb", "TMDB", "tmdb"):
        raw = provider_ids.get(key)
        if raw is None:
            continue
        try:
            return int(str(raw).strip())
        except Exception:
            continue
    return None


def _item_title(item: dict[str, Any]) -> str:
    return str(item.get("Name") or item.get("Title") or "").strip()


def _item_year(item: dict[str, Any]) -> str:
    year = item.get("ProductionYear")
    if year:
        s = str(year).strip()
        if s[:4].isdigit():
            return s[:4]
    for key in ("PremiereDate", "DateCreated", "EndDate"):
        value = str(item.get(key) or "").strip()
        if len(value) >= 4 and value[:4].isdigit():
            return value[:4]
    return ""


def _item_genres(item: dict[str, Any]) -> list[str]:
    genres = item.get("Genres")
    if isinstance(genres, list):
        return [str(g).strip() for g in genres if str(g).strip()]
    return []


def _item_people(item: dict[str, Any]) -> list[str]:
    people = item.get("People")
    if not isinstance(people, list):
        return []
    names: list[str] = []
    for person in people:
        if not isinstance(person, dict):
            continue
        role = str(person.get("Type") or "").lower()
        if role not in {"director", "actor"}:
            continue
        name = str(person.get("Name") or "").strip()
        if name:
            names.append(name)
    return names


class RecommendService:
    def __init__(self) -> None:
        self._generate_lock = asyncio.Lock()

    # —— 画像构建 ——

    async def build_profile(self) -> dict[str, Any]:
        """从 Emby 用户行为数据聚合出紧凑画像。"""
        user_id = await emby_service.pick_user_id()
        profile: dict[str, Any] = {
            "user_id": user_id,
            "top_genres": [],
            "recent_played": [],
            "in_progress": [],
            "favorites": [],
            "top_people": [],
            "year_range": "",
            "summary": "",
        }
        if not user_id:
            profile["summary"] = "未配置 Emby 用户，无法获取观影画像。"
            return profile

        played, resume, favorites, latest = await asyncio.gather(
            emby_service.get_user_played(user_id, _PROFILE_PLAYED_LIMIT),
            emby_service.get_user_resume(user_id, _PROFILE_RESUME_LIMIT),
            emby_service.get_user_favorites(user_id, _PROFILE_FAVORITE_LIMIT),
            emby_service.get_user_latest(user_id, _PROFILE_LATEST_LIMIT),
        )

        genre_counter: Counter[str] = Counter()
        people_counter: Counter[str] = Counter()
        years: list[int] = []

        for item in played:
            title = _item_title(item)
            year = _item_year(item)
            if title:
                profile["recent_played"].append({"title": title, "year": year})
            genre_counter.update(_item_genres(item))
            people_counter.update(_item_people(item))
            if year and year.isdigit():
                years.append(int(year))

        for item in favorites:
            title = _item_title(item)
            if title:
                profile["favorites"].append({"title": title, "year": _item_year(item)})
            genre_counter.update(_item_genres(item))
            people_counter.update(_item_people(item))

        for item in resume:
            title = _item_title(item)
            if title:
                profile["in_progress"].append({"title": title, "year": _item_year(item)})

        # 最近添加也参与类型统计，丰富画像
        for item in latest:
            genre_counter.update(_item_genres(item))

        profile["top_genres"] = [g for g, _ in genre_counter.most_common(_TOP_GENRES)]
        profile["top_people"] = [p for p, _ in people_counter.most_common(_TOP_PEOPLE)]
        if years:
            profile["year_range"] = f"{min(years)}-{max(years)}"

        if not profile["recent_played"] and not profile["favorites"]:
            profile["summary"] = "用户观影数据较少，请结合大众口碑进行推荐。"
        return profile

    # —— TMDB 解析与过滤 ——

    async def _resolve_via_tmdb(
        self, title: str, media_type: str, year: str
    ) -> dict[str, Any] | None:
        """把 LLM 给出的片名解析为 TMDB 条目，按年份匹配最佳结果。"""
        year_int: int | None = None
        if year and year.isdigit():
            year_int = int(year)
        try:
            result = await tmdb_service.search_by_media_type(
                title, media_type=media_type, page=1, year=year_int
            )
        except Exception as exc:
            logger.warning("TMDB 解析失败 title=%s: %s", title, exc)
            return None
        items = result.get("items") if isinstance(result, dict) else None
        if not isinstance(items, list) or not items:
            return None

        def _candidate_year(raw: dict[str, Any]) -> str:
            value = str(
                raw.get("release_date") or raw.get("first_air_date") or ""
            ).strip()
            return value[:4] if len(value) >= 4 and value[:4].isdigit() else ""

        # 优先取年份匹配项，否则取第一个
        best = items[0]
        if year_int:
            for raw in items:
                if _candidate_year(raw) == str(year_int):
                    best = raw
                    break
        if not isinstance(best, dict) or best.get("id") is None:
            return None

        tmdb_id = int(best["id"])
        image_base = runtime_settings_service.get_tmdb_image_base_url()
        poster_path = str(best.get("poster_path") or "").strip()
        poster_url = f"{image_base}{poster_path}" if poster_path else ""
        try:
            rating = float(best.get("vote_average") or 0)
            if rating <= 0:
                rating = None
        except Exception:
            rating = None

        return {
            "id": tmdb_id,
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "title": str(best.get("title") or best.get("name") or title).strip(),
            "year": _candidate_year(best),
            "poster_url": poster_url,
            "rating": rating,
        }

    async def _build_library_tmdb_ids(self) -> set[int]:
        """收集 Emby 库中所有影视的 TMDB id（用于排除已入库）。"""
        ids: set[int] = set()
        try:
            movies, series = await asyncio.gather(
                emby_service.list_all_movies(),
                emby_service.list_all_series(),
            )
        except Exception as exc:
            logger.warning("拉取 Emby 库条目失败: %s", exc)
            return ids
        for item in movies + series:
            if not isinstance(item, dict):
                continue
            tmdb_id = _extract_tmdb_id(item)
            if tmdb_id:
                ids.add(tmdb_id)
        return ids

    # —— 主流程 ——

    async def generate(self, force: bool = False) -> dict[str, Any]:
        """生成推荐并写缓存。返回最新缓存内容。"""
        async with self._generate_lock:
            return await self._generate_inner(force)

    async def _generate_inner(self, force: bool) -> dict[str, Any]:
        if not runtime_settings_service.is_recommend_ready():
            message = "推荐功能未就绪：请在设置页配置并启用 LLM 与推荐。"
            await self._save_cache(items=[], profile_summary="", error=message)
            return self._format_cached(items=[], generated_at=None, error=message)

        count = runtime_settings_service.get_recommend_count()
        try:
            profile = await self.build_profile()
            raw_recommendations = await llm_service.recommend(profile, count)
        except Exception as exc:
            logger.exception("LLM 推荐生成失败")
            message = f"LLM 调用失败：{exc}"
            await self._save_cache(items=[], profile_summary="", error=message)
            return self._format_cached(items=[], generated_at=None, error=message)

        # 并发解析 TMDB
        resolved: list[dict[str, Any]] = []
        results = await asyncio.gather(
            *[
                self._resolve_via_tmdb(r["title"], r["media_type"], r.get("year") or "")
                for r in raw_recommendations
            ],
            return_exceptions=True,
        )
        reason_map: dict[tuple[str, str], str] = {}
        for raw, res in zip(raw_recommendations, results):
            if isinstance(res, Exception) or not res:
                continue
            reason_map[(res["media_type"], str(res["tmdb_id"]))] = raw.get("reason") or ""
            resolved.append(res)

        # 去重 + 过滤已入库/已看过
        library_ids = await self._build_library_tmdb_ids()
        played_ids: set[int] = set()
        # profile 里 recent_played 已是聚合结构，重新从 Emby 取一次原始条目拿 tmdb id
        try:
            user_id = profile.get("user_id")
            if user_id:
                played_items = await emby_service.get_user_played(user_id, 100)
                for item in played_items:
                    tmdb_id = _extract_tmdb_id(item)
                    if tmdb_id:
                        played_ids.add(tmdb_id)
        except Exception:
            pass

        seen_ids: set[int] = set()
        final_items: list[dict[str, Any]] = []
        for item in resolved:
            tmdb_id = item["tmdb_id"]
            if tmdb_id in seen_ids:
                continue
            if tmdb_id in library_ids or tmdb_id in played_ids:
                continue
            seen_ids.add(tmdb_id)
            reason = reason_map.get((item["media_type"], str(tmdb_id)), "")
            item["reason"] = reason
            item["intro"] = reason or "AI 推荐"
            item["rank"] = len(final_items) + 1
            final_items.append(item)
            if len(final_items) >= count:
                break

        profile_summary = self._summarize_profile(profile)
        await self._save_cache(
            items=final_items, profile_summary=profile_summary, error=None
        )
        return self._format_cached(
            items=final_items,
            generated_at=beijing_now().isoformat(),
            error=None,
            profile_summary=profile_summary,
        )

    @staticmethod
    def _summarize_profile(profile: dict[str, Any]) -> str:
        parts: list[str] = []
        if profile.get("top_genres"):
            parts.append("类型偏好：" + "、".join(profile["top_genres"]))
        if profile.get("recent_played"):
            parts.append(
                "近期已看 "
                + str(len(profile["recent_played"]))
                + " 部"
            )
        if profile.get("top_people"):
            parts.append("关注：" + "、".join(profile["top_people"]))
        return "；".join(parts) if parts else "画像数据较少"

    # —— 缓存读写 ——

    async def _save_cache(
        self,
        items: list[dict[str, Any]],
        profile_summary: str,
        error: str | None,
    ) -> None:
        async with async_session_maker() as db:
            result = await db.execute(
                select(RecommendationCache).where(RecommendationCache.id == 1).limit(1)
            )
            row = result.scalar_one_or_none()
            now = beijing_now()
            if row is None:
                row = RecommendationCache(id=1)
                db.add(row)
            row.items_json = json.dumps(items, ensure_ascii=False)
            row.profile_summary = profile_summary
            row.generated_at = now if not error else row.generated_at
            row.generated_count = len(items) if not error else 0
            row.error_message = error
            row.updated_at = now
            await db.commit()

    async def get_cached(self) -> dict[str, Any]:
        """读取缓存结果与新鲜度信息。"""
        async with async_session_maker() as db:
            result = await db.execute(
                select(RecommendationCache).where(RecommendationCache.id == 1).limit(1)
            )
            row = result.scalar_one_or_none()

        items: list[dict[str, Any]] = []
        generated_at = None
        error = None
        profile_summary = ""
        if row is not None:
            generated_at = row.generated_at.isoformat() if row.generated_at else None
            error = row.error_message
            profile_summary = row.profile_summary or ""
            try:
                parsed = json.loads(row.items_json or "[]")
                if isinstance(parsed, list):
                    items = [it for it in parsed if isinstance(it, dict)]
            except Exception:
                items = []

        return self._format_cached(
            items=items,
            generated_at=generated_at,
            error=error,
            profile_summary=profile_summary,
        )

    def _format_cached(
        self,
        items: list[dict[str, Any]],
        generated_at: str | None,
        error: str | None,
        profile_summary: str = "",
    ) -> dict[str, Any]:
        return {
            "items": items,
            "total": len(items),
            "generated_at": generated_at,
            "profile_summary": profile_summary,
            "error": error,
            "enabled": runtime_settings_service.get_recommend_enabled(),
            "ready": runtime_settings_service.is_recommend_ready(),
        }


recommend_service = RecommendService()
