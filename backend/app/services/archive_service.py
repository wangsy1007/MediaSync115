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

SUBTITLE_EXTENSIONS = {
    ".srt",
    ".ass",
    ".ssa",
    ".vtt",
    ".sub",
    ".idx",
    ".sup",
}

ARCHIVE_EXTENSIONS = VIDEO_EXTENSIONS | SUBTITLE_EXTENSIONS

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
    28: "动作",
    12: "冒险",
    16: "动画",
    35: "喜剧",
    80: "犯罪",
    99: "纪录片",
    18: "剧情",
    10751: "家庭",
    14: "奇幻",
    36: "历史",
    27: "恐怖",
    10402: "音乐",
    9648: "悬疑",
    10749: "爱情",
    878: "科幻",
    10770: "电视电影",
    53: "惊悚",
    10752: "战争",
    37: "西部",
}
TV_GENRE_MAP = {
    10759: "动作冒险",
    16: "动画",
    35: "喜剧",
    80: "犯罪",
    99: "纪录片",
    18: "剧情",
    10751: "家庭",
    10762: "儿童",
    9648: "悬疑",
    10763: "新闻",
    10764: "真人秀",
    10765: "科幻奇幻",
    10766: "肥皂剧",
    10767: "脱口秀",
    10768: "战争政治",
    37: "西部",
}


class _AuthExpiredError(Exception):
    """115 认证过期，整个扫描应立即中断"""


