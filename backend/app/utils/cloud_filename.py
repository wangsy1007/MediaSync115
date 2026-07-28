"""115 网盘同名冲突时自动追加 (1)(2) 等后缀的文件名处理。"""

from __future__ import annotations

import re

_CLOUD_DUP_PAREN_SUFFIX = re.compile(r"[\s._\-]*[\(（](\d+)[\)）]$")
_CLOUD_DUP_SPACE_SUFFIX = re.compile(r"[\s._\-]+(\d{1,3})$")


def strip_cloud_duplicate_suffix(filename: str) -> str:
    """去掉网盘自动追加的重复序号后缀，保留扩展名。"""
    text = str(filename or "").strip()
    if not text:
        return ""
    dot = text.rfind(".")
    if dot <= 0:
        base, ext = text, ""
    else:
        base, ext = text[:dot], text[dot:]

    previous = None
    current = base
    while previous != current:
        previous = current
        current = _CLOUD_DUP_PAREN_SUFFIX.sub("", current).rstrip(" ._-")
        current = _CLOUD_DUP_SPACE_SUFFIX.sub("", current).rstrip(" ._-")
    return f"{current}{ext}" if ext else current


def normalize_archive_basename(filename: str) -> str:
    """用于目标目录内文件名去重比较的规范化基名。"""
    return strip_cloud_duplicate_suffix(str(filename or "")).strip().casefold()


def is_cloud_duplicate_variant(name_a: str, name_b: str) -> bool:
    """判断两个文件名是否为同一文件（含网盘重复后缀变体）。"""
    left = normalize_archive_basename(name_a)
    right = normalize_archive_basename(name_b)
    return bool(left) and left == right
