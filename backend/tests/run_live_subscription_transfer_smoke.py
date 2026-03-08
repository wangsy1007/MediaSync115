#!/usr/bin/env python3
"""Live smoke test for subscribe/save queue workflows.

This script talks to the running local API service and exercises:
1. Explore subscribe queue: subscribe -> unsubscribe.
2. Explore save queue for TV titles: enqueue two tasks back-to-back and verify
   they execute serially, then inspect 115 search results and queue logs.

It is intentionally side-effect aware:
- Subscribe test uses a unique temporary TMDB ID and unsubscribes afterwards.
- Save test cleans up newly created 115 items that match the tested titles.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 360
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_SAVE_CASES = [
    {"title": "除恶", "media_type": "tv", "tmdb_id": 281495, "year": "2026"},
    {"title": "玫瑰丛生", "media_type": "tv", "tmdb_id": 240446, "year": "2026"},
]


class ApiError(RuntimeError):
    """Raised when the API returns a non-2xx response."""


@dataclass
class TaskOutcome:
    """Simplified queue task payload."""

    task_id: str
    status: str
    message: str
    error: str
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    raw: dict[str, Any]


class LiveSmokeRunner:
    """Small client around the running MediaSync115 service."""

    def __init__(self, base_url: str, folder_id: str, timeout_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.folder_id = str(folder_id or "0")
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> Any:
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params, doseq=True)
        url = f"{self.base_url}{path}{query}"
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                text = response.read().decode(charset)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"{method} {path} -> {exc}") from exc

        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def enqueue_subscribe(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/search/explore/queue/subscribe", payload=payload)

    def enqueue_save(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/search/explore/queue/save", payload=payload)

    def get_queue_task(self, task_id: str) -> TaskOutcome:
        task = self.request("GET", f"/api/search/explore/queue/tasks/{urllib.parse.quote(task_id)}")
        return TaskOutcome(
            task_id=str(task.get("task_id") or ""),
            status=str(task.get("status") or ""),
            message=str(task.get("message") or ""),
            error=str(task.get("error") or ""),
            created_at=task.get("created_at"),
            started_at=task.get("started_at"),
            finished_at=task.get("finished_at"),
            raw=task,
        )

    def wait_for_queue_task(self, task_id: str) -> TaskOutcome:
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            task = self.get_queue_task(task_id)
            if task.status in {"success", "failed"}:
                return task
            time.sleep(DEFAULT_POLL_INTERVAL_SECONDS)
        raise TimeoutError(f"queue task timeout: {task_id}")

    def list_logs(self, trace_id: str, limit: int = 20) -> list[dict[str, Any]]:
        payload = self.request(
            "GET",
            "/api/logs",
            params={"source_type": "explore_queue", "module": "explore_queue", "trace_id": trace_id, "limit": limit},
        )
        items = payload.get("items") if isinstance(payload, dict) else []
        return [item for item in items if isinstance(item, dict)]

    def pan115_search(self, keyword: str) -> dict[str, Any]:
        return self.request(
            "GET",
            "/api/pan115/search",
            params={"search_value": keyword, "cid": self.folder_id},
            timeout=self.timeout_seconds,
        )

    def delete_pan115_items(self, fids: list[str]) -> dict[str, Any]:
        result = {"deleted": [], "tolerated": [], "failed": []}
        for fid in fids:
            try:
                payload = self.request(
                    "DELETE",
                    "/api/pan115/files",
                    params=[("fid", fid)],
                    timeout=self.timeout_seconds,
                )
                result["deleted"].append({"fid": fid, "result": payload})
            except Exception as exc:
                error_text = str(exc)
                if "文件已删除，请勿重复操作" in error_text:
                    result["tolerated"].append({"fid": fid, "error": error_text})
                    continue
                result["failed"].append({"fid": fid, "error": error_text})
        return result


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def extract_search_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def load_default_folder_id() -> str:
    runtime_file = Path(__file__).resolve().parents[1] / "data" / "runtime_settings.json"
    try:
        payload = json.loads(runtime_file.read_text(encoding="utf-8"))
    except Exception:
        return "0"
    return str(payload.get("pan115_default_folder_id") or "0")


def build_cleanup_fids(before_items: list[dict[str, Any]], after_items: list[dict[str, Any]]) -> list[str]:
    before_fids = {str(item.get("fid") or "") for item in before_items if item.get("fid")}
    cleanup_fids: list[str] = []
    for item in after_items:
        fid = str(item.get("fid") or "")
        if fid and fid not in before_fids:
            cleanup_fids.append(fid)
    return cleanup_fids


def is_duplicate_receive_error(task: dict[str, Any]) -> bool:
    error_text = str(task.get("error") or "")
    return "文件已接收，无需重复接收" in error_text


def run_subscribe_queue_smoke(runner: LiveSmokeRunner) -> dict[str, Any]:
    unique_suffix = int(time.time())
    tmdb_id = 990000000 + (unique_suffix % 1000000)
    title = f"自动化订阅测试-{unique_suffix}"
    base_payload = {
        "source": "tmdb",
        "media_type": "tv",
        "tmdb_id": tmdb_id,
        "title": title,
        "year": "2026",
    }

    subscribe_task = runner.enqueue_subscribe(base_payload)
    subscribe_result = runner.wait_for_queue_task(str(subscribe_task["task_id"]))
    unsubscribe_task = runner.enqueue_subscribe({**base_payload, "intent": "unsubscribe"})
    unsubscribe_result = runner.wait_for_queue_task(str(unsubscribe_task["task_id"]))

    return {
        "test_name": "subscribe_queue_smoke",
        "passed": (
            subscribe_result.status == "success"
            and unsubscribe_result.status == "success"
            and subscribe_result.raw.get("message") == "订阅成功"
            and unsubscribe_result.raw.get("message") == "已取消订阅"
        ),
        "subscribe_task": subscribe_result.raw,
        "unsubscribe_task": unsubscribe_result.raw,
        "subscribe_logs": runner.list_logs(subscribe_result.task_id),
        "unsubscribe_logs": runner.list_logs(unsubscribe_result.task_id),
    }


def run_save_queue_smoke(runner: LiveSmokeRunner, save_cases: list[dict[str, Any]]) -> dict[str, Any]:
    before_snapshots: dict[str, dict[str, Any]] = {}
    enqueue_results: list[dict[str, Any]] = []

    for case in save_cases:
        before_payload = runner.pan115_search(case["title"])
        before_items = extract_search_items(before_payload)
        before_snapshots[case["title"]] = {
            "payload": before_payload,
            "items": before_items,
            "count": int(before_payload.get("count") or len(before_items)),
        }

    for case in save_cases:
        payload = {
            "source": "tmdb",
            "media_type": case["media_type"],
            "tmdb_id": case["tmdb_id"],
            "title": case["title"],
            "year": case["year"],
        }
        enqueue_results.append({"case": case, "task": runner.enqueue_save(payload)})

    outcomes: list[dict[str, Any]] = []
    for entry in enqueue_results:
        task_id = str(entry["task"]["task_id"])
        final_task = runner.wait_for_queue_task(task_id)
        time.sleep(2)
        after_payload = runner.pan115_search(entry["case"]["title"])
        after_items = extract_search_items(after_payload)
        cleanup_fids = build_cleanup_fids(before_snapshots[entry["case"]["title"]]["items"], after_items)
        cleanup_result = None
        cleanup_error = ""
        cleanup_result = runner.delete_pan115_items(cleanup_fids)
        if cleanup_result.get("failed"):
            cleanup_error = json.dumps(cleanup_result["failed"], ensure_ascii=False)

        outcomes.append(
            {
                "case": entry["case"],
                "task": final_task.raw,
                "logs": runner.list_logs(task_id),
                "before_count": before_snapshots[entry["case"]["title"]]["count"],
                "after_count": int(after_payload.get("count") or len(after_items)),
                "cleanup_fids": cleanup_fids,
                "cleanup_result": cleanup_result,
                "cleanup_error": cleanup_error,
            }
        )

    serial_execution = False
    if len(outcomes) >= 2:
        first_finished = parse_iso_datetime(outcomes[0]["task"].get("finished_at"))
        second_started = parse_iso_datetime(outcomes[1]["task"].get("started_at"))
        serial_execution = bool(first_finished and second_started and second_started >= first_finished)

    passed = serial_execution
    for result in outcomes:
        task = result["task"]
        accepted_duplicate = task.get("status") == "failed" and is_duplicate_receive_error(task)
        result["accepted_duplicate_receive"] = accepted_duplicate
        passed = (
            passed
            and (task.get("status") == "success" or accepted_duplicate)
            and not result["cleanup_error"]
        )

    return {
        "test_name": "tv_save_queue_smoke",
        "passed": passed,
        "serial_execution": serial_execution,
        "outcomes": outcomes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live smoke tests for subscribe/save queue workflows.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base url, default: http://127.0.0.1:8000")
    parser.add_argument("--folder-id", default=load_default_folder_id(), help="115 default folder id")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Task timeout")
    args = parser.parse_args()

    runner = LiveSmokeRunner(
        base_url=args.base_url,
        folder_id=args.folder_id,
        timeout_seconds=args.timeout_seconds,
    )

    results = {
        "base_url": args.base_url,
        "folder_id": args.folder_id,
        "subscribe_queue": run_subscribe_queue_smoke(runner),
        "save_queue": run_save_queue_smoke(runner, list(DEFAULT_SAVE_CASES)),
    }
    results["passed"] = bool(
        results["subscribe_queue"].get("passed")
        and results["save_queue"].get("passed")
    )

    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
