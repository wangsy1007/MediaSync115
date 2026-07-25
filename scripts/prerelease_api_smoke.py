#!/usr/bin/env python3
"""MediaSync115 上线前 API 冒烟（只读 / 连通性，默认无副作用）。

对正在运行的服务（默认 http://127.0.0.1:5173）按模块检查基础能力，
输出 PASS / WARN / FAIL 汇总。任一 FAIL 退出码为 1；仅 WARN 退出 0。
加 --strict 时 WARN 也视为失败。
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable


DEFAULT_BASE_URL = os.environ.get("MEDIASYNC_BASE_URL", "http://127.0.0.1:5173")
DEFAULT_USER = os.environ.get("MEDIASYNC_USER", "admin")
DEFAULT_PASSWORD = os.environ.get("MEDIASYNC_PASSWORD", "password")

QUALITY_FIELDS = (
    "resource_preferred_resolutions",
    "resource_preferred_hdr",
    "resource_preferred_audio",
    "resource_preferred_subtitles",
    "resource_exclude_tags",
    "resource_min_size_gb",
    "resource_max_size_gb",
    "subscription_exclude_iso",
)

NOT_CONFIGURED_HINTS = (
    "未配置",
    "未登录",
    "请先配置",
    "not configured",
    "not_configured",
    "cookie_missing",
    "缺少",
)


@dataclass
class CheckResult:
    module: str
    name: str
    status: str  # PASS | WARN | FAIL
    message: str
    duration_ms: int = 0


@dataclass
class SmokeReport:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == "PASS")


class ApiClient:
    """带 Cookie 的简单 HTTP 客户端（标准库）。"""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
        authenticated: bool = True,
    ) -> tuple[int, Any]:
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params, doseq=True)
        url = f"{self.base_url}{path}{query}"
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url, data=body, method=method.upper(), headers=headers
        )
        opener = self.opener if authenticated else urllib.request.build_opener()
        try:
            with opener.open(request, timeout=timeout or self.timeout) as response:
                status = int(response.status)
                raw = response.read()
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{method} {path} -> {exc}") from exc

        text = raw.decode("utf-8", errors="replace") if raw else ""
        if not text:
            return status, None
        try:
            return status, json.loads(text)
        except json.JSONDecodeError:
            return status, text


def _is_not_configured(payload: Any, status_code: int | None = None) -> bool:
    if status_code in {412,}:
        return True
    if not isinstance(payload, dict):
        text = str(payload or "")
        return any(hint in text for hint in NOT_CONFIGURED_HINTS)
    if str(payload.get("status") or "") == "not_configured":
        return True
    message = str(payload.get("message") or payload.get("detail") or "")
    if isinstance(payload.get("detail"), dict):
        detail = payload["detail"]
        message = f"{message} {detail.get('message', '')} {detail.get('code', '')}"
    lowered = message.lower()
    return any(hint.lower() in lowered for hint in NOT_CONFIGURED_HINTS)


def _tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _run_check(
    report: SmokeReport,
    module: str,
    name: str,
    fn: Callable[[], tuple[str, str]],
) -> None:
    started = time.perf_counter()
    try:
        status, message = fn()
    except Exception as exc:  # noqa: BLE001 - smoke must never crash the suite
        status, message = "FAIL", str(exc)
    duration_ms = int((time.perf_counter() - started) * 1000)
    report.add(
        CheckResult(
            module=module,
            name=name,
            status=status,
            message=message,
            duration_ms=duration_ms,
        )
    )


def _payload_message(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("code") or "")
        if detail not in (None, ""):
            return str(detail)
        return str(payload.get("message") or "")
    return str(payload or "")


def classify_connectivity(payload: Any, status_code: int) -> tuple[str, str]:
    """将连通性检查结果归类为 PASS / WARN / FAIL。"""
    if _is_not_configured(payload, status_code):
        return "WARN", f"未配置/未登录: {_payload_message(payload) or '未配置'}"
    if isinstance(payload, dict):
        if payload.get("valid") is True or payload.get("success") is True:
            return "PASS", str(payload.get("message") or "连接正常")
        if payload.get("valid") is False:
            return "FAIL", str(payload.get("message") or "连接失败")
    if status_code >= 500:
        return "FAIL", f"HTTP {status_code}: {payload}"
    if 200 <= status_code < 300:
        return "PASS", f"HTTP {status_code}"
    return "FAIL", f"HTTP {status_code}: {payload}"


def check_ready(client: ApiClient, report: SmokeReport, alt_ports: list[str]) -> None:
    def healthz() -> tuple[str, str]:
        status, body = client.request("GET", "/healthz", authenticated=False, timeout=10)
        if status == 200:
            return "PASS", f"healthy ({body})"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "ready", "healthz", healthz)

    parsed = urllib.parse.urlparse(client.base_url)
    host = parsed.hostname or "127.0.0.1"
    for port in alt_ports:
        def port_check(p: str = port) -> tuple[str, str]:
            url = f"http://{host}:{p}/healthz"
            try:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    if int(resp.status) == 200:
                        return "PASS", f"{url} OK"
                    return "FAIL", f"{url} HTTP {resp.status}"
            except Exception as exc:  # noqa: BLE001
                return "WARN", f"{url} 不可达: {exc}"

        _run_check(report, "ready", f"healthz:{port}", port_check)

    def api_surface() -> tuple[str, str]:
        # all-in-one nginx 只反代 /api 与 /healthz，/docs、/openapi.json 不会到后端
        status, body = client.request(
            "GET", "/api/auth/session", authenticated=False, timeout=15
        )
        if status == 200 and isinstance(body, dict) and "authenticated" in body:
            return "PASS", "API 面可达 (/api/auth/session)"
        return "FAIL", f"/api/auth/session HTTP {status}: {body}"

    _run_check(report, "ready", "api_surface", api_surface)


def check_auth(client: ApiClient, report: SmokeReport, username: str, password: str) -> None:
    def unauth_protected() -> tuple[str, str]:
        status, body = client.request(
            "GET", "/api/subscriptions", authenticated=False, timeout=15
        )
        if status == 401:
            return "PASS", "未登录正确返回 401"
        return "FAIL", f"期望 401，实际 HTTP {status}: {body}"

    _run_check(report, "auth", "unauthenticated_401", unauth_protected)

    def login() -> tuple[str, str]:
        status, body = client.request(
            "POST",
            "/api/auth/login",
            payload={"username": username, "password": password},
            authenticated=True,
            timeout=15,
        )
        if status != 200 or not isinstance(body, dict) or not body.get("success"):
            return "FAIL", f"登录失败 HTTP {status}: {body}"
        return "PASS", f"登录成功 ({body.get('username')})"

    _run_check(report, "auth", "login", login)

    def session() -> tuple[str, str]:
        status, body = client.request("GET", "/api/auth/session", timeout=15)
        if status == 200 and isinstance(body, dict) and body.get("authenticated"):
            return "PASS", f"session ok ({body.get('username')})"
        return "FAIL", f"session 无效 HTTP {status}: {body}"

    _run_check(report, "auth", "session", session)


def check_settings(client: ApiClient, report: SmokeReport) -> None:
    runtime_payload: dict[str, Any] = {}

    def runtime() -> tuple[str, str]:
        nonlocal runtime_payload
        status, body = client.request("GET", "/api/settings/runtime", timeout=20)
        if status != 200 or not isinstance(body, dict):
            return "FAIL", f"HTTP {status}: {body}"
        runtime_payload = body
        return "PASS", f"字段数={len(body)}"

    _run_check(report, "settings", "runtime", runtime)

    def app_info() -> tuple[str, str]:
        status, body = client.request("GET", "/api/settings/app-info", timeout=15)
        if status != 200 or not isinstance(body, dict):
            return "FAIL", f"HTTP {status}: {body}"
        version = body.get("version") or body.get("app_version") or body.get("build_version")
        return "PASS", f"app-info ok (version={version})"

    _run_check(report, "settings", "app_info", app_info)

    def health_all() -> tuple[str, str]:
        status, body = client.request("GET", "/api/settings/health/all", timeout=60)
        if status != 200 or not isinstance(body, dict):
            return "FAIL", f"HTTP {status}: {body}"
        if "services" not in body:
            return "FAIL", "缺少 services 字段"
        return "PASS", f"valid={body.get('valid_count')}/{body.get('total_count')}"

    _run_check(report, "settings", "health_all", health_all)

    def quality_fields() -> tuple[str, str]:
        if not runtime_payload:
            return "WARN", "runtime 未加载，跳过画质字段检查"
        missing = [key for key in QUALITY_FIELDS if key not in runtime_payload]
        if missing:
            return "FAIL", f"缺少画质字段: {', '.join(missing)}"
        if not isinstance(runtime_payload.get("resource_exclude_tags"), list):
            return "FAIL", "resource_exclude_tags 应为 list"
        return "PASS", "画质偏好字段齐全"

    _run_check(report, "settings", "quality_preference_fields", quality_fields)

    for path, label in (
        ("/api/settings/tmdb/check", "tmdb"),
        ("/api/settings/emby/check", "emby"),
        ("/api/settings/feiniu/check", "feiniu"),
        ("/api/settings/tg/check", "tg"),
        ("/api/settings/hdhive/check", "hdhive"),
        ("/api/settings/pansou/check", "pansou"),
        ("/api/settings/juying/check", "juying"),
    ):

        def connectivity(p: str = path, name: str = label) -> tuple[str, str]:
            status, body = client.request("GET", p, timeout=45)
            return classify_connectivity(body, status)

        _run_check(report, "connectivity", label, connectivity)

    def update_check() -> tuple[str, str]:
        status, body = client.request("GET", "/api/settings/update-check", timeout=30)
        if status == 200 and isinstance(body, dict):
            return "PASS", str(body.get("message") or "update-check ok")
        if status in {400, 502}:
            return "WARN", f"更新检查不可用 HTTP {status}: {body}"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "settings", "update_check", update_check)

    def tg_bot_status() -> tuple[str, str]:
        status, body = client.request("GET", "/api/settings/tg-bot/status", timeout=15)
        if status == 200 and isinstance(body, dict):
            return "PASS", f"running={body.get('running')}"
        return "WARN", f"HTTP {status}: {body}"

    _run_check(report, "settings", "tg_bot_status", tg_bot_status)


def check_search_explore(client: ApiClient, report: SmokeReport) -> None:
    def explore_home() -> tuple[str, str]:
        status, body = client.request(
            "GET",
            "/api/search/explore/home",
            params={"source": "douban"},
            timeout=60,
        )
        if status != 200:
            msg = _payload_message(body)
            # 外网/代理未就绪时豆瓣榜单会 502，记 WARN 不阻断本地模块回归
            if status in {502, 503, 504} or "Failed to fetch" in msg:
                return "WARN", f"外部榜单暂不可用: {msg or body}"
            return "FAIL", f"HTTP {status}: {body}"
        if not isinstance(body, dict):
            return "FAIL", "响应非 JSON 对象"
        return "PASS", f"keys={list(body.keys())[:6]}"

    _run_check(report, "explore", "douban_home", explore_home)

    def search() -> tuple[str, str]:
        status, body = client.request(
            "GET",
            "/api/search",
            params={"query": "Inception", "media_type": "movie"},
            timeout=45,
        )
        if status != 200:
            if _is_not_configured(body, status):
                return "WARN", f"搜索依赖未就绪: {body}"
            return "FAIL", f"HTTP {status}: {body}"
        return "PASS", "search ok"

    _run_check(report, "explore", "tmdb_search", search)

    def movie_detail() -> tuple[str, str]:
        status, body = client.request("GET", "/api/search/movie/272", timeout=45)
        if status != 200:
            if _is_not_configured(body, status):
                return "WARN", f"电影详情依赖未就绪: {body}"
            return "FAIL", f"HTTP {status}: {body}"
        if isinstance(body, dict) and (body.get("id") or body.get("title") or body.get("name")):
            return "PASS", str(body.get("title") or body.get("name") or body.get("id"))
        return "PASS", "movie detail ok"

    _run_check(report, "explore", "movie_detail", movie_detail)

    def tv_detail() -> tuple[str, str]:
        status, body = client.request("GET", "/api/search/tv/1399", timeout=45)
        if status != 200:
            if _is_not_configured(body, status):
                return "WARN", f"剧集详情依赖未就绪: {body}"
            return "FAIL", f"HTTP {status}: {body}"
        return "PASS", str(
            (body.get("name") if isinstance(body, dict) else None) or "tv detail ok"
        )

    _run_check(report, "explore", "tv_detail", tv_detail)


def check_subscriptions(client: ApiClient, report: SmokeReport) -> None:
    def list_subs() -> tuple[str, str]:
        status, body = client.request("GET", "/api/subscriptions", timeout=30)
        if status != 200 or not isinstance(body, dict):
            return "FAIL", f"HTTP {status}: {body}"
        items = body.get("items")
        count = len(items) if isinstance(items, list) else "?"
        return "PASS", f"items={count}"

    _run_check(report, "subscriptions", "list", list_subs)

    def status_map() -> tuple[str, str]:
        status, body = client.request("GET", "/api/subscriptions/status-map", timeout=30)
        if status != 200:
            return "FAIL", f"HTTP {status}: {body}"
        return "PASS", "status-map ok"

    _run_check(report, "subscriptions", "status_map", status_map)

    def run_status() -> tuple[str, str]:
        status, body = client.request(
            "GET", "/api/subscriptions/actions/run/status", timeout=20
        )
        if status != 200:
            return "FAIL", f"HTTP {status}: {body}"
        return "PASS", "run status ok"

    _run_check(report, "subscriptions", "run_status", run_status)


def check_watchlists_and_follows(client: ApiClient, report: SmokeReport) -> None:
    def watchlists() -> tuple[str, str]:
        status, body = client.request("GET", "/api/watchlists", timeout=20)
        if status != 200:
            return "FAIL", f"HTTP {status}: {body}"
        return "PASS", "watchlists ok"

    _run_check(report, "watchlists", "list", watchlists)

    def watchlist_status() -> tuple[str, str]:
        status, body = client.request("GET", "/api/watchlists/status-map", timeout=20)
        if status != 200:
            return "FAIL", f"HTTP {status}: {body}"
        return "PASS", "status-map ok"

    _run_check(report, "watchlists", "status_map", watchlist_status)

    def follows() -> tuple[str, str]:
        status, body = client.request("GET", "/api/person-follows", timeout=20)
        if status != 200:
            return "FAIL", f"HTTP {status}: {body}"
        return "PASS", "person-follows ok"

    _run_check(report, "person_follows", "list", follows)

    def follow_status() -> tuple[str, str]:
        status, body = client.request(
            "GET", "/api/person-follows/status-map", timeout=20
        )
        if status != 200:
            return "FAIL", f"HTTP {status}: {body}"
        return "PASS", "status-map ok"

    _run_check(report, "person_follows", "status_map", follow_status)


def check_pan115(client: ApiClient, report: SmokeReport) -> None:
    def cookie_check() -> tuple[str, str]:
        status, body = client.request("GET", "/api/pan115/cookie/check", timeout=45)
        return classify_connectivity(body, status)

    _run_check(report, "pan115", "cookie_check", cookie_check)

    def transfer_status() -> tuple[str, str]:
        status, body = client.request("GET", "/api/pan115/transfer/status", timeout=20)
        if status == 200:
            return "PASS", "transfer status ok"
        if _is_not_configured(body, status):
            return "WARN", f"未配置: {body}"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "pan115", "transfer_status", transfer_status)

    def default_folder() -> tuple[str, str]:
        status, body = client.request("GET", "/api/pan115/default-folder", timeout=20)
        if status == 200:
            return "PASS", str(body)
        if _is_not_configured(body, status):
            return "WARN", f"未配置: {body}"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "pan115", "default_folder", default_folder)


def check_quark_pansou_juying(client: ApiClient, report: SmokeReport) -> None:
    def quark() -> tuple[str, str]:
        status, body = client.request("GET", "/api/quark/cookie/check", timeout=30)
        return classify_connectivity(body, status)

    _run_check(report, "quark", "cookie_check", quark)

    def pansou_health() -> tuple[str, str]:
        status, body = client.request("GET", "/api/pansou/health", timeout=30)
        if status == 200 and isinstance(body, dict):
            if body.get("status") == "healthy":
                return "PASS", "pansou healthy"
            return "WARN", f"pansou 未就绪: {body}"
        return classify_connectivity(body, status)

    _run_check(report, "pansou", "health", pansou_health)

    def pansou_config() -> tuple[str, str]:
        status, body = client.request("GET", "/api/pansou/config", timeout=15)
        if status == 200 and isinstance(body, dict):
            return "PASS", "config ok"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "pansou", "config", pansou_config)

    def juying_resources() -> tuple[str, str]:
        # 只验证路由可达；未登录聚影时允许 WARN
        status, body = client.request(
            "GET", "/api/juying/movie/272/resources", timeout=45
        )
        if status == 200:
            return "PASS", "resources ok"
        return classify_connectivity(body, status)

    _run_check(report, "juying", "movie_resources", juying_resources)


def check_archive_strm(client: ApiClient, report: SmokeReport) -> None:
    def archive_config() -> tuple[str, str]:
        status, body = client.request("GET", "/api/archive/config", timeout=20)
        if status == 200 and isinstance(body, dict):
            return "PASS", "archive config ok"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "archive", "config", archive_config)

    def archive_tasks() -> tuple[str, str]:
        status, body = client.request("GET", "/api/archive/tasks", timeout=20)
        if status == 200:
            return "PASS", "tasks ok"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "archive", "tasks", archive_tasks)

    def strm_config() -> tuple[str, str]:
        status, body = client.request("GET", "/api/strm/config", timeout=20)
        if status == 200 and isinstance(body, dict):
            return "PASS", "strm config ok"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "strm", "config", strm_config)

    def strm_diagnose() -> tuple[str, str]:
        status, body = client.request("GET", "/api/strm/diagnose", timeout=45)
        if status == 200:
            return "PASS", "diagnose ok"
        # 未配置输出目录时可能失败
        if _is_not_configured(body, status) or status in {400, 404}:
            return "WARN", f"diagnose 未就绪: {body}"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "strm", "diagnose", strm_diagnose)


def check_emby_proxy(report: SmokeReport, base_url: str) -> None:
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"

    def port_8099() -> tuple[str, str]:
        if _tcp_open(host, 8099, timeout=2.0):
            return "PASS", f"{host}:8099 端口可达"
        return "WARN", f"{host}:8099 端口不可达（未启用 Emby 代理时可忽略）"

    _run_check(report, "emby_proxy", "port_8099", port_8099)

    def stream_redirect_route() -> tuple[str, str]:
        # 无真实 item 时可能 404/502，但路由应存在且非「请先登录」
        url = f"http://{host}:8099/api/emby/stream-redirect/prerelease-probe"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return "PASS", f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                body = exc.read().decode("utf-8", errors="replace")
                if "请先登录" in body:
                    return "FAIL", "Emby 代理路由被鉴权拦截"
            if exc.code in {404, 400, 502, 503}:
                return "PASS", f"路由可达 (HTTP {exc.code})"
            return "WARN", f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            return "WARN", f"探测失败: {exc}"

    _run_check(report, "emby_proxy", "stream_redirect_route", stream_redirect_route)


def check_ops(client: ApiClient, report: SmokeReport) -> None:
    def scheduler_jobs() -> tuple[str, str]:
        status, body = client.request("GET", "/api/scheduler/jobs", timeout=20)
        if status == 200:
            return "PASS", "jobs ok"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "scheduler", "jobs", scheduler_jobs)

    def workflows() -> tuple[str, str]:
        status, body = client.request("GET", "/api/workflow", timeout=20)
        if status == 200:
            return "PASS", "workflows ok"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "workflow", "list", workflows)

    def event_types() -> tuple[str, str]:
        status, body = client.request("GET", "/api/workflow/event-types", timeout=15)
        if status == 200:
            return "PASS", "event-types ok"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "workflow", "event_types", event_types)

    def log_modules() -> tuple[str, str]:
        status, body = client.request("GET", "/api/logs/modules", timeout=15)
        if status == 200:
            return "PASS", "modules ok"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "logs", "modules", log_modules)

    def logs_list() -> tuple[str, str]:
        status, body = client.request(
            "GET", "/api/logs", params={"limit": 5}, timeout=20
        )
        if status == 200:
            return "PASS", "logs list ok"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "logs", "list", logs_list)

    def license_status() -> tuple[str, str]:
        status, body = client.request("GET", "/api/license/status", timeout=15)
        if status == 200 and isinstance(body, dict):
            return "PASS", f"has_license_key={body.get('has_license_key')}"
        return "FAIL", f"HTTP {status}: {body}"

    _run_check(report, "license", "status", license_status)


def print_report(report: SmokeReport) -> None:
    print()
    print("=" * 72)
    print("MediaSync115 上线前 API 冒烟报告")
    print("=" * 72)
    current_module = ""
    for item in report.results:
        if item.module != current_module:
            current_module = item.module
            print(f"\n[{current_module}]")
        mark = {"PASS": "OK  ", "WARN": "WARN", "FAIL": "FAIL"}.get(item.status, item.status)
        print(f"  {mark}  {item.name:<32} {item.duration_ms:>5}ms  {item.message}")
    print()
    print("-" * 72)
    print(
        f"合计: PASS={report.pass_count}  WARN={report.warn_count}  FAIL={report.fail_count}"
    )
    print("-" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="MediaSync115 pre-release API smoke")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument(
        "--alt-health-ports",
        default="9008",
        help="逗号分隔的额外 healthz 端口，默认 9008",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="WARN 也视为失败",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="可选：将结果写入 JSON 文件",
    )
    args = parser.parse_args()

    alt_ports = [p.strip() for p in str(args.alt_health_ports).split(",") if p.strip()]
    client = ApiClient(args.base_url)
    report = SmokeReport()

    print(f"目标: {args.base_url}")
    check_ready(client, report, alt_ports)
    # 就绪失败则后续多半无意义，但仍继续尽量收集信息
    check_auth(client, report, args.username, args.password)
    check_settings(client, report)
    check_search_explore(client, report)
    check_subscriptions(client, report)
    check_watchlists_and_follows(client, report)
    check_pan115(client, report)
    check_quark_pansou_juying(client, report)
    check_archive_strm(client, report)
    check_emby_proxy(report, args.base_url)
    check_ops(client, report)

    print_report(report)

    if args.json_out:
        payload = {
            "base_url": args.base_url,
            "pass": report.pass_count,
            "warn": report.warn_count,
            "fail": report.fail_count,
            "results": [
                {
                    "module": r.module,
                    "name": r.name,
                    "status": r.status,
                    "message": r.message,
                    "duration_ms": r.duration_ms,
                }
                for r in report.results
            ],
        }
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    if report.fail_count:
        return 1
    if args.strict and report.warn_count:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
