import asyncio
import base64
import html
import re
import time
from urllib.parse import quote

import httpx


class SeedHubService:
    def __init__(self, base_url: str = "https://www.seedhub.cc") -> None:
        self.base_url = base_url.rstrip("/")
        self._search_cache_ttl = 15 * 60
        self._magnet_cache_ttl = 60 * 60
        self._request_timeout = 20.0
        self._resolve_concurrency = 8
        self._request_retries = 2
        self._search_cache: dict[str, tuple[float, list[dict]]] = {}
        self._magnet_cache: dict[str, tuple[float, str]] = {}
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    async def search_magnets_by_keyword(
        self,
        keyword: str,
        limit: int = 40,
        expected_context: dict | None = None,
    ) -> list[dict]:
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []
        normalized_limit = max(1, min(int(limit or 40), 80))

        cached = self._read_search_cache(normalized_keyword)
        if cached:
            return cached[:normalized_limit]

        async with self._create_client() as client:
            movie_candidates = await self._search_movie_candidates(
                normalized_keyword,
                client=client,
                limit=5,
                expected_context=expected_context,
            )
            if not movie_candidates:
                return []

            movie_id = str(movie_candidates[0].get("movie_id") or "").strip()
            if not movie_id:
                return []
            entries = await self._fetch_seed_entries(movie_id, client=client)
            if not entries:
                return []

            collected = await self._resolve_entry_batch(
                [(movie_id, entry) for entry in entries],
                client,
                max_results=normalized_limit,
                concurrency=self._resolve_concurrency,
            )

            self._write_search_cache(normalized_keyword, collected)
            return collected[:normalized_limit]

    async def _resolve_entry_batch(
        self,
        queued_entries: list[tuple[str, dict]],
        client: httpx.AsyncClient,
        max_results: int,
        existing: list[dict] | None = None,
        concurrency: int = 3,
    ) -> list[dict]:
        collected = list(existing or [])
        seen_magnets = {
            str(item.get("magnet") or "").strip().lower()
            for item in collected
            if str(item.get("magnet") or "").strip()
        }
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def resolve(movie_id: str, entry: dict) -> dict | None:
            seed_id = str(entry.get("seed_id") or "").strip()
            if not seed_id:
                return None
            title = str(entry.get("title") or "").strip()
            size = str(entry.get("size") or "").strip()
            updated_at = str(entry.get("updated_at") or "").strip()

            async with semaphore:
                magnet = await self._resolve_magnet(seed_id, client=client)
            if not magnet:
                return None
            magnet_key = magnet.lower()
            if magnet_key in seen_magnets:
                return None
            seen_magnets.add(magnet_key)
            return {
                "id": f"seedhub-{seed_id}",
                "name": title or f"SeedHub 资源 #{seed_id}",
                "title": title or f"SeedHub 资源 #{seed_id}",
                "size": size,
                "magnet": magnet,
                "source_service": "seedhub",
                "seed_id": seed_id,
                "updated_at": updated_at,
                "movie_id": movie_id,
            }

        resolved_items = await asyncio.gather(
            *(resolve(movie_id, entry) for movie_id, entry in queued_entries),
            return_exceptions=True,
        )
        for item in resolved_items:
            if isinstance(item, dict):
                collected.append(item)
            if len(collected) >= max_results:
                break
        return collected[:max_results]

    async def _search_movie_ids(
        self,
        keyword: str,
        client: httpx.AsyncClient | None = None,
        limit: int = 1,
        expected_context: dict | None = None,
    ) -> list[str]:
        candidates = await self._search_movie_candidates(
            keyword,
            client=client,
            limit=limit,
            expected_context=expected_context,
        )
        return [
            str(item.get("movie_id") or "").strip()
            for item in candidates
            if str(item.get("movie_id") or "").strip()
        ]

    async def _search_movie_candidates(
        self,
        keyword: str,
        client: httpx.AsyncClient | None = None,
        limit: int = 5,
        expected_context: dict | None = None,
    ) -> list[dict]:
        url = f"{self.base_url}/s/{quote(keyword)}/"
        text = await self._fetch_text(url, client=client)
        if not text:
            return []

        candidates = self._parse_search_candidates(text)
        if not candidates:
            return []
        return self._rank_search_candidates(
            candidates[: max(1, limit)], expected_context=expected_context
        )[: max(1, limit)]

    def _parse_search_candidates(self, text: str) -> list[dict]:
        candidates: list[dict] = []
        seen_ids: set[str] = set()
        pattern = re.compile(
            r'<div class="cover">.*?title="(?P<anchor_title>[^"]*)"[^>]*href="/movies/(?P<movie_id>\d+)/".*?'
            r'<li><h2><a[^>]+href="/movies/\d+/"[^>]*>.*?</a>\s*(?P<title>.*?)</h2></li>\s*'
            r"<li>(?P<meta>.*?)</li>",
            re.IGNORECASE | re.DOTALL,
        )
        for matched in pattern.finditer(text):
            movie_id = str(matched.group("movie_id") or "").strip()
            if not movie_id or movie_id in seen_ids:
                continue
            seen_ids.add(movie_id)
            title = self._clean_html_text(matched.group("title") or "")
            anchor_title = self._clean_html_text(matched.group("anchor_title") or "")
            meta = self._clean_html_text(matched.group("meta") or "")
            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", meta)
            year = year_match.group(1) if year_match else ""
            media_type = ""
            meta_parts = [part.strip() for part in meta.split("/") if str(part).strip()]
            if len(meta_parts) >= 2:
                media_type = meta_parts[1]
            candidates.append(
                {
                    "movie_id": movie_id,
                    "title": title,
                    "anchor_title": anchor_title,
                    "year": year,
                    "media_type": media_type,
                }
            )
        return candidates

    def _rank_search_candidates(
        self, candidates: list[dict], expected_context: dict | None = None
    ) -> list[dict]:
        if not candidates:
            return []
        context = expected_context or {}
        expected_title = self._normalize_title_fingerprint(
            context.get("expected_title")
        )
        expected_original_title = self._normalize_title_fingerprint(
            context.get("expected_original_title")
        )
        expected_year = str(context.get("expected_year") or "").strip()
        expected_media_type = str(context.get("expected_media_type") or "").strip()

        ranked: list[tuple[tuple[int, int], dict]] = []
        for index, item in enumerate(candidates):
            title_fp = self._normalize_title_fingerprint(item.get("title"))
            anchor_fp = self._normalize_title_fingerprint(item.get("anchor_title"))
            item_year = str(item.get("year") or "").strip()
            item_media_type = str(item.get("media_type") or "").strip()
            score = 0
            if expected_title and (
                title_fp == expected_title or anchor_fp == expected_title
            ):
                score += 100
            if expected_original_title and (
                title_fp == expected_original_title
                or anchor_fp == expected_original_title
            ):
                score += 90
            if expected_year and item_year == expected_year:
                score += 40
            if expected_media_type and item_media_type == expected_media_type:
                score += 10
            ranked.append(((score, -index), item))

        ranked.sort(key=lambda entry: entry[0], reverse=True)
        return [item for _, item in ranked]

    def _normalize_title_fingerprint(self, value: object) -> str:
        text = html.unescape(str(value or "").strip()).casefold()
        if not text:
            return ""
        return re.sub(
            r"[\s\-_:：·•.,，。!！?？'\"“”‘’()（）\[\]【】/\\]+",
            "",
            text,
        )

    def _clean_html_text(self, value: object) -> str:
        text = re.sub(r"<[^>]+>", "", str(value or ""))
        return html.unescape(text).strip()

    async def _fetch_seed_entries(
        self, movie_id: str, client: httpx.AsyncClient | None = None
    ) -> list[dict]:
        url = f"{self.base_url}/movies/{movie_id}/"
        text = await self._fetch_text(url, client=client)
        if not text:
            return []

        entries: list[dict] = []
        seen_ids: set[str] = set()
        pattern = re.compile(
            r"<li>\s*(?P<a><a[^>]+href=\"/link_start/\?seed_id=(?P<seed>\d+)[^\"]*\"[^>]*>.*?</a>)"
            r"\s*/\s*<code class=\"size\">(?P<size>[^<]*)</code>"
            r".*?<span class=\"create-time\"[^>]*>(?P<updated>[^<]*)</span>",
            re.IGNORECASE | re.DOTALL,
        )
        for matched in pattern.finditer(text):
            seed_id = str(matched.group("seed") or "").strip()
            anchor = str(matched.group("a") or "")
            title_match = re.search(r'title="([^"]*)"', anchor, flags=re.IGNORECASE)
            title = title_match.group(1) if title_match else ""
            size = str(matched.group("size") or "").strip()
            updated_at = str(matched.group("updated") or "").strip()
            if seed_id in seen_ids:
                continue
            seen_ids.add(seed_id)
            entries.append(
                {
                    "seed_id": seed_id,
                    "title": html.unescape(str(title or "").strip()),
                    "size": str(size or "").strip(),
                    "updated_at": str(updated_at or "").strip(),
                }
            )
        return entries

    async def _resolve_magnet(
        self, seed_id: str, client: httpx.AsyncClient | None = None
    ) -> str:
        cached = self._read_magnet_cache(seed_id)
        if cached:
            return cached
        url = f"{self.base_url}/link_start/?seed_id={seed_id}&movie_title=seedhub"
        text = await self._fetch_text(url, client=client)
        if not text:
            return ""

        matched = re.search(r'const\s+data\s*=\s*"([A-Za-z0-9+/=]+)"', text)
        if not matched:
            return ""

        encoded = matched.group(1)
        try:
            decoded = base64.b64decode(encoded).decode("utf-8", errors="ignore").strip()
        except Exception:
            return ""

        if not decoded.startswith("magnet:?"):
            return ""
        self._write_magnet_cache(seed_id, decoded)
        return decoded

    async def _fetch_text(
        self, url: str, client: httpx.AsyncClient | None = None
    ) -> str:
        if client is None:
            async with self._create_client() as async_client:
                return await self._fetch_text_with_client(url, async_client)
        return await self._fetch_text_with_client(url, client)

    def _create_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._request_timeout,
            follow_redirects=True,
            headers=self._headers,
            limits=httpx.Limits(max_connections=12, max_keepalive_connections=6),
        )

    async def _fetch_text_with_client(self, url: str, client: httpx.AsyncClient) -> str:
        for attempt in range(self._request_retries):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.text or ""
            except Exception as exc:
                if attempt + 1 >= self._request_retries:
                    break
                await asyncio.sleep(0.2 * (attempt + 1))
        return ""

    def _read_search_cache(self, keyword: str) -> list[dict] | None:
        cached = self._search_cache.get(keyword)
        if not cached:
            return None
        ts, items = cached
        if time.time() - ts > self._search_cache_ttl:
            self._search_cache.pop(keyword, None)
            return None
        return list(items)

    def _write_search_cache(self, keyword: str, items: list[dict]) -> None:
        self._search_cache[keyword] = (time.time(), list(items))

    def _read_magnet_cache(self, seed_id: str) -> str:
        cached = self._magnet_cache.get(seed_id)
        if not cached:
            return ""
        ts, magnet = cached
        if time.time() - ts > self._magnet_cache_ttl:
            self._magnet_cache.pop(seed_id, None)
            return ""
        return magnet

    def _write_magnet_cache(self, seed_id: str, magnet: str) -> None:
        self._magnet_cache[seed_id] = (time.time(), magnet)


seedhub_service = SeedHubService()
