import json
import os
import secrets
import hashlib
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.archive_subdir_config import (
    DEFAULT_ARCHIVE_SUBDIRS,
    normalize_archive_subdirs,
)
from app.services.archive_naming_config import (
    DEFAULT_ARCHIVE_NAMING,
    normalize_archive_naming,
)
from app.services.hdhive_service import hdhive_service
from app.services.pansou_service import pansou_service
from app.services.tg_service import tg_service
from app.services.emby_service import emby_service
from app.utils.proxy import proxy_manager


class RuntimeSettingsService:
    ENV_FIELD_MAP = {
        "http_proxy": "HTTP_PROXY",
        "https_proxy": "HTTPS_PROXY",
        "all_proxy": "ALL_PROXY",
        "socks_proxy": "SOCKS_PROXY",
        "pan115_cookie": "PAN115_COOKIE",
        "quark_cookie": "QUARK_COOKIE",
        "hdhive_cookie": "HDHIVE_COOKIE",
        "hdhive_base_url": "HDHIVE_BASE_URL",
        "pansou_base_url": "PANSOU_BASE_URL",
        "tg_api_id": "TG_API_ID",
        "tg_api_hash": "TG_API_HASH",
        "tg_phone": "TG_PHONE",
        "tg_session": "TG_SESSION",
        "tg_channel_usernames": "TG_CHANNEL_USERNAMES",
        "tg_search_days": "TG_SEARCH_DAYS",
        "tg_max_messages_per_channel": "TG_MAX_MESSAGES_PER_CHANNEL",
        "tmdb_api_key": "TMDB_API_KEY",
        "tmdb_base_url": "TMDB_BASE_URL",
        "tmdb_image_base_url": "TMDB_IMAGE_BASE_URL",
        "tmdb_language": "TMDB_LANGUAGE",
        "tmdb_region": "TMDB_REGION",
        "emby_url": "EMBY_URL",
        "emby_api_key": "EMBY_API_KEY",
        "feiniu_url": "FEINIU_URL",
        "feiniu_secret": "FEINIU_SECRET",
        "feiniu_api_key": "FEINIU_API_KEY",
        "feiniu_session_token": "FEINIU_SESSION_TOKEN",
    }

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
        self._loaded_keys: set[str] = set()
        self._defaults = {
            "http_proxy": settings.HTTP_PROXY or "",
            "https_proxy": settings.HTTPS_PROXY or "",
            "all_proxy": settings.ALL_PROXY or "",
            "socks_proxy": settings.SOCKS_PROXY or "",
            "pan115_cookie": settings.PAN115_COOKIE or "",
            "pan115_default_folder_id": "0",
            "pan115_default_folder_name": "根目录",
            "pan115_offline_folder_id": "0",
            "pan115_offline_folder_name": "根目录",
            "quark_cookie": settings.QUARK_COOKIE or "",
            "quark_default_folder_id": "0",
            "quark_default_folder_name": "根目录",
            "hdhive_cookie": settings.HDHIVE_COOKIE or "",
            "hdhive_base_url": settings.HDHIVE_BASE_URL,
            "hdhive_auto_checkin_enabled": False,
            "hdhive_auto_checkin_mode": "normal",
            "hdhive_auto_checkin_method": "web",
            "hdhive_auto_checkin_run_time": "09:00",
            "pansou_base_url": settings.PANSOU_BASE_URL,
            "tg_api_id": settings.TG_API_ID or "",
            "tg_api_hash": settings.TG_API_HASH or "",
            "tg_phone": settings.TG_PHONE or "",
            "tg_session": settings.TG_SESSION or "",
            "tg_channel_usernames": tg_service._parse_channels(
                settings.TG_CHANNEL_USERNAMES
            ),
            "tg_search_days": int(settings.TG_SEARCH_DAYS or 30),
            "tg_max_messages_per_channel": int(
                settings.TG_MAX_MESSAGES_PER_CHANNEL or 200
            ),
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
            "emby_sync_interval_minutes": 1440,
            "feiniu_url": settings.FEINIU_URL or "",
            "feiniu_secret": settings.FEINIU_SECRET or "",
            "feiniu_api_key": settings.FEINIU_API_KEY or "",
            "feiniu_session_token": "",
            "feiniu_login_username": "",
            "feiniu_password_enc": "",
            "feiniu_sync_enabled": False,
            "feiniu_sync_interval_hours": 24,
            "feiniu_sync_interval_minutes": 1440,
            "auth_username": "admin",
            "auth_password_hash": "",
            "auth_secret": "",
            "subscription_enabled": False,
            "subscription_interval_hours": 24,
            "subscription_resource_priority": ["hdhive", "pansou", "tg"],
            "subscription_resource_enabled": {
                "hdhive": True,
                "pansou": True,
                "tg": True,
            },
            "subscription_hdhive_auto_unlock_enabled": False,
            "subscription_hdhive_unlock_max_points_per_item": 10,
            "subscription_hdhive_unlock_budget_points_per_run": 30,
            "subscription_hdhive_unlock_threshold_inclusive": True,
            "subscription_hdhive_prefer_free": True,
            "resource_preferred_resolutions": [],
            "resource_preferred_hdr": [],
            "resource_preferred_codec": [],
            "resource_preferred_audio": [],
            "resource_preferred_subtitles": [],
            "resource_exclude_tags": ["CAM", "TS", "抢先版"],
            "resource_min_size_gb": None,
            "resource_max_size_gb": None,
            "update_source_type": "official",
            "update_repository": "wangsy1007/mediasync115",
            "tg_bot_token": "",
            "tg_bot_enabled": False,
            "tg_bot_allowed_users": [],
            "tg_bot_notify_chat_ids": [],
            "tg_bot_hdhive_auto_unlock": False,
            "detail_visible_tabs": [
                "pan115",
                "pan115_pansou",
                "pan115_hdhive",
                "pan115_tg",
                "quark",
                "quark_pansou",
                "quark_hdhive",
                "quark_tg",
                "magnet",
                "magnet_seedhub",
                "magnet_butailing",
            ],
            "license_key": "",
            "subscription_offline_transfer_enabled": False,
            "subscription_auto_sync_after_transfer": True,
            "subscription_exclude_iso": True,
            "chart_subscription_enabled": False,
            "chart_subscription_sources": [],
            "chart_subscription_limit": 20,
            "chart_subscription_interval_hours": 24,
            "person_follow_enabled": False,
            "person_follow_interval_hours": 24,
            "person_follow_auto_subscribe": True,
            "archive_enabled": False,
            "archive_watch_cid": "",
            "archive_watch_name": "",
            "archive_output_cid": "",
            "archive_output_name": "",
            "archive_interval_minutes": 10,
            "archive_auto_on_transfer": True,
            "archive_auto_on_offline": True,
            "offline_monitor_interval_minutes": 3,
            "archive_subdirs": DEFAULT_ARCHIVE_SUBDIRS,
            "archive_naming": DEFAULT_ARCHIVE_NAMING,
            "strm_enabled": False,
            "strm_output_dir": "",
            "strm_base_url": "",
            "strm_redirect_mode": "redirect",
            "strm_auto_after_archive": True,
            "strm_refresh_emby_after_generate": False,
            "strm_refresh_feiniu_after_generate": False,
            "strm_token_secret": "",
            "strm_proxy_enabled": False,
            "strm_proxy_port": 8099,
            "strm_early_redirect": True,
            "strm_schedule_enabled": False,
            "strm_incremental_interval_minutes": 360,
            "strm_full_schedule_enabled": False,
            "strm_full_schedule_day": "sun",
            "strm_full_schedule_time": "03:00",
            # —— LLM 配置 ——
            "llm_base_url": "https://api.deepseek.com/v1",
            "llm_api_key_enc": "",
            "llm_model": "deepseek-chat",
            "llm_enabled": False,
        }
        self._data = dict(self._defaults)
        self._load()
        self._merge_settings_backed_values()
        self._ensure_auth_defaults()
        self._migrate_detail_visible_tabs()
        self.apply_runtime_overrides()

    def _migrate_detail_visible_tabs(self) -> None:
        """老配置里没有 quark 相关 tab key 时自动补全，让新增功能默认可见"""
        current = self._data.get("detail_visible_tabs")
        if not isinstance(current, list) or not current:
            return
        quark_keys = ["quark", "quark_pansou", "quark_hdhive", "quark_tg"]
        if any(k in current for k in quark_keys):
            return
        # 把 quark 系列插入到 magnet 之前；找不到 magnet 就追加到末尾
        new_list = []
        inserted = False
        for key in current:
            if key == "magnet" and not inserted:
                new_list.extend(quark_keys)
                inserted = True
            new_list.append(key)
        if not inserted:
            new_list.extend(quark_keys)
        self._data["detail_visible_tabs"] = new_list
        try:
            self._save()
        except Exception:
            pass

    def _get_persisted_data(self) -> dict[str, Any]:
        return dict(self._data)

    def _load(self) -> None:
        if not self._file_path.exists():
            return

        try:
            raw = json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception:
            return

        if not isinstance(raw, dict):
            return

        self._loaded_keys = {str(key) for key in raw.keys()}
        for key, default_value in self._defaults.items():
            value = raw.get(key)
            if isinstance(default_value, str):
                if isinstance(value, str):
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
            json.dumps(self._get_persisted_data(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _merge_settings_backed_values(self) -> None:
        fallback_values = {
            "http_proxy": settings.HTTP_PROXY or "",
            "https_proxy": settings.HTTPS_PROXY or "",
            "all_proxy": settings.ALL_PROXY or "",
            "socks_proxy": settings.SOCKS_PROXY or "",
            "pan115_cookie": settings.PAN115_COOKIE or "",
            "hdhive_cookie": settings.HDHIVE_COOKIE or "",
            "hdhive_base_url": settings.HDHIVE_BASE_URL or "",
            "pansou_base_url": settings.PANSOU_BASE_URL or "",
            "tg_api_id": settings.TG_API_ID or "",
            "tg_api_hash": settings.TG_API_HASH or "",
            "tg_phone": settings.TG_PHONE or "",
            "tg_session": settings.TG_SESSION or "",
            "tg_channel_usernames": tg_service._parse_channels(
                settings.TG_CHANNEL_USERNAMES
            ),
            "tg_search_days": int(settings.TG_SEARCH_DAYS or 30),
            "tg_max_messages_per_channel": int(
                settings.TG_MAX_MESSAGES_PER_CHANNEL or 200
            ),
            "tmdb_api_key": settings.TMDB_API_KEY or "",
            "tmdb_base_url": settings.TMDB_BASE_URL or "",
            "tmdb_image_base_url": settings.TMDB_IMAGE_BASE_URL or "",
            "tmdb_language": settings.TMDB_LANGUAGE or "",
            "tmdb_region": settings.TMDB_REGION or "",
            "emby_url": settings.EMBY_URL or "",
            "emby_api_key": settings.EMBY_API_KEY or "",
            "feiniu_url": settings.FEINIU_URL or "",
            "feiniu_secret": settings.FEINIU_SECRET or "",
            "feiniu_api_key": settings.FEINIU_API_KEY or "",
        }
        for key, fallback_value in fallback_values.items():
            if key in self._loaded_keys:
                continue
            current_value = self._data.get(key)
            if isinstance(fallback_value, list):
                if isinstance(current_value, list) and current_value:
                    continue
                self._data[key] = list(fallback_value)
                continue
            if isinstance(fallback_value, int):
                try:
                    if int(current_value) > 0:
                        continue
                except Exception:
                    pass
                self._data[key] = fallback_value
                continue
            if str(current_value or "").strip():
                continue
            self._data[key] = fallback_value

    def _normalize_env_backed_update(
        self, key: str, value: Any
    ) -> tuple[Any, str | None]:
        default_value = self._defaults[key]

        if isinstance(default_value, list):
            source_items: list[str] = []
            if value is None:
                return [], None
            if isinstance(value, str):
                source_items = [part.strip() for part in value.split(",")]
            elif isinstance(value, list):
                source_items = [str(part or "").strip() for part in value]
            normalized_list = tg_service._parse_channels(source_items)
            if not normalized_list:
                return [], None
            return normalized_list, ",".join(normalized_list)

        if isinstance(default_value, bool):
            if value is None:
                return default_value, None
            if isinstance(value, bool):
                return value, "true" if value else "false"
            normalized_bool = str(value or "").strip().lower()
            if normalized_bool in {"1", "true", "yes", "on"}:
                return True, "true"
            if normalized_bool in {"0", "false", "no", "off"}:
                return False, "false"
            return default_value, None

        if isinstance(default_value, int):
            if value is None or not str(value).strip():
                return default_value, None
            parsed = int(str(value).strip())
            return parsed, str(parsed)

        if value is None:
            return "", None
        cleaned = str(value).strip()
        if not cleaned:
            return "", None
        return cleaned, cleaned

    def _persist_env_backed_fields(self, updates: dict[str, Any]) -> None:
        if not updates:
            return

        for key, value in updates.items():
            if key not in self.ENV_FIELD_MAP:
                continue
            normalized_value, _ = self._normalize_env_backed_update(key, value)
            self._data[key] = normalized_value
            self._loaded_keys.add(key)

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

    def update_hdhive_cookie(self, cookie: str) -> str:
        """持久化 HDHive 自动续期后的 Cookie。"""
        cleaned = str(cookie or "").strip()
        if not cleaned:
            raise ValueError("HDHive Cookie 不能为空")
        if cleaned == self.get_hdhive_cookie():
            return cleaned

        self._persist_env_backed_fields({"hdhive_cookie": cleaned})
        self._save()
        settings.HDHIVE_COOKIE = cleaned
        hdhive_service.set_cookie(cleaned)
        return cleaned

    def get_hdhive_base_url(self) -> str:
        return self._data["hdhive_base_url"]

    def has_hdhive_credentials(self, merged_settings: dict | None = None) -> bool:
        """判断是否具备有效 HDHive Cookie。"""
        if merged_settings is None:
            cookie = self.get_hdhive_cookie()
        else:
            cookie = str(merged_settings.get("hdhive_cookie") or "").strip()
        return bool(cookie)

    def get_hdhive_auto_checkin_enabled(self) -> bool:
        return bool(self._data.get("hdhive_auto_checkin_enabled", False))

    def get_hdhive_auto_checkin_mode(self) -> str:
        value = (
            str(self._data.get("hdhive_auto_checkin_mode") or "normal").strip().lower()
        )
        if value == "gamble":
            return "gamble"
        return "normal"

    def get_hdhive_auto_checkin_method(self) -> str:
        # HDHive 已移除旧 /api/checkin；cookie/api 旧值统一迁移到网页 Server Action。
        return "web"

    def get_hdhive_auto_checkin_run_time(self) -> str:
        return str(self._data.get("hdhive_auto_checkin_run_time", "09:00") or "09:00")

    def get_pan115_cookie(self) -> str:
        return self._data["pan115_cookie"]

    def update_pan115_cookie(self, cookie: str) -> str:
        cleaned = str(cookie or "").strip()
        if not cleaned:
            raise ValueError("115 Cookie 不能为空")

        self._persist_env_backed_fields({"pan115_cookie": cleaned})
        self._save()
        self.apply_runtime_overrides()
        return self.get_pan115_cookie()

    def get_quark_cookie(self) -> str:
        return str(self._data.get("quark_cookie") or "")

    def update_quark_cookie(self, cookie: str) -> str:
        cleaned = str(cookie or "").strip()
        if not cleaned:
            raise ValueError("夸克 Cookie 不能为空")

        self._persist_env_backed_fields({"quark_cookie": cleaned})
        self._save()
        self.apply_runtime_overrides()
        return self.get_quark_cookie()

    def get_quark_default_folder(self) -> dict[str, str]:
        folder_id = str(self._data.get("quark_default_folder_id") or "0")
        folder_name = str(self._data.get("quark_default_folder_name") or "")
        if folder_id == "0" and not folder_name:
            folder_name = "根目录"
        return {"folder_id": folder_id, "folder_name": folder_name}

    def update_quark_default_folder(self, folder_id: str, folder_name: str = "") -> dict[str, str]:
        normalized_id = str(folder_id or "0").strip()
        normalized_name = str(folder_name or "").strip()
        if normalized_id == "0" and not normalized_name:
            normalized_name = "根目录"
        self._data["quark_default_folder_id"] = normalized_id
        self._data["quark_default_folder_name"] = normalized_name
        self._save()
        return self.get_quark_default_folder()

    def update_pansou_base_url(self, base_url: str) -> str:
        cleaned = str(base_url or "").strip()
        if not cleaned:
            raise ValueError("pansou base_url 不能为空")

        self._persist_env_backed_fields({"pansou_base_url": cleaned})
        self._save()
        self.apply_runtime_overrides()
        return self.get_pansou_base_url()

    def get_pan115_default_folder(self) -> dict[str, str]:
        folder_id = str(self._data.get("pan115_default_folder_id") or "0")
        folder_name = str(self._data.get("pan115_default_folder_name") or "")
        if folder_id == "0" and not folder_name:
            folder_name = "根目录"
        return {
            "folder_id": folder_id,
            "folder_name": folder_name,
        }

    def update_pan115_default_folder(
        self, folder_id: str, folder_name: str = ""
    ) -> dict[str, str]:
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

    def update_pan115_offline_folder(
        self, folder_id: str, folder_name: str = ""
    ) -> dict[str, str]:
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

    def get_tg_api_id(self) -> str:
        return str(self._data.get("tg_api_id") or "")

    def get_tg_api_hash(self) -> str:
        return str(self._data.get("tg_api_hash") or "")

    def get_tg_phone(self) -> str:
        return str(self._data.get("tg_phone") or "")

    def get_tg_session(self) -> str:
        return str(self._data.get("tg_session") or "")

    def update_tg_session(self, session: str) -> str:
        self._persist_env_backed_fields({"tg_session": str(session or "").strip()})
        self._save()
        self.apply_runtime_overrides()
        return self._data["tg_session"]

    def clear_tg_session(self) -> None:
        self._persist_env_backed_fields({"tg_session": None})
        self._save()
        self.apply_runtime_overrides()

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

    def get_tg_bot_hdhive_auto_unlock(self) -> bool:
        return bool(self._data.get("tg_bot_hdhive_auto_unlock", False))

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

    def get_emby_sync_interval_minutes(self) -> int:
        value = self._data.get("emby_sync_interval_minutes")
        if value is not None:
            try:
                return max(1, int(value))
            except Exception:
                pass
        # 兼容旧版 hours 配置，自动转换为分钟
        old_hours = self._data.get("emby_sync_interval_hours")
        if old_hours is not None:
            try:
                return max(1, int(old_hours) * 60)
            except Exception:
                pass
        return 1440

    def get_emby_sync_interval_hours(self) -> int:
        return max(1, self.get_emby_sync_interval_minutes() // 60)

    def get_feiniu_url(self) -> str:
        return str(self._data.get("feiniu_url") or "")

    def get_llm_base_url(self) -> str:
        return str(self._data.get("llm_base_url") or "").strip()

    def get_llm_model(self) -> str:
        return str(self._data.get("llm_model") or "").strip()

    def get_llm_api_key(self) -> str:
        """解密读取 LLM API Key。"""
        from app.utils.credential_crypto import decrypt_credential

        encrypted = str(self._data.get("llm_api_key_enc") or "")
        if not encrypted:
            return ""
        return decrypt_credential(encrypted, self.get_auth_secret())

    def set_llm_api_key(self, api_key: str) -> None:
        """加密保存 LLM API Key，空字符串清除。"""
        from app.utils.credential_crypto import encrypt_credential

        plain = str(api_key or "").strip()
        self._data["llm_api_key_enc"] = (
            encrypt_credential(plain, self.get_auth_secret()) if plain else ""
        )
        self._loaded_keys.add("llm_api_key_enc")
        self._save()

    def has_llm_api_key(self) -> bool:
        return bool(str(self._data.get("llm_api_key_enc") or "").strip())

    def get_llm_enabled(self) -> bool:
        return bool(self._data.get("llm_enabled", False))

    def get_feiniu_secret(self) -> str:
        return str(self._data.get("feiniu_secret") or "")

    def get_feiniu_api_key(self) -> str:
        return str(self._data.get("feiniu_api_key") or "")

    def get_feiniu_session_token(self) -> str:
        return str(self._data.get("feiniu_session_token") or "")

    def get_feiniu_login_username(self) -> str:
        return str(self._data.get("feiniu_login_username") or "")

    def has_feiniu_sync_credentials(self, merged_settings: dict | None = None) -> bool:
        """判断是否具备飞牛同步所需凭据。"""
        from app.services.feiniu_service import feiniu_service

        if merged_settings is None:
            feiniu_url = self.get_feiniu_url()
            feiniu_session_token = self.get_feiniu_session_token()
            feiniu_login_username = self.get_feiniu_login_username()
            feiniu_password_enc = self.get_feiniu_password_enc()
        else:
            feiniu_url = str(merged_settings.get("feiniu_url") or "").strip()
            feiniu_session_token = str(
                merged_settings.get("feiniu_session_token") or ""
            ).strip()
            feiniu_login_username = str(
                merged_settings.get("feiniu_login_username") or ""
            ).strip()
            feiniu_password_enc = str(
                merged_settings.get("feiniu_password_enc") or ""
            ).strip()

        if not feiniu_url:
            return False
        if feiniu_service.is_trim_vapi_token(feiniu_session_token):
            return True
        return bool(feiniu_login_username and feiniu_password_enc)

    def get_feiniu_password_enc(self) -> str:
        return str(self._data.get("feiniu_password_enc") or "")

    def get_feiniu_password(self) -> str:
        """解密读取飞牛影视登录密码。"""
        from app.utils.credential_crypto import decrypt_credential

        encrypted = self.get_feiniu_password_enc()
        if not encrypted:
            return ""
        return decrypt_credential(encrypted, self.get_auth_secret())

    def set_feiniu_password(self, password: str) -> None:
        """加密保存飞牛影视登录密码。"""
        from app.utils.credential_crypto import encrypt_credential

        plain = str(password or "").strip()
        if not plain:
            self._data["feiniu_password_enc"] = ""
            return
        self._data["feiniu_password_enc"] = encrypt_credential(
            plain,
            self.get_auth_secret(),
        )

    def get_feiniu_sync_enabled(self) -> bool:
        return bool(self._data.get("feiniu_sync_enabled", False))

    def get_feiniu_sync_interval_minutes(self) -> int:
        value = self._data.get("feiniu_sync_interval_minutes")
        if value is not None:
            try:
                return max(1, int(value))
            except Exception:
                pass
        # 兼容旧版 hours 配置，自动转换为分钟
        old_hours = self._data.get("feiniu_sync_interval_hours")
        if old_hours is not None:
            try:
                return max(1, int(old_hours) * 60)
            except Exception:
                pass
        return 1440

    def get_feiniu_sync_interval_hours(self) -> int:
        return max(1, self.get_feiniu_sync_interval_minutes() // 60)

    def get_auth_username(self) -> str:
        return str(self._data.get("auth_username") or "admin").strip() or "admin"

    def get_auth_password_hash(self) -> str:
        return str(self._data.get("auth_password_hash") or "").strip()

    def get_auth_secret(self) -> str:
        return str(self._data.get("auth_secret") or "").strip()

    def update_auth_credentials(
        self, username: str, new_password: str | None = None
    ) -> dict[str, str]:
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

        allowed = {"hdhive", "pansou", "tg"}
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

    @staticmethod
    def _subscription_resource_source_set() -> set[str]:
        return {"hdhive", "pansou", "tg"}

    def get_subscription_resource_enabled(self) -> dict[str, bool]:
        allowed = self._subscription_resource_source_set()
        defaults = {
            source: True
            for source in self._defaults.get("subscription_resource_enabled") or allowed
        }
        if not defaults:
            defaults = {source: True for source in allowed}

        value = self._data.get("subscription_resource_enabled")
        if not isinstance(value, dict):
            return dict(defaults)

        normalized = dict(defaults)
        for source in allowed:
            if source in value:
                normalized[source] = bool(value[source])
        return normalized

    def get_active_subscription_resource_priority(self) -> list[str]:
        enabled = self.get_subscription_resource_enabled()
        priority = self.get_subscription_resource_priority()
        active = [source for source in priority if enabled.get(source, True)]
        if active:
            return active
        return list(priority)

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
        return bool(
            self._data.get("subscription_hdhive_unlock_threshold_inclusive", True)
        )

    def get_subscription_hdhive_prefer_free(self) -> bool:
        return bool(self._data.get("subscription_hdhive_prefer_free", True))

    def get_subscription_offline_transfer_enabled(self) -> bool:
        return bool(self._data.get("subscription_offline_transfer_enabled", False))

    def get_subscription_auto_sync_after_transfer(self) -> bool:
        return bool(self._data.get("subscription_auto_sync_after_transfer", True))

    def get_subscription_exclude_iso(self) -> bool:
        """订阅转存时跳过 ISO/IMG 原盘资源（默认开启）。"""
        if "subscription_exclude_iso" not in self._data:
            return True
        return bool(self._data.get("subscription_exclude_iso"))

    def get_resource_preferred_resolutions(self) -> list[str]:
        val = self._data.get("resource_preferred_resolutions")
        return list(val) if isinstance(val, list) else []

    def get_resource_preferred_hdr(self) -> list[str]:
        val = self._data.get("resource_preferred_hdr")
        return list(val) if isinstance(val, list) else []

    def get_resource_preferred_codec(self) -> list[str]:
        val = self._data.get("resource_preferred_codec")
        return list(val) if isinstance(val, list) else []

    def get_resource_preferred_audio(self) -> list[str]:
        val = self._data.get("resource_preferred_audio")
        return list(val) if isinstance(val, list) else []

    def get_resource_preferred_subtitles(self) -> list[str]:
        val = self._data.get("resource_preferred_subtitles")
        return list(val) if isinstance(val, list) else []

    def get_resource_exclude_tags(self) -> list[str]:
        val = self._data.get("resource_exclude_tags")
        return list(val) if isinstance(val, list) else []

    def get_resource_min_size_gb(self) -> float | None:
        val = self._data.get("resource_min_size_gb")
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def get_resource_max_size_gb(self) -> float | None:
        val = self._data.get("resource_max_size_gb")
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def get_update_source_type(self) -> str:
        value = str(self._data.get("update_source_type") or "official").strip().lower()
        if value == "custom_dockerhub":
            return "custom_dockerhub"
        return "official"

    def get_update_repository(self) -> str:
        value = str(self._data.get("update_repository") or "").strip()
        return value or "wangsy1007/mediasync115"

    def get_archive_enabled(self) -> bool:
        return bool(self._data.get("archive_enabled", False))

    def get_archive_watch_cid(self) -> str:
        return str(self._data.get("archive_watch_cid") or "").strip()

    def get_archive_watch_name(self) -> str:
        return str(self._data.get("archive_watch_name") or "").strip()

    def get_archive_output_cid(self) -> str:
        return str(self._data.get("archive_output_cid") or "").strip()

    def get_archive_output_name(self) -> str:
        return str(self._data.get("archive_output_name") or "").strip()

    def get_archive_interval_minutes(self) -> int:
        value = self._data.get("archive_interval_minutes", 10)
        try:
            return max(1, int(value))
        except Exception:
            return 10

    def get_archive_auto_on_transfer(self) -> bool:
        return bool(self._data.get("archive_auto_on_transfer", True))

    def get_archive_auto_on_offline(self) -> bool:
        return bool(self._data.get("archive_auto_on_offline", True))

    def get_offline_monitor_interval_minutes(self) -> int:
        value = self._data.get("offline_monitor_interval_minutes", 3)
        try:
            return max(1, int(value))
        except Exception:
            return 3

    def get_archive_subdirs(self) -> dict[str, Any]:
        raw = self._data.get("archive_subdirs")
        try:
            return normalize_archive_subdirs(raw)
        except ValueError:
            return normalize_archive_subdirs(DEFAULT_ARCHIVE_SUBDIRS)

    def get_archive_naming(self) -> dict[str, str]:
        raw = self._data.get("archive_naming")
        try:
            return normalize_archive_naming(raw)
        except ValueError:
            return normalize_archive_naming(DEFAULT_ARCHIVE_NAMING)

    def get_archive_config(self) -> dict[str, Any]:
        return {
            "archive_enabled": self.get_archive_enabled(),
            "archive_watch_cid": self.get_archive_watch_cid(),
            "archive_watch_name": self.get_archive_watch_name(),
            "archive_output_cid": self.get_archive_output_cid(),
            "archive_output_name": self.get_archive_output_name(),
            "archive_interval_minutes": self.get_archive_interval_minutes(),
            "archive_auto_on_transfer": self.get_archive_auto_on_transfer(),
            "archive_auto_on_offline": self.get_archive_auto_on_offline(),
            "offline_monitor_interval_minutes": self.get_offline_monitor_interval_minutes(),
            "strm_auto_after_archive": self.get_strm_auto_after_archive(),
            "archive_subdirs": self.get_archive_subdirs(),
            "archive_naming": self.get_archive_naming(),
        }

    def get_strm_enabled(self) -> bool:
        return bool(self._data.get("strm_enabled", False))

    def get_strm_output_dir(self) -> str:
        return str(self._data.get("strm_output_dir") or "").strip()

    def get_strm_base_url(self) -> str:
        return str(self._data.get("strm_base_url") or "").strip().rstrip("/")

    def get_strm_redirect_mode(self) -> str:
        value = str(self._data.get("strm_redirect_mode") or "redirect").strip().lower()
        if value == "proxy":
            return "proxy"
        if value == "auto":
            return "redirect"
        return "redirect"

    def get_strm_auto_after_archive(self) -> bool:
        """归档成功后是否自动增量生成 STRM；缺省开启。"""
        if "strm_auto_after_archive" not in self._data:
            return True
        return bool(self._data.get("strm_auto_after_archive"))

    def get_strm_refresh_emby_after_generate(self) -> bool:
        return bool(self._data.get("strm_refresh_emby_after_generate", False))

    def get_strm_refresh_feiniu_after_generate(self) -> bool:
        return bool(self._data.get("strm_refresh_feiniu_after_generate", False))

    def get_strm_token_secret(self) -> str:
        return str(self._data.get("strm_token_secret") or "").strip()

    def get_strm_proxy_enabled(self) -> bool:
        return bool(self._data.get("strm_proxy_enabled", False))

    def get_strm_proxy_port(self) -> int:
        return int(self._data.get("strm_proxy_port") or 8099)

    def get_strm_early_redirect(self) -> bool:
        """SmartStrm 风格：PlaybackInfo 阶段提前返回 CDN 直链，缩短首播等待。"""
        if "strm_early_redirect" not in self._data:
            return True
        return bool(self._data.get("strm_early_redirect"))

    def get_strm_schedule_enabled(self) -> bool:
        return bool(self._data.get("strm_schedule_enabled", False))

    def get_strm_incremental_interval_minutes(self) -> int:
        try:
            return max(1, int(self._data.get("strm_incremental_interval_minutes", 360)))
        except (TypeError, ValueError):
            return 360

    def get_strm_full_schedule_enabled(self) -> bool:
        return bool(self._data.get("strm_full_schedule_enabled", False))

    def get_strm_full_schedule_day(self) -> str:
        value = str(self._data.get("strm_full_schedule_day") or "sun").lower()
        return value if value in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"} else "sun"

    def get_strm_full_schedule_time(self) -> str:
        value = str(self._data.get("strm_full_schedule_time") or "03:00").strip()
        try:
            hour, minute = (int(part) for part in value.split(":", 1))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        except (TypeError, ValueError):
            pass
        return "03:00"

    def get_strm_config(self) -> dict[str, Any]:
        return {
            "strm_enabled": self.get_strm_enabled(),
            "strm_output_dir": self.get_strm_output_dir(),
            "strm_base_url": self.get_strm_base_url(),
            "strm_redirect_mode": self.get_strm_redirect_mode(),
            "strm_auto_after_archive": self.get_strm_auto_after_archive(),
            "strm_refresh_emby_after_generate": self.get_strm_refresh_emby_after_generate(),
            "strm_refresh_feiniu_after_generate": self.get_strm_refresh_feiniu_after_generate(),
            "strm_proxy_enabled": self.get_strm_proxy_enabled(),
            "strm_proxy_port": self.get_strm_proxy_port(),
            "strm_early_redirect": self.get_strm_early_redirect(),
            "strm_schedule_enabled": self.get_strm_schedule_enabled(),
            "strm_incremental_interval_minutes": self.get_strm_incremental_interval_minutes(),
            "strm_full_schedule_enabled": self.get_strm_full_schedule_enabled(),
            "strm_full_schedule_day": self.get_strm_full_schedule_day(),
            "strm_full_schedule_time": self.get_strm_full_schedule_time(),
        }

    def update_strm_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("STRM 配置格式无效")

        if "strm_enabled" in payload and payload["strm_enabled"] is not None:
            self._data["strm_enabled"] = bool(payload["strm_enabled"])
        if "strm_output_dir" in payload and payload["strm_output_dir"] is not None:
            self._data["strm_output_dir"] = str(
                payload["strm_output_dir"] or ""
            ).strip()
        if "strm_base_url" in payload and payload["strm_base_url"] is not None:
            self._data["strm_base_url"] = (
                str(payload["strm_base_url"] or "").strip().rstrip("/")
            )
        if (
            "strm_redirect_mode" in payload
            and payload["strm_redirect_mode"] is not None
        ):
            mode = str(payload["strm_redirect_mode"] or "redirect").strip().lower()
            if mode == "auto":
                mode = "redirect"
            if mode not in {"redirect", "proxy"}:
                raise ValueError("STRM 播放模式仅支持 redirect / proxy")
            self._data["strm_redirect_mode"] = mode
        if (
            "strm_auto_after_archive" in payload
            and payload["strm_auto_after_archive"] is not None
        ):
            self._data["strm_auto_after_archive"] = bool(
                payload["strm_auto_after_archive"]
            )
        if (
            "strm_refresh_emby_after_generate" in payload
            and payload["strm_refresh_emby_after_generate"] is not None
        ):
            self._data["strm_refresh_emby_after_generate"] = bool(
                payload["strm_refresh_emby_after_generate"]
            )
        if (
            "strm_refresh_feiniu_after_generate" in payload
            and payload["strm_refresh_feiniu_after_generate"] is not None
        ):
            self._data["strm_refresh_feiniu_after_generate"] = bool(
                payload["strm_refresh_feiniu_after_generate"]
            )
        if "strm_token_secret" in payload and payload["strm_token_secret"] is not None:
            self._data["strm_token_secret"] = str(
                payload["strm_token_secret"] or ""
            ).strip()
        if "strm_proxy_enabled" in payload and payload["strm_proxy_enabled"] is not None:
            self._data["strm_proxy_enabled"] = bool(payload["strm_proxy_enabled"])
        if "strm_proxy_port" in payload and payload["strm_proxy_port"] is not None:
            self._data["strm_proxy_port"] = int(payload["strm_proxy_port"] or 8099)
        if (
            "strm_early_redirect" in payload
            and payload["strm_early_redirect"] is not None
        ):
            self._data["strm_early_redirect"] = bool(payload["strm_early_redirect"])
        if "strm_schedule_enabled" in payload and payload["strm_schedule_enabled"] is not None:
            self._data["strm_schedule_enabled"] = bool(payload["strm_schedule_enabled"])
        if (
            "strm_incremental_interval_minutes" in payload
            and payload["strm_incremental_interval_minutes"] is not None
        ):
            interval = int(payload["strm_incremental_interval_minutes"])
            if interval < 1:
                raise ValueError("STRM 增量生成间隔不能少于 1 分钟")
            self._data["strm_incremental_interval_minutes"] = interval
        if (
            "strm_full_schedule_enabled" in payload
            and payload["strm_full_schedule_enabled"] is not None
        ):
            self._data["strm_full_schedule_enabled"] = bool(
                payload["strm_full_schedule_enabled"]
            )
        if "strm_full_schedule_day" in payload and payload["strm_full_schedule_day"] is not None:
            day = str(payload["strm_full_schedule_day"]).strip().lower()
            if day not in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
                raise ValueError("STRM 全量校准星期设置无效")
            self._data["strm_full_schedule_day"] = day
        if "strm_full_schedule_time" in payload and payload["strm_full_schedule_time"] is not None:
            value = str(payload["strm_full_schedule_time"]).strip()
            try:
                hour, minute = (int(part) for part in value.split(":", 1))
            except (TypeError, ValueError) as exc:
                raise ValueError("STRM 全量校准时间格式应为 HH:MM") from exc
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("STRM 全量校准时间格式应为 HH:MM")
            self._data["strm_full_schedule_time"] = f"{hour:02d}:{minute:02d}"

        self._save()
        return self.get_strm_config()

    def update_archive_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("归档配置格式无效")

        if "archive_enabled" in payload and payload["archive_enabled"] is not None:
            self._data["archive_enabled"] = bool(payload["archive_enabled"])
        if "archive_watch_cid" in payload and payload["archive_watch_cid"] is not None:
            self._data["archive_watch_cid"] = str(
                payload["archive_watch_cid"] or ""
            ).strip()
        if (
            "archive_watch_name" in payload
            and payload["archive_watch_name"] is not None
        ):
            self._data["archive_watch_name"] = str(
                payload["archive_watch_name"] or ""
            ).strip()
        if (
            "archive_output_cid" in payload
            and payload["archive_output_cid"] is not None
        ):
            self._data["archive_output_cid"] = str(
                payload["archive_output_cid"] or ""
            ).strip()
        if (
            "archive_output_name" in payload
            and payload["archive_output_name"] is not None
        ):
            self._data["archive_output_name"] = str(
                payload["archive_output_name"] or ""
            ).strip()
        if (
            "archive_interval_minutes" in payload
            and payload["archive_interval_minutes"] is not None
        ):
            self._data["archive_interval_minutes"] = max(
                1, int(payload["archive_interval_minutes"])
            )
        if (
            "archive_auto_on_transfer" in payload
            and payload["archive_auto_on_transfer"] is not None
        ):
            self._data["archive_auto_on_transfer"] = bool(
                payload["archive_auto_on_transfer"]
            )
        if (
            "archive_auto_on_offline" in payload
            and payload["archive_auto_on_offline"] is not None
        ):
            self._data["archive_auto_on_offline"] = bool(
                payload["archive_auto_on_offline"]
            )
        if (
            "strm_auto_after_archive" in payload
            and payload["strm_auto_after_archive"] is not None
        ):
            self._data["strm_auto_after_archive"] = bool(
                payload["strm_auto_after_archive"]
            )
        if (
            "offline_monitor_interval_minutes" in payload
            and payload["offline_monitor_interval_minutes"] is not None
        ):
            self._data["offline_monitor_interval_minutes"] = max(
                1, int(payload["offline_monitor_interval_minutes"])
            )
        if "archive_subdirs" in payload and payload["archive_subdirs"] is not None:
            self._data["archive_subdirs"] = normalize_archive_subdirs(
                payload["archive_subdirs"]
            )
        if "archive_naming" in payload and payload["archive_naming"] is not None:
            self._data["archive_naming"] = normalize_archive_naming(
                payload["archive_naming"]
            )

        self._save()
        return self.get_archive_config()

    def update_bulk(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("配置数据格式无效")

        normalized = dict(self._data)
        env_updates: dict[str, Any] = {}
        for key in self._defaults.keys():
            if key not in payload:
                continue
            value = payload.get(key)
            if key in self.ENV_FIELD_MAP:
                env_updates[key] = value
                continue

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
                # TG Bot 的用户 ID / Chat ID 列表直接保存为整数列表
                if key in ("tg_bot_allowed_users", "tg_bot_notify_chat_ids"):
                    if isinstance(value, list):
                        int_list = []
                        for item in value:
                            try:
                                int_list.append(int(item))
                            except (ValueError, TypeError):
                                continue
                        normalized[key] = int_list
                    continue

                if key in (
                    "detail_visible_tabs",
                    "resource_preferred_resolutions",
                    "resource_preferred_hdr",
                    "resource_preferred_audio",
                    "resource_preferred_subtitles",
                    "resource_exclude_tags",
                ):
                    if isinstance(value, list):
                        normalized[key] = [
                            str(v).strip() for v in value if str(v).strip()
                        ]
                    continue

                if key == "chart_subscription_sources":
                    if isinstance(value, list):
                        normalized[key] = [
                            item
                            for item in value
                            if isinstance(item, dict)
                            and item.get("source")
                            and item.get("key")
                        ]
                    continue

                source_items: list[str] = []
                if isinstance(value, str):
                    source_items = [part.strip() for part in value.split(",")]
                elif isinstance(value, list):
                    source_items = [str(part or "").strip() for part in value]
                else:
                    continue

                if key == "subscription_resource_priority":
                    allowed = {"hdhive", "pansou", "tg"}
                elif key == "subscription_resource_enabled":
                    allowed = self._subscription_resource_source_set()
                    defaults = {
                        source: True for source in allowed
                    }
                    normalized_map = dict(defaults)
                    if isinstance(value, dict):
                        for raw_source, raw_enabled in value.items():
                            source = str(raw_source or "").strip().lower()
                            if source in allowed:
                                normalized_map[source] = bool(raw_enabled)
                    normalized[key] = normalized_map
                    continue
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
        self._persist_env_backed_fields(env_updates)
        self._loaded_keys.update(self._data.keys())
        self._save()
        self.apply_runtime_overrides()
        return self.get_all()

    def apply_runtime_overrides(self) -> None:
        settings.HTTP_PROXY = str(self._data.get("http_proxy") or "").strip() or None
        settings.HTTPS_PROXY = str(self._data.get("https_proxy") or "").strip() or None
        settings.ALL_PROXY = str(self._data.get("all_proxy") or "").strip() or None
        settings.SOCKS_PROXY = str(self._data.get("socks_proxy") or "").strip() or None
        settings.PAN115_COOKIE = self.get_pan115_cookie() or None
        settings.QUARK_COOKIE = self.get_quark_cookie() or None
        settings.HDHIVE_COOKIE = self.get_hdhive_cookie() or None
        settings.HDHIVE_BASE_URL = self.get_hdhive_base_url()
        settings.PANSOU_BASE_URL = self.get_pansou_base_url()
        settings.TG_API_ID = self.get_tg_api_id() or None
        settings.TG_API_HASH = self.get_tg_api_hash() or None
        settings.TG_PHONE = self.get_tg_phone() or None
        settings.TG_SESSION = self.get_tg_session() or None
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
        settings.FEINIU_URL = self.get_feiniu_url()
        settings.FEINIU_SECRET = self.get_feiniu_secret()
        settings.FEINIU_API_KEY = self.get_feiniu_api_key()

        proxy_manager.update_proxy(
            http_proxy=self._data.get("http_proxy"),
            https_proxy=self._data.get("https_proxy"),
            all_proxy=self._data.get("all_proxy"),
            socks_proxy=self._data.get("socks_proxy"),
        )

        # Keep the singleton client in sync with runtime cookie updates.
        from app.services.pan115_service import pan115_service

        pan115_service.update_cookie(self.get_pan115_cookie())
        from app.services.quark_service import quark_service
        quark_service.update_cookie(self.get_quark_cookie())
        hdhive_service.set_cookie(self.get_hdhive_cookie())
        hdhive_service.set_base_url(self.get_hdhive_base_url())
        pansou_service.set_base_url(self.get_pansou_base_url())
        tg_service.set_config(
            api_id=self.get_tg_api_id(),
            api_hash=self.get_tg_api_hash(),
            phone=self.get_tg_phone(),
            session=self.get_tg_session(),
            channels=self.get_tg_channel_usernames(),
            search_days=self.get_tg_search_days(),
            max_messages=self.get_tg_max_messages_per_channel(),
        )
        emby_service.set_config(
            base_url=self.get_emby_url(),
            api_key=self.get_emby_api_key(),
        )
        from app.services.feiniu_service import feiniu_service

        feiniu_service.configure_client(
            base_url=self.get_feiniu_url(),
            username=self.get_feiniu_login_username(),
            password=self.get_feiniu_password(),
            token=self.get_feiniu_session_token(),
        )
        from app.services.license_service import license_service

        license_service.set_license_key(str(self._data.get("license_key") or ""))

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def get_all(self) -> dict[str, Any]:
        return {
            "http_proxy": str(self._data.get("http_proxy") or ""),
            "https_proxy": str(self._data.get("https_proxy") or ""),
            "all_proxy": str(self._data.get("all_proxy") or ""),
            "socks_proxy": str(self._data.get("socks_proxy") or ""),
            "pan115_default_folder_id": self.get_pan115_default_folder()["folder_id"],
            "pan115_default_folder_name": self.get_pan115_default_folder()[
                "folder_name"
            ],
            "pan115_offline_folder_id": self.get_pan115_offline_folder()["folder_id"],
            "pan115_offline_folder_name": self.get_pan115_offline_folder()[
                "folder_name"
            ],
            "hdhive_cookie": self.get_hdhive_cookie(),
            "hdhive_base_url": self.get_hdhive_base_url(),
            "hdhive_auto_checkin_enabled": self.get_hdhive_auto_checkin_enabled(),
            "hdhive_auto_checkin_mode": self.get_hdhive_auto_checkin_mode(),
            "hdhive_auto_checkin_method": self.get_hdhive_auto_checkin_method(),
            "hdhive_auto_checkin_run_time": self.get_hdhive_auto_checkin_run_time(),
            "pansou_base_url": self.get_pansou_base_url(),
            "tg_api_id": self.get_tg_api_id(),
            "tg_api_hash": self.get_tg_api_hash(),
            "tg_phone": self.get_tg_phone(),
            "tg_session": self.get_tg_session(),
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
            "emby_sync_interval_minutes": self.get_emby_sync_interval_minutes(),
            "feiniu_url": self.get_feiniu_url(),
            "feiniu_secret": self.get_feiniu_secret(),
            "feiniu_api_key": self.get_feiniu_api_key(),
            "feiniu_session_token": self.get_feiniu_session_token(),
            "feiniu_sync_enabled": self.get_feiniu_sync_enabled(),
            "feiniu_sync_interval_hours": self.get_feiniu_sync_interval_hours(),
            "feiniu_sync_interval_minutes": self.get_feiniu_sync_interval_minutes(),
            "auth_username": self.get_auth_username(),
            "subscription_enabled": bool(
                self._data.get("subscription_enabled", False)
            ),
            "subscription_interval_hours": int(
                self._data.get("subscription_interval_hours", 24) or 24
            ),
            "subscription_resource_priority": self.get_subscription_resource_priority(),
            "subscription_resource_enabled": self.get_subscription_resource_enabled(),
            "subscription_hdhive_auto_unlock_enabled": self.get_subscription_hdhive_auto_unlock_enabled(),
            "subscription_hdhive_unlock_max_points_per_item": self.get_subscription_hdhive_unlock_max_points_per_item(),
            "subscription_hdhive_unlock_budget_points_per_run": self.get_subscription_hdhive_unlock_budget_points_per_run(),
            "subscription_hdhive_unlock_threshold_inclusive": self.get_subscription_hdhive_unlock_threshold_inclusive(),
            "subscription_hdhive_prefer_free": self.get_subscription_hdhive_prefer_free(),
            "resource_preferred_resolutions": self.get_resource_preferred_resolutions(),
            "resource_preferred_hdr": self.get_resource_preferred_hdr(),
            "resource_preferred_audio": self.get_resource_preferred_audio(),
            "resource_preferred_subtitles": self.get_resource_preferred_subtitles(),
            "resource_exclude_tags": self.get_resource_exclude_tags(),
            "resource_min_size_gb": self.get_resource_min_size_gb(),
            "resource_max_size_gb": self.get_resource_max_size_gb(),
            "update_source_type": self.get_update_source_type(),
            "update_repository": self.get_update_repository(),
            "tg_bot_token": str(self._data.get("tg_bot_token") or ""),
            "tg_bot_enabled": bool(self._data.get("tg_bot_enabled", False)),
            "tg_bot_allowed_users": self._data.get("tg_bot_allowed_users") or [],
            "tg_bot_notify_chat_ids": self._data.get("tg_bot_notify_chat_ids") or [],
            "tg_bot_hdhive_auto_unlock": bool(self._data.get("tg_bot_hdhive_auto_unlock", False)),
            "detail_visible_tabs": self._data.get("detail_visible_tabs") or [],
            "license_key": str(self._data.get("license_key") or ""),
            "subscription_offline_transfer_enabled": self.get_subscription_offline_transfer_enabled(),
            "subscription_auto_sync_after_transfer": self.get_subscription_auto_sync_after_transfer(),
            "subscription_exclude_iso": self.get_subscription_exclude_iso(),
            "chart_subscription_enabled": bool(
                self._data.get("chart_subscription_enabled", False)
            ),
            "chart_subscription_sources": self._data.get("chart_subscription_sources")
            or [],
            "chart_subscription_limit": int(
                self._data.get("chart_subscription_limit", 20) or 20
            ),
            "chart_subscription_interval_hours": int(
                self._data.get("chart_subscription_interval_hours", 24) or 24
            ),
            "person_follow_enabled": bool(
                self._data.get("person_follow_enabled", False)
            ),
            "person_follow_interval_hours": int(
                self._data.get("person_follow_interval_hours", 24) or 24
            ),
            "person_follow_auto_subscribe": bool(
                self._data.get("person_follow_auto_subscribe", True)
            ),
            "archive_enabled": self.get_archive_enabled(),
            "archive_watch_cid": self.get_archive_watch_cid(),
            "archive_output_cid": self.get_archive_output_cid(),
            "archive_interval_minutes": self.get_archive_interval_minutes(),
            "strm_enabled": self.get_strm_enabled(),
            "strm_output_dir": self.get_strm_output_dir(),
            "strm_base_url": self.get_strm_base_url(),
            "strm_redirect_mode": self.get_strm_redirect_mode(),
            "strm_auto_after_archive": self.get_strm_auto_after_archive(),
            "strm_refresh_emby_after_generate": self.get_strm_refresh_emby_after_generate(),
            "strm_refresh_feiniu_after_generate": self.get_strm_refresh_feiniu_after_generate(),
            "strm_proxy_enabled": self.get_strm_proxy_enabled(),
            "strm_proxy_port": self.get_strm_proxy_port(),
            "strm_early_redirect": self.get_strm_early_redirect(),
            "strm_schedule_enabled": self.get_strm_schedule_enabled(),
            "strm_incremental_interval_minutes": self.get_strm_incremental_interval_minutes(),
            "strm_full_schedule_enabled": self.get_strm_full_schedule_enabled(),
            "strm_full_schedule_day": self.get_strm_full_schedule_day(),
            "strm_full_schedule_time": self.get_strm_full_schedule_time(),
            "llm_base_url": self.get_llm_base_url(),
            "llm_model": self.get_llm_model(),
            "llm_api_key_set": self.has_llm_api_key(),
            "llm_enabled": self.get_llm_enabled(),
        }


runtime_settings_service = RuntimeSettingsService()
hdhive_service.set_cookie_update_callback(runtime_settings_service.update_hdhive_cookie)
