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
_SHARED_PARENT_SCAN_LIMIT = 300


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


def _title_hints(*candidates: str) -> list[str]:
    hints: list[str] = []
    for candidate in candidates:
        value = extract_chinese_title_from_text(candidate)
        if value and value not in hints:
            hints.append(value)
    return hints


def _titles_overlap(left: str, right: str) -> bool:
    a = str(left or "").strip()
    b = str(right or "").strip()
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    a_latin = re.sub(r"[^a-z0-9]+", "", a.lower())
    b_latin = re.sub(r"[^a-z0-9]+", "", b.lower())
    return bool(a_latin and b_latin and len(a_latin) >= 3 and a_latin == b_latin)


def intent_matches_file(
    intent: dict[str, Any] | None,
    *,
    filename: str = "",
    folder_name: str = "",
    tmdb_id: int | None = None,
) -> bool:
    """判断转存意图是否与待归档文件属于同一部影视。"""
    if not isinstance(intent, dict) or not intent:
        return False

    parsed_tmdb_id = int(tmdb_id) if tmdb_id and int(tmdb_id) > 0 else None
    intent_tmdb_id = (
        int(intent["tmdb_id"])
        if intent.get("tmdb_id") and int(intent["tmdb_id"]) > 0
        else None
    )
    if parsed_tmdb_id and intent_tmdb_id:
        return parsed_tmdb_id == intent_tmdb_id

    file_hints = _title_hints(filename, folder_name)
    intent_hints = _title_hints(
        str(intent.get("display_title") or ""),
        str(intent.get("resource_name") or ""),
    )
    if not file_hints:
        return False
    if not intent_hints:
        return False
    return any(
        _titles_overlap(file_hint, intent_hint)
        for file_hint in file_hints
        for intent_hint in intent_hints
    )


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
        filename: str = "",
        folder_name: str = "",
    ) -> dict[str, Any] | None:
        parent = str(parent_cid or "").strip()
        fid = str(file_fid or "").strip()
        normalized_type = str(media_type or "").strip().lower()
        parsed_tmdb_id = int(tmdb_id) if tmdb_id and int(tmdb_id) > 0 else None
        filename_text = str(filename or "").strip()
        folder_text = str(folder_name or "").strip()

        async with async_session_maker() as db:
            if parent:
                folder_row = (
                    await db.execute(
                        select(TransferIntent)
                        .where(TransferIntent.target_folder_id == parent)
                        .order_by(TransferIntent.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                payload = self._row_to_dict(folder_row)
                if payload and intent_matches_file(
                    payload,
                    filename=filename_text,
                    folder_name=folder_text,
                    tmdb_id=parsed_tmdb_id,
                ):
                    return payload

            if parsed_tmdb_id:
                stmt = (
                    select(TransferIntent)
                    .where(TransferIntent.tmdb_id == parsed_tmdb_id)
                    .order_by(TransferIntent.created_at.desc())
                    .limit(_SHARED_PARENT_SCAN_LIMIT)
                )
                if normalized_type in {"movie", "tv"}:
                    stmt = stmt.where(TransferIntent.media_type == normalized_type)
                rows = (await db.execute(stmt)).scalars().all()
                for row in rows:
                    payload = self._row_to_dict(row)
                    if not payload:
                        continue
                    if intent_matches_file(
                        payload,
                        filename=filename_text,
                        folder_name=folder_text,
                        tmdb_id=parsed_tmdb_id,
                    ):
                        return payload

            if parent:
                rows = (
                    await db.execute(
                        select(TransferIntent)
                        .where(
                            (TransferIntent.target_parent_id == parent)
                            | (TransferIntent.target_folder_id == parent)
                        )
                        .order_by(TransferIntent.created_at.desc())
                        .limit(_SHARED_PARENT_SCAN_LIMIT)
                    )
                ).scalars().all()
                for row in rows:
                    payload = self._row_to_dict(row)
                    if not payload:
                        continue
                    if intent_matches_file(
                        payload,
                        filename=filename_text,
                        folder_name=folder_text,
                        tmdb_id=parsed_tmdb_id,
                    ):
                        return payload

            if fid:
                rows = (
                    await db.execute(
                        select(TransferIntent)
                        .order_by(TransferIntent.created_at.desc())
                        .limit(_SHARED_PARENT_SCAN_LIMIT)
                    )
                ).scalars().all()
                for row in rows:
                    if row.target_folder_id != fid and row.target_parent_id != fid:
                        continue
                    payload = self._row_to_dict(row)
                    if payload and intent_matches_file(
                        payload,
                        filename=filename_text,
                        folder_name=folder_text,
                        tmdb_id=parsed_tmdb_id,
                    ):
                        return payload
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
