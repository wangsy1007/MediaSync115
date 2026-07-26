"""归档/转存展示片名清洗：去掉资源站广告、画质尾巴与无规则前缀。"""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_YEAR_SUFFIX_RE = re.compile(r"\s*[\(（]\s*\d{4}\s*[\)）]\s*$")
_BRACKET_GROUP_RE = re.compile(r"[【\[][^】\]]*[】\]]|[（(][^）)]*[）)]")
_LEADING_EMOJI_RE = re.compile(
    r"^[\s"
    r"\U0001F300-\U0001FAFF"
    r"\u2600-\u27BF"
    r"]+"
)
_CATEGORY_PREFIX_RE = re.compile(
    r"^(?:电影|电视剧|剧集|综艺|动漫|纪录片|动画|资源|高清|蓝光|网盘)[:：]\s*"
)

_TECH_TOKEN = (
    r"(?:"
    r"2160p|1080p|720p|480p|576p|360p|"
    r"4k(?:[\s._-]?uhd)?|8k|uhd|fhd|"
    r"web[\s._-]?dl|webrip|webdl|"
    r"blu[\s._-]?ray|bluray|bdremux|bdrip|brrip|hddvd|hdtv|hdrip|dvdrip|dvdscr|remux|pdtv|sdtv|hdcam|cam|ts|tc|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|av1|xvid|divx|"
    r"hdr10\+?|hdr|sdr|hlg|dolby[\s._-]?vision|\bdv\b|"
    r"atmos|truehd|dts(?:[\s._-]?hd)?(?:[\s._-]?ma)?|dd[p+]?(?:[\s._-]?[57]\.1)?|ac3|eac3|aac|flac|lpcm|opus|"
    r"10[\s._-]?bit|8[\s._-]?bit|12[\s._-]?bit|"
    r"imax|repack|proper|extended|uncut|remaster(?:ed)?|criterion|"
    r"directors?[\s._-]?cut|theatrical|hybrid|"
    r"nf|amzn|dsnp|atvp|hmax|hulu|itunes|\bit\b|"
    r"ma[\s._-]?10|main10"
    r")"
)

_ZH_NOISE_TOKEN = (
    r"(?:"
    r"杜比视界|杜比全景声|内封|外挂|特效|字幕|简中|简英|繁中|繁英|"
    r"双语|国语|粤语|中字|英字|中英|精修|高码|原盘|特效字幕|"
    r"中文字幕|英文字幕|简体|繁体|"
    r"更新至\d+[集话期]?|全\d+[集话期]|更至\d+[集话期]?|"
    r"完结|全集|合集|高清|蓝光|抢先版|内部|独家"
    r")"
)

_AD_SITE_TOKEN = (
    r"(?:"
    r"高清(?:资源|剧集|影视|电影)?网?|资源站|电影天堂|阳光电影|哔嘀影视|"
    r"更多精彩|关注微信|扫码关注|加群|电报群?|Telegram|频道|分享|"
    r"首发|独家发布|招募|广告|网盘资源|阿里云盘|夸克网盘|115网盘|"
    r"磁力搜索|最新电影|免费观看"
    r")"
)

TECH_CUT_RE = re.compile(
    rf"(?i)(?:(?<=[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af])|(?<![A-Za-z0-9])){_TECH_TOKEN}"
)
ZH_NOISE_CUT_RE = re.compile(
    rf"(?:(?<=[\u3400-\u9fff])|(?<=[^A-Za-z0-9\u3400-\u9fff])|^){_ZH_NOISE_TOKEN}"
)
AD_SITE_RE = re.compile(_AD_SITE_TOKEN)

IGNORE_PATTERNS = (
    rf"(?i)(?<![A-Za-z0-9]){_TECH_TOKEN}(?![A-Za-z0-9])",
    rf"(?i)(?<=[\u3400-\u9fff]){_TECH_TOKEN}",
    rf"{_ZH_NOISE_TOKEN}",
    rf"{_AD_SITE_TOKEN}",
    r"(?i)\b(?:yyets|rarbg|nhd|mteam|mteampt|btbtt|wiki|chd|chdbits|frds|cmct|hds|wds|ade|dream|pter|hhweb|audiences|qun\d+|gnb|ourbits|usas|usa)\b",
    r"(?i)\b(?:mp4|mkv|avi|ts|m2ts|iso)\b",
    r"sup字幕|内封精修|特效sup",
)

_NOISE_ONLY_TITLES = {
    "高清",
    "高清资源",
    "高清剧集",
    "高清影视",
    "资源",
    "资源站",
    "电影",
    "剧集",
    "影视",
    "更新",
    "全集",
    "完结",
    "合集",
    "蓝光",
    "字幕",
    "中字",
    "广告",
    "分享",
    "频道",
}


def contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def is_noisy_display_title(title: str) -> bool:
    """判断标题是否仍像资源站广告/噪音，不宜用作归档片名。"""
    text = str(title or "").strip(" ._-")
    if not text:
        return True
    if text in _NOISE_ONLY_TITLES:
        return True
    if AD_SITE_RE.fullmatch(text):
        return True
    if len(text) <= 1:
        return True
    # 残留括号广告或明显画质尾巴
    if re.search(r"[【\[\]]", text):
        return True
    if TECH_CUT_RE.search(text) and contains_cjk(text):
        # 片名后仍粘着 4K/HDR 等
        head = TECH_CUT_RE.split(text, maxsplit=1)[0].strip(" ._-")
        if head and head != text:
            return True
    return False


def clean_archive_display_title(raw: str) -> str:
    """清洗归档展示片名：去广告括号、分类前缀、画质/中文噪音尾巴。"""
    text = str(raw or "").strip()
    if not text:
        return ""

    text = _LEADING_EMOJI_RE.sub("", text).strip()
    text = _YEAR_SUFFIX_RE.sub("", text).strip(" ._-")
    # 去掉全部【广告】/[tag]/(说明) 组，避免「【高清资源】片名」误取广告词
    text = _BRACKET_GROUP_RE.sub(" ", text)
    text = _CATEGORY_PREFIX_RE.sub("", text).strip(" ._-")

    # 截断画质 / 中文资源噪音尾巴（片名4K、片名杜比视界、更新至8集）
    cut = len(text)
    tech_match = TECH_CUT_RE.search(text)
    if tech_match and tech_match.start() > 0:
        cut = min(cut, tech_match.start())
    zh_match = ZH_NOISE_CUT_RE.search(text)
    if zh_match and zh_match.start() > 0 and text[: zh_match.start()].strip(" ._-" ):
        cut = min(cut, zh_match.start())
    text = text[:cut]

    for pattern in IGNORE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    text = text.replace(".", " ").replace("_", " ").replace("-", " ")
    # 去掉夹在中间的年份，避免「片名 2025」进入归档名（年份由模板 {year} 单独提供）
    text = re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", " ", text)
    text = re.sub(r"[<>:\"/\\|?*]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ._-")

    if not text:
        return ""

    if contains_cjk(text):
        # 优先取最长的中日韩块，避免短广告词抢占
        blocks = re.findall(
            r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af0-9A-Za-z·]{2,}", text
        )
        cjk_blocks = [b for b in blocks if contains_cjk(b) and not is_noisy_display_title(b)]
        if cjk_blocks:
            return max(cjk_blocks, key=len).strip(" ._-")
        match = re.search(
            r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af0-9A-Za-z·]+", text
        )
        if match:
            candidate = match.group(0).strip(" ._-")
            if not is_noisy_display_title(candidate):
                return candidate

    # 英文片名：保留字母数字空格
    ascii_title = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9' ]+", " ", text)).strip()
    return ascii_title
