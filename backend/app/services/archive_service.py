import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select

from app.core.database import async_session_maker
from app.models.archive import ArchiveStatus, ArchiveTask
from app.services.media_postprocess_service import media_postprocess_service
from app.services.operation_log_service import operation_log_service
from app.services.pan115_service import Pan115Service
from app.services.archive_subdir_config import (
    normalize_archive_subdirs,
    resolve_movie_category,
    resolve_tv_category,
)
from app.services.archive_naming_config import (
    normalize_archive_naming,
    render_archive_name,
)
from app.services.runtime_settings_service import runtime_settings_service
from app.services.tmdb_service import tmdb_service

from app.core.timezone_utils import beijing_now

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
    ".m2ts",
    ".mpg",
    ".mpeg",
    ".vob",
    ".iso",
    ".rmvb",
    ".rm",
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

# 分辨率 / 片源 / 编码等技术标记（用于切标题终点与清洗）
_TECH_TOKEN = (
    r"(?:"
    r"2160p|1080p|720p|480p|576p|360p|"
    r"4k(?:[\s._-]?uhd)?|8k|uhd|fhd|"
    r"web[\s._-]?dl|webrip|webdl|"
    r"blu[\s._-]?ray|bluray|bdremux|bdrip|brrip|hddvd|hdtv|hdrip|dvdrip|dvdscr|remux|pdtv|sdtv|hdcam|cam|ts|tc|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|av1|xvid|divx|"
    r"hdr10\+?|hdr|sdr|hlg|dolby[\s._-]?vision|\bdv\b|"
    r"atmos|truehd|dts(?:[\s._-]?hd)?(?:[\s._-]?ma)?|dd[p+]?(?:[\s._-]?[57]\.1)?|ac3|eac3|aac|flac|lpcm|opus|"
    r"10[\s._-]?bit|8[\s._-]?bit|12[\s._-]?bit|"
    r"imax|repack|proper|extended|uncut|remaster(?:ed)?|criterion|"
    r"directors?[\s._-]?cut|theatrical|hybrid|"
    r"nf|amzn|dsnp|atvp|hmax|hulu|itunes|\bit\b|"
    r"ma[\s._-]?10|main10"
    r")"
)

# 中文资源站常见噪音词（粘在片名后）
_ZH_NOISE_TOKEN = (
    r"(?:"
    r"杜比视界|杜比全景声|内封|外挂|特效|字幕|简中|简英|繁中|繁英|"
    r"双语|国语|粤语|中字|英字|中英|精修|高码|原盘|特效字幕|"
    r"中文字幕|英文字幕|简体|繁体"
    r")"
)

# 匹配技术标记：英文词边界，或紧贴在中日韩文字后（如 火遮眼4K）
TECH_CUT_RE = re.compile(
    rf"(?i)(?:(?<=[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af])|(?<![A-Za-z0-9])){_TECH_TOKEN}"
)
ZH_NOISE_CUT_RE = re.compile(
    rf"(?:(?<=[\u3400-\u9fff])|(?<=[^A-Za-z0-9\u3400-\u9fff])|^){_ZH_NOISE_TOKEN}"
)

IGNORE_PATTERNS = (
    rf"(?i)(?<![A-Za-z0-9]){_TECH_TOKEN}(?![A-Za-z0-9])",
    rf"(?i)(?<=[\u3400-\u9fff]){_TECH_TOKEN}",
    rf"{_ZH_NOISE_TOKEN}",
    r"(?i)\b(?:yyets|rarbg|nhd|mteam|mteampt|btbtt|wiki|chd|chdbits|frds|cmct|hds|wds|ade|dream|pter|hhweb|audiences|qun\d+|gnb|ourbits|usas|usa)\b",
    r"(?i)\b(?:mp4|mkv|avi|ts|m2ts|iso)\b",
    r"sup字幕|内封精修|特效sup",
)

