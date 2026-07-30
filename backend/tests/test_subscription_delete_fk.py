"""订阅删除需先清理缺集缓存，避免 FK 导致无缺集订阅删不掉。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.services.subscription_service import SubscriptionService


@pytest.mark.asyncio
async def test_delete_subscription_removes_missing_cache_before_parent() -> None:
    service = SubscriptionService()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())

    await service._delete_subscription_with_records(db, 42)

    assert db.execute.await_count == 3
    # 三次 delete：cache -> downloads -> subscription
    sql_texts = []
    for args in db.execute.await_args_list:
        statement = args.args[0]
        sql_texts.append(str(statement))

    assert "subscription_tv_missing_cache" in sql_texts[0]
    assert "download_records" in sql_texts[1]
    assert "subscriptions" in sql_texts[2]
