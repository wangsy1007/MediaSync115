import asyncio
import logging
from typing import Any

from telegram import Bot
from telegram.error import NetworkError, TelegramError, TimedOut
from telegram.ext import Application

logger = logging.getLogger(__name__)

TG_BOT_START_TIMEOUT_SECONDS = 25.0
TG_BOT_STOP_TIMEOUT_SECONDS = 15.0


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

    async def _shutdown_app(self, app: Application) -> None:
        try:
            if getattr(app, "updater", None) and app.updater.running:
                await app.updater.stop()
        except Exception:
            logger.exception("Error stopping TG Bot updater")
        try:
            await app.stop()
            await app.shutdown()
        except Exception:
            logger.exception("Error shutting down TG Bot application")

    async def start(self) -> None:
        async with self._lock:
            if self._running:
                return

            cfg = self._get_settings()
            if not cfg["enabled"] or not cfg["token"]:
                logger.info("TG Bot is disabled or token is empty, skipping start")
                return

            partial_app: Application | None = None
            try:
                from .handlers import register_handlers

                builder = Application.builder().token(cfg["token"])
                partial_app = builder.build()
                register_handlers(partial_app, cfg["allowed_users"])
                self._app = partial_app

                await asyncio.wait_for(
                    self._finish_start(partial_app),
                    timeout=TG_BOT_START_TIMEOUT_SECONDS,
                )
                self._running = True
                logger.info("TG Bot started successfully")
            except (asyncio.TimeoutError, TimedOut):
                await self._abort_start(
                    partial_app,
                    "TG Bot 启动超时，主服务将继续运行；请检查 Token 与访问 Telegram 的网络，稍后在设置中重启 Bot",
                )
            except NetworkError as exc:
                await self._abort_start(
                    partial_app,
                    "TG Bot 网络异常，主服务将继续运行：%s",
                    exc,
                )
            except TelegramError:
                await self._abort_start(
                    partial_app,
                    "TG Bot 启动失败（Token 或 Telegram API 异常），主服务将继续运行",
                )
            except Exception:
                await self._abort_start(
                    partial_app,
                    "TG Bot 启动出现未知错误，主服务将继续运行",
                    exc_info=True,
                )

    async def _abort_start(
        self,
        partial_app: Application | None,
        message: str,
        *args: Any,
        exc_info: bool = False,
    ) -> None:
        if exc_info:
            logger.exception(message, *args)
        elif args:
            logger.error(message, *args)
        else:
            logger.error(message)
        if partial_app is not None:
            await self._shutdown_app(partial_app)
        self._app = None
        self._running = False

    async def _finish_start(self, app: Application) -> None:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        async with self._lock:
            if not self._running and not self._app:
                return

            app = self._app
            self._app = None
            self._running = False
            if not app:
                return

            try:
                await asyncio.wait_for(
                    self._shutdown_app(app),
                    timeout=TG_BOT_STOP_TIMEOUT_SECONDS,
                )
                logger.info("TG Bot stopped")
            except asyncio.TimeoutError:
                logger.error("TG Bot stop timed out, state cleared")
            except Exception:
                logger.exception("Error stopping TG Bot")

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
