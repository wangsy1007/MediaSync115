"""事件类型定义"""

from enum import Enum


class EventType(str, Enum):
    """分析事件类型"""

    # API 请求事件
    API_REQUEST = "api_request"

    # 搜索事件
    SEARCH_KEYWORD = "search_keyword"
    SEARCH_RESOURCE = "search_resource"

    # 订阅事件
    SUBSCRIPTION_CREATE = "subscription_create"
    SUBSCRIPTION_DELETE = "subscription_delete"
    SUBSCRIPTION_RUN = "subscription_run"

    # 转存事件
    TRANSFER_START = "transfer_start"
    TRANSFER_SUCCESS = "transfer_success"
    TRANSFER_FAILED = "transfer_failed"

    # 资源获取事件
    RESOURCE_FETCH_START = "resource_fetch_start"
    RESOURCE_FETCH_SUCCESS = "resource_fetch_success"
    RESOURCE_FETCH_FAILED = "resource_fetch_failed"

    # 来源尝试事件
    SOURCE_ATTEMPT = "source_attempt"
