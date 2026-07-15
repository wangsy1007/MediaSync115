from app.utils.name_parser import name_parser


class TestEpisodeCoverageParser:
    def test_parse_single_episode(self) -> None:
        coverage = name_parser.parse_episode_coverage("Show.S01E02.1080p.mkv")
        assert coverage == {
            "season": 1,
            "episode_start": 2,
            "episode_end": 2,
        }

    def test_parse_episode_range(self) -> None:
        coverage = name_parser.parse_episode_coverage("Show.S01E01-E10.2160p.mkv")
        assert coverage == {
            "season": 1,
            "episode_start": 1,
            "episode_end": 10,
        }

    def test_parse_episode_range_with_e_prefix(self) -> None:
        coverage = name_parser.parse_episode_coverage("爱情有烟火 S01E01-E11 4K WEB-DL.mkv")
        assert coverage == {
            "season": 1,
            "episode_start": 1,
            "episode_end": 11,
        }

    def test_iter_episode_keys(self) -> None:
        keys = name_parser.iter_episode_keys(
            {"season": 1, "episode_start": 1, "episode_end": 3}
        )
        assert keys == [(1, 1), (1, 2), (1, 3)]
