"""电视剧转存/归档按集去重：优先补缺集，单集优先于合集，同集保留最高画质。"""

from __future__ import annotations

import re
from typing import Any, Callable

from app.utils.name_parser import name_parser


def _default_score(item: dict[str, Any]) -> tuple[Any, ...]:
    from app.services.pan115_service import Pan115Service

    name = str(item.get("name") or item.get("fn") or "")
    size = item.get("size")
    if size is None:
        size = item.get("s") or item.get("fs") or 0
    return Pan115Service._score_video_file({"name": name, "size": size})


def build_tv_file_entry(
    item: dict[str, Any], *, group_id: int = 0
) -> dict[str, Any] | None:
    name = str(item.get("name") or item.get("fn") or "").strip()
    if not name:
        return None
    coverage = name_parser.parse_episode_coverage(name)
    if not coverage:
        return None
    fid = str(item.get("fid") or "").strip()
    if not fid:
        return None
    span = int(coverage["episode_end"]) - int(coverage["episode_start"]) + 1
    return {
        "fid": fid,
        "item": item,
        "coverage": coverage,
        "span": span,
        "is_single": span == 1,
        "group_id": int(group_id or 0),
    }


def entry_episode_set(entry: dict[str, Any]) -> set[tuple[int, int]]:
    return set(name_parser.iter_episode_keys(entry["coverage"]))


def tv_candidate_rank(
    entry: dict[str, Any],
    score_fn: Callable[[dict[str, Any]], tuple[Any, ...]] | None = None,
) -> tuple[Any, ...]:
    scorer = score_fn or _default_score
    return (
        1 if entry.get("is_single") else 0,
        -int(entry.get("span") or 1),
        scorer(entry.get("item") or {}),
    )


def _format_episode_label(season: int, episode: int) -> str:
    return f"S{season:02d}E{episode:02d}"


def _format_skip_for_fully_existing(entry: dict[str, Any]) -> str:
    episodes = name_parser.iter_episode_keys(entry["coverage"])
    if entry["is_single"]:
        season, episode = episodes[0]
        return f"网盘已存在 {_format_episode_label(season, episode)}，已跳过"
    start = int(entry["coverage"]["episode_start"])
    end = int(entry["coverage"]["episode_end"])
    return (
        f"网盘已存在 S{entry['coverage']['season']:02d}"
        f"E{start:02d}-E{end:02d} 全部集数，已跳过"
    )


def _prune_singles_covered_by_collections(
    entries: list[dict[str, Any]], keep_fids: set[str]
) -> set[str]:
    """已保留的多集合集覆盖到的单集文件不再重复保留。"""
    kept = [entry for entry in entries if entry["fid"] in keep_fids]
    collections = [entry for entry in kept if not entry["is_single"]]
    if not collections:
        return keep_fids

    next_keep = set(keep_fids)
    for entry in kept:
        if not entry["is_single"]:
            continue
        season, episode = name_parser.iter_episode_keys(entry["coverage"])[0]
        for collection in collections:
            if int(collection["coverage"]["season"]) != season:
                continue
            if name_parser.coverage_covers_episode(collection["coverage"], season, episode):
                next_keep.discard(entry["fid"])
                break
    return next_keep


def dedupe_tv_file_entries(
    entries: list[dict[str, Any]],
    *,
    existing_episodes: set[tuple[int, int]] | None = None,
    score_fn: Callable[[dict[str, Any]], tuple[Any, ...]] | None = None,
) -> tuple[set[str], dict[str, str]]:
    """
    按「补缺集」保留文件：只要还能覆盖尚未占用的集数就保留。
    单集优先于合集；同集冲突时保留更高画质；合集可补部分缺集。
    """
    existing = set(existing_episodes or set())
    skip_map: dict[str, str] = {}
    if not entries:
        return set(), skip_map

    candidates: list[dict[str, Any]] = []
    for entry in entries:
        episodes = entry_episode_set(entry)
        if existing and episodes.issubset(existing):
            skip_map[entry["fid"]] = _format_skip_for_fully_existing(entry)
            continue
        candidates.append(entry)

    if not candidates:
        return set(), skip_map

    sorted_entries = sorted(
        candidates,
        key=lambda row: tv_candidate_rank(row, score_fn),
        reverse=True,
    )

    covered = set(existing)
    keep_fids: set[str] = set()

    for entry in sorted_entries:
        fid = entry["fid"]
        episodes = entry_episode_set(entry)
        new_episodes = episodes - covered
        if not new_episodes:
            if entry["is_single"]:
                season, episode = next(iter(episodes))
                skip_map[fid] = (
                    f"重复集数 {_format_episode_label(season, episode)}，已保留更优资源"
                )
            else:
                start = int(entry["coverage"]["episode_start"])
                end = int(entry["coverage"]["episode_end"])
                skip_map[fid] = (
                    f"合集 S{entry['coverage']['season']:02d}E{start:02d}-E{end:02d} "
                    f"所含集数已全部覆盖，已跳过"
                )
            continue

        keep_fids.add(fid)
        covered |= episodes

    keep_fids = _prune_singles_covered_by_collections(candidates, keep_fids)
    for fid in list(keep_fids):
        skip_map.pop(fid, None)

    return keep_fids, skip_map


def dedupe_tv_transfer_files(
    files: list[dict[str, Any]],
    *,
    existing_episodes: set[tuple[int, int]] | None = None,
    group_id: int = 0,
    score_fn: Callable[[dict[str, Any]], tuple[Any, ...]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """对转存候选视频按集去重，非剧集文件原样保留。"""
    if not files:
        return [], {}

    tv_entries: list[dict[str, Any]] = []
    passthrough: list[dict[str, Any]] = []
    seen_tv_fids: set[str] = set()

    for item in files:
        entry = build_tv_file_entry(item, group_id=group_id)
        if entry:
            if entry["fid"] in seen_tv_fids:
                continue
            seen_tv_fids.add(entry["fid"])
            tv_entries.append(entry)
        else:
            passthrough.append(item)

    keep_fids, skip_map = dedupe_tv_file_entries(
        tv_entries,
        existing_episodes=existing_episodes,
        score_fn=score_fn,
    )

    kept_tv = [entry["item"] for entry in tv_entries if entry["fid"] in keep_fids]
    return passthrough + kept_tv, skip_map


def filename_likely_same_show(filename: str, show_title: str) -> bool:
    title = str(show_title or "").strip()
    if not title:
        return True
    name = str(filename or "").lower()
    normalized = re.sub(r"\s*[\(（]\s*\d{4}\s*[\)）]\s*$", "", title).strip()
    if not normalized:
        return True
    if normalized.lower() in name:
        return True
    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    if chinese_runs and any(run.lower() in name for run in chinese_runs):
        return True
    latin = re.sub(r"[^a-z0-9]+", "", normalized.lower())
    file_latin = re.sub(r"[^a-z0-9]+", "", name)
    if latin and len(latin) >= 3 and latin in file_latin:
        return True
    return False


def extract_episodes_from_filename(filename: str) -> set[tuple[int, int]]:
    coverage = name_parser.parse_episode_coverage(filename)
    if not coverage:
        return set()
    return set(name_parser.iter_episode_keys(coverage))
