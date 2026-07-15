"""电视剧转存/归档按集去重：单集优先于合集，同集保留最高画质。"""

from __future__ import annotations

import re
from collections import defaultdict
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


def dedupe_tv_file_entries(
    entries: list[dict[str, Any]],
    *,
    existing_episodes: set[tuple[int, int]] | None = None,
    score_fn: Callable[[dict[str, Any]], tuple[Any, ...]] | None = None,
) -> tuple[set[str], dict[str, str]]:
    """返回应保留的 fid 集合，以及被跳过文件的说明。"""
    existing = set(existing_episodes or set())
    skip_map: dict[str, str] = {}
    if not entries:
        return set(), skip_map

    usable_entries: list[dict[str, Any]] = []
    for entry in entries:
        episodes = name_parser.iter_episode_keys(entry["coverage"])
        if existing and all(ep in existing for ep in episodes):
            fid = entry["fid"]
            if len(episodes) == 1:
                season, episode = episodes[0]
                skip_map[fid] = f"网盘已存在 S{season:02d}E{episode:02d}，已跳过"
            else:
                start = int(entry["coverage"]["episode_start"])
                end = int(entry["coverage"]["episode_end"])
                skip_map[fid] = (
                    f"网盘已存在 S{entry['coverage']['season']:02d}"
                    f"E{start:02d}-E{end:02d} 覆盖集数，已跳过"
                )
            continue
        usable_entries.append(entry)

    if not usable_entries:
        return set(), skip_map

    episode_candidates: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(
        list
    )
    for entry in usable_entries:
        group_id = int(entry.get("group_id") or 0)
        for season, episode in name_parser.iter_episode_keys(entry["coverage"]):
            episode_candidates[(group_id, season, episode)].append(entry)

    episode_winner_fid: dict[tuple[int, int, int], str] = {}
    for ep_key, candidates in episode_candidates.items():
        winner = max(candidates, key=lambda row: tv_candidate_rank(row, score_fn))
        episode_winner_fid[ep_key] = winner["fid"]

    keep_fids: set[str] = set()
    for entry in usable_entries:
        fid = entry["fid"]
        group_id = int(entry.get("group_id") or 0)
        episodes = name_parser.iter_episode_keys(entry["coverage"])
        winner_fids = {
            episode_winner_fid.get((group_id, season, episode))
            for season, episode in episodes
        }
        if len(winner_fids) == 1 and fid in winner_fids:
            keep_fids.add(fid)
            continue

        if entry["is_single"]:
            season, episode = episodes[0]
            skip_map[fid] = (
                f"重复集数 S{season:02d}E{episode:02d}，已保留更高画质版本"
            )
            continue

        start = int(entry["coverage"]["episode_start"])
        end = int(entry["coverage"]["episode_end"])
        skip_map[fid] = (
            f"合集 S{entry['coverage']['season']:02d}E{start:02d}-E{end:02d} "
            f"与已有单集/更优资源重复，已跳过"
        )

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
    passthrough_fids: set[str] = set()

    for item in files:
        entry = build_tv_file_entry(item, group_id=group_id)
        if entry:
            tv_entries.append(entry)
        else:
            passthrough.append(item)
            fid = str(item.get("fid") or "").strip()
            if fid:
                passthrough_fids.add(fid)

    keep_fids, skip_map = dedupe_tv_file_entries(
        tv_entries,
        existing_episodes=existing_episodes,
        score_fn=score_fn,
    )

    kept_tv = [
        entry["item"]
        for entry in tv_entries
        if entry["fid"] in keep_fids
    ]
    # 保持相对稳定的顺序：先 passthrough，再 tv
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
