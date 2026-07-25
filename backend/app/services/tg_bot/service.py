import asyncio
import logging
from typing import Any

from telegram import Bot
from telegram.error import Conflict, NetworkError, TelegramError, TimedOut
from telegram.ext import Application

logger = logging.getLogger(__name__)

TG_BOT_START_TIMEOUT_SECONDS = 25.0
TG_BOT_STOP_TIMEOUT_SECONDS = 15.0
TG_BOT_START_MAX_ATTEMPTS = 5
TG_BOT_START_RETRY_BASE_SECONDS = 2.0
TG_BOT_START_RETRY_MAX_SECONDS = 30.0
TG_BOT_RECOVERY_INTERVAL_SECONDS = 60.0
TG_BOT_CONFLICT_COOLDOWN_SECONDS = 8.0


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
        self._restart_schedule_lock = asyncio.Lock()
        self._last_error: str = ""
        self._restart_task: asyncio.Task | None = None
        self._recovery_task: asyncio.Task | None = None
        self._start_task: asyncio.Task | None = None
        self._restart_requested = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def last_error(self) -> str:
        return self._last_error

    def _resolve_telegram_proxy(self) -> str | None:
        from app.utils.proxy import proxy_manager

        return proxy_manager.get_effective_https_proxy()

    def _build_httpx_request(self, proxy_url: str | None = None) -> "HTTPXRequest":
        """构建 Telegram HTTP 客户端，禁用系统环境代理避免 Docker 注入无效 HTTP_PROXY。"""
        from telegram.request import HTTPXRequest

        return HTTPXRequest(
            proxy=proxy_url,
            connect_timeout=10.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=10.0,
            httpx_kwargs={"trust_env": False},
        )

    def _build_application(self, token: str) -> Application:
        from .handlers import register_handlers

        proxy_url = self._resolve_telegram_proxy()
        request = self._build_httpx_request(proxy_url)
        get_updates_request = self._build_httpx_request(proxy_url)
        if proxy_url:
            logger.info("TG Bot 使用代理: %s", proxy_url)
        else:
            logger.info("TG Bot 使用直连（已忽略系统环境变量 HTTP_PROXY）")
        builder = (
            Application.builder()
            .token(token)
            .request(request)
            .get_updates_request(get_updates_request)
        )
        app = builder.build()
        cfg = self._get_settings()
        register_handlers(app, cfg["allowed_users"])
        return app

    def _build_standalone_bot(self, token: str) -> Bot:
        proxy_url = self._resolve_telegram_proxy()
        return Bot(token, request=self._build_httpx_request(proxy_url))

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
        except RuntimeError:
            pass
        try:
            await app.shutdown()
        except Exception:
            logger.exception("Error shutting down TG Bot application")

    async def _clear_webhook(self, bot: Bot) -> None:
        """轮询前清理 webhook，避免与历史 webhook / 其他实例残留冲突。"""
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            logger.warning("TG Bot delete_webhook failed", exc_info=True)

    async def _finish_start_polling(self, app: Application) -> None:
        await app.initialize()
        await self._clear_webhook(app.bot)
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

    def _retry_delay(self, attempt: int) -> float:
        delay = TG_BOT_START_RETRY_BASE_SECONDS * (2 ** max(0, attempt - 1))
        return min(delay, TG_BOT_START_RETRY_MAX_SECONDS)

    async def start(self) -> None:
        async with self._lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        if self._running:
            return

        cfg = self._get_settings()
        if not cfg["enabled"] or not cfg["token"]:
            logger.info("TG Bot is disabled or token is empty, skipping start")
            self._last_error = ""
            self._cancel_recovery()
            return

        last_message = ""
        for attempt in range(1, TG_BOT_START_MAX_ATTEMPTS + 1):
            partial_app: Application | None = None
            try:
                partial_app = self._build_application(cfg["token"])
                self._app = partial_app

                await asyncio.wait_for(
                    self._finish_start_polling(partial_app),
                    timeout=TG_BOT_START_TIMEOUT_SECONDS,
                )
                self._running = True
                self._last_error = ""
                self._cancel_recovery()
                logger.info("TG Bot started successfully (attempt %s)", attempt)
                return
            except Conflict as exc:
                last_message = (
                    "TG Bot 与其他 getUpdates 实例冲突（同一 Token 只能有一个轮询进程）。"
                    "已自动清理 webhook 并稍后重试；请确认未在其他机器/容器使用同一 Token"
                )
                logger.warning(
                    "TG Bot Conflict on start attempt %s/%s: %s",
                    attempt,
                    TG_BOT_START_MAX_ATTEMPTS,
                    exc,
                )
                await self._abort_start(partial_app, last_message, schedule_recovery=False)
                await asyncio.sleep(TG_BOT_CONFLICT_COOLDOWN_SECONDS)
            except (asyncio.TimeoutError, TimedOut) as exc:
                last_message = (
                    "TG Bot 启动超时，请检查 Token 与访问 Telegram 的网络，"
                    "或在设置中配置可用代理后重启 Bot"
                )
                logger.warning(
                    "TG Bot timeout on start attempt %s/%s: %s",
                    attempt,
                    TG_BOT_START_MAX_ATTEMPTS,
                    exc,
                )
                await self._abort_start(partial_app, last_message, schedule_recovery=False)
            except NetworkError as exc:
                last_message = (
                    f"TG Bot 无法连接 Telegram API：{exc}。"
                    "如在 Docker/国内环境，请在「代理设置」中配置可访问 Telegram 的 HTTPS 代理"
                )
                logger.warning(
                    "TG Bot network error on start attempt %s/%s: %s",
                    attempt,
                    TG_BOT_START_MAX_ATTEMPTS,
                    exc,
                )
                await self._abort_start(partial_app, last_message, schedule_recovery=False)
            except TelegramError as exc:
                last_message = (
                    f"TG Bot 启动失败（Token 无效或 Telegram API 异常）：{exc}"
                )
                logger.error(
                    "TG Bot telegram error on start attempt %s/%s: %s",
                    attempt,
                    TG_BOT_START_MAX_ATTEMPTS,
                    exc,
                )
                await self._abort_start(partial_app, last_message, schedule_recovery=False)
                # Token 无效时无需立刻打满重试，交给 recovery 低频自愈
                break
            except Exception:
                last_message = "TG Bot 启动出现未知错误，请查看服务日志"
                await self._abort_start(
                    partial_app,
                    last_message,
                    exc_info=True,
                    schedule_recovery=False,
                )

            if attempt < TG_BOT_START_MAX_ATTEMPTS:
                delay = self._retry_delay(attempt)
                logger.info("TG Bot will retry start in %.1fs", delay)
                await asyncio.sleep(delay)

        self._last_error = last_message or "TG Bot 启动失败"
        self._schedule_recovery()

    async def _abort_start(
        self,
        partial_app: Application | None,
        message: str,
        *args: Any,
        exc_info: bool = False,
        schedule_recovery: bool = True,
    ) -> None:
        if exc_info:
            logger.exception(message, *args)
        elif args:
            logger.error(message, *args)
        else:
            logger.error(message)
        self._last_error = str(message)
        if partial_app is not None:
            await self._shutdown_app(partial_app)
        self._app = None
        self._running = False
        if schedule_recovery:
            self._schedule_recovery()

    def _cancel_recovery(self) -> None:
        task = self._recovery_task
        self._recovery_task = None
        if task and not task.done():
            task.cancel()

    def _schedule_recovery(self) -> None:
        """启动失败后后台周期重试，避免进程起来后永久处于未运行状态。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if self._recovery_task and not self._recovery_task.done():
            return

        async def _recover() -> None:
            while True:
                await asyncio.sleep(TG_BOT_RECOVERY_INTERVAL_SECONDS)
                cfg = self._get_settings()
                if not cfg["enabled"] or not cfg["token"]:
                    self._last_error = ""
                    return
                if self._running:
                    return
                logger.info("TG Bot recovery: retrying start")
                try:
                    async with self._lock:
                        await self._start_locked()
                except Exception:
                    logger.exception("TG Bot recovery attempt failed")
                if self._running:
                    return

        self._recovery_task = loop.create_task(_recover())

    async def stop(self) -> None:
        self._cancel_recovery()
        async with self._lock:
            if not self._running and not self._app:
                return

            app = self._app
            self._app = None
            self._running = False
            if not app:
                return

            token = ""
            try:
                token = str(self._get_settings().get("token") or "")
            except Exception:
                token = ""

            try:
                await asyncio.wait_for(
                    self._shutdown_app(app),
                    timeout=TG_BOT_STOP_TIMEOUT_SECONDS,
                )
                # shutdown 后原 bot 会话可能已关闭，用独立客户端清理 webhook
                if token:
                    try:
                        cleanup_bot = self._build_standalone_bot(token)
                        async with cleanup_bot:
                            await self._clear_webhook(cleanup_bot)
                    except Exception:
                        logger.warning(
                            "TG Bot post-stop webhook cleanup failed",
                            exc_info=True,
                        )
                self._last_error = ""
                logger.info("TG Bot stopped")
            except asyncio.TimeoutError:
                logger.error("TG Bot stop timed out, state cleared")
            except Exception:
                logger.exception("Error stopping TG Bot")

    async def _run_restart_loop(self) -> None:
        while self._restart_requested:
            self._restart_requested = False
            await self.stop()
            # 给 Telegram 侧释放上一次 getUpdates 会话的缓冲时间
            await asyncio.sleep(TG_BOT_CONFLICT_COOLDOWN_SECONDS)
            await self.start()

    async def restart(self) -> None:
        """串行重启：多次调用会合并为一次，避免连点导致双 polling。"""
        self._restart_requested = True
        async with self._restart_schedule_lock:
            if self._restart_task and not self._restart_task.done():
                logger.info("TG Bot restart already in progress, coalescing request")
                task = self._restart_task
            else:
                task = asyncio.create_task(self._run_restart_loop())
                self._restart_task = task
        try:
            await task
        finally:
            async with self._restart_schedule_lock:
                if self._restart_task is task and task.done():
                    self._restart_task = None

    def request_start(self) -> None:
        """非阻塞启动（供应用 lifespan 使用，避免阻塞健康检查）。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._start_task and not self._start_task.done():
            return
        self._start_task = loop.create_task(self.start())

    def request_restart(self) -> None:
        """非阻塞触发重启（供设置保存后台任务使用）。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.restart())

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
            bot = self._build_standalone_bot(cfg["token"])
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
            "last_error": self._last_error,
            "using_proxy": bool(self._resolve_telegram_proxy()),
            "recovery_scheduled": bool(
                self._recovery_task and not self._recovery_task.done()
            ),
        }


tg_bot_service = TgBotService()
