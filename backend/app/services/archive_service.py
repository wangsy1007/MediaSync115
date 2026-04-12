import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select

from app.core.database import async_session_maker
from app.models.archive import ArchiveStatus, ArchiveTask
from app.services.operation_log_service import operation_log_service
from app.services.pan115_service import Pan115Service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.tmdb_service import tmdb_service

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".ts",
}
IGNORE_PATTERNS = (
    r"\b(?:2160p|1080p|720p|480p|4k|8k)\b",
    r"\b(?:bluray|bdrip|brrip|webrip|web-dl|webdl|hdtv|dvdrip|remux)\b",
    r"\b(?:x264|x265|h264|h265|hevc|av1|aac|dts|atmos|ac3|ddp5?\.1?)\b",
    r"\b(?:hdr|dv|dolby\s?vision|imax|repack|proper|extended|uncut)\b",
    r"\b(?:yyets|rarbg|nhd|mteam|mteampt|btbtt|wiki)\b",
)
EPISODE_PATTERNS = (
    re.compile(r"(?i)\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b"),
    re.compile(r"(?i)\b(?P<season>\d{1,2})x(?P<episode>\d{1,3})\b"),
    re.compile(r"(?i)\bEP?(?P<episode>\d{1,3})\b"),
)
MOVIE_GENRE_MAP = {
    28: "action",
    12: "adventure",
    16: "animation",
    35: "comedy",
    80: "crime",
    99: "documentary",
    18: "drama",
    10751: "family",
    14: "fantasy",
    36: "history",
    27: "horror",
    10402: "music",
    9648: "mystery",
    10749: "romance",
    878: "science-fiction",
    10770: "tv-movie",
    53: "thriller",
    10752: "war",
    37: "western",
}
TV_GENRE_MAP = {
    10759: "action-adventure",
    16: "animation",
    35: "comedy",
    80: "crime",
    99: "documentary",
    18: "drama",
    10751: "family",
    10762: "kids",
    9648: "mystery",
    10763: "news",
    10764: "reality",
    10765: "sci-fi-fantasy",
    10766: "soap",
    10767: "talk",
    10768: "war-politics",
    37: "western",
}


