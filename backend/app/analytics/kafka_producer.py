"""Kafka 生产者"""

import json
import logging
from datetime import datetime
from typing import Any

from kafka import KafkaProducer
from kafka.errors import KafkaError

logger = logging.getLogger(__name__)


class AnalyticsKafkaProducer:
    """分析数据 Kafka 生产者"""

    # Kafka Topic 映射
    TOPIC_MAPPING = {
        "api_request": "mediasync.api_requests",
        "search_keyword": "mediasync.search_events",
        "search_resource": "mediasync.search_events",
        "subscription_create": "mediasync.subscription_events",
        "subscription_delete": "mediasync.subscription_events",
        "subscription_run": "mediasync.subscription_events",
        "transfer_start": "mediasync.transfer_events",
        "transfer_success": "mediasync.transfer_events",
        "transfer_failed": "mediasync.transfer_events",
        "resource_fetch_start": "mediasync.resource_fetch_events",
        "resource_fetch_success": "mediasync.resource_fetch_events",
        "resource_fetch_failed": "mediasync.resource_fetch_events",
        "source_attempt": "mediasync.resource_fetch_events",
    }

    def __init__(self) -> None:
        self._producer: KafkaProducer | None = None
        self._enabled: bool = False

    def init(self, bootstrap_servers: str | None = None) -> None:
        """初始化 Kafka 生产者"""
        if not bootstrap_servers:
            logger.info("Kafka 未配置，埋点功能禁用")
            self._enabled = False
            return

        try:
            self._producer = KafkaProducer(
                bootstrap_servers=bootstrap_servers.split(","),
                value_serializer=lambda v: json.dumps(
                    v, default=self._json_serializer
                ).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks="all",  # 确保消息不丢失
                retries=3,
                max_in_flight_requests_per_connection=5,
                compression_type="gzip",  # 启用压缩
            )
            self._enabled = True
            logger.info(f"Kafka 生产者初始化成功: {bootstrap_servers}")
        except Exception as e:
            logger.error(f"Kafka 生产者初始化失败: {e}")
            self._enabled = False

    def close(self) -> None:
        """关闭 Kafka 生产者"""
        if self._producer:
            self._producer.flush()
            self._producer.close()
            logger.info("Kafka 生产者已关闭")

    def send(
        self, event_type: str, data: dict[str, Any], key: str | None = None
    ) -> None:
        """发送事件到 Kafka"""
        if not self._enabled or not self._producer:
            return

        topic = self.TOPIC_MAPPING.get(event_type)
        if not topic:
            logger.warning(f"未知事件类型: {event_type}")
            return

        # 构建消息
        message = {
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data,
        }

        try:
            future = self._producer.send(
                topic,
                value=message,
                key=key,
            )
            # 异步发送，不阻塞主线程
            future.add_callback(self._on_send_success)
            future.add_errback(self._on_send_error)
        except KafkaError as e:
            logger.error(f"Kafka 发送失败: {e}")

    def _on_send_success(self, record_metadata: Any) -> None:
        """发送成功回调"""
        logger.debug(
            f"Kafka 消息发送成功: topic={record_metadata.topic}, "
            f"partition={record_metadata.partition}, offset={record_metadata.offset}"
        )

    def _on_send_error(self, exc: Exception) -> None:
        """发送失败回调"""
        logger.error(f"Kafka 消息发送失败: {exc}")

    @staticmethod
    def _json_serializer(obj: Any) -> str:
        """JSON 序列化器"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# 全局实例
kafka_producer = AnalyticsKafkaProducer()
