"""HDHive Cookie + Next.js 网页解析客户端。"""

import asyncio
import html
import json
import re
import unicodedata
from time import monotonic
from typing import Any
from urllib.parse import quote_plus, unquote, urlencode

import httpx

from app.core.config import settings
from app.services.tmdb_service import tmdb_service
from app.utils.proxy import proxy_manager


class HDHiveWebClient:
    def __init__(
        self,
        base_url: str | None = None,
        cookie: str | None = None,
    ) -> None:
        self._base_url = str(base_url or settings.HDHIVE_BASE_URL or "https://hdhive.com/").strip().rstrip("/")
        self._cookie = str(cookie or settings.HDHIVE_COOKIE or "").strip()
        self._timeout = 20.0
        self._user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        self._unlock_action_id = ""
        self._checkin_action_id = ""
        self._unlock_locks: dict[str, asyncio.Lock] = {}
        self._unlock_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._unlock_cache_ttl_seconds = 120.0
        self._unlock_action_id_cached_at = 0.0
        self._checkin_action_id_cached_at = 0.0
        self._unlock_action_id_ttl_seconds = 1800.0

    def set_base_url(self, base_url: str | None) -> None:
        value = str(base_url or "").strip()
        if not value:
            return
        self._base_url = value.rstrip("/")

    def set_cookie(self, cookie: str | None) -> None:
        self._cookie = str(cookie or "").strip()

    def _create_client(self, **kwargs) -> httpx.AsyncClient:
        """创建配置了代理的 httpx 客户端"""
        client_kwargs = {
            "timeout": self._timeout,
            "follow_redirects": True,
            **kwargs
        }
        return proxy_manager.create_httpx_client(**client_kwargs)

    async def _fetch_text(self, path: str, accept: str | None = None) -> str:
        headers = {
            "user-agent": self._user_agent,
            "accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if self._cookie:
            headers["cookie"] = self._cookie

        url = path if path.startswith("http") else f"{self._base_url}{path}"
        client = self._create_client()
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            self._apply_client_cookies(client)
            return response.text
        finally:
            await client.aclose()

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

        patterns = (
            r'/_next/static/chunks/[A-Za-z0-9._()/-]+\.js',
            r'static/chunks/[A-Za-z0-9._()/-]+\.js',
            r'/_next/static/chunks/app/\(auth\)/login/page-[A-Za-z0-9]+\.js',
            r'static/chunks/app/\(auth\)/login/page-[A-Za-z0-9]+\.js',
            r'app/\(auth\)/login/page-[A-Za-z0-9]+\.js',
            r'app/\(no-layout\)/resource/[A-Za-z0-9._()/-]+\.js',
        )
        matches: list[str] = []
        for pattern in patterns:
            matches.extend(re.findall(pattern, raw))

        deduped: list[str] = []
        seen: set[str] = set()
        for item in matches:
            value = str(item or "").strip()
            if not value:
                continue
            if not value.startswith("/_next/"):
                if value.startswith("static/chunks/"):
                    value = f"/_next/{value}"
                elif value.startswith("app/"):
                    value = f"/_next/static/chunks/{value}"
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)

        login_first = [path for path in deduped if "/login/page-" in path]
        others = [path for path in deduped if path not in login_first]
        return login_first + others

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

        # Some pages contain a trailing backslash before physical newline in script payload.
        # Keep JSON escapes as-is to avoid mojibake on CJK text.
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
    def _extract_json_like_array(cls, raw: str, field_name: str) -> list[dict[str, Any]]:
        # Next.js app-router payload is embedded in script strings.
        tokens = [
            f'"{field_name}":[',
            f'\\"{field_name}\\":[',
        ]

        for token in tokens:
            payload = cls._extract_bracket_payload(raw, token)
            if not payload:
                continue
            for parsed in cls._decode_json_candidates(payload):
                if isinstance(parsed, list):
                    rows = [item for item in parsed if isinstance(item, dict)]
                    if rows:
                        return rows
        return []

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
                    is_vip = raw_vip_text == "true" or raw_vip_text.isdigit() and int(raw_vip_text) > 0

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

    @staticmethod
    def _merge_user_info(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base or {})
        if not isinstance(extra, dict):
            return merged

        for key in ("username", "nickname", "points"):
            value = extra.get(key)
            if value is None or value == "":
                continue
            merged[key] = value

        if "is_vip" in extra:
            merged["is_vip"] = bool(extra.get("is_vip"))

        return merged

    async def _resolve_unlock_action_id(self, resource_html: str) -> str:
        now = monotonic()
        if (
            self._unlock_action_id
            and self._unlock_action_id_cached_at > 0
            and now - self._unlock_action_id_cached_at < self._unlock_action_id_ttl_seconds
        ):
            return self._unlock_action_id

        chunk_paths = self._extract_next_static_chunk_paths(resource_html)
        prioritized = [path for path in chunk_paths if "/7224-" in path or "/1088-" in path]
        search_paths = prioritized + [path for path in chunk_paths if path not in prioritized]
        for path in search_paths:
            try:
                chunk_text = await self._fetch_text(path, accept="application/javascript,text/javascript,*/*;q=0.8")
            except Exception:
                continue

            action_id = self._extract_server_action_id_from_chunk(chunk_text, "unlockResource")
            if not action_id:
                continue
            self._unlock_action_id = action_id
            self._unlock_action_id_cached_at = monotonic()
            return action_id

        return self._unlock_action_id

    async def _resolve_checkin_action_id(self, page_html: str) -> str:
        now = monotonic()
        if (
            self._checkin_action_id
            and self._checkin_action_id_cached_at > 0
            and now - self._checkin_action_id_cached_at < self._unlock_action_id_ttl_seconds
        ):
            return self._checkin_action_id

        chunk_paths = self._extract_next_static_chunk_paths(page_html)
        for path in chunk_paths:
            try:
                chunk_text = await self._fetch_text(path, accept="application/javascript,text/javascript,*/*;q=0.8")
            except Exception:
                continue

            action_id = self._extract_server_action_id_from_chunk(chunk_text, "checkIn")
            if not action_id:
                continue
            self._checkin_action_id = action_id
            self._checkin_action_id_cached_at = monotonic()
            return action_id

        return self._checkin_action_id

    @staticmethod
    def _serialize_response_cookies(response: httpx.Response) -> str:
        pairs: list[str] = []
        seen: set[str] = set()
        for name, value in response.cookies.items():
            key = str(name or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            pairs.append(f"{key}={value}")
        return "; ".join(pairs)

    def _parse_cookie_pairs(self, cookie_header: str | None = None) -> dict[str, str]:
        pairs: dict[str, str] = {}
        for part in str(cookie_header if cookie_header is not None else self._cookie or "").split(";"):
            item = part.strip()
            if not item or "=" not in item:
                continue
            name, value = item.split("=", 1)
            key = name.strip()
            if not key:
                continue
            pairs[key] = value.strip()
        return pairs

    @staticmethod
    def _serialize_cookie_pairs(pairs: dict[str, str]) -> str:
        return "; ".join(f"{key}={value}" for key, value in pairs.items() if key and value is not None)

    def _build_cookie_header(self, client: httpx.AsyncClient, base_cookie: str | None = None) -> str:
        pairs = self._parse_cookie_pairs(base_cookie)
        for name, value in client.cookies.items():
            key = str(name or "").strip()
            if not key:
                continue
            pairs[key] = str(value or "").strip()
        return self._serialize_cookie_pairs(pairs)

    async def _prefetch_action_token(self, client: httpx.AsyncClient) -> None:
        """刷新 Next.js Server Action 所需的 hdh_sa_token。"""
        await client.head(
            f"{self._base_url}/login",
            headers={"user-agent": self._user_agent},
        )

    @staticmethod
    def _is_action_token_error(parsed: dict[str, Any]) -> bool:
        code = str(parsed.get("code") or "").strip().lower()
        return code in {"action_token_invalid", "action_token_required"}

    def _merge_cookie_header(self, extra_cookie: str) -> None:
        extra = str(extra_cookie or "").strip()
        if not extra:
            return
        existing: dict[str, str] = {}
        for part in str(self._cookie or "").split(";"):
            item = part.strip()
            if not item or "=" not in item:
                continue
            name, value = item.split("=", 1)
            existing[name.strip()] = value.strip()
        for part in extra.split(";"):
            item = part.strip()
            if not item or "=" not in item:
                continue
            name, value = item.split("=", 1)
            existing[name.strip()] = value.strip()
        self._cookie = "; ".join(f"{k}={v}" for k, v in existing.items())

    def _serialize_client_cookies(self, client: httpx.AsyncClient) -> str:
        pairs: list[str] = []
        seen: set[str] = set()
        for name, value in client.cookies.items():
            key = str(name or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            pairs.append(f"{key}={value}")
        return "; ".join(pairs)

    def _apply_client_cookies(self, client: httpx.AsyncClient) -> None:
        cookie_header = self._serialize_client_cookies(client)
        if cookie_header:
            self._merge_cookie_header(cookie_header)

    async def check_connection(self) -> dict[str, Any]:
        if not self._cookie:
            raise ValueError("未配置 HDHive Cookie")

        user_info = await self.get_user_info()
        username = str(user_info.get("username") or user_info.get("nickname") or "").strip()
        if not username:
            raise ValueError("HDHive Cookie 无效或未登录")

        return {
            "valid": True,
            "message": "HDHive Cookie 有效，用户信息已获取",
            "user": user_info,
        }

    @staticmethod
    def _normalize_media_type(media_type: str) -> str:
        return "tv" if str(media_type or "").strip().lower() == "tv" else "movie"

    @staticmethod
    def _normalize_slug(slug: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", str(slug or "").strip())

    @staticmethod
    def _normalize_pan_type(raw_value: Any) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "", str(raw_value or "").strip().lower())
        if not normalized:
            return ""
        if normalized in {"115", "115com", "115wangpan", "115netdisk"}:
            return "115"
        return normalized

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
        if checked_in is False or any(
            keyword in normalized_text or keyword in normalized_message
            for keyword in already_keywords
        ):
            return "already_checked_in", normalized_message or "今天已经签到过了，无需重复签到"
        return "success", normalized_message or "签到成功"

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

    async def _collect_tmdb_resources(
        self,
        tmdb_id: int,
        media_type: str,
        *,
        target_pan_type: str = "115",
    ) -> dict[str, Any]:
        normalized_media_type = self._normalize_media_type(media_type)
        slug = await self._resolve_media_slug(tmdb_id, normalized_media_type)
        detail_path = (
            f"/{normalized_media_type}/{slug}"
            if not slug.isdigit()
            else f"/{normalized_media_type}/{int(tmdb_id)}"
        )
        detail_html = await self._fetch_text(detail_path)
        field_name = "115" if target_pan_type == "115" else "quark"
        rows = self._extract_json_like_array(detail_html, field_name=field_name)

        if not rows and not slug.isdigit():
            fallback_html = await self._fetch_text(f"/{normalized_media_type}/{int(tmdb_id)}")
            rows = self._extract_json_like_array(fallback_html, field_name=field_name)

        pan_type_counts: dict[str, int] = {}
        filtered_rows: list[dict[str, Any]] = []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            pan_type = self._normalize_pan_type(row.get("pan_type")) or target_pan_type
            pan_type_counts[pan_type] = pan_type_counts.get(pan_type, 0) + 1
            if pan_type != target_pan_type:
                continue
            filtered_rows.append(self._map_resource_row(row, idx))

        return {
            "items": filtered_rows,
            "raw_total": len(rows),
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

    @staticmethod
    def sort_free_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(items, key=lambda r: int(r.get("unlock_points") or 0) > 0)

    @staticmethod
    def _extract_media_slug_from_home(raw: str, tmdb_id: int, media_type: str) -> str:
        escaped_tmdb = str(int(tmdb_id))
        escaped_type = "tv" if media_type == "tv" else "movie"
        pattern = re.compile(
            rf'\\"slug\\":\\"([^\\"]+)\\",\\"tmdb_id\\":\\"{escaped_tmdb}\\".*?\\"type\\":\\"{escaped_type}\\"',
            re.S,
        )
        match = pattern.search(raw)
        if match:
            return match.group(1).strip()

        fallback_pattern = re.compile(
            rf'\\"slug\\":\\"([^\\"]+)\\",\\"tmdb_id\\":\\"{escaped_tmdb}\\"',
            re.S,
        )
        fallback_match = fallback_pattern.search(raw)
        if fallback_match:
            return fallback_match.group(1).strip()
        return ""

    @staticmethod
    def _extract_next_redirect_share_link(raw: str) -> str:
        patterns = [
            r'NEXT_REDIRECT;replace;(https?://(?:115|share\.115|115cdn)[^;]+);307',
            r'NEXT_REDIRECT;replace;(https?%3A%2F%2F(?:115|share\.115|115cdn)[^;]+);307',
        ]
        for pattern in patterns:
            match = re.search(pattern, raw)
            if not match:
                continue
            value = match.group(1).strip()
            value = value.replace("\\/", "/")
            value = value.replace("&amp;", "&")
            value = unquote(value)
            return value
        return ""

    @classmethod
    def _extract_share_link(cls, raw: str) -> str:
        patterns = [
            r'\\"url\\":\\"(https?://(?:115|share\.115|115cdn)[^\\"]+)\\"',
            r'"url":"(https?://(?:115|share\.115|115cdn)[^"]+)"',
        ]
        share_url = ""
        for pattern in patterns:
            match = re.search(pattern, raw)
            if match:
                share_url = match.group(1).replace("\\/", "/").strip()
                break

        if not share_url:
            share_url = cls._extract_next_redirect_share_link(raw)
            if not share_url:
                return ""

        code_match = re.search(r'\\"access_code\\":\\"([A-Za-z0-9]{4})\\"', raw)
        if not code_match:
            code_match = re.search(r'"access_code":"([A-Za-z0-9]{4})"', raw)
        if not code_match:
            return share_url

        access_code = code_match.group(1).strip()
        if not access_code:
            return share_url
        if "password=" in share_url or "pwd=" in share_url:
            return share_url

        joiner = "&" if "?" in share_url else "?"
        return f"{share_url}{joiner}{urlencode({'password': access_code})}"

    @staticmethod
    def _extract_resource_payload(raw: str) -> dict[str, Any]:
        marker = '\\"slug\\":\\"'
        index = raw.find(marker)
        if index < 0:
            return {}

        tail = raw[max(0, index - 2000):]
        for pattern in (
            r'\\"slug\\":\\"[^\\"]+\\".*?\\"data\\":(\{.*?\}),\\"error\\":(\{.*?\}),\\"poster\\":',
            r'\\"slug\\":\\"[^\\"]+\\".*?\\"data\\":(\{.*?\}),\\"error\\":null,\\"poster\\":',
        ):
            match = re.search(pattern, tail, re.S)
            if not match:
                continue
            data_raw = match.group(1)
            error_raw = match.group(2) if match.lastindex and match.lastindex >= 2 else "null"
            try:
                data_obj = json.loads(data_raw.replace('\\"', '"').replace("\\/", "/"))
            except Exception:
                data_obj = {}
            try:
                error_obj = json.loads(error_raw.replace('\\"', '"').replace("\\/", "/")) if error_raw else {}
            except Exception:
                error_obj = {}
            return {
                "data": data_obj if isinstance(data_obj, dict) else {},
                "error": error_obj if isinstance(error_obj, dict) else {},
            }
        return {}

    @classmethod
    def _extract_resource_meta(cls, raw: str) -> dict[str, Any]:
        payload = cls._extract_resource_payload(raw)
        data_obj = payload.get("data") if isinstance(payload, dict) else {}
        error_obj = payload.get("error") if isinstance(payload, dict) else {}

        data_obj = data_obj if isinstance(data_obj, dict) else {}
        error_obj = error_obj if isinstance(error_obj, dict) else {}

        lock_code = str(error_obj.get("code") or "").strip()
        lock_message = str(error_obj.get("message") or "").strip()
        unlock_points = int(data_obj.get("unlock_points") or 0)
        access_code = str(data_obj.get("access_code") or "").strip()
        resource_url = str(data_obj.get("url") or "").strip()
        full_url = str(data_obj.get("full_url") or "").strip()
        if not full_url and resource_url and access_code:
            joiner = "&" if "?" in resource_url else "?"
            full_url = f"{resource_url}{joiner}{urlencode({'password': access_code})}"
        locked = bool(lock_code == "400404" or ("解锁" in lock_message and not access_code))

        return {
            "locked": locked,
            "lock_code": lock_code,
            "lock_message": lock_message,
            "unlock_points": unlock_points,
            "resource_url": resource_url,
            "access_code": access_code,
            "full_url": full_url,
        }

    @classmethod
    def _sanitize_share_url(cls, raw_url: str) -> str:
        """清理解锁响应中的分享链接（含 HTML 实体与截断后缀）。"""
        value = html.unescape(str(raw_url or "").strip())
        value = value.replace("\\/", "/")
        value = re.sub(r"&#$", "", value)
        value = re.sub(r"&+$", "", value)
        return value.strip()

    @classmethod
    def _extract_share_link_from_action_data(
        cls, action_result: dict[str, Any]
    ) -> tuple[str, str, bool]:
        """从 unlockResource Server Action 响应中提取 115 分享链接。"""
        data_obj = action_result.get("data")
        if not isinstance(data_obj, dict):
            return "", "", False

        access_code = str(data_obj.get("access_code") or "").strip()
        share_link = cls._sanitize_share_url(str(data_obj.get("full_url") or ""))
        resource_url = cls._sanitize_share_url(str(data_obj.get("url") or ""))
        if not share_link and resource_url:
            share_link = resource_url
        if share_link and access_code and "password=" not in share_link and "pwd=" not in share_link:
            joiner = "&" if "?" in share_link else "?"
            share_link = f"{share_link}{joiner}{urlencode({'password': access_code})}"
        already_owned = bool(data_obj.get("already_owned"))
        return share_link, access_code, already_owned

    async def _resolve_media_slug(self, tmdb_id: int, media_type: str) -> str:
        try:
            tmdb_route_html = await self._fetch_text(f"/tmdb/{media_type}/{int(tmdb_id)}")
            redirect_match = re.search(
                rf"NEXT_REDIRECT;replace;/{media_type}/([^;]+);307",
                tmdb_route_html,
            )
            if redirect_match:
                return redirect_match.group(1).strip()
        except Exception:
            pass

        home_html = await self._fetch_text("/")
        slug = self._extract_media_slug_from_home(home_html, tmdb_id, media_type)
        if slug:
            return slug
        return str(int(tmdb_id))

    async def get_user_info(self) -> dict[str, Any]:
        candidate_paths = (
            "/user/settings",
            "/",
        )
        merged_user: dict[str, Any] = {}

        for path in candidate_paths:
            html = await self._fetch_text(path)
            user = self._extract_current_user(html)
            if not user:
                continue
            merged_user = self._merge_user_info(merged_user, user)
            if merged_user.get("points") is not None:
                return merged_user

        if merged_user:
            return merged_user
        raise ValueError("未获取到 HDHive 用户信息，请检查 Cookie")

    async def _fetch_resource_share_link(self, slug: str) -> str:
        slug = str(slug or "").strip()
        if not slug:
            return ""
        html = await self._fetch_text(f"/resource/115/{slug}")
        return self._extract_share_link(html)

    async def _fetch_resource_meta(self, slug: str) -> dict[str, Any]:
        slug = str(slug or "").strip()
        if not slug:
            return {}
        html = await self._fetch_text(f"/resource/115/{slug}")
        meta = self._extract_resource_meta(html)
        share_link = self._extract_share_link(html)
        if share_link and not meta.get("full_url"):
            meta["full_url"] = share_link
        return meta

    @staticmethod
    def _parse_next_action_response(text: str) -> dict[str, Any]:
        if not text:
            return {"success": False, "message": "空响应"}

        payload_line = ""
        for line in text.splitlines():
            if line.startswith("1:"):
                payload_line = line[2:].strip()
                break
        if not payload_line:
            try:
                plain_payload = json.loads(text)
            except Exception:
                plain_payload = None
            if isinstance(plain_payload, dict):
                if isinstance(plain_payload.get("response"), dict):
                    response_obj = plain_payload["response"]
                    return {
                        "success": bool(response_obj.get("success")),
                        "code": str(response_obj.get("code") or ""),
                        "message": str(response_obj.get("message") or ""),
                        "data": response_obj.get("data") if isinstance(response_obj.get("data"), dict) else {},
                    }
                return {
                    "success": bool(plain_payload.get("success")),
                    "code": str(plain_payload.get("code") or ""),
                    "message": str(plain_payload.get("message") or ""),
                    "data": plain_payload.get("data") if isinstance(plain_payload.get("data"), dict) else {},
                }
            return {"success": False, "message": "未获取到响应数据"}

        try:
            payload = json.loads(payload_line)
        except Exception as exc:
            return {"success": False, "message": f"解析响应失败: {exc}"}

        if not isinstance(payload, dict):
            return {"success": False, "message": "响应格式异常"}

        if isinstance(payload.get("response"), dict):
            response_obj = payload["response"]
            return {
                "success": bool(response_obj.get("success")),
                "code": str(response_obj.get("code") or ""),
                "message": str(response_obj.get("message") or ""),
                "data": response_obj.get("data") if isinstance(response_obj.get("data"), dict) else {},
            }
        if isinstance(payload.get("error"), dict):
            error_obj = payload["error"]
            return {
                "success": False,
                "code": str(error_obj.get("code") or ""),
                "message": str(error_obj.get("message") or error_obj.get("description") or "请求失败"),
                "data": error_obj.get("data") if isinstance(error_obj.get("data"), dict) else {},
            }
        if isinstance(payload.get("digest"), str):
            return {"success": False, "message": f"请求失败(digest={payload['digest']})"}
        return {"success": False, "message": "请求未返回有效结果"}

    async def _post_next_action(self, page_path: str, action_id: str, args: list[Any]) -> httpx.Response:
        normalized_path = page_path if page_path.startswith("http") else f"{self._base_url}{page_path}"
        referer = page_path if page_path.startswith("http") else f"{self._base_url}{page_path}"
        base_cookie = self._cookie

        client = self._create_client()
        try:
            await self._prefetch_action_token(client)
            cookie_header = self._build_cookie_header(client, base_cookie)
            post_headers = {
                "user-agent": self._user_agent,
                "accept": "text/x-component",
                "origin": self._base_url,
                "referer": referer,
                "next-action": action_id,
                "content-type": "text/plain;charset=UTF-8",
                "cookie": cookie_header,
            }
            body = json.dumps(args, ensure_ascii=False)
            response = await client.post(normalized_path, headers=post_headers, content=body)

            if response.status_code < 400:
                parsed = self._parse_next_action_response(response.text)
                if self._is_action_token_error(parsed):
                    await self._prefetch_action_token(client)
                    post_headers["cookie"] = self._build_cookie_header(client, base_cookie)
                    response = await client.post(normalized_path, headers=post_headers, content=body)
            return response
        finally:
            await client.aclose()

    async def _unlock_resource_via_next_action(self, slug: str, resource_html: str) -> dict[str, Any]:
        slug = str(slug or "").strip()
        if not slug:
            return {"success": False, "message": "资源 slug 为空"}

        page_path = f"/resource/115/{slug}"
        self._unlock_action_id_cached_at = 0.0
        self._unlock_action_id = ""
        action_id = await self._resolve_unlock_action_id(resource_html)
        if not action_id:
            return {"success": False, "message": "未找到 unlockResource Server Action"}
        response = await self._post_next_action(page_path, action_id, [slug])
        if response.status_code == 404 and "Server action not found" in response.text:
            self._unlock_action_id_cached_at = 0.0
            self._unlock_action_id = ""
            refreshed_action_id = await self._resolve_unlock_action_id(resource_html)
            if refreshed_action_id and refreshed_action_id != action_id:
                response = await self._post_next_action(page_path, refreshed_action_id, [slug])
        if response.status_code >= 400:
            return {
                "success": False,
                "message": response.text.strip() or f"解锁请求失败(HTTP {response.status_code})",
            }
        parsed = self._parse_next_action_response(response.text)
        if self._is_action_token_error(parsed):
            return {
                "success": False,
                "code": parsed.get("code"),
                "message": str(parsed.get("message") or "HDHive 解锁令牌失效，请重试"),
            }
        parsed["raw"] = response.text[:2000]
        return parsed

    async def _load_checkin_page(self) -> tuple[str, str]:
        candidate_paths = (
            "/user/signin",
            "/user/checkin",
        )
        for path in candidate_paths:
            try:
                html = await self._fetch_text(path)
            except Exception:
                continue
            if html:
                return path, html
        raise ValueError("未获取到 HDHive 签到页面，请检查 Cookie")

    async def check_in(self, gamble: bool = False) -> dict[str, Any]:
        page_path, page_html = await self._load_checkin_page()
        action_id = await self._resolve_checkin_action_id(page_html)
        response = await self._post_next_action(page_path, action_id, [bool(gamble)])
        if response.status_code == 404 and "Server action not found" in response.text:
            self._checkin_action_id_cached_at = 0.0
            refreshed_action_id = await self._resolve_checkin_action_id(page_html)
            if refreshed_action_id and refreshed_action_id != action_id:
                response = await self._post_next_action(page_path, refreshed_action_id, [bool(gamble)])
        response.raise_for_status()

        parsed = self._parse_next_action_response(response.text)
        user_info: dict[str, Any] = {}
        try:
            user_info = await self.get_user_info()
        except Exception:
            user_info = {}

        data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
        checked_in = self._extract_optional_bool(data.get("checked_in"))
        status, message = self._classify_checkin_status(
            str(parsed.get("message") or data.get("message") or "").strip(),
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
            "method": "web",
            "code": str(parsed.get("code") or "").strip(),
            "data": data,
            "user": user_info,
            "points": self._extract_first_int(user_info.get("points")) if isinstance(user_info, dict) else None,
            "points_earned": points_earned,
            "checked_in": checked_in,
            "page_path": page_path,
        }

    async def check_in_by_cookie(self, gamble: bool = False) -> dict[str, Any]:
        """使用 /api/checkin 接口签到（Cookie 方式）。"""
        headers = {
            "user-agent": self._user_agent,
            "accept": "application/json",
            "content-type": "application/json",
        }
        if self._cookie:
            headers["cookie"] = self._cookie

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
            message = str(payload.get("message") or "").strip() or f"HTTP {response.status_code}"
            raise ValueError(message)

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
        if cached and cached[1].get("success") and (now - cached[0] < self._unlock_cache_ttl_seconds):
            return cached[1]

        lock = self._unlock_locks.setdefault(normalized_slug, asyncio.Lock())
        async with lock:
            cached = self._unlock_cache.get(normalized_slug)
            now = monotonic()
            if cached and cached[1].get("success") and (now - cached[0] < self._unlock_cache_ttl_seconds):
                return cached[1]

            resource_html = await self._fetch_text(f"/resource/115/{normalized_slug}")
            action_result = await self._unlock_resource_via_next_action(normalized_slug, resource_html)
            action_share_link, action_access_code, already_owned = (
                self._extract_share_link_from_action_data(action_result)
            )
            meta = self._extract_resource_meta(resource_html)
            if bool(meta.get("locked")):
                meta = await self._fetch_resource_meta(normalized_slug)
            access_code = action_access_code or str(meta.get("access_code") or "").strip()
            share_link = action_share_link or self._sanitize_share_url(
                str(meta.get("full_url") or "")
            )
            resource_url = self._sanitize_share_url(str(meta.get("resource_url") or ""))
            if not share_link and resource_url and access_code:
                joiner = "&" if "?" in resource_url else "?"
                share_link = f"{resource_url}{joiner}{urlencode({'password': access_code})}"
            if not share_link:
                try:
                    fetched_link = await self._fetch_resource_share_link(normalized_slug)
                    if fetched_link:
                        share_link = self._sanitize_share_url(fetched_link)
                except Exception:
                    pass
            action_message = str(action_result.get("message") or "").strip()
            success = bool(share_link or access_code) and (
                bool(action_result.get("success"))
                or already_owned
                or "已解锁" in action_message
            )

            result = {
                "success": success,
                "method": "next_action",
                "message": (
                    action_message
                    or ("资源解锁成功" if success else "资源解锁失败")
                ),
                "share_link": share_link,
                "access_code": access_code,
                "full_url": share_link,
                "already_owned": already_owned,
                "locked": bool(meta.get("locked")) and not success,
                "lock_code": str(meta.get("lock_code") or ""),
                "lock_message": str(meta.get("lock_message") or ""),
                "unlock_points": int(meta.get("unlock_points") or 0),
                "resource_url": resource_url,
            }
            if success:
                self._unlock_cache[normalized_slug] = (monotonic(), result)
            return result

    async def get_pan115_by_keyword(self, keyword: str, media_type: str = "movie") -> list[dict[str, Any]]:
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []

        target_media_type = self._normalize_media_type(media_type)
        search_path = f"/{target_media_type}?keyword={quote_plus(normalized_keyword)}"
        try:
            search_html = await self._fetch_text(search_path)
            candidates = self._search_media_candidates(search_html, normalized_keyword, target_media_type)
        except Exception:
            candidates = []

        merged: list[dict[str, Any]] = []
        seen_key: set[str] = set()
        for candidate in candidates:
            slug = str(candidate.get("slug") or "").strip()
            if not slug:
                continue
            try:
                detail_html = await self._fetch_text(f"/{target_media_type}/{slug}")
                rows = self._extract_json_like_array(detail_html, field_name="115")
            except Exception:
                continue
            if not rows:
                continue
            media_title = str(candidate.get("title") or "").strip()
            for idx, row in enumerate(rows[:30]):
                if not isinstance(row, dict):
                    continue
                item = self._map_resource_row(row, idx)
                dedupe_key = str(item.get("slug") or "").strip().lower()
                if not dedupe_key or dedupe_key in seen_key:
                    continue
                seen_key.add(dedupe_key)
                if media_title and not str(item.get("title") or "").strip():
                    item["title"] = media_title
                item["matched_media_title"] = media_title
                merged.append(item)
                if len(merged) >= 30:
                    return merged

        if merged:
            return merged

        tmdb_candidates = await self._search_tmdb_candidates(normalized_keyword, target_media_type)
        for tmdb_id in tmdb_candidates:
            try:
                rows = await self._list_resources_by_tmdb(tmdb_id, target_media_type)
            except Exception:
                continue
            for row in rows:
                dedupe_key = str(row.get("slug") or "").strip().lower()
                if not dedupe_key or dedupe_key in seen_key:
                    continue
                seen_key.add(dedupe_key)
                merged.append(row)
                if len(merged) >= 30:
                    return merged
        return merged

    async def get_movie_pan115(self, tmdb_id: int) -> list[dict[str, Any]]:
        return await self._list_resources_by_tmdb(tmdb_id, "movie")

    async def get_tv_pan115(self, tmdb_id: int) -> list[dict[str, Any]]:
        return await self._list_resources_by_tmdb(tmdb_id, "tv")

    async def get_movie_pan115_result(self, tmdb_id: int) -> dict[str, Any]:
        return await self._collect_tmdb_resources(tmdb_id, "movie", target_pan_type="115")

    async def get_tv_pan115_result(self, tmdb_id: int) -> dict[str, Any]:
        return await self._collect_tmdb_resources(tmdb_id, "tv", target_pan_type="115")

    async def get_movie_quark_result(self, tmdb_id: int) -> dict[str, Any]:
        return await self._collect_tmdb_resources(tmdb_id, "movie", target_pan_type="quark")

    async def get_tv_quark_result(self, tmdb_id: int) -> dict[str, Any]:
        return await self._collect_tmdb_resources(tmdb_id, "tv", target_pan_type="quark")

    @staticmethod
    def _normalize_keyword(text: str) -> str:
        raw = unicodedata.normalize("NFKD", str(text or ""))
        raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
        return re.sub(r"[\s\-_·:：,.，。!！?？/\\\\'\"`()\\[\\]]+", "", raw.strip().lower())

    def _search_media_candidates(self, raw: str, keyword: str, media_type: str) -> list[dict[str, Any]]:
        rows = self._extract_json_like_array(raw, field_name="data")
        if not rows:
            return []

        keyword_normalized = self._normalize_keyword(keyword)
        candidates: list[tuple[int, bool, dict[str, Any]]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            slug = str(row.get("slug") or "").strip()
            if not slug:
                continue
            row_media_type = str(row.get("type") or media_type).strip().lower()
            if row_media_type and row_media_type not in {"movie", "tv"}:
                row_media_type = media_type
            title = str(row.get("title") or "").strip()
            original_title = str(row.get("original_title") or "").strip()
            merged_title = " ".join(part for part in [title, original_title] if part)
            merged_normalized = self._normalize_keyword(merged_title)

            score = 0
            if row_media_type == media_type:
                score += 20
            if keyword_normalized and merged_normalized:
                if keyword_normalized in merged_normalized:
                    score += 120
                elif merged_normalized in keyword_normalized:
                    score += 80
                elif any(part and part in merged_normalized for part in keyword_normalized.split()):
                    score += 30
            if title:
                score += 5

            has_keyword_hit = bool(keyword_normalized and merged_normalized and keyword_normalized in merged_normalized)
            candidates.append((score, has_keyword_hit, row))

        exact_hit_candidates = [item for item in candidates if item[1]]
        selected_pool = exact_hit_candidates
        if not selected_pool:
            return []
        selected_pool.sort(key=lambda item: item[0], reverse=True)
        selected: list[dict[str, Any]] = []
        seen_slugs: set[str] = set()
        for _, _, row in selected_pool:
            slug = str(row.get("slug") or "").strip()
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            selected.append(row)
            if len(selected) >= 3:
                break
        return selected
