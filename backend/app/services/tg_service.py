import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from app.core.config import settings

try:
    from telethon import TelegramClient
    from telethon.errors import (
        ChannelPrivateError,
        FloodWaitError,
        PhoneCodeExpiredError,
        PhoneCodeInvalidError,
        SessionPasswordNeededError,
        UsernameInvalidError,
        UsernameNotOccupiedError,
    )
    from telethon.sessions import StringSession
    from telethon.tl.types import MessageEntityTextUrl

    TELETHON_AVAILABLE = True
    TELETHON_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - runtime fallback
    TELETHON_AVAILABLE = False
    TELETHON_IMPORT_ERROR = str(exc)
    TelegramClient = None  # type: ignore[assignment]
    StringSession = None  # type: ignore[assignment]
    MessageEntityTextUrl = object  # type: ignore[assignment]
    SessionPasswordNeededError = Exception  # type: ignore[assignment]
    PhoneCodeInvalidError = Exception  # type: ignore[assignment]
    PhoneCodeExpiredError = Exception  # type: ignore[assignment]
    FloodWaitError = Exception  # type: ignore[assignment]
    UsernameInvalidError = Exception  # type: ignore[assignment]
    UsernameNotOccupiedError = Exception  # type: ignore[assignment]
    ChannelPrivateError = Exception  # type: ignore[assignment]


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
        self._proxy = str(settings.TG_PROXY or "").strip()
        self._channels = self._parse_channels(settings.TG_CHANNEL_USERNAMES)
        self._search_days = max(1, int(settings.TG_SEARCH_DAYS or 30))
        self._max_messages = max(20, int(settings.TG_MAX_MESSAGES_PER_CHANNEL or 200))
        self._user_agent = "MediaSync115/1.0 (+https://localhost)"

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
    def _build_proxy(proxy_value: str) -> tuple[str, str, int] | None:
        value = str(proxy_value or "").strip()
        if not value:
            return None
        # formats:
        # 1) socks5://host:port
        # 2) host:port
        if value.startswith("socks5://"):
            value = value[len("socks5://") :]
        if ":" not in value:
            return None
        host, port_text = value.rsplit(":", 1)
        try:
            port = int(port_text)
        except Exception:
            return None
        host = host.strip()
        if not host:
            return None
        return ("socks5", host, port)

    def set_config(
        self,
        *,
        api_id: str | None = None,
        api_hash: str | None = None,
        phone: str | None = None,
        session: str | None = None,
        proxy: str | None = None,
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
        if proxy is not None:
            self._proxy = str(proxy or "").strip()
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

    def _ensure_dependency(self) -> None:
        if not TELETHON_AVAILABLE:
            raise RuntimeError(f"Telethon 未安装或加载失败: {TELETHON_IMPORT_ERROR}")

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
        proxy = self._build_proxy(self._proxy)
        return TelegramClient(
            StringSession(session_value),
            api_id=api_id,
            api_hash=self._api_hash,
            proxy=proxy,
            device_model="MediaSync115",
            system_version="Linux",
            app_version="1.0.0",
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

    async def logout(self) -> None:
        self._ensure_login_config()
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
    ) -> list[dict[str, Any]]:
        self._ensure_search_config()
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []
        target_channels = channels or self._channels
        if not target_channels:
            return []
        days = max(1, int(search_days or self._search_days))
        limit = max(20, int(max_messages or self._max_messages))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        normalized_media = "tv" if str(media_type or "").strip().lower() == "tv" else "movie"
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
                        continue
                    for index, share_link in enumerate(links):
                        key = f"{str(channel).lower()}|{str(getattr(message, 'id', 0))}|{share_link.lower()}"
                        if key in seen:
                            continue
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
        finally:
            await client.disconnect()
        return rows


tg_service = TgService()
