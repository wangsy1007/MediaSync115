"""
订阅 API 测试
"""
import pytest
from fastapi.testclient import TestClient


class TestSubscriptions:
    """订阅功能测试类"""

    def test_list_subscriptions(self, client: TestClient) -> None:
        """测试获取订阅列表"""
        response = client.get("/api/subscriptions")
        assert response.status_code == 200
        data = response.json()
        if isinstance(data, dict):
            assert "items" in data
            assert isinstance(data["items"], list)
        else:
            assert isinstance(data, list)

    def test_list_subscriptions_exclude_transferred_success(
        self, client: TestClient
    ) -> None:
        """已成功转存的订阅可被 exclude_transferred_success 排除。"""
        payload = {
            "title": "Transferred TV Show",
            "media_type": "tv",
            "tmdb_id": 880001,
            "auto_download": False,
        }
        create_resp = client.post("/api/subscriptions", json=payload)
        assert create_resp.status_code == 200
        created = create_resp.json()
        sub_id = created["id"]

        try:
            from app.core.database import async_session_maker
            from app.models.models import DownloadRecord, MediaStatus

            async def _add_completed_download() -> None:
                async with async_session_maker() as db:
                    db.add(
                        DownloadRecord(
                            subscription_id=sub_id,
                            resource_name="test.mkv",
                            resource_url="https://example.com/test",
                            resource_type="115",
                            status=MediaStatus.COMPLETED,
                        )
                    )
                    await db.commit()

            import asyncio

            asyncio.run(_add_completed_download())

            all_resp = client.get(
                "/api/subscriptions",
                params={"is_active": True},
            )
            assert all_resp.status_code == 200
            all_items = all_resp.json().get("items", all_resp.json())
            assert any(item["id"] == sub_id for item in all_items)

            filtered_resp = client.get(
                "/api/subscriptions",
                params={"is_active": True, "exclude_transferred_success": True},
            )
            assert filtered_resp.status_code == 200
            filtered_items = filtered_resp.json().get("items", filtered_resp.json())
            assert not any(item["id"] == sub_id for item in filtered_items)
        finally:
            client.delete(f"/api/subscriptions/{sub_id}")

    def test_create_subscription_validation(self, client: TestClient) -> None:
        """测试创建订阅参数验证"""
        # 缺少必填参数
        response = client.post("/api/subscriptions", json={})
        assert response.status_code == 422

    def test_create_and_delete_subscription(self, client: TestClient) -> None:
        """测试创建和删除订阅"""
        # 创建订阅
        payload = {
            "title": "Test Movie",
            "media_type": "movie",
            "tmdb_id": 12345,
            "auto_download": False
        }
        response = client.post("/api/subscriptions", json=payload)
        assert response.status_code == 200
        created = response.json()
        assert created["title"] == "Test Movie"

        # 删除订阅
        sub_id = created["id"]
        response = client.delete(f"/api/subscriptions/{sub_id}")
        assert response.status_code == 200

    def test_get_subscription_detail(self, client: TestClient) -> None:
        """测试获取订阅详情"""
        # 先创建订阅
        payload = {
            "title": "Test TV Show",
            "media_type": "tv",
            "tmdb_id": 67890,
            "auto_download": False
        }
        response = client.post("/api/subscriptions", json=payload)
        created = response.json()
        sub_id = created["id"]

        # 获取详情
        response = client.get(f"/api/subscriptions/{sub_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sub_id

        # 清理
        client.delete(f"/api/subscriptions/{sub_id}")
