"""
Extract resolution and format tags from resource metadata.

Tags are derived from resource_name, title, and existing quality/resolution fields.
"""

import re
from typing import Any

# ── Resolution definitions (order = priority high→low) ──────────────
RESOLUTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("4K",    re.compile(r"\b(?:4K|2160[pPiI]|UHD)\b", re.IGNORECASE)),
    ("1080p", re.compile(r"\b(?:1080[pPiI]|FHD|Full\s*HD)\b", re.IGNORECASE)),
    ("720p",  re.compile(r"\b720[pPiI]\b", re.IGNORECASE)),
    ("480p",  re.compile(r"\b480[pPiI]\b", re.IGNORECASE)),
]

# ── Format definitions ───────────────────────────────────────────────
FORMAT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Dolby Vision", re.compile(r"\b(?:Dolby\s*Vision|DoVi|DV)\b", re.IGNORECASE)),
    ("HDR10+",       re.compile(r"\bHDR10\+", re.IGNORECASE)),
    ("HDR10",        re.compile(r"\bHDR10\b", re.IGNORECASE)),
    ("HDR",          re.compile(r"\bHDR\b", re.IGNORECASE)),
    ("SDR",          re.compile(r"\bSDR\b", re.IGNORECASE)),
    ("REMUX",        re.compile(r"\bREMUX\b", re.IGNORECASE)),
    ("BluRay",       re.compile(r"\b(?:Blu[\-\s]?Ray|BDRip|BDRemux|BD)\b", re.IGNORECASE)),
    ("WEB-DL",       re.compile(r"\b(?:WEB[\-\s]?DL|WEBDL|WEBRip|WEB)\b", re.IGNORECASE)),
    ("HEVC",         re.compile(r"\b(?:HEVC|[Hh]\.?265|x265)\b")),
    ("H.264",        re.compile(r"\b(?:AVC|[Hh]\.?264|x264)\b")),
    ("AV1",          re.compile(r"\bAV1\b", re.IGNORECASE)),
    ("Atmos",        re.compile(r"\bAtmos\b", re.IGNORECASE)),
    ("DTS-HD",       re.compile(r"\bDTS[\-\s]?HD(?:\s*MA)?\b", re.IGNORECASE)),
    ("TrueHD",       re.compile(r"\bTrueHD\b", re.IGNORECASE)),
    ("DTS",          re.compile(r"\bDTS\b", re.IGNORECASE)),
    ("AAC",          re.compile(r"\bAAC\b", re.IGNORECASE)),
    ("FLAC",         re.compile(r"\bFLAC\b", re.IGNORECASE)),
]

# ── Exclude patterns (low quality / fake) ────────────────────────────
EXCLUDE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("CAM",     re.compile(r"\b(?:CAM|CAMRip|枪版)\b", re.IGNORECASE)),
    ("TS",      re.compile(r"\b(?:TS|TELESYNC|TeleSync)\b", re.IGNORECASE)),
    ("抢先版",  re.compile(r"\b(?:抢先版|抢版|偷跑版|枪版)\b")),
    ("TC",      re.compile(r"\bTC\b")),
    ("SCR",     re.compile(r"\bSCR\b")),
    ("DVDScr",  re.compile(r"\bDVDScr\b", re.IGNORECASE)),
]

# ── Language / subtitle patterns ─────────────────────────────────────
LANGUAGE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("国语",   re.compile(r"\b(?:国语|国配|国粤|CHINESE|普通话|mandarin)\b", re.IGNORECASE)),
    ("粤语",   re.compile(r"\b(?:粤语|粤配|Cantonese)\b", re.IGNORECASE)),
    ("英语",   re.compile(r"\b(?:英语|English|ENG)\b", re.IGNORECASE)),
    ("日语",   re.compile(r"\b(?:日语|Japanese|JAP)\b", re.IGNORECASE)),
    ("韩语",   re.compile(r"\b(?:韩语|Korean|KOR)\b", re.IGNORECASE)),
]

SUBTITLE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("中字",   re.compile(r"\b(?:中字|中文字幕|内嵌中字|简中|繁中|双语字幕|中英字幕|中英双字)\b", re.IGNORECASE)),
    ("内封字幕", re.compile(r"\b(?:内封|内嵌|内封字幕)\b", re.IGNORECASE)),
    ("外挂字幕", re.compile(r"\b(?:外挂|外挂字幕)\b", re.IGNORECASE)),
]

