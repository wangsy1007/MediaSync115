"""TG Bot 启动重试 / 重启合并 / 自愈调度测试。"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import Conflict, NetworkError

from app.services.tg_bot import service as tg_bot_module
from app.services.tg_bot.service import TgBotService


@pytest.fixture
def bot_service(monkeypatch: pytest.MonkeyPatch) -> TgBotService:
    svc = TgBotService()
    monkeypatch.setattr(tg_bot_module, "TG_BOT_START_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(tg_bot_module, "TG_BOT_START_RETRY_BASE_SECONDS", 0.01)
    monkeypatch.setattr(tg_bot_module, "TG_BOT_START_RETRY_MAX_SECONDS", 0.02)
    monkeypatch.setattr(tg_bot_module, "TG_BOT_CONFLICT_COOLDOWN_SECONDS", 0.01)
    monkeypatch.setattr(tg_bot_module, "TG_BOT_RECOVERY_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(tg_bot_module, "TG_BOT_START_TIMEOUT_SECONDS", 2.0)
    return svc


def _patch_settings(enabled: bool = True, token: str = "123:abc") -> Any:
    return patch.object(
        TgBotService,
        "_get_settings",
        return_value={
            "token": token,
            "enabled": enabled,
            "allowed_users": [],
            "notify_chat_ids": [],
        },
    )


@pytest.mark.asyncio
async def test_start_retries_on_network_error_then_succeeds(
    bot_service: TgBotService,
) -> None:
    app = MagicMock()
    app.bot = MagicMock()
    app.updater = MagicMock()
    app.updater.running = False
    app.initialize = AsyncMock()
    app.start = AsyncMock()
    app.stop = AsyncMock()
    app.shutdown = AsyncMock()
    app.updater.stop = AsyncMock()
    app.updater.start_polling = AsyncMock(
        side_effect=[NetworkError("boom"), None]
    )

    with (
        _patch_settings(),
        patch.object(bot_service, "_build_application", return_value=app),
        patch.object(bot_service, "_clear_webhook", new=AsyncMock()),
        patch.object(bot_service, "_resolve_telegram_proxy", return_value=None),
    ):
        await bot_service.start()

    assert bot_service.running is True
    assert bot_service.last_error == ""
    assert app.updater.start_polling.await_count == 2


@pytest.mark.asyncio
async def test_start_conflict_then_recovers(bot_service: TgBotService) -> None:
    app = MagicMock()
    app.bot = MagicMock()
    app.updater = MagicMock()
    app.updater.running = False
    app.initialize = AsyncMock()
    app.start = AsyncMock()
    app.stop = AsyncMock()
    app.shutdown = AsyncMock()
    app.updater.stop = AsyncMock()
    app.updater.start_polling = AsyncMock(
        side_effect=[Conflict("terminated by other getUpdates"), None]
    )

    with (
        _patch_settings(),
        patch.object(bot_service, "_build_application", return_value=app),
        patch.object(bot_service, "_clear_webhook", new=AsyncMock()) as clear_webhook,
        patch.object(bot_service, "_resolve_telegram_proxy", return_value=None),
    ):
        await bot_service.start()

    assert bot_service.running is True
    assert clear_webhook.await_count >= 1
    assert "冲突" not in bot_service.last_error


@pytest.mark.asyncio
async def test_start_failure_schedules_recovery(bot_service: TgBotService) -> None:
    app = MagicMock()
    app.bot = MagicMock()
    app.updater = MagicMock()
    app.updater.running = False
    app.initialize = AsyncMock()
    app.start = AsyncMock()
    app.stop = AsyncMock()
    app.shutdown = AsyncMock()
    app.updater.stop = AsyncMock()
    app.updater.start_polling = AsyncMock(side_effect=NetworkError("down"))

    with (
        _patch_settings(),
        patch.object(bot_service, "_build_application", return_value=app),
        patch.object(bot_service, "_clear_webhook", new=AsyncMock()),
        patch.object(bot_service, "_resolve_telegram_proxy", return_value=None),
    ):
        await bot_service.start()
        assert bot_service.running is False
        assert "无法连接" in bot_service.last_error
        assert bot_service.status()["recovery_scheduled"] is True
        bot_service._cancel_recovery()


@pytest.mark.asyncio
async def test_restart_requests_are_serialized(bot_service: TgBotService) -> None:
    active = 0
    max_active = 0
    loops = 0

    async def fake_stop() -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.03)
        active -= 1

    async def fake_start() -> None:
        nonlocal loops
        loops += 1
        bot_service._running = True

    with (
        patch.object(bot_service, "stop", side_effect=fake_stop),
        patch.object(bot_service, "start", side_effect=fake_start),
    ):
        t1 = asyncio.create_task(bot_service.restart())
        await asyncio.sleep(0.005)
        t2 = asyncio.create_task(bot_service.restart())
        await asyncio.gather(t1, t2)

    # 不允许两个 restart 循环并行执行
    assert max_active == 1
    assert loops >= 1
