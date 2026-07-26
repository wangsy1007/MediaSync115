"""转存文件与 TMDB 一一绑定：归档扫描优先按 file_fid 识别。"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select

from app.core.database import async_session_maker
from app.core.timezone_utils import beijing_now
from app.models.transfer_file_binding import TransferFileBinding
from app.services.transfer_intent_service import normalize_transfer_display_title

logger = logging.getLogger(__name__)

_RETENTION_DAYS = 90
_MAX_ROWS = 5000
_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".ts",
    ".m2ts",
    ".mpg",
    ".mpeg",
    ".rmvb",
    ".rm",
    ".3gp",
}


def _is_video_name(name: str) -> bool:
    text = str(name or "").strip().lower()
    if not text or text.startswith("."):
        return False
    return any(text.endswith(ext) for ext in _VIDEO_EXTENSIONS)


class TransferFileBindingService:
    async def bind_files(
        self,
        *,
        file_fids: list[str] | tuple[str, ...] | set[str],
        tmdb_id: int,
        media_type: str = "movie",
        display_title: str = "",
        parent_cid: str | None = None,
        season: int | None = None,
        episode: int | None = None,
        source: str = "unknown",
        download_record_id: int | None = None,
        subscription_id: int | None = None,
        resource_name: str | None = None,
    ) -> int:
        """按 file_fid upsert 绑定；返回写入条数。"""
        parsed_tmdb = int(tmdb_id) if tmdb_id and int(tmdb_id) > 0 else 0
        if parsed_tmdb <= 0:
            return 0

        fids = sorted(
            {
                str(fid or "").strip()
                for fid in (file_fids or [])
                if str(fid or "").strip()
            }
        )
        if not fids:
            return 0

        normalized_type = "tv" if str(media_type or "").lower() == "tv" else "movie"
        title = (
            normalize_transfer_display_title(display_title)
            or str(display_title or "").strip()
        )
        parent = str(parent_cid or "").strip() or None
        resource = str(resource_name or "").strip() or None
        source_text = str(source or "unknown")[:50]
        season_val = int(season) if season is not None and int(season) >= 0 else None
        episode_val = int(episode) if episode is not None and int(episode) >= 0 else None

        written = 0
        try:
            async with async_session_maker() as db:
                existing_rows = (
                    await db.execute(
                        select(TransferFileBinding).where(
                            TransferFileBinding.file_fid.in_(fids)
                        )
                    )
                ).scalars().all()
                by_fid = {str(row.file_fid): row for row in existing_rows}

                for fid in fids:
                    row = by_fid.get(fid)
                    if row is None:
                        db.add(
                            TransferFileBinding(
                                file_fid=fid,
                                tmdb_id=parsed_tmdb,
                                media_type=normalized_type,
                                display_title=title,
                                parent_cid=parent,
                                season=season_val,
                                episode=episode_val,
                                source=source_text,
                                download_record_id=download_record_id,
                                subscription_id=subscription_id,
                                resource_name=resource,
                            )
                        )
                    else:
                        row.tmdb_id = parsed_tmdb
                        row.media_type = normalized_type
                        row.display_title = title
                        row.parent_cid = parent
                        row.season = season_val
                        row.episode = episode_val
                        row.source = source_text
                        row.download_record_id = download_record_id
                        row.subscription_id = subscription_id
                        row.resource_name = resource
                        row.created_at = beijing_now()
                    written += 1
                await db.commit()
            await self._cleanup_old_rows()
        except Exception as exc:
            logger.warning("写入转存文件绑定失败: %s", exc)
            return 0
        return written

    async def list_video_fids(
        self,
        folder_cid: str,
        *,
        pan115: Any | None = None,
        max_files: int = 1150,
    ) -> set[str]:
        """列出目录下一层视频 file_fid，供转存前后 diff。"""
        videos = await self._list_folder_videos(
            folder_cid, pan115=pan115, max_files=max_files
        )
        return {fid for fid, _name in videos}

    async def bind_folder_files(
        self,
        *,
        folder_cid: str,
        tmdb_id: int,
        media_type: str = "movie",
        display_title: str = "",
        source: str = "unknown",
        download_record_id: int | None = None,
        subscription_id: int | None = None,
        resource_name: str | None = None,
        pan115: Any | None = None,
        max_files: int = 200,
        before_fids: set[str] | None = None,
        name_hints: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> int:
        """列出文件夹下视频并批量绑定同一 TMDB。

        - 专用影视目录：直接绑定目录内全部视频
        - 公共监听目录直存：传入转存前 before_fids，仅绑定新增文件；
          或传 name_hints 按文件名精确匹配
        """
        cid = str(folder_cid or "").strip()
        if not cid:
            return 0
        parsed_tmdb = int(tmdb_id) if tmdb_id and int(tmdb_id) > 0 else 0
        if parsed_tmdb <= 0:
            return 0

        videos = await self._list_folder_videos(
            cid, pan115=pan115, max_files=max_files
        )
        if not videos:
            return 0

        video_fids: list[str]
        if before_fids is not None:
            before = {str(x or "").strip() for x in before_fids if str(x or "").strip()}
            video_fids = [fid for fid, _ in videos if fid not in before]
        elif name_hints:
            hints = {
                str(n or "").strip().lower()
                for n in name_hints
                if str(n or "").strip()
            }
            video_fids = [
                fid for fid, name in videos if name.strip().lower() in hints
            ]
        else:
            video_fids = [fid for fid, _ in videos]

        if not video_fids:
            return 0

        return await self.bind_files(
            file_fids=video_fids,
            tmdb_id=parsed_tmdb,
            media_type=media_type,
            display_title=display_title,
            parent_cid=cid,
            source=source,
            download_record_id=download_record_id,
            subscription_id=subscription_id,
            resource_name=resource_name,
        )

    async def _list_folder_videos(
        self,
        folder_cid: str,
        *,
        pan115: Any | None = None,
        max_files: int = 1150,
    ) -> list[tuple[str, str]]:
        cid = str(folder_cid or "").strip()
        if not cid:
            return []

        client = pan115
        if client is None:
            from app.services.pan115_service import pan115_service

            client = pan115_service

        try:
            page_limit = min(max(int(max_files), 1), 1150)
            listing = await client.get_file_list(
                cid, offset=0, limit=page_limit, asc=0, o="user_ptime"
            )
            items = (
                listing.get("data")
                or listing.get("files")
                or listing.get("list")
                or []
            )
            if isinstance(listing, list):
                items = listing
        except Exception as exc:
            logger.warning("列举转存目录失败 cid=%s: %s", cid, exc)
            return []

        is_folder = getattr(client, "_is_folder_item", None)
        videos: list[tuple[str, str]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            if len(videos) >= max_files:
                break
            if callable(is_folder):
                try:
                    if bool(is_folder(item)):
                        continue
                except Exception:
                    pass
            elif bool(item.get("is_dir") or item.get("fc") == 0):
                continue
            name = str(item.get("n") or item.get("name") or item.get("fn") or "")
            fid = str(item.get("fid") or "").strip()
            if not fid or not _is_video_name(name):
                continue
            videos.append((fid, name))
        return videos

    async def get_by_file_fid(self, file_fid: str) -> dict[str, Any] | None:
        fid = str(file_fid or "").strip()
        if not fid:
            return None
        async with async_session_maker() as db:
            row = (
                await db.execute(
                    select(TransferFileBinding)
                    .where(TransferFileBinding.file_fid == fid)
                    .order_by(TransferFileBinding.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return self._row_to_dict(row)

    async def get_by_file_fids(
        self, file_fids: list[str] | tuple[str, ...] | set[str]
    ) -> dict[str, dict[str, Any]]:
        fids = sorted(
            {
                str(fid or "").strip()
                for fid in (file_fids or [])
                if str(fid or "").strip()
            }
        )
        if not fids:
            return {}
        async with async_session_maker() as db:
            rows = (
                await db.execute(
                    select(TransferFileBinding).where(
                        TransferFileBinding.file_fid.in_(fids)
                    )
                )
            ).scalars().all()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload = self._row_to_dict(row)
            if payload:
                result[str(row.file_fid)] = payload
        return result

    @staticmethod
    def _row_to_dict(row: TransferFileBinding | None) -> dict[str, Any] | None:
        if not row:
            return None
        tmdb_id = int(row.tmdb_id or 0)
        if tmdb_id <= 0:
            return None
        return {
            "file_fid": str(row.file_fid or ""),
            "tmdb_id": tmdb_id,
            "media_type": str(row.media_type or "movie"),
            "display_title": str(row.display_title or "").strip(),
            "parent_cid": row.parent_cid,
            "season": row.season,
            "episode": row.episode,
            "source": row.source,
            "download_record_id": row.download_record_id,
            "subscription_id": row.subscription_id,
            "resource_name": row.resource_name,
        }

    async def _cleanup_old_rows(self) -> None:
        cutoff = beijing_now() - timedelta(days=_RETENTION_DAYS)
        async with async_session_maker() as db:
            await db.execute(
                delete(TransferFileBinding).where(
                    TransferFileBinding.created_at < cutoff
                )
            )
            count = (
                await db.execute(select(TransferFileBinding.id).limit(_MAX_ROWS + 1))
            ).all()
            if len(count) <= _MAX_ROWS:
                await db.commit()
                return
            overflow = max(0, len(count) - _MAX_ROWS)
            stale_ids = (
                await db.execute(
                    select(TransferFileBinding.id)
                    .order_by(TransferFileBinding.created_at.asc())
                    .limit(overflow)
                )
            ).scalars().all()
            if stale_ids:
                await db.execute(
                    delete(TransferFileBinding).where(
                        TransferFileBinding.id.in_(stale_ids)
                    )
                )
            await db.commit()


transfer_file_binding_service = TransferFileBindingService()
