"""对比 HDHive 解锁流程优化前后的 HTTP 请求次数与耗时。

用法（容器内或本地，需有效 HDHive Cookie）:
  python backend/scripts/bench_hdhive_unlock.py --slug <资源slug>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.hdhive_web_client import HDHiveWebClient
from app.services.runtime_settings_service import runtime_settings_service


class _CountingClient(HDHiveWebClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.request_count = 0

    async def _fetch_text_using_client(self, client, path, accept=None):  # type: ignore[override]
        self.request_count += 1
        return await super()._fetch_text_using_client(client, path, accept=accept)

    async def _prefetch_action_token(self, client) -> None:  # type: ignore[override]
        self.request_count += 1
        return await super()._prefetch_action_token(client)

    async def _post_next_action_with_client(self, client, page_path, action_id, args, *, prefetch_token=True):  # type: ignore[override]
        self.request_count += 1
        return await super()._post_next_action_with_client(
            client,
            page_path,
            action_id,
            args,
            prefetch_token=prefetch_token,
        )


async def _simulate_legacy_unlock(client: _CountingClient, slug: str) -> dict[str, Any]:
    """模拟优化前：每次清空 action 缓存 + 多次独立 HTTP 客户端 + 重复拉取资源页。"""
    client.request_count = 0
    client._invalidate_unlock_action_id_cache()
    started = time.perf_counter()

    page_path = f"/resource/115/{slug}"
    http = client._create_client()
    try:
        resource_html = await client._fetch_text_with_retry_using_client(http, page_path)
        client._invalidate_unlock_action_id_cache()
        action_id = await client._resolve_unlock_action_id(resource_html, http)
        if not action_id:
            return {"success": False, "message": "no action id", "requests": client.request_count}

        response = await client._post_next_action_with_client(
            http,
            page_path,
            action_id,
            [slug],
        )
        parsed = client._parse_next_action_response(response.text)
        meta = client._extract_resource_meta(resource_html)
        if bool(meta.get("locked")):
            refreshed = await client._fetch_text_with_retry_using_client(http, page_path, max_retries=1)
            meta = client._extract_resource_meta(refreshed)
        share_link, _ = client._resolve_share_link_from_meta(meta, html=resource_html)
        if not share_link:
            extra_html = await client._fetch_text_with_retry_using_client(http, page_path, max_retries=1)
            share_link = client._extract_share_link(extra_html)
    finally:
        await http.aclose()

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "success": bool(share_link) or bool(parsed.get("success")),
        "requests": client.request_count,
        "elapsed_ms": elapsed_ms,
        "share_link": share_link,
    }


async def _run_optimized_unlock(client: _CountingClient, slug: str) -> dict[str, Any]:
    client.request_count = 0
    client._invalidate_unlock_action_id_cache()
    started = time.perf_counter()
    result = await client.unlock_resource(slug)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "success": bool(result.get("success")),
        "requests": client.request_count,
        "elapsed_ms": elapsed_ms,
        "method": result.get("method"),
        "timing_ms": result.get("timing_ms") or {},
        "share_link": result.get("share_link"),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="HDHive 解锁性能对比")
    parser.add_argument("--slug", required=True, help="HDHive 资源 slug")
    parser.add_argument("--rounds", type=int, default=2, help="每种模式重复次数（第二次可观察 action 缓存）")
    args = parser.parse_args()

    runtime_settings_service.apply_runtime_overrides()
    slug = str(args.slug).strip()
    client = _CountingClient()

    print(f"slug={slug}\n")

    legacy_rows: list[dict[str, Any]] = []
    optimized_rows: list[dict[str, Any]] = []

    for index in range(max(int(args.rounds), 1)):
        print(f"=== Round {index + 1} ===")
        legacy = await _simulate_legacy_unlock(client, slug)
        legacy_rows.append(legacy)
        print("legacy   ", json.dumps(legacy, ensure_ascii=False))

        optimized = await _run_optimized_unlock(client, slug)
        optimized_rows.append(optimized)
        print("optimized", json.dumps(optimized, ensure_ascii=False))
        print()

    def _avg(rows: list[dict[str, Any]], key: str) -> float:
        values = [float(row.get(key) or 0) for row in rows if row]
        return round(sum(values) / len(values), 1) if values else 0.0

    summary = {
        "legacy_avg_requests": _avg(legacy_rows, "requests"),
        "legacy_avg_elapsed_ms": _avg(legacy_rows, "elapsed_ms"),
        "optimized_avg_requests": _avg(optimized_rows, "requests"),
        "optimized_avg_elapsed_ms": _avg(optimized_rows, "elapsed_ms"),
        "request_reduction_pct": None,
        "elapsed_reduction_pct": None,
    }
    if summary["legacy_avg_requests"] > 0:
        summary["request_reduction_pct"] = round(
            (1 - summary["optimized_avg_requests"] / summary["legacy_avg_requests"]) * 100,
            1,
        )
    if summary["legacy_avg_elapsed_ms"] > 0:
        summary["elapsed_reduction_pct"] = round(
            (1 - summary["optimized_avg_elapsed_ms"] / summary["legacy_avg_elapsed_ms"]) * 100,
            1,
        )

    print("=== Summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
