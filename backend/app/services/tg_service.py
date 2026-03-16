import re
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote, urlencode, urlparse
from uuid import uuid4

from app.core.config import settings
from app.utils.proxy import proxy_manager

TELETHON_AVAILABLE = False
TELETHON_IMPORT_ERROR = ""
TelegramClient = None
StringSession = None
MessageEntityTextUrl = object
SessionPasswordNeededError = Exception
PhoneCodeInvalidError = Exception
PhoneCodeExpiredError = Exception
FloodWaitError = Exception
UsernameInvalidError = Exception
UsernameNotOccupiedError = Exception
ChannelPrivateError = Exception


def _load_telethon() -> None:
    global TELETHON_AVAILABLE
    global TELETHON_IMPORT_ERROR
    global TelegramClient
    global StringSession
    global MessageEntityTextUrl
    global SessionPasswordNeededError
    global PhoneCodeInvalidError
    global PhoneCodeExpiredError
    global FloodWaitError
    global UsernameInvalidError
    global UsernameNotOccupiedError
    global ChannelPrivateError

    if TELETHON_AVAILABLE:
        return
    if TELETHON_IMPORT_ERROR:
        raise RuntimeError(f"Telethon 未安装或加载失败: {TELETHON_IMPORT_ERROR}")

    try:
        from telethon import TelegramClient as telethon_client
        from telethon.errors import (
            ChannelPrivateError as telethon_channel_private_error,
            FloodWaitError as telethon_flood_wait_error,
            PhoneCodeExpiredError as telethon_phone_code_expired_error,
            PhoneCodeInvalidError as telethon_phone_code_invalid_error,
            SessionPasswordNeededError as telethon_session_password_needed_error,
            UsernameInvalidError as telethon_username_invalid_error,
            UsernameNotOccupiedError as telethon_username_not_occupied_error,
        )
        from telethon.sessions import StringSession as telethon_string_session
        from telethon.tl.types import MessageEntityTextUrl as telethon_message_entity_text_url
    except Exception as exc:  # pragma: no cover - runtime fallback
        TELETHON_IMPORT_ERROR = str(exc)
        raise RuntimeError(f"Telethon 未安装或加载失败: {TELETHON_IMPORT_ERROR}") from exc

    TelegramClient = telethon_client
    StringSession = telethon_string_session
    MessageEntityTextUrl = telethon_message_entity_text_url
    SessionPasswordNeededError = telethon_session_password_needed_error
    PhoneCodeInvalidError = telethon_phone_code_invalid_error
    PhoneCodeExpiredError = telethon_phone_code_expired_error
    FloodWaitError = telethon_flood_wait_error
    UsernameInvalidError = telethon_username_invalid_error
    UsernameNotOccupiedError = telethon_username_not_occupied_error
    ChannelPrivateError = telethon_channel_private_error
    TELETHON_AVAILABLE = True


_PAN115_SHARE_URL_PATTERN = re.compile(
    r"(https?://(?:115(?:cdn)?\.com/s/[A-Za-z0-9]+(?:[^\s\"'<>]*)?|share\.115\.com/[A-Za-z0-9]+(?:[^\s\"'<>]*)?))",
    re.IGNORECASE,
)
_PAN115_RECEIVE_CODE_PATTERN = re.compile(
    r"(?:提取码|提取碼|访问码|訪問碼|密码|密碼|password|pwd)\s*[:：=]?\s*([A-Za-z0-9]{4})",
    re.IGNORECASE,
)
_PAN115_SHARE_CODE_HINT_PATTERN = re.compile(
    r"(?:分享码|分享碼|share(?:_|\s*)code)\s*[:：=]?\s*([A-Za-z0-9]{6,32})",
    re.IGNORECASE,
)


