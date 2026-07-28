from app.utils.cloud_filename import (
    is_cloud_duplicate_variant,
    normalize_archive_basename,
    strip_cloud_duplicate_suffix,
)


class TestCloudFilename:
    def test_strip_parenthesis_suffix(self) -> None:
        assert (
            strip_cloud_duplicate_suffix("权力的游戏前传 S01E01 (1).mkv")
            == "权力的游戏前传 S01E01.mkv"
        )
        assert strip_cloud_duplicate_suffix("Show.S01E01(2).mp4") == "Show.S01E01.mp4"

    def test_strip_space_suffix(self) -> None:
        assert strip_cloud_duplicate_suffix("Movie Name 3.mkv") == "Movie Name.mkv"

    def test_normalize_for_compare(self) -> None:
        left = normalize_archive_basename("Show S01E01 (1).MKV")
        right = normalize_archive_basename("show s01e01.mkv")
        assert left == right

    def test_is_cloud_duplicate_variant(self) -> None:
        assert is_cloud_duplicate_variant(
            "House.of.Dragon.S01E01.mkv",
            "House.of.Dragon.S01E01 (1).mkv",
        )
