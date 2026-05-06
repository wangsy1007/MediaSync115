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
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from app.services.emby_service import emby_service
from app.services.feiniu_service import feiniu_service
from app.services.operation_log_service import operation_log_service
from app.services.pan115_service import Pan115Service, pan115_service
from app.services.runtime_settings_service import runtime_settings_service
from app.utils.proxy import proxy_manager

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
MANIFEST_FILENAME = ".mediasync115-strm-manifest.json"


class StrmService:
    """STRM 生成与播放服务"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._generate_task: asyncio.Task[dict[str, Any]] | None = None
        self._last_generate_started_at: str = ""
        self._last_generate_finished_at: str = ""
        self._last_generate_error: str = ""
        self._last_generate_summary: dict[str, Any] | None = None
        self._last_generate_trigger: str = ""

    def get_runtime_status(self) -> dict[str, Any]:
        generate_running = bool(self._generate_task and not self._generate_task.done())
        return {
            "generate_running": generate_running or self._lock.locked(),
            "last_generate_started_at": self._last_generate_started_at,
            "last_generate_finished_at": self._last_generate_finished_at,
            "last_generate_error": self._last_generate_error,
            "last_generate_summary": self._last_generate_summary,
            "last_generate_trigger": self._last_generate_trigger,
        }

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

    def build_play_url(self, pick_code: str) -> str:
        base_url = runtime_settings_service.get_strm_base_url()
        if not base_url:
            raise ValueError("STRM 播放地址未配置")
        # 如果启用了 Emby 代理，STRM 文件使用代理端口，所有 Emby 播放经过代理
        if runtime_settings_service.get_strm_proxy_enabled():
            proxy_port = runtime_settings_service.get_strm_proxy_port()
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            base_url = f"{parsed.scheme}://{parsed.hostname}:{proxy_port}"
        token = self._encode_token({"pc": str(pick_code or "").strip()})
        return f"{base_url}/api/strm/play/{token}"

    async def start_generate_library(self, trigger: str = "manual") -> dict[str, Any]:
        if self._is_generate_running():
            raise ValueError("STRM 生成任务正在执行中，请稍后再试")

        output_cid, output_dir = self._prepare_generate()
        task = asyncio.create_task(
            self._run_generate_task(
                trigger=str(trigger or "manual"),
                output_cid=output_cid,
                output_dir=output_dir,
            )
        )
        self._generate_task = task
        task.add_done_callback(self._clear_generate_task)
        return {
            "success": True,
            "started": True,
            "trigger": str(trigger or "manual"),
            "output_cid": output_cid,
            "output_dir": str(output_dir),
        }

    async def generate_library(self, trigger: str = "manual") -> dict[str, Any]:
        if self._is_generate_running() and not self._lock.locked():
            raise ValueError("STRM 生成任务正在执行中，请稍后再试")

        output_cid, output_dir = self._prepare_generate()

        return await self._run_generate_task(
            trigger=str(trigger or "manual"),
            output_cid=output_cid,
            output_dir=output_dir,
        )

    async def _run_generate_task(
        self, trigger: str, output_cid: str, output_dir: Path
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
                    output_cid=output_cid, output_dir=output_dir
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

    def _is_generate_running(self) -> bool:
        return bool(self._generate_task and not self._generate_task.done())

    def _clear_generate_task(self, task: asyncio.Task[dict[str, Any]]) -> None:
        if self._generate_task is task:
            self._generate_task = None
        try:
            task.result()
        except Exception:
            logger.exception("STRM 后台生成任务执行失败")

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
    ) -> Response:
        payload = self._decode_token(token)
        pick_code = str(payload.get("pc") or "").strip()
        if not pick_code:
            raise ValueError("无效的 STRM 播放令牌")

        player_user_agent = self._extract_request_user_agent(request_headers or {})

        try:
            raw_resp = await pan115_service._async_call(
                "download_url_app",
                {"pickcode": pick_code},
                app="chrome",
                user_agent=player_user_agent if player_user_agent is not None else "",
            )
        except Exception as exc:
            logger.exception("STRM download_url_app failed for pick_code=%s", pick_code)
            raise ValueError(f"获取 115 下载地址失败: {exc}") from exc
        download_url = self._extract_download_url(raw_resp)
        if not download_url:
            raise ValueError("未能解析 115 下载地址")
        required_headers = self._extract_download_headers(raw_resp)
        filename = self._extract_file_name(raw_resp, fallback=f"{pick_code}.mp4")
        direct_requirement = self._get_direct_requirement(download_url)
        mode = runtime_settings_service.get_strm_redirect_mode()
        if mode == "redirect" and direct_requirement == "3":
            mode = "proxy"
        elif mode == "auto":
            requires_proxy = direct_requirement == "3"
            mode = "proxy" if requires_proxy else "redirect"

        if mode == "redirect":
            return RedirectResponse(url=download_url, status_code=302)
        return await self._build_proxy_response(
            method=method,
            download_url=download_url,
            filename=filename,
            required_headers=required_headers,
            request_headers=request_headers or {},
        )

    async def _generate(self, output_cid: str, output_dir: Path) -> dict[str, Any]:
        scanned_files = await self._scan_video_files(
            pan115=pan115_service, cid=output_cid
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / MANIFEST_FILENAME
        previous_files = self._load_manifest_files(manifest_path)

        generated_files: set[str] = set()
        written_count = 0
        unchanged_count = 0

        for item in scanned_files:
            relative_video_path = PurePosixPath(item["relative_path"])
            safe_relative_path = self._safe_relative_path(relative_video_path)
            strm_relative_path = safe_relative_path.with_suffix(".strm")
            generated_files.add(strm_relative_path.as_posix())

            target_path = output_dir.joinpath(*strm_relative_path.parts)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            content = self.build_play_url(item["pc"]) + "\n"

            if target_path.exists():
                try:
                    if target_path.read_text(encoding="utf-8") == content:
                        unchanged_count += 1
                        continue
                except Exception:
                    pass

            target_path.write_text(content, encoding="utf-8")
            written_count += 1

        removed_count = 0
        stale_files = previous_files - generated_files
        for relative in stale_files:
            stale_path = output_dir.joinpath(*PurePosixPath(relative).parts)
            if stale_path.exists() and stale_path.is_file():
                stale_path.unlink()
                removed_count += 1

        self._cleanup_empty_dirs(output_dir)
        self._save_manifest(manifest_path, generated_files, output_cid)

        refresh_results = await self._refresh_media_servers()
        return {
            "trigger": self._last_generate_trigger,
            "output_cid": output_cid,
            "output_dir": str(output_dir),
            "scanned_video_count": len(scanned_files),
            "written_count": written_count,
            "unchanged_count": unchanged_count,
            "removed_count": removed_count,
            "generated_file_count": len(generated_files),
            "refresh_results": refresh_results,
        }

    async def _scan_video_files(
        self, pan115: Pan115Service, cid: str
    ) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []

        async def _walk(folder_cid: str, parent_parts: tuple[str, ...]) -> None:
            offset = 0
            limit = 200
            while True:
                response = await pan115.get_file_list(
                    cid=folder_cid, offset=offset, limit=limit
                )
                items = response.get("data") or []
                if not isinstance(items, list) or not items:
                    break

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = self._extract_file_name(item)
                    if not name:
                        continue
                    if pan115._is_folder_item(item):
                        child_cid = str(pan115._extract_folder_id(item) or "").strip()
                        if child_cid:
                            await _walk(child_cid, (*parent_parts, name))
                        continue

                    if not self._is_video_file(name):
                        continue
                    pick_code = self._extract_pick_code(item)
                    if not pick_code:
                        continue
                    relative_path = PurePosixPath(*parent_parts, name).as_posix()
                    results.append({"pc": pick_code, "relative_path": relative_path})

                if len(items) < limit:
                    break
                offset += len(items)

        await _walk(str(cid or "0"), tuple())
        return results

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
        if "user-agent" not in {k.lower() for k in proxy_request_headers}:
            proxy_request_headers["User-Agent"] = ""
        client = httpx.AsyncClient(follow_redirects=True, timeout=None)
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
            await client.aclose()
            raise

        response_headers = self._build_proxy_headers(upstream.headers, filename)
        media_type = (
            upstream.headers.get("content-type") or mimetypes.guess_type(filename)[0]
        )

        if method.upper() == "HEAD":
            await upstream.aclose()
            await client.aclose()
            return Response(
                status_code=upstream.status_code,
                headers=response_headers,
                media_type=media_type,
            )

        return StreamingResponse(
            upstream.aiter_bytes(),
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=media_type,
            background=BackgroundTask(self._close_proxy_resources, upstream, client),
        )

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
            parts.append(cleaned or "_")
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
    def _load_manifest_files(manifest_path: Path) -> set[str]:
        if not manifest_path.exists():
            return set()
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return set()
        files = payload.get("generated_files") if isinstance(payload, dict) else None
        if not isinstance(files, list):
            return set()
        return {str(item).strip() for item in files if str(item).strip()}

    @staticmethod
    def _save_manifest(manifest_path: Path, files: set[str], output_cid: str) -> None:
        payload = {
            "output_cid": str(output_cid or "").strip(),
            "generated_files": sorted(files),
        }
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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

        return datetime.utcnow().isoformat()


strm_service = StrmService()
