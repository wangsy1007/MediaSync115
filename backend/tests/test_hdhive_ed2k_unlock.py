from app.services.subscription_service import SubscriptionService


class TestHDHiveEd2kUnlockRouting:
    def test_extract_resource_url_rejects_ed2k(self) -> None:
        service = SubscriptionService()
        assert service._extract_resource_url(
            {"share_link": "ed2k://|file|demo.mp4|1|ABCDEF|/"}
        ) == ""
        assert service._extract_resource_url(
            {"share_link": "https://115cdn.com/s/abc123?password=q045"}
        ) == "https://115.com/s/abc123?password=q045"

    def test_extract_offline_url_from_share_link_field(self) -> None:
        service = SubscriptionService()
        ed2k = "ed2k://|file|demo.mp4|1|ABCDEF|/"
        assert service._extract_offline_url({"share_link": ed2k}) == ed2k
        assert service._extract_offline_url({"ed2k": ed2k}) == ed2k
        assert service._item_has_transferable_url(
            {"share_link": ed2k}, offline_enabled=True
        )
        assert not service._item_has_transferable_url(
            {"share_link": ed2k}, offline_enabled=False
        )

    def test_determine_resource_type_ed2k(self) -> None:
        assert (
            SubscriptionService._determine_resource_type(
                "ed2k://|file|demo.mp4|1|ABCDEF|/"
            )
            == "ed2k"
        )
