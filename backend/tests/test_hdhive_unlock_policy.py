import asyncio

from app.services.subscription_service import SubscriptionService


class TestHDHiveUnlockPolicy:
    def test_prepare_hdhive_locked_resources_stops_after_first_success(self) -> None:
        service = SubscriptionService()
        unlock_calls: list[str] = []

        async def fake_unlock(slug: str) -> dict:
            unlock_calls.append(slug)
            return {
                "success": True,
                "message": "资源解锁成功",
                "share_link": f"https://115.com/s/{slug}?password=abcd",
            }

        from app.services import subscription_service as subscription_service_module

        original_unlock = subscription_service_module.hdhive_service.unlock_resource
        subscription_service_module.hdhive_service.unlock_resource = fake_unlock  # type: ignore[method-assign]
        try:
            resources = [
                {
                    "source_service": "hdhive",
                    "slug": "slug-a",
                    "hdhive_locked": True,
                    "unlock_points": 0,
                    "resource_name": "资源 A",
                },
                {
                    "source_service": "hdhive",
                    "slug": "slug-b",
                    "hdhive_locked": True,
                    "unlock_points": 0,
                    "resource_name": "资源 B",
                },
                {
                    "source_service": "hdhive",
                    "slug": "slug-c",
                    "hdhive_locked": True,
                    "unlock_points": 0,
                    "resource_name": "资源 C",
                },
            ]
            context = {
                "enabled": True,
                "max_points_per_item": 10,
                "budget_total": 30,
                "budget_left": 30,
                "threshold_inclusive": True,
                "max_unlocks_per_run": 1,
                "consecutive_failed_limit": 3,
                "consecutive_failed_count": 0,
                "request_interval_seconds": 0,
                "stopped_by_circuit": False,
                "stopped_reason": "",
                "stats": {
                    "attempted": 0,
                    "success": 0,
                    "failed": 0,
                    "skipped": 0,
                    "points_spent": 0,
                },
            }
            traces: list[dict] = []

            result = asyncio.run(
                service._prepare_hdhive_locked_resources(resources, context, traces)
            )
        finally:
            subscription_service_module.hdhive_service.unlock_resource = original_unlock  # type: ignore[method-assign]

        assert unlock_calls == ["slug-a"]
        assert service._extract_resource_url(result[0]) == (
            "https://115.com/s/slug-a?password=abcd"
        )
        assert not service._extract_resource_url(result[1])
        assert any(
            trace.get("step") == "hdhive_unlock_stop"
            and trace.get("payload", {}).get("reason") == "max_unlocks_reached"
            for trace in traces
        )
