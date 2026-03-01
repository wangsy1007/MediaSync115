import asyncio
import json
import re
from typing import Any
from urllib.parse import urlencode

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
    def _extract_json_like_array(raw: str, escaped_key: str) -> list[dict[str, Any]]:
        # Next.js RSC payload is escaped in HTML scripts; this extracts and decodes one array field.
        match = re.search(
            rf'{escaped_key}\\":\\[(.*?)\\],\\"[A-Za-z0-9_]+\\"',
            raw,
            flags=re.S,
        )
        if not match:
            return []

        payload = f"[{match.group(1)}]"
        payload = payload.replace('\\"', '"')
        payload = payload.replace("\\/", "/")
        payload = payload.replace("\\u0026", "&")
        payload = payload.replace("\\n", "\n")
        payload = payload.replace("\\t", "\t")

        try:
            parsed = json.loads(payload)
        except Exception:
            try:
                parsed = json.loads(bytes(payload, "utf-8").decode("unicode_escape"))
            except Exception:
                return []

        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
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
        return ""

    @staticmethod
    def _extract_share_link(raw: str) -> str:
        match = re.search(r'\\"url\\":\\"(https?://(?:115|share\.115|115cdn)[^\\"]+)\\"', raw)
        if not match:
            return ""
        share_url = match.group(1).replace("\\/", "/").strip()

        code_match = re.search(r'\\"access_code\\":\\"([A-Za-z0-9]{4})\\"', raw)
        if not code_match:
            return share_url

        access_code = code_match.group(1).strip()
        if not access_code:
            return share_url
        if "password=" in share_url or "pwd=" in share_url:
            return share_url

        joiner = "&" if "?" in share_url else "?"
        return f"{share_url}{joiner}{urlencode({'password': access_code})}"

    async def _resolve_media_slug(self, tmdb_id: int, media_type: str) -> str:
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

    async def _build_pan115_rows(self, tmdb_id: int, media_type: str) -> list[dict[str, Any]]:
        slug = await self._resolve_media_slug(tmdb_id, media_type)
        detail_path = f"/{media_type}/{slug}" if not slug.isdigit() else f"/{media_type}/{int(tmdb_id)}"
        detail_html = await self._fetch_text(detail_path)
        rows = self._extract_json_like_array(detail_html, escaped_key=r"\\\"115")

        if not rows and not slug.isdigit():
            fallback_html = await self._fetch_text(f"/{media_type}/{int(tmdb_id)}")
            rows = self._extract_json_like_array(fallback_html, escaped_key=r"\\\"115")

        if not rows:
            return []

        async def resolve_row(row: dict[str, Any], index: int) -> dict[str, Any]:
            resource_slug = str(row.get("slug") or "").strip()
            unlock_points = int(row.get("unlock_points") or 0)
            share_link = ""
            if resource_slug:
                try:
                    share_link = await self._fetch_resource_share_link(resource_slug)
                except Exception:
                    share_link = ""

            title = str(row.get("title") or "").strip() or f"HDHive 资源 #{index + 1}"
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
                "size": size,
                "quality": quality,
                "resolution": resolution,
                "share_link": share_link,
                "unlock_points": unlock_points,
                "source_service": "hdhive",
                "pan115_savable": savable,
            }

        tasks = [resolve_row(row, idx) for idx, row in enumerate(rows[:30])]
        return await asyncio.gather(*tasks)

    async def get_movie_pan115(self, tmdb_id: int) -> list[dict[str, Any]]:
        return await self._build_pan115_rows(tmdb_id, "movie")

    async def get_tv_pan115(self, tmdb_id: int) -> list[dict[str, Any]]:
        return await self._build_pan115_rows(tmdb_id, "tv")


hdhive_service = HDHiveService()
