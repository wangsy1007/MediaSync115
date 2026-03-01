import asyncio
import json
import re
import unicodedata
from typing import Any
from urllib.parse import quote_plus, unquote, urlencode
from time import monotonic

import httpx

from app.core.config import settings


class HDHiveService:
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
        self._unlock_action_id = "40dbca7ab6f555dbd98c40945c8b970185c58e16d3"
        self._unlock_locks: dict[str, asyncio.Lock] = {}
        self._unlock_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._unlock_cache_ttl_seconds = 120.0

    def set_base_url(self, base_url: str | None) -> None:
        value = str(base_url or "").strip()
        if not value:
            return
        self._base_url = value.rstrip("/")

    def set_cookie(self, cookie: str | None) -> None:
        self._cookie = str(cookie or "").strip()

    async def _fetch_text(self, path: str) -> str:
        headers = {
            "user-agent": self._user_agent,
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if self._cookie:
            headers["cookie"] = self._cookie

        url = path if path.startswith("http") else f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.text

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

    @staticmethod
    def _extract_current_user(raw: str) -> dict[str, Any]:
        segment = ""
        marker = '\\"currentUser\\":{'
        index = raw.find(marker)
        if index >= 0:
            segment = raw[index:index + 5000]
        if not segment:
            return {}

        username = ""
        nickname = ""
        is_vip = False

        username_match = re.search(r'\\"username\\":\\"([^\\"]*)\\"', segment)
        if username_match:
            username = username_match.group(1).strip()

        nickname_match = re.search(r'\\"nickname\\":\\"([^\\"]*)\\"', segment)
        if nickname_match:
            nickname = nickname_match.group(1).strip()

        vip_match = re.search(r'\\"is_vip\\":(true|false|[0-9]+)', segment)
        if vip_match:
            raw_vip = vip_match.group(1).strip().lower()
            is_vip = raw_vip == "true" or (raw_vip.isdigit() and int(raw_vip) > 0)

        return {
            "username": username or nickname or "",
            "nickname": nickname or "",
            "is_vip": bool(is_vip),
        }

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
        home_html = await self._fetch_text("/")
        user = self._extract_current_user(home_html)
        if not user:
            raise ValueError("未获取到 HDHive 用户信息，请检查 Cookie")
        return user

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
                "message": str(error_obj.get("message") or error_obj.get("description") or "解锁失败"),
                "data": error_obj.get("data") if isinstance(error_obj.get("data"), dict) else {},
            }
        if isinstance(payload.get("digest"), str):
            return {"success": False, "message": f"解锁请求失败(digest={payload['digest']})"}
        return {"success": False, "message": "解锁请求未返回有效结果"}

    async def _unlock_resource_via_next_action(self, slug: str) -> dict[str, Any]:
        slug = str(slug or "").strip()
        if not slug:
            return {"success": False, "message": "资源 slug 为空"}

        resource_url = f"{self._base_url}/resource/115/{slug}"
        headers = {
            "user-agent": self._user_agent,
            "accept": "text/x-component",
            "origin": self._base_url,
            "referer": resource_url,
            "next-action": self._unlock_action_id,
            "content-type": "text/plain;charset=UTF-8",
        }
        if self._cookie:
            headers["cookie"] = self._cookie

        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.post(resource_url, headers=headers, content=json.dumps([slug]))
            response.raise_for_status()
            parsed = self._parse_next_action_response(response.text)
            parsed["raw"] = response.text[:2000]
            return parsed

    async def unlock_resource(self, slug: str) -> dict[str, Any]:
        slug = str(slug or "").strip()
        if not slug:
            return {"success": False, "message": "资源 slug 为空", "locked": True}

        cached = self._unlock_cache.get(slug)
        now = monotonic()
        if cached and (now - cached[0] < self._unlock_cache_ttl_seconds):
            return cached[1]

        lock = self._unlock_locks.setdefault(slug, asyncio.Lock())
        async with lock:
            cached = self._unlock_cache.get(slug)
            now = monotonic()
            if cached and (now - cached[0] < self._unlock_cache_ttl_seconds):
                return cached[1]

            action_result = await self._unlock_resource_via_next_action(slug)
            meta = await self._fetch_resource_meta(slug)
            access_code = str(meta.get("access_code") or "").strip()
            share_link = str(meta.get("full_url") or "").strip()
            success = bool(action_result.get("success")) and bool(share_link or access_code)

            result = {
                "success": success,
                "method": "next_action",
                "message": (
                    str(action_result.get("message") or "").strip()
                    or ("资源解锁成功" if success else "资源解锁失败")
                ),
                "share_link": share_link,
                "access_code": access_code,
                "locked": bool(meta.get("locked")),
                "lock_code": str(meta.get("lock_code") or ""),
                "lock_message": str(meta.get("lock_message") or ""),
                "unlock_points": int(meta.get("unlock_points") or 0),
                "resource_url": str(meta.get("resource_url") or ""),
            }
            self._unlock_cache[slug] = (monotonic(), result)
            return result

    async def _build_pan115_rows(self, tmdb_id: int, media_type: str) -> list[dict[str, Any]]:
        slug = await self._resolve_media_slug(tmdb_id, media_type)
        detail_path = f"/{media_type}/{slug}" if not slug.isdigit() else f"/{media_type}/{int(tmdb_id)}"
        detail_html = await self._fetch_text(detail_path)
        rows = self._extract_json_like_array(detail_html, field_name="115")

        if not rows and not slug.isdigit():
            fallback_html = await self._fetch_text(f"/{media_type}/{int(tmdb_id)}")
            rows = self._extract_json_like_array(fallback_html, field_name="115")

        if not rows:
            return []

        tasks = [self._resolve_pan115_row(row, idx) for idx, row in enumerate(rows[:30])]
        return await asyncio.gather(*tasks)

    async def _resolve_pan115_row(self, row: dict[str, Any], index: int) -> dict[str, Any]:
        resource_slug = str(row.get("slug") or "").strip()
        unlock_points = int(row.get("unlock_points") or 0)
        share_link = ""
        lock_meta: dict[str, Any] = {}
        if resource_slug:
            try:
                lock_meta = await self._fetch_resource_meta(resource_slug)
                share_link = str(lock_meta.get("full_url") or "").strip()
            except Exception:
                share_link = ""
                lock_meta = {}

        title = str(row.get("title") or "").strip() or f"HDHive 资源 #{index + 1}"
        resource_name = (
            str(row.get("remark") or "").strip()
            or str(row.get("name") or "").strip()
            or title
        )
        size = str(row.get("share_size") or "").strip()
        quality = row.get("source") if isinstance(row.get("source"), list) else []
        resolution = row.get("video_resolution") if isinstance(row.get("video_resolution"), list) else []
        savable = bool(share_link)
        if unlock_points > 0 and not savable:
            savable = False

        return {
            "id": row.get("id") or resource_slug or f"hdhive-{index}",
            "slug": resource_slug,
            "title": title,
            "resource_name": resource_name,
            "size": size,
            "quality": quality,
            "resolution": resolution,
            "share_link": share_link,
            "unlock_points": unlock_points,
            "hdhive_locked": bool(lock_meta.get("locked")),
            "hdhive_lock_code": str(lock_meta.get("lock_code") or ""),
            "hdhive_lock_message": str(lock_meta.get("lock_message") or ""),
            "hdhive_resource_url": str(lock_meta.get("resource_url") or ""),
            "source_service": "hdhive",
            "pan115_savable": savable,
        }

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

    async def get_pan115_by_keyword(self, keyword: str, media_type: str = "movie") -> list[dict[str, Any]]:
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []

        target_media_type = "tv" if str(media_type or "").strip().lower() == "tv" else "movie"
        search_path = f"/{target_media_type}?keyword={quote_plus(normalized_keyword)}"
        search_html = await self._fetch_text(search_path)
        candidates = self._search_media_candidates(search_html, normalized_keyword, target_media_type)
        if not candidates:
            return []

        merged: list[dict[str, Any]] = []
        seen_key: set[str] = set()
        for candidate in candidates:
            slug = str(candidate.get("slug") or "").strip()
            if not slug:
                continue
            detail_html = await self._fetch_text(f"/{target_media_type}/{slug}")
            rows = self._extract_json_like_array(detail_html, field_name="115")
            if not rows:
                continue
            tasks = [self._resolve_pan115_row(row, idx) for idx, row in enumerate(rows[:30])]
            items = await asyncio.gather(*tasks)
            media_title = str(candidate.get("title") or "").strip()
            for item in items:
                share_link = str(item.get("share_link") or "").strip()
                dedupe_key = f"{str(item.get('slug') or '').strip()}|{share_link}"
                if dedupe_key in seen_key:
                    continue
                seen_key.add(dedupe_key)
                if media_title and not str(item.get("title") or "").strip():
                    item["title"] = media_title
                item["matched_media_title"] = media_title
                merged.append(item)
        return merged

    async def get_movie_pan115(self, tmdb_id: int) -> list[dict[str, Any]]:
        return await self._build_pan115_rows(tmdb_id, "movie")

    async def get_tv_pan115(self, tmdb_id: int) -> list[dict[str, Any]]:
        return await self._build_pan115_rows(tmdb_id, "tv")


hdhive_service = HDHiveService()
