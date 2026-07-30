import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from app.core.database import async_session_maker
from app.models.archive import ArchiveStatus, ArchiveTask
from app.models.models import DownloadRecord, MediaType, Subscription
from app.services.transfer_intent_service import (
    extract_chinese_title_from_text,
    intent_matches_file,
    pick_preferred_chinese_title,
    transfer_intent_service,
)
from app.services.transfer_file_binding_service import transfer_file_binding_service
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
from app.utils.cloud_filename import (
    is_cloud_duplicate_variant,
    normalize_archive_basename,
    strip_cloud_duplicate_suffix,
)
from app.utils.name_parser import name_parser
from app.utils.media_title_cleanup import clean_archive_display_title

from app.core.timezone_utils import beijing_now

logger = logging.getLogger(__name__)

# 单次归档扫描最长执行时间，避免 115 接口挂起导致后续扫描永久不可用
ARCHIVE_SCAN_TIMEOUT_SECONDS = 30 * 60
# 超过该时长仍处于 processing 的任务视为僵尸任务
ARCHIVE_STALE_TASK_MINUTES = 30
# 页面拉取状态/任务列表时，超过该时长仍无更新的 processing 任务自动标记失败
ARCHIVE_IDLE_PROCESSING_MINUTES = 5
ARCHIVE_CANCEL_WAIT_SECONDS = 3.0
# 识别阶段并发（TMDB 查询，不走 115 限速）
ARCHIVE_IDENTIFY_CONCURRENCY = 8
# 同一目标目录下批量移动的文件数（115 fs_move 支持多 fid）
ARCHIVE_MOVE_BATCH_SIZE = 20

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
    # 允许 S02E01 / S02.E01 / S02_E01（stem 规范化可能插入分隔符）
    re.compile(r"(?i)\bS(?P<season>\d{1,2})[.\s_-]*E(?P<episode>\d{1,3})\b"),
    re.compile(r"(?i)\bSeason[\s._-]?(?P<season>\d{1,2})[\s._-]*E(?:p(?:isode)?)?[\s._-]?(?P<episode>\d{1,3})\b"),
    re.compile(r"(?i)\b(?P<season>\d{1,2})x(?P<episode>\d{1,3})\b"),
    re.compile(r"第(?P<season>\d{1,2})季[\s._-]*第(?P<episode>\d{1,3})[集话話]"),
    re.compile(r"第(?P<episode>\d{1,3})[集话話]"),
    re.compile(r"(?i)\bEP(?P<episode>\d{1,3})\b"),
    re.compile(r"(?i)(?<![A-Z0-9])E(?P<episode>\d{2,3})(?![A-Z0-9])"),
)
# 相对路径/文件夹名中的剧集痕迹（无文件名季集标记时，仍应归档到剧集库）
_PATH_TV_HINT_RE = re.compile(
    r"(?i)(?:"
    r"第\d{1,2}季|"
    r"Season[\s._-]?\d{1,2}|"
    r"\bS\d{1,2}[.\s_-]*E\d{1,3}\b|"
    r"\b\d{1,2}x\d{1,3}\b|"
    r"第\d{1,3}[集话話]"
    r")"
)
_PATH_SEASON_RE = re.compile(r"(?i)(?:第(?P<season>\d{1,2})季|Season[\s._-]?(?P<season_en>\d{1,2}))")
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
        self._pending_rescan = False
        self._pending_rescan_trigger: str = ""
        self._cancel_requested = False

    def _raise_if_scan_cancel_requested(self) -> None:
        if self._cancel_requested:
            raise asyncio.CancelledError("归档扫描已取消")

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

    async def get_runtime_status_async(self) -> dict[str, Any]:
        await self.reconcile_idle_processing_tasks()
        processing_count = await self._count_processing_tasks()
        status = self.get_runtime_status()
        status["processing_count"] = processing_count
        status["scan_active"] = bool(
            status.get("scan_running") or processing_count > 0
        )
        return status

    def is_scan_running(self) -> bool:
        self._cleanup_finished_scan_task()
        if self._background_scan_task and not self._background_scan_task.done():
            return True
        if self._scan_lock.locked():
            return True
        return False

    def _cleanup_finished_scan_task(self) -> None:
        task = self._background_scan_task
        if task and task.done():
            self._background_scan_task = None

    async def reconcile_idle_processing_tasks(self) -> int:
        """将长时间无更新的 processing 任务标记为失败，避免页面长期卡住。"""
        return await self._mark_processing_tasks_failed(
            reason="任务长时间未完成，已自动标记为失败，可点击重试",
            max_age_minutes=ARCHIVE_IDLE_PROCESSING_MINUTES,
        )

    async def _count_processing_tasks(self) -> int:
        async with async_session_maker() as db:
            result = await db.execute(
                select(func.count(ArchiveTask.id)).where(
                    ArchiveTask.status == ArchiveStatus.PROCESSING
                )
            )
            return int(result.scalar() or 0)

    async def recover_stale_state(self) -> dict[str, Any]:
        """服务启动或人工恢复时，清理僵尸扫描状态与 processing 任务。"""
        self._cleanup_finished_scan_task()
        recovered_tasks = await self._mark_processing_tasks_failed(
            reason="服务重启或扫描中断，任务已自动标记为失败",
            max_age_minutes=None,
        )
        if recovered_tasks:
            logger.warning("归档启动恢复：已将 %d 条 processing 任务标记为失败", recovered_tasks)
        return {"recovered_tasks": recovered_tasks}

    async def _mark_processing_tasks_failed(
        self,
        *,
        reason: str,
        max_age_minutes: int | None = None,
    ) -> int:
        cutoff = (
            beijing_now() - timedelta(minutes=max(1, int(max_age_minutes)))
            if max_age_minutes is not None
            else None
        )
        async with async_session_maker() as db:
            query = select(ArchiveTask).where(ArchiveTask.status == ArchiveStatus.PROCESSING)
            if cutoff is not None:
                query = query.where(ArchiveTask.updated_at < cutoff)
            result = await db.execute(query)
            tasks = result.scalars().all()
            if not tasks:
                return 0
            now = beijing_now()
            for task in tasks:
                task.status = ArchiveStatus.FAILED
                task.error_message = str(reason or "任务已中断")[:2000]
                task.completed_at = now
            await db.commit()
            return len(tasks)

    async def cancel_scan(self) -> dict[str, Any]:
        self._cancel_requested = True
        self._cleanup_finished_scan_task()
        task = self._background_scan_task
        had_active_task = bool(task and not task.done())

        if had_active_task:
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=ARCHIVE_CANCEL_WAIT_SECONDS)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                logger.warning("归档扫描取消等待超时，已强制结束扫描状态")
            except Exception:
                logger.exception("等待归档扫描取消时出错")

        self._cleanup_finished_scan_task()
        recovered_tasks = await self._mark_processing_tasks_failed(
            reason="归档扫描已取消",
            max_age_minutes=None,
        )
        self._last_scan_finished_at = beijing_now()
        if had_active_task or recovered_tasks:
            self._last_scan_error = "归档扫描已取消"
        self._cancel_requested = False

        return {
            "cancelled": had_active_task or recovered_tasks > 0,
            "running": self.is_scan_running(),
            "recovered_tasks": recovered_tasks,
            "message": "归档扫描已取消"
            + (f"，已清理 {recovered_tasks} 条卡住的任务" if recovered_tasks else ""),
            "runtime": await self.get_runtime_status_async(),
        }

    async def start_scan(
        self,
        trigger: str = "manual",
        *,
        respect_save_queue: bool = True,
    ) -> dict[str, Any]:
        if respect_save_queue and str(trigger or "").strip().lower() != "manual":
            from app.services.explore_action_queue_service import (
                explore_action_queue_service,
            )

            deferred = await explore_action_queue_service.defer_until_save_queue_idle(
                f"archive_scan:{trigger}",
                lambda: self.start_scan(
                    trigger=trigger,
                    respect_save_queue=False,
                ),
            )
            if deferred:
                return {
                    "started": False,
                    "running": False,
                    "queued": True,
                    "deferred": True,
                    "message": "转存队列执行中，归档扫描已延迟至队列空闲",
                    "runtime": self.get_runtime_status(),
                }

        self._cleanup_finished_scan_task()
        if self.is_scan_running() or self._scan_lock.locked():
            self._pending_rescan = True
            self._pending_rescan_trigger = str(trigger or "manual")
            return {
                "started": False,
                "running": True,
                "queued": True,
                "message": "归档扫描已在执行中，将在当前扫描完成后自动再次执行",
                "runtime": self.get_runtime_status(),
            }

        await self._mark_processing_tasks_failed(
            reason="上次归档任务未正常结束，已自动标记为失败",
            max_age_minutes=ARCHIVE_STALE_TASK_MINUTES,
        )

        self._last_scan_started_at = beijing_now()
        self._last_scan_finished_at = None
        self._last_scan_trigger = trigger
        self._last_scan_summary = None
        self._last_scan_error = ""

        self._cancel_requested = False
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
        self._background_scan_task = None
        try:
            self._last_scan_summary = task.result()
            self._last_scan_error = ""
        except asyncio.CancelledError:
            self._last_scan_summary = None
            if not self._last_scan_error:
                self._last_scan_error = "归档扫描已取消"
        except Exception as exc:
            self._last_scan_summary = None
            self._last_scan_error = self._format_scan_error(exc)
            logger.exception("Archive background scan failed")

        pending_trigger = ""
        if self._pending_rescan:
            self._pending_rescan = False
            pending_trigger = str(self._pending_rescan_trigger or "deferred").strip()
            self._pending_rescan_trigger = ""
        if pending_trigger:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self.start_scan(trigger=pending_trigger),
                    name=f"archive-scan-{pending_trigger}",
                )
            except RuntimeError:
                logger.warning("归档补扫调度失败：事件循环不可用")

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

        if isinstance(exc, asyncio.TimeoutError):
            return (
                f"归档扫描超时（超过 {ARCHIVE_SCAN_TIMEOUT_SECONDS // 60} 分钟），"
                "已自动终止。请稍后重试。"
            )

        if not error_text:
            return "归档扫描失败：未知错误"

        return f"归档扫描失败：{error_text[:500]}"

    # ================================================================
    #  主扫描流程（参考 QMediaSync）
    # ================================================================

    async def run_scan(self, trigger: str = "manual") -> dict[str, Any]:
        async with self._scan_lock:
            try:
                return await asyncio.wait_for(
                    self._run_scan_locked(trigger=trigger),
                    timeout=ARCHIVE_SCAN_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError as exc:
                await self._mark_processing_tasks_failed(
                    reason="归档扫描超时，任务已自动标记为失败",
                    max_age_minutes=ARCHIVE_STALE_TASK_MINUTES,
                )
                raise TimeoutError(self._format_scan_error(exc)) from exc

    async def _run_scan_locked(self, trigger: str = "manual") -> dict[str, Any]:
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

                # 阶段二：优先 file_fid↔TMDB 绑定，再回退文件名搜 TMDB
                identify_tasks = []
                for item in video_items:
                    parsed = self.parse_media_filename(item["name"])
                    identify_tasks.append((item, parsed))

                binding_map = await transfer_file_binding_service.get_by_file_fids(
                    [str(it.get("fid") or "") for it, _ in identify_tasks]
                )

                identified: list[dict[str, Any]] = []
                identify_semaphore = asyncio.Semaphore(ARCHIVE_IDENTIFY_CONCURRENCY)
                tmdb_id_cache: dict[tuple[str, int], dict[str, Any] | None] = {}
                tmdb_search_cache: dict[
                    tuple[str, str, int | None], list[Any]
                ] = {}

                async def _identify_one(
                    _item: dict[str, Any], _parsed: dict[str, Any]
                ) -> dict[str, Any]:
                    async with identify_semaphore:
                        fid = str(_item.get("fid") or "")
                        binding = binding_map.get(fid)
                        parsed = dict(_parsed or {})
                        try:
                            matched = None
                            if binding and binding.get("tmdb_id"):
                                media_type = str(
                                    binding.get("media_type")
                                    or parsed.get("media_type")
                                    or "movie"
                                )
                                parsed["media_type"] = (
                                    "tv" if media_type == "tv" else "movie"
                                )
                                if binding.get("season") is not None:
                                    # 文件名已明确解析出季号时，以文件名为准，避免错误 binding 覆盖
                                    if parsed.get("season") is None:
                                        parsed["season"] = int(binding["season"])
                                if binding.get("episode") is not None:
                                    if parsed.get("episode") is None:
                                        parsed["episode"] = int(binding["episode"])
                                matched = await self._identify_by_tmdb_id(
                                    int(binding["tmdb_id"]),
                                    parsed["media_type"],
                                    cache=tmdb_id_cache,
                                )
                            if not matched:
                                matched = await self.identify_media(
                                    parsed,
                                    id_cache=tmdb_id_cache,
                                    search_cache=tmdb_search_cache,
                                )
                            return {
                                "item": _item,
                                "parsed": parsed,
                                "matched": matched,
                                "binding": binding or {},
                            }
                        except Exception:
                            return {
                                "item": _item,
                                "parsed": parsed,
                                "matched": None,
                                "binding": binding or {},
                            }

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

                # 阶段 2.5：电视剧按集去重（单集优先于合集，同集保留最高画质）
                tv_skip_map = self._dedupe_tv_identified_items(identified)
                season_episode_cache: dict[str, set[tuple[int, int]]] = {}
                folder_snapshot_cache: dict[str, dict[str, Any]] = {}
                tv_cleanup_done: set[str] = set()

                # 阶段三：准备目标目录 → 按目录批量移动 → 逐个重命名/字幕
                folder_cache: dict[tuple[str, ...], str] = {}
                processed_cids: set[str] = set()
                identified_video_map: dict[str, dict[str, Any]] = {
                    str(ir["item"].get("fid", "")): ir for ir in identified
                }

                prepared_plans: list[dict[str, Any]] = []
                for item in video_items:
                    self._raise_if_scan_cancel_requested()
                    fid = str(item.get("fid", ""))
                    identify_info = identified_video_map.get(fid)
                    if not identify_info:
                        continue

                    skip_reason = tv_skip_map.get(fid)
                    if skip_reason:
                        result = self._build_archive_skip_result(item, skip_reason)
                        summary["items"].append(result)
                        summary["skipped"] += 1
                        continue

                    plan = await self._prepare_identified(
                        pan115,
                        item=item,
                        identify_info=identify_info,
                        output_cid=output_cid,
                        folder_cache=folder_cache,
                        season_episode_cache=season_episode_cache,
                        folder_snapshot_cache=folder_snapshot_cache,
                        id_cache=tmdb_id_cache,
                        tv_cleanup_done=tv_cleanup_done,
                    )
                    prepared_plans.append(plan)

                # 按目标目录批量移动（同一目录一次 API 可带多个 fid）
                ready_plans = [p for p in prepared_plans if p.get("ready")]
                plans_by_target: dict[str, list[dict[str, Any]]] = {}
                for plan in ready_plans:
                    target_cid = str(plan.get("target_cid") or "").strip()
                    if not target_cid:
                        plan["ready"] = False
                        plan["result"] = {
                            "task_id": plan.get("task_id"),
                            "status": ArchiveStatus.FAILED.value,
                            "source_fid": plan.get("fid", ""),
                            "source_filename": plan.get("filename", ""),
                            "message": "目标目录无效",
                        }
                        continue
                    plans_by_target.setdefault(target_cid, []).append(plan)

                for target_cid, group in plans_by_target.items():
                    self._raise_if_scan_cancel_requested()
                    for start in range(0, len(group), ARCHIVE_MOVE_BATCH_SIZE):
                        chunk = group[start : start + ARCHIVE_MOVE_BATCH_SIZE]
                        fids = [str(p["fid"]) for p in chunk]
                        try:
                            await pan115.move_file(fids, target_cid)
                            for plan in chunk:
                                plan["moved"] = True
                        except Exception as batch_exc:
                            logger.warning(
                                "批量移动失败（%s 个文件 → %s），回退逐个移动: %s",
                                len(fids),
                                target_cid,
                                batch_exc,
                            )
                            for plan in chunk:
                                self._raise_if_scan_cancel_requested()
                                try:
                                    await pan115.move_file(str(plan["fid"]), target_cid)
                                    plan["moved"] = True
                                except Exception as one_exc:
                                    msg = str(one_exc) or "移动失败"
                                    task_id = plan.get("task_id")
                                    if task_id:
                                        await self._mark_task_failed(task_id, msg)
                                    plan["ready"] = False
                                    plan["result"] = {
                                        "task_id": task_id,
                                        "status": ArchiveStatus.FAILED.value,
                                        "source_fid": plan.get("fid", ""),
                                        "source_filename": plan.get("filename", ""),
                                        "message": msg,
                                    }

                for plan in prepared_plans:
                    self._raise_if_scan_cancel_requested()
                    if plan.get("result"):
                        result = plan["result"]
                    elif plan.get("ready") and plan.get("moved"):
                        result = await self._finalize_identified(
                            pan115,
                            plan=plan,
                            subtitle_items=subtitle_items,
                            season_episode_cache=season_episode_cache,
                            folder_snapshot_cache=folder_snapshot_cache,
                        )
                    elif plan.get("ready") and not plan.get("moved"):
                        result = {
                            "task_id": plan.get("task_id"),
                            "status": ArchiveStatus.FAILED.value,
                            "source_fid": plan.get("fid", ""),
                            "source_filename": plan.get("filename", ""),
                            "message": "文件移动未完成",
                        }
                    else:
                        continue

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
            except asyncio.CancelledError:
                await self._mark_processing_tasks_failed(
                    reason="归档扫描已取消",
                    max_age_minutes=None,
                )
                raise
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
    #  电视剧集数去重
    # ================================================================

    @staticmethod
    def _extract_tv_coverage(
        parsed: dict[str, Any], filename: str
    ) -> dict[str, int] | None:
        coverage = name_parser.parse_episode_coverage(
            strip_cloud_duplicate_suffix(str(filename or ""))
        )
        if coverage:
            return coverage
        if str(parsed.get("media_type") or "") != "tv":
            return None
        season = parsed.get("season")
        episode = parsed.get("episode")
        if season is None or episode is None:
            return None
        return {
            "season": int(season),
            "episode_start": int(episode),
            "episode_end": int(episode),
        }

    def _dedupe_tv_identified_items(
        self, identified: list[dict[str, Any]]
    ) -> dict[str, str]:
        """同一部剧同一集只保留一个候选：单集优先，其次范围更小，再比画质。"""
        from app.utils.tv_episode_dedup import build_tv_file_entry, dedupe_tv_file_entries

        tv_entries: list[dict[str, Any]] = []
        for identify_info in identified:
            parsed = identify_info.get("parsed") or {}
            matched = identify_info.get("matched") or {}
            if str(parsed.get("media_type") or "") != "tv":
                continue
            tmdb_id = int(matched.get("tmdb_id") or 0)
            if tmdb_id <= 0:
                continue
            item = identify_info.get("item") or {}
            entry = build_tv_file_entry(item, group_id=tmdb_id)
            if not entry:
                coverage = self._extract_tv_coverage(parsed, str(item.get("name") or ""))
                if not coverage:
                    continue
                fid = str(item.get("fid") or "").strip()
                if not fid:
                    continue
                span = int(coverage["episode_end"]) - int(coverage["episode_start"]) + 1
                entry = {
                    "fid": fid,
                    "item": item,
                    "coverage": coverage,
                    "span": span,
                    "is_single": span == 1,
                    "group_id": tmdb_id,
                }
            tv_entries.append(entry)

        skip_map: dict[str, str] = {}
        grouped: dict[int, list[dict[str, Any]]] = {}
        for entry in tv_entries:
            grouped.setdefault(int(entry.get("group_id") or 0), []).append(entry)
        for entries in grouped.values():
            _, group_skip = dedupe_tv_file_entries(entries)
            skip_map.update(group_skip)
        return skip_map

    @staticmethod
    def _build_archive_skip_result(item: dict[str, Any], message: str) -> dict[str, Any]:
        return {
            "status": ArchiveStatus.SKIPPED.value,
            "source_fid": item.get("fid", ""),
            "source_filename": item.get("name", ""),
            "message": message,
        }

    async def _get_target_folder_snapshot(
        self,
        pan115: Pan115Service,
        folder_cid: str,
        cache: dict[str, dict[str, Any]] | None = None,
        *,
        require_list: bool = False,
    ) -> dict[str, Any]:
        """列出目标目录已有文件：集数索引 + 规范化文件名（用于去重）。

        require_list=True 时，列举失败会抛出异常，避免误当成空目录而重复归档。
        """
        cid = str(folder_cid or "").strip()
        empty: dict[str, Any] = {
            "episodes": set(),
            "basenames": set(),
            "files": [],
        }
        if not cid:
            return empty
        if cache is not None and cid in cache:
            return cache[cid]

        episodes: set[tuple[int, int]] = set()
        basenames: set[str] = set()
        files: list[dict[str, str]] = []
        offset = 0
        limit = 200
        listed = False
        list_error: Exception | None = None
        while True:
            try:
                result = await pan115.get_file_list(cid=cid, limit=limit, offset=offset)
                listed = True
            except Exception as exc:
                list_error = exc
                break
            rows = result.get("data") or []
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                if not isinstance(row, dict) or pan115._is_folder_item(row):
                    continue
                name = str(row.get("name") or row.get("fn") or "")
                fid = str(row.get("fid") or row.get("cid") or "").strip()
                clean_name = strip_cloud_duplicate_suffix(name)
                coverage = name_parser.parse_episode_coverage(clean_name)
                if coverage:
                    episodes.update(name_parser.iter_episode_keys(coverage))
                normalized = normalize_archive_basename(name)
                if normalized:
                    basenames.add(normalized)
                raw_size = row.get("size")
                if raw_size in (None, ""):
                    raw_size = row.get("s")
                if raw_size in (None, ""):
                    raw_size = row.get("fs")
                try:
                    size = int(raw_size or 0)
                except (TypeError, ValueError):
                    size = 0
                files.append(
                    {
                        "fid": fid,
                        "name": name,
                        "normalized": normalized,
                        "size": size,
                    }
                )
            if len(rows) < limit:
                break
            offset += limit

        if list_error is not None and (require_list or not listed):
            raise RuntimeError(
                f"无法列举目标目录 {cid} 以检查重复，已中止归档以避免重复入库：{list_error}"
            ) from list_error

        snapshot = {
            "episodes": episodes,
            "basenames": basenames,
            "files": files,
        }
        if cache is not None:
            cache[cid] = snapshot
        return snapshot

    async def _get_season_archived_episodes(
        self,
        pan115: Pan115Service,
        season_cid: str,
        cache: dict[str, set[tuple[int, int]]] | None = None,
    ) -> set[tuple[int, int]]:
        """兼容旧调用：仅返回目标季目录内已解析到的集数。"""
        folder_cache: dict[str, dict[str, Any]] | None = None
        if cache is not None:
            folder_cache = {}
        snapshot = await self._get_target_folder_snapshot(
            pan115, season_cid, folder_cache
        )
        if cache is not None and folder_cache is not None:
            cache[season_cid] = set(snapshot["episodes"])
        return set(snapshot["episodes"])

    @staticmethod
    def _snapshot_has_filename_conflict(
        snapshot: dict[str, Any],
        *,
        source_filename: str,
        target_filename: str,
        exclude_fid: str = "",
    ) -> str | None:
        """检查目标目录是否已有同名/同集文件（含网盘 (1)(2) 变体）。"""
        exclude = str(exclude_fid or "").strip()
        normalized_targets = {
            value
            for value in (
                normalize_archive_basename(source_filename),
                normalize_archive_basename(target_filename),
            )
            if value
        }
        if not normalized_targets:
            return None

        for row in snapshot.get("files") or []:
            fid = str(row.get("fid") or "").strip()
            if exclude and fid == exclude:
                continue
            normalized = str(row.get("normalized") or "")
            if normalized in normalized_targets:
                existing_name = str(row.get("name") or target_filename)
                return f"目标目录已存在 {existing_name}，已跳过"
            for candidate in normalized_targets:
                if is_cloud_duplicate_variant(str(row.get("name") or ""), candidate):
                    existing_name = str(row.get("name") or target_filename)
                    return f"目标目录已存在 {existing_name}，已跳过"
        return None

    async def _check_tv_episode_archive_conflict(
        self,
        pan115: Pan115Service,
        parsed: dict[str, Any],
        filename: str,
        target_cid: str,
        season_episode_cache: dict[str, set[tuple[int, int]]] | None,
        *,
        new_filename: str = "",
        exclude_fid: str = "",
        folder_snapshot_cache: dict[str, dict[str, Any]] | None = None,
    ) -> str | None:
        if str(parsed.get("media_type") or "") != "tv":
            return None
        coverage = self._extract_tv_coverage(parsed, filename)
        snapshot = await self._get_target_folder_snapshot(
            pan115, target_cid, folder_snapshot_cache, require_list=True
        )

        filename_conflict = self._snapshot_has_filename_conflict(
            snapshot,
            source_filename=filename,
            target_filename=new_filename or filename,
            exclude_fid=exclude_fid,
        )
        if filename_conflict:
            return filename_conflict

        if not coverage:
            return None

        exclude = str(exclude_fid or "").strip()
        existing: set[tuple[int, int]] = set()
        for row in snapshot.get("files") or []:
            if exclude and str(row.get("fid") or "").strip() == exclude:
                continue
            row_name = str(row.get("name") or "")
            row_coverage = name_parser.parse_episode_coverage(
                strip_cloud_duplicate_suffix(row_name)
            )
            if row_coverage:
                existing.update(name_parser.iter_episode_keys(row_coverage))
        if season_episode_cache is not None:
            cached = set(season_episode_cache.get(str(target_cid or "")) or set())
            existing |= cached
            # 合并磁盘快照与本批已记住的集，禁止整表覆盖丢掉缓存
            season_episode_cache[str(target_cid or "")] = existing | set(
                snapshot.get("episodes") or set()
            )

        overlap = [
            (season, episode)
            for season, episode in name_parser.iter_episode_keys(coverage)
            if (season, episode) in existing
        ]
        if not overlap:
            return None
        if len(overlap) == 1:
            season, episode = overlap[0]
            return f"目标目录已存在 S{season:02d}E{episode:02d}，已跳过"
        labels = ", ".join(f"S{s:02d}E{e:02d}" for s, e in overlap[:5])
        suffix = " 等" if len(overlap) > 5 else ""
        return f"目标目录已存在 {labels}{suffix}，已跳过"

    async def _check_movie_archive_conflict(
        self,
        pan115: Pan115Service,
        filename: str,
        target_cid: str,
        *,
        new_filename: str = "",
        folder_snapshot_cache: dict[str, dict[str, Any]] | None = None,
        exclude_fid: str = "",
    ) -> str | None:
        snapshot = await self._get_target_folder_snapshot(
            pan115, target_cid, folder_snapshot_cache, require_list=True
        )
        return self._snapshot_has_filename_conflict(
            snapshot,
            source_filename=filename,
            target_filename=new_filename or filename,
            exclude_fid=exclude_fid,
        )

    @staticmethod
    def _remember_archived_tv_episodes(
        parsed: dict[str, Any],
        filename: str,
        target_cid: str,
        season_episode_cache: dict[str, set[tuple[int, int]]],
    ) -> None:
        coverage = ArchiveService._extract_tv_coverage(parsed, filename)
        if not coverage:
            return
        cached = season_episode_cache.setdefault(str(target_cid or ""), set())
        cached.update(name_parser.iter_episode_keys(coverage))

    async def _cleanup_duplicate_tv_episodes_in_folder(
        self,
        pan115: Pan115Service,
        folder_cid: str,
        *,
        folder_snapshot_cache: dict[str, dict[str, Any]] | None = None,
        cleaned_cids: set[str] | None = None,
    ) -> int:
        """季目录内同 (S,E) 多份时保留画质最高的一份，删除其余。"""
        cid = str(folder_cid or "").strip()
        if not cid:
            return 0
        if cleaned_cids is not None and cid in cleaned_cids:
            return 0

        snapshot = await self._get_target_folder_snapshot(
            pan115, cid, folder_snapshot_cache, require_list=True
        )
        if cleaned_cids is not None:
            cleaned_cids.add(cid)

        groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for row in snapshot.get("files") or []:
            if not isinstance(row, dict):
                continue
            fid = str(row.get("fid") or "").strip()
            name = str(row.get("name") or "")
            if not fid or not name:
                continue
            coverage = name_parser.parse_episode_coverage(
                strip_cloud_duplicate_suffix(name)
            )
            if not coverage:
                continue
            keys = list(name_parser.iter_episode_keys(coverage))
            # 仅清理「单集文件」之间的同集多份；合集包不参与，避免误删
            if len(keys) != 1:
                continue
            groups.setdefault(keys[0], []).append(row)

        delete_fids: list[str] = []
        for key, rows in groups.items():
            # 同一文件可能覆盖多集，按 fid 去重后再比画质
            by_fid: dict[str, dict[str, Any]] = {}
            for row in rows:
                fid = str(row.get("fid") or "").strip()
                if fid and fid not in by_fid:
                    by_fid[fid] = row
            unique_rows = list(by_fid.values())
            if len(unique_rows) <= 1:
                continue
            best = max(
                unique_rows,
                key=lambda r: Pan115Service._score_video_file(
                    {
                        "name": str(r.get("name") or ""),
                        "size": int(r.get("size") or 0),
                    }
                ),
            )
            best_fid = str(best.get("fid") or "").strip()
            for row in unique_rows:
                fid = str(row.get("fid") or "").strip()
                if fid and fid != best_fid:
                    delete_fids.append(fid)

        # 去重删除列表（合集文件可能出现在多组）
        delete_fids = list(dict.fromkeys(delete_fids))
        if not delete_fids:
            return 0

        try:
            await pan115.delete_file(delete_fids)
        except Exception as exc:
            logger.warning(
                "清理季目录同集重复失败 cid=%s count=%s: %s",
                cid,
                len(delete_fids),
                exc,
            )
            return 0

        if folder_snapshot_cache is not None and cid in folder_snapshot_cache:
            del folder_snapshot_cache[cid]
        logger.info(
            "清理季目录同集重复：cid=%s deleted=%s",
            cid,
            len(delete_fids),
        )
        return len(delete_fids)

    # ================================================================
    #  阶段二：处理已识别的视频文件（准备目录 + 移动 + 重命名 + 字幕）
    # ================================================================

    async def _prepare_identified(
        self,
        pan115: Pan115Service,
        item: dict[str, Any],
        identify_info: dict[str, Any],
        output_cid: str,
        folder_cache: dict[tuple[str, ...], str] | None = None,
        season_episode_cache: dict[str, set[tuple[int, int]]] | None = None,
        folder_snapshot_cache: dict[str, dict[str, Any]] | None = None,
        id_cache: dict[tuple[str, int], dict[str, Any] | None] | None = None,
        tv_cleanup_done: set[str] | None = None,
    ) -> dict[str, Any]:
        """准备归档计划：识别校正、建目录、冲突检查；不执行移动。"""
        parsed = dict(identify_info.get("parsed") or {})
        matched = identify_info["matched"]
        binding = identify_info.get("binding") or {}
        if not matched:
            return {
                "ready": False,
                "result": {
                    "status": ArchiveStatus.FAILED.value,
                    "source_fid": item.get("fid", ""),
                    "source_filename": item.get("name", ""),
                    "message": "TMDB 未匹配",
                },
            }

        fid = item["fid"]
        filename = item["name"]

        if binding.get("tmdb_id"):
            if binding.get("media_type"):
                parsed["media_type"] = (
                    "tv" if str(binding.get("media_type")) == "tv" else "movie"
                )
            if binding.get("season") is not None:
                if parsed.get("season") is None:
                    parsed["season"] = int(binding["season"])
            if binding.get("episode") is not None:
                if parsed.get("episode") is None:
                    parsed["episode"] = int(binding["episode"])
            if int(matched.get("tmdb_id") or 0) != int(binding["tmdb_id"]):
                binding_matched = await self._identify_by_tmdb_id(
                    int(binding["tmdb_id"]),
                    str(parsed.get("media_type") or "movie"),
                    cache=id_cache,
                )
                if binding_matched:
                    matched = binding_matched

        transfer_context = await self._lookup_transfer_context(
            str(item.get("cid") or ""),
            fid,
            str(item.get("relative_path") or ""),
            tmdb_id=int(matched.get("tmdb_id") or 0) or None,
            media_type=str(parsed.get("media_type") or "movie"),
            filename=filename,
        )
        if binding.get("display_title"):
            transfer_context["binding_display_title"] = str(
                binding.get("display_title") or ""
            ).strip()
        intent = transfer_context.get("intent") or {}
        if intent and not intent_matches_file(
            intent,
            filename=filename,
            folder_name=str(transfer_context.get("folder_name") or ""),
            tmdb_id=int(matched.get("tmdb_id") or 0) or None,
        ):
            # 文件名已判成 movie 时，tmdb_id 可能是错的电影 ID；仍保留按目录命中的剧集意图
            if str(intent.get("media_type") or "").lower() != "tv":
                transfer_context["intent"] = {}
                intent = {}

        original_type = str(parsed.get("media_type") or "movie")
        parsed = self._apply_tv_media_type_hints(
            parsed,
            binding=binding,
            intent=intent,
            relative_path=str(item.get("relative_path") or ""),
            folder_name=str(transfer_context.get("folder_name") or ""),
        )

        if intent.get("tmdb_id") and not binding.get("tmdb_id"):
            intent_matched = await self._identify_by_tmdb_id(
                int(intent["tmdb_id"]),
                str(intent.get("media_type") or parsed.get("media_type") or "movie"),
                cache=id_cache,
            )
            if intent_matched:
                matched = intent_matched
        elif (
            original_type != "tv"
            and str(parsed.get("media_type") or "") == "tv"
            and int(matched.get("tmdb_id") or 0) > 0
        ):
            # 文件名误判为电影后，按剧集重新拉详情，避免 region 落成外语电影
            rematch_id = int(
                (intent.get("tmdb_id") if intent else 0)
                or (binding.get("tmdb_id") if binding else 0)
                or matched.get("tmdb_id")
                or 0
            )
            if rematch_id > 0:
                rematched = await self._identify_by_tmdb_id(
                    rematch_id, "tv", cache=id_cache
                )
                if rematched:
                    matched = rematched
                else:
                    rematched = await self.identify_media(
                        parsed, id_cache=id_cache
                    )
                    if rematched:
                        matched = rematched
            else:
                rematched = await self.identify_media(parsed, id_cache=id_cache)
                if rematched:
                    matched = rematched

        db_task = await self._upsert_task(
            task_id=None, source_fid=fid, source_filename=filename
        )

        try:
            region_name = str(matched.get("region_name") or MOVIE_REGION_DEFAULT)
            display_title = self._resolve_archive_display_title(
                parsed,
                matched,
                transfer_context={**transfer_context, "filename": filename},
            )
            title = display_title
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
                display_title=display_title,
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
                await self._cleanup_duplicate_tv_episodes_in_folder(
                    pan115,
                    target_cid,
                    folder_snapshot_cache=folder_snapshot_cache,
                    cleaned_cids=tv_cleanup_done,
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

            new_filename = self._build_target_filename(
                parsed,
                matched,
                filename,
                naming,
                display_title=display_title,
            )

            if parsed["media_type"] == "tv":
                conflict = await self._check_tv_episode_archive_conflict(
                    pan115,
                    parsed,
                    filename,
                    target_cid,
                    season_episode_cache,
                    new_filename=new_filename,
                    exclude_fid=fid,
                    folder_snapshot_cache=folder_snapshot_cache,
                )
                if conflict:
                    await self._mark_task_skipped(db_task.id, conflict)
                    return {
                        "ready": False,
                        "result": self._build_archive_skip_result(item, conflict),
                    }
                if season_episode_cache is not None:
                    self._remember_archived_tv_episodes(
                        parsed,
                        filename,
                        target_cid,
                        season_episode_cache,
                    )
                if folder_snapshot_cache is not None:
                    snapshot = await self._get_target_folder_snapshot(
                        pan115, target_cid, folder_snapshot_cache
                    )
                    normalized_new = normalize_archive_basename(new_filename)
                    if normalized_new:
                        snapshot["basenames"].add(normalized_new)
                    coverage = self._extract_tv_coverage(parsed, filename)
                    if coverage:
                        snapshot["episodes"].update(
                            name_parser.iter_episode_keys(coverage)
                        )
            else:
                conflict = await self._check_movie_archive_conflict(
                    pan115,
                    filename,
                    target_cid,
                    new_filename=new_filename,
                    folder_snapshot_cache=folder_snapshot_cache,
                    exclude_fid=fid,
                )
                if conflict:
                    await self._mark_task_skipped(db_task.id, conflict)
                    return {
                        "ready": False,
                        "result": self._build_archive_skip_result(item, conflict),
                    }
                if folder_snapshot_cache is not None:
                    snapshot = await self._get_target_folder_snapshot(
                        pan115, target_cid, folder_snapshot_cache
                    )
                    normalized_new = normalize_archive_basename(new_filename)
                    if normalized_new:
                        snapshot["basenames"].add(normalized_new)

            await self._update_task(
                db_task.id,
                media_type=parsed["media_type"],
                tmdb_id=matched.get("tmdb_id"),
                tmdb_title=title,
                tmdb_year=year,
                genre_name=region_name,
                target_path=target_desc,
            )

            return {
                "ready": True,
                "moved": False,
                "fid": fid,
                "filename": filename,
                "item": item,
                "parsed": parsed,
                "matched": matched,
                "naming": naming,
                "display_title": display_title,
                "target_cid": target_cid,
                "target_desc": target_desc,
                "new_filename": new_filename,
                "task_id": db_task.id,
            }
        except asyncio.CancelledError:
            await self._mark_task_failed(db_task.id, "归档扫描已取消")
            raise
        except Exception as exc:
            msg = str(exc) or "未知错误"
            await self._mark_task_failed(db_task.id, msg)
            logger.warning("归档准备 %s 失败: %s", filename, msg)
            return {
                "ready": False,
                "result": {
                    "task_id": db_task.id,
                    "status": ArchiveStatus.FAILED.value,
                    "source_fid": fid,
                    "source_filename": filename,
                    "message": msg,
                },
            }

    async def _finalize_identified(
        self,
        pan115: Pan115Service,
        *,
        plan: dict[str, Any],
        subtitle_items: list[dict[str, Any]] | None = None,
        season_episode_cache: dict[str, set[tuple[int, int]]] | None = None,
        folder_snapshot_cache: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """文件已移动后：重命名、字幕、标记成功。"""
        fid = str(plan.get("fid") or "")
        filename = str(plan.get("filename") or "")
        parsed = dict(plan.get("parsed") or {})
        matched = plan.get("matched") or {}
        naming = plan.get("naming")
        display_title = str(plan.get("display_title") or "")
        target_cid = str(plan.get("target_cid") or "")
        target_desc = str(plan.get("target_desc") or "")
        new_filename = str(plan.get("new_filename") or filename)
        task_id = plan.get("task_id")
        item = plan.get("item") or {}

        try:
            if folder_snapshot_cache is not None and target_cid in folder_snapshot_cache:
                del folder_snapshot_cache[target_cid]
            snapshot = await self._get_target_folder_snapshot(
                pan115, target_cid, folder_snapshot_cache
            )
            duplicate_message = self._snapshot_has_filename_conflict(
                snapshot,
                source_filename=filename,
                target_filename=new_filename,
                exclude_fid=fid,
            )
            if duplicate_message:
                try:
                    await pan115.delete_file([fid])
                except Exception as exc:
                    logger.warning("删除重复归档文件 %s 失败: %s", filename, exc)
                if task_id:
                    await self._mark_task_skipped(task_id, duplicate_message)
                return self._build_archive_skip_result(item, duplicate_message)

            # 移动后按 SxxExx 再判一次（同集不同扩展名/画质后缀）
            # 不传 season_episode_cache：prepare 已把本集写入缓存，否则会误伤自身
            if str(parsed.get("media_type") or "") == "tv":
                episode_conflict = await self._check_tv_episode_archive_conflict(
                    pan115,
                    parsed,
                    filename,
                    target_cid,
                    None,
                    new_filename=new_filename,
                    exclude_fid=fid,
                    folder_snapshot_cache=folder_snapshot_cache,
                )
                if episode_conflict:
                    try:
                        await pan115.delete_file([fid])
                    except Exception as exc:
                        logger.warning(
                            "删除同集重复归档文件 %s 失败: %s", filename, exc
                        )
                    if task_id:
                        await self._mark_task_skipped(task_id, episode_conflict)
                    return self._build_archive_skip_result(item, episode_conflict)

            renamed = await self._rename_archived_file(
                pan115, fid, filename, new_filename
            )
            if not renamed and normalize_archive_basename(new_filename):
                refreshed = await self._get_target_folder_snapshot(
                    pan115, target_cid, None
                )
                retry_message = self._snapshot_has_filename_conflict(
                    refreshed,
                    source_filename=filename,
                    target_filename=new_filename,
                    exclude_fid=fid,
                )
                if retry_message:
                    try:
                        await pan115.delete_file([fid])
                    except Exception as exc:
                        logger.warning(
                            "重命名冲突后删除重复文件 %s 失败: %s", filename, exc
                        )
                    if task_id:
                        await self._mark_task_skipped(task_id, retry_message)
                    return self._build_archive_skip_result(item, retry_message)

            if subtitle_items:
                await self._move_subtitles(
                    pan115,
                    item,
                    subtitle_items,
                    target_cid,
                    parsed,
                    matched,
                    naming=naming,
                    display_title=display_title,
                )

            if task_id:
                await self._mark_task_success(task_id)
            if parsed.get("media_type") == "tv" and season_episode_cache is not None:
                self._remember_archived_tv_episodes(
                    parsed,
                    filename,
                    target_cid,
                    season_episode_cache,
                )
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="archive",
                action="archive.file.success",
                status="success",
                message=(
                    f"归档完成：{filename} → {target_desc}"
                    + (f"（重命名为 {new_filename}）" if renamed else "")
                ),
                extra={
                    "task_id": task_id,
                    "target_desc": target_desc,
                    "renamed": renamed,
                    "new_filename": new_filename if renamed else "",
                },
            )
            return {
                "task_id": task_id,
                "status": ArchiveStatus.SUCCESS.value,
                "source_fid": fid,
                "source_filename": filename,
                "target_desc": target_desc,
                "target_cid": target_cid,
                "renamed": renamed,
                "new_filename": new_filename if renamed else filename,
            }
        except asyncio.CancelledError:
            if task_id:
                await self._mark_task_failed(task_id, "归档扫描已取消")
            raise
        except Exception as exc:
            msg = str(exc) or "未知错误"
            if task_id:
                await self._mark_task_failed(task_id, msg)
            logger.warning("归档收尾 %s 失败: %s", filename, msg)
            return {
                "task_id": task_id,
                "status": ArchiveStatus.FAILED.value,
                "source_fid": fid,
                "source_filename": filename,
                "message": msg,
            }

    async def _process_identified(
        self,
        pan115: Pan115Service,
        item: dict[str, Any],
        identify_info: dict[str, Any],
        output_cid: str,
        trigger: str = "manual",
        folder_cache: dict[tuple[str, ...], str] | None = None,
        subtitle_items: list[dict[str, Any]] | None = None,
        season_episode_cache: dict[str, set[tuple[int, int]]] | None = None,
        folder_snapshot_cache: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """单文件完整归档（重试入口）：准备 → 移动 → 收尾。"""
        del trigger  # 保留参数兼容调用方
        plan = await self._prepare_identified(
            pan115,
            item=item,
            identify_info=identify_info,
            output_cid=output_cid,
            folder_cache=folder_cache,
            season_episode_cache=season_episode_cache,
            folder_snapshot_cache=folder_snapshot_cache,
        )
        if not plan.get("ready"):
            return plan.get("result") or {
                "status": ArchiveStatus.FAILED.value,
                "source_fid": item.get("fid", ""),
                "source_filename": item.get("name", ""),
                "message": "归档准备失败",
            }
        try:
            await pan115.move_file(str(plan["fid"]), str(plan["target_cid"]))
            plan["moved"] = True
        except Exception as exc:
            msg = str(exc) or "移动失败"
            task_id = plan.get("task_id")
            if task_id:
                await self._mark_task_failed(task_id, msg)
            return {
                "task_id": task_id,
                "status": ArchiveStatus.FAILED.value,
                "source_fid": plan.get("fid", ""),
                "source_filename": plan.get("filename", ""),
                "message": msg,
            }
        return await self._finalize_identified(
            pan115,
            plan=plan,
            subtitle_items=subtitle_items,
            season_episode_cache=season_episode_cache,
            folder_snapshot_cache=folder_snapshot_cache,
        )

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
        season_episode_cache: dict[str, set[tuple[int, int]]] | None = None,
        folder_snapshot_cache: dict[str, dict[str, Any]] | None = None,
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
            binding = await transfer_file_binding_service.get_by_file_fid(fid)
            matched = None
            if binding and binding.get("tmdb_id"):
                if binding.get("media_type"):
                    parsed["media_type"] = (
                        "tv" if str(binding.get("media_type")) == "tv" else "movie"
                    )
                if binding.get("season") is not None:
                    if parsed.get("season") is None:
                        parsed["season"] = int(binding["season"])
                if binding.get("episode") is not None:
                    if parsed.get("episode") is None:
                        parsed["episode"] = int(binding["episode"])
                matched = await self._identify_by_tmdb_id(
                    int(binding["tmdb_id"]),
                    str(parsed.get("media_type") or "movie"),
                )
            if not matched:
                matched = await self.identify_media(parsed)
            transfer_context = await self._lookup_transfer_context(
                str(item.get("cid") or source_cid or ""),
                fid,
                str(item.get("relative_path") or ""),
                tmdb_id=int(matched.get("tmdb_id") or 0) if matched else None,
                media_type=str(parsed.get("media_type") or "movie"),
                filename=filename,
            )
            if binding and binding.get("display_title"):
                transfer_context["binding_display_title"] = str(
                    binding.get("display_title") or ""
                ).strip()
            intent = transfer_context.get("intent") or {}
            if intent and matched and not intent_matches_file(
                intent,
                filename=filename,
                folder_name=str(transfer_context.get("folder_name") or ""),
                tmdb_id=int(matched.get("tmdb_id") or 0) or None,
            ):
                if str(intent.get("media_type") or "").lower() != "tv":
                    transfer_context["intent"] = {}
                    intent = {}

            original_type = str(parsed.get("media_type") or "movie")
            parsed = self._apply_tv_media_type_hints(
                parsed,
                binding=binding or {},
                intent=intent,
                relative_path=str(item.get("relative_path") or ""),
                folder_name=str(transfer_context.get("folder_name") or ""),
            )

            if intent.get("tmdb_id") and not (binding and binding.get("tmdb_id")):
                intent_matched = await self._identify_by_tmdb_id(
                    int(intent["tmdb_id"]),
                    str(intent.get("media_type") or parsed.get("media_type") or "movie"),
                )
                if intent_matched:
                    matched = intent_matched
            elif (
                original_type != "tv"
                and str(parsed.get("media_type") or "") == "tv"
            ):
                rematch_id = int(
                    (intent.get("tmdb_id") if intent else 0)
                    or ((binding or {}).get("tmdb_id") or 0)
                    or ((matched or {}).get("tmdb_id") or 0)
                    or 0
                )
                if rematch_id > 0:
                    rematched = await self._identify_by_tmdb_id(rematch_id, "tv")
                    if rematched:
                        matched = rematched
                    else:
                        rematched = await self.identify_media(parsed)
                        if rematched:
                            matched = rematched
                else:
                    rematched = await self.identify_media(parsed)
                    if rematched:
                        matched = rematched
            if not matched:
                raise ValueError("TMDB 未匹配到可用结果")

            region_name = str(matched.get("region_name") or MOVIE_REGION_DEFAULT)
            display_title = self._resolve_archive_display_title(
                parsed,
                matched,
                transfer_context={**transfer_context, "filename": filename},
            )
            title = display_title
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
                display_title=display_title,
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
                await self._cleanup_duplicate_tv_episodes_in_folder(
                    pan115,
                    target_cid,
                    folder_snapshot_cache=folder_snapshot_cache,
                )
                new_filename = self._build_target_filename(
                    parsed,
                    matched,
                    filename,
                    naming,
                    display_title=display_title,
                )
                conflict = await self._check_tv_episode_archive_conflict(
                    pan115,
                    parsed,
                    filename,
                    target_cid,
                    season_episode_cache,
                    new_filename=new_filename,
                    exclude_fid=fid,
                    folder_snapshot_cache=folder_snapshot_cache,
                )
                if conflict:
                    await self._mark_task_skipped(db_task.id, conflict)
                    return self._build_archive_skip_result(item, conflict)
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
                new_filename = self._build_target_filename(
                    parsed,
                    matched,
                    filename,
                    naming,
                    display_title=display_title,
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

            await pan115.move_file(fid, target_cid)
            return await self._finalize_identified(
                pan115,
                plan={
                    "fid": fid,
                    "filename": filename,
                    "parsed": parsed,
                    "matched": matched,
                    "naming": naming,
                    "display_title": display_title,
                    "target_cid": target_cid,
                    "target_desc": target_desc,
                    "new_filename": new_filename,
                    "task_id": db_task.id,
                    "item": item,
                    "moved": True,
                },
                subtitle_items=subtitle_items,
                season_episode_cache=season_episode_cache,
                folder_snapshot_cache=folder_snapshot_cache,
            )
        except asyncio.CancelledError:
            await self._mark_task_failed(db_task.id, "归档扫描已取消")
            raise
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
    def _extract_transfer_folder_name(relative_path: str) -> str:
        path = str(relative_path or "").strip().replace("\\", "/")
        if "/" not in path:
            return ""
        return path.rsplit("/", 1)[0].split("/")[-1].strip()

    def _title_from_transfer_resource_name(self, resource_name: str) -> str:
        name = str(resource_name or "").strip()
        if not name:
            return ""
        parsed = self.parse_media_filename(
            name if "." in name else f"{name}.mkv"
        )
        return str(parsed.get("query_title") or "").strip()

    async def _lookup_transfer_context(
        self,
        parent_cid: str,
        fid: str,
        relative_path: str,
        *,
        tmdb_id: int | None = None,
        media_type: str = "",
        filename: str = "",
    ) -> dict[str, Any]:
        resource_name = ""
        subscription_title = ""
        subscription_title_by_tmdb = ""
        folder_name = self._extract_transfer_folder_name(relative_path)
        file_title_hint = extract_chinese_title_from_text(
            filename or (relative_path.rsplit("/", 1)[-1] if relative_path else "")
        )
        lookup_ids = [value for value in (parent_cid, fid) if str(value or "").strip()]
        if lookup_ids:
            async with async_session_maker() as db:
                stmt = (
                    select(DownloadRecord.resource_name, Subscription.title)
                    .join(
                        Subscription,
                        DownloadRecord.subscription_id == Subscription.id,
                        isouter=True,
                    )
                    .where(DownloadRecord.file_id.in_(lookup_ids))
                    .order_by(
                        DownloadRecord.completed_at.desc().nullslast(),
                        DownloadRecord.created_at.desc(),
                    )
                )
                if file_title_hint:
                    stmt = stmt.where(
                        DownloadRecord.resource_name.contains(file_title_hint)
                        | Subscription.title.contains(file_title_hint)
                    )
                result = await db.execute(stmt.limit(1))
                row = result.first()
                if row:
                    resource_name = str(row.resource_name or "").strip()
                    subscription_title = str(row.title or "").strip()
                elif file_title_hint:
                    fallback = await db.execute(
                        select(DownloadRecord.resource_name, Subscription.title)
                        .join(
                            Subscription,
                            DownloadRecord.subscription_id == Subscription.id,
                            isouter=True,
                        )
                        .where(DownloadRecord.file_id.in_(lookup_ids))
                        .order_by(
                            DownloadRecord.completed_at.desc().nullslast(),
                            DownloadRecord.created_at.desc(),
                        )
                        .limit(1)
                    )
                    row = fallback.first()
                    if row:
                        resource_name = str(row.resource_name or "").strip()
                        subscription_title = str(row.title or "").strip()

        intent = await transfer_intent_service.find_best_match(
            parent_cid=parent_cid,
            file_fid=fid,
            tmdb_id=tmdb_id,
            media_type=media_type,
            filename=filename,
            folder_name=folder_name,
        )
        # 文件名误判为 movie 时，按类型过滤会漏掉剧集意图；再无类型兜底一次
        if not intent and str(media_type or "").strip().lower() == "movie":
            intent = await transfer_intent_service.find_best_match(
                parent_cid=parent_cid,
                file_fid=fid,
                tmdb_id=tmdb_id,
                media_type="",
                filename=filename,
                folder_name=folder_name,
            )

        lookup_tmdb_id = int(intent["tmdb_id"]) if intent and intent.get("tmdb_id") else None
        if not lookup_tmdb_id and tmdb_id and int(tmdb_id) > 0:
            lookup_tmdb_id = int(tmdb_id)

        effective_media_type = str(
            (intent or {}).get("media_type") or media_type or "movie"
        ).strip().lower()
        if effective_media_type != "tv":
            effective_media_type = "movie"

        if lookup_tmdb_id:
            async with async_session_maker() as db:
                sub_result = await db.execute(
                    select(Subscription.title)
                    .where(
                        Subscription.tmdb_id == lookup_tmdb_id,
                        Subscription.media_type == (
                            MediaType.TV
                            if effective_media_type == "tv"
                            else MediaType.MOVIE
                        ),
                    )
                    .order_by(Subscription.updated_at.desc())
                    .limit(1)
                )
                subscription_title_by_tmdb = str(sub_result.scalar_one_or_none() or "").strip()
                if not subscription_title_by_tmdb and effective_media_type == "movie":
                    # 电影检索无结果时，再试剧集订阅标题（误判兜底）
                    sub_result = await db.execute(
                        select(Subscription.title)
                        .where(
                            Subscription.tmdb_id == lookup_tmdb_id,
                            Subscription.media_type == MediaType.TV,
                        )
                        .order_by(Subscription.updated_at.desc())
                        .limit(1)
                    )
                    subscription_title_by_tmdb = str(
                        sub_result.scalar_one_or_none() or ""
                    ).strip()

        if not resource_name and folder_name:
            resource_name = folder_name

        return {
            "resource_name": resource_name,
            "subscription_title": subscription_title or subscription_title_by_tmdb,
            "subscription_title_by_tmdb": subscription_title_by_tmdb,
            "folder_name": folder_name,
            "intent": intent or {},
            "filename": filename,
        }

    def _resolve_archive_display_title(
        self,
        parsed: dict[str, Any],
        matched: dict[str, Any],
        *,
        transfer_context: dict[str, Any] | None = None,
    ) -> str:
        context = transfer_context or {}
        media_type = str(parsed.get("media_type") or "movie")
        intent = context.get("intent") or {}
        intent_title = str(intent.get("display_title") or "").strip()
        binding_title = str(context.get("binding_display_title") or "").strip()
        source_filename = str(context.get("filename") or parsed.get("source_filename") or "")

        if intent_title and not intent_matches_file(
            intent,
            filename=source_filename,
            folder_name=str(context.get("folder_name") or ""),
            tmdb_id=int(matched.get("tmdb_id") or 0) or None,
        ):
            intent_title = ""

        folder_title = extract_chinese_title_from_text(str(context.get("folder_name") or ""))
        resource_title = extract_chinese_title_from_text(
            str(context.get("resource_name") or "")
        )
        # binding/intent/订阅/TMDB 也统一清洗，避免广告括号或画质尾巴进入归档名
        binding_title = clean_archive_display_title(binding_title)
        intent_title = clean_archive_display_title(intent_title)
        subscription_title = clean_archive_display_title(
            str(context.get("subscription_title") or "")
        )
        subscription_title_by_tmdb = clean_archive_display_title(
            str(context.get("subscription_title_by_tmdb") or "")
        )
        tmdb_title = clean_archive_display_title(str(matched.get("title") or ""))
        parsed_title = clean_archive_display_title(
            str(parsed.get("query_title") or "")
        )

        if media_type == "movie":
            # 电影：绑定/意图/订阅优先；文件夹与资源名常带广告，放在 TMDB 之后作为兜底
            return pick_preferred_chinese_title(
                binding_title,
                intent_title,
                subscription_title,
                subscription_title_by_tmdb,
                tmdb_title,
                folder_title,
                resource_title,
                parsed_title,
            )

        return pick_preferred_chinese_title(
            binding_title,
            intent_title,
            subscription_title,
            subscription_title_by_tmdb,
            tmdb_title,
            folder_title,
            resource_title,
            parsed_title,
        )

    async def _rename_archived_file(
        self,
        pan115: Pan115Service,
        fid: str,
        old_name: str,
        new_name: str,
    ) -> bool:
        normalized_old = str(old_name or "").strip()
        normalized_new = str(new_name or "").strip()
        if not normalized_new or normalized_new == normalized_old:
            return False
        try:
            await pan115.rename_file(fid, normalized_new)
            return True
        except Exception as exc:
            logger.warning(
                "重命名 %s -> %s 失败，保留原文件名：%s",
                normalized_old,
                normalized_new,
                exc,
            )
            return False

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
        display_title: str = "",
    ) -> str:
        template_key = "tv_folder" if media_type == "tv" else "movie_folder"
        matched = matched or {}
        parsed = parsed or {}
        resolved_title = str(display_title or title or "").strip()
        return render_archive_name(
            naming,
            template_key,
            title=resolved_title,
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
        *,
        display_title: str = "",
    ) -> str:
        title = str(
            display_title
            or matched.get("title")
            or parsed.get("query_title")
            or ""
        )
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
        *,
        display_title: str = "",
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
                    sub_parsed,
                    matched,
                    sub["name"],
                    naming,
                    display_title=display_title,
                )
                await self._rename_archived_file(
                    pan115, sub["fid"], sub["name"], new_sub_name
                )
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

    async def _cached_get_or_create_folder(
        self,
        pan115: Pan115Service,
        parent_cid: str,
        folder_name: str,
        folder_cache: dict[tuple[str, ...], str] | None = None,
    ) -> str:
        """按 (父目录, 名称) 缓存中间目录 CID，避免同一次扫描重复 search/create。"""
        key = ("folder", str(parent_cid), str(folder_name))
        if folder_cache is not None and key in folder_cache:
            return folder_cache[key]
        cid = await pan115.get_or_create_folder(parent_cid, folder_name)
        if folder_cache is not None:
            folder_cache[key] = cid
        return cid

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

        movies_cid = await self._cached_get_or_create_folder(
            pan115, root_cid, movie_root, folder_cache
        )
        region_cid = await self._cached_get_or_create_folder(
            pan115, movies_cid, region, folder_cache
        )
        folder_cid = await self._cached_get_or_create_folder(
            pan115, region_cid, title_folder, folder_cache
        )
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

        tv_cid = await self._cached_get_or_create_folder(
            pan115, root_cid, tv_root, folder_cache
        )
        genre_cid = await self._cached_get_or_create_folder(
            pan115, tv_cid, genre, folder_cache
        )
        title_cid = await self._cached_get_or_create_folder(
            pan115, genre_cid, title_folder, folder_cache
        )
        season_cid = await self._cached_get_or_create_folder(
            pan115, title_cid, season_dir, folder_cache
        )
        if folder_cache is not None:
            folder_cache[cache_key] = season_cid
        return season_cid

    # ---------- TMDB 识别 ----------

    async def identify_media(
        self,
        parsed: dict[str, Any],
        *,
        id_cache: dict[tuple[str, int], dict[str, Any] | None] | None = None,
        search_cache: dict[tuple[str, str, int | None], list[Any]] | None = None,
    ) -> dict[str, Any] | None:
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
                query=query_title,
                media_type=media_type,
                year=year,
                cache=search_cache,
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

        cached = await self._identify_by_tmdb_id(
            tmdb_id, media_type, cache=id_cache
        )
        if not cached:
            return None
        if not cached.get("title"):
            cached["title"] = pick_preferred_chinese_title(
                str(first.get("title") or first.get("name") or used_query).strip()
            )
        if not cached.get("year"):
            cached["year"] = str(parsed.get("year") or "")
        return cached

    async def _identify_by_tmdb_id(
        self,
        tmdb_id: int,
        media_type: str,
        *,
        cache: dict[tuple[str, int], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any] | None:
        if not tmdb_id or int(tmdb_id) <= 0:
            return None
        normalized_type = "tv" if str(media_type or "") == "tv" else "movie"
        cache_key = (normalized_type, int(tmdb_id))
        if cache is not None and cache_key in cache:
            cached = cache[cache_key]
            return dict(cached) if isinstance(cached, dict) else None
        try:
            detail = (
                await tmdb_service.get_movie_detail(int(tmdb_id))
                if normalized_type == "movie"
                else await tmdb_service.get_tv_detail(int(tmdb_id))
            )
        except Exception:
            if cache is not None:
                cache[cache_key] = None
            return None
        if not isinstance(detail, dict) or not detail:
            if cache is not None:
                cache[cache_key] = None
            return None

        title = pick_preferred_chinese_title(
            str(detail.get("title") or "").strip(),
            str(detail.get("name") or "").strip(),
            str(detail.get("original_title") or "").strip(),
            str(detail.get("original_name") or "").strip(),
        )
        release_date = str(
            detail.get("release_date") or detail.get("first_air_date") or ""
        ).strip()
        year_text = release_date[:4] if len(release_date) >= 4 else ""
        genre_name = self._extract_genre_name(detail, normalized_type)
        subdirs = self._get_archive_subdirs()
        region_name = (
            self._extract_movie_region(detail, subdirs=subdirs)
            if normalized_type == "movie"
            else self._extract_tv_category(detail, subdirs=subdirs)
        )
        result = {
            "tmdb_id": int(tmdb_id),
            "media_type": normalized_type,
            "title": title,
            "year": year_text,
            "genre_name": genre_name,
            "region_name": region_name,
        }
        if cache is not None:
            cache[cache_key] = dict(result)
        return result

    @classmethod
    def _apply_tv_media_type_hints(
        cls,
        parsed: dict[str, Any],
        *,
        binding: dict[str, Any] | None = None,
        intent: dict[str, Any] | None = None,
        relative_path: str = "",
        folder_name: str = "",
    ) -> dict[str, Any]:
        """综合 binding / 转存意图 / 路径痕迹，纠正误判为 movie 的剧集。"""
        result = dict(parsed or {})
        binding = binding or {}
        intent = intent or {}
        path_hint = f"{relative_path}\n{folder_name}"

        forced_tv = False
        if str(binding.get("media_type") or "").strip().lower() == "tv":
            forced_tv = True
        elif str(intent.get("media_type") or "").strip().lower() == "tv":
            forced_tv = True
        elif _PATH_TV_HINT_RE.search(path_hint):
            forced_tv = True

        if forced_tv:
            result["media_type"] = "tv"

        if str(result.get("media_type") or "") != "tv":
            return result

        if binding.get("season") is not None and result.get("season") is None:
            try:
                result["season"] = int(binding["season"])
            except Exception:
                pass
        if binding.get("episode") is not None and result.get("episode") is None:
            try:
                result["episode"] = int(binding["episode"])
            except Exception:
                pass

        if result.get("season") is None:
            season_match = _PATH_SEASON_RE.search(path_hint)
            if season_match:
                raw = season_match.group("season") or season_match.group("season_en")
                if raw and str(raw).isdigit():
                    result["season"] = int(raw)
        if result.get("season") is None:
            result["season"] = 1
        return result

    @staticmethod
    def _extract_tmdb_item_year(item: dict[str, Any]) -> int | None:
        for key in ("release_date", "first_air_date", "year"):
            raw = str(item.get(key) or "").strip()
            if len(raw) >= 4 and raw[:4].isdigit():
                value = int(raw[:4])
                if 1800 <= value <= 2100:
                    return value
        return None

    @classmethod
    def _rank_tmdb_items_by_year(
        cls,
        items: list[Any],
        expected_year: int | None,
    ) -> list[Any]:
        """有解析年份时优先精确年，其次 ±1 年，避免冷门片名串到同名旧作。"""
        normalized = [item for item in items if isinstance(item, dict)]
        if not normalized or expected_year is None:
            return normalized

        exact: list[dict[str, Any]] = []
        near: list[dict[str, Any]] = []
        for item in normalized:
            item_year = cls._extract_tmdb_item_year(item)
            if item_year is None:
                continue
            if item_year == expected_year:
                exact.append(item)
            elif abs(item_year - expected_year) <= 1:
                near.append(item)
        if exact:
            return exact
        if near:
            return near
        # 有明确年份却完全对不上时，不要盲目用第一条错误结果
        return []

    async def _search_tmdb_items(
        self,
        *,
        query: str,
        media_type: str,
        year: int | None,
        cache: dict[tuple[str, str, int | None], list[Any]] | None = None,
    ) -> list[Any]:
        cache_key = (str(media_type or "movie"), str(query or ""), year)
        if cache is not None and cache_key in cache:
            return list(cache[cache_key])

        result = await tmdb_service.search_by_media_type(
            query=query,
            media_type=media_type,
            page=1,
            year=year,
        )
        items = result.get("results") if isinstance(result.get("results"), list) else []
        if items:
            if year is None:
                if cache is not None:
                    cache[cache_key] = list(items)
                return items
            ranked = self._rank_tmdb_items_by_year(items, year)
            # 年份检索已由 TMDB 过滤时，若条目缺日期字段则仍信任原结果
            resolved = ranked or items
            if cache is not None:
                cache[cache_key] = list(resolved)
            return resolved
        if year is None:
            if cache is not None:
                cache[cache_key] = []
            return []
        result = await tmdb_service.search_by_media_type(
            query=query,
            media_type=media_type,
            page=1,
            year=None,
        )
        fallback_items = (
            result.get("results") if isinstance(result.get("results"), list) else []
        )
        # 无年份过滤的回退必须严格按解析年份筛选，避免 Cold War 串到同名旧作
        ranked = self._rank_tmdb_items_by_year(fallback_items, year)
        if cache is not None:
            cache[cache_key] = list(ranked)
        return ranked

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
        # 注意：会把 S02E01 误拆成 S02.E01，后面必须还原，否则季号丢失默认成第1季
        text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", ".", text)
        text = re.sub(
            r"(?i)(S\d{1,2})\.+(E\d{1,3}(?:\s*[-~_至到]+\s*E?\d{1,3})?)",
            r"\1\2",
            text,
        )
        # 字母与年份分界：Zootopia2025 -> Zootopia.2025
        text = re.sub(r"(?<=[A-Za-z])(19\d{2}|20\d{2})(?![0-9])", r".\1", text)
        # 中文与年份分界：冷战1994 -> 冷战.1994
        text = re.sub(
            r"(?<=[\u3400-\u9fff])(19\d{2}|20\d{2})(?![0-9])",
            r".\1",
            text,
        )
        return text

    @staticmethod
    def _iter_year_matches(name: str, *, end: int | None = None) -> list[re.Match[str]]:
        """收集文件名中的年份匹配（可限制在 end 之前）。"""
        limit = len(name) if end is None else max(0, min(int(end), len(name)))
        search_text = name[:limit]
        matches: list[re.Match[str]] = []
        seen_spans: set[tuple[int, int]] = set()
        for pattern in (
            r"(?<![A-Za-z0-9])(19\d{2}|20\d{2})(?![A-Za-z0-9])",
            r"[.\-_](19\d{2}|20\d{2})(?![A-Za-z0-9])",
            r"(?<=[A-Za-z\u3400-\u9fff])(19\d{2}|20\d{2})(?![A-Za-z0-9])",
        ):
            for match in re.finditer(pattern, search_text):
                span = match.span(1)
                if span in seen_spans:
                    continue
                seen_spans.add(span)
                matches.append(match)
        matches.sort(key=lambda item: item.start(1))
        return matches

    @classmethod
    def _find_year_match(
        cls,
        name: str,
        *,
        end: int | None = None,
        prefer_last: bool = True,
    ) -> tuple[re.Match[str] | None, str | None]:
        """
        提取发行年份。

        资源名常见「片名年份 + 上映年份」，如 Cold.War.1994.2026.2160p。
        默认取画质/剧集标记前的最后一个年份作为上映年，前面的年份保留在片名中。
        """
        matches = cls._iter_year_matches(name, end=end)
        if not matches:
            return None, None
        chosen = matches[-1] if prefer_last else matches[0]
        return chosen, chosen.group(1)

    def parse_media_filename(self, filename: str) -> dict[str, Any]:
        ext_match = re.search(r"\.[^.]+$", filename)
        ext = ext_match.group(0) if ext_match else ""
        name = filename[: -len(ext)] if ext else filename
        name = self._prepare_filename_stem(name)

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

        tech_match = TECH_CUT_RE.search(name)
        if tech_match and tech_match.start() < title_end:
            title_end = tech_match.start()

        zh_noise_match = ZH_NOISE_CUT_RE.search(name)
        if zh_noise_match and zh_noise_match.start() < title_end:
            # 仅当噪音词出现在片名之后（前面已有有效文字）时才截断
            prefix = name[: zh_noise_match.start()].strip(" ._-")
            if prefix:
                title_end = zh_noise_match.start()

        # 在画质/剧集截断点之前取“最后一个年份”作为上映年
        year_match, year = self._find_year_match(name, end=title_end, prefer_last=True)
        if year_match and year_match.start() < title_end:
            title_end = year_match.start()

        raw_title = name[:title_end] if title_end > 0 else name
        # 去掉片名前缀广告组 【xxx】 [xxx]
        raw_title = re.sub(r"^[\s\[【（(]+[^\]】）)]*[\]】）)]\s*", "", raw_title)
        query_title = self._normalize_title(raw_title)
        if not query_title:
            query_title = self._normalize_title(name)

        # 与 name_parser 对齐：原始文件名能解析出季集时，纠正 stem 拆分导致的季号丢失
        coverage = name_parser.parse_episode_coverage(filename)
        if coverage:
            media_type = "tv"
            if season is None:
                season = int(coverage["season"])
            if episode is None:
                episode = int(coverage["episode_start"])
            # 文件名明确写了 S02E01，不得被默认季号/残缺解析覆盖成 S01
            elif int(coverage["season"]) != int(season or 0):
                season = int(coverage["season"])
                episode = int(coverage["episode_start"])

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
        tech_match = TECH_CUT_RE.search(stem)
        if tech_match:
            cut = min(cut, tech_match.start())
        zh_noise_match = ZH_NOISE_CUT_RE.search(stem)
        if zh_noise_match and stem[: zh_noise_match.start()].strip(" ._-"):
            cut = min(cut, zh_noise_match.start())
        year_match, _year = cls._find_year_match(stem, end=cut, prefer_last=True)
        if year_match:
            cut = min(cut, year_match.start())

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

    async def cancel_task(self, task_id: int) -> dict[str, Any]:
        async with async_session_maker() as db:
            task = await db.get(ArchiveTask, task_id)
            if not task:
                raise ValueError("归档任务不存在")
            if task.status != ArchiveStatus.PROCESSING:
                raise ValueError("只能取消处理中的任务")
            now = beijing_now()
            task.status = ArchiveStatus.FAILED
            task.error_message = "任务已手动取消，可点击重试"
            task.completed_at = now
            await db.commit()
        return {
            "cancelled": True,
            "task_id": task_id,
            "runtime": await self.get_runtime_status_async(),
        }

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

    async def clear_tasks(
        self,
        include_failed: bool = False,
        include_stale_processing: bool = False,
    ) -> int:
        if include_stale_processing:
            await self._mark_processing_tasks_failed(
                reason="任务长时间未完成，已手动清理",
                max_age_minutes=ARCHIVE_STALE_TASK_MINUTES,
            )

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
        await self.reconcile_idle_processing_tasks()
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

    async def _mark_task_skipped(self, task_id: int, reason: str) -> None:
        await self._update_task(
            task_id,
            status=ArchiveStatus.SKIPPED,
            error_message=str(reason or "")[:2000],
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
