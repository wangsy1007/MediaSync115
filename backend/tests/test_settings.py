"""
设置 API 测试
"""
import pytest
from fastapi.testclient import TestClient


class TestSettings:
    """设置功能测试类"""

    def test_get_runtime_settings(self, client: TestClient) -> None:
        """测试获取运行时设置"""
        response = client.get("/api/settings/runtime")
        assert response.status_code == 200
        data = response.json()
        # 验证关键配置字段存在
        assert isinstance(data, dict)

    def test_update_runtime_settings(self, client: TestClient) -> None:
        """测试更新运行时设置"""
        # 获取当前设置
        response = client.get("/api/settings/runtime")
        original = response.json()

        # 更新设置
        payload = {
            "tmdb_language": "zh-CN",
            "tmdb_region": "CN"
        }
        response = client.put("/api/settings/runtime", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_health_check_all(self, client: TestClient) -> None:
        """测试所有服务健康检查"""
        response = client.get("/api/settings/health/all")
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "valid_count" in data
        assert "total_count" in data

    def test_check_tmdb_credentials(self, client: TestClient) -> None:
        """测试 TMDB 凭证检查"""
        response = client.get("/api/settings/tmdb/check")
        assert response.status_code == 200
        data = response.json()
        assert "valid" in data
        assert "message" in data

    def test_proxy_config(self, client: TestClient) -> None:
        """测试代理配置"""
        response = client.get("/api/settings/proxy")
        assert response.status_code == 200
        data = response.json()
        assert "has_proxy" in data

    def test_update_tg_bot_runtime_only(self, client: TestClient) -> None:
        """仅更新 TG Bot 配置时不应阻塞过久"""
        response = client.put(
            "/api/settings/runtime",
            json={
                "tg_bot_enabled": False,
                "tg_bot_allowed_users": [],
                "tg_bot_notify_chat_ids": [],
            },
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_restart_tg_bot_returns_immediately(self, client: TestClient) -> None:
        """TG Bot 重启接口应立即返回并接受后台任务"""
        response = client.post("/api/settings/tg-bot/restart")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data.get("accepted") is True
