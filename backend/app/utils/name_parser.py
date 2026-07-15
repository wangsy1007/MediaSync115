import re
from typing import Optional, TypedDict


class EpisodeCoverage(TypedDict):
    season: int
    episode_start: int
    episode_end: int


class NameParser:
    @staticmethod
    def parse_episode(filename: str) -> Optional[tuple[int, int]]:
        coverage = NameParser.parse_episode_coverage(filename)
        if not coverage:
            return None
        return coverage["season"], coverage["episode_start"]

    @staticmethod
    def parse_episode_coverage(filename: str) -> Optional[EpisodeCoverage]:
        """
        从文件名解析季号与集号范围。
        单集返回 episode_start == episode_end；合集如 S01E01-E10 返回范围。
        """
        clean_name = re.sub(r"\[.*?\]", "", filename)
        clean_name = re.sub(r"\{.*?\}", "", clean_name)

        range_patterns = (
            r"S(\d+)\s*E(\d+)\s*[-~_至到]+\s*E?(\d+)",
            r"第(\d+)季[\s._-]*第(\d+)[-~_至到]+(\d+)[集话話]",
            r"第(\d+)季[\s._-]*第(\d+)[集话話][-~_至到]+第(\d+)[集话話]",
        )
        for pattern in range_patterns:
            match = re.search(pattern, clean_name, re.IGNORECASE)
            if not match:
                continue
            season = int(match.group(1))
            episode_start = int(match.group(2))
            episode_end = int(match.group(3))
            if episode_start > episode_end:
                episode_start, episode_end = episode_end, episode_start
            return {
                "season": season,
                "episode_start": episode_start,
                "episode_end": episode_end,
            }

        # 匹配 S01E01 或 s1e01 或 S1E1 或 s01 e01 (忽略大小写)
        match = re.search(r"S(\d+)\s*E(\d+)", clean_name, re.IGNORECASE)
        if match:
            episode = int(match.group(2))
            return {
                "season": int(match.group(1)),
                "episode_start": episode,
                "episode_end": episode,
            }

        # 匹配 第1季 第2集 或 第一季 第二集
        match = re.search(r"第(\d+)季.*?第(\d+)集", clean_name)
        if match:
            episode = int(match.group(2))
            return {
                "season": int(match.group(1)),
                "episode_start": episode,
                "episode_end": episode,
            }

        # 只匹配 第x集
        match = re.search(r"第(\d+)集", clean_name)
        if match:
            episode = int(match.group(1))
            return {
                "season": 1,
                "episode_start": episode,
                "episode_end": episode,
            }

        # 匹配 EP01 或 E01
        match = re.search(r"EP?(\d+)", clean_name, re.IGNORECASE)
        if match:
            episode = int(match.group(1))
            return {
                "season": 1,
                "episode_start": episode,
                "episode_end": episode,
            }

        # 匹配 - 01 或 01 (常用于动漫，如 繁花 01.mp4)
        match = re.search(
            r"(?:[-_ ]|^\s*)(\d{1,4})\s*(?:\.mp4|\.mkv|\.avi|\.ts|\.rmvb|\.flv)",
            clean_name,
            re.IGNORECASE,
        )
        if match:
            episode = int(match.group(1))
            return {
                "season": 1,
                "episode_start": episode,
                "episode_end": episode,
            }

        return None

    @staticmethod
    def iter_episode_keys(coverage: EpisodeCoverage) -> list[tuple[int, int]]:
        season = int(coverage["season"])
        start = int(coverage["episode_start"])
        end = int(coverage["episode_end"])
        if start > end:
            start, end = end, start
        return [(season, episode) for episode in range(start, end + 1)]

    @staticmethod
    def coverage_covers_episode(
        coverage: EpisodeCoverage, season: int, episode: int
    ) -> bool:
        if int(coverage["season"]) != int(season):
            return False
        start = int(coverage["episode_start"])
        end = int(coverage["episode_end"])
        if start > end:
            start, end = end, start
        return start <= int(episode) <= end


name_parser = NameParser()