class ArchiveService:
    """归档刮削服务 - 操作 115 网盘目录"""

    def __init__(self) -> None:
        self._scan_lock = asyncio.Lock()
        self._pan115: Pan115Service | None = None
        self._background_scan_task: asyncio.Task | None = None
        self._last_scan_started_at: datetime | None = None
        self._last_scan_finished_at: datetime | None = None
        self._last_scan_trigger: str = ""
        self._last_scan_summary: dict[str, Any] | None = None
        self._last_scan_error: str = ""

    def _get_pan115(self) -> Pan115Service:
        if self._pan115 is None:
            self._pan115 = Pan115Service()
        return self._pan115

    def get_config(self) -> dict[str, Any]:
        return runtime_settings_service.get_archive_config()

    def get_runtime_status(self) -> dict[str, Any]:
        config = self.get_config()
        return {
            "archive_enabled": config.get("archive_enabled", False),
            "watch_cid": config.get("archive_watch_cid", ""),
            "output_cid": config.get("archive_output_cid", ""),
            "scan_running": self.is_scan_running(),
            "last_scan_started_at": self._last_scan_started_at.isoformat()
            if isinstance(self._last_scan_started_at, datetime)
            else "",
            "last_scan_finished_at": self._last_scan_finished_at.isoformat()
            if isinstance(self._last_scan_finished_at, datetime)
            else "",
            "last_scan_trigger": self._last_scan_trigger,
            "last_scan_summary": self._last_scan_summary,
            "last_scan_error": self._last_scan_error,
        }

    def is_scan_running(self) -> bool:
        return bool(
            self._background_scan_task and not self._background_scan_task.done()
        )

    async def start_scan(self, trigger: str = "manual") -> dict[str, Any]:
        """后台启动一次归档扫描，避免前端请求长时间阻塞。"""
        if self.is_scan_running() or self._scan_lock.locked():
            return {
                "started": False,
                "running": True,
                "message": "归档扫描已在执行中，请稍后刷新任务列表查看进度",
                "runtime": self.get_runtime_status(),
            }

        self._last_scan_started_at = datetime.utcnow()
        self._last_scan_finished_at = None
        self._last_scan_trigger = trigger
        self._last_scan_summary = None
        self._last_scan_error = ""

        self._background_scan_task = asyncio.create_task(
            self.run_scan(trigger=trigger),
            name=f"archive-scan-{trigger}",
        )
        self._background_scan_task.add_done_callback(self._handle_background_scan_done)

        return {
            "started": True,
            "running": True,
            "message": "归档扫描已启动，正在后台执行",
            "runtime": self.get_runtime_status(),
        }

    def _handle_background_scan_done(self, task: asyncio.Task) -> None:
        self._last_scan_finished_at = datetime.utcnow()
        try:
            self._last_scan_summary = task.result()
            self._last_scan_error = ""
        except Exception as exc:
            self._last_scan_summary = None
            self._last_scan_error = str(exc or "")[:2000]
            logger.exception("Archive background scan failed")

    async def run_scan(self, trigger: str = "manual") -> dict[str, Any]:
        """执行一次完整扫描"""
        async with self._scan_lock:
            config = self.get_config()
            watch_cid = str(config.get("archive_watch_cid") or "").strip()
            output_cid = str(config.get("archive_output_cid") or "").strip()
            if not watch_cid:
                raise ValueError("请先配置归档监听目录（115 文件夹 ID）")
            if not output_cid:
                raise ValueError("请先配置归档输出目录（115 文件夹 ID）")

            pan115 = self._get_pan115()
            source_items = await self._list_video_files(pan115, watch_cid)
            folder_cache: dict[tuple[str, ...], str] = {}

            await operation_log_service.log_background_event(
                source_type="background_task"
                if trigger != "scheduler"
                else "scheduler",
                module="archive",
                action="archive.scan.start",
                status="info",
                message=f"归档扫描开始：触发方式={trigger}，待处理文件数={len(source_items)}",
                extra={
                    "trigger": trigger,
                    "watch_cid": watch_cid,
                    "file_count": len(source_items),
                },
            )

            summary = {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "total": len(source_items),
                "items": [],
            }
            for item in source_items:
                result = await self._process_one(
                    pan115,
                    item,
                    output_cid,
                    trigger=trigger,
                    folder_cache=folder_cache,
                )
                summary["items"].append(result)
                s = str(result.get("status") or "")
                if s == ArchiveStatus.SUCCESS.value:
                    summary["success"] += 1
                elif s == ArchiveStatus.SKIPPED.value:
                    summary["skipped"] += 1
                else:
                    summary["failed"] += 1

            finish_status = "success" if summary["failed"] == 0 else "warning"
            await operation_log_service.log_background_event(
                source_type="background_task"
                if trigger != "scheduler"
                else "scheduler",
                module="archive",
                action="archive.scan.finish",
                status=finish_status,
                message=(
                    f"归档扫描完成：总计 {summary['total']} 个，"
                    f"成功 {summary['success']} 个，"
                    f"跳过 {summary['skipped']} 个，"
                    f"失败 {summary['failed']} 个"
                ),
                extra={"trigger": trigger, **summary},
            )
            return summary

    async def _list_video_files(
        self, pan115: Pan115Service, cid: str
    ) -> list[dict[str, Any]]:
        """并发 BFS 列出监听目录及其子目录中的视频文件（两阶段扫描第一阶段）"""
        items: list[dict[str, Any]] = []
        seen_dirs: set[str] = set()
        dir_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        items_lock = asyncio.Lock()
        seen_lock = asyncio.Lock()

        await dir_queue.put((str(cid or "0").strip() or "0", ""))

        async def _worker() -> None:
            while True:
                try:
                    current_cid, current_path = dir_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                async with seen_lock:
                    if current_cid in seen_dirs:
                        continue
                    seen_dirs.add(current_cid)

                offset = 0
                limit = 1000
                while True:
                    try:
                        result = await pan115.get_file_list(
                            cid=current_cid, offset=offset, limit=limit
                        )
                    except Exception:
                        logger.exception("列出目录 %s 失败", current_cid)
                        break

                    batch = result.get("data") or []
                    if not batch:
                        break

                    local_dirs: list[tuple[str, str]] = []
                    local_items: list[dict[str, Any]] = []

                    for it in batch:
                        if not isinstance(it, dict):
                            continue
                        name = str(it.get("n") or it.get("name") or "").strip()
                        if not name:
                            continue
                        if pan115._is_folder_item(it):
                            folder_cid = str(
                                pan115._extract_folder_id(it) or ""
                            ).strip()
                            if folder_cid:
                                next_path = (
                                    f"{current_path}/{name}" if current_path else name
                                )
                                local_dirs.append((folder_cid, next_path))
                            continue

                        fid = str(it.get("fid") or "").strip()
                        if not fid or not self._is_video(name):
                            continue

                        relative_path = (
                            f"{current_path}/{name}" if current_path else name
                        )
                        local_items.append(
                            {
                                "fid": fid,
                                "name": name,
                                "cid": current_cid,
                                "relative_path": relative_path,
                            }
                        )

                    for d in local_dirs:
                        await dir_queue.put(d)
                    async with items_lock:
                        items.extend(local_items)

                    if len(batch) < limit:
                        break
                    offset += limit

        # 启动多个 worker 并发扫描；worker 数与全局队列 worker 数保持一致
        worker_count = 3
        workers = [asyncio.create_task(_worker()) for _ in range(worker_count)]
        await asyncio.gather(*workers, return_exceptions=True)

        items.sort(
            key=lambda x: str(x.get("relative_path") or x.get("name") or "").lower()
        )
        return items

    async def _process_one(
        self,
        pan115: Pan115Service,
        item: dict[str, Any],
        output_cid: str,
        trigger: str = "manual",
        folder_cache: dict[tuple[str, ...], str] | None = None,
    ) -> dict[str, Any]:
        """处理单个 115 文件"""
        fid = item["fid"]
        filename = item["name"]

        parsed = self.parse_media_filename(filename)
        db_task = await self._upsert_task(
            task_id=None, source_fid=fid, source_filename=filename
        )

        await operation_log_service.log_background_event(
            source_type="background_task",
            module="archive",
            action="archive.file.start",
            status="info",
            message=f"开始归档文件：{filename}",
            extra={"task_id": db_task.id, "trigger": trigger, "source_fid": fid},
        )
        await operation_log_service.log_background_event(
            source_type="background_task",
            module="archive",
            action="archive.file.parsed",
            status="info",
            message=(
                f"文件解析完成：类型={parsed['media_type']}，"
                f"标题={parsed['query_title']}，"
                f"年份={parsed.get('year') or '-'}，"
                f"季集={parsed.get('season') or '-'} / {parsed.get('episode') or '-'}"
            ),
            extra={"task_id": db_task.id, "parsed": parsed},
        )

        try:
            matched = await self.identify_media(parsed)
            if not matched:
                raise ValueError("TMDB 未匹配到可用结果")

            genre_name = str(matched.get("genre_name") or "other")
            title = str(matched.get("title") or parsed["query_title"])
            year = str(matched.get("year") or parsed.get("year") or "")
            title_folder = f"{title} ({year})" if year else title

            if parsed["media_type"] == "tv":
                target_cid = await self._ensure_tv_path(
                    pan115,
                    output_cid,
                    genre_name,
                    title_folder,
                    parsed,
                    folder_cache=folder_cache,
                )
                target_desc = f"tv/{genre_name}/{title_folder}/Season {int(parsed.get('season') or 1):02d}"
            else:
                target_cid = await self._ensure_movie_path(
                    pan115,
                    output_cid,
                    genre_name,
                    title_folder,
                    folder_cache=folder_cache,
                )
                target_desc = f"movies/{genre_name}/{title_folder}"

            await self._update_task(
                db_task.id,
                media_type=parsed["media_type"],
                tmdb_id=matched.get("tmdb_id"),
                tmdb_title=title,
                tmdb_year=year,
                genre_name=genre_name,
                target_path=target_desc,
            )
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="archive",
                action="archive.file.matched",
                status="info",
                message=f"TMDB 匹配成功：{title} ({year})，分类={genre_name}",
                extra={"task_id": db_task.id, "matched": matched},
            )
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="archive",
                action="archive.file.plan",
                status="info",
                message=f"归档目标目录已生成：{target_desc}",
                extra={
                    "task_id": db_task.id,
                    "target_cid": target_cid,
                    "target_desc": target_desc,
                },
            )

            await pan115.move_file(fid, target_cid)
            await self._mark_task_success(db_task.id)
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="archive",
                action="archive.file.success",
                status="success",
                message=f"归档完成：{filename} 已移动到 {target_desc}",
                extra={"task_id": db_task.id, "target_desc": target_desc},
            )
            return {
                "task_id": db_task.id,
                "status": ArchiveStatus.SUCCESS.value,
                "source_fid": fid,
                "source_filename": filename,
                "target_desc": target_desc,
            }
        except Exception as exc:
            msg = str(exc) or "未知错误"
            await self._mark_task_failed(db_task.id, msg)
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="archive",
                action="archive.file.failed",
                status="failed",
                message=f"归档失败：{filename}，原因：{msg}",
                extra={"task_id": db_task.id, "source_fid": fid},
            )
            return {
                "task_id": db_task.id,
                "status": ArchiveStatus.FAILED.value,
                "source_fid": fid,
                "source_filename": filename,
                "message": msg,
            }

    async def _ensure_movie_path(
        self,
        pan115: Pan115Service,
        root_cid: str,
        genre: str,
        title_folder: str,
        folder_cache: dict[tuple[str, ...], str] | None = None,
    ) -> str:
        """确保电影归档目录存在，返回最终目录 CID"""
        cache_key = ("movie", str(root_cid), str(genre), str(title_folder))
        if folder_cache and cache_key in folder_cache:
            return folder_cache[cache_key]

        movies_cid = await pan115.get_or_create_folder(root_cid, "movies")
        genre_cid = await pan115.get_or_create_folder(movies_cid, genre)
        folder_cid = await pan115.get_or_create_folder(genre_cid, title_folder)
        if folder_cache is not None:
            folder_cache[cache_key] = folder_cid
        return folder_cid

    async def _ensure_tv_path(
        self,
        pan115: Pan115Service,
        root_cid: str,
        genre: str,
        title_folder: str,
        parsed: dict[str, Any],
        folder_cache: dict[tuple[str, ...], str] | None = None,
    ) -> str:
        """确保剧集归档目录存在，返回最终目录 CID"""
        season = int(parsed.get("season") or 1)
        cache_key = (
            "tv",
            str(root_cid),
            str(genre),
            str(title_folder),
            f"S{season:02d}",
        )
        if folder_cache and cache_key in folder_cache:
            return folder_cache[cache_key]

        tv_cid = await pan115.get_or_create_folder(root_cid, "tv")
        genre_cid = await pan115.get_or_create_folder(tv_cid, genre)
        title_cid = await pan115.get_or_create_folder(genre_cid, title_folder)
        season_dir = f"Season {season:02d}"
        season_cid = await pan115.get_or_create_folder(title_cid, season_dir)
        if folder_cache is not None:
            folder_cache[cache_key] = season_cid
        return season_cid

    # ---------- TMDB 识别 ----------

    async def identify_media(self, parsed: dict[str, Any]) -> dict[str, Any] | None:
        media_type = str(parsed.get("media_type") or "movie")
        query_title = str(parsed.get("query_title") or "").strip()
        if not query_title:
            return None
        year_val = parsed.get("year")
        year = int(year_val) if str(year_val or "").isdigit() else None

        result = await tmdb_service.search_by_media_type(
            query=query_title,
            media_type=media_type,
            page=1,
            year=year,
        )
        items = result.get("results") if isinstance(result.get("results"), list) else []
        if not items and year is not None:
            result = await tmdb_service.search_by_media_type(
                query=query_title,
                media_type=media_type,
                page=1,
                year=None,
            )
            items = (
                result.get("results") if isinstance(result.get("results"), list) else []
            )
        if not items:
            return None

        first = items[0]
        tmdb_id = first.get("tmdb_id") or first.get("id")
        if not isinstance(tmdb_id, int):
            return None

        detail = (
            await tmdb_service.get_movie_detail(tmdb_id)
            if media_type == "movie"
            else await tmdb_service.get_tv_detail(tmdb_id)
        )
        title = str(
            detail.get("title")
            or detail.get("name")
            or first.get("title")
            or first.get("name")
            or query_title
        ).strip()
        release_date = str(
            detail.get("release_date") or detail.get("first_air_date") or ""
        ).strip()
        year_text = (
            release_date[:4]
            if len(release_date) >= 4
            else str(parsed.get("year") or "")
        )
        genre_name = self._extract_genre_name(detail, media_type)

        return {
            "tmdb_id": tmdb_id,
            "title": title,
            "year": year_text,
            "genre_name": genre_name,
        }

    # ---------- 文件名解析 ----------

    def parse_media_filename(self, filename: str) -> dict[str, Any]:
        name = re.sub(r"\.[^.]+$", "", filename)
        ext_match = re.search(r"\.[^.]+$", filename)
        ext = ext_match.group(0) if ext_match else ""

        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", name)
        year = year_match.group(1) if year_match else None

        media_type = "movie"
        season = None
        episode = None
        title_end = len(name)
        for pattern in EPISODE_PATTERNS:
            match = pattern.search(name)
            if not match:
                continue
            media_type = "tv"
            title_end = min(title_end, match.start())
            sg = match.groupdict().get("season")
            eg = match.groupdict().get("episode")
            if sg:
                season = int(sg)
            if eg:
                episode = int(eg)
            break

        if year_match and year_match.start() < title_end:
            title_end = year_match.start()

        raw_title = name[:title_end] if title_end > 0 else name
        query_title = self._normalize_title(raw_title) or self._normalize_title(name)

        return {
            "source_filename": filename,
            "extension": ext,
            "media_type": media_type,
            "query_title": query_title,
            "year": year,
            "season": season,
            "episode": episode,
        }

    # ---------- 任务 CRUD ----------

    async def retry_task(self, task_id: int) -> dict[str, Any]:
        async with async_session_maker() as db:
            task = await db.get(ArchiveTask, task_id)
            if not task:
                raise ValueError("归档任务不存在")
            fid = task.source_path
            filename = task.source_filename
        config = self.get_config()
        output_cid = str(config.get("archive_output_cid") or "").strip()
        pan115 = self._get_pan115()
        return await self._process_one(
            pan115,
            {"fid": fid, "name": filename, "cid": ""},
            output_cid,
            trigger="retry",
            folder_cache={},
        )

    async def clear_tasks(self, include_failed: bool = False) -> int:
        statuses = [ArchiveStatus.SUCCESS, ArchiveStatus.SKIPPED]
        if include_failed:
            statuses.append(ArchiveStatus.FAILED)
        async with async_session_maker() as db:
            result = await db.execute(
                delete(ArchiveTask).where(ArchiveTask.status.in_(statuses))
            )
            await db.commit()
            removed = int(result.rowcount or 0)
        await operation_log_service.log_background_event(
            source_type="background_task",
            module="archive",
            action="archive.tasks.clear",
            status="success",
            message=f"已清理归档任务记录 {removed} 条",
            extra={"removed": removed, "include_failed": include_failed},
        )
        return removed

    async def list_tasks(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async with async_session_maker() as db:
            base = select(ArchiveTask)
            total_q = select(func.count(ArchiveTask.id))
            if status:
                try:
                    ns = ArchiveStatus(status)
                except ValueError:
                    raise ValueError("无效的归档任务状态筛选值")
                base = base.where(ArchiveTask.status == ns)
                total_q = total_q.where(ArchiveTask.status == ns)

            rows = await db.execute(
                base.order_by(ArchiveTask.created_at.desc(), ArchiveTask.id.desc())
                .offset(offset)
                .limit(limit)
            )
            total = await db.execute(total_q)

        items = []
        for row in rows.scalars().all():
            items.append(
                {
                    "id": row.id,
                    "source_path": row.source_path,
                    "source_filename": row.source_filename,
                    "media_type": row.media_type,
                    "tmdb_id": row.tmdb_id,
                    "tmdb_title": row.tmdb_title,
                    "tmdb_year": row.tmdb_year,
                    "genre_name": row.genre_name,
                    "target_path": row.target_path,
                    "status": row.status.value
                    if isinstance(row.status, ArchiveStatus)
                    else row.status,
                    "error_message": row.error_message,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                    "completed_at": row.completed_at,
                }
            )
        return {
            "items": items,
            "total": int(total.scalar() or 0),
            "limit": limit,
            "offset": offset,
        }

    # ---------- 内部工具 ----------

    async def _upsert_task(
        self,
        task_id: int | None,
        source_fid: str,
        source_filename: str,
    ) -> ArchiveTask:
        async with async_session_maker() as db:
            task = await db.get(ArchiveTask, task_id) if task_id else None
            if task is None:
                task = ArchiveTask(
                    source_path=source_fid,
                    source_filename=source_filename,
                    status=ArchiveStatus.PROCESSING,
                    error_message=None,
                    completed_at=None,
                )
                db.add(task)
            else:
                task.source_path = source_fid
                task.source_filename = source_filename
                task.status = ArchiveStatus.PROCESSING
                task.error_message = None
                task.completed_at = None
            await db.commit()
            await db.refresh(task)
            return task

    async def _update_task(self, task_id: int, **kwargs: Any) -> None:
        async with async_session_maker() as db:
            task = await db.get(ArchiveTask, task_id)
            if not task:
                return
            for k, v in kwargs.items():
                setattr(task, k, v)
            await db.commit()

    async def _mark_task_success(self, task_id: int) -> None:
        await self._update_task(
            task_id,
            status=ArchiveStatus.SUCCESS,
            error_message=None,
            completed_at=datetime.utcnow(),
        )

    async def _mark_task_failed(self, task_id: int, error_message: str) -> None:
        await self._update_task(
            task_id,
            status=ArchiveStatus.FAILED,
            error_message=str(error_message or "")[:2000],
            completed_at=datetime.utcnow(),
        )

    @staticmethod
    def _is_video(filename: str) -> bool:
        idx = filename.rfind(".")
        if idx < 0:
            return False
        return filename[idx:].lower() in VIDEO_EXTENSIONS

    @staticmethod
    def _normalize_title(value: str) -> str:
        text = str(value or "")
        text = re.sub(r"\[[^\]]*\]", " ", text)
        text = re.sub(r"\([^)]*\)", " ", text)
        for pattern in IGNORE_PATTERNS:
            text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
        text = text.replace(".", " ").replace("_", " ").replace("-", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _extract_genre_name(detail: dict[str, Any], media_type: str) -> str:
        genre_map = MOVIE_GENRE_MAP if media_type == "movie" else TV_GENRE_MAP
        genres = detail.get("genres") if isinstance(detail.get("genres"), list) else []
        for g in genres:
            if isinstance(g, dict):
                gid = g.get("id")
                if isinstance(gid, int) and gid in genre_map:
                    return genre_map[gid]
        for g in genres:
            if isinstance(g, dict):
                n = (
                    re.sub(r"[\\/:*?\"<>|]", " ", str(g.get("name") or ""))
                    .strip()
                    .lower()
                )
                if n:
                    return n
        return "other"


archive_service = ArchiveService()
