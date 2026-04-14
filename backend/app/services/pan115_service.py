"""
115网盘服务模块 - 基于p115client实现
提供115网盘的文件管理、离线下载、分享链接转存等功能
"""

import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Set
from uuid import uuid4

from app.core.config import settings

P115Client = None
_P115CLIENT_IMPORT_ERROR = ""


def _load_p115client() -> None:
    global P115Client
    global _P115CLIENT_IMPORT_ERROR
    if P115Client is not None:
        return
    if _P115CLIENT_IMPORT_ERROR:
        raise RuntimeError(f"p115client 未安装或加载失败: {_P115CLIENT_IMPORT_ERROR}")
    try:
        from p115client import P115Client as p115_client_cls
        from p115client import check_response as p115_check_response
        from p115client.util import share_extract_payload as p115_share_extract_payload
    except Exception as exc:  # pragma: no cover - runtime fallback
        _P115CLIENT_IMPORT_ERROR = str(exc)
        raise RuntimeError(
            f"p115client 未安装或加载失败: {_P115CLIENT_IMPORT_ERROR}"
        ) from exc

    P115Client = p115_client_cls
    globals()["check_response"] = p115_check_response
    globals()["share_extract_payload"] = p115_share_extract_payload


def check_response(result: Any) -> Any:
    _load_p115client()
    return globals()["check_response"](result)


def share_extract_payload(url: str) -> Any:
    _load_p115client()
    return globals()["share_extract_payload"](url)


def _get_p115_client_cls() -> Any:
    _load_p115client()
    return P115Client


# ==================== 全局请求队列 + 三层限速 + 熔断器 ====================

from collections import deque
from dataclasses import dataclass
import time


@dataclass
class _QueueRequest:
    """队列请求包装器"""

    coro_factory: Any
    future: asyncio.Future[Any]
    bypass_rate_limit: bool = False


class _Pan115ThrottleManager:
    """全局熔断管理器：一旦检测到 405 / 限流，进入冷却期"""

    def __init__(self, cooldown_seconds: float = 30.0):
        self._cooldown_seconds = cooldown_seconds
        self._throttled_until: float = 0.0
        self._lock = asyncio.Lock()

    async def mark_throttled(self) -> None:
        now = time.monotonic()
        async with self._lock:
            new_until = now + self._cooldown_seconds
            if new_until > self._throttled_until:
                self._throttled_until = new_until

    async def wait_if_throttled(self) -> None:
        while True:
            now = time.monotonic()
            async with self._lock:
                remaining = self._throttled_until - now
            if remaining <= 0:
                break
            await asyncio.sleep(min(remaining, 1.0))

    def is_throttled(self) -> bool:
        return time.monotonic() < self._throttled_until


class _Pan115RateLimiter:
    """三层滑动窗口限速器：QPS / QPM / QPH"""

    def __init__(self, qps: int = 3, qpm: int = 200, qph: int = 12000):
        self.qps = max(qps, 1)
        self.qpm = max(qpm, 1)
        self.qph = max(qph, 1)
        self._second_window: deque[float] = deque()
        self._minute_window: deque[float] = deque()
        self._hour_window: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            now = time.monotonic()
            async with self._lock:
                cutoff_sec = now - 1.0
                cutoff_min = now - 60.0
                cutoff_hour = now - 3600.0
                while self._second_window and self._second_window[0] <= cutoff_sec:
                    self._second_window.popleft()
                while self._minute_window and self._minute_window[0] <= cutoff_min:
                    self._minute_window.popleft()
                while self._hour_window and self._hour_window[0] <= cutoff_hour:
                    self._hour_window.popleft()

                if (
                    len(self._second_window) < self.qps
                    and len(self._minute_window) < self.qpm
                    and len(self._hour_window) < self.qph
                ):
                    self._second_window.append(now)
                    self._minute_window.append(now)
                    self._hour_window.append(now)
                    return

            async with self._lock:
                sleep_sec = 0.0
                if len(self._second_window) >= self.qps and self._second_window:
                    sleep_sec = max(sleep_sec, self._second_window[0] + 1.01 - now)
                if len(self._minute_window) >= self.qpm and self._minute_window:
                    sleep_sec = max(sleep_sec, self._minute_window[0] + 60.01 - now)
                if len(self._hour_window) >= self.qph and self._hour_window:
                    sleep_sec = max(sleep_sec, self._hour_window[0] + 3600.01 - now)

            if sleep_sec > 0:
                await asyncio.sleep(sleep_sec)


class _Pan115QueueExecutor:
    """115 API 全局队列执行器"""

    def __init__(
        self, qps: int = 3, qpm: int = 200, qph: int = 12000, worker_count: int = 3
    ):
        self._queue: asyncio.Queue[_QueueRequest] = asyncio.Queue(maxsize=500)
        self._limiter = _Pan115RateLimiter(qps, qpm, qph)
        self._throttle = _Pan115ThrottleManager()
        self._worker_count = max(worker_count, 2)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for i in range(self._worker_count):
            asyncio.create_task(self._worker_loop(), name=f"pan115-queue-worker-{i}")

    async def _worker_loop(self) -> None:
        while True:
            req = await self._queue.get()
            try:
                if not req.bypass_rate_limit:
                    await self._limiter.acquire()
                    await self._throttle.wait_if_throttled()

                result = await req.coro_factory()
                if not req.future.done():
                    req.future.set_result(result)
            except Exception as exc:
                error_text = str(exc).lower()
                if (
                    "code=405" in error_text
                    or "method not allowed" in error_text
                    or "访问频率过高" in error_text
                    or "too many" in error_text
                    or "rate limit" in error_text
                ):
                    await self._throttle.mark_throttled()
                if not req.future.done():
                    req.future.set_exception(exc)
            finally:
                self._queue.task_done()

    def enqueue(self, req: _QueueRequest) -> None:
        if not self._started:
            self.start()
        try:
            self._queue.put_nowait(req)
        except asyncio.QueueFull:
            if not req.future.done():
                req.future.set_exception(RuntimeError("115 请求队列已满，请稍后重试"))


_global_pan115_executor: Optional[_Pan115QueueExecutor] = None
_global_executor_lock = asyncio.Lock()


async def _get_global_pan115_executor() -> _Pan115QueueExecutor:
    global _global_pan115_executor
    if _global_pan115_executor is not None:
        return _global_pan115_executor
    async with _global_executor_lock:
        if _global_pan115_executor is not None:
            return _global_pan115_executor
        _global_pan115_executor = _Pan115QueueExecutor(
            qps=3, qpm=200, qph=12000, worker_count=3
        )
        _global_pan115_executor.start()
        return _global_pan115_executor


