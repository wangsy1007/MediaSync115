"""
设置 API 测试
"""
import asyncio

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

    def test_check_tmdb_credentials_with_form_key(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试使用表单 API Key 检测 TMDB 连接"""
        import app.api.settings as settings_api

        async def fake_check(
            *,
            api_key: str,
            base_url: str | None = None,
            language: str | None = None,
            region: str | None = None,
        ) -> dict:
            assert api_key == "test-key"
            assert language == "zh-CN"
            assert region == "CN"
            return {
                "images_configured": True,
                "change_keys_count": 3,
                "configuration": {"images": {"base_url": "https://image.tmdb.org/t/p/"}},
            }

        monkeypatch.setattr(
            settings_api.tmdb_service,
            "check_connection_with_config",
            fake_check,
        )
        response = client.get(
            "/api/settings/tmdb/check",
            params={
                "tmdb_api_key": "test-key",
                "tmdb_language": "zh-CN",
                "tmdb_region": "CN",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert "可用" in data["message"]
        assert data["images_configured"] is True
        assert data["change_keys_count"] == 3

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

    @pytest.mark.asyncio
    async def test_stop_tg_index_job_keeps_single_flight_until_cancelled(self) -> None:
        """TG 停止请求应先进入停止中，任务退出后再变为已停止，期间不能重复启动。"""
        from app.services.tg_sync_service import TgSyncService

        service = TgSyncService()
        await service._ensure_tables()

        first = await service._create_job(job_type="backfill")
        first_job_id = str(first["job_id"])

        class FakeTask:
            def __init__(self) -> None:
                self.cancelled_with = None

            def done(self) -> bool:
                return False

            def cancel(self, message: str | None = None) -> None:
                self.cancelled_with = message

        fake_task = FakeTask()
        service._job_tasks[first_job_id] = fake_task
        await service._set_job(first_job_id, status="running", message="执行中")

        stop_result = await service.stop_job("backfill")
        assert stop_result["success"] is True
        assert stop_result["job"]["status"] == "cancelling"
        assert fake_task.cancelled_with == "TG 全量回填停止中"

        second = await service._create_job(job_type="backfill")
        assert second["already_running"] is True
        assert second["status"] == "cancelling"

        await service._mark_job_cancelled(first_job_id, "任务已停止")
        cancelled_job = await service.get_job(first_job_id)
        assert cancelled_job["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_tg_index_status_auto_recovers_stale_cancelling_job(self) -> None:
        """TG 索引状态查询应自动收口没有活跃 task 的停止中任务。"""
        from app.services.tg_sync_service import TgSyncService

        service = TgSyncService()
        await service._ensure_tables()

        job = await service._create_job(job_type="incremental")
        job_id = str(job["job_id"])
        await service._set_job(job_id, status="cancelling", message="TG 增量同步停止中")

        status = await service.get_status()
        running_jobs = status.get("running_jobs") or []
        latest_jobs = status.get("latest_jobs") or []

        assert all(str(item.get("job_id") or "") != job_id for item in running_jobs)
        recovered = next(item for item in latest_jobs if str(item.get("job_id") or "") == job_id)
        assert recovered["status"] == "cancelled"
        assert recovered["message"] == "任务已停止"

    @pytest.mark.asyncio
    async def test_stop_tg_rebuild_job_is_supported(self) -> None:
        """TG 索引重建任务应支持停止。"""
        from app.services.tg_sync_service import TgSyncService

        service = TgSyncService()
        await service._ensure_tables()

        job = await service._create_job(job_type="backfill_rebuild")
        job_id = str(job["job_id"])

        class FakeTask:
            def __init__(self) -> None:
                self.cancelled_with = None

            def done(self) -> bool:
                return False

            def cancel(self, message: str | None = None) -> None:
                self.cancelled_with = message

        fake_task = FakeTask()
        service._job_tasks[job_id] = fake_task
        await service._set_job(job_id, status="running", message="执行中")

        stop_result = await service.stop_job("backfill_rebuild")
        assert stop_result["success"] is True
        assert stop_result["job"]["status"] == "cancelling"
        assert fake_task.cancelled_with == "TG 索引重建停止中"

    def test_stop_tg_index_job_requires_auth(self, client: TestClient) -> None:
        """停止 TG 索引任务接口已注册，未登录时应走统一鉴权。"""
        response = client.post("/api/settings/tg/index/stop", json={"job_type": "backfill"})
        assert response.status_code == 401
