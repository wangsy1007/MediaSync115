import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete

from app.core.database import async_session_maker
from app.models.models import OperationLog

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


class OperationLogService:
    def __init__(self) -> None:
        self._last_pruned_at: datetime | None = None

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
        row = OperationLog(
            trace_id=str(trace_id or "").strip() or "unknown",
            source_type=str(source_type or "unknown")[:40],
            module=str(module or "unknown")[:60],
            action=str(action or "unknown")[:255],
            status=str(status or "info")[:20],
            http_method=(str(http_method)[:10] if http_method else None),
            path=(str(path)[:255] if path else None),
            status_code=status_code,
            duration_ms=duration_ms,
            message=str(message or "")[:500] or "-",
            request_summary=self.redact_payload(request_summary),
            response_summary=self.redact_payload(response_summary),
            extra=self.redact_payload(extra),
        )
        async with async_session_maker() as db:
            db.add(row)
            await db.commit()
        await self.maybe_prune()

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

    async def prune(self, days: int = 30) -> int:
        ttl_days = max(1, int(days or 30))
        cutoff = datetime.utcnow() - timedelta(days=ttl_days)
        async with async_session_maker() as db:
            result = await db.execute(
                delete(OperationLog).where(OperationLog.created_at < cutoff)
            )
            await db.commit()
            return int(result.rowcount or 0)

    async def clear(self) -> int:
        async with async_session_maker() as db:
            result = await db.execute(delete(OperationLog))
            await db.commit()
            self._last_pruned_at = datetime.utcnow()
            return int(result.rowcount or 0)

    async def maybe_prune(self, days: int = 30, interval_minutes: int = 60) -> None:
        now = datetime.utcnow()
        if self._last_pruned_at and now - self._last_pruned_at < timedelta(
            minutes=max(1, interval_minutes)
        ):
            return
        await self.prune(days=days)
        self._last_pruned_at = now


operation_log_service = OperationLogService()
