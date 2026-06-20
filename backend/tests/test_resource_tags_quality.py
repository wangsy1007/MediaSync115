"""资源画质偏好排序与过滤测试。"""

from app.utils.resource_tags import filter_and_sort_by_quality


class TestResourceQualityPreference:
    """画质偏好应影响排序，而非剔除未匹配资源。"""

    def test_preference_sorts_without_dropping_non_matching(self) -> None:
        resources = [
            {"resource_name": "Movie.720p.WEB-DL.H264"},
            {"resource_name": "Movie.1080p.WEB-DL.HEVC.HDR10"},
        ]

        result = filter_and_sort_by_quality(
            resources,
            preferred_resolutions=["1080p", "4K"],
            preferred_formats=["HDR10", "HEVC"],
        )

        assert len(result) == 2
        assert "1080p" in result[0]["resource_name"]

    def test_exclude_labels_still_filter_resources(self) -> None:
        resources = [
            {"resource_name": "Movie.1080p.WEB-DL.HDR10"},
            {"resource_name": "Movie.CAM.1080p"},
        ]

        result = filter_and_sort_by_quality(
            resources,
            preferred_resolutions=["1080p"],
            exclude_labels=["CAM"],
        )

        assert len(result) == 1
        assert "CAM" not in result[0]["resource_name"]

    def test_size_range_still_filter_resources(self) -> None:
        resources = [
            {"resource_name": "Movie.1080p.WEB-DL 2.5GB"},
            {"resource_name": "Movie.1080p.WEB-DL 8.0GB"},
        ]

        result = filter_and_sort_by_quality(
            resources,
            preferred_resolutions=["1080p"],
            min_size_gb=3.0,
            max_size_gb=6.0,
        )

        assert len(result) == 1
        assert "2.5GB" in result[0]["resource_name"]