class TgService:
    def __init__(self) -> None:
        self._api_id = str(settings.TG_API_ID or "").strip()
        self._api_hash = str(settings.TG_API_HASH or "").strip()
        self._phone = str(settings.TG_PHONE or "").strip()
        self._session = str(settings.TG_SESSION or "").strip()
        self._channels = self._parse_channels(settings.TG_CHANNEL_USERNAMES)
        self._search_days = max(1, int(settings.TG_SEARCH_DAYS or 30))
        self._max_messages = max(20, int(settings.TG_MAX_MESSAGES_PER_CHANNEL or 200))
        self._user_agent = "MediaSync115/1.0 (+https://localhost)"
        self._qr_pending: dict[str, dict[str, Any]] = {}
        self._qr_lock = asyncio.Lock()

    @staticmethod
    def _parse_channels(raw: object) -> list[str]:
        if isinstance(raw, list):
            source_items = [str(item or "").strip() for item in raw]
        else:
            text = str(raw or "")
            source_items = [part.strip() for part in re.split(r"[\n,，;；]+", text)]

        normalized: list[str] = []
        seen: set[str] = set()
        for item in source_items:
            if not item:
                continue
            value = item[1:] if item.startswith("@") else item
            value = value.strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(value)
        return normalized

    @staticmethod
    def _build_proxy(proxy_value: str) -> tuple[Any, ...] | None:
        value = str(proxy_value or "").strip()
        if not value:
            return None

        if "://" not in value:
            value = f"socks5://{value}"

        parsed = urlparse(value)
        scheme = str(parsed.scheme or "").strip().lower()
        host = str(parsed.hostname or "").strip()
        port = parsed.port
        if scheme == "socks":
            scheme = "socks5"
        if scheme not in {"socks5", "socks4", "http", "https"}:
            return None
        if not host or port is None:
            return None

        username = unquote(parsed.username) if parsed.username else None
        password = unquote(parsed.password) if parsed.password else None
        if username is not None or password is not None:
            return (scheme, host, int(port), True, username, password)
        return (scheme, host, int(port))

    def _resolve_proxy(self) -> tuple[Any, ...] | None:
        for scheme in ("socks5", "https", "http"):
            fallback_proxy = proxy_manager.get_proxy_for_scheme(scheme)
            parsed_proxy = self._build_proxy(str(fallback_proxy or ""))
            if parsed_proxy:
                return parsed_proxy
        return None

    def set_config(
        self,
        *,
        api_id: str | None = None,
        api_hash: str | None = None,
        phone: str | None = None,
        session: str | None = None,
        channels: list[str] | str | None = None,
        search_days: int | None = None,
        max_messages: int | None = None,
    ) -> None:
        if api_id is not None:
            self._api_id = str(api_id or "").strip()
        if api_hash is not None:
            self._api_hash = str(api_hash or "").strip()
        if phone is not None:
            self._phone = str(phone or "").strip()
        if session is not None:
            self._session = str(session or "").strip()
        if channels is not None:
            self._channels = self._parse_channels(channels)
        if search_days is not None:
            try:
                self._search_days = max(1, int(search_days))
            except Exception:
                pass
        if max_messages is not None:
            try:
                self._max_messages = max(20, int(max_messages))
            except Exception:
                pass

    def get_session(self) -> str:
        return self._session

    def clear_session(self) -> None:
        self._session = ""

    async def _clear_expired_qr_pending(self) -> None:
        now = datetime.now(timezone.utc)
        expired_tokens: list[str] = []
        async with self._qr_lock:
            for token, item in self._qr_pending.items():
                expires_at: datetime = item.get("expires_at") or now
                created_at: datetime = item.get("created_at") or now
                state = str(item.get("state") or "pending")
                terminal_ttl_seconds = 600
                if now >= expires_at or (state != "pending" and (now - created_at).total_seconds() > terminal_ttl_seconds):
                    expired_tokens.append(token)
            expired_items = [self._qr_pending.pop(token, None) for token in expired_tokens]
        for item in expired_items:
            if not item:
                continue
            task = item.get("task")
            if task and not task.done():
                task.cancel()
            client = item.get("client")
            try:
                if client:
                    await client.disconnect()
            except Exception:
                pass

    async def _await_qr_login(self, token: str) -> None:
        async with self._qr_lock:
            item = self._qr_pending.get(token)
        if not item:
            return
        qr_login = item.get("qr_login")
        client = item.get("client")
        if not qr_login or not client:
            async with self._qr_lock:
                self._qr_pending.pop(token, None)
            return
        try:
            user = await qr_login.wait(timeout=240)
            final_session = str(client.session.save() or "").strip()
            if final_session:
                self._session = final_session
            async with self._qr_lock:
                current = self._qr_pending.get(token)
                if current:
                    current["state"] = "authorized"
                    current["session"] = final_session
                    current["user"] = self._serialize_user(user)
                    current["message"] = "扫码登录成功"
        except SessionPasswordNeededError:
            temp_session = str(client.session.save() or "").strip()
            async with self._qr_lock:
                current = self._qr_pending.get(token)
                if current:
                    current["state"] = "need_password"
                    current["session"] = temp_session
                    current["message"] = "账号开启了二步验证，请输入密码"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            async with self._qr_lock:
                current = self._qr_pending.get(token)
                if current:
                    current["state"] = "failed"
                    current["message"] = str(exc)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    def _ensure_dependency(self) -> None:
        _load_telethon()

    def _ensure_login_config(self) -> None:
        self._ensure_dependency()
        if not self._api_id or not self._api_hash:
            raise RuntimeError("Telegram API ID / API HASH 未配置")

    def _ensure_search_config(self) -> None:
        self._ensure_login_config()
        if not self._session:
            raise RuntimeError("Telegram 尚未登录，请先在设置页完成登录")
        if not self._channels:
            raise RuntimeError("Telegram 频道列表为空，请先在设置中配置频道")

    def _build_client(self, session_value: str) -> "TelegramClient":
        self._ensure_login_config()
        api_id = int(str(self._api_id).strip())
        proxy = self._resolve_proxy()
        return TelegramClient(
            StringSession(session_value),
            api_id=api_id,
            api_hash=self._api_hash,
            proxy=proxy,
            device_model="MediaSync115",
            system_version="Linux",
            app_version="1.0.3",
            system_lang_code="zh-CN",
            lang_code="zh-CN",
        )

    @staticmethod
    def _is_likely_115_share_identifier(value: str) -> bool:
        raw = str(value or "").strip()
        if not raw:
            return False
        if raw.startswith(("http://", "https://", "//")):
            lowered = raw.lower()
            return "115.com" in lowered or "115cdn.com" in lowered or "anxia.com" in lowered
        return bool(re.match(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]{4})?$", raw))

    @staticmethod
    def _extract_share_link_from_text(text: str) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return []

        links: list[str] = []
        seen: set[str] = set()
        receive_code = ""
        receive_match = _PAN115_RECEIVE_CODE_PATTERN.search(raw)
        if receive_match:
            receive_code = receive_match.group(1).strip()

        for matched in _PAN115_SHARE_URL_PATTERN.finditer(raw):
            url = str(matched.group(1) or "").strip()
            if not url:
                continue
            if receive_code and "password=" not in url.lower() and "pwd=" not in url.lower():
                joiner = "&" if "?" in url else "?"
                url = f"{url}{joiner}{urlencode({'password': receive_code})}"
            key = url.lower()
            if key in seen:
                continue
            seen.add(key)
            links.append(url)

        if links:
            return links

        share_code_match = _PAN115_SHARE_CODE_HINT_PATTERN.search(raw)
        if share_code_match:
            share_code = share_code_match.group(1).strip()
            if share_code:
                if receive_code:
                    return [f"{share_code}-{receive_code}"]
                return [share_code]
        return []

    @staticmethod
    def _build_resource_name(text: str, fallback: str) -> str:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        for line in lines:
            if "115.com/s/" in line or "share.115.com/" in line:
                continue
            return line[:160]
        return fallback

    @staticmethod
    def _normalize_for_match(value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        text = re.sub(r"[`~!@#$%^&*()_+=\[\]{}\\|;:'\",.<>/?，。！？：；【】（）《》、·\-]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _extract_year(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        matched = re.search(r"(19\d{2}|20\d{2})", text)
        return matched.group(1) if matched else ""

    @staticmethod
    def _title_tokens(value: str) -> list[str]:
        normalized = TgService._normalize_for_match(value)
        if not normalized:
            return []
        return [part for part in normalized.split(" ") if part and len(part) >= 2]

    def _score_row_relevance(
        self,
        *,
        row_title: str,
        row_overview: str,
        expected_title: str,
        expected_original_title: str,
        expected_year: str,
    ) -> tuple[int, str, bool]:
        title_norm = self._normalize_for_match(row_title)
        overview_norm = self._normalize_for_match(row_overview)
        full_text = f"{title_norm} {overview_norm}".strip()
        exp_title_norm = self._normalize_for_match(expected_title)
        exp_original_norm = self._normalize_for_match(expected_original_title)
        title_tokens = self._title_tokens(expected_title)
        original_tokens = self._title_tokens(expected_original_title)

        score = 0
        reasons: list[str] = []
        strong_hit = False

        if exp_title_norm and exp_title_norm in title_norm:
            score += 60
            strong_hit = True
            reasons.append("title_exact")
        elif exp_title_norm and exp_title_norm in full_text:
            score += 45
            strong_hit = True
            reasons.append("title_phrase")

        if exp_original_norm and exp_original_norm in title_norm:
            score += 45
            strong_hit = True
            reasons.append("original_exact")
        elif exp_original_norm and exp_original_norm in full_text:
            score += 30
            strong_hit = True
            reasons.append("original_phrase")

        if title_tokens and all(token in full_text for token in title_tokens):
            score += 20
            reasons.append("title_tokens")
        if original_tokens and all(token in full_text for token in original_tokens):
            score += 15
            reasons.append("original_tokens")

        normalized_year = self._extract_year(expected_year)
        if normalized_year:
            if normalized_year in full_text:
                score += 20
                reasons.append("year")
            else:
                score -= 40
                reasons.append("year_missing")
        return score, ",".join(reasons) if reasons else "none", strong_hit

    def _build_rows_from_message(
        self,
        *,
        channel: str,
        message: Any,
        normalized_media: str,
        seen: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        msg_date = getattr(message, "date", None)
        if msg_date and msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)

        raw_text = str(getattr(message, "raw_text", "") or "")
        message_text = str(getattr(message, "message", "") or "")
        links: list[str] = []
        links.extend(self._extract_share_link_from_text(raw_text))
        links.extend(self._extract_share_link_from_text(message_text))
        entities = getattr(message, "entities", None) or []
        for ent in entities:
            if isinstance(ent, MessageEntityTextUrl):
                links.extend(self._extract_share_link_from_text(str(getattr(ent, "url", "") or "")))
        if not links:
            return []

        rows: list[dict[str, Any]] = []
        for index, share_link in enumerate(links):
            key = f"{str(channel).lower()}|{str(getattr(message, 'id', 0))}|{share_link.lower()}"
            if seen is not None and key in seen:
                continue
            if seen is not None:
                seen.add(key)
            row_id = f"tg-{str(channel).replace('@', '')}-{getattr(message, 'id', 0)}-{index}"
            title_fallback = f"Telegram 资源 {getattr(message, 'id', 0)}"
            resource_name = self._build_resource_name(raw_text or message_text, title_fallback)
            rows.append(
                {
                    "id": row_id,
                    "media_type": "resource",
                    "title": resource_name,
                    "name": resource_name,
                    "resource_name": resource_name,
                    "overview": (raw_text or message_text)[:300],
                    "poster_path": "",
                    "source_service": "tg",
                    "pan115_share_link": share_link,
                    "share_link": share_link,
                    "pan115_savable": self._is_likely_115_share_identifier(share_link),
                    "tg_channel": str(channel),
                    "tg_message_id": int(getattr(message, "id", 0) or 0),
                    "tg_message_date": msg_date.isoformat() if msg_date else "",
                    "tg_media_type_hint": normalized_media,
                }
            )
        return rows

    async def send_login_code(self, phone: str | None = None) -> dict[str, Any]:
        self._ensure_login_config()
        final_phone = str(phone or self._phone or "").strip()
        if not final_phone:
            raise RuntimeError("Telegram 手机号未配置")

        client = self._build_client("")
        try:
            await client.connect()
            sent = await client.send_code_request(final_phone)
            temp_session = client.session.save()
            return {
                "phone": final_phone,
                "phone_code_hash": str(sent.phone_code_hash or ""),
                "session": temp_session,
            }
        except FloodWaitError as exc:
            raise RuntimeError(f"触发 Telegram 频控，请 {int(exc.seconds)} 秒后重试")
        finally:
            await client.disconnect()

    async def verify_login_code(
        self,
        *,
        phone: str,
        code: str,
        phone_code_hash: str,
        session: str,
    ) -> dict[str, Any]:
        self._ensure_login_config()
        client = self._build_client(session)
        try:
            await client.connect()
            try:
                user = await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            except SessionPasswordNeededError:
                return {
                    "need_password": True,
                    "session": client.session.save(),
                }
            except PhoneCodeInvalidError:
                raise RuntimeError("验证码无效")
            except PhoneCodeExpiredError:
                raise RuntimeError("验证码已过期，请重新发送")

            final_session = client.session.save()
            self._session = final_session
            self._phone = str(phone or "").strip()
            return {
                "need_password": False,
                "session": final_session,
                "user": self._serialize_user(user),
            }
        finally:
            await client.disconnect()

    async def verify_login_password(self, *, password: str, session: str) -> dict[str, Any]:
        self._ensure_login_config()
        pwd = str(password or "").strip()
        if not pwd:
            raise RuntimeError("二步验证密码不能为空")
        client = self._build_client(session)
        try:
            await client.connect()
            user = await client.sign_in(password=pwd)
            final_session = client.session.save()
            self._session = final_session
            return {
                "need_password": False,
                "session": final_session,
                "user": self._serialize_user(user),
            }
        finally:
            await client.disconnect()

    async def import_session(self, session: str) -> dict[str, Any]:
        self._ensure_login_config()
        raw = str(session or "").strip()
        if not raw:
            raise RuntimeError("会话串不能为空")
        client = self._build_client(raw)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError("会话串无效或已过期，请重新获取")
            user = await client.get_me()
            final_session = client.session.save()
            self._session = str(final_session or "").strip()
            return {
                "session": self._session,
                "user": self._serialize_user(user),
            }
        finally:
            await client.disconnect()

    async def start_qr_login(self) -> dict[str, Any]:
        self._ensure_login_config()
        await self._clear_expired_qr_pending()
        client = self._build_client("")
        try:
            await client.connect()
            qr_login = await client.qr_login()
            token = uuid4().hex
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=240)
            async with self._qr_lock:
                self._qr_pending[token] = {
                    "client": client,
                    "qr_login": qr_login,
                    "created_at": datetime.now(timezone.utc),
                    "expires_at": expires_at,
                    "state": "pending",
                    "session": "",
                    "user": None,
                    "message": "等待扫码确认",
                    "task": None,
                }
                task = asyncio.create_task(self._await_qr_login(token))
                self._qr_pending[token]["task"] = task
            return {
                "token": token,
                "url": str(getattr(qr_login, "url", "") or ""),
                "expires_at": expires_at.isoformat(),
                "expire_seconds": 240,
            }
        except Exception:
            try:
                await client.disconnect()
            except Exception:
                pass
            raise

    async def check_qr_login_status(self, token: str) -> dict[str, Any]:
        self._ensure_login_config()
        await self._clear_expired_qr_pending()
        normalized = str(token or "").strip()
        if not normalized:
            raise RuntimeError("二维码会话标识不能为空")

        async with self._qr_lock:
            item = self._qr_pending.get(normalized)
        if not item:
            raise RuntimeError("二维码会话不存在或已过期，请重新生成")
        state = str(item.get("state") or "pending")
        if state == "authorized":
            session = str(item.get("session") or "").strip()
            if session:
                self._session = session
            async with self._qr_lock:
                self._qr_pending.pop(normalized, None)
            return {
                "authorized": True,
                "need_password": False,
                "session": session,
                "user": item.get("user"),
                "message": str(item.get("message") or "扫码登录成功"),
            }
        if state == "need_password":
            return {
                "authorized": False,
                "need_password": True,
                "pending": False,
                "session": str(item.get("session") or ""),
                "message": str(item.get("message") or "账号开启了二步验证，请输入密码"),
            }
        if state == "failed":
            raise RuntimeError(str(item.get("message") or "二维码登录失败"))
        return {
            "authorized": False,
            "need_password": False,
            "pending": True,
            "message": str(item.get("message") or "等待扫码确认"),
        }

    async def logout(self) -> None:
        self._ensure_login_config()
        await self._clear_expired_qr_pending()
        async with self._qr_lock:
            pending_items = list(self._qr_pending.values())
            self._qr_pending.clear()
        for item in pending_items:
            task = item.get("task")
            if task and not task.done():
                task.cancel()
            client = item.get("client")
            try:
                if client:
                    await client.disconnect()
            except Exception:
                pass
        if not self._session:
            return
        client = self._build_client(self._session)
        try:
            await client.connect()
            if await client.is_user_authorized():
                await client.log_out()
        finally:
            await client.disconnect()
        self._session = ""

    @staticmethod
    def _serialize_user(user: Any) -> dict[str, Any]:
        if not user:
            return {}
        return {
            "id": getattr(user, "id", None),
            "username": getattr(user, "username", "") or "",
            "phone": getattr(user, "phone", "") or "",
            "first_name": getattr(user, "first_name", "") or "",
            "last_name": getattr(user, "last_name", "") or "",
            "is_premium": bool(getattr(user, "premium", False)),
        }

    async def get_user_info(self) -> dict[str, Any]:
        self._ensure_search_config()
        client = self._build_client(self._session)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError("Telegram 会话已失效，请重新登录")
            me = await client.get_me()
            return self._serialize_user(me)
        finally:
            await client.disconnect()

    async def check_connection(self) -> dict[str, Any]:
        self._ensure_login_config()
        if not self._session:
            return {
                "authorized": False,
                "message": "未登录",
                "user": None,
                "channels": [],
            }
        client = self._build_client(self._session)
        channel_checks: list[dict[str, Any]] = []
        try:
            await client.connect()
            if not await client.is_user_authorized():
                return {
                    "authorized": False,
                    "message": "会话失效，请重新登录",
                    "user": None,
                    "channels": [],
                }
            me = await client.get_me()
            for channel in self._channels[:5]:
                status = {"channel": channel, "ok": False, "message": ""}
                try:
                    await client.get_entity(channel)
                    status["ok"] = True
                    status["message"] = "可访问"
                except (UsernameNotOccupiedError, UsernameInvalidError):
                    status["message"] = "频道不存在"
                except ChannelPrivateError:
                    status["message"] = "频道私有或无权限"
                except Exception as exc:
                    status["message"] = str(exc)[:120]
                channel_checks.append(status)
            return {
                "authorized": True,
                "message": "连接正常",
                "user": self._serialize_user(me),
                "channels": channel_checks,
            }
        finally:
            await client.disconnect()

    async def search_115_by_keyword(
        self,
        keyword: str,
        *,
        media_type: str = "movie",
        channels: list[str] | None = None,
        search_days: int | None = None,
        max_messages: int | None = None,
        expected_title: str = "",
        expected_original_title: str = "",
        expected_year: str = "",
    ) -> list[dict[str, Any]]:
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []
        target_channels = channels or self._channels
        if not target_channels:
            return []
        normalized_media = "tv" if str(media_type or "").strip().lower() == "tv" else "movie"

        from app.services.runtime_settings_service import runtime_settings_service
        from app.services.tg_index_service import tg_index_service

        index_enabled = runtime_settings_service.get_tg_index_enabled()
        fallback_enabled = runtime_settings_service.get_tg_index_realtime_fallback_enabled()
        index_query_limit = runtime_settings_service.get_tg_index_query_limit_per_channel()

        if index_enabled:
            indexed_rows = await tg_index_service.search_resources(
                keyword=normalized_keyword,
                media_type=normalized_media,
                channels=target_channels,
                per_channel_limit=index_query_limit,
                expected_title=expected_title,
                expected_original_title=expected_original_title,
                expected_year=expected_year,
            )
            if indexed_rows:
                return indexed_rows
            if not fallback_enabled:
                return []

        self._ensure_search_config()
        days = max(1, int(search_days or self._search_days))
        limit = max(20, int(max_messages or self._max_messages))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        client = self._build_client(self._session)
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError("Telegram 会话已失效，请重新登录")

            for channel in target_channels:
                try:
                    entity = await client.get_entity(channel)
                except Exception:
                    continue

                async for message in client.iter_messages(entity, search=normalized_keyword, limit=limit):
                    msg_date = getattr(message, "date", None)
                    if msg_date and msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                    if msg_date and msg_date < cutoff:
                        continue
                    if not msg_date and getattr(message, "id", 0) <= 0:
                        continue
                    rows.extend(
                        self._build_rows_from_message(
                            channel=str(channel),
                            message=message,
                            normalized_media=normalized_media,
                            seen=seen,
                        )
                    )
        finally:
            await client.disconnect()
        has_context = bool(self._normalize_for_match(expected_title) or self._normalize_for_match(expected_original_title))
        if has_context:
            filtered_rows: list[dict[str, Any]] = []
            for row in rows:
                score, reason, strong_hit = self._score_row_relevance(
                    row_title=str(row.get("resource_name") or row.get("title") or ""),
                    row_overview=str(row.get("overview") or ""),
                    expected_title=expected_title,
                    expected_original_title=expected_original_title,
                    expected_year=expected_year,
                )
                if not strong_hit or score < 80:
                    continue
                row["tg_relevance_score"] = score
                row["tg_match_reason"] = reason
                filtered_rows.append(row)
            rows = filtered_rows
        if rows and index_enabled:
            try:
                await tg_index_service.upsert_rows(rows)
            except Exception:
                pass
        return rows


tg_service = TgService()
