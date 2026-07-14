from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import socket
import time
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from sqlalchemy import delete, func, select
from starlette.background import BackgroundTask

from app.core.database import async_session_maker, ensure_tables_exist
from app.models.strm_index import StrmFileIndex, StrmFolderIndex, StrmSyncState
from app.services.emby_service import emby_service
from app.services.feiniu_service import feiniu_service
from app.services.operation_log_service import operation_log_service
from app.services.playback_log_service import playback_log_service
from app.services.pan115_service import Pan115Service, pan115_service
from app.services.runtime_settings_service import runtime_settings_service
from app.utils.proxy import proxy_manager

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
MANIFEST_FILENAME = ".mediasync115-strm-manifest.json"
DOWNLOAD_URL_CACHE_DEFAULT_TTL_SECONDS = 1800.0
DOWNLOAD_URL_CACHE_MAX_ITEMS = 512


class StrmService:
    """STRM 生成与播放服务"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._download_url_cache_lock = asyncio.Lock()
        self._download_url_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._proxy_client: httpx.AsyncClient | None = None
        self._proxy_client_lock = asyncio.Lock()
        self._generate_task: asyncio.Task[dict[str, Any]] | None = None
        self._last_generate_started_at: str = ""
        self._last_generate_finished_at: str = ""
        self._last_generate_error: str = ""
        self._last_generate_summary: dict[str, Any] | None = None
        self._last_generate_trigger: str = ""
        self._current_mode: str = ""
        self._pending_mode: str | None = None
        self._pending_scopes: list[dict[str, str]] = []
        self._pending_unscoped = False
        self._index_stats: dict[str, Any] = {
            "file_count": 0,
            "folder_count": 0,
            "output_cid": "",
        }

    def get_runtime_status(self) -> dict[str, Any]:
        generate_running = bool(self._generate_task and not self._generate_task.done())
        return {
            "generate_running": generate_running or self._lock.locked(),
            "last_generate_started_at": self._last_generate_started_at,
            "last_generate_finished_at": self._last_generate_finished_at,
            "last_generate_error": self._last_generate_error,
            "last_generate_summary": self._last_generate_summary,
            "last_generate_trigger": self._last_generate_trigger,
            "current_mode": self._current_mode,
            "queued": bool(self._pending_mode),
            "queued_mode": self._pending_mode or "",
            "queued_scope_count": len(self._pending_scopes),
            "index_stats": dict(self._index_stats),
            "last_incremental_at": str(
                self._index_stats.get("last_incremental_at") or ""
            ),
            "last_full_at": str(self._index_stats.get("last_full_at") or ""),
        }

    async def get_runtime_status_async(self) -> dict[str, Any]:
        """合并进程内任务状态与持久化索引状态。"""
        status = self.get_runtime_status()
        output_cid = runtime_settings_service.get_archive_output_cid()
        if not output_cid:
            return status
        try:
            await ensure_tables_exist(
                "strm_file_index", "strm_folder_index", "strm_sync_state"
            )
            async with async_session_maker() as session:
                state = await session.get(StrmSyncState, output_cid)
                if state is None:
                    return status
                index_stats = {
                    "output_cid": output_cid,
                    "output_dir": state.output_dir,
                    "file_count": state.file_count,
                    "folder_count": state.folder_count,
                    "last_mode": state.last_mode,
                    "last_status": state.last_status,
                    "last_incremental_at": (
                        state.last_incremental_at.isoformat()
                        if state.last_incremental_at
                        else ""
                    ),
                    "last_full_at": (
                        state.last_full_at.isoformat() if state.last_full_at else ""
                    ),
                }
                self._index_stats = index_stats
                status["index_stats"] = index_stats
                status["last_incremental_at"] = index_stats["last_incremental_at"]
                status["last_full_at"] = index_stats["last_full_at"]
                if not status["last_generate_error"] and state.last_error:
                    status["last_generate_error"] = state.last_error
        except Exception:
            logger.warning("读取 STRM 持久化状态失败", exc_info=True)
        return status

    @staticmethod
    def detect_mount_paths() -> list[dict[str, str]]:
        """检测容器内可用的挂载路径，返回路径和描述的列表"""
        candidates: list[tuple[str, str]] = [
            ("/app/data", "数据目录（data）"),
            ("/app/strm", "STRM 输出目录（strm）"),
        ]
        results: list[dict[str, str]] = []
        for path, label in candidates:
            try:
                p = Path(path)
                if p.exists():
                    results.append(
                        {
                            "path": path,
                            "label": label,
                            "writable": os.access(path, os.W_OK),
                        }
                    )
                else:
                    try:
                        p.mkdir(parents=True, exist_ok=True)
                        results.append({"path": path, "label": label, "writable": True})
                    except Exception:
                        results.append(
                            {"path": path, "label": label, "writable": False}
                        )
            except Exception:
                results.append({"path": path, "label": label, "writable": False})
        return results

    @staticmethod
    def detect_local_ip() -> str:
        """探测本机局域网 IP，用于自动生成播放根地址提示"""
        env_ip = os.environ.get("STRM_HOST_IP", "").strip()
        if env_ip:
            return env_ip
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(2)
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def build_play_url(self, pick_code: str, filename: str = "") -> str:
        """生成 STRM 播放地址（对齐 qmediasync: /api/115/url/video.{ext}?pickcode=）。"""
        base_url = runtime_settings_service.get_strm_base_url()
        if not base_url:
            raise ValueError("STRM 播放地址未配置")
        # 如果启用了 Emby 代理，STRM 文件使用代理端口，所有 Emby 播放经过代理
        if runtime_settings_service.get_strm_proxy_enabled():
            proxy_port = runtime_settings_service.get_strm_proxy_port()
            from urllib.parse import urlparse

            parsed = urlparse(base_url)
            base_url = f"{parsed.scheme}://{parsed.hostname}:{proxy_port}"
        base_url = str(base_url).rstrip("/")
        pc = str(pick_code or "").strip()
        if not pc:
            raise ValueError("pickcode 为空")
        source_name = str(filename or "").strip()
        ext = ".mp4"
        if source_name:
            lower = source_name.lower()
            if lower.endswith(".strm"):
                lower = lower[: -len(".strm")]
            idx = lower.rfind(".")
            if idx >= 0:
                candidate = lower[idx:]
                body = candidate[1:]
                if body and len(body) <= 8 and body.isalnum():
                    ext = candidate
        from urllib.parse import urlencode

        return f"{base_url}/api/115/url/video{ext}?{urlencode({'pickcode': pc})}"

    async def start_generate_library(
        self,
        trigger: str = "manual",
        mode: str = "incremental",
        scopes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        mode = self._validate_mode(mode)
        normalized_scopes = self._normalize_scopes(scopes)
        if self._is_generate_running():
            if mode == "full":
                self._pending_mode = "full"
                self._pending_scopes = []
                self._pending_unscoped = True
            elif self._pending_mode != "full":
                self._merge_pending_scopes(
                    normalized_scopes, unscoped=scopes is None
                )
            return {
                "success": True,
                "started": False,
                "queued": True,
                "mode": self._pending_mode or mode,
                "queued_scope_count": len(self._pending_scopes),
                "trigger": str(trigger or "manual"),
            }

        output_cid, output_dir = self._prepare_generate()
        task = asyncio.create_task(
            self._run_generate_task(
                trigger=str(trigger or "manual"),
                output_cid=output_cid,
                output_dir=output_dir,
                mode=mode,
                scopes=normalized_scopes,
            )
        )
        self._generate_task = task
        task.add_done_callback(self._clear_generate_task)
        return {
            "success": True,
            "started": True,
            "queued": False,
            "trigger": str(trigger or "manual"),
            "mode": mode,
            "scope_count": len(normalized_scopes),
            "output_cid": output_cid,
            "output_dir": str(output_dir),
        }

    async def generate_library(
        self,
        trigger: str = "manual",
        mode: str = "incremental",
        scopes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        mode = self._validate_mode(mode)
        running_task = self._generate_task
        if (
            running_task
            and not running_task.done()
            and asyncio.current_task() is not running_task
        ):
            await asyncio.shield(running_task)

        output_cid, output_dir = self._prepare_generate()

        return await self._run_generate_task(
            trigger=str(trigger or "manual"),
            output_cid=output_cid,
            output_dir=output_dir,
            mode=mode,
            scopes=self._normalize_scopes(scopes),
        )

    async def _run_generate_task(
        self,
        trigger: str,
        output_cid: str,
        output_dir: Path,
        mode: str,
        scopes: list[dict[str, str]],
    ) -> dict[str, Any]:
        if self._lock.locked() and asyncio.current_task() is not self._generate_task:
            raise ValueError("STRM 生成任务正在执行中，请稍后再试")

        async with self._lock:
            started_at = self._now_iso()
            self._last_generate_started_at = started_at
            self._last_generate_finished_at = ""
            self._last_generate_error = ""
            self._last_generate_summary = None
            self._last_generate_trigger = trigger
            self._current_mode = mode

            await operation_log_service.log_background_event(
                source_type="background_task",
                module="strm",
                action="strm.generate.start",
                status="info",
                message=f"STRM 生成开始（触发方式：{self._last_generate_trigger}）",
                extra={
                    "trigger": self._last_generate_trigger,
                    "output_dir": str(output_dir),
                },
            )

            try:
                summary = await self._generate(
                    output_cid=output_cid,
                    output_dir=output_dir,
                    mode=mode,
                    scopes=scopes,
                )
                while self._pending_mode:
                    queued_mode, queued_scopes = self._take_pending()
                    queued_summary = await self._generate(
                        output_cid=output_cid,
                        output_dir=output_dir,
                        mode=queued_mode,
                        scopes=queued_scopes,
                    )
                    summary["queued_runs"] = summary.get("queued_runs", 0) + 1
                    for key in ("scanned_video_count", "written_count", "removed_count"):
                        summary[key] = summary.get(key, 0) + queued_summary.get(key, 0)
                    summary["generated_file_count"] = queued_summary.get(
                        "generated_file_count", summary.get("generated_file_count", 0)
                    )
                    summary["refresh_results"] = queued_summary.get(
                        "refresh_results", {}
                    )
                self._last_generate_summary = summary
                self._last_generate_finished_at = self._now_iso()
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="strm",
                    action="strm.generate.success",
                    status="success",
                    message=(
                        f"STRM 生成完成：扫描 {summary['scanned_video_count']} 个视频，"
                        f"写入 {summary['written_count']} 个，删除 {summary['removed_count']} 个"
                    ),
                    extra=summary,
                )
                return {"success": True, **summary}
            except Exception as exc:
                self._last_generate_finished_at = self._now_iso()
                self._last_generate_error = str(exc)[:2000]
                await self._mark_state_failed(
                    output_cid=output_cid,
                    output_dir=output_dir,
                    mode=mode,
                    error=exc,
                )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="strm",
                    action="strm.generate.failed",
                    status="failed",
                    message=f"STRM 生成失败：{str(exc)[:200]}",
                    extra={
                        "trigger": self._last_generate_trigger,
                        "error": str(exc)[:500],
                    },
                )
                raise

    def _prepare_generate(self) -> tuple[str, Path]:
        output_cid = runtime_settings_service.get_archive_output_cid()
        if not output_cid:
            raise ValueError("请先在归档刮削中配置 115 输出目录")

        output_dir = self._resolve_output_dir(
            runtime_settings_service.get_strm_output_dir()
        )
        if not runtime_settings_service.get_strm_base_url():
            raise ValueError("请先配置 STRM 播放根地址")
        return output_cid, output_dir

    @staticmethod
    def _validate_mode(mode: str) -> str:
        normalized = str(mode or "incremental").strip().lower()
        if normalized not in {"incremental", "full"}:
            raise ValueError("STRM 生成模式必须是 incremental 或 full")
        return normalized

    @classmethod
    def _normalize_scopes(
        cls, scopes: list[dict[str, Any]] | None
    ) -> list[dict[str, str]]:
        normalized: dict[tuple[str, str, str], dict[str, str]] = {}
        for raw in scopes or []:
            if not isinstance(raw, dict):
                continue
            scope = {
                "fid": str(raw.get("fid") or raw.get("source_fid") or "").strip(),
                "target_cid": str(raw.get("target_cid") or "").strip(),
                "relative_prefix": cls._normalize_prefix(
                    str(raw.get("relative_prefix") or "")
                ),
            }
            if not scope["fid"] and not scope["target_cid"]:
                continue
            key = (scope["fid"], scope["target_cid"], scope["relative_prefix"])
            normalized[key] = scope
        return list(normalized.values())

    @staticmethod
    def _normalize_prefix(value: str) -> str:
        parts = [
            part.replace("\\", "_").replace("/", "_").strip() or "_"
            for part in PurePosixPath(str(value or "").strip().strip("/")).parts
            if part not in {"", ".", ".."}
        ]
        return PurePosixPath(*parts).as_posix() if parts else ""

    def _merge_pending_scopes(
        self, scopes: list[dict[str, str]], *, unscoped: bool = False
    ) -> None:
        self._pending_mode = "incremental"
        self._pending_unscoped = self._pending_unscoped or unscoped
        merged = {
            (item["fid"], item["target_cid"], item["relative_prefix"]): item
            for item in (*self._pending_scopes, *scopes)
        }
        self._pending_scopes = list(merged.values())

    def _take_pending(self) -> tuple[str, list[dict[str, str]]]:
        mode = self._pending_mode or "incremental"
        scopes = [] if self._pending_unscoped else self._pending_scopes
        self._pending_mode = None
        self._pending_scopes = []
        self._pending_unscoped = False
        return mode, scopes

    def _is_generate_running(self) -> bool:
        return bool(self._generate_task and not self._generate_task.done())

    def _clear_generate_task(self, task: asyncio.Task[dict[str, Any]]) -> None:
        if self._generate_task is task:
            self._generate_task = None
        try:
            task.result()
        except Exception:
            logger.exception("STRM 后台生成任务执行失败")
        if self._pending_mode and self._generate_task is None:
            try:
                mode, scopes = self._take_pending()
                output_cid, output_dir = self._prepare_generate()
                next_task = asyncio.create_task(
                    self._run_generate_task(
                        trigger="queued",
                        output_cid=output_cid,
                        output_dir=output_dir,
                        mode=mode,
                        scopes=scopes,
                    )
                )
                self._generate_task = next_task
                next_task.add_done_callback(self._clear_generate_task)
            except Exception:
                logger.exception("启动排队的 STRM 生成任务失败")

    async def diagnose_sample(
        self, request_headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        output_dir = self._resolve_output_dir(
            runtime_settings_service.get_strm_output_dir()
        )
        sample_path = self._pick_sample_strm_file(output_dir)
        if sample_path is None:
            raise ValueError("未找到可诊断的 STRM 文件，请先生成 STRM")

        sample_url = sample_path.read_text(encoding="utf-8").strip()
        if not sample_url:
            raise ValueError("样本 STRM 文件内容为空")

        token = self._extract_token_from_url(sample_url)
        payload = self._decode_token(token)
        pick_code = str(payload.get("pc") or "").strip()
        if not pick_code:
            raise ValueError("样本 STRM 链接不包含有效的播放令牌")

        player_user_agent = self._extract_request_user_agent(request_headers or {})
        raw_resp = await pan115_service._async_call(
            "download_url_app",
            {"pickcode": pick_code},
            app="chrome",
            user_agent=player_user_agent if player_user_agent is not None else "",
        )
        download_url = self._extract_download_url(raw_resp)
        if not download_url:
            raise ValueError("未能解析样本 STRM 对应的 115 下载地址")

        direct_requirement = self._get_direct_requirement(download_url)
        configured_mode = runtime_settings_service.get_strm_redirect_mode()
        effective_mode = configured_mode
        if configured_mode == "redirect" and direct_requirement == "3":
            effective_mode = "proxy"
        elif configured_mode == "auto":
            effective_mode = "proxy" if direct_requirement == "3" else "redirect"

        return {
            "sample_file": str(sample_path),
            "sample_url": sample_url,
            "pick_code": pick_code,
            "configured_mode": configured_mode,
            "effective_mode": effective_mode,
            "direct_requirement": direct_requirement or "none",
            "player_user_agent": player_user_agent or "",
            "bound_user_agent": (
                player_user_agent if player_user_agent is not None else ""
            ),
            "download_url": download_url,
            "required_headers": self._extract_download_headers(raw_resp),
            "direct_probe": await self._probe_direct_access(
                download_url, player_user_agent
            ),
            "reason": self._build_diagnose_reason(
                configured_mode=configured_mode,
                effective_mode=effective_mode,
                direct_requirement=direct_requirement,
            ),
            "note": "302 直链会绑定触发本次诊断请求的 User-Agent。实际播放器发起播放时，会重新绑定播放器自己的 User-Agent。",
        }

    async def resolve_play_response(self, token: str, method: str = "GET") -> Response:
        return await self.resolve_play_response_with_headers(
            token=token,
            method=method,
            request_headers=None,
        )

    async def resolve_play_response_with_headers(
        self,
        token: str,
        method: str = "GET",
        request_headers: dict[str, str] | None = None,
        *,
        client_ip: str = "",
        request_path: str = "",
        force_proxy: bool = False,
    ) -> Response:
        payload = self._decode_token(token)
        pick_code = str(payload.get("pc") or "").strip()
        if not pick_code:
            raise ValueError("无效的 STRM 播放令牌")

        player_user_agent = self._extract_request_user_agent(request_headers or {})

        try:
            download_info = await self._fetch_pick_code_download_info(
                pick_code,
                user_agent=player_user_agent if player_user_agent is not None else "",
                force_proxy=force_proxy,
            )
        except Exception as exc:
            logger.exception("STRM download_url_app failed for pick_code=%s", pick_code)
            raise ValueError(f"获取 115 下载地址失败: {exc}") from exc
        download_url = str(download_info.get("download_url") or "")
        if not download_url:
            raise ValueError("未能解析 115 下载地址")
        required_headers = dict(download_info.get("required_headers") or {})
        filename = str(download_info.get("filename") or f"{pick_code}.mp4")
        direct_requirement = str(download_info.get("direct_requirement") or "")
        mode = runtime_settings_service.get_strm_redirect_mode()
        if force_proxy:
            mode = "proxy"
        elif mode == "redirect" and direct_requirement == "3":
            mode = "proxy"
        elif mode == "auto":
            requires_proxy = direct_requirement == "3"
            mode = "proxy" if requires_proxy else "redirect"

        if mode == "redirect":
            if method == "GET":
                await self._log_strm_playback(
                    title=filename,
                    pick_code=pick_code,
                    player=player_user_agent or "",
                    client_ip=client_ip,
                    play_mode="redirect",
                    http_method=method,
                    path=request_path,
                )
            return RedirectResponse(url=download_url, status_code=302)
        if method == "GET":
            await self._log_strm_playback(
                title=filename,
                pick_code=pick_code,
                player=player_user_agent or "",
                client_ip=client_ip,
                play_mode="proxy",
                http_method=method,
                path=request_path,
            )
        return await self._build_proxy_response(
            method=method,
            download_url=download_url,
            filename=filename,
            required_headers=required_headers,
            request_headers=request_headers or {},
        )

    @staticmethod
    async def _log_strm_playback(
        *,
        title: str,
        pick_code: str,
        player: str,
        client_ip: str,
        play_mode: str,
        http_method: str,
        path: str,
    ) -> None:
        try:
            await playback_log_service.log_playback(
                source="strm_gateway",
                title=title,
                pick_code=pick_code,
                player=player,
                client_ip=client_ip,
                play_mode=play_mode,
                http_method=http_method,
                path=path,
            )
        except Exception:
            logger.exception("写入 STRM 播放日志失败")

    async def _generate(
        self,
        output_cid: str,
        output_dir: Path,
        mode: str = "incremental",
        scopes: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        await ensure_tables_exist(
            "strm_file_index", "strm_folder_index", "strm_sync_state"
        )
        existing_files, existing_folders, state = await self._load_index(output_cid)
        config_fingerprint = self._config_fingerprint()
        requested_mode = mode
        await self._mark_state_started(output_cid, output_dir, requested_mode)
        if not existing_files:
            mode = "full"

        config_only = (
            mode == "incremental"
            and not scopes
            and state is not None
            and state.config_fingerprint != config_fingerprint
            and bool(existing_files)
        )
        scan: dict[str, Any]
        if config_only:
            scan = {
                "files": [self._file_model_to_record(item) for item in existing_files],
                "folders": [],
                "complete_prefixes": [],
                "exact_fids": set(),
                "parent_cids": set(),
                "root_snapshot_hash": state.root_snapshot_hash,
                "source": "index_config_rewrite",
            }
        elif mode == "full":
            files, folders = await self._scan_tree(
                pan115_service, output_cid, "", parent_cid=""
            )
            root = next((item for item in folders if item["fid"] == output_cid), None)
            scan = {
                "files": files,
                "folders": folders,
                "complete_prefixes": [""],
                "exact_fids": set(),
                "parent_cids": set(),
                "root_snapshot_hash": root["snapshot_hash"] if root else "",
                "source": "full",
            }
        elif scopes:
            scan = await self._scan_scopes(pan115_service, scopes)
        else:
            scan = await self._scan_root_incremental(
                pan115_service,
                output_cid,
                existing_files,
                existing_folders,
                state,
            )
            if scan.get("fallback_full"):
                files, folders = await self._scan_tree(
                    pan115_service, output_cid, "", parent_cid=""
                )
                root = next(
                    (item for item in folders if item["fid"] == output_cid), None
                )
                mode = "full"
                scan = {
                    "files": files,
                    "folders": folders,
                    "complete_prefixes": [""],
                    "exact_fids": set(),
                    "parent_cids": set(),
                    "root_snapshot_hash": root["snapshot_hash"] if root else "",
                    "source": "full_fallback",
                }

        scanned_files = scan["files"]
        scanned_by_fid = {item["fid"]: item for item in scanned_files}
        scanned_paths: dict[str, str] = {}
        for item in scanned_files:
            relative_path = item["relative_path"]
            previous_fid = scanned_paths.get(relative_path)
            if previous_fid and previous_fid != item["fid"]:
                raise ValueError(
                    f"115 文件映射到重复 STRM 路径：{relative_path}"
                )
            scanned_paths[relative_path] = item["fid"]
        existing_by_fid = {item.fid: item for item in existing_files}
        stale_fids = self._select_stale_fids(
            existing_files=existing_files,
            scanned_fids=set(scanned_by_fid),
            complete_prefixes=scan["complete_prefixes"],
            exact_fids=scan["exact_fids"],
            parent_cids=scan["parent_cids"],
        )

        await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
        manifest_path = output_dir / MANIFEST_FILENAME
        previous_manifest_files = await self._load_manifest_files_async(
            manifest_path, expected_output_cid=output_cid
        )
        written_count = 0
        unchanged_count = 0
        removed_count = 0

        paths_to_remove: set[str] = set()
        for fid in stale_fids:
            old = existing_by_fid.get(fid)
            if old:
                paths_to_remove.add(self._strm_relative_path(old.relative_path))
        for item in scanned_files:
            old = existing_by_fid.get(item["fid"])
            if old and old.relative_path != item["relative_path"]:
                paths_to_remove.add(self._strm_relative_path(old.relative_path))

        for item in scanned_files:
            item["content_hash"] = self._record_content_hash(item)
            strm_relative = self._strm_relative_path(item["relative_path"])
            target_path = output_dir.joinpath(*PurePosixPath(strm_relative).parts)
            content = self.build_play_url(
                item["pick_code"], item.get("name") or item.get("relative_path") or ""
            ) + "\n"
            old = existing_by_fid.get(item["fid"])
            needs_write = (
                old is None
                or old.relative_path != item["relative_path"]
                or old.content_hash != item["content_hash"]
                or old.config_fingerprint != config_fingerprint
                or not await asyncio.to_thread(target_path.is_file)
            )
            if not needs_write:
                unchanged_count += 1
                continue
            await asyncio.to_thread(target_path.parent.mkdir, parents=True, exist_ok=True)
            if await asyncio.to_thread(target_path.is_file):
                try:
                    if (
                        await asyncio.to_thread(
                            target_path.read_text, encoding="utf-8"
                        )
                        == content
                    ):
                        unchanged_count += 1
                        continue
                except Exception:
                    pass
            await asyncio.to_thread(
                self._write_text_atomic, target_path, content
            )
            written_count += 1

        final_records = {
            item.fid: self._file_model_to_record(item)
            for item in existing_files
            if item.fid not in stale_fids
        }
        final_records.update(scanned_by_fid)
        generated_files = {
            self._strm_relative_path(item["relative_path"])
            for item in final_records.values()
        }
        await self._persist_index(
            output_cid=output_cid,
            scanned_files=scanned_files,
            scanned_folders=scan["folders"],
            stale_fids=stale_fids,
            complete_prefixes=scan["complete_prefixes"],
            config_fingerprint=config_fingerprint,
            root_snapshot_hash=scan.get("root_snapshot_hash")
            or (state.root_snapshot_hash if state else ""),
            mode=mode,
            file_count=len(final_records),
        )
        stale_paths = paths_to_remove - generated_files
        if mode == "full":
            stale_paths.update(previous_manifest_files - generated_files)
        for relative in sorted(stale_paths):
            if await self._remove_generated_file(output_dir, relative):
                removed_count += 1
        await asyncio.to_thread(self._cleanup_empty_dirs, output_dir)
        await self._save_manifest_async(manifest_path, generated_files, output_cid)

        refresh_results = (
            await self._refresh_media_servers()
            if written_count + removed_count > 0
            else {}
        )
        return {
            "trigger": self._last_generate_trigger,
            "requested_mode": requested_mode,
            "mode": mode,
            "scan_source": scan["source"],
            "output_cid": output_cid,
            "output_dir": str(output_dir),
            "scanned_video_count": len(scanned_files),
            "written_count": written_count,
            "unchanged_count": unchanged_count,
            "removed_count": removed_count,
            "generated_file_count": len(generated_files),
            "refresh_results": refresh_results,
        }

    async def _scan_tree(
        self,
        pan115: Pan115Service,
        cid: str,
        relative_prefix: str,
        parent_cid: str,
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        files: list[dict[str, str]] = []
        folders: list[dict[str, str]] = []

        async def _walk(
            folder_cid: str, prefix: str, folder_parent_cid: str
        ) -> None:
            items = await self._list_folder_items(pan115, folder_cid)
            folders.append(
                {
                    "fid": folder_cid,
                    "relative_path": prefix,
                    "parent_cid": folder_parent_cid,
                    "snapshot_hash": self._snapshot_hash(items, pan115),
                }
            )
            for item in items:
                name = self._extract_file_name(item)
                if not name:
                    continue
                relative_path = (
                    PurePosixPath(prefix, name).as_posix() if prefix else name
                )
                if pan115._is_folder_item(item):
                    child_cid = str(pan115._extract_folder_id(item) or "").strip()
                    if child_cid:
                        await _walk(child_cid, relative_path, folder_cid)
                    continue
                record = self._file_item_to_record(item, relative_path, folder_cid)
                if record:
                    files.append(record)

        await _walk(str(cid), self._normalize_prefix(relative_prefix), parent_cid)
        return files, folders

    async def _scan_video_files(
        self, pan115: Pan115Service, cid: str
    ) -> list[dict[str, str]]:
        """兼容旧调用方；新索引扫描使用扩展字段。"""
        files, _ = await self._scan_tree(pan115, cid, "", "")
        return files

    async def _scan_scopes(
        self, pan115: Pan115Service, scopes: list[dict[str, str]]
    ) -> dict[str, Any]:
        files: list[dict[str, str]] = []
        folders: list[dict[str, str]] = []
        complete_prefixes: set[str] = set()
        exact_fids: set[str] = set()
        parent_cids: set[str] = set()

        for scope in scopes:
            fid = scope["fid"]
            target_cid = scope["target_cid"]
            prefix = scope["relative_prefix"]
            handled = False
            if fid:
                try:
                    payload = await pan115.get_file_info(fid)
                    item = self._find_file_info_item(payload, fid)
                    if item:
                        handled = True
                        exact_fids.add(fid)
                        if pan115._is_folder_item(item):
                            tree_files, tree_folders = await self._scan_tree(
                                pan115, fid, prefix, target_cid
                            )
                            files.extend(tree_files)
                            folders.extend(tree_folders)
                            complete_prefixes.add(prefix)
                        else:
                            name = self._extract_file_name(item)
                            relative_path = (
                                PurePosixPath(prefix, name).as_posix()
                                if prefix and name
                                else (prefix or name)
                            )
                            record = self._file_item_to_record(
                                item, relative_path, target_cid
                            )
                            if record:
                                files.append(record)
                except Exception:
                    logger.warning(
                        "无法按 fid=%s 获取 STRM 增量范围，尝试目标目录", fid,
                        exc_info=True,
                    )
            if not handled and target_cid:
                tree_files, tree_folders = await self._scan_tree(
                    pan115, target_cid, prefix, ""
                )
                files.extend(tree_files)
                folders.extend(tree_folders)
                visible_fids = {item["fid"] for item in tree_files}
                if not fid or fid in visible_fids:
                    complete_prefixes.add(prefix)
                else:
                    logger.info(
                        "115 归档文件 fid=%s 尚未在目标目录可见，本轮仅增补、不执行范围删除",
                        fid,
                    )

        return {
            "files": self._dedupe_records(files),
            "folders": self._dedupe_records(folders),
            "complete_prefixes": sorted(complete_prefixes),
            "exact_fids": exact_fids,
            "parent_cids": parent_cids,
            "root_snapshot_hash": "",
            "source": "scopes",
        }

    async def _scan_root_incremental(
        self,
        pan115: Pan115Service,
        output_cid: str,
        existing_files: list[StrmFileIndex],
        existing_folders: list[StrmFolderIndex],
        state: StrmSyncState | None,
    ) -> dict[str, Any]:
        try:
            root_items = await self._list_folder_items(pan115, output_cid)
            root_hash = self._snapshot_hash(root_items, pan115)

            indexed_folders = {item.fid: item for item in existing_folders}
            old_top = {
                item.fid: item
                for item in existing_folders
                if item.parent_cid == output_cid
            }
            current_top: dict[str, tuple[dict[str, Any], str]] = {}
            direct_files: list[dict[str, str]] = []
            for item in root_items:
                name = self._extract_file_name(item)
                if not name:
                    continue
                if pan115._is_folder_item(item):
                    child_cid = str(pan115._extract_folder_id(item) or "").strip()
                    if child_cid:
                        current_top[child_cid] = (item, name)
                else:
                    record = self._file_item_to_record(item, name, output_cid)
                    if record:
                        direct_files.append(record)

            files = list(direct_files)
            folders: list[dict[str, str]] = [
                {
                    "fid": output_cid,
                    "relative_path": "",
                    "parent_cid": "",
                    "snapshot_hash": root_hash,
                }
            ]
            complete_prefixes: set[str] = set()
            list_cache: dict[str, list[dict[str, Any]]] = {}
            for child_cid, (_, name) in current_top.items():
                old = old_top.get(child_cid)
                changed = old is None or old.relative_path != name
                if not changed:
                    changed = await self._folder_tree_changed(
                        pan115, child_cid, indexed_folders, list_cache
                    )
                if changed:
                    tree_files, tree_folders = await self._scan_tree(
                        pan115, child_cid, name, output_cid
                    )
                    files.extend(tree_files)
                    folders.extend(tree_folders)
                    complete_prefixes.add(name)
                    if old and old.relative_path != name:
                        complete_prefixes.add(old.relative_path)

            for child_cid, old in old_top.items():
                if child_cid not in current_top:
                    complete_prefixes.add(old.relative_path)

            return {
                "files": self._dedupe_records(files),
                "folders": self._dedupe_records(folders),
                "complete_prefixes": sorted(complete_prefixes),
                "exact_fids": set(),
                "parent_cids": {output_cid},
                "root_snapshot_hash": root_hash,
                "source": "root_snapshot",
            }
        except Exception:
            logger.warning("根目录增量快照不完整，将回退完整扫描", exc_info=True)
            return {"fallback_full": True}

    async def _folder_tree_changed(
        self,
        pan115: Pan115Service,
        folder_cid: str,
        indexed_folders: dict[str, StrmFolderIndex],
        list_cache: dict[str, list[dict[str, Any]]],
    ) -> bool:
        items = list_cache.get(folder_cid)
        if items is None:
            items = await self._list_folder_items(pan115, folder_cid)
            list_cache[folder_cid] = items
        indexed = indexed_folders.get(folder_cid)
        if indexed is None or indexed.snapshot_hash != self._snapshot_hash(items, pan115):
            return True
        for item in items:
            if not pan115._is_folder_item(item):
                continue
            child_cid = str(pan115._extract_folder_id(item) or "").strip()
            if child_cid and await self._folder_tree_changed(
                pan115, child_cid, indexed_folders, list_cache
            ):
                return True
        return False

    @staticmethod
    async def _list_folder_items(
        pan115: Pan115Service, cid: str
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        offset = 0
        limit = 200
        while True:
            response = await pan115.get_file_list(
                cid=str(cid), offset=offset, limit=limit
            )
            if (
                isinstance(response, dict)
                and response.get("_normalized_list_valid") is False
            ):
                raise ValueError(f"115 目录 {cid} 返回了无法识别的列表结构")
            items = response.get("data") if isinstance(response, dict) else None
            if isinstance(items, dict):
                items = items.get("data") or items.get("list")
            if not isinstance(items, list):
                raise ValueError(f"115 目录 {cid} 返回了不完整的列表")
            valid_items = [item for item in items if isinstance(item, dict)]
            if len(valid_items) != len(items):
                raise ValueError(f"115 目录 {cid} 返回了不完整的条目")
            results.extend(valid_items)
            total_value = None
            if isinstance(response, dict):
                total_value = response.get("count", response.get("total"))
            try:
                total = int(total_value) if total_value is not None else None
            except (TypeError, ValueError):
                total = None
            if total is not None and offset + len(items) < total and len(items) < limit:
                raise ValueError(f"115 目录 {cid} 分页结果不完整")
            if len(items) < limit:
                break
            offset += len(items)
        return results

    @classmethod
    def _snapshot_hash(
        cls, items: list[dict[str, Any]], pan115: Pan115Service
    ) -> str:
        snapshot: list[dict[str, str]] = []
        for item in items:
            is_folder = pan115._is_folder_item(item)
            snapshot.append(
                {
                    "fid": (
                        str(pan115._extract_folder_id(item) or "").strip()
                        if is_folder
                        else cls._extract_file_id(item)
                    ),
                    "name": cls._extract_file_name(item),
                    "type": "folder" if is_folder else "file",
                    "pick_code": "" if is_folder else cls._extract_pick_code(item),
                    "sha1": "" if is_folder else cls._extract_optional(item, "sha1", "sha"),
                    "size": "" if is_folder else cls._extract_optional(item, "fs", "size"),
                }
            )
        body = json.dumps(
            sorted(snapshot, key=lambda value: (value["type"], value["fid"], value["name"])),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    @classmethod
    def _file_item_to_record(
        cls, item: dict[str, Any], relative_path: str, parent_cid: str
    ) -> dict[str, str] | None:
        name = cls._extract_file_name(item)
        fid = cls._extract_file_id(item)
        pick_code = cls._extract_pick_code(item)
        if not name or not fid or not pick_code or not cls._is_video_file(name):
            return None
        safe_path = cls._safe_relative_path(PurePosixPath(relative_path)).as_posix()
        return {
            "fid": fid,
            "name": name,
            "pick_code": pick_code,
            "pc": pick_code,
            "relative_path": safe_path,
            "parent_cid": str(parent_cid or ""),
            "sha1": cls._extract_optional(item, "sha1", "sha"),
            "utime": cls._extract_optional(
                item, "utime", "user_utime", "upt", "te"
            ),
        }

    @staticmethod
    def _extract_optional(item: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @classmethod
    def _find_file_info_item(
        cls, payload: Any, fid: str
    ) -> dict[str, Any] | None:
        if isinstance(payload, dict):
            if cls._extract_file_id(payload) == fid:
                return payload
            for value in payload.values():
                found = cls._find_file_info_item(value, fid)
                if found:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = cls._find_file_info_item(value, fid)
                if found:
                    return found
        return None

    @staticmethod
    def _dedupe_records(
        records: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        return list({item["fid"]: item for item in records if item.get("fid")}.values())

    @staticmethod
    def _record_content_hash(item: dict[str, str]) -> str:
        body = json.dumps(
            {
                "pick_code": item.get("pick_code", ""),
                "relative_path": item.get("relative_path", ""),
                "sha1": item.get("sha1", ""),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def _config_fingerprint(self) -> str:
        payload = {
            "base_url": runtime_settings_service.get_strm_base_url(),
            "output_dir": str(
                self._resolve_output_dir(
                    runtime_settings_service.get_strm_output_dir()
                )
            ),
            "proxy_enabled": runtime_settings_service.get_strm_proxy_enabled(),
            "proxy_port": runtime_settings_service.get_strm_proxy_port(),
            "token_secret": self._get_token_secret(),
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    @classmethod
    def _select_stale_fids(
        cls,
        existing_files: list[StrmFileIndex],
        scanned_fids: set[str],
        complete_prefixes: list[str],
        exact_fids: set[str],
        parent_cids: set[str],
    ) -> set[str]:
        stale: set[str] = set()
        for item in existing_files:
            covered = (
                item.fid in exact_fids
                or item.parent_cid in parent_cids
                or any(
                    cls._path_in_prefix(item.relative_path, prefix)
                    for prefix in complete_prefixes
                )
            )
            if covered and item.fid not in scanned_fids:
                stale.add(item.fid)
        return stale

    @staticmethod
    def _path_in_prefix(path: str, prefix: str) -> bool:
        normalized_path = str(path or "").strip("/")
        normalized_prefix = str(prefix or "").strip("/")
        return not normalized_prefix or normalized_path == normalized_prefix or (
            normalized_path.startswith(normalized_prefix + "/")
        )

    @classmethod
    def _strm_relative_path(cls, relative_path: str) -> str:
        return cls._safe_relative_path(PurePosixPath(relative_path)).with_suffix(
            ".strm"
        ).as_posix()

    @staticmethod
    async def _remove_generated_file(output_dir: Path, relative: str) -> bool:
        relative_path = PurePosixPath(str(relative or ""))
        if relative_path.is_absolute() or any(
            part in {"", ".", ".."} for part in relative_path.parts
        ):
            logger.warning("拒绝删除不安全的 STRM 相对路径：%s", relative)
            return False
        root = output_dir.resolve()
        target = output_dir.joinpath(*relative_path.parts).resolve()
        if not target.is_relative_to(root):
            logger.warning("拒绝删除 STRM 输出目录之外的路径：%s", target)
            return False
        if await asyncio.to_thread(target.is_file):
            await asyncio.to_thread(target.unlink)
            return True
        return False

    async def _load_index(
        self, output_cid: str
    ) -> tuple[list[StrmFileIndex], list[StrmFolderIndex], StrmSyncState | None]:
        async with async_session_maker() as session:
            files = list(
                (
                    await session.scalars(
                        select(StrmFileIndex).where(
                            StrmFileIndex.output_cid == output_cid
                        )
                    )
                ).all()
            )
            folders = list(
                (
                    await session.scalars(
                        select(StrmFolderIndex).where(
                            StrmFolderIndex.output_cid == output_cid
                        )
                    )
                ).all()
            )
            state = await session.get(StrmSyncState, output_cid)
            return files, folders, state

    async def _mark_state_started(
        self, output_cid: str, output_dir: Path, mode: str
    ) -> None:
        async with async_session_maker() as session:
            state = await session.get(StrmSyncState, output_cid)
            if state is None:
                state = StrmSyncState(output_cid=output_cid)
                session.add(state)
            state.output_dir = str(output_dir)
            state.last_mode = mode
            state.last_status = "running"
            state.last_error = None
            state.last_started_at = beijing_now()
            await session.commit()

    async def _mark_state_failed(
        self,
        *,
        output_cid: str,
        output_dir: Path,
        mode: str,
        error: Exception,
    ) -> None:
        try:
            async with async_session_maker() as session:
                state = await session.get(StrmSyncState, output_cid)
                if state is None:
                    state = StrmSyncState(output_cid=output_cid)
                    session.add(state)
                state.output_dir = str(output_dir)
                state.last_mode = mode
                state.last_status = "failed"
                state.last_error = str(error)[:2000]
                state.last_finished_at = beijing_now()
                await session.commit()
        except Exception:
            logger.warning("持久化 STRM 失败状态时出错", exc_info=True)

    @staticmethod
    def _file_model_to_record(item: StrmFileIndex) -> dict[str, str]:
        return {
            "fid": item.fid,
            "pick_code": item.pick_code,
            "pc": item.pick_code,
            "relative_path": item.relative_path,
            "parent_cid": item.parent_cid,
            "sha1": item.sha1 or "",
            "utime": item.utime or "",
            "content_hash": item.content_hash,
        }

    async def _persist_index(
        self,
        *,
        output_cid: str,
        scanned_files: list[dict[str, str]],
        scanned_folders: list[dict[str, str]],
        stale_fids: set[str],
        complete_prefixes: list[str],
        config_fingerprint: str,
        root_snapshot_hash: str,
        mode: str,
        file_count: int,
    ) -> None:
        async with async_session_maker() as session:
            if stale_fids:
                await session.execute(
                    delete(StrmFileIndex).where(
                        StrmFileIndex.output_cid == output_cid,
                        StrmFileIndex.fid.in_(stale_fids),
                    )
                )
            for item in scanned_files:
                model = await session.scalar(
                    select(StrmFileIndex).where(
                        StrmFileIndex.output_cid == output_cid,
                        StrmFileIndex.fid == item["fid"],
                    )
                )
                if model is None:
                    model = StrmFileIndex(output_cid=output_cid, fid=item["fid"])
                    session.add(model)
                model.pick_code = item["pick_code"]
                model.relative_path = item["relative_path"]
                model.parent_cid = item["parent_cid"]
                model.sha1 = item.get("sha1") or None
                model.utime = item.get("utime") or None
                model.content_hash = item["content_hash"]
                model.config_fingerprint = config_fingerprint

            if complete_prefixes:
                indexed_folders = list(
                    (
                        await session.scalars(
                            select(StrmFolderIndex).where(
                                StrmFolderIndex.output_cid == output_cid
                            )
                        )
                    ).all()
                )
                stale_folder_ids = [
                    item.id
                    for item in indexed_folders
                    if any(
                        self._path_in_prefix(item.relative_path, prefix)
                        for prefix in complete_prefixes
                    )
                ]
                if stale_folder_ids:
                    await session.execute(
                        delete(StrmFolderIndex).where(
                            StrmFolderIndex.id.in_(stale_folder_ids)
                        )
                    )
                    await session.flush()
            for item in scanned_folders:
                model = await session.scalar(
                    select(StrmFolderIndex).where(
                        StrmFolderIndex.output_cid == output_cid,
                        StrmFolderIndex.fid == item["fid"],
                    )
                )
                if model is None:
                    model = StrmFolderIndex(output_cid=output_cid, fid=item["fid"])
                    session.add(model)
                model.relative_path = item["relative_path"]
                model.parent_cid = item["parent_cid"]
                model.snapshot_hash = item["snapshot_hash"]

            await session.flush()
            folder_count = int(
                await session.scalar(
                    select(func.count(StrmFolderIndex.id)).where(
                        StrmFolderIndex.output_cid == output_cid
                    )
                )
                or 0
            )
            state = await session.get(StrmSyncState, output_cid)
            if state is None:
                state = StrmSyncState(output_cid=output_cid)
                session.add(state)
            state.config_fingerprint = config_fingerprint
            state.root_snapshot_hash = root_snapshot_hash
            state.output_dir = str(
                self._resolve_output_dir(
                    runtime_settings_service.get_strm_output_dir()
                )
            )
            state.last_mode = mode
            state.last_status = "success"
            state.last_error = None
            state.file_count = file_count
            state.folder_count = folder_count
            state.last_finished_at = beijing_now()
            if mode == "full":
                state.last_full_at = state.last_finished_at
            else:
                state.last_incremental_at = state.last_finished_at
            await session.commit()
        self._index_stats = {
            "output_cid": output_cid,
            "file_count": file_count,
            "folder_count": folder_count,
            "last_mode": mode,
            "last_status": "success",
            "last_incremental_at": (
                state.last_incremental_at.isoformat()
                if state.last_incremental_at
                else ""
            ),
            "last_full_at": state.last_full_at.isoformat() if state.last_full_at else "",
        }

    async def _refresh_media_servers(self) -> dict[str, Any]:
        results: dict[str, Any] = {}

        if runtime_settings_service.get_strm_refresh_emby_after_generate():
            try:
                await emby_service.refresh_library()
                results["emby"] = {"status": "ok", "message": "已触发 Emby 刷新"}
            except Exception as exc:
                results["emby"] = {"status": "failed", "message": str(exc)}

        if runtime_settings_service.get_strm_refresh_feiniu_after_generate():
            try:
                results["feiniu"] = await feiniu_service.refresh_library()
            except Exception as exc:
                results["feiniu"] = {"status": "failed", "message": str(exc)}

        return results

    async def _get_proxy_client(self) -> httpx.AsyncClient:
        """复用到 115 CDN 的长连接，避免每次 Range 重新握手。"""
        async with self._proxy_client_lock:
            if self._proxy_client is None or self._proxy_client.is_closed:
                self._proxy_client = httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=None,
                    limits=httpx.Limits(
                        max_connections=64,
                        max_keepalive_connections=32,
                        keepalive_expiry=120.0,
                    ),
                    http2=False,
                )
            return self._proxy_client

    async def _build_proxy_response(
        self,
        method: str,
        download_url: str,
        filename: str,
        required_headers: dict[str, str],
        request_headers: dict[str, str],
    ) -> Response:
        proxy_request_headers = {}
        for key, value in required_headers.items():
            try:
                value.encode("latin-1")
                proxy_request_headers[key] = value
            except UnicodeEncodeError:
                pass
        for key in ("range", "if-range"):
            forwarded_value = request_headers.get(key) or request_headers.get(
                key.title(), ""
            )
            if forwarded_value:
                proxy_request_headers[key] = forwarded_value
        # 透传播放器 UA，保持与申请直链时绑定的 UA 一致。
        incoming_ua = (
            request_headers.get("user-agent")
            or request_headers.get("User-Agent")
            or ""
        )
        if "user-agent" not in {k.lower() for k in proxy_request_headers}:
            proxy_request_headers["User-Agent"] = incoming_ua

        client = await self._get_proxy_client()
        try:
            upstream = await client.send(
                httpx.Request(
                    method.upper(),
                    download_url,
                    headers=proxy_request_headers,
                ),
                stream=True,
            )
        except Exception:
            raise

        response_headers = self._build_proxy_headers(upstream.headers, filename)
        media_type = (
            upstream.headers.get("content-type") or mimetypes.guess_type(filename)[0]
        )

        if method.upper() == "HEAD":
            await upstream.aclose()
            return Response(
                status_code=upstream.status_code,
                headers=response_headers,
                media_type=media_type,
            )

        return StreamingResponse(
            upstream.aiter_bytes(chunk_size=1024 * 256),
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=media_type,
            background=BackgroundTask(self._close_proxy_upstream, upstream),
        )

    @staticmethod
    async def _close_proxy_upstream(upstream: httpx.Response) -> None:
        await upstream.aclose()

    @staticmethod
    async def _close_proxy_resources(
        upstream: httpx.Response, client: httpx.AsyncClient
    ) -> None:
        try:
            await upstream.aclose()
        finally:
            await client.aclose()

    @staticmethod
    def _build_proxy_headers(headers: httpx.Headers, filename: str) -> dict[str, str]:
        from urllib.parse import quote

        allowed = {
            "accept-ranges",
            "cache-control",
            "content-length",
            "content-range",
            "content-type",
            "etag",
            "last-modified",
        }
        response_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() in allowed and value
        }
        if "content-disposition" not in {key.lower() for key in response_headers}:
            ascii_filename = (
                "".join(
                    ch if 32 <= ord(ch) < 127 and ch not in {'"', "\\"} else "_"
                    for ch in filename
                ).strip()
                or "video"
            )
            quoted_filename = quote(filename, safe="")
            response_headers["Content-Disposition"] = (
                f'inline; filename="{ascii_filename}"; '
                f"filename*=UTF-8''{quoted_filename}"
            )
        return response_headers

    def _encode_token(self, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        encoded = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
        signature = hmac.new(
            self._get_token_secret().encode("utf-8"),
            encoded.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{encoded}.{signature}"

    async def resolve_download_url_with_ua(
        self, token: str, *, user_agent: str = ""
    ) -> dict[str, Any]:
        """按播放器 UA 解析 115 直链，供 Emby 代理做单跳 302。"""
        payload = self._decode_token(token)
        pick_code = str(payload.get("pc") or "").strip()
        if not pick_code:
            raise ValueError("无效的 STRM 播放令牌")

        download_info = await self._fetch_pick_code_download_info(
            pick_code, user_agent=str(user_agent or "")
        )
        download_url = str(download_info.get("download_url") or "")
        if not download_url:
            raise ValueError("未能解析 115 下载地址")
        direct_requirement = str(download_info.get("direct_requirement") or "")
        mode = runtime_settings_service.get_strm_redirect_mode()
        if mode == "redirect" and direct_requirement == "3":
            mode = "proxy"
        elif mode == "auto":
            mode = "proxy" if direct_requirement == "3" else "redirect"
        return {
            "download_url": download_url,
            "pick_code": pick_code,
            "direct_requirement": direct_requirement,
            "mode": mode,
            "required_headers": dict(download_info.get("required_headers") or {}),
        }

    async def _fetch_pick_code_download_info(
        self,
        pick_code: str,
        *,
        user_agent: str = "",
        force_proxy: bool = False,
    ) -> dict[str, Any]:
        """获取并缓存 115 下载信息，避免 ISO 等频繁 Range 请求反复换链。"""
        cache_key = f"{pick_code}\0{user_agent or ''}"
        now = time.monotonic()
        async with self._download_url_cache_lock:
            cached = self._download_url_cache.get(cache_key)
            if cached and cached[0] > now:
                info = dict(cached[1])
                if force_proxy:
                    info["force_proxy"] = True
                return info

        raw_resp = await pan115_service._async_call(
            "download_url_app",
            {"pickcode": pick_code},
            app="chrome",
            user_agent=user_agent,
        )
        download_url = self._extract_download_url(raw_resp)
        if not download_url:
            raise ValueError("未能解析 115 下载地址")
        info = {
            "download_url": download_url,
            "required_headers": self._extract_download_headers(raw_resp),
            "direct_requirement": self._get_direct_requirement(download_url) or "",
            "filename": self._extract_file_name(raw_resp, fallback=f"{pick_code}.mp4"),
            "force_proxy": force_proxy,
        }
        ttl = self._download_url_cache_ttl(download_url)
        async with self._download_url_cache_lock:
            if len(self._download_url_cache) >= DOWNLOAD_URL_CACHE_MAX_ITEMS:
                oldest_key = min(
                    self._download_url_cache.items(), key=lambda item: item[1][0]
                )[0]
                self._download_url_cache.pop(oldest_key, None)
            self._download_url_cache[cache_key] = (now + ttl, dict(info))
        return info

    @staticmethod
    def _download_url_cache_ttl(
        download_url: str,
        *,
        default: float = DOWNLOAD_URL_CACHE_DEFAULT_TTL_SECONDS,
    ) -> float:
        from urllib.parse import parse_qs, urlparse

        try:
            query = parse_qs(urlparse(download_url).query)
            values = query.get("t") or []
            if values:
                expires_at = int(values[0])
                remaining = expires_at - int(time.time()) - 120
                if remaining > 60:
                    return float(min(default, remaining))
        except Exception:
            pass
        return default

    def _decode_token(self, token: str) -> dict[str, Any]:
        encoded, _, signature = str(token or "").partition(".")
        if not encoded or not signature:
            raise ValueError("无效的 STRM 令牌")
        expected = hmac.new(
            self._get_token_secret().encode("utf-8"),
            encoded.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("STRM 令牌校验失败")

        padding = "=" * (-len(encoded) % 4)
        try:
            decoded = base64.urlsafe_b64decode(encoded + padding)
            payload = json.loads(decoded.decode("utf-8"))
        except Exception as exc:
            raise ValueError("无效的 STRM 令牌内容") from exc
        if not isinstance(payload, dict):
            raise ValueError("无效的 STRM 令牌内容")
        return payload

    @staticmethod
    def _extract_token_from_url(url: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(str(url or "").strip())
        token = parsed.path.rsplit("/", 1)[-1].strip()
        if not token:
            raise ValueError("样本 STRM 链接格式无效")
        return token

    async def _probe_direct_access(
        self, download_url: str, user_agent: str | None
    ) -> dict[str, Any]:
        headers = {}
        if user_agent is not None:
            headers["User-Agent"] = user_agent
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
                response = await client.head(download_url, headers=headers)
                return {
                    "status_code": response.status_code,
                    "content_length": response.headers.get("content-length", ""),
                    "final_url": str(response.url),
                    "ok": response.status_code < 400,
                }
        except Exception as exc:
            return {
                "status_code": 0,
                "content_length": "",
                "final_url": "",
                "ok": False,
                "error": str(exc),
            }

    @staticmethod
    def _build_diagnose_reason(
        configured_mode: str, effective_mode: str, direct_requirement: str
    ) -> str:
        if configured_mode == "proxy":
            return "当前配置固定使用服务器代理。"
        if configured_mode == "redirect":
            if effective_mode == "proxy":
                return "当前配置为 302 直链，但该 115 链接要求额外 Cookie（f=3），已自动回退到代理。"
            return "当前配置为 302 直链，系统会按本次请求的 User-Agent 绑定 115 直链。"
        if effective_mode == "proxy":
            return (
                "自动模式检测到该 115 链接要求额外 Cookie（f=3），因此切换到代理播放。"
            )
        if direct_requirement == "1":
            return "自动模式检测到该 115 链接需要绑定 User-Agent（f=1），但不要求额外 Cookie，因此可使用 302 直链。"
        return "自动模式判定该样本可直接使用 302 直链。"

    @staticmethod
    def _extract_file_name(item: Any, fallback: str = "") -> str:
        if isinstance(item, dict):
            for key in ("file_name", "name", "n", "fn"):
                value = str(item.get(key) or "").strip()
                if value:
                    return value
            for value in item.values():
                found = StrmService._extract_file_name(value)
                if found:
                    return found
        elif isinstance(item, list):
            for value in item:
                found = StrmService._extract_file_name(value)
                if found:
                    return found
        return fallback

    @staticmethod
    def _extract_file_id(item: dict[str, Any]) -> str:
        for key in ("fid", "file_id", "id"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _extract_pick_code(item: Any) -> str:
        if isinstance(item, dict):
            for key in ("pick_code", "pickcode", "pc"):
                value = str(item.get(key) or "").strip()
                if value:
                    return value
            for value in item.values():
                found = StrmService._extract_pick_code(value)
                if found:
                    return found
        elif isinstance(item, list):
            for value in item:
                found = StrmService._extract_pick_code(value)
                if found:
                    return found
        return ""

    @staticmethod
    def _extract_download_url(payload: Any) -> str:
        if isinstance(payload, str):
            normalized = payload.strip()
            if normalized.startswith(("http://", "https://")):
                return normalized
            return ""
        if isinstance(payload, dict):
            direct_keys = ("file_url", "url", "download_url")
            for key in direct_keys:
                value = payload.get(key)
                if isinstance(value, str) and value.strip().startswith(
                    ("http://", "https://")
                ):
                    return value.strip()
                if isinstance(value, dict):
                    found = StrmService._extract_download_url(value)
                    if found:
                        return found
            for value in payload.values():
                found = StrmService._extract_download_url(value)
                if found:
                    return found
        if isinstance(payload, list):
            for value in payload:
                found = StrmService._extract_download_url(value)
                if found:
                    return found
        return ""

    @staticmethod
    def _extract_download_headers(payload: Any) -> dict[str, str]:
        if isinstance(payload, dict):
            headers = payload.get("headers")
            if isinstance(headers, dict):
                result: dict[str, str] = {}
                for key, value in headers.items():
                    k = str(key).strip()
                    if not k:
                        continue
                    v = str(value) if value is not None else ""
                    if k.lower() == "user-agent":
                        result[k] = v
                    elif v.strip():
                        result[k] = v.strip()
                return result
            for value in payload.values():
                nested = StrmService._extract_download_headers(value)
                if nested:
                    return nested
        elif isinstance(payload, list):
            for value in payload:
                nested = StrmService._extract_download_headers(value)
                if nested:
                    return nested
        return {}

    @staticmethod
    def _get_direct_requirement(url: str) -> str:
        """解析 115 直链的 f 参数：1=绑定 UA，3=需要额外 Cookie"""
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        return params.get("f", [""])[0]

    @staticmethod
    def _extract_request_user_agent(request_headers: dict[str, str]) -> str | None:
        for key in ("user-agent", "User-Agent"):
            if key in request_headers:
                return str(request_headers.get(key) or "")
        return None

    @staticmethod
    def _is_video_file(filename: str) -> bool:
        return Path(filename).suffix.lower() in VIDEO_EXTENSIONS

    @staticmethod
    def _safe_relative_path(path: PurePosixPath) -> PurePosixPath:
        parts: list[str] = []
        for raw_part in path.parts:
            cleaned = raw_part.replace("/", "_").replace("\\", "_").strip()
            if cleaned in {"", ".", ".."}:
                cleaned = "_"
            parts.append(cleaned)
        return PurePosixPath(*parts)

    @staticmethod
    def _resolve_output_dir(raw_path: str) -> Path:
        normalized = str(raw_path or "").strip()
        if not normalized:
            raise ValueError("请先配置 STRM 输出目录")
        path = Path(normalized).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if path.exists() and not path.is_dir():
            raise ValueError("STRM 输出目录不能是文件")
        return path

    @staticmethod
    def _pick_sample_strm_file(output_dir: Path) -> Path | None:
        manifest_path = output_dir / MANIFEST_FILENAME
        manifest_files = StrmService._load_manifest_files(manifest_path)
        for relative in sorted(manifest_files):
            candidate = output_dir.joinpath(*PurePosixPath(relative).parts)
            if candidate.exists() and candidate.is_file():
                return candidate

        for candidate in sorted(output_dir.rglob("*.strm")):
            if candidate.is_file():
                return candidate
        return None

    def _get_token_secret(self) -> str:
        return (
            runtime_settings_service.get_strm_token_secret()
            or runtime_settings_service.get_auth_secret()
            or "mediasync115-strm"
        )

    @staticmethod
    def _load_manifest_files(
        manifest_path: Path, expected_output_cid: str | None = None
    ) -> set[str]:
        if not manifest_path.exists():
            return set()
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return set()
        if expected_output_cid is not None:
            manifest_cid = (
                str(payload.get("output_cid") or "").strip()
                if isinstance(payload, dict)
                else ""
            )
            if manifest_cid and manifest_cid != str(expected_output_cid).strip():
                logger.warning(
                    "STRM manifest 属于其他输出目录 cid=%s，本轮不据此删除文件",
                    manifest_cid,
                )
                return set()
        files = payload.get("generated_files") if isinstance(payload, dict) else None
        if not isinstance(files, list):
            return set()
        safe_files: set[str] = set()
        for item in files:
            value = str(item or "").strip()
            path = PurePosixPath(value)
            if (
                not value
                or path.is_absolute()
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                continue
            safe_files.add(path.as_posix())
        return safe_files

    @classmethod
    async def _load_manifest_files_async(
        cls, manifest_path: Path, expected_output_cid: str | None = None
    ) -> set[str]:
        return await asyncio.to_thread(
            cls._load_manifest_files, manifest_path, expected_output_cid
        )

    @staticmethod
    def _save_manifest(manifest_path: Path, files: set[str], output_cid: str) -> None:
        payload = {
            "output_cid": str(output_cid or "").strip(),
            "generated_files": sorted(files),
        }
        StrmService._write_text_atomic(
            manifest_path,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

    @staticmethod
    def _write_text_atomic(path: Path, content: str) -> None:
        """同目录写临时文件后原子替换，避免中途失败留下半文件。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temp_path.write_text(content, encoding="utf-8")
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    @classmethod
    async def _save_manifest_async(
        cls, manifest_path: Path, files: set[str], output_cid: str
    ) -> None:
        await asyncio.to_thread(cls._save_manifest, manifest_path, files, output_cid)

    @staticmethod
    def _cleanup_empty_dirs(root_dir: Path) -> None:
        if not root_dir.exists():
            return
        for path in sorted(
            root_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True
        ):
            if path.name == MANIFEST_FILENAME:
                continue
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    continue

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime

        return beijing_now().isoformat()


strm_service = StrmService()
