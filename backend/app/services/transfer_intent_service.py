"""转存意图登记与查询：归档命名与转存影视一一关联。"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select

from app.core.database import async_session_maker
from app.core.timezone_utils import beijing_now
from app.models.transfer_intent import TransferIntent

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_YEAR_SUFFIX_RE = re.compile(r"\s*[\(（]\s*\d{4}\s*[\)）]\s*$")
_RETENTION_DAYS = 90
_MAX_ROWS = 2000


def contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def normalize_transfer_display_title(raw: str) -> str:
    """从转存文件夹名/用户标题提取展示用中文片名。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    text = _YEAR_SUFFIX_RE.sub("", text).strip(" ._-")
    if contains_cjk(text):
        match = re.search(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af0-9A-Za-z·]+", text)
        if match:
            return match.group(0).strip(" ._-")
    return text


def extract_chinese_title_from_text(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    normalized = normalize_transfer_display_title(text)
    if normalized:
        return normalized
    for match in re.finditer(r"[\u3400-\u9fff]{2,}", text):
        return match.group(0).strip()
    return ""


def pick_preferred_chinese_title(*candidates: str) -> str:
    cleaned: list[str] = []
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value:
            continue
        if value not in cleaned:
            cleaned.append(value)
    for value in cleaned:
        if contains_cjk(value):
            return value
    return cleaned[0] if cleaned else ""


class TransferIntentService:
    async def register_intent(
        self,
        *,
        display_title: str,
        media_type: str = "movie",
        tmdb_id: int | None = None,
        douban_id: str | None = None,
        target_folder_id: str | None = None,
        target_parent_id: str | None = None,
        resource_name: str | None = None,
        source: str = "unknown",
    ) -> None:
        title = normalize_transfer_display_title(display_title) or str(display_title or "").strip()
        if len(title) < 1:
            return

        normalized_type = "tv" if str(media_type or "").lower() == "tv" else "movie"
        parsed_tmdb_id = int(tmdb_id) if tmdb_id and int(tmdb_id) > 0 else None
        folder_id = str(target_folder_id or "").strip() or None
        parent_id = str(target_parent_id or "").strip() or None
        douban_text = str(douban_id or "").strip() or None
        resource = str(resource_name or "").strip() or None

        if not any([folder_id, parent_id, parsed_tmdb_id, douban_text]):
            return

        try:
            async with async_session_maker() as db:
                db.add(
                    TransferIntent(
                        tmdb_id=parsed_tmdb_id,
                        douban_id=douban_text,
                        media_type=normalized_type,
                        display_title=title,
                        target_folder_id=folder_id,
                        target_parent_id=parent_id,
                        resource_name=resource,
                        source=str(source or "unknown")[:50],
                    )
                )
                await db.commit()
            await self._cleanup_old_rows()
        except Exception as exc:
            logger.warning("登记转存意图失败: %s", exc)

    async def find_best_match(
        self,
        *,
        parent_cid: str = "",
        file_fid: str = "",
        tmdb_id: int | None = None,
        media_type: str = "",
    ) -> dict[str, Any] | None:
        parent = str(parent_cid or "").strip()
        fid = str(file_fid or "").strip()
        normalized_type = str(media_type or "").strip().lower()
        parsed_tmdb_id = int(tmdb_id) if tmdb_id and int(tmdb_id) > 0 else None

        async with async_session_maker() as db:
            queries: list[Any] = []
            if parent:
                queries.append(
                    select(TransferIntent)
                    .where(TransferIntent.target_folder_id == parent)
                    .order_by(TransferIntent.created_at.desc())
                    .limit(1)
                )
                queries.append(
                    select(TransferIntent)
                    .where(TransferIntent.target_parent_id == parent)
                    .order_by(TransferIntent.created_at.desc())
                    .limit(1)
                )
            if parsed_tmdb_id:
                stmt = (
                    select(TransferIntent)
                    .where(TransferIntent.tmdb_id == parsed_tmdb_id)
                    .order_by(TransferIntent.created_at.desc())
                    .limit(1)
                )
                if normalized_type in {"movie", "tv"}:
                    stmt = stmt.where(TransferIntent.media_type == normalized_type)
                queries.append(stmt)

            for stmt in queries:
                row = (await db.execute(stmt)).scalar_one_or_none()
                payload = self._row_to_dict(row)
                if payload:
                    return payload

            if parent or fid:
                recent = (
                    await db.execute(
                        select(TransferIntent)
                        .order_by(TransferIntent.created_at.desc())
                        .limit(200)
                    )
                ).scalars().all()
                for row in recent:
                    if parent and row.target_folder_id == parent:
                        return self._row_to_dict(row)
                    if parent and row.target_parent_id == parent:
                        return self._row_to_dict(row)
        return None

    @staticmethod
    def _row_to_dict(row: TransferIntent | None) -> dict[str, Any] | None:
        if not row:
            return None
        title = str(row.display_title or "").strip()
        if not title:
            return None
        return {
            "display_title": title,
            "tmdb_id": row.tmdb_id,
            "douban_id": row.douban_id,
            "media_type": row.media_type,
            "target_folder_id": row.target_folder_id,
            "target_parent_id": row.target_parent_id,
            "resource_name": row.resource_name,
            "source": row.source,
        }

    async def _cleanup_old_rows(self) -> None:
        cutoff = beijing_now() - timedelta(days=_RETENTION_DAYS)
        async with async_session_maker() as db:
            await db.execute(delete(TransferIntent).where(TransferIntent.created_at < cutoff))
            count = (
                await db.execute(select(TransferIntent.id).limit(_MAX_ROWS + 1))
            ).all()
            if len(count) <= _MAX_ROWS:
                await db.commit()
                return
            stale_ids = (
                await db.execute(
                    select(TransferIntent.id)
                    .order_by(TransferIntent.created_at.asc())
                    .limit(max(0, len(count) - _MAX_ROWS))
                )
            ).scalars().all()
            if stale_ids:
                await db.execute(delete(TransferIntent).where(TransferIntent.id.in_(stale_ids)))
            await db.commit()


transfer_intent_service = TransferIntentService()
