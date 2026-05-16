"""探索「更多」页首屏 TMDB 同步解析上限测试"""

from app.api.search import _douban_explore_sync_prime_limit


class TestExploreSectionPrimeLimit:
    def test_first_screen_caps_sync_prime(self) -> None:
        assert _douban_explore_sync_prime_limit(30, 0) == 12

    def test_pagination_caps_sync_prime(self) -> None:
        assert _douban_explore_sync_prime_limit(30, 30) == 18