EPISODE_PATTERNS = (
    re.compile(r"(?i)\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b"),
    re.compile(r"(?i)\bSeason[\s._-]?(?P<season>\d{1,2})[\s._-]*E(?:p(?:isode)?)?[\s._-]?(?P<episode>\d{1,3})\b"),
    re.compile(r"(?i)\b(?P<season>\d{1,2})x(?P<episode>\d{1,3})\b"),
    re.compile(r"第(?P<season>\d{1,2})季[\s._-]*第(?P<episode>\d{1,3})[集话話]"),
    re.compile(r"第(?P<episode>\d{1,3})[集话話]"),
    re.compile(r"(?i)\bEP(?P<episode>\d{1,3})\b"),
    re.compile(r"(?i)(?<![A-Z0-9])E(?P<episode>\d{2,3})(?![A-Z0-9])"),
)
MOVIE_REGION_MAP = {
    "CN": "华语电影",
    "HK": "华语电影",
    "TW": "华语电影",
    "SG": "华语电影",
    "JP": "日韩电影",
    "KR": "日韩电影",
    "KP": "日韩电影",
}
MOVIE_REGION_DEFAULT = "外语电影"

TV_GENRE_MAP = {
    99: "纪录片",
    16: "动漫",
    10764: "综艺",
    10767: "综艺",
    10763: "综艺",
}
TV_REGION_MAP = {
    "CN": "国产剧",
    "HK": "国产剧",
    "TW": "国产剧",
    "SG": "国产剧",
    "JP": "日韩剧",
    "KR": "日韩剧",
    "KP": "日韩剧",
}
TV_REGION_DEFAULT_FOR_GENRE = {
    "纪录片": "",
    "动漫": "",
    "综艺": "",
}
TV_REGION_DEFAULT = "美英剧"
TV_GENRE_DEFAULT = "其他"


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

    def _get_archive_subdirs(self) -> dict[str, Any]:
        config = self.get_config()
        return normalize_archive_subdirs(config.get("archive_subdirs"))

    def _get_archive_naming(self) -> dict[str, str]:
        config = self.get_config()
        return normalize_archive_naming(config.get("archive_naming"))

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

        self._last_scan_started_at = beijing_now()
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
        self._last_scan_finished_at = beijing_now()
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
                    await self._trigger_strm_after_archive(summary, trigger)
                    return summary

                # 阶段二：并发 TMDB 识别（纯网络请求，不涉及 115 操作）
                identify_tasks = []
                for item in video_items:
                    parsed = self.parse_media_filename(item["name"])
                    identify_tasks.append((item, parsed))

                identified: list[dict[str, Any]] = []
                identify_semaphore = asyncio.Semaphore(5)

                async def _identify_one(
                    _item: dict[str, Any], _parsed: dict[str, Any]
                ) -> dict[str, Any]:
                    async with identify_semaphore:
                        try:
                            matched = await self.identify_media(_parsed)
                            return {
                                "item": _item,
                                "parsed": _parsed,
                                "matched": matched,
                            }
                        except Exception:
                            return {"item": _item, "parsed": _parsed, "matched": None}

                identify_results = await asyncio.gather(
                    *[_identify_one(it, ps) for it, ps in identify_tasks],
                    return_exceptions=False,
                )

                for ir in identify_results:
                    if ir and ir.get("matched"):
                        identified.append(ir)

                if not identified:
                    await operation_log_service.log_background_event(
                        source_type=log_source_type,
                        module="archive",
                        action="archive.scan.finish",
                        status="warning",
                        message=f"所有 {len(video_items)} 个文件均未匹配到 TMDB 结果",
                        extra={"trigger": trigger, "total": len(video_items)},
                    )
                    summary["failed"] = len(video_items)
                    summary["total"] = len(video_items)
                    await self._trigger_strm_after_archive(summary, trigger)
                    return summary

                # 阶段三：串行处理每个文件（涉及 115 移动/重命名，必须走限速队列）
                folder_cache: dict[tuple[str, ...], str] = {}
                processed_cids: set[str] = set()
                identified_video_map: dict[str, dict[str, Any]] = {
                    str(ir["item"].get("fid", "")): ir for ir in identified
                }

                for item in video_items:
                    fid = str(item.get("fid", ""))
                    identify_info = identified_video_map.get(fid)
                    if not identify_info:
                        continue

                    result = await self._process_identified(
                        pan115,
                        item=item,
                        identify_info=identify_info,
                        output_cid=output_cid,
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

                # 阶段三：清理空源目录树
                await self._cleanup_empty_dir_tree(pan115, watch_cid, video_items)

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
                await self._trigger_strm_after_archive(summary, trigger)
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

    async def _trigger_strm_after_archive(
        self, summary: dict[str, Any], trigger: str
    ) -> None:
        await media_postprocess_service.trigger_strm_after_archive(
            summary,
            trigger=f"archive_{str(trigger or 'manual')}",
        )

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
                            "pid": str(it.get("pid") or current_cid).strip(),
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
    #  阶段二：处理已识别的视频文件（移动 + 重命名 + 字幕）
    # ================================================================

    async def _process_identified(
        self,
        pan115: Pan115Service,
        item: dict[str, Any],
        identify_info: dict[str, Any],
        output_cid: str,
        trigger: str = "manual",
        folder_cache: dict[tuple[str, ...], str] | None = None,
        subtitle_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        parsed = identify_info["parsed"]
        matched = identify_info["matched"]
        if not matched:
            return {
                "status": ArchiveStatus.FAILED.value,
                "source_fid": item.get("fid", ""),
                "source_filename": item.get("name", ""),
                "message": "TMDB 未匹配",
            }

        fid = item["fid"]
        filename = item["name"]

        db_task = await self._upsert_task(
            task_id=None, source_fid=fid, source_filename=filename
        )

        try:
            genre_name = str(matched.get("genre_name") or "其他")
            region_name = str(matched.get("region_name") or MOVIE_REGION_DEFAULT)
            title = str(matched.get("title") or parsed["query_title"])
            year = str(matched.get("year") or parsed.get("year") or "")
            naming = self._get_archive_naming()
            title_folder = self._build_title_folder(
                parsed["media_type"],
                title,
                year,
                naming,
                matched=matched,
                parsed=parsed,
                source_filename=filename,
            )

            subdirs = self._get_archive_subdirs()
            if parsed["media_type"] == "tv":
                target_cid = await self._ensure_tv_path(
                    pan115,
                    output_cid,
                    region_name,
                    title_folder,
                    parsed,
                    folder_cache=folder_cache,
                    subdirs=subdirs,
                    naming=naming,
                )
                season = int(parsed.get("season") or 1)
                target_desc = self._build_target_desc(
                    "tv",
                    subdirs,
                    region_name,
                    title_folder,
                    season=season,
                    naming=naming,
                )
            else:
                target_cid = await self._ensure_movie_path(
                    pan115,
                    output_cid,
                    region_name,
                    title_folder,
                    folder_cache=folder_cache,
                    subdirs=subdirs,
                )
                target_desc = self._build_target_desc(
                    "movie", subdirs, region_name, title_folder, naming=naming
                )

            await self._update_task(
                db_task.id,
                media_type=parsed["media_type"],
                tmdb_id=matched.get("tmdb_id"),
                tmdb_title=title,
                tmdb_year=year,
                genre_name=region_name,
                target_path=target_desc,
            )

            await pan115.move_file(fid, target_cid)

            new_filename = self._build_target_filename(parsed, matched, filename, naming)
            try:
                await pan115.rename_file(fid, new_filename)
            except Exception:
                logger.warning(
                    "重命名 %s -> %s 失败，保留原文件名", filename, new_filename
                )

            if subtitle_items:
                await self._move_subtitles(
                    pan115,
                    item,
                    subtitle_items,
                    target_cid,
                    parsed,
                    matched,
                    naming=naming,
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
            logger.warning("归档文件 %s 失败: %s", filename, msg)
            return {
                "task_id": db_task.id,
                "status": ArchiveStatus.FAILED.value,
                "source_fid": fid,
                "source_filename": filename,
                "message": msg,
            }

    # ================================================================
    #  处理单个视频文件（完整流程：识别 + 移动 + 重命名 + 字幕）
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

            genre_name = str(matched.get("genre_name") or "其他")
            region_name = str(matched.get("region_name") or MOVIE_REGION_DEFAULT)
            title = str(matched.get("title") or parsed["query_title"])
            year = str(matched.get("year") or parsed.get("year") or "")
            naming = self._get_archive_naming()
            title_folder = self._build_title_folder(
                parsed["media_type"],
                title,
                year,
                naming,
                matched=matched,
                parsed=parsed,
                source_filename=filename,
            )

            subdirs = self._get_archive_subdirs()
            if parsed["media_type"] == "tv":
                target_cid = await self._ensure_tv_path(
                    pan115,
                    output_cid,
                    region_name,
                    title_folder,
                    parsed,
                    folder_cache=folder_cache,
                    subdirs=subdirs,
                    naming=naming,
                )
                season = int(parsed.get("season") or 1)
                target_desc = self._build_target_desc(
                    "tv",
                    subdirs,
                    region_name,
                    title_folder,
                    season=season,
                    naming=naming,
                )
            else:
                target_cid = await self._ensure_movie_path(
                    pan115,
                    output_cid,
                    region_name,
                    title_folder,
                    folder_cache=folder_cache,
                    subdirs=subdirs,
                )
                target_desc = self._build_target_desc(
                    "movie", subdirs, region_name, title_folder, naming=naming
                )

            await self._update_task(
                db_task.id,
                media_type=parsed["media_type"],
                tmdb_id=matched.get("tmdb_id"),
                tmdb_title=title,
                tmdb_year=year,
                genre_name=region_name,
                target_path=target_desc,
            )
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="archive",
                action="archive.file.matched",
                status="info",
                message=f"TMDB 匹配成功：{title} ({year})，分类={target_desc}",
                extra={"task_id": db_task.id, "matched": matched},
            )

            # --- 参考QMediaSync：移动视频文件 ---
            await pan115.move_file(fid, target_cid)

            # --- 参考QMediaSync：移动后重命名为规范文件名 ---
            new_filename = self._build_target_filename(parsed, matched, filename, naming)
            try:
                await pan115.rename_file(fid, new_filename)
            except Exception:
                logger.warning(
                    "重命名 %s -> %s 失败，保留原文件名", filename, new_filename
                )

            # --- 参考QMediaSync：关联移动字幕文件 ---
            if subtitle_items:
                await self._move_subtitles(
                    pan115,
                    item,
                    subtitle_items,
                    target_cid,
                    parsed,
                    matched,
                    naming=naming,
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
    def _build_title_folder(
        media_type: str,
        title: str,
        year: str,
        naming: dict[str, str] | None = None,
        *,
        matched: dict[str, Any] | None = None,
        parsed: dict[str, Any] | None = None,
        source_filename: str = "",
    ) -> str:
        template_key = "tv_folder" if media_type == "tv" else "movie_folder"
        matched = matched or {}
        parsed = parsed or {}
        return render_archive_name(
            naming,
            template_key,
            title=title,
            year=year,
            tmdb_id=matched.get("tmdb_id"),
            media_type=str(parsed.get("media_type") or media_type),
            category=str(matched.get("region_name") or ""),
            source_filename=source_filename or str(parsed.get("source_filename") or ""),
        )

    def _build_target_filename(
        self,
        parsed: dict[str, Any],
        matched: dict[str, Any],
        original_filename: str,
        naming: dict[str, str] | None = None,
    ) -> str:
        title = str(matched.get("title") or parsed.get("query_title") or "")
        year = str(matched.get("year") or parsed.get("year") or "")
        ext = str(parsed.get("extension") or "")
        if not ext and original_filename:
            dot_index = original_filename.rfind(".")
            if dot_index > 0:
                ext = original_filename[dot_index:]

        if not title.strip():
            return original_filename

        template_key = "tv_file" if parsed.get("media_type") == "tv" else "movie_file"
        rendered = render_archive_name(
            naming,
            template_key,
            title=title,
            year=year,
            season=int(parsed.get("season") or 1),
            episode=int(parsed.get("episode") or 1),
            ext=ext,
            tmdb_id=matched.get("tmdb_id"),
            media_type=str(parsed.get("media_type") or "movie"),
            category=str(matched.get("region_name") or ""),
            source_filename=original_filename,
        )
        return rendered or original_filename

    async def _move_subtitles(
        self,
        pan115: Pan115Service,
        video_item: dict[str, Any],
        subtitle_items: list[dict[str, Any]],
        target_cid: str,
        parsed: dict[str, Any],
        matched: dict[str, Any],
        naming: dict[str, str] | None = None,
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
                sub_ext = sub["name"][sub["name"].rfind(".") :] if "." in sub["name"] else ""
                sub_parsed = dict(parsed)
                if sub_ext:
                    sub_parsed["extension"] = sub_ext
                new_sub_name = self._build_target_filename(
                    sub_parsed, matched, sub["name"], naming
                )
                try:
                    await pan115.rename_file(sub["fid"], new_sub_name)
                except Exception:
                    logger.warning("字幕重命名 %s 失败", sub["name"])
            except Exception:
                logger.warning("字幕移动 %s 失败", sub["name"])

    # ================================================================
    #  清理源目录树（归档后删除残余广告图片等，从叶子往上逐层删除空目录）
    # ================================================================

    async def _cleanup_empty_dir_tree(
        self,
        pan115: Pan115Service,
        watch_cid: str,
        moved_items: list[dict[str, Any]],
    ) -> None:
        moved_cids: set[str] = set()
        cid_to_pid: dict[str, str] = {}
        for it in moved_items:
            cid = str(it.get("cid") or "")
            pid = str(it.get("pid") or "")
            if cid and cid != watch_cid:
                moved_cids.add(cid)
                if pid:
                    cid_to_pid[cid] = pid

        # 补全父级目录链的 pid（确保能回溯到 watch_cid）
        for cid in list(moved_cids):
            current = cid_to_pid.get(cid, "")
            while current and current != watch_cid and current not in cid_to_pid:
                try:
                    result = await pan115.get_file_list(cid=current, limit=1)
                    items = result.get("data") or []
                    if items and isinstance(items[0], dict):
                        pid = str(items[0].get("pid") or "").strip()
                        if pid:
                            cid_to_pid[current] = pid
                            current = pid
                            continue
                except Exception:
                    pass
                break

        if not moved_cids:
            return

        deleted: set[str] = set()

        for cid in moved_cids:
            current = cid
            while current and current != watch_cid and current not in deleted:
                try:
                    result = await pan115.get_file_list(cid=current, limit=100)
                    remaining = result.get("data") or []
                except Exception:
                    logger.debug("检查目录 %s 内容失败（可忽略）", current)
                    break

                # 先删除目录内残留的非视频非字幕文件（广告图片等）
                leftover_fids: list[str] = []
                leftover_folder_cids: list[str] = []
                for it in remaining:
                    if not isinstance(it, dict):
                        continue
                    if pan115._is_folder_item(it):
                        fid = str(
                            pan115._extract_folder_id(it) or it.get("fid") or ""
                        ).strip()
                        if fid:
                            leftover_folder_cids.append(fid)
                    else:
                        fid = str(it.get("fid") or "").strip()
                        if fid:
                            leftover_fids.append(fid)

                if leftover_fids:
                    try:
                        await pan115.delete_file(leftover_fids)
                    except Exception:
                        logger.debug("删除残留文件失败（可忽略）：%s", leftover_fids)

                # 目录内如果还有子目录，说明子目录还没被清理，不能删该层
                still_has_folders = False
                if leftover_folder_cids:
                    for sub_cid in leftover_folder_cids:
                        if sub_cid not in deleted:
                            still_has_folders = True
                            break

                parent = cid_to_pid.get(current)

                if still_has_folders:
                    break

                # 目录为空或只剩已删除的子目录，删除该目录
                try:
                    await pan115.delete_file([current])
                    deleted.add(current)
                except Exception:
                    logger.debug("删除目录 %s 失败（可忽略）", current)
                    break

                current = parent if parent else ""

    # ================================================================
    #  参考QMediaSync：预创建分类目录（带缓存）
    # ================================================================

    @staticmethod
    def _build_target_desc(
        media_type: str,
        subdirs: dict[str, Any],
        category_name: str,
        title_folder: str,
        *,
        season: int | None = None,
        naming: dict[str, str] | None = None,
    ) -> str:
        if media_type == "tv":
            tv_root = str(subdirs.get("tv_root") or "剧集")
            season_num = int(season or 1)
            season_folder = render_archive_name(
                naming,
                "tv_season_folder",
                title="",
                season=season_num,
            )
            if not season_folder:
                season_folder = f"第{season_num}季"
            return f"{tv_root}/{category_name}/{title_folder}/{season_folder}"
        movie_root = str(subdirs.get("movie_root") or "电影")
        return f"{movie_root}/{category_name}/{title_folder}"

    async def _ensure_movie_path(
        self,
        pan115: Pan115Service,
        root_cid: str,
        region: str,
        title_folder: str,
        folder_cache: dict[tuple[str, ...], str] | None = None,
        subdirs: dict[str, Any] | None = None,
    ) -> str:
        subdir_config = normalize_archive_subdirs(subdirs)
        movie_root = str(subdir_config.get("movie_root") or "电影")
        cache_key = ("movie", str(root_cid), movie_root, str(region), str(title_folder))
        if folder_cache and cache_key in folder_cache:
            return folder_cache[cache_key]

        movies_cid = await pan115.get_or_create_folder(root_cid, movie_root)
        region_cid = await pan115.get_or_create_folder(movies_cid, region)
        folder_cid = await pan115.get_or_create_folder(region_cid, title_folder)
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
        subdirs: dict[str, Any] | None = None,
        naming: dict[str, str] | None = None,
    ) -> str:
        subdir_config = normalize_archive_subdirs(subdirs)
        tv_root = str(subdir_config.get("tv_root") or "剧集")
        season = int(parsed.get("season") or 1)
        season_dir = render_archive_name(
            naming,
            "tv_season_folder",
            title="",
            season=season,
        )
        if not season_dir:
            season_dir = f"第{season}季"
        cache_key = (
            "tv",
            str(root_cid),
            tv_root,
            str(genre),
            str(title_folder),
            season_dir,
        )
        if folder_cache and cache_key in folder_cache:
            return folder_cache[cache_key]

        tv_cid = await pan115.get_or_create_folder(root_cid, tv_root)
        genre_cid = await pan115.get_or_create_folder(tv_cid, genre)
        title_cid = await pan115.get_or_create_folder(genre_cid, title_folder)
        season_cid = await pan115.get_or_create_folder(title_cid, season_dir)
        if folder_cache is not None:
            folder_cache[cache_key] = season_cid
        return season_cid

    # ---------- TMDB 识别 ----------

    async def identify_media(self, parsed: dict[str, Any]) -> dict[str, Any] | None:
        media_type = str(parsed.get("media_type") or "movie")
        year_val = parsed.get("year")
        year = int(year_val) if str(year_val or "").isdigit() else None
        queries = self._build_title_query_candidates(parsed)
        if not queries:
            return None

        first: dict[str, Any] | None = None
        used_query = queries[0]
        for query_title in queries:
            items = await self._search_tmdb_items(
                query=query_title, media_type=media_type, year=year
            )
            if items:
                first = items[0] if isinstance(items[0], dict) else None
                used_query = query_title
                break
        if not first:
            return None

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
            or used_query
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
        subdirs = self._get_archive_subdirs()
        region_name = (
            self._extract_movie_region(detail, subdirs=subdirs)
            if media_type == "movie"
            else self._extract_tv_category(detail, subdirs=subdirs)
        )

        return {
            "tmdb_id": tmdb_id,
            "title": title,
            "year": year_text,
            "genre_name": genre_name,
            "region_name": region_name,
        }

    async def _search_tmdb_items(
        self, *, query: str, media_type: str, year: int | None
    ) -> list[Any]:
        result = await tmdb_service.search_by_media_type(
            query=query,
            media_type=media_type,
            page=1,
            year=year,
        )
        items = result.get("results") if isinstance(result.get("results"), list) else []
        if items:
            return items
        if year is None:
            return []
        result = await tmdb_service.search_by_media_type(
            query=query,
            media_type=media_type,
            page=1,
            year=None,
        )
        return result.get("results") if isinstance(result.get("results"), list) else []

    # ---------- 文件名解析 ----------

    @classmethod
    def _prepare_filename_stem(cls, name: str) -> str:
        """规范化粘连文件名，便于提取片名/年份。"""
        text = str(name or "").strip()
        text = (
            text.replace("&", ".")
            .replace("·", ".")
            .replace("—", "-")
            .replace("–", "-")
        )
        # 115 网盘前缀与英文片名粘连：115Zootopia -> Zootopia
        text = re.sub(r"^115(?=[A-Z])", "", text)
        # 误写的粘连年份：.22025 / 22025 -> .2025
        text = re.sub(r"([.\-_]|^)2(20\d{2})(?![0-9])", r"\1\2", text)
        # 小写/数字与大写字母分界：22025Repack -> 22025.Repack
        text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", ".", text)
        # 字母与年份分界：Zootopia2025 -> Zootopia.2025
        text = re.sub(r"(?<=[A-Za-z])(20\d{2})(?![0-9])", r".\1", text)
        return text

    @staticmethod
    def _find_year_match(name: str) -> tuple[re.Match[str] | None, str | None]:
        best: tuple[int, str, re.Match[str]] | None = None
        for pattern in (
            r"(?<![A-Za-z0-9])(19\d{2}|20\d{2})(?![A-Za-z0-9])",
            r"[.\-_](20\d{2})(?![A-Za-z0-9])",
            r"(?<=[A-Za-z])(20\d{2})(?![A-Za-z0-9])",
        ):
            for match in re.finditer(pattern, name):
                year = match.group(1)
                if best is None or match.start() < best[0]:
                    best = (match.start(), year, match)
        if best is None:
            return None, None
        return best[2], best[1]

    def parse_media_filename(self, filename: str) -> dict[str, Any]:
        ext_match = re.search(r"\.[^.]+$", filename)
        ext = ext_match.group(0) if ext_match else ""
        name = filename[: -len(ext)] if ext else filename
        name = self._prepare_filename_stem(name)

        year_match, year = self._find_year_match(name)

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

        tech_match = TECH_CUT_RE.search(name)
        if tech_match and tech_match.start() < title_end:
            title_end = tech_match.start()

        zh_noise_match = ZH_NOISE_CUT_RE.search(name)
        if zh_noise_match and zh_noise_match.start() < title_end:
            # 仅当噪音词出现在片名之后（前面已有有效文字）时才截断
            prefix = name[: zh_noise_match.start()].strip(" ._-")
            if prefix:
                title_end = zh_noise_match.start()

        raw_title = name[:title_end] if title_end > 0 else name
        # 去掉片名前缀广告组 【xxx】 [xxx]
        raw_title = re.sub(r"^[\s\[【（(]+[^\]】）)]*[\]】）)]\s*", "", raw_title)
        query_title = self._normalize_title(raw_title)
        if not query_title:
            query_title = self._normalize_title(name)

        return {
            "source_filename": filename,
            "extension": ext,
            "media_type": media_type,
            "query_title": query_title,
            "year": year,
            "season": season,
            "episode": episode,
            "raw_title": raw_title.strip(" ._-"),
        }

    @classmethod
    def _build_title_query_candidates(cls, parsed: dict[str, Any]) -> list[str]:
        """生成多个 TMDB 查询候选，提高脏文件名命中率。"""
        candidates: list[str] = []

        def _add(value: str | None) -> None:
            text = cls._normalize_title(str(value or ""))
            if len(text) < 2:
                return
            if text not in candidates:
                candidates.append(text)

        _add(parsed.get("query_title"))
        _add(parsed.get("raw_title"))

        source = str(parsed.get("source_filename") or "")
        stem = cls._prepare_filename_stem(re.sub(r"\.[^.]+$", "", source))
        cut = len(stem)
        for pattern in EPISODE_PATTERNS:
            match = pattern.search(stem)
            if match:
                cut = min(cut, match.start())
                break
        year_match, _year = cls._find_year_match(stem)
        if year_match:
            cut = min(cut, year_match.start())
        tech_match = TECH_CUT_RE.search(stem)
        if tech_match:
            cut = min(cut, tech_match.start())
        zh_noise_match = ZH_NOISE_CUT_RE.search(stem)
        if zh_noise_match and stem[: zh_noise_match.start()].strip(" ._-"):
            cut = min(cut, zh_noise_match.start())

        head = stem[:cut]
        _add(head)

        # 连续中日韩文字块（常见：火遮眼4K... -> 火遮眼）
        for match in re.finditer(
            r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]{2,}", head or stem
        ):
            _add(match.group(0))
            break

        # PascalCase 英文片名（115Zootopia... -> Zootopia）
        for match in re.finditer(r"[A-Z][a-z]{2,}", head or stem):
            _add(match.group(0))

        # 英文片名：取技术标记前的单词（至少 2 个字母，避免 K/p 等碎片）
        ascii_words = re.findall(r"[A-Za-z][A-Za-z'']+", head)
        if ascii_words:
            _add(" ".join(ascii_words[:8]))

        # 过长查询逐步缩短
        primary = candidates[0] if candidates else ""
        if len(primary) > 24:
            _add(primary[:24].rstrip())
            parts = primary.split()
            if len(parts) > 1:
                _add(" ".join(parts[:2]))
                _add(parts[0])

        return candidates

    @staticmethod
    def _normalize_title(value: str) -> str:
        text = str(value or "")
        text = re.sub(r"[【\[][^】\]]*[】\]]", " ", text)
        text = re.sub(r"[（(][^）)]*[）)]", " ", text)
        text = text.replace("&", " ")
        for pattern in IGNORE_PATTERNS:
            text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
        text = text.replace(".", " ").replace("_", " ").replace("-", " ")
        text = re.sub(r"[<>:\"/\\|?*]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" ._-")
        return text

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
        result = await self._process_one(
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
        if str(result.get("status") or "") == ArchiveStatus.SUCCESS.value:
            await self._trigger_strm_after_archive(
                {
                    "success": 1,
                    "failed": 0,
                    "skipped": 0,
                    "total": 1,
                    "items": [result],
                },
                "retry",
            )
        return result

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
            completed_at=beijing_now(),
        )

    async def _mark_task_failed(self, task_id: int, error_message: str) -> None:
        await self._update_task(
            task_id,
            status=ArchiveStatus.FAILED,
            error_message=str(error_message or "")[:2000],
            completed_at=beijing_now(),
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
    def _extract_genre_name(detail: dict[str, Any], media_type: str) -> str:
        genres = detail.get("genres") if isinstance(detail.get("genres"), list) else []
        for g in genres:
            if isinstance(g, dict):
                gid = g.get("id")
                if isinstance(gid, int) and gid in TV_GENRE_MAP:
                    return TV_GENRE_MAP[gid]
        for g in genres:
            if isinstance(g, dict):
                n = re.sub(r"[\\/:*?\"<>|]", " ", str(g.get("name") or "")).strip()
                if n:
                    return n
        return TV_GENRE_DEFAULT

    def _extract_movie_region(
        self,
        detail: dict[str, Any],
        *,
        subdirs: dict[str, Any] | None = None,
    ) -> str:
        return resolve_movie_category(detail, subdirs or self._get_archive_subdirs())

    def _extract_tv_category(
        self,
        detail: dict[str, Any],
        *,
        subdirs: dict[str, Any] | None = None,
    ) -> str:
        return resolve_tv_category(detail, subdirs or self._get_archive_subdirs())


archive_service = ArchiveService()