class Pan115Service:
    """115网盘服务类，封装p115client的功能"""

    _QR_LOGIN_EXPIRE_SECONDS = 180
    _QR_LOGIN_PENDING: dict[str, dict[str, Any]] = {}
    _QR_LOGIN_LOCK = asyncio.Lock()
    _QR_LOGIN_ALLOWED_APPS = {
        "web",
        "desktop",
        "bios",
        "ios",
        "115ios",
        "bandroid",
        "android",
        "115android",
        "bipad",
        "ipad",
        "115ipad",
        "tv",
        "apple_tv",
        "qandriod",
        "qios",
        "qipad",
        "wechatmini",
        "alipaymini",
        "harmony",
        "os_windows",
        "os_mac",
        "os_linux",
    }

    def __init__(self, cookie: Optional[str] = None):
        """
        初始化115网盘客户端

        Args:
            cookie: 115网盘cookie字符串，如未提供则使用配置文件中的cookie
        """
        self.cookie = cookie or settings.PAN115_COOKIE or ""
        self._client: Optional[Any] = None

    @property
    def client(self) -> Any:
        """获取或创建p115client实例"""
        if self._client is None:
            if not self.cookie:
                raise ValueError("115网盘Cookie未配置，请在设置中更新Cookie")
            self._client = _get_p115_client_cls()(self.cookie)
        return self._client

    async def _async_call(self, method_name: str, *args, **kwargs) -> Dict[str, Any]:
        """
        异步调用p115client方法（经过全局队列限速）

        Args:
            method_name: 方法名称
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            API响应字典
        """
        method = getattr(self.client, method_name)
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        async def coro_factory():
            return await method(*args, async_=True, **kwargs)

        executor = await _get_global_pan115_executor()
        executor.enqueue(_QueueRequest(coro_factory=coro_factory, future=future))
        return await future

    # ==================== 用户信息 ====================

    async def get_user_info(self) -> Dict[str, Any]:
        """
        获取用户信息

        Returns:
            用户信息字典，包含用户名、空间使用情况等
        """
        result = await self._async_call("user_info")
        return check_response(result)

    async def get_user_space_info(self) -> Dict[str, Any]:
        """
        获取用户空间使用情况

        Returns:
            空间使用信息字典
        """
        result = await self._async_call("fs_index_info")
        return check_response(result)

    @staticmethod
    def _pick_first_int(source: Any, *keys: str) -> int | None:
        if not isinstance(source, dict):
            return None
        for key in keys:
            value = source.get(key)
            if value is None or value == "":
                continue
            try:
                return int(str(value))
            except Exception:
                continue
        return None

    def _normalize_offline_quota_info(self, payload: Any) -> Dict[str, Any]:
        data = payload if isinstance(payload, dict) else {}
        nested = data.get("data") if isinstance(data.get("data"), dict) else {}

        total_quota = (
            self._pick_first_int(nested, "count", "quota", "total", "package_count")
            if nested
            else None
        )
        if total_quota is None:
            total_quota = self._pick_first_int(
                data, "count", "quota", "total", "package_count"
            )

        used_quota = (
            self._pick_first_int(nested, "used", "use", "used_count")
            if nested
            else None
        )
        if used_quota is None:
            used_quota = self._pick_first_int(data, "used", "use", "used_count")

        remaining_quota = (
            self._pick_first_int(nested, "remaining", "remain", "left", "surplus")
            if nested
            else None
        )
        if remaining_quota is None:
            remaining_quota = self._pick_first_int(
                data, "remaining", "remain", "left", "surplus"
            )

        if (
            remaining_quota is None
            and total_quota is not None
            and used_quota is not None
        ):
            remaining_quota = max(total_quota - used_quota, 0)

        return {
            "total_quota": total_quota,
            "used_quota": used_quota,
            "remaining_quota": remaining_quota,
        }

    async def get_offline_quota_info(self) -> Dict[str, Any]:
        """
        获取离线下载配额信息

        Returns:
            配额信息，包含总配额、已用配额、剩余配额
        """
        attempts = (
            ("offline_quota_package_info", {}),
            ("offline_quota_info", {}),
            ("offline_quota_info_open", {}),
        )

        last_error: Exception | None = None
        for method_name, kwargs in attempts:
            try:
                result = await self._async_call(method_name, **kwargs)
                data = check_response(result)
                return self._normalize_offline_quota_info(data)
            except Exception as exc:
                last_error = exc
                continue

        raise last_error or RuntimeError("获取离线下载配额失败")

    async def check_offline_quota_valid(self) -> Dict[str, Any]:
        """
        检查离线下载配额接口是否可用

        Returns:
            包含有效状态和配额信息的字典
        """
        try:
            quota_info = await self.get_offline_quota_info()
            return {
                "valid": True,
                "quota_info": quota_info,
                "message": "离线下载配额获取成功",
            }
        except Exception as e:
            message = str(e)
            if "重新登录" in message:
                message = "离线下载接口要求重新登录，请重新扫码登录 115 后再查看配额"
            return {
                "valid": False,
                "quota_info": None,
                "message": message,
            }

    # ==================== 文件操作 ====================

    async def get_file_list(
        self,
        cid: str = "0",
        offset: int = 0,
        limit: int = 50,
        asc: int = 1,
        o: str = "user_ptime",
    ) -> Dict[str, Any]:
        """
        获取文件列表

        Args:
            cid: 目录ID，根目录为"0"
            offset: 偏移量
            limit: 返回数量限制
            asc: 排序方式，1为升序，0为降序
            o: 排序字段

        Returns:
            文件列表信息
        """
        payload = {"cid": cid, "offset": offset, "limit": limit, "asc": asc, "o": o}
        attempts = (
            ("fs_files", {"base_url": "https://webapi.115.com"}),
            ("fs_files", {}),
            ("fs_files_app", {"app": "android"}),
        )

        last_error: Exception | None = None
        for method_name, extra_kwargs in attempts:
            for retry in range(3):
                try:
                    result = await self._async_call(
                        method_name, payload, **extra_kwargs
                    )
                    data = check_response(result)
                    return self._normalize_file_list_result(data)
                except Exception as exc:
                    last_error = exc
                    error_text = str(exc)
                    # 凭证失效时不再回退，直接抛给上层进行鉴权提示
                    if self._is_auth_related_error(error_text):
                        raise
                    # 文件列表接口短时 405 通常属于风控，交由全局队列熔断处理
                    if self._is_method_not_allowed_error(error_text) and retry < 2:
                        continue
                    break

        raise last_error or Exception("获取文件列表失败")

    async def create_folder(self, pid: str, name: str) -> Dict[str, Any]:
        """
        创建文件夹

        Args:
            pid: 父目录ID
            name: 文件夹名称

        Returns:
            创建结果（包含错误信息的原始响应，不抛出异常）
        """
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                result = await self._async_call("fs_mkdir", {"pid": pid, "cname": name})
                return (
                    result
                    if isinstance(result, dict)
                    else {"state": False, "error": "Invalid response"}
                )
            except Exception as exc:
                last_error = exc
                if self._is_method_not_allowed_error(str(exc)) and attempt < 2:
                    continue
                raise

        raise last_error or Exception("创建文件夹失败")

    async def delete_file(self, fid: List[str]) -> Dict[str, Any]:
        """
        删除文件/文件夹

        Args:
            fid: 文件ID列表

        Returns:
            删除结果
        """
        if isinstance(fid, str):
            fid = [fid]
        result = await self._async_call("fs_delete", {"fid": ",".join(fid)})
        return check_response(result)

    async def copy_file(self, fid: List[str], pid: str) -> Dict[str, Any]:
        """
        复制文件

        Args:
            fid: 源文件ID列表
            pid: 目标目录ID

        Returns:
            复制结果
        """
        if isinstance(fid, str):
            fid = [fid]
        result = await self._async_call("fs_copy", {"fid": ",".join(fid), "pid": pid})
        return check_response(result)

    async def move_file(self, fid: List[str], pid: str) -> Dict[str, Any]:
        """
        移动文件

        Args:
            fid: 源文件ID列表
            pid: 目标目录ID

        Returns:
            移动结果
        """
        if isinstance(fid, str):
            fid = [fid]
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                result = await self._async_call(
                    "fs_move", {"fid": ",".join(fid), "pid": pid}
                )
                return check_response(result)
            except Exception as exc:
                last_error = exc
                if self._is_method_not_allowed_error(str(exc)) and attempt < 2:
                    continue
                raise

        raise last_error or Exception("移动文件失败")

    async def rename_file(self, fid: str, name: str) -> Dict[str, Any]:
        """
        重命名文件/文件夹

        Args:
            fid: 文件ID
            name: 新名称

        Returns:
            重命名结果
        """
        result = await self._async_call("fs_rename", {"fid": fid, "name": name})
        return check_response(result)

    async def get_file_info(self, fid: str) -> Dict[str, Any]:
        """
        获取文件信息

        Args:
            fid: 文件ID

        Returns:
            文件详细信息
        """
        result = await self._async_call("fs_file", {"fid": fid})
        return check_response(result)

    async def search_file(self, search_value: str, cid: str = "0") -> Dict[str, Any]:
        """
        搜索文件

        Args:
            search_value: 搜索关键词
            cid: 搜索范围目录ID

        Returns:
            搜索结果
        """
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                result = await self._async_call(
                    "fs_search", {"search_value": search_value, "cid": cid}
                )
                data = check_response(result)
                break
            except Exception as exc:
                last_error = exc
                if self._is_method_not_allowed_error(str(exc)) and attempt < 2:
                    continue
                raise
        else:
            raise last_error or Exception("搜索文件失败")

        # 确保返回字典格式
        if isinstance(data, list):
            return {"list": data}
        elif isinstance(data, dict):
            return data
        return {"list": []}

    async def get_download_url(self, pick_code: str) -> Dict[str, Any]:
        """
        获取下载链接

        Args:
            pick_code: 文件提取码

        Returns:
            下载链接信息
        """
        result = await self._async_call("download_url", {"pickcode": pick_code})
        return check_response(result)

    # ==================== 离线下载 ====================

    async def offline_task_add(self, url: str, wp_path_id: str = "") -> Dict[str, Any]:
        """
        添加离线下载任务

        Args:
            url: 下载链接（支持磁力、ed2k、http等）
            wp_path_id: 保存目录ID

        Returns:
            任务添加结果
        """
        payload = {"url": url}
        if wp_path_id:
            payload["wp_path_id"] = wp_path_id
        result = await self._async_call("offline_add_url", payload)
        return check_response(result)

    async def offline_task_list(self, page: int = 1) -> Dict[str, Any]:
        """
        获取离线任务列表

        Args:
            page: 页码

        Returns:
            任务列表
        """
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                result = await self._async_call("offline_list", {"page": page})
                data = check_response(result)
                break
            except Exception as exc:
                last_error = exc
                error_text = str(exc)
                # 115 离线接口在短时间高频访问时可能返回 405，交由全局队列熔断处理
                if "code=405" in error_text or "Method Not Allowed" in error_text:
                    if attempt < 2:
                        continue
                raise
        else:
            raise last_error or Exception("获取离线任务失败")

        tasks = data.get("tasks") if isinstance(data, dict) else []
        if not isinstance(tasks, list):
            tasks = []

        normalized_tasks: list[dict[str, Any]] = []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            percent_done = task.get("percentDone", task.get("percent", 0))
            try:
                percent_done = float(percent_done)
            except Exception:
                percent_done = 0.0
            if percent_done < 0:
                percent_done = 0.0
            if percent_done > 100:
                percent_done = 100.0

            row = dict(task)
            row["percent"] = percent_done
            row["percentDone"] = percent_done
            normalized_tasks.append(row)

        if isinstance(data, dict):
            response = dict(data)
            response["tasks"] = normalized_tasks
            return response
        return {"tasks": normalized_tasks, "state": True}

    async def offline_task_delete(self, hash_list: List[str]) -> Dict[str, Any]:
        """
        删除离线任务

        Args:
            hash_list: 任务hash列表

        Returns:
            删除结果
        """
        if isinstance(hash_list, str):
            hash_list = [hash_list]
        result = await self._async_call("offline_remove", {"hash": ",".join(hash_list)})
        return check_response(result)

    async def offline_task_restart(self, info_hash: str) -> Dict[str, Any]:
        """
        重试离线任务

        Args:
            info_hash: 任务 info_hash

        Returns:
            重试结果
        """
        result = await self._async_call("offline_restart", info_hash)
        return check_response(result)

    async def offline_task_clear(self, flag: int = 0) -> Dict[str, Any]:
        """
        清空已完成/失败的离线任务

        Returns:
            清空结果
        """
        result = await self._async_call("offline_clear", {"flag": int(flag)})
        return check_response(result)

    # ==================== 分享链接操作 ====================

    async def parse_share_link(self, share_url: str) -> Dict[str, Any]:
        """
        解析分享链接，获取分享信息

        Args:
            share_url: 分享链接（格式：https://115.com/s/xxxxx 或直接分享码）

        Returns:
            分享信息，包含分享码、文件列表等
        """
        # 从URL中提取分享码
        share_code = self._extract_share_code(share_url)
        if not share_code:
            raise ValueError("无效的分享链接格式")

        # 获取分享信息
        result = await self._async_call("share_info", {"share_code": share_code})
        return check_response(result)

    async def get_share_file_list(
        self,
        share_code: str,
        receive_code: str = "",
        cid: str = "0",
        offset: int = 0,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        获取分享链接中的文件列表

        Args:
            share_code: 分享码
            receive_code: 提取码（如果有）
            cid: 目录ID
            offset: 偏移量
            limit: 返回数量

        Returns:
            文件列表
        """
        payload = {
            "share_code": share_code,
            "receive_code": receive_code,
            "cid": cid,
            "offset": offset,
            "limit": limit,
        }
        attempts = (
            (
                "share_snap",
                {"base_url": "https://webapi.115.com"},
                "webapi.115.com/share/snap",
            ),
            ("share_snap", {}, "default/share_snap"),
            # proapi 的正确端点是 /{app}/2.0/share/snap，需调用 share_snap_app
            (
                "share_snap_app",
                {"app": "android", "base_url": "https://proapi.115.com"},
                "proapi.115.com/android/2.0/share/snap",
            ),
        )

        max_retries_per_attempt = 3
        last_error: Exception | None = None
        last_error_endpoint = ""
        data: Any | None = None
        for method_name, extra_kwargs, endpoint in attempts:
            for retry in range(max_retries_per_attempt):
                try:
                    result = await self._async_call(
                        method_name, payload, **extra_kwargs
                    )
                    data = check_response(result)
                    break
                except Exception as exc:
                    last_error = exc
                    last_error_endpoint = endpoint
                    error_text = str(exc)
                    if self._is_auth_related_error(error_text):
                        raise
                    # 仅当端点本身不可用(405)时，才降级尝试其它 share/snap 端点。
                    # 业务错误（如“请输入访问码/访问码错误/分享失效”）应直接抛出，避免被后续端点错误覆盖。
                    if not self._is_method_not_allowed_error(error_text):
                        raise
                    if self._is_method_not_allowed_error(error_text):
                        if retry < max_retries_per_attempt - 1:
                            continue
                    break

            # 请求成功后直接返回
            if data is not None:
                break

        if data is None:
            if last_error and self._is_method_not_allowed_error(str(last_error)):
                raise RuntimeError(
                    "share_api_method_not_allowed: "
                    f"endpoint={last_error_endpoint}, share_code={share_code}, cid={cid}, "
                    f"detail={str(last_error)[:300] if last_error else 'unknown'}"
                )
            raise last_error or Exception("获取分享文件列表失败")

        # 确保返回的是字典格式，包含 list 字段
        if isinstance(data, list):
            return {"list": data}
        elif isinstance(data, dict):
            if "list" not in data and "data" in data:
                return {"list": data["data"].get("list", [])}
            return data
        return {"list": []}

    async def get_share_all_files_recursive(
        self,
        share_code: str,
        receive_code: str = "",
        cid: str = "0",
        visited_cids: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        递归获取分享链接中的所有文件（包括子文件夹中的文件）

        Args:
            share_code: 分享码
            receive_code: 提取码（如果有）
            cid: 目录ID

        Returns:
            所有文件的列表，每个文件包含 fid 和 path（相对路径）
        """
        all_files = []
        if visited_cids is None:
            visited_cids = set()

        cid = str(cid or "0")
        if cid in visited_cids:
            return all_files
        visited_cids.add(cid)

        offset = 0
        limit = 100

        while True:
            result = await self.get_share_file_list(
                share_code, receive_code, cid, offset, limit
            )
            file_list = result.get("list", []) if isinstance(result, dict) else result

            if not file_list:
                break

            for item in file_list:
                if not isinstance(item, dict):
                    continue

                # web share_snap 返回中，目录通常没有 fid，文件包含 fid
                fid = item.get("fid")
                if fid:
                    all_files.append(
                        {
                            "fid": str(fid),
                            "name": item.get("n", ""),
                            "size": item.get("s", 0),
                        }
                    )
                    continue

                # 没有 fid 时按目录处理，递归抓取子目录文件
                sub_folder_cid = item.get("cid")
                if sub_folder_cid is None or sub_folder_cid in ("", 0, "0"):
                    continue

                sub_files = await self.get_share_all_files_recursive(
                    share_code, receive_code, str(sub_folder_cid), visited_cids
                )
                all_files.extend(sub_files)

            # 如果获取的文件数量小于 limit，说明已经获取完毕
            if len(file_list) < limit:
                break

            offset += limit

        return all_files

    async def save_share_file(
        self, share_code: str, file_id: str, pid: str = "0", receive_code: str = ""
    ) -> Dict[str, Any]:
        """
        转存分享文件到网盘

        Args:
            share_code: 分享码
            file_id: 要转存的文件ID
            pid: 保存到的目标目录ID
            receive_code: 提取码（如果有）

        Returns:
            转存结果
        """
        payload = {
            "share_code": share_code,
            "file_id": file_id,
            "cid": pid,
            "receive_code": receive_code,
        }
        result = await self._async_call("share_receive", payload)
        return check_response(result)

    async def save_share_files(
        self,
        share_code: str,
        file_ids: List[str],
        pid: str = "0",
        receive_code: str = "",
    ) -> Dict[str, Any]:
        """
        批量转存分享文件到网盘

        Args:
            share_code: 分享码
            file_ids: 要转存的文件ID列表
            pid: 保存到的目标目录ID
            receive_code: 提取码（如果有）

        Returns:
            转存结果
        """
        if isinstance(file_ids, str):
            file_ids = [file_ids]

        # 过滤掉空的 file_id
        file_ids = [fid for fid in file_ids if fid]
        if not file_ids:
            return {"state": False, "error": "没有有效的文件ID"}

        payload = {
            "share_code": share_code,
            "file_id": ",".join(file_ids),
            "cid": pid,
            "receive_code": receive_code,
        }
        max_attempts = 5
        last_error_text = ""
        for attempt in range(max_attempts):
            try:
                result = await self._async_call("share_receive", payload)
                data = check_response(result)
            except Exception as exc:
                error_text = str(exc)
                last_error_text = error_text
                if attempt < max_attempts - 1 and self._is_retryable_save_error(
                    error_text
                ):
                    continue
                raise

            if isinstance(data, dict):
                save_success = True
                if "success" in data:
                    save_success = bool(data.get("success"))
                elif "state" in data:
                    save_success = bool(data.get("state"))

                error_text = (
                    str(data.get("error") or "")
                    or str(data.get("error_msg") or "")
                    or str(data.get("message") or "")
                    or str(data.get("msg") or "")
                )
                last_error_text = error_text
                if (
                    not save_success
                    and attempt < max_attempts - 1
                    and self._is_retryable_save_error(error_text)
                ):
                    continue

            # 确保返回字典格式
            if isinstance(data, list):
                return {"state": True, "data": data}
            return data if isinstance(data, dict) else {"state": True, "data": data}

        retry_hint = f"115转存失败(已自动重试{max_attempts}次)"
        if last_error_text:
            return {"state": False, "error": f"{retry_hint}: {last_error_text}"}
        return {"state": False, "error": retry_hint}

    async def save_share_all(
        self, share_code: str, pid: str = "0", receive_code: str = ""
    ) -> Dict[str, Any]:
        """
        转存分享链接中的所有文件（仅当分享为单文件/文件夹时）

        Args:
            share_code: 分享码
            pid: 保存到的目标目录ID
            receive_code: 提取码（如果有）

        Returns:
            转存结果
        """
        # 先获取分享信息
        share_info = await self.get_share_file_list(share_code, receive_code)

        # 处理不同的返回格式
        if isinstance(share_info, list):
            file_list = share_info
        elif isinstance(share_info, dict):
            file_list = share_info.get("list", [])
        else:
            file_list = []

        if file_list:
            file_ids = []
            for f in file_list:
                if isinstance(f, dict):
                    fid = f.get("fid") or f.get("id", "")
                    if fid:
                        file_ids.append(str(fid))
            return await self.save_share_files(share_code, file_ids, pid, receive_code)

        return {"state": False, "error": "分享内容为空或无法获取"}

    # ==================== Cookie管理 ====================

    async def start_qr_login(self, app: str = "alipaymini") -> Dict[str, Any]:
        """
        启动115扫码登录，返回二维码链接和会话token。
        """
        await self._clear_expired_qr_sessions()
        normalized_app = str(app or "alipaymini").strip() or "alipaymini"
        if normalized_app not in self._QR_LOGIN_ALLOWED_APPS:
            normalized_app = "alipaymini"

        raw_token = await asyncio.wait_for(
            _get_p115_client_cls().login_qrcode_token(async_=True, timeout=8),
            timeout=8.5,
        )
        token_payload = self._extract_qr_data(raw_token)
        uid = str(token_payload.get("uid") or "").strip()
        if not uid:
            raise RuntimeError("获取115二维码失败：响应中缺少uid")

        scan_payload = {
            "uid": uid,
            "time": token_payload.get("time"),
            "sign": token_payload.get("sign"),
        }
        qr_url = str(token_payload.get("qrcode") or "").strip()
        if not qr_url:
            qr_url = f"https://115.com/scan/dg-{uid}"

        token = uuid4().hex
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._QR_LOGIN_EXPIRE_SECONDS)
        async with self._QR_LOGIN_LOCK:
            self._QR_LOGIN_PENDING[token] = {
                "token": token,
                "uid": uid,
                "scan_payload": scan_payload,
                "qr_url": qr_url,
                "app": normalized_app,
                "state": "pending",
                "message": "等待扫码",
                "created_at": now,
                "expires_at": expires_at,
                "cookie": "",
            }

        return {
            "token": token,
            "qr_url": qr_url,
            "expires_at": expires_at.isoformat(),
            "expire_seconds": self._QR_LOGIN_EXPIRE_SECONDS,
            "app": normalized_app,
        }

    async def get_qr_login_image(self, token: str) -> bytes:
        """
        获取扫码二维码PNG图片，供前端直接展示。
        """
        await self._clear_expired_qr_sessions()
        normalized = str(token or "").strip()
        if not normalized:
            raise ValueError("扫码会话标识不能为空")
        async with self._QR_LOGIN_LOCK:
            item = self._QR_LOGIN_PENDING.get(normalized)
        if not item:
            raise ValueError("扫码会话不存在或已过期，请重新生成二维码")
        uid = str(item.get("uid") or "").strip()
        if not uid:
            raise RuntimeError("扫码会话缺少uid，无法获取二维码图片")
        image_bytes = await asyncio.wait_for(
            _get_p115_client_cls().login_qrcode(uid, async_=True, timeout=8),
            timeout=8.5,
        )
        if not isinstance(image_bytes, (bytes, bytearray)):
            raise RuntimeError("二维码图片响应异常")
        return bytes(image_bytes)

    async def check_qr_login_status(self, token: str) -> Dict[str, Any]:
        """
        检查扫码登录状态；授权成功时返回cookie（仅服务端使用，不建议直接透传前端）。
        """
        await self._clear_expired_qr_sessions()
        normalized = str(token or "").strip()
        if not normalized:
            raise ValueError("扫码会话标识不能为空")

        async with self._QR_LOGIN_LOCK:
            item = self._QR_LOGIN_PENDING.get(normalized)
        if not item:
            raise ValueError("扫码会话不存在或已过期，请重新生成二维码")

        now = datetime.now(timezone.utc)
        expires_at = item.get("expires_at")
        if isinstance(expires_at, datetime) and now >= expires_at:
            async with self._QR_LOGIN_LOCK:
                self._QR_LOGIN_PENDING.pop(normalized, None)
            return {
                "authorized": False,
                "pending": False,
                "status": "expired",
                "message": "二维码已过期，请重新生成",
                "expires_at": expires_at.isoformat(),
            }

        current_state = str(item.get("state") or "pending")
        if current_state in {"authorized", "canceled", "expired", "failed"}:
            return {
                "authorized": current_state == "authorized",
                "pending": False,
                "status": current_state,
                "message": str(item.get("message") or ""),
                "cookie": str(item.get("cookie") or ""),
                "expires_at": expires_at.isoformat()
                if isinstance(expires_at, datetime)
                else "",
            }

        try:
            status_resp = await asyncio.wait_for(
                _get_p115_client_cls().login_qrcode_scan_status(
                    item.get("scan_payload") or {},
                    async_=True,
                    timeout=8,
                ),
                timeout=8.5,
            )
        except Exception as exc:
            return {
                "authorized": False,
                "pending": True,
                "status": "pending",
                "message": str(exc)[:300] or "等待扫码",
                "expires_at": expires_at.isoformat()
                if isinstance(expires_at, datetime)
                else "",
            }

        status_data = self._extract_qr_data(status_resp)
        status_code = self._safe_int(status_data.get("status"), default=None)
        status_message = str(
            status_data.get("msg") or status_data.get("message") or ""
        ).strip()

        if status_code == 0:
            message = status_message or "等待扫码"
            await self._update_qr_session(normalized, state="pending", message=message)
            return {
                "authorized": False,
                "pending": True,
                "status": "pending",
                "message": message,
                "expires_at": expires_at.isoformat()
                if isinstance(expires_at, datetime)
                else "",
            }

        if status_code == 1:
            message = status_message or "已扫码，等待确认"
            await self._update_qr_session(normalized, state="scanned", message=message)
            return {
                "authorized": False,
                "pending": True,
                "status": "scanned",
                "message": message,
                "expires_at": expires_at.isoformat()
                if isinstance(expires_at, datetime)
                else "",
            }

        if status_code == -2:
            message = status_message or "已取消扫码登录"
            await self._update_qr_session(normalized, state="canceled", message=message)
            return {
                "authorized": False,
                "pending": False,
                "status": "canceled",
                "message": message,
                "expires_at": expires_at.isoformat()
                if isinstance(expires_at, datetime)
                else "",
            }

        if status_code == -1:
            message = status_message or "二维码已过期，请重新生成"
            await self._update_qr_session(normalized, state="expired", message=message)
            return {
                "authorized": False,
                "pending": False,
                "status": "expired",
                "message": message,
                "expires_at": expires_at.isoformat()
                if isinstance(expires_at, datetime)
                else "",
            }

        if status_code != 2:
            message = status_message or "等待扫码确认"
            await self._update_qr_session(normalized, state="pending", message=message)
            return {
                "authorized": False,
                "pending": True,
                "status": "pending",
                "message": message,
                "expires_at": expires_at.isoformat()
                if isinstance(expires_at, datetime)
                else "",
            }

        result_resp = await asyncio.wait_for(
            _get_p115_client_cls().login_qrcode_scan_result(
                str(item.get("uid") or ""),
                app=str(item.get("app") or "alipaymini"),
                async_=True,
                timeout=8,
            ),
            timeout=8.5,
        )
        result_data = check_response(result_resp)
        cookie = self._normalize_qr_cookie(result_data)
        if not cookie:
            raise RuntimeError("扫码成功但未获取到Cookie")

        await self._update_qr_session(
            normalized, state="authorized", message="扫码登录成功", cookie=cookie
        )
        return {
            "authorized": True,
            "pending": False,
            "status": "authorized",
            "message": "扫码登录成功",
            "cookie": cookie,
            "expires_at": expires_at.isoformat()
            if isinstance(expires_at, datetime)
            else "",
        }

    async def cancel_qr_login(self, token: str) -> Dict[str, Any]:
        """
        取消扫码登录会话。
        """
        normalized = str(token or "").strip()
        if not normalized:
            raise ValueError("扫码会话标识不能为空")
        async with self._QR_LOGIN_LOCK:
            removed = self._QR_LOGIN_PENDING.pop(normalized, None)
        if not removed:
            return {"canceled": False, "message": "扫码会话不存在或已结束"}
        return {"canceled": True, "message": "扫码会话已取消"}

    @classmethod
    async def _clear_expired_qr_sessions(cls) -> None:
        now = datetime.now(timezone.utc)
        async with cls._QR_LOGIN_LOCK:
            expired = []
            for token, item in cls._QR_LOGIN_PENDING.items():
                expires_at = item.get("expires_at")
                if isinstance(expires_at, datetime) and now >= expires_at:
                    expired.append(token)
            for token in expired:
                cls._QR_LOGIN_PENDING.pop(token, None)

    @classmethod
    async def _update_qr_session(cls, token: str, **updates: Any) -> None:
        async with cls._QR_LOGIN_LOCK:
            item = cls._QR_LOGIN_PENDING.get(token)
            if not item:
                return
            item.update(updates)

    @staticmethod
    def _extract_qr_data(resp: Any) -> Dict[str, Any]:
        if isinstance(resp, dict):
            data = resp.get("data")
            if isinstance(data, dict):
                return data
            return resp
        return {}

    @staticmethod
    def _normalize_qr_cookie(resp_data: Any) -> str:
        data = resp_data if isinstance(resp_data, dict) else {}
        cookie_raw = data.get("cookie")
        if cookie_raw is None and isinstance(data.get("data"), dict):
            cookie_raw = data["data"].get("cookie")
        if isinstance(cookie_raw, str):
            return cookie_raw.strip().rstrip(";")
        if isinstance(cookie_raw, dict):
            pairs = [
                f"{str(k)}={str(v)}" for k, v in cookie_raw.items() if str(k).strip()
            ]
            return "; ".join(pairs).strip().rstrip(";")
        return ""

    async def check_cookie_valid(self) -> Dict[str, Any]:
        """
        检查Cookie是否有效

        Returns:
            包含有效状态和用户信息的字典
        """
        try:
            user_info = await self.get_user_info()
            space_info = await self.get_user_space_info()

            # 提取用户基本信息
            user_data = user_info.get("data", {})

            # 提取空间信息
            space_data = space_info.get("data", {}).get("space_info", {})
            all_total = space_data.get("all_total", {})
            all_use = space_data.get("all_use", {})

            # 合并用户信息和空间信息
            combined_info = {
                "user_id": user_data.get("user_id"),
                "user_name": user_data.get("user_name"),
                "is_vip": user_data.get("is_vip"),
                "user_face": user_data.get("user_face"),
                "space_total": all_total.get("size"),
                "space_total_format": all_total.get("size_format"),
                "space_used": all_use.get("size"),
                "space_used_format": all_use.get("size_format"),
            }

            return {"valid": True, "user_info": combined_info, "message": "Cookie有效"}
        except Exception as e:
            return {"valid": False, "user_info": None, "message": str(e)}

    def update_cookie(self, cookie: str) -> None:
        """
        更新Cookie

        Args:
            cookie: 新的cookie字符串
        """
        self.cookie = cookie
        self._client = None  # 重置客户端实例

    def get_cookie(self) -> str:
        """
        获取当前Cookie

        Returns:
            当前cookie字符串
        """
        return self.cookie

    @staticmethod
    def _extract_share_code(share_url: str) -> Optional[str]:
        """
        从URL或字符串中提取分享码

        Args:
            share_url: 分享链接或分享码

        Returns:
            分享码，如果无法提取则返回None
        """
        # 尝试匹配常见分享链接（115.com / 115cdn.com / share.115.com）
        match = re.search(
            r"(?:115(?:cdn)?\.com/s/|share\.115\.com/)([a-zA-Z0-9]+)", share_url
        )
        if match:
            return match.group(1)

        # 尝试匹配 share_code-receive_code 格式
        short_match = re.match(r"^([a-zA-Z0-9]+)-[a-zA-Z0-9]{4}$", share_url.strip())
        if short_match:
            return short_match.group(1)

        # 尝试匹配纯分享码（通常是字母数字组合）
        if re.match(r"^[a-zA-Z0-9]+$", share_url.strip()):
            return share_url.strip()

        return None

    def _resolve_share_payload(
        self, share_url: str, receive_code: str = ""
    ) -> tuple[str, str]:
        """Normalize share url into share_code and receive_code."""
        normalized_url = str(share_url or "").strip()
        try:
            share_payload = share_extract_payload(normalized_url)
        except Exception:
            share_payload = {
                "share_code": self._extract_share_code(normalized_url) or "",
                "receive_code": "",
            }

        share_code = str(share_payload.get("share_code") or "").strip()
        if not share_code:
            raise ValueError("无效的分享链接格式")

        resolved_receive_code = str(receive_code or "").strip()
        if not resolved_receive_code:
            resolved_receive_code = str(share_payload.get("receive_code") or "").strip()
        if not resolved_receive_code:
            short_receive_match = re.match(
                r"^[A-Za-z0-9]+-([A-Za-z0-9]{4})$", normalized_url
            )
            if short_receive_match:
                resolved_receive_code = short_receive_match.group(1)
        if not resolved_receive_code:
            password_match = re.search(
                r"(?:password|pwd)=([^&#]+)", normalized_url, re.IGNORECASE
            )
            resolved_receive_code = password_match.group(1) if password_match else ""
        if not resolved_receive_code:
            text_receive_match = re.search(
                r"(?:提取码|提取碼|密码|密碼)\s*[:：=]?\s*([A-Za-z0-9]{4})",
                normalized_url,
                re.IGNORECASE,
            )
            resolved_receive_code = (
                text_receive_match.group(1) if text_receive_match else ""
            )

        return share_code, resolved_receive_code

    @staticmethod
    def _safe_int(value: Any, default: int | None = 0) -> int | None:
        try:
            return int(value)
        except Exception:
            return default

    # ==================== 高级功能 ====================

    def _is_folder_item(self, item: dict) -> bool:
        """
        判断文件项是否为文件夹

        Args:
            item: 文件信息字典

        Returns:
            是否为文件夹
        """
        # 方法1：检查 ico 字段（文件夹通常是 "folder"）
        ico = item.get("ico", "")
        if ico == "folder":
            return True

        # 方法2：检查 pc 字段（父目录标识）
        pc = item.get("pc")
        if pc is not None:
            # pc 是字符串时，非 "0" 表示文件夹
            if isinstance(pc, str):
                return pc != "0" and bool(pc)
            # pc 是数字时，1 表示文件夹
            if isinstance(pc, int):
                return pc == 1

        # 方法3：检查是否没有文件大小（文件夹通常 size 为 0 或无此字段）
        # 同时检查是否有 fid（文件有 fid，文件夹可能没有）
        has_size = item.get("s") is not None and item.get("s", 0) > 0
        has_fid = bool(item.get("fid"))

        # 如果有大小或者有 fid，可能是文件
        if has_size:
            return False

        return True

    def _extract_folder_id(self, item: dict) -> str:
        """
        从文件项中提取文件夹ID

        Args:
            item: 文件信息字典

        Returns:
            文件夹ID
        """
        # 文件夹可能使用 fid, id, cid 等字段
        return (
            item.get("fid")
            or item.get("id")
            or item.get("cid")
            or item.get("file_id")
            or ""
        )

    async def _wait_for_folder_ready(
        self,
        folder_id: str,
        retries: int = 5,
        delay: float = 0.25,
    ) -> bool:
        """
        等待新建目录在 115 侧可见，避免“首次转存失败、重试成功”的时序问题。

        Args:
            folder_id: 目录ID
            retries: 最大重试次数
            delay: 每次重试间隔（秒）

        Returns:
            目录是否已可访问
        """
        folder_id = str(folder_id or "").strip()
        if not folder_id or folder_id == "0":
            return True

        for attempt in range(retries):
            try:
                await self.get_file_info(folder_id)
                return True
            except Exception:
                if attempt == retries - 1:
                    break
                await asyncio.sleep(delay)

        return False

    @staticmethod
    def _normalize_file_list_result(data: Any) -> Dict[str, Any]:
        """统一文件列表返回结构，保证 data 为列表。"""
        if isinstance(data, list):
            return {"data": data}
        if isinstance(data, dict):
            result = dict(data)
            raw_data = result.get("data")
            if isinstance(raw_data, list):
                return result
            if isinstance(raw_data, dict):
                nested_list = raw_data.get("list")
                if isinstance(nested_list, list):
                    result["data"] = nested_list
                    return result
            top_level_list = result.get("list")
            if isinstance(top_level_list, list):
                result["data"] = top_level_list
                return result
            result["data"] = []
            return result
        return {"data": []}

    @staticmethod
    def _is_auth_related_error(error_text: str) -> bool:
        text = str(error_text or "").lower()
        if not text:
            return False
        auth_tokens = (
            "cookie",
            "eauth",
            "errno': 990001",
            '"errno": 990001',
            "errno=990001",
            "errno: 990001",
            "errno': 99",
            '"errno": 99',
            "errno=99",
            "errno: 99",
            "重新登录",
            "登录超时",
        )
        return any(token in text for token in auth_tokens)

    @staticmethod
    def _is_method_not_allowed_error(error_text: str) -> bool:
        text = str(error_text or "").lower()
        if not text:
            return False
        return "code=405" in text or "method not allowed" in text

    @staticmethod
    def _is_retryable_save_error(error_text: str) -> bool:
        """判断是否属于目录刚创建后的短暂一致性错误。"""
        text = str(error_text or "").lower()
        if not text:
            return False
        retry_tokens = (
            "enoent",
            "不存在",
            "目录",
            "invalid cid",
            "folder",
            "cid",
            "code=405",
            "method not allowed",
            "频繁",
            "too many",
            "rate limit",
        )
        return any(token in text for token in retry_tokens)

    @staticmethod
    def _save_retry_delay(attempt: int) -> float:
        # 指数退避 + 少量随机抖动，降低持续触发风控概率。
        base = min(0.8 * (2**attempt), 20.0)
        jitter = random.uniform(0.0, 0.4)
        return base + jitter

    async def get_or_create_folder(self, parent_id: str, folder_name: str) -> str:
        """
        获取或创建文件夹

        Args:
            parent_id: 父目录ID
            folder_name: 文件夹名称

        Returns:
            文件夹ID
        """
        # 先搜索是否存在同名文件夹
        search_result = await self.search_file(folder_name, parent_id)

        # 处理不同的返回格式
        if isinstance(search_result, list):
            file_list = search_result
        elif isinstance(search_result, dict):
            # data 可能是列表，也可能包含 list 字段
            data = search_result.get("data")
            if isinstance(data, list):
                file_list = data
            else:
                file_list = search_result.get("list") or (
                    data.get("list", []) if isinstance(data, dict) else []
                )
        else:
            file_list = []

        # 查找同名文件夹（必须确认 pid 与当前 parent_id 一致，避免搜到其它位置的同名目录）
        for item in file_list:
            if isinstance(item, dict):
                item_name = item.get("n", "")
                item_pid = str(item.get("pid") or item.get("parent_id") or "").strip()
                if (
                    item_name == folder_name
                    and self._is_folder_item(item)
                    and item_pid == str(parent_id)
                ):
                    folder_id = self._extract_folder_id(item)
                    if folder_id:
                        return folder_id

        # 不存在则创建
        create_result = await self.create_folder(parent_id, folder_name)

        # 处理创建结果
        if isinstance(create_result, dict):
            # 创建成功
            if create_result.get("state"):
                data = create_result.get("data", {})
                folder_id = (
                    data.get("fid")
                    or data.get("file_id")
                    or create_result.get("file_id", "")
                )
                if folder_id:
                    await self._wait_for_folder_ready(str(folder_id))
                    return folder_id

            # 目录已存在（errno 20004 是警告，说明目录已存在）
            if create_result.get("errno") == 20004 or "该目录名称已存在" in str(
                create_result.get("error", "")
            ):
                # 等待一小段时间后重新搜索
                await asyncio.sleep(0.3)
                retry_result = await self.search_file(folder_name, parent_id)

                # 提取文件列表
                retry_list = []
                if isinstance(retry_result, list):
                    retry_list = retry_result
                elif isinstance(retry_result, dict):
                    data = retry_result.get("data")
                    if isinstance(data, list):
                        retry_list = data
                    elif isinstance(data, dict):
                        retry_list = data.get("list", [])
                    else:
                        retry_list = retry_result.get("list", [])

                # 再次查找同名文件夹（仍需校验 pid）
                for item in retry_list:
                    if isinstance(item, dict):
                        item_name = item.get("n", "")
                        item_pid = str(
                            item.get("pid") or item.get("parent_id") or ""
                        ).strip()
                        if (
                            item_name == folder_name
                            and self._is_folder_item(item)
                            and item_pid == str(parent_id)
                        ):
                            folder_id = self._extract_folder_id(item)
                            if folder_id:
                                return folder_id

                # 如果还是找不到，尝试直接获取文件列表精确查找
                try:
                    file_list_result = await self.get_file_list(
                        cid=parent_id, limit=1000
                    )
                    direct_list = []
                    if isinstance(file_list_result, dict):
                        direct_list = file_list_result.get("data", [])

                    for item in direct_list:
                        if isinstance(item, dict):
                            item_name = item.get("n", "")
                            if item_name == folder_name and self._is_folder_item(item):
                                folder_id = self._extract_folder_id(item)
                                if folder_id:
                                    return folder_id
                except Exception:
                    pass

        # 如果以上都失败，抛出异常
        error_msg = (
            create_result.get("error", "未知错误")
            if isinstance(create_result, dict)
            else "未知错误"
        )
        raise Exception(f"创建文件夹失败: {error_msg}")

    async def save_share_to_folder(
        self,
        share_url: str,
        folder_name: str,
        parent_id: str = "0",
        receive_code: str = "",
    ) -> Dict[str, Any]:
        """
        将分享链接转存到指定文件夹中（递归转存所有文件）

        Args:
            share_url: 分享链接
            folder_name: 目标文件夹名称
            parent_id: 父目录ID
            receive_code: 提取码

        Returns:
            转存结果
        """
        share_code, receive_code = self._resolve_share_payload(share_url, receive_code)

        # 获取或创建目标文件夹
        target_folder_id = await self.get_or_create_folder(parent_id, folder_name)
        if not str(target_folder_id or "").strip():
            raise ValueError("创建目标文件夹失败，未获取到目录ID")

        # 递归获取分享中的所有文件（包括子文件夹中的文件）
        all_files = await self.get_share_all_files_recursive(share_code, receive_code)

        if not all_files:
            raise ValueError("分享中没有可转存的文件")

        # 批量转存所有文件（去重）
        file_ids = list(
            dict.fromkeys([str(f["fid"]) for f in all_files if f.get("fid")])
        )
        result = await self.save_share_files(
            share_code, file_ids, target_folder_id, receive_code
        )
        transfer_success = True
        if isinstance(result, dict):
            if "success" in result:
                transfer_success = bool(result.get("success"))
            elif "state" in result:
                transfer_success = bool(result.get("state"))
            elif "errNo" in result:
                transfer_success = str(result.get("errNo")) == "0"
            elif "code" in result:
                transfer_success = str(result.get("code")) in {"0", "200"}

        if not transfer_success:
            error_msg = ""
            if isinstance(result, dict):
                error_msg = (
                    str(result.get("error") or "")
                    or str(result.get("error_msg") or "")
                    or str(result.get("message") or "")
                    or str(result.get("msg") or "")
                )
            raise ValueError(error_msg or "115转存失败，接口未返回成功状态")

        # 返回结果包含文件数量
        return {
            "success": transfer_success,
            "message": f"成功转存 {len(file_ids)} 个文件",
            "folder_id": target_folder_id,
            "folder_name": folder_name,
            "file_count": len(file_ids),
            "result": result,
        }

    async def save_share_directly(
        self,
        share_url: str,
        parent_id: str = "0",
        receive_code: str = "",
    ) -> Dict[str, Any]:
        """将分享里的所有文件直接转存到目标目录，不创建影视外层文件夹。"""
        share_code, receive_code = self._resolve_share_payload(share_url, receive_code)
        all_files = await self.get_share_all_files_recursive(share_code, receive_code)
        if not all_files:
            raise ValueError("分享中没有可转存的文件")

        file_ids = list(
            dict.fromkeys([str(f["fid"]) for f in all_files if f.get("fid")])
        )
        result = await self.save_share_files(
            share_code, file_ids, str(parent_id or "0"), receive_code
        )
        transfer_success = True
        if isinstance(result, dict):
            if "success" in result:
                transfer_success = bool(result.get("success"))
            elif "state" in result:
                transfer_success = bool(result.get("state"))
            elif "errNo" in result:
                transfer_success = str(result.get("errNo")) == "0"
            elif "code" in result:
                transfer_success = str(result.get("code")) in {"0", "200"}

        if not transfer_success:
            error_msg = ""
            if isinstance(result, dict):
                error_msg = (
                    str(result.get("error") or "")
                    or str(result.get("error_msg") or "")
                    or str(result.get("message") or "")
                    or str(result.get("msg") or "")
                )
            raise ValueError(error_msg or "115转存失败，接口未返回成功状态")

        return {
            "success": transfer_success,
            "message": f"成功直存 {len(file_ids)} 个文件",
            "target_parent_id": str(parent_id or "0"),
            "file_count": len(file_ids),
            "save_mode": "direct",
            "result": result,
        }

    async def save_share_files_to_folder(
        self,
        share_url: str,
        file_ids: List[str],
        folder_name: str,
        parent_id: str = "0",
        receive_code: str = "",
    ) -> Dict[str, Any]:
        """
        选集转存（部分转存）：将指定的 file_ids 转存到目标文件夹中

        Args:
            share_url: 分享链接
            file_ids: 要转存的文件 fid 列表
            folder_name: 目标文件夹名称
            parent_id: 父目录ID
            receive_code: 提取码

        Returns:
            转存结果
        """
        if not file_ids:
            raise ValueError("未选择任何要转存的文件")

        share_code, receive_code = self._resolve_share_payload(share_url, receive_code)

        # 获取或创建目标文件夹
        target_folder_id = await self.get_or_create_folder(parent_id, folder_name)
        if not str(target_folder_id or "").strip():
            raise ValueError("创建目标文件夹失败，未获取到目录ID")

        # 去重
        file_ids = list(dict.fromkeys(file_ids))

        # 批量转存选中文件
        result = await self.save_share_files(
            share_code, file_ids, target_folder_id, receive_code
        )
        transfer_success = True
        if isinstance(result, dict):
            if "success" in result:
                transfer_success = bool(result.get("success"))
            elif "state" in result:
                transfer_success = bool(result.get("state"))
            elif "errNo" in result:
                transfer_success = str(result.get("errNo")) == "0"
            elif "code" in result:
                transfer_success = str(result.get("code")) in {"0", "200"}

        if not transfer_success:
            error_msg = ""
            if isinstance(result, dict):
                error_msg = (
                    str(result.get("error") or "")
                    or str(result.get("error_msg") or "")
                    or str(result.get("message") or "")
                    or str(result.get("msg") or "")
                )
            raise ValueError(error_msg or "115转存失败，接口未返回成功状态")

        return {
            "success": transfer_success,
            "message": f"成功转存 {len(file_ids)} 个文件",
            "folder_id": target_folder_id,
            "folder_name": folder_name,
            "file_count": len(file_ids),
            "result": result,
        }

    async def save_share_files_directly(
        self,
        share_url: str,
        file_ids: List[str],
        parent_id: str = "0",
        receive_code: str = "",
    ) -> Dict[str, Any]:
        """将指定文件直接转存到目标目录，不创建影视外层文件夹。"""
        if not file_ids:
            raise ValueError("未选择任何要转存的文件")

        share_code, receive_code = self._resolve_share_payload(share_url, receive_code)
        file_ids = list(
            dict.fromkeys([str(fid) for fid in file_ids if str(fid or "").strip()])
        )
        result = await self.save_share_files(
            share_code, file_ids, str(parent_id or "0"), receive_code
        )
        transfer_success = True
        if isinstance(result, dict):
            if "success" in result:
                transfer_success = bool(result.get("success"))
            elif "state" in result:
                transfer_success = bool(result.get("state"))
            elif "errNo" in result:
                transfer_success = str(result.get("errNo")) == "0"
            elif "code" in result:
                transfer_success = str(result.get("code")) in {"0", "200"}

        if not transfer_success:
            error_msg = ""
            if isinstance(result, dict):
                error_msg = (
                    str(result.get("error") or "")
                    or str(result.get("error_msg") or "")
                    or str(result.get("message") or "")
                    or str(result.get("msg") or "")
                )
            raise ValueError(error_msg or "115转存失败，接口未返回成功状态")

        return {
            "success": transfer_success,
            "message": f"成功直存 {len(file_ids)} 个文件",
            "target_parent_id": str(parent_id or "0"),
            "file_count": len(file_ids),
            "save_mode": "direct",
            "result": result,
        }


# 创建默认服务实例
pan115_service = Pan115Service()
