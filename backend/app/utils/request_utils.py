"""HTTP 请求辅助工具。"""

from __future__ import annotations

from fastapi import Request


def get_client_ip(request: Request) -> str:
    forwarded_for = str(request.headers.get("x-forwarded-for", "")).strip()
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    client = request.client
    return str(getattr(client, "host", "") or "unknown")
