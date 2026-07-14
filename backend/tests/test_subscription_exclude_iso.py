"""订阅转存跳过 ISO/IMG 原盘测试。"""

from app.utils.resource_tags import (
    filter_iso_disc_resources,
    is_iso_disc_filename,
    is_iso_disc_resource,
)


class TestIsoDiscDetection:
    def test_iso_filename(self) -> None:
        assert is_iso_disc_filename("Movie.2024.iso")
        assert is_iso_disc_filename("disc.IMG")
        assert not is_iso_disc_filename("Movie.2024.mkv")

    def test_iso_resource_by_title(self) -> None:
        assert is_iso_disc_resource(
            {"title": "十二生肖 Chinese Zodiac 2012 .iso", "resource_name": "pack"}
        )
        assert is_iso_disc_resource({"resource_name": "蓝光原盘/movie.iso"})
        assert not is_iso_disc_resource(
            {"title": "1080P蓝光原盘[港版原盘 国粤双语]", "resource_name": "remux"}
        )

    def test_bdmv_resource(self) -> None:
        assert is_iso_disc_resource({"title": "Avatar /BDMV/"})


class TestFilterIsoDiscResources:
    def test_filter_enabled(self) -> None:
        resources = [
            {"title": "A.mkv"},
            {"title": "B.iso"},
            {"title": "C /BDMV/"},
        ]
        kept, excluded = filter_iso_disc_resources(resources, enabled=True)
        assert excluded == 2
        assert len(kept) == 1
        assert kept[0]["title"] == "A.mkv"

    def test_filter_disabled(self) -> None:
        resources = [{"title": "B.iso"}]
        kept, excluded = filter_iso_disc_resources(resources, enabled=False)
        assert excluded == 0
        assert len(kept) == 1
