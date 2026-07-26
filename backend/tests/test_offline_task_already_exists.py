"""115 离线任务已存在（errcode 10008）应按成功处理。"""

from __future__ import annotations

import pytest

from app.services.explore_action_queue_service import ExploreActionQueueService
from app.services.pan115_service import Pan115Service


class TestOfflineTaskAlreadyExists:
    def test_extract_payload_from_dict_args(self) -> None:
        exc = Exception(
            {
                "data": {
                    "state": False,
                    "error_msg": "任务已存在，请勿重复添加该地址",
                    "errcode": 10008,
                    "info_hash": "333a7d96fbdd2323858623dafea9126e",
                },
                "errcode": 10008,
                "error_msg": "任务已存在，请勿重复添加该地址",
                "state": False,
            }
        )
        payload = Pan115Service._extract_offline_already_exists_payload(exc)
        assert payload is not None
        assert payload["already_exists"] is True
        assert payload["state"] is True
        assert payload["info_hash"] == "333a7d96fbdd2323858623dafea9126e"

    def test_extract_payload_from_text(self) -> None:
        exc = RuntimeError(
            "[Errno 5] {'errcode': 10008, 'error_msg': '任务已存在，请勿重复添加该地址', "
            "'info_hash': 'AABBCCDDEEFF00112233445566778899'}"
        )
        payload = Pan115Service._extract_offline_already_exists_payload(exc)
        assert payload is not None
        assert payload["info_hash"] == "AABBCCDDEEFF00112233445566778899"

    def test_non_duplicate_error_returns_none(self) -> None:
        exc = RuntimeError("空间不足")
        assert Pan115Service._extract_offline_already_exists_payload(exc) is None

    @pytest.mark.asyncio
    async def test_offline_task_add_treats_10008_as_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = Pan115Service.__new__(Pan115Service)

        async def _raise(*_args, **_kwargs):
            raise Exception(
                {
                    "data": {
                        "state": False,
                        "error_msg": "任务已存在，请勿重复添加该地址",
                        "errcode": 10008,
                        "info_hash": "abc123abc123abc123abc123abc123ab",
                    },
                    "errcode": 10008,
                }
            )

        monkeypatch.setattr(service, "_async_call", _raise)
        result = await service.offline_task_add(
            "ed2k://|file|demo.mp4|1|333A7D96FBDD2323858623DAFEA9126E|/",
            wp_path_id="1",
        )
        assert result["already_exists"] is True
        assert result["state"] is True
        assert result["info_hash"] == "abc123abc123abc123abc123abc123ab"


class TestExploreAttemptErrorSummary:
    def test_unsavable_hint(self) -> None:
        summary = ExploreActionQueueService._build_attempt_error_summary(
            [
                {"source": "tg", "status": "empty"},
                {
                    "source": "hdhive",
                    "status": "empty",
                    "error": "资源已命中但未获取可转存链接",
                    "count": 0,
                },
            ]
        )
        assert "已搜到资源但无可转存链接" in summary
        assert "hdhive" in summary
