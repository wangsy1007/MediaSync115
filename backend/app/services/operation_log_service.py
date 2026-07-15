import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError

from app.core.database import async_session_maker, is_database_locked_error
from app.models.models import OperationLog

from app.core.timezone_utils import beijing_now

logger = logging.getLogger(__name__)

SENSITIVE_KEYWORDS = (
    "cookie",
    "authorization",
    "token",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "session",
    "hash",
)
MAX_SUMMARY_CHARS = 4000
MAX_DEPTH = 4
OPERATION_LOG_QUEUE_MAXSIZE = 4096
OPERATION_LOG_BATCH_SIZE = 100
OPERATION_LOG_BUSY_TIMEOUT_MS = 2000
OPERATION_LOG_LOCK_RETRY_ATTEMPTS = 5


class OperationLogService:
    def __init__(
        self,
        *,
        queue_maxsize: int = OPERATION_LOG_QUEUE_MAXSIZE,
        batch_size: int = OPERATION_LOG_BATCH_SIZE,
        busy_timeout_ms: int = OPERATION_LOG_BUSY_TIMEOUT_MS,
        lock_retry_attempts: int = OPERATION_LOG_LOCK_RETRY_ATTEMPTS,
    ) -> None:
        self._last_pruned_at: datetime | None = None
        self._queue_maxsize = max(1, int(queue_maxsize))
        self._batch_size = max(1, int(batch_size))
        self._busy_timeout_ms = max(1, int(busy_timeout_ms))
        self._lock_retry_attempts = max(1, int(lock_retry_attempts))
        self._queue: asyncio.Queue[dict[str, Any] | None] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._worker_loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False
        self._dropped_count = 0

    async def start(self) -> None:
        """启动单写者队列，避免业务事务同步写日志造成 SQLite 自锁。"""
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._stopping = False
        self._queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._worker_loop = asyncio.get_running_loop()
        self._worker_task = asyncio.create_task(
            self._run_writer(), name="operation-log-writer"
        )

    async def stop(self) -> None:
        """写完已接收的日志并停止后台写入器。"""
        task = self._worker_task
        queue = self._queue
        if task is None or queue is None:
            return
        self._stopping = True
        await self.flush()
        await queue.put(None)
        await task
        self._worker_task = None
        self._worker_loop = None
        self._queue = None
        self._stopping = False

    async def flush(self) -> None:
        """等待队列中当前所有日志完成持久化。"""
        if self._writer_runs_in_current_loop():
            assert self._queue is not None
            await self._queue.join()

    def _writer_runs_in_current_loop(self) -> bool:
        task = self._worker_task
        if task is None or task.done() or self._worker_loop is None:
            return False
        try:
            return asyncio.get_running_loop() is self._worker_loop
        except RuntimeError:
            return False

    def _enqueue(self, payload: dict[str, Any]) -> None:
        queue = self._queue
        if queue is None or self._stopping:
            return
        try:
            queue.put_nowait(payload)
            return
        except asyncio.QueueFull:
            pass

        # 日志属于观测数据，队列饱和时淘汰最旧项，绝不反向阻塞业务事务。
        try:
            queue.get_nowait()
            queue.task_done()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._dropped_count += 1
            return
        self._dropped_count += 1
        if self._dropped_count == 1 or self._dropped_count % 100 == 0:
            logger.warning(
                "操作日志队列已满，累计丢弃最旧日志 %d 条", self._dropped_count
            )

    async def _persist_batch(self, payloads: list[dict[str, Any]]) -> None:
        for attempt in range(self._lock_retry_attempts):
            try:
                async with async_session_maker() as db:
                    # 日志写入器使用较短等待并主动退避；业务连接仍保留 60 秒容错。
                    await db.execute(
                        text(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
                    )
                    db.add_all(OperationLog(**payload) for payload in payloads)
                    await db.commit()
                return
            except OperationalError as exc:
                if (
                    not is_database_locked_error(exc)
                    or attempt + 1 >= self._lock_retry_attempts
                ):
                    raise
                delay = min(0.1 * (2**attempt), 1.0)
                logger.warning(
                    "操作日志批量写入遇到数据库锁，%.1f 秒后重试（%d/%d）",
                    delay,
                    attempt + 1,
                    self._lock_retry_attempts,
                )
                await asyncio.sleep(delay)

    async def _run_writer(self) -> None:
        queue = self._queue
        if queue is None:
            return
        while True:
            first = await queue.get()
            if first is None:
                queue.task_done()
                return

            batch = [first]
            while len(batch) < self._batch_size:
                try:
                    item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is None:
                    queue.task_done()
                    break
                batch.append(item)

            try:
                await self._persist_batch(batch)
            except Exception:
                # 观测日志失败不能再使订阅、转存等核心业务失败。
                logger.exception("操作日志批量持久化失败，丢弃 %d 条日志", len(batch))
            finally:
                for _ in batch:
                    queue.task_done()

            try:
                await self.maybe_prune()
            except Exception:
                logger.warning("自动清理过期操作日志失败", exc_info=True)

    @staticmethod
    def _trim_text(text: str) -> str:
        value = str(text or "")
        if len(value) <= MAX_SUMMARY_CHARS:
            return value
        return f"{value[:MAX_SUMMARY_CHARS]}...(truncated)"

    @staticmethod
    def _mask_value(value: Any) -> str:
        text = str(value or "")
        if not text:
            return "***"
        if len(text) <= 8:
            return "***"
        return f"{text[:3]}***{text[-3:]}"

    def _is_sensitive_key(self, key: str) -> bool:
        lowered = str(key or "").strip().lower()
        return any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)

    def _redact(self, data: Any, depth: int = 0) -> Any:
        if depth > MAX_DEPTH:
            return "..."
        if isinstance(data, dict):
            output: dict[str, Any] = {}
            for key, value in data.items():
                if self._is_sensitive_key(str(key)):
                    output[str(key)] = self._mask_value(value)
                else:
                    output[str(key)] = self._redact(value, depth + 1)
            return output
        if isinstance(data, list):
            return [self._redact(item, depth + 1) for item in data[:100]]
        if isinstance(data, tuple):
            return [self._redact(item, depth + 1) for item in list(data)[:100]]
        if isinstance(data, (str, int, float, bool)) or data is None:
            if isinstance(data, str):
                return self._trim_text(data)
            return data
        return self._trim_text(repr(data))

    def redact_payload(self, payload: Any) -> str | None:
        if payload is None:
            return None
        try:
            redacted = self._redact(payload)
            return self._trim_text(json.dumps(redacted, ensure_ascii=False))
        except Exception:
            return self._trim_text(str(payload))

    def redact_headers(self, headers: dict[str, Any]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in headers.items():
            if self._is_sensitive_key(str(key)):
                output[str(key)] = self._mask_value(value)
                continue
            output[str(key)] = self._trim_text(str(value))
        return output

    def _build_module(self, path: str) -> str:
        cleaned = str(path or "").split("?", 1)[0]
        parts = [part for part in cleaned.split("/") if part]
        if len(parts) >= 2 and parts[0] == "api":
            return parts[1]
        if parts:
            return parts[0]
        return "unknown"

    async def log(
        self,
        *,
        trace_id: str,
        source_type: str,
        module: str,
        action: str,
        status: str,
        message: str,
        http_method: str | None = None,
        path: str | None = None,
        status_code: int | None = None,
        duration_ms: int | None = None,
        request_summary: Any = None,
        response_summary: Any = None,
        extra: Any = None,
    ) -> None:
        payload = {
            "trace_id": str(trace_id or "").strip() or "unknown",
            "source_type": str(source_type or "unknown")[:40],
            "module": str(module or "unknown")[:60],
            "action": str(action or "unknown")[:255],
            "status": str(status or "info")[:20],
            "http_method": (str(http_method)[:10] if http_method else None),
            "path": (str(path)[:255] if path else None),
            "status_code": status_code,
            "duration_ms": duration_ms,
            "message": str(message or "")[:500] or "-",
            "request_summary": self.redact_payload(request_summary),
            "response_summary": self.redact_payload(response_summary),
            "extra": self.redact_payload(extra),
            "created_at": beijing_now(),
        }

        if self._writer_runs_in_current_loop():
            self._enqueue(payload)
        elif not self._stopping:
            # 脚本和单元测试未启动应用 lifespan 时保持原有的即时可见语义。
            try:
                await self._persist_batch([payload])
                await self.maybe_prune()
            except Exception:
                logger.exception("操作日志持久化失败，已忽略以保护核心业务")

        # 发送到 Kafka（异步，不阻塞主线程）
        self._send_to_kafka(
            trace_id,
            source_type,
            module,
            action,
            status,
            message,
            http_method,
            path,
            status_code,
            duration_ms,
            extra,
        )

    def _send_to_kafka(
        self,
        trace_id: str,
        source_type: str,
        module: str,
        action: str,
        status: str,
        message: str,
        http_method: str | None = None,
        path: str | None = None,
        status_code: int | None = None,
        duration_ms: int | None = None,
        extra: Any = None,
    ) -> None:
        """发送日志到 Kafka"""
        try:
            from app.analytics import kafka_producer

            if not kafka_producer._enabled:
                return

            # 构建事件数据
            event_data = {
                "trace_id": trace_id,
                "source_type": source_type,
                "module": module,
                "action": action,
                "status": status,
                "message": message,
                "http_method": http_method,
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
            }

            # 解析 extra 中的数据
            if extra and isinstance(extra, dict):
                # 提取查询关键词
                if "keyword" in extra:
                    event_data["keyword"] = extra["keyword"]
                # 提取订阅信息
                if "subscription_id" in extra:
                    event_data["subscription_id"] = extra["subscription_id"]
                if "title" in extra:
                    event_data["title"] = extra["title"]
                if "media_type" in extra:
                    event_data["media_type"] = extra["media_type"]
                # 提取来源信息
                if "source" in extra:
                    event_data["source"] = extra["source"]
                if "source_attempt_summary" in extra:
                    event_data["source_attempt_summary"] = extra[
                        "source_attempt_summary"
                    ]

            # 确定事件类型
            event_type = "api_request"
            if source_type == "api":
                if "search" in module.lower() or (path and "/search" in path):
                    event_type = "search_keyword"
                elif "subscription" in module.lower():
                    if "create" in action.lower():
                        event_type = "subscription_create"
                    elif "delete" in action.lower():
                        event_type = "subscription_delete"
                    elif "run" in action.lower():
                        event_type = "subscription_run"
                    elif "transfer" in action.lower():
                        event_type = "transfer_success"
            elif source_type == "background_task":
                if "subscription" in module.lower():
                    if "fetch" in action.lower():
                        event_type = "resource_fetch_success"
                    elif "transfer" in action.lower():
                        event_type = "transfer_success"

            kafka_producer.send(
                event_type=event_type,
                data=event_data,
                key=trace_id,
            )
        except Exception as e:
            logger.debug(f"Kafka 发送失败（忽略）: {e}")

    async def log_api_request(
        self,
        *,
        trace_id: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
        request_summary: Any = None,
        response_summary: Any = None,
        message: str = "",
    ) -> None:
        if status_code >= 500:
            status = "failed"
        elif status_code >= 400:
            status = "warning"
        else:
            status = "success"
        await self.log(
            trace_id=trace_id,
            source_type="api",
            module=self._build_module(path),
            action=f"{method} {path}",
            status=status,
            message=message or f"{method} {path} -> {status_code}",
            http_method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            request_summary=request_summary,
            response_summary=response_summary,
        )

    async def log_background_event(
        self,
        *,
        source_type: str,
        module: str,
        action: str,
        status: str,
        message: str,
        trace_id: str | None = None,
        extra: Any = None,
    ) -> None:
        await self.log(
            trace_id=str(trace_id or "background"),
            source_type=source_type,
            module=module,
            action=action,
            status=status,
            message=message,
            extra=extra,
        )

    async def get_latest_pan115_transfer_result(
        self,
        folder_name: str,
        *,
        since: datetime | None = None,
    ) -> dict[str, Any] | None:
        """查询指定文件夹最近一次 115 转存操作日志"""

        cleaned = str(folder_name or "").strip()
        if not cleaned:
            return None

        await self.flush()

        where_clauses = [
            OperationLog.module == "pan115",
            OperationLog.action == "transfer.save_to_folder",
            OperationLog.message.ilike(f"%{cleaned}%"),
        ]
        if since is not None:
            where_clauses.append(OperationLog.created_at >= since)

        async with async_session_maker() as db:
            result = await db.execute(
                select(OperationLog)
                .where(*where_clauses)
                .order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "status": str(row.status or ""),
                "message": str(row.message or ""),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "extra": row.extra,
            }

    async def prune(self, days: int = 30) -> int:
        await self.flush()
        return await self._prune_now(days)

    async def _prune_now(self, days: int = 30) -> int:
        ttl_days = max(1, int(days or 30))
        cutoff = beijing_now() - timedelta(days=ttl_days)
        async with async_session_maker() as db:
            result = await db.execute(
                delete(OperationLog).where(OperationLog.created_at < cutoff)
            )
            await db.commit()
            removed = int(result.rowcount or 0)
        self._last_pruned_at = beijing_now()
        return removed

    async def clear(self) -> int:
        await self.flush()
        async with async_session_maker() as db:
            result = await db.execute(delete(OperationLog))
            await db.commit()
            self._last_pruned_at = beijing_now()
            return int(result.rowcount or 0)

    async def maybe_prune(self, days: int = 30, interval_minutes: int = 60) -> None:
        now = beijing_now()
        if self._last_pruned_at and now - self._last_pruned_at < timedelta(
            minutes=max(1, interval_minutes)
        ):
            return
        await self._prune_now(days=days)


operation_log_service = OperationLogService()
