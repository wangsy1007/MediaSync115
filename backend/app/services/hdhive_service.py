import asyncio
import json
import re
import unicodedata
from time import monotonic
from typing import Any

import httpx

from app.core.config import settings
from app.services.tmdb_service import tmdb_service
from app.utils.proxy import proxy_manager


class HDHiveApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str = "",
        message: str = "",
        description: str = "",
    ) -> None:
        self.status_code = int(status_code or 500)
        self.code = str(code or "").strip()
        self.message = str(message or "").strip()
        self.description = str(description or "").strip()
        parts: list[str] = []
        if self.message:
            parts.append(self.message)
        if self.description and self.description != self.message:
            parts.append(self.description)
        if self.code and self.code not in parts:
            parts.append(self.code)
        final_message = "；".join(parts) if parts else f"HTTP {self.status_code}"
        super().__init__(final_message)


class HDHiveService:
    def __init__(
        self,
        base_url: str | None = None,
        cookie: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._base_url = str(base_url or settings.HDHIVE_BASE_URL or "https://hdhive.com/").strip().rstrip("/")
        self._cookie = str(cookie or settings.HDHIVE_COOKIE or "").strip()
        self._api_key = str(api_key or settings.HDHIVE_API_KEY or "").strip()
        self._timeout = 20.0
        self._user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        self._unlock_locks: dict[str, asyncio.Lock] = {}
        self._unlock_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._unlock_cache_ttl_seconds = 120.0

    @staticmethod
    def _extract_error_text(response: httpx.Response) -> str:
        try:
            text = str(response.text or "").strip()
        except Exception:
            return ""
        if not text:
            return ""
        normalized = re.sub(r"\s+", " ", text)
        if normalized.startswith("<"):
            return ""
        return normalized[:200]

    def set_base_url(self, base_url: str | None) -> None:
        value = str(base_url or "").strip()
        if not value:
            return
        self._base_url = value.rstrip("/")

    def set_cookie(self, cookie: str | None) -> None:
        self._cookie = str(cookie or "").strip()

    def set_api_key(self, api_key: str | None) -> None:
        self._api_key = str(api_key or "").strip()

    @staticmethod
    def _extract_optional_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if value == 1:
                return True
            if value == 0:
                return False
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
        return None

    @staticmethod
    def _classify_checkin_status(message: str, checked_in: bool | None) -> tuple[str, str]:
        normalized_message = str(message or "").strip()
        normalized_text = normalized_message.lower()
        already_keywords = (
            "已签到",
            "已经签到",
            "今日已签到",
            "今天已签到",
            "already checked",
            "already check",
            "already signed",
            "already sign",
        )
        if checked_in is False or any(keyword in normalized_text or keyword in normalized_message for keyword in already_keywords):
            return "already_checked_in", normalized_message or "今天已经签到过了，无需重复签到"
        return "success", normalized_message or "签到成功"

    def _create_client(self, **kwargs) -> httpx.AsyncClient:
        client_kwargs = {
            "timeout": self._timeout,
            "follow_redirects": True,
            **kwargs,
        }
        return proxy_manager.create_httpx_client(**client_kwargs)

    def _get_open_api_key(self) -> str:
        api_key = str(self._api_key or settings.HDHIVE_API_KEY or "").strip()
        if api_key:
            return api_key
        raise ValueError("未配置 HDHive API Key")

    def _build_open_api_headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {
            "user-agent": self._user_agent,
            "accept": "application/json",
            "x-api-key": self._get_open_api_key(),
        }
        if json_body:
            headers["content-type"] = "application/json"
        return headers

    def _build_open_api_url(self, path: str) -> str:
        normalized_path = str(path or "").strip()
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"
        return f"{self._base_url}/api/open{normalized_path}"

    @staticmethod
    def _extract_first_int(raw_value: Any) -> int | None:
        if raw_value is None or raw_value == "":
            return None
        if isinstance(raw_value, bool):
            return int(raw_value)
        if isinstance(raw_value, (int, float)):
            return int(raw_value)

        text = str(raw_value).strip()
        if not text:
            return None

        match = re.search(r"-?\d+", text.replace(",", ""))
        if not match:
            return None
        try:
            return int(match.group(0))
        except ValueError:
            return None

    @classmethod
    def _extract_user_points(cls, user_obj: dict[str, Any]) -> int | None:
        if not isinstance(user_obj, dict):
            return None

        candidate_keys = (
            "points",
            "point",
            "point_balance",
            "point_total",
            "credit",
            "credits",
            "credit_balance",
            "score",
            "scores",
            "integral",
            "balance",
            "wallet_points",
            "unlock_points_balance",
        )

        for key in candidate_keys:
            value = cls._extract_first_int(user_obj.get(key))
            if value is not None:
                return value

        nested_keys = (
            "user_meta",
            "meta",
            "profile",
            "stats",
            "user_stats",
        )
        for key in nested_keys:
            nested_obj = user_obj.get(key)
            if not isinstance(nested_obj, dict):
                continue
            value = cls._extract_user_points(nested_obj)
            if value is not None:
                return value
        return None

    @staticmethod
    def _extract_object_payload(raw: str, token: str) -> str:
        index = raw.find(token)
        if index < 0:
            return ""
        start = raw.find("{", index)
        if start < 0:
            return ""

        depth = 0
        in_string = False
        escaped = False
        for pos in range(start, len(raw)):
            char = raw[pos]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return raw[start:pos + 1]
        return ""

    @staticmethod
    def _extract_bracket_payload(raw: str, token: str) -> str:
        index = raw.find(token)
        if index < 0:
            return ""
        start = raw.find("[", index)
        if start < 0:
            return ""

        depth = 0
        for pos in range(start, len(raw)):
            char = raw[pos]
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return raw[start:pos + 1]
        return ""

    @staticmethod
    def _extract_next_static_chunk_paths(raw: str) -> list[str]:
        if not raw:
            return []
        matches = re.findall(r'/_next/static/chunks/[A-Za-z0-9._-]+\.js', raw)
        deduped: list[str] = []
        seen: set[str] = set()
        for item in matches:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    @staticmethod
    def _extract_server_action_id_from_chunk(raw: str, action_name: str) -> str:
        if not raw:
            return ""
        normalized_action = str(action_name or "").strip()
        if not normalized_action:
            return ""
        escaped_action = re.escape(normalized_action)
        patterns = (
            rf'createServerReference\)\("([A-Za-z0-9]+)".{{0,200}}?,"{escaped_action}"\)',
            rf'createServerReference[^"]*\("([A-Za-z0-9]+)".{{0,200}}?,"{escaped_action}"\)',
            rf'createServerReference[^"]*\("([A-Za-z0-9]+)".{{0,200}}?"{escaped_action}"',
        )
        for pattern in patterns:
            match = re.search(pattern, raw, re.S)
            if match:
                return str(match.group(1) or "").strip()
        return ""

    @staticmethod
    def _decode_json_candidates(payload: str) -> list[Any]:
        candidates: list[str] = [payload]
        normalized = payload
        normalized = normalized.replace('\\"', '"')
        normalized = normalized.replace("\\/", "/")
        normalized = normalized.replace("\\u0026", "&")
        candidates.append(normalized)
        candidates.append(normalized.replace("\\\n", ""))
        candidates.append(normalized.replace("\\\r\n", ""))

        parsed_values: list[Any] = []
        seen: set[str] = set()
        for item in candidates:
            key = item[:300]
            if key in seen:
                continue
            seen.add(key)
            try:
                parsed_values.append(json.loads(item))
            except Exception:
                continue
        return parsed_values

    @classmethod
    def _extract_current_user(cls, raw: str) -> dict[str, Any]:
        payload_candidates: list[str] = []

        normalized_raw = raw.replace('\\"', '"').replace("\\/", "/").replace("\\u0026", "&")
        normalized_payload = cls._extract_object_payload(normalized_raw, '"currentUser":{')
        if normalized_payload:
            payload_candidates.append(normalized_payload)

        direct_payload = cls._extract_object_payload(raw, '"currentUser":{')
        if direct_payload:
            payload_candidates.append(direct_payload)

        if not payload_candidates:
            return {}

        for payload in payload_candidates:
            for parsed in cls._decode_json_candidates(payload):
                if not isinstance(parsed, dict):
                    continue

                username = str(parsed.get("username") or parsed.get("nickname") or "").strip()
                nickname = str(parsed.get("nickname") or "").strip()
                raw_vip = parsed.get("is_vip")
                is_vip = False
                if isinstance(raw_vip, bool):
                    is_vip = raw_vip
                elif isinstance(raw_vip, (int, float)):
                    is_vip = int(raw_vip) > 0
                elif isinstance(raw_vip, str):
                    raw_vip_text = raw_vip.strip().lower()
                    is_vip = raw_vip_text == "true" or (raw_vip_text.isdigit() and int(raw_vip_text) > 0)

                user_info = {
                    "username": username,
                    "nickname": nickname,
                    "is_vip": bool(is_vip),
                }

                points = cls._extract_user_points(parsed)
                if points is not None:
                    user_info["points"] = points
                return user_info

        return {}

    async def _request_open_api(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[httpx.Response, dict[str, Any]]:
        headers = self._build_open_api_headers(json_body=json_body is not None)
        client = self._create_client()
        try:
            response = await client.request(
                method.upper(),
                self._build_open_api_url(path),
                headers=headers,
                params=params,
                json=json_body,
            )
        finally:
            await client.aclose()

        payload: dict[str, Any] = {}
        try:
            raw_payload = response.json()
            if isinstance(raw_payload, dict):
                payload = raw_payload
        except Exception:
            payload = {}

        success = bool(payload.get("success")) if payload else response.is_success
        if response.is_error or not success:
            raise HDHiveApiError(
                status_code=response.status_code or 500,
                code=str(payload.get("code") or "").strip(),
                message=str(payload.get("message") or self._extract_error_text(response) or "").strip(),
                description=str(payload.get("description") or "").strip(),
            )
        return response, payload

    @staticmethod
    def _normalize_media_type(media_type: str) -> str:
        return "tv" if str(media_type or "").strip().lower() == "tv" else "movie"

    @staticmethod
    def _normalize_slug(slug: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", str(slug or "").strip())

    @staticmethod
    def _normalize_keyword(text: str) -> str:
        raw = unicodedata.normalize("NFKD", str(text or ""))
        raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
        return re.sub(r"[\s\-_·:：,.，。!！?？/\\\\'\"`()\\[\\]]+", "", raw.strip().lower())

    @staticmethod
    def _normalize_pan_type(raw_value: Any) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "", str(raw_value or "").strip().lower())
        if not normalized:
            return ""
        if normalized in {"115", "115com", "115wangpan", "115netdisk"}:
            return "115"
        return normalized

    @classmethod
    def _is_pan115(cls, raw_value: Any) -> bool:
        return cls._normalize_pan_type(raw_value) == "115"

    async def check_connection(self) -> dict[str, Any]:
        _, ping_payload = await self._request_open_api("GET", "/ping")
        ping_data = ping_payload.get("data") if isinstance(ping_payload.get("data"), dict) else {}

        user_info: dict[str, Any] | None = None
        message = "HDHive API Key 可用"
        try:
            user_info = await self.get_user_info()
            message = "HDHive API Key 可用，用户信息已获取"
        except HDHiveApiError as exc:
            if exc.status_code == 403 and exc.code == "VIP_REQUIRED":
                message = "HDHive API Key 可用，当前账号未开通 Premium，无法读取用户详情"
            else:
                raise

        return {
            "valid": True,
            "message": message,
            "user": user_info,
            "ping": ping_data,
        }

    async def get_user_info(self) -> dict[str, Any]:
        _, payload = await self._request_open_api("GET", "/me")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if not data:
            raise ValueError("未获取到 HDHive 用户信息，请检查 API Key")

        return {
            "id": data.get("id"),
            "username": str(data.get("username") or "").strip(),
            "nickname": str(data.get("nickname") or "").strip(),
            "email": str(data.get("email") or "").strip(),
            "avatar_url": str(data.get("avatar_url") or "").strip(),
            "is_vip": bool(data.get("is_vip")),
            "vip_expiration_date": str(data.get("vip_expiration_date") or "").strip(),
            "last_active_at": str(data.get("last_active_at") or "").strip(),
            "points": self._extract_user_points(data),
            "user_meta": data.get("user_meta") if isinstance(data.get("user_meta"), dict) else {},
            "telegram_user": data.get("telegram_user") if isinstance(data.get("telegram_user"), dict) else None,
            "created_at": str(data.get("created_at") or "").strip(),
        }

    async def check_in(self, gamble: bool = False) -> dict[str, Any]:
        """使用 Open API（需要 API Key，仅 Premium）签到。"""
        _, payload = await self._request_open_api(
            "POST",
            "/checkin",
            json_body={"is_gambler": bool(gamble)} if gamble else {},
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}

        user_info: dict[str, Any] = {}
        try:
            user_info = await self.get_user_info()
        except Exception:
            user_info = {}
        checked_in = self._extract_optional_bool(data.get("checked_in"))
        status, message = self._classify_checkin_status(
            str(payload.get("message") or data.get("message") or "").strip(),
            checked_in,
        )

        points_earned = self._extract_first_int(data.get("points_earned"))
        if points_earned is None:
            points_earned = self._extract_first_int(data.get("points"))
        if points_earned is None:
            points_earned = self._extract_first_int(data.get("change"))

        return {
            "success": status == "success",
            "status": status,
            "message": message,
            "mode": "gamble" if gamble else "normal",
            "method": "api",
            "code": str(payload.get("code") or "200").strip(),
            "data": data,
            "user": user_info,
            "points": self._extract_first_int(user_info.get("points")) if isinstance(user_info, dict) else None,
            "points_earned": points_earned,
            "checked_in": checked_in,
        }

    def _get_cookie(self) -> str:
        cookie = str(self._cookie or settings.HDHIVE_COOKIE or "").strip()
        if cookie:
            return cookie
        raise ValueError("未配置 HDHive Cookie")

    def _build_cookie_headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {
            "user-agent": self._user_agent,
            "accept": "application/json",
            "cookie": self._get_cookie(),
        }
        if json_body:
            headers["content-type"] = "application/json"
        return headers

    async def check_in_by_cookie(self, gamble: bool = False) -> dict[str, Any]:
        """使用 Cookie（所有用户均可）签到。"""
        headers = self._build_cookie_headers(json_body=True)
        url = f"{self._base_url}/api/checkin"
        body = {"is_gambler": True} if gamble else {}

        client = self._create_client()
        try:
            response = await client.post(url, headers=headers, json=body)
        finally:
            await client.aclose()

        payload: dict[str, Any] = {}
        try:
            raw = response.json()
            if isinstance(raw, dict):
                payload = raw
        except Exception:
            payload = {}

        success = bool(payload.get("success")) if payload else response.is_success
        if response.is_error or not success:
            raise HDHiveApiError(
                status_code=response.status_code or 500,
                code=str(payload.get("code") or "").strip(),
                message=str(payload.get("message") or self._extract_error_text(response) or "").strip(),
                description=str(payload.get("description") or "").strip(),
            )

        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        checked_in = self._extract_optional_bool(data.get("checked_in"))
        status, message = self._classify_checkin_status(
            str(payload.get("message") or data.get("message") or "").strip(),
            checked_in,
        )

        points_earned = self._extract_first_int(data.get("points_earned"))
        if points_earned is None:
            points_earned = self._extract_first_int(data.get("points"))
        if points_earned is None:
            points_earned = self._extract_first_int(data.get("change"))

        return {
            "success": status == "success",
            "status": status,
            "message": message,
            "mode": "gamble" if gamble else "normal",
            "method": "cookie",
            "code": str(payload.get("code") or "200").strip(),
            "data": data,
            "user": {},
            "points": None,
            "points_earned": points_earned,
            "checked_in": checked_in,
        }

    async def unlock_resource(self, slug: str) -> dict[str, Any]:
        normalized_slug = self._normalize_slug(slug)
        if not normalized_slug:
            return {"success": False, "message": "资源 slug 为空", "locked": True}

        cached = self._unlock_cache.get(normalized_slug)
        now = monotonic()
        if cached and (now - cached[0] < self._unlock_cache_ttl_seconds):
            return cached[1]

        lock = self._unlock_locks.setdefault(normalized_slug, asyncio.Lock())
        async with lock:
            cached = self._unlock_cache.get(normalized_slug)
            now = monotonic()
            if cached and (now - cached[0] < self._unlock_cache_ttl_seconds):
                return cached[1]

            _, payload = await self._request_open_api(
                "POST",
                "/resources/unlock",
                json_body={"slug": normalized_slug},
            )
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            share_link = str(data.get("full_url") or data.get("url") or "").strip()
            access_code = str(data.get("access_code") or "").strip()
            if not share_link and str(data.get("url") or "").strip() and access_code:
                joiner = "&" if "?" in str(data.get("url") or "") else "?"
                share_link = f"{str(data.get('url') or '').strip()}{joiner}password={access_code}"

            result = {
                "success": bool(share_link),
                "method": "open_api",
                "message": str(payload.get("message") or "").strip() or "资源解锁成功",
                "share_link": share_link,
                "access_code": access_code,
                "full_url": share_link,
                "already_owned": bool(data.get("already_owned")),
                "locked": False,
                "lock_code": "",
                "lock_message": "",
                "unlock_points": 0,
                "resource_url": str(data.get("url") or "").strip(),
            }
            self._unlock_cache[normalized_slug] = (monotonic(), result)
            return result

    def _map_resource_row(self, row: dict[str, Any], index: int) -> dict[str, Any]:
        resource_slug = self._normalize_slug(str(row.get("slug") or ""))
        unlock_points = int(row.get("unlock_points") or 0)
        title = str(row.get("title") or "").strip() or f"HDHive 资源 #{index + 1}"
        resource_name = str(row.get("remark") or "").strip() or title
        pan_type = self._normalize_pan_type(row.get("pan_type"))
        media_url = str(row.get("media_url") or "").strip()
        media_slug = self._normalize_slug(str(row.get("media_slug") or ""))
        validate_status = str(row.get("validate_status") or "").strip().lower()
        validate_message = str(row.get("validate_message") or "").strip()
        suspected_invalid = validate_status in {"invalid", "suspected_invalid", "suspect_invalid"}
        is_unlocked = bool(row.get("is_unlocked"))
        locked = True
        lock_message = "免费资源，解锁后可获取分享链接"
        if unlock_points > 0:
            lock_message = f"该资源需要 {unlock_points} 积分解锁"
        elif is_unlocked:
            lock_message = "已拥有该资源，点击后将获取分享链接"

        return {
            "id": resource_slug or f"hdhive-{index}",
            "slug": resource_slug,
            "title": title,
            "resource_name": resource_name,
            "size": str(row.get("share_size") or "").strip(),
            "quality": row.get("source") if isinstance(row.get("source"), list) else [],
            "resolution": row.get("video_resolution") if isinstance(row.get("video_resolution"), list) else [],
            "share_link": "",
            "access_code": "",
            "unlock_points": unlock_points,
            "hdhive_locked": locked,
            "hdhive_lock_code": "",
            "hdhive_lock_message": lock_message,
            "hdhive_resource_url": media_url,
            "hdhive_pan_type": pan_type,
            "hdhive_media_url": media_url,
            "hdhive_media_slug": media_slug,
            "hdhive_validate_status": validate_status,
            "hdhive_validate_message": validate_message,
            "hdhive_suspected_invalid": suspected_invalid,
            "source_service": "hdhive",
            "pan115_savable": False,
            "is_official": bool(row.get("is_official")) if row.get("is_official") is not None else None,
            "created_at": str(row.get("created_at") or "").strip(),
            "hdhive_unlocked_users_count": self._extract_first_int(row.get("unlocked_users_count")),
            "hdhive_is_unlocked": is_unlocked,
            "user": row.get("user") if isinstance(row.get("user"), dict) else None,
        }

    async def _collect_tmdb_resources(self, tmdb_id: int, media_type: str) -> dict[str, Any]:
        normalized_media_type = self._normalize_media_type(media_type)
        _, payload = await self._request_open_api(
            "GET",
            f"/resources/{normalized_media_type}/{int(tmdb_id)}",
        )
        rows = payload.get("data")
        if not isinstance(rows, list):
            rows = []
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        raw_total = self._extract_first_int(meta.get("total"))
        pan_type_counts: dict[str, int] = {}
        filtered_rows: list[dict[str, Any]] = []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            pan_type = self._normalize_pan_type(row.get("pan_type")) or "unknown"
            pan_type_counts[pan_type] = pan_type_counts.get(pan_type, 0) + 1
            if pan_type != "115":
                continue
            filtered_rows.append(self._map_resource_row(row, idx))
        return {
            "items": filtered_rows,
            "raw_total": raw_total if raw_total is not None else len(rows),
            "filtered_total": len(filtered_rows),
            "pan_type_counts": pan_type_counts,
        }

    async def _list_resources_by_tmdb(self, tmdb_id: int, media_type: str) -> list[dict[str, Any]]:
        payload = await self._collect_tmdb_resources(tmdb_id, media_type)
        items = payload.get("items")
        return list(items) if isinstance(items, list) else []

    async def _search_tmdb_candidates(self, keyword: str, media_type: str) -> list[int]:
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []

        try:
            payload = await tmdb_service.search_by_media_type(
                normalized_keyword,
                self._normalize_media_type(media_type),
                page=1,
            )
        except Exception:
            return []

        rows = payload.get("items") if isinstance(payload.get("items"), list) else []
        keyword_fp = self._normalize_keyword(normalized_keyword)
        scored: list[tuple[float, int]] = []
        seen: set[int] = set()

        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                tmdb_id = int(row.get("tmdb_id") or row.get("id") or 0)
            except Exception:
                continue
            if tmdb_id <= 0 or tmdb_id in seen:
                continue
            seen.add(tmdb_id)

            title = str(row.get("title") or row.get("name") or "").strip()
            title_fp = self._normalize_keyword(title)
            score = 0.0
            if keyword_fp and title_fp:
                if keyword_fp == title_fp:
                    score += 1000
                elif keyword_fp in title_fp:
                    score += 500
                elif title_fp in keyword_fp:
                    score += 300
            vote_average = row.get("vote_average")
            try:
                score += float(vote_average or 0)
            except Exception:
                pass
            scored.append((score, tmdb_id))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [tmdb_id for _, tmdb_id in scored[:5]]

    async def get_pan115_by_keyword(self, keyword: str, media_type: str = "movie") -> list[dict[str, Any]]:
        tmdb_candidates = await self._search_tmdb_candidates(keyword, media_type)
        if not tmdb_candidates:
            return []

        deduped: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for tmdb_id in tmdb_candidates:
            try:
                rows = await self._list_resources_by_tmdb(tmdb_id, media_type)
            except Exception:
                continue
            for row in rows:
                dedupe_key = str(row.get("slug") or "").strip().lower()
                if not dedupe_key or dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                deduped.append(row)
                if len(deduped) >= 30:
                    return deduped
        return deduped

    async def get_movie_pan115(self, tmdb_id: int) -> list[dict[str, Any]]:
        return await self._list_resources_by_tmdb(tmdb_id, "movie")

    async def get_tv_pan115(self, tmdb_id: int) -> list[dict[str, Any]]:
        return await self._list_resources_by_tmdb(tmdb_id, "tv")

    async def get_movie_pan115_result(self, tmdb_id: int) -> dict[str, Any]:
        return await self._collect_tmdb_resources(tmdb_id, "movie")

    async def get_tv_pan115_result(self, tmdb_id: int) -> dict[str, Any]:
        return await self._collect_tmdb_resources(tmdb_id, "tv")


    @staticmethod
    def sort_free_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sort resources so free ones (unlock_points=0) come first, preserving relative order."""
        return sorted(items, key=lambda r: int(r.get("unlock_points") or 0) > 0)


hdhive_service = HDHiveService()
