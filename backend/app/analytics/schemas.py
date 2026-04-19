"""消息格式定义"""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class AnalyticsEvent(BaseModel):
    """分析事件基础模型"""

    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    trace_id: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class APIRequestEvent(AnalyticsEvent):
    """API 请求事件"""

    event_type: str = "api_request"
    method: str = ""
    path: str = ""
    module: str = ""
    status_code: int = 0
    duration_ms: int = 0


class SearchKeywordEvent(AnalyticsEvent):
    """搜索关键词事件"""

    event_type: str = "search_keyword"
    keyword: str = ""
    source: str = ""  # tmdb/douban/local
    result_count: int = 0


class SubscriptionEvent(AnalyticsEvent):
    """订阅事件"""

    event_type: str = "subscription_create"
    subscription_id: int = 0
    title: str = ""
    media_type: str = ""  # movie/tv
    tmdb_id: int | None = None
    year: str | None = None
    rating: float | None = None


class TransferEvent(AnalyticsEvent):
    """转存事件"""

    event_type: str = "transfer_start"
    subscription_id: int = 0
    title: str = ""
    source: str = ""  # hdhive/pansou/tg/offline
    resource_name: str = ""
    status: str = ""  # success/failed
    error_type: str | None = None
    duration_ms: int = 0


class SourceAttemptEvent(AnalyticsEvent):
    """来源尝试事件"""

    event_type: str = "source_attempt"
    subscription_id: int = 0
    title: str = ""
    source: str = ""
    status: str = ""  # success/empty/failed
    resource_count: int = 0
    duration_ms: int = 0