class ArchiveService:
    """归档刮削服务 - 参考 QMediaSync 流程重构"""

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
            cookie = runtime_settings_service.get_pan115_cookie()
            self._pan115 = Pan115Service(cookie)
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
        if self.is_scan_running() or self._scan_lock.locked():
            return {
                "started": False,
                "running": True,
                "message": "归档扫描已在执行中，请稍后刷新查看进度",
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
            self._last_scan_error = self._format_scan_error(exc)
            logger.exception("Archive background scan failed")

    @staticmethod
    def _format_scan_error(exc: Exception) -> str:
        error_text = str(exc or "").strip()
        lowered_error_text = error_text.lower()

        if Pan115Service._is_auth_related_error(error_text):
            return "115 登录已失效，请前往设置页重新扫码登录后再执行归档扫描"

        if (
            Pan115Service._is_method_not_allowed_error(error_text)
            or "频繁" in error_text
            or "网络风控" in error_text
        ):
            return "115 文件列表接口被临时风控拦截（405），请等待数小时后再试，或在设置页重新扫码登录刷新 Cookie"

        if "enoent" in lowered_error_text or "不存在" in error_text:
            return f"文件或目录不存在：{error_text[:500]}"

        if not error_text:
            return "归档扫描失败：未知错误"

        return f"归档扫描失败：{error_text[:500]}"

    # ================================================================
    #  主扫描流程（参考 QMediaSync）
    # ================================================================

    async def run_scan(self, trigger: str = "manual") -> dict[str, Any]:
        async with self._scan_lock:
            config = self.get_config()
            watch_cid = str(config.get("archive_watch_cid") or "").strip()
            output_cid = str(config.get("archive_output_cid") or "").strip()
            if not watch_cid:
                raise ValueError("请先配置归档监听目录（115 文件夹 ID）")
            if not output_cid:
                raise ValueError("请先配置归档输出目录（115 文件夹 ID）")

            pan115 = self._get_pan115()
            log_source_type = (
                "background_task" if trigger != "scheduler" else "scheduler"
            )

            await operation_log_service.log_background_event(
                source_type=log_source_type,
                module="archive",
                action="archive.scan.start",
                status="info",
                message=f"归档扫描开始：触发方式={trigger}，正在扫描监听目录",
                extra={
                    "trigger": trigger,
                    "watch_cid": watch_cid,
                    "output_cid": output_cid,
                },
            )
            try:
                # 阶段一：扫描监听目录下的所有视频+字幕文件
                source_items = await self._scan_source_files(pan115, watch_cid)

                await operation_log_service.log_background_event(
                    source_type=log_source_type,
                    module="archive",
                    action="archive.scan.files",
                    status="info",
                    message=f"扫描完成：发现 {len(source_items)} 个视频/字幕文件",
                    extra={
                        "trigger": trigger,
                        "file_count": len(source_items),
                    },
                )

                # 过滤：只取视频文件作为主文件，字幕文件作为附属
                video_items = [it for it in source_items if it["is_video"]]
                subtitle_items = [it for it in source_items if it["is_subtitle"]]

                summary = {
                    "success": 0,
                    "failed": 0,
                    "skipped": 0,
                    "total": len(video_items),
                    "items": [],
                }

                if not video_items:
                    await operation_log_service.log_background_event(
                        source_type=log_source_type,
                        module="archive",
                        action="archive.scan.finish",
                        status="info",
                        message="监听目录中未发现视频文件，跳过归档",
                        extra={"trigger": trigger, **summary},
                    )
                    return summary

                # 阶段二：批量识别 + 预创建分类目录
                folder_cache: dict[tuple[str, ...], str] = {}
                processed_cids: set[str] = set()

                for item in video_items:
                    result = await self._process_one(
                        pan115,
                        item,
                        output_cid,
                        trigger=trigger,
                        folder_cache=folder_cache,
                        subtitle_items=subtitle_items,
                    )
                    summary["items"].append(result)
                    s = str(result.get("status") or "")
                    if s == ArchiveStatus.SUCCESS.value:
                        summary["success"] += 1
                    elif s == ArchiveStatus.SKIPPED.value:
                        summary["skipped"] += 1
                    else:
                        summary["failed"] += 1

                    target_cid = str(result.get("target_cid") or "")
                    if target_cid and target_cid not in processed_cids:
                        processed_cids.add(target_cid)

                # 阶段三：清理空源目录
                await self._cleanup_empty_dirs(pan115, watch_cid, video_items)

                finish_status = "success" if summary["failed"] == 0 else "warning"
                await operation_log_service.log_background_event(
                    source_type=log_source_type,
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
            except Exception as exc:
                error_message = self._format_scan_error(exc)
                await operation_log_service.log_background_event(
                    source_type=log_source_type,
                    module="archive",
                    action="archive.scan.finish",
                    status="failed",
                    message=f"归档扫描失败：{error_message}",
                    extra={
                        "trigger": trigger,
                        "watch_cid": watch_cid,
                        "output_cid": output_cid,
                        "error": error_message,
                    },
                )
                raise

    # ================================================================
    #  阶段一：扫描源目录文件（参考 QMediaSync 两阶段扫描）
    # ================================================================

    async def _scan_source_files(
        self, pan115: Pan115Service, cid: str
    ) -> list[dict[str, Any]]:
        """递归 BFS 扫描监听目录中的视频和字幕文件"""
        items: list[dict[str, Any]] = []
        pending_dirs: list[tuple[str, str]] = [(str(cid or "0").strip() or "0", "")]
        seen_dirs: set[str] = set()
        limit = 1000

        while pending_dirs:
            current_cid, current_path = pending_dirs.pop(0)
            if current_cid in seen_dirs:
                continue
            seen_dirs.add(current_cid)

            offset = 0
            while True:
                result = await pan115.get_file_list(
                    cid=current_cid, offset=offset, limit=limit
                )
                batch = result.get("data") or []
                if not batch:
                    break

                for it in batch:
                    if not isinstance(it, dict):
                        continue

                    name = str(
                        it.get("n") or it.get("name") or it.get("fn") or ""
                    ).strip()
                    if not name:
                        continue

                    if pan115._is_folder_item(it):
                        folder_cid = str(pan115._extract_folder_id(it) or "").strip()
                        if folder_cid:
                            next_path = (
                                f"{current_path}/{name}" if current_path else name
                            )
                            pending_dirs.append((folder_cid, next_path))
                        continue

                    fid = str(it.get("fid") or "").strip()
                    if not fid:
                        continue

                    is_video = self._is_video(name)
                    is_subtitle = not is_video and self._is_subtitle(name)
                    if not is_video and not is_subtitle:
                        continue

                    relative_path = f"{current_path}/{name}" if current_path else name
                    items.append(
                        {
                            "fid": fid,
                            "name": name,
                            "cid": current_cid,
                            "relative_path": relative_path,
                            "is_video": is_video,
                            "is_subtitle": is_subtitle,
                        }
                    )

                if len(batch) < limit:
                    break
                offset += limit

        items.sort(
            key=lambda x: str(x.get("relative_path") or x.get("name") or "").lower()
        )
        return items

    # ================================================================
    #  阶段二：处理单个视频文件（识别 + 预创建目录 + 移动 + 重命名 + 字幕）
    # ================================================================

    async def _process_one(
        self,
        pan115: Pan115Service,
        item: dict[str, Any],
        output_cid: str,
        trigger: str = "manual",
        folder_cache: dict[tuple[str, ...], str] | None = None,
        subtitle_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        fid = item["fid"]
        filename = item["name"]
        source_cid = item.get("cid", "")

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
                season = int(parsed.get("season") or 1)
                target_desc = f"剧集/{genre_name}/{title_folder}/第{season}季"
            else:
                target_cid = await self._ensure_movie_path(
                    pan115,
                    output_cid,
                    genre_name,
                    title_folder,
                    folder_cache=folder_cache,
                )
                target_desc = f"电影/{genre_name}/{title_folder}"

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

            # --- 参考QMediaSync：移动视频文件 ---
            await pan115.move_file(fid, target_cid)

            # --- 参考QMediaSync：移动后重命名为规范文件名 ---
            new_filename = self._build_target_filename(parsed, matched, filename)
            try:
                await pan115.rename_file(fid, new_filename)
            except Exception:
                logger.warning(
                    "重命名 %s -> %s 失败，保留原文件名", filename, new_filename
                )

            # --- 参考QMediaSync：关联移动字幕文件 ---
            if subtitle_items:
                await self._move_subtitles(
                    pan115, item, subtitle_items, target_cid, parsed, matched
                )

            await self._mark_task_success(db_task.id)
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="archive",
                action="archive.file.success",
                status="success",
                message=f"归档完成：{filename} → {target_desc}",
                extra={"task_id": db_task.id, "target_desc": target_desc},
            )
            return {
                "task_id": db_task.id,
                "status": ArchiveStatus.SUCCESS.value,
                "source_fid": fid,
                "source_filename": filename,
                "target_desc": target_desc,
                "target_cid": target_cid,
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

    # ================================================================
    #  参考QMediaSync：重命名与字幕关联
    # ================================================================

    @staticmethod
    def _build_target_filename(
        parsed: dict[str, Any], matched: dict[str, Any], original_filename: str
    ) -> str:
        title = str(matched.get("title") or parsed.get("query_title") or "")
        year = str(matched.get("year") or parsed.get("year") or "")
        ext = parsed.get("extension", "")

        title = re.sub(r'[\\/:*?"<>|]', "", title).strip()
        if not title:
            return original_filename

        if parsed["media_type"] == "tv":
            season = int(parsed.get("season") or 1)
            return (
                f"{title} ({year}) - S{season:02d}E{parsed.get('episode', 1):02d}{ext}"
                if year
                else f"{title} - S{season:02d}E{parsed.get('episode', 1):02d}{ext}"
            )
        else:
            return f"{title} ({year}){ext}" if year else f"{title}{ext}"

    async def _move_subtitles(
        self,
        pan115: Pan115Service,
        video_item: dict[str, Any],
        subtitle_items: list[dict[str, Any]],
        target_cid: str,
        parsed: dict[str, Any],
        matched: dict[str, Any],
    ) -> None:
        video_base = re.sub(r"\.[^.]+$", "", video_item["name"]).lower()
        video_cid = video_item.get("cid", "")

        for sub in subtitle_items:
            sub_cid = sub.get("cid", "")
            if sub_cid != video_cid:
                continue

            sub_base = re.sub(r"\.[^.]+$", "", sub["name"]).lower()
            if not sub_base.startswith(video_base):
                continue

            try:
                await pan115.move_file(sub["fid"], target_cid)
                new_sub_name = self._build_target_filename(parsed, matched, sub["name"])
                try:
                    await pan115.rename_file(sub["fid"], new_sub_name)
                except Exception:
                    logger.warning("字幕重命名 %s 失败", sub["name"])
            except Exception:
                logger.warning("字幕移动 %s 失败", sub["name"])

    # ================================================================
    #  参考QMediaSync：清理空源目录
    # ================================================================

    async def _cleanup_empty_dirs(
        self,
        pan115: Pan115Service,
        watch_cid: str,
        moved_items: list[dict[str, Any]],
    ) -> None:
        moved_cids: set[str] = set()
        for it in moved_items:
            cid = str(it.get("cid") or "")
            if cid and cid != watch_cid:
                moved_cids.add(cid)

        for cid in moved_cids:
            try:
                result = await pan115.get_file_list(cid=cid, limit=10)
                remaining = result.get("data") or []
                has_content = False
                for it in remaining:
                    if isinstance(it, dict):
                        has_content = True
                        break
                if not has_content:
                    try:
                        await pan115.delete_file(cid)
                    except Exception:
                        logger.debug("清理空目录 %s 失败（可忽略）", cid)
            except Exception:
                logger.debug("检查目录 %s 内容失败（可忽略）", cid)

    # ================================================================
    #  参考QMediaSync：预创建分类目录（带缓存）
    # ================================================================

    async def _ensure_movie_path(
        self,
        pan115: Pan115Service,
        root_cid: str,
        genre: str,
        title_folder: str,
        folder_cache: dict[tuple[str, ...], str] | None = None,
    ) -> str:
        cache_key = ("movie", str(root_cid), str(genre), str(title_folder))
        if folder_cache and cache_key in folder_cache:
            return folder_cache[cache_key]

        movies_cid = await pan115.get_or_create_folder(root_cid, "电影")
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

        tv_cid = await pan115.get_or_create_folder(root_cid, "剧集")
        genre_cid = await pan115.get_or_create_folder(tv_cid, genre)
        title_cid = await pan115.get_or_create_folder(genre_cid, title_folder)
        season_dir = f"第{season}季"
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
        parsed = self.parse_media_filename(filename)
        return await self._process_one(
            pan115,
            {
                "fid": fid,
                "name": filename,
                "cid": "",
                "is_video": True,
                "is_subtitle": False,
            },
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
    def _is_subtitle(filename: str) -> bool:
        idx = filename.rfind(".")
        if idx < 0:
            return False
        return filename[idx:].lower() in SUBTITLE_EXTENSIONS

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