# ── Size parsing ─────────────────────────────────────────────────────
SIZE_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(GB|GiB|MB|MiB|TB|TiB)\b",
    re.IGNORECASE,
)

ALL_RESOLUTION_LABELS = [label for label, _ in RESOLUTION_PATTERNS]
ALL_FORMAT_LABELS = [label for label, _ in FORMAT_PATTERNS]
ALL_EXCLUDE_LABELS = [label for label, _ in EXCLUDE_PATTERNS]
ALL_LANGUAGE_LABELS = [label for label, _ in LANGUAGE_PATTERNS]
ALL_SUBTITLE_LABELS = [label for label, _ in SUBTITLE_PATTERNS]


def _collect_text(resource: dict[str, Any]) -> str:
    """Build a searchable text blob from all relevant resource fields."""
    parts: list[str] = []
    for key in ("resource_name", "title", "name", "overview"):
        val = resource.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)

    # HDHive structured fields
    for key in ("quality", "resolution"):
        val = resource.get(key)
        if isinstance(val, list):
            parts.extend(str(v) for v in val if v)
        elif isinstance(val, str) and val.strip():
            parts.append(val)

    return " ".join(parts)


def extract_tags(resource: dict[str, Any]) -> dict[str, Any]:
    """
    Return ``{"resolution": "1080p"|"", "formats": ["HDR", "HEVC", ...]}``.

    Only the *highest-priority* resolution is returned; formats can be multiple.
    """
    text = _collect_text(resource)

    resolution = ""
    for label, pattern in RESOLUTION_PATTERNS:
        if pattern.search(text):
            resolution = label
            break

    formats: list[str] = []
    seen: set[str] = set()
    for label, pattern in FORMAT_PATTERNS:
        if label in seen:
            continue
        if pattern.search(text):
            formats.append(label)
            seen.add(label)
            # Avoid duplicate HDR variants
            if label in ("HDR10+", "HDR10"):
                seen.add("HDR")
            elif label == "DTS-HD":
                seen.add("DTS")

    return {"resolution": resolution, "formats": formats}


def extract_extended_tags(resource: dict[str, Any]) -> dict[str, Any]:
    """Extended tag extraction including exclude, language, subtitle, size."""
    text = _collect_text(resource)

    base = extract_tags(resource)

    excludes: list[str] = []
    for label, pattern in EXCLUDE_PATTERNS:
        if pattern.search(text):
            excludes.append(label)

    languages: list[str] = []
    for label, pattern in LANGUAGE_PATTERNS:
        if pattern.search(text):
            languages.append(label)

    subtitles: list[str] = []
    for label, pattern in SUBTITLE_PATTERNS:
        if pattern.search(text):
            subtitles.append(label)

    size_gb: float | None = None
    size_match = SIZE_PATTERN.search(text)
    if size_match:
        value = float(size_match.group(1))
        unit = size_match.group(2).upper()
        if unit.startswith("TB"):
            size_gb = value * 1024
        elif unit.startswith("GB"):
            size_gb = value
        elif unit.startswith("MB"):
            size_gb = value / 1024

    base["excludes"] = excludes
    base["languages"] = languages
    base["subtitles"] = subtitles
    base["size_gb"] = size_gb
    return base


def enrich_resource(resource: dict[str, Any]) -> dict[str, Any]:
    """Add ``_tags`` field to a resource dict (in-place and returned)."""
    resource["_tags"] = extract_tags(resource)
    return resource


def enrich_resource_extended(resource: dict[str, Any]) -> dict[str, Any]:
    """Add ``_tags`` field with extended tags to a resource dict (in-place and returned)."""
    resource["_tags"] = extract_extended_tags(resource)
    return resource


