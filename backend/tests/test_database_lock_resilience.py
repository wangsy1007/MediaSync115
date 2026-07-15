import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text

from app.core.database import (
    async_session_maker,
    ensure_tables_exist,
    engine,
    is_database_locked_error,
)
from app.models.models import OperationLog
from app.services.operation_log_service import OperationLogService


@pytest.mark.asyncio
async def test_sqlite_connection_pragmas_are_applied_to_new_connections() -> None:
    async with engine.connect() as connection:
        busy_timeout = await connection.scalar(text("PRAGMA busy_timeout"))
        foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))

    assert busy_timeout == 60000
    assert foreign_keys == 1


def test_database_lock_error_recognizes_sqlite_lock_variants() -> None:
    from sqlalchemy.exc import OperationalError

    for message in (
        "database is locked",
        "database table is locked: operation_logs",
        "database schema is locked: main",
    ):
        exc = OperationalError("INSERT", {}, Exception(message))
        assert is_database_locked_error(exc) is True

    assert is_database_locked_error(RuntimeError("database is locked")) is False


@pytest.mark.asyncio
async def test_operation_log_queue_does_not_block_lock_holding_business_transaction() -> None:
    await ensure_tables_exist("operation_logs")
    service = OperationLogService(
        busy_timeout_ms=100,
        lock_retry_attempts=10,
    )
    trace_id = f"lock-test-{uuid4().hex}"
    await service.start()

    try:
        async with async_session_maker() as blocker:
            await blocker.execute(text("BEGIN IMMEDIATE"))

            # 即使后台写入器正在等待 SQLite 写锁，业务侧记录日志也必须立即返回。
            await asyncio.wait_for(
                service.log_background_event(
                    source_type="test",
                    module="database",
                    action="lock.queue",
                    status="success",
                    message="queued while another transaction owns the write lock",
                    trace_id=trace_id,
                ),
                timeout=0.2,
            )
            await asyncio.sleep(0.15)
            await blocker.commit()

        await asyncio.wait_for(service.flush(), timeout=5)
        async with async_session_maker() as db:
            row = await db.scalar(
                select(OperationLog).where(OperationLog.trace_id == trace_id)
            )
            assert row is not None
            await db.execute(delete(OperationLog).where(OperationLog.trace_id == trace_id))
            await db.commit()
    finally:
        await service.stop()
