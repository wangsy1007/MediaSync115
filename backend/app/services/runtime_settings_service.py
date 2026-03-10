import json
import os
import secrets
import hashlib
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.hdhive_service import hdhive_service
from app.services.nullbr_client import nullbr_client
from app.services.pansou_service import pansou_service
from app.services.tg_service import tg_service
from app.services.emby_service import emby_service


class RuntimeSettingsService:
    @staticmethod
    def _hash_auth_password(password: str, salt: str | None = None) -> str:
        raw_password = str(password or "")
        if not raw_password:
            raise ValueError("密码不能为空")
        normalized_salt = salt or secrets.token_hex(16)
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            raw_password.encode("utf-8"),
            normalized_salt.encode("utf-8"),
            390000,
        )
        return f"{normalized_salt}${derived.hex()}"

    def __init__(self) -> None:
        self._file_path = Path("data/runtime_settings.json")
        self._defaults = {
            "pan115_cookie": settings.PAN115_COOKIE or "",
            "pan115_default_folder_id": "0",
            "pan115_default_folder_name": "根目录",
            "pan115_offline_folder_id": "0",
            "pan115_offline_folder_name": "根目录",
            "hdhive_cookie": settings.HDHIVE_COOKIE or "",
            "hdhive_base_url": settings.HDHIVE_BASE_URL,
            "pansou_base_url": settings.PANSOU_BASE_URL,
            "nullbr_app_id": settings.NULLBR_APP_ID,
            "nullbr_api_key": settings.NULLBR_API_KEY,
            "nullbr_base_url": settings.NULLBR_BASE_URL,
            "tg_api_id": settings.TG_API_ID or "",
            "tg_api_hash": settings.TG_API_HASH or "",
            "tg_phone": settings.TG_PHONE or "",
            "tg_session": settings.TG_SESSION or "",
            "tg_proxy": settings.TG_PROXY or "",
            "tg_channel_usernames": tg_service._parse_channels(settings.TG_CHANNEL_USERNAMES),
            "tg_search_days": int(settings.TG_SEARCH_DAYS or 30),
            "tg_max_messages_per_channel": int(settings.TG_MAX_MESSAGES_PER_CHANNEL or 200),
            "tg_index_enabled": True,
            "tg_index_realtime_fallback_enabled": True,
            "tg_index_query_limit_per_channel": 120,
            "tg_backfill_batch_size": 200,
            "tg_incremental_interval_minutes": 30,
            "tmdb_api_key": settings.TMDB_API_KEY or "",
            "tmdb_base_url": settings.TMDB_BASE_URL,
            "tmdb_image_base_url": settings.TMDB_IMAGE_BASE_URL,
            "tmdb_language": settings.TMDB_LANGUAGE,
            "tmdb_region": settings.TMDB_REGION,
            "emby_url": settings.EMBY_URL or "",
            "emby_api_key": settings.EMBY_API_KEY or "",
            "emby_sync_enabled": False,
            "emby_sync_interval_hours": 24,
            "auth_username": "admin",
            "auth_password_hash": "",
            "auth_secret": "",
            "subscription_nullbr_enabled": False,
            "subscription_nullbr_interval_hours": 24,
            "subscription_nullbr_run_time": "03:00",
            "subscription_hdhive_enabled": False,
            "subscription_hdhive_interval_hours": 24,
            "subscription_hdhive_run_time": "03:15",
            "subscription_pansou_enabled": False,
            "subscription_pansou_interval_hours": 24,
            "subscription_pansou_run_time": "03:30",
            "subscription_tg_enabled": False,
            "subscription_tg_interval_hours": 24,
            "subscription_tg_run_time": "04:00",
            "subscription_resource_priority": ["nullbr", "hdhive", "pansou", "tg"],
            "subscription_hdhive_auto_unlock_enabled": False,
            "subscription_hdhive_unlock_max_points_per_item": 10,
            "subscription_hdhive_unlock_budget_points_per_run": 30,
            "subscription_hdhive_unlock_threshold_inclusive": True,
        }
        self._data = dict(self._defaults)
        self._load()
        self._ensure_auth_defaults()
        self.apply_runtime_overrides()

    def _load(self) -> None:
        if not self._file_path.exists():
            return

        try:
            raw = json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception:
            return

        if not isinstance(raw, dict):
            return

        for key, default_value in self._defaults.items():
            value = raw.get(key)
            if isinstance(default_value, str):
                if isinstance(value, str) and value.strip():
                    self._data[key] = value.strip()
            elif isinstance(default_value, bool):
                if isinstance(value, bool):
                    self._data[key] = value
                elif isinstance(value, str):
                    normalized = value.strip().lower()
                    if normalized in {"1", "true", "yes", "on"}:
                        self._data[key] = True
                    elif normalized in {"0", "false", "no", "off"}:
                        self._data[key] = False
            elif isinstance(default_value, int):
                if value is None:
                    continue
                try:
                    self._data[key] = int(str(value))
                except Exception:
                    continue
            elif value is not None:
                self._data[key] = value

    def _save(self) -> None:
        os.makedirs(self._file_path.parent, exist_ok=True)
        self._file_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _ensure_auth_defaults(self) -> None:
        changed = False
        if not str(self._data.get("auth_secret") or "").strip():
            self._data["auth_secret"] = secrets.token_urlsafe(32)
            changed = True

        if not str(self._data.get("auth_username") or "").strip():
            self._data["auth_username"] = "admin"
            changed = True

        if not str(self._data.get("auth_password_hash") or "").strip():
            self._data["auth_password_hash"] = self._hash_auth_password("password")
            changed = True

        if changed:
            self._save()

    def get_pansou_base_url(self) -> str:
        return self._data["pansou_base_url"]

    def get_hdhive_cookie(self) -> str:
        return self._data["hdhive_cookie"]

    def get_hdhive_base_url(self) -> str:
        return self._data["hdhive_base_url"]

    def get_pan115_cookie(self) -> str:
        return self._data["pan115_cookie"]

    def update_pan115_cookie(self, cookie: str) -> str:
        cleaned = str(cookie or "").strip()
        if not cleaned:
            raise ValueError("115 Cookie 不能为空")

        self._data["pan115_cookie"] = cleaned
        self._save()
        self.apply_runtime_overrides()
        return cleaned

    def update_pansou_base_url(self, base_url: str) -> str:
        cleaned = str(base_url or "").strip()
        if not cleaned:
            raise ValueError("pansou base_url 不能为空")

        self._data["pansou_base_url"] = cleaned
        self._save()
        self.apply_runtime_overrides()
        return cleaned

    def get_pan115_default_folder(self) -> dict[str, str]:
        folder_id = str(self._data.get("pan115_default_folder_id") or "0")
        folder_name = str(self._data.get("pan115_default_folder_name") or "")
        if folder_id == "0" and not folder_name:
            folder_name = "根目录"
        return {
            "folder_id": folder_id,
            "folder_name": folder_name,
        }

    def update_pan115_default_folder(self, folder_id: str, folder_name: str = "") -> dict[str, str]:
        normalized_id = str(folder_id or "0").strip() or "0"
        normalized_name = str(folder_name or "").strip()
        if normalized_id == "0" and not normalized_name:
            normalized_name = "根目录"

        self._data["pan115_default_folder_id"] = normalized_id
        self._data["pan115_default_folder_name"] = normalized_name
        self._save()
        return {
            "folder_id": normalized_id,
            "folder_name": normalized_name,
        }

    def get_pan115_offline_folder(self) -> dict[str, str]:
        folder_id = str(self._data.get("pan115_offline_folder_id") or "0")
        folder_name = str(self._data.get("pan115_offline_folder_name") or "")
        if folder_id == "0" and not folder_name:
            folder_name = "根目录"
        return {
            "folder_id": folder_id,
            "folder_name": folder_name,
        }

    def update_pan115_offline_folder(self, folder_id: str, folder_name: str = "") -> dict[str, str]:
        normalized_id = str(folder_id or "0").strip() or "0"
        normalized_name = str(folder_name or "").strip()
        if normalized_id == "0" and not normalized_name:
            normalized_name = "根目录"

        self._data["pan115_offline_folder_id"] = normalized_id
        self._data["pan115_offline_folder_name"] = normalized_name
        self._save()
        return {
            "folder_id": normalized_id,
            "folder_name": normalized_name,
        }

    def get_nullbr_app_id(self) -> str:
        return self._data["nullbr_app_id"]

    def get_nullbr_api_key(self) -> str:
        return self._data["nullbr_api_key"]

    def get_nullbr_base_url(self) -> str:
        return self._data["nullbr_base_url"]

    def get_tg_api_id(self) -> str:
        return str(self._data.get("tg_api_id") or "")

    def get_tg_api_hash(self) -> str:
        return str(self._data.get("tg_api_hash") or "")

    def get_tg_phone(self) -> str:
        return str(self._data.get("tg_phone") or "")

    def get_tg_session(self) -> str:
        return str(self._data.get("tg_session") or "")

    def update_tg_session(self, session: str) -> str:
        self._data["tg_session"] = str(session or "").strip()
        self._save()
        self.apply_runtime_overrides()
        return self._data["tg_session"]

    def clear_tg_session(self) -> None:
        self._data["tg_session"] = ""
        self._save()
        self.apply_runtime_overrides()

    def get_tg_proxy(self) -> str:
        return str(self._data.get("tg_proxy") or "")

    def get_tg_channel_usernames(self) -> list[str]:
        value = self._data.get("tg_channel_usernames")
        if isinstance(value, list):
            return tg_service._parse_channels(value)
        return tg_service._parse_channels(value)

    def get_tg_search_days(self) -> int:
        value = self._data.get("tg_search_days", 30)
        try:
            return max(1, int(value))
        except Exception:
            return 30

    def get_tg_max_messages_per_channel(self) -> int:
        value = self._data.get("tg_max_messages_per_channel", 200)
        try:
            return max(20, int(value))
        except Exception:
            return 200

    def get_tg_index_enabled(self) -> bool:
        return bool(self._data.get("tg_index_enabled", True))

    def get_tg_index_realtime_fallback_enabled(self) -> bool:
        return bool(self._data.get("tg_index_realtime_fallback_enabled", True))

    def get_tg_index_query_limit_per_channel(self) -> int:
        value = self._data.get("tg_index_query_limit_per_channel", 120)
        try:
            return max(20, int(value))
        except Exception:
            return 120

    def get_tg_backfill_batch_size(self) -> int:
        value = self._data.get("tg_backfill_batch_size", 200)
        try:
            return max(50, int(value))
        except Exception:
            return 200

    def get_tg_incremental_interval_minutes(self) -> int:
        value = self._data.get("tg_incremental_interval_minutes", 30)
        try:
            return max(5, int(value))
        except Exception:
            return 30

    def get_tmdb_api_key(self) -> str:
        return self._data["tmdb_api_key"]

    def get_tmdb_base_url(self) -> str:
        return self._data["tmdb_base_url"]

    def get_tmdb_image_base_url(self) -> str:
        return self._data["tmdb_image_base_url"]

    def get_tmdb_language(self) -> str:
        return self._data["tmdb_language"]

    def get_tmdb_region(self) -> str:
        return self._data["tmdb_region"]

    def get_emby_url(self) -> str:
        return str(self._data.get("emby_url") or "")

    def get_emby_api_key(self) -> str:
        return str(self._data.get("emby_api_key") or "")

    def get_emby_sync_enabled(self) -> bool:
        return bool(self._data.get("emby_sync_enabled", False))

    def get_emby_sync_interval_hours(self) -> int:
        value = self._data.get("emby_sync_interval_hours", 24)
        try:
            return max(1, int(value))
        except Exception:
            return 24

    def get_auth_username(self) -> str:
        return str(self._data.get("auth_username") or "admin").strip() or "admin"

    def get_auth_password_hash(self) -> str:
        return str(self._data.get("auth_password_hash") or "").strip()

    def get_auth_secret(self) -> str:
        return str(self._data.get("auth_secret") or "").strip()

    def update_auth_credentials(self, username: str, new_password: str | None = None) -> dict[str, str]:
        next_username = str(username or "").strip()
        if not next_username:
            raise ValueError("账号不能为空")

        self._data["auth_username"] = next_username
        if new_password is not None:
            self._data["auth_password_hash"] = self._hash_auth_password(new_password)
        self._save()
        return {
            "username": self.get_auth_username(),
        }

    def get_subscription_resource_priority(self) -> list[str]:
        value = self._data.get("subscription_resource_priority")
        if not isinstance(value, list):
            return list(self._defaults["subscription_resource_priority"])

        allowed = {"nullbr", "hdhive", "pansou", "tg"}
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            source = str(item or "").strip().lower()
            if source in allowed and source not in seen:
                normalized.append(source)
                seen.add(source)

        if normalized:
            return normalized
        return list(self._defaults["subscription_resource_priority"])

    def get_subscription_hdhive_auto_unlock_enabled(self) -> bool:
        return bool(self._data.get("subscription_hdhive_auto_unlock_enabled", False))

    def get_subscription_hdhive_unlock_max_points_per_item(self) -> int:
        value = self._data.get("subscription_hdhive_unlock_max_points_per_item", 10)
        try:
            return max(1, int(value))
        except Exception:
            return 10

    def get_subscription_hdhive_unlock_budget_points_per_run(self) -> int:
        value = self._data.get("subscription_hdhive_unlock_budget_points_per_run", 30)
        try:
            return max(1, int(value))
        except Exception:
            return 30

    def get_subscription_hdhive_unlock_threshold_inclusive(self) -> bool:
        return bool(self._data.get("subscription_hdhive_unlock_threshold_inclusive", True))

    def update_bulk(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("配置数据格式无效")

        normalized = dict(self._data)
        for key in self._defaults.keys():
            if key not in payload:
                continue
            value = payload.get(key)
            if value is None:
                continue

            default_value = self._defaults[key]
            if isinstance(default_value, str):
                if not isinstance(value, str):
                    value = str(value)
                cleaned = value.strip()
                if not cleaned:
                    continue
                normalized[key] = cleaned
            elif isinstance(default_value, bool):
                if isinstance(value, bool):
                    normalized[key] = value
                elif isinstance(value, str):
                    normalized_value = value.strip().lower()
                    if normalized_value in {"1", "true", "yes", "on"}:
                        normalized[key] = True
                    elif normalized_value in {"0", "false", "no", "off"}:
                        normalized[key] = False
            elif isinstance(default_value, int):
                try:
                    normalized[key] = int(str(value))
                except Exception:
                    continue
            elif isinstance(default_value, list):
                source_items: list[str] = []
                if isinstance(value, str):
                    source_items = [part.strip() for part in value.split(",")]
                elif isinstance(value, list):
                    source_items = [str(part or "").strip() for part in value]
                else:
                    continue

                if key == "subscription_resource_priority":
                    allowed = {"nullbr", "hdhive", "pansou", "tg"}
                else:
                    normalized[key] = tg_service._parse_channels(source_items)
                    continue
                deduped: list[str] = []
                seen: set[str] = set()
                for item in source_items:
                    source = str(item or "").strip().lower()
                    if source in allowed and source not in seen:
                        deduped.append(source)
                        seen.add(source)
                if deduped:
                    normalized[key] = deduped
            else:
                normalized[key] = value

        self._data = normalized
        self._save()
        self.apply_runtime_overrides()
        return self.get_all()

    def apply_runtime_overrides(self) -> None:
        settings.PAN115_COOKIE = self.get_pan115_cookie() or None
        settings.HDHIVE_COOKIE = self.get_hdhive_cookie() or None
        settings.HDHIVE_BASE_URL = self.get_hdhive_base_url()
        settings.PANSOU_BASE_URL = self.get_pansou_base_url()
        settings.NULLBR_APP_ID = self.get_nullbr_app_id()
        settings.NULLBR_API_KEY = self.get_nullbr_api_key()
        settings.NULLBR_BASE_URL = self.get_nullbr_base_url()
        settings.TG_API_ID = self.get_tg_api_id() or None
        settings.TG_API_HASH = self.get_tg_api_hash() or None
        settings.TG_PHONE = self.get_tg_phone() or None
        settings.TG_SESSION = self.get_tg_session() or None
        settings.TG_PROXY = self.get_tg_proxy() or None
        settings.TG_CHANNEL_USERNAMES = ",".join(self.get_tg_channel_usernames())
        settings.TG_SEARCH_DAYS = self.get_tg_search_days()
        settings.TG_MAX_MESSAGES_PER_CHANNEL = self.get_tg_max_messages_per_channel()

        settings.TMDB_API_KEY = self.get_tmdb_api_key() or None
        settings.TMDB_BASE_URL = self.get_tmdb_base_url()
        settings.TMDB_IMAGE_BASE_URL = self.get_tmdb_image_base_url()
        settings.TMDB_LANGUAGE = self.get_tmdb_language()
        settings.TMDB_REGION = self.get_tmdb_region()
        settings.EMBY_URL = self.get_emby_url()
        settings.EMBY_API_KEY = self.get_emby_api_key()

        # Keep the singleton client in sync with runtime cookie updates.
        from app.services.pan115_service import pan115_service

        pan115_service.update_cookie(self.get_pan115_cookie())
        hdhive_service.set_cookie(self.get_hdhive_cookie())
        hdhive_service.set_base_url(self.get_hdhive_base_url())
        pansou_service.set_base_url(self.get_pansou_base_url())
        nullbr_client.update_config(
            app_id=self.get_nullbr_app_id(),
            api_key=self.get_nullbr_api_key(),
            base_url=self.get_nullbr_base_url(),
        )
        tg_service.set_config(
            api_id=self.get_tg_api_id(),
            api_hash=self.get_tg_api_hash(),
            phone=self.get_tg_phone(),
            session=self.get_tg_session(),
            proxy=self.get_tg_proxy(),
            channels=self.get_tg_channel_usernames(),
            search_days=self.get_tg_search_days(),
            max_messages=self.get_tg_max_messages_per_channel(),
        )
        emby_service.set_config(
            base_url=self.get_emby_url(),
            api_key=self.get_emby_api_key(),
        )

    def get_all(self) -> dict[str, Any]:
        return {
            "pan115_default_folder_id": self.get_pan115_default_folder()["folder_id"],
            "pan115_default_folder_name": self.get_pan115_default_folder()["folder_name"],
            "pan115_offline_folder_id": self.get_pan115_offline_folder()["folder_id"],
            "pan115_offline_folder_name": self.get_pan115_offline_folder()["folder_name"],
            "hdhive_cookie": self.get_hdhive_cookie(),
            "hdhive_base_url": self.get_hdhive_base_url(),
            "pansou_base_url": self.get_pansou_base_url(),
            "nullbr_app_id": self.get_nullbr_app_id(),
            "nullbr_api_key": self.get_nullbr_api_key(),
            "nullbr_base_url": self.get_nullbr_base_url(),
            "tg_api_id": self.get_tg_api_id(),
            "tg_api_hash": self.get_tg_api_hash(),
            "tg_phone": self.get_tg_phone(),
            "tg_session": self.get_tg_session(),
            "tg_proxy": self.get_tg_proxy(),
            "tg_channel_usernames": self.get_tg_channel_usernames(),
            "tg_search_days": self.get_tg_search_days(),
            "tg_max_messages_per_channel": self.get_tg_max_messages_per_channel(),
            "tg_index_enabled": self.get_tg_index_enabled(),
            "tg_index_realtime_fallback_enabled": self.get_tg_index_realtime_fallback_enabled(),
            "tg_index_query_limit_per_channel": self.get_tg_index_query_limit_per_channel(),
            "tg_backfill_batch_size": self.get_tg_backfill_batch_size(),
            "tg_incremental_interval_minutes": self.get_tg_incremental_interval_minutes(),
            "tmdb_api_key": self.get_tmdb_api_key(),
            "tmdb_base_url": self.get_tmdb_base_url(),
            "tmdb_image_base_url": self.get_tmdb_image_base_url(),
            "tmdb_language": self.get_tmdb_language(),
            "tmdb_region": self.get_tmdb_region(),
            "emby_url": self.get_emby_url(),
            "emby_api_key": self.get_emby_api_key(),
            "emby_sync_enabled": self.get_emby_sync_enabled(),
            "emby_sync_interval_hours": self.get_emby_sync_interval_hours(),
            "auth_username": self.get_auth_username(),
            "subscription_nullbr_enabled": bool(self._data.get("subscription_nullbr_enabled", False)),
            "subscription_nullbr_interval_hours": int(self._data.get("subscription_nullbr_interval_hours", 24) or 24),
            "subscription_nullbr_run_time": str(self._data.get("subscription_nullbr_run_time", "03:00") or "03:00"),
            "subscription_hdhive_enabled": bool(self._data.get("subscription_hdhive_enabled", False)),
            "subscription_hdhive_interval_hours": int(self._data.get("subscription_hdhive_interval_hours", 24) or 24),
            "subscription_hdhive_run_time": str(self._data.get("subscription_hdhive_run_time", "03:15") or "03:15"),
            "subscription_pansou_enabled": bool(self._data.get("subscription_pansou_enabled", False)),
            "subscription_pansou_interval_hours": int(self._data.get("subscription_pansou_interval_hours", 24) or 24),
            "subscription_pansou_run_time": str(self._data.get("subscription_pansou_run_time", "03:30") or "03:30"),
            "subscription_tg_enabled": bool(self._data.get("subscription_tg_enabled", False)),
            "subscription_tg_interval_hours": int(self._data.get("subscription_tg_interval_hours", 24) or 24),
            "subscription_tg_run_time": str(self._data.get("subscription_tg_run_time", "04:00") or "04:00"),
            "subscription_resource_priority": self.get_subscription_resource_priority(),
            "subscription_hdhive_auto_unlock_enabled": self.get_subscription_hdhive_auto_unlock_enabled(),
            "subscription_hdhive_unlock_max_points_per_item": self.get_subscription_hdhive_unlock_max_points_per_item(),
            "subscription_hdhive_unlock_budget_points_per_run": self.get_subscription_hdhive_unlock_budget_points_per_run(),
            "subscription_hdhive_unlock_threshold_inclusive": self.get_subscription_hdhive_unlock_threshold_inclusive(),
        }


runtime_settings_service = RuntimeSettingsService()
