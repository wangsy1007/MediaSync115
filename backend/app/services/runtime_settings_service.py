import json
import os
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.hdhive_service import hdhive_service
from app.services.nullbr_client import nullbr_client
from app.services.pansou_service import pansou_service


class RuntimeSettingsService:
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
            "tmdb_api_key": settings.TMDB_API_KEY or "",
            "tmdb_base_url": settings.TMDB_BASE_URL,
            "tmdb_image_base_url": settings.TMDB_IMAGE_BASE_URL,
            "tmdb_language": settings.TMDB_LANGUAGE,
            "tmdb_region": settings.TMDB_REGION,
            "subscription_nullbr_enabled": False,
            "subscription_nullbr_interval_hours": 24,
            "subscription_nullbr_run_time": "03:00",
            "subscription_pansou_enabled": False,
            "subscription_pansou_interval_hours": 24,
            "subscription_pansou_run_time": "03:30",
        }
        self._data = dict(self._defaults)
        self._load()
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

        settings.TMDB_API_KEY = self.get_tmdb_api_key() or None
        settings.TMDB_BASE_URL = self.get_tmdb_base_url()
        settings.TMDB_IMAGE_BASE_URL = self.get_tmdb_image_base_url()
        settings.TMDB_LANGUAGE = self.get_tmdb_language()
        settings.TMDB_REGION = self.get_tmdb_region()

        hdhive_service.set_cookie(self.get_hdhive_cookie())
        hdhive_service.set_base_url(self.get_hdhive_base_url())
        pansou_service.set_base_url(self.get_pansou_base_url())
        nullbr_client.update_config(
            app_id=self.get_nullbr_app_id(),
            api_key=self.get_nullbr_api_key(),
            base_url=self.get_nullbr_base_url(),
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
            "tmdb_api_key": self.get_tmdb_api_key(),
            "tmdb_base_url": self.get_tmdb_base_url(),
            "tmdb_image_base_url": self.get_tmdb_image_base_url(),
            "tmdb_language": self.get_tmdb_language(),
            "tmdb_region": self.get_tmdb_region(),
            "subscription_nullbr_enabled": bool(self._data.get("subscription_nullbr_enabled", False)),
            "subscription_nullbr_interval_hours": int(self._data.get("subscription_nullbr_interval_hours", 24) or 24),
            "subscription_nullbr_run_time": str(self._data.get("subscription_nullbr_run_time", "03:00") or "03:00"),
            "subscription_pansou_enabled": bool(self._data.get("subscription_pansou_enabled", False)),
            "subscription_pansou_interval_hours": int(self._data.get("subscription_pansou_interval_hours", 24) or 24),
            "subscription_pansou_run_time": str(self._data.get("subscription_pansou_run_time", "03:30") or "03:30"),
        }


runtime_settings_service = RuntimeSettingsService()
