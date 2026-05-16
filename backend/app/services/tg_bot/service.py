import asyncio
import logging
from typing import Any

from telegram import Bot
from telegram.ext import Application

logger = logging.getLogger(__name__)


def _normalize_notify_chat_id(raw: Any) -> int | None:
    """将配置中的 Chat ID 转为整数（群组常为负数）。"""
    try:
        return int(str(raw).strip())
    except Exception:
        return None


class TgBotService:
    def __init__(self) -> None:
        self._app: Application | None = None
        self._running = False
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def bot(self) -> Bot | None:
        return self._app.bot if self._app else None

    def _get_settings(self) -> dict[str, Any]:
        from app.services.runtime_settings_service import runtime_settings_service
        return {
            "token": runtime_settings_service.get("tg_bot_token", ""),
            "enabled": runtime_settings_service.get("tg_bot_enabled", False),
            "allowed_users": runtime_settings_service.get("tg_bot_allowed_users", []),
            "notify_chat_ids": runtime_settings_service.get("tg_bot_notify_chat_ids", []),
        }

    async def start(self) -> None:
        async with self._lock:
            if self._running:
                return

            cfg = self._get_settings()
            if not cfg["enabled"] or not cfg["token"]:
                logger.info("TG Bot is disabled or token is empty, skipping start")
                return

            try:
                from .handlers import register_handlers

                builder = Application.builder().token(cfg["token"])
                self._app = builder.build()
                register_handlers(self._app, cfg["allowed_users"])

                await self._app.initialize()
                await self._app.start()
                await self._app.updater.start_polling(drop_pending_updates=True)
                self._running = True
                logger.info("TG Bot started successfully")
            except Exception:
                logger.exception("Failed to start TG Bot")
                self._app = None

    async def stop(self) -> None:
        async with self._lock:
            if not self._running or not self._app:
                return

            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
                logger.info("TG Bot stopped")
            except Exception:
                logger.exception("Error stopping TG Bot")
            finally:
                self._app = None
                self._running = False

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def send_notification(self, text: str, parse_mode: str = "HTML") -> None:
        cfg = self._get_settings()
        if not cfg["enabled"] or not cfg["token"]:
            return

        chat_ids = cfg.get("notify_chat_ids") or []
        if not chat_ids:
            logger.debug("TG Bot notify skipped: notify_chat_ids empty")
            return

        normalized_ids = []
        for raw in chat_ids:
            cid = _normalize_notify_chat_id(raw)
            if cid is not None:
                normalized_ids.append(cid)
        if not normalized_ids:
            logger.debug("TG Bot notify skipped: no valid chat ids")
            return

        async def _deliver(bot: Bot) -> None:
            for chat_id in normalized_ids:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode=parse_mode,
                    )
                except Exception:
                    logger.warning(
                        "Failed to send notification to chat %s", chat_id, exc_info=True
                    )

        if self._running and self._app and self._app.bot:
            await _deliver(self._app.bot)
            return

        try:
            bot = Bot(cfg["token"])
            async with bot:
                await _deliver(bot)
        except Exception:
            logger.warning(
                "TG Bot notify failed (standalone client, polling may be down)",
                exc_info=True,
            )

    def status(self) -> dict[str, Any]:
        cfg = self._get_settings()
        return {
            "enabled": cfg["enabled"],
            "running": self._running,
            "has_token": bool(cfg["token"]),
            "notify_chat_ids": cfg.get("notify_chat_ids", []),
            "allowed_users": cfg.get("allowed_users", []),
        }


tg_bot_service = TgBotService()