def score_resource(
    resource: dict[str, Any],
    preferred_resolutions: list[str],
    preferred_formats: list[str],
) -> float:
    """
    Score a resource based on user preferences.  Higher = better match.

    - Resolution match: 1000 * (N - index) where N = len(preferred_resolutions)
    - Format match: 100 per matching format (earlier in pref list → higher)
    - No match → 0 (still usable, just lower priority)
    """
    tags = resource.get("_tags") or extract_tags(resource)
    score = 0.0

    res = tags.get("resolution", "")
    if res and preferred_resolutions:
        res_lower = res.lower()
        for idx, pref in enumerate(preferred_resolutions):
            if pref.lower() == res_lower:
                score += 1000 * (len(preferred_resolutions) - idx)
                break

    formats = set(f.lower() for f in (tags.get("formats") or []))
    if formats and preferred_formats:
        for idx, pref in enumerate(preferred_formats):
            if pref.lower() in formats:
                score += 100 * (len(preferred_formats) - idx)

    return score


def matches_quality_filter(
    resource: dict[str, Any],
    *,
    preferred_resolutions: list[str] | None = None,
    preferred_formats: list[str] | None = None,
    exclude_labels: list[str] | None = None,
    preferred_languages: list[str] | None = None,
    preferred_subtitles: list[str] | None = None,
    min_size_gb: float | None = None,
    max_size_gb: float | None = None,
) -> bool:
    """Check if a resource passes quality filters. Returns True if it should be kept."""
    tags = resource.get("_tags") or extract_extended_tags(resource)

    if exclude_labels:
        resource_excludes = set(e.lower() for e in (tags.get("excludes") or []))
        for label in exclude_labels:
            if label.lower() in resource_excludes:
                return False

    if min_size_gb is not None or max_size_gb is not None:
        size = tags.get("size_gb")
        if size is not None:
            if min_size_gb is not None and size < min_size_gb:
                return False
            if max_size_gb is not None and size > max_size_gb:
                return False

    if preferred_resolutions:
        res = (tags.get("resolution") or "").lower()
        if res and not any(res == pref.lower() for pref in preferred_resolutions):
            return False

    if preferred_formats:
        resource_formats = set(f.lower() for f in (tags.get("formats") or []))
        if resource_formats and not any(
            pref.lower() in resource_formats for pref in preferred_formats
        ):
            return False

    if preferred_languages:
        resource_langs = set(l.lower() for l in (tags.get("languages") or []))
        if resource_langs and not any(
            pref.lower() in resource_langs for pref in preferred_languages
        ):
            return False

    if preferred_subtitles:
        resource_subs = set(s.lower() for s in (tags.get("subtitles") or []))
        if resource_subs and not any(
            pref.lower() in resource_subs for pref in preferred_subtitles
        ):
            return False

    return True


def filter_and_sort_by_quality(
    resources: list[dict[str, Any]],
    *,
    preferred_resolutions: list[str] | None = None,
    preferred_formats: list[str] | None = None,
    exclude_labels: list[str] | None = None,
    preferred_languages: list[str] | None = None,
    preferred_subtitles: list[str] | None = None,
    min_size_gb: float | None = None,
    max_size_gb: float | None = None,
) -> list[dict[str, Any]]:
    """Filter resources by quality criteria and sort by preference score."""
    has_filter = any([
        preferred_resolutions,
        preferred_formats,
        exclude_labels,
        preferred_languages,
        preferred_subtitles,
        min_size_gb,
        max_size_gb,
    ])

    for r in resources:
        if "_tags" not in r:
            enrich_resource_extended(r)

    if has_filter:
        resources = [
            r for r in resources
            if matches_quality_filter(
                r,
                preferred_resolutions=preferred_resolutions or [],
                preferred_formats=preferred_formats or [],
                exclude_labels=exclude_labels or [],
                preferred_languages=preferred_languages or [],
                preferred_subtitles=preferred_subtitles or [],
                min_size_gb=min_size_gb,
                max_size_gb=max_size_gb,
            )
        ]

    if preferred_resolutions or preferred_formats:
        return sorted(
            resources,
            key=lambda r: score_resource(r, preferred_resolutions or [], preferred_formats or []),
            reverse=True,
        )
    return resources


def sort_by_preference(
    resources: list[dict[str, Any]],
    preferred_resolutions: list[str],
    preferred_formats: list[str],
) -> list[dict[str, Any]]:
    """Sort resources by preference score (highest first), preserving order for ties."""
    if not preferred_resolutions and not preferred_formats:
        return resources
    for r in resources:
        if "_tags" not in r:
            enrich_resource(r)
    return sorted(
        resources,
        key=lambda r: score_resource(r, preferred_resolutions, preferred_formats),
        reverse=True,
    )
