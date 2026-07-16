"""订阅转存渠道启用开关测试"""

from app.services.runtime_settings_service import RuntimeSettingsService


class TestSubscriptionResourceEnabled:
    def test_get_active_priority_filters_disabled_sources(self) -> None:
        service = RuntimeSettingsService()
        service._data["subscription_resource_priority"] = ["hdhive", "pansou", "tg"]
        service._data["subscription_resource_enabled"] = {
            "hdhive": True,
            "pansou": False,
            "tg": True,
        }

        assert service.get_active_subscription_resource_priority() == [
            "hdhive",
            "tg",
        ]

    def test_update_bulk_normalizes_enabled_map(self) -> None:
        service = RuntimeSettingsService()
        service.update_bulk(
            {
                "subscription_resource_enabled": {
                    "hdhive": False,
                    "pansou": "yes",
                    "tg": 0,
                    "invalid": True,
                }
            }
        )

        enabled = service.get_subscription_resource_enabled()
        assert enabled == {
            "hdhive": False,
            "juying": False,
            "pansou": True,
            "tg": False,
        }
