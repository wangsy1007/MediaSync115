import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable
from uuid import uuid4

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    DownloadRecord,
    ExecutionStatus,
    MediaStatus,
    MediaType,
    Subscription,
    SubscriptionExecutionLog,
    SubscriptionStepLog,
)
from app.api.search import (
    _normalize_pansou_pan115_list,
    _search_pansou_pan115_resources,
)
from app.services.butailing_service import butailing_service
from app.services.media_postprocess_service import media_postprocess_service
from app.services.operation_log_service import operation_log_service
from app.services.emby_service import emby_service
from app.services.feiniu_service import feiniu_service
from app.services.feiniu_sync_index_service import feiniu_sync_index_service
from app.services.hdhive_service import hdhive_service
from app.services.pan115_service import Pan115Service
from app.services.pansou_service import pansou_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.seedhub_service import seedhub_service
from app.services.tg_service import tg_service
from app.services.transfer_guard_service import transfer_guard_service
from app.services.tv_missing_service import tv_missing_service
from app.utils.resource_tags import sort_by_preference, filter_and_sort_by_quality
from app.utils.name_parser import name_parser

logger = logging.getLogger(__name__)


class SubscriptionService:
    async def run_channel_check(
        self,
        db: AsyncSession,
        channel: str,
        force_auto_download: bool = False,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        normalized_channel = self._normalize_channel(channel)
        run_id = uuid4().hex
        started_at = datetime.utcnow()
        await operation_log_service.log_background_event(
            source_type="background_task",
            module="subscriptions",
            action="subscription.check.start",
            status="info",
            message=f"订阅检查任务启动（频道：{normalized_channel}）",
            trace_id=run_id,
            extra={
                "channel": normalized_channel,
                "force_auto_download": force_auto_download,
            },
        )

        result = {
            "channel": normalized_channel,
            "run_id": run_id,
            "checked_count": 0,
            "processed_count": 0,
            "new_resource_count": 0,
            "failed_count": 0,
            "auto_saved_count": 0,
            "auto_failed_count": 0,
            "auto_new_saved_count": 0,
            "auto_new_failed_count": 0,
            "auto_retry_saved_count": 0,
            "auto_retry_failed_count": 0,
            "resource_checked_count": 0,
            "resource_duplicate_count": 0,
            "hdhive_unlock_attempted_count": 0,
            "hdhive_unlock_success_count": 0,
            "hdhive_unlock_failed_count": 0,
            "hdhive_unlock_skipped_count": 0,
            "hdhive_unlock_points_spent": 0,
            "cleanup_deleted_count": 0,
            "cleanup_movie_deleted_count": 0,
            "cleanup_tv_deleted_count": 0,
            "errors": [],
            "started_at": started_at.isoformat(),
        }
        hdhive_unlock_context = self._build_hdhive_unlock_context()
        source_order = self._resolve_source_order(normalized_channel)

        has_successful_transfer = (
            select(DownloadRecord.id)
            .where(
                DownloadRecord.subscription_id == Subscription.id,
                or_(
                    DownloadRecord.completed_at.is_not(None),
                    DownloadRecord.status.in_(
                        (MediaStatus.COMPLETED, MediaStatus.OFFLINE_COMPLETED)
                    ),
                ),
            )
            .exists()
            .label("has_successful_transfer")
        )
        subs_result = await db.execute(
            select(
                Subscription.id,
                Subscription.tmdb_id,
                Subscription.title,
                Subscription.media_type,
                Subscription.year,
                Subscription.auto_download,
                Subscription.tv_scope,
                Subscription.tv_season_number,
                Subscription.tv_episode_start,
                Subscription.tv_episode_end,
                Subscription.tv_follow_mode,
                Subscription.tv_include_specials,
                Subscription.preferred_resolutions,
                Subscription.preferred_codecs,
                Subscription.preferred_hdr,
                Subscription.preferred_audio,
                Subscription.preferred_subtitles,
                Subscription.exclude_tags,
                Subscription.min_size_gb,
                Subscription.max_size_gb,
                has_successful_transfer,
            )
            .where(
                Subscription.is_active == True,  # noqa: E712
            )
            .order_by(Subscription.id.asc())
        )
        subscriptions = [
            SubscriptionSnapshot(
                id=int(row.id),
                tmdb_id=int(row.tmdb_id) if row.tmdb_id is not None else None,
                title=str(row.title or ""),
                media_type=row.media_type,
                year=str(row.year) if row.year is not None else None,
                auto_download=bool(row.auto_download),
                tv_scope=str(row.tv_scope or "all"),
                tv_season_number=int(row.tv_season_number)
                if row.tv_season_number is not None
                else None,
                tv_episode_start=int(row.tv_episode_start)
                if row.tv_episode_start is not None
                else None,
                tv_episode_end=int(row.tv_episode_end)
                if row.tv_episode_end is not None
                else None,
                tv_follow_mode=str(row.tv_follow_mode or "missing"),
                tv_include_specials=bool(row.tv_include_specials),
                preferred_resolutions=str(row.preferred_resolutions) if row.preferred_resolutions is not None else None,
                preferred_codecs=str(row.preferred_codecs) if row.preferred_codecs is not None else None,
                preferred_hdr=str(row.preferred_hdr) if row.preferred_hdr is not None else None,
                preferred_audio=str(row.preferred_audio) if row.preferred_audio is not None else None,
                preferred_subtitles=str(row.preferred_subtitles) if row.preferred_subtitles is not None else None,
                exclude_tags=str(row.exclude_tags) if row.exclude_tags is not None else None,
                min_size_gb=float(row.min_size_gb) if row.min_size_gb is not None else None,
                max_size_gb=float(row.max_size_gb) if row.max_size_gb is not None else None,
                has_successful_transfer=bool(row.has_successful_transfer),
            )
            for row in subs_result.all()
        ]
        result["checked_count"] = len(subscriptions)
        await self._create_step_log(
            db,
            run_id=run_id,
            channel=normalized_channel,
            step="run_start",
            status="info",
            message=f"开始本轮检查，共有 {len(subscriptions)} 个订阅需要处理",
            payload={
                "checked_count": len(subscriptions),
                "source_order": source_order,
                "scope": {
                    "is_active": True,
                    "exclude_transferred_success": False,
                    "cleanup_enabled": True,
                },
            },
        )
        if progress_callback:
            await progress_callback(
                {
                    "channel": normalized_channel,
                    "status": "running",
                    "processed_count": 0,
                    "checked_count": result["checked_count"],
                    "new_resource_count": 0,
                    "auto_saved_count": 0,
                    "auto_failed_count": 0,
                    "auto_new_saved_count": 0,
                    "auto_new_failed_count": 0,
                    "auto_retry_saved_count": 0,
                    "auto_retry_failed_count": 0,
                    "failed_count": 0,
                    "message": "任务开始执行",
                }
            )

        for sub in subscriptions:
            sub_id = sub.id
            sub_title = sub.title
            try:
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=normalized_channel,
                    subscription_id=sub_id,
                    subscription_title=sub_title,
                    step="subscription_start",
                    status="info",
                    message=f"正在检查「{sub_title}」的资源和入库状态",
                )
                cleanup_before = await self._evaluate_pre_scan_cleanup(
                    db,
                    run_id=run_id,
                    channel=normalized_channel,
                    sub=sub,
                )
                if cleanup_before.get("deleted"):
                    self._apply_cleanup_stats(result, sub.media_type)
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=normalized_channel,
                        subscription_id=sub_id,
                        subscription_title=sub_title,
                        step="subscription_done",
                        status="success",
                        message="订阅已自动清理",
                    )
                    await operation_log_service.log_background_event(
                        source_type="background_task",
                        module="subscriptions",
                        action="subscription.item.done",
                        status="success",
                        message=f"[{sub_title}] 订阅已自动清理（转存完成或已入库）",
                        trace_id=run_id,
                        extra={
                            "subscription_id": sub_id,
                            "title": sub_title,
                            "channel": normalized_channel,
                        },
                    )
                    await db.commit()
                    continue

                tv_missing_snapshot = cleanup_before.get("tv_missing_snapshot")
                (
                    resources,
                    fetch_trace,
                    source_attempt_info,
                ) = await self._fetch_resources(
                    normalized_channel,
                    sub,
                    hdhive_unlock_context,
                    source_order=source_order,
                )
                for trace in fetch_trace:
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=normalized_channel,
                        subscription_id=sub_id,
                        subscription_title=sub_title,
                        step=str(trace.get("step") or "fetch_trace"),
                        status=str(trace.get("status") or "info"),
                        message=str(trace.get("message") or ""),
                        payload=trace.get("payload")
                        if isinstance(trace.get("payload"), dict)
                        else None,
                    )

                # 记录来源尝试链路汇总日志
                source_summary = source_attempt_info.get("summary", "")
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=normalized_channel,
                    subscription_id=sub_id,
                    subscription_title=sub_title,
                    step="fetch_resources_summary",
                    status="success" if resources else "warning",
                    message=f"搜索完成，找到 {len(resources)} 个可用资源" if resources else "本轮未找到新资源",
                    payload={
                        "resource_count": len(resources),
                        "source_order": source_attempt_info.get("source_order", []),
                        "attempts": source_attempt_info.get("attempts", []),
                        "summary": source_summary,
                    },
                )

                # 为每部影视记录资源抓取汇总
                fetch_sources_tried = [
                    t.get("payload", {}).get("source", t.get("step", ""))
                    for t in fetch_trace
                    if t.get("step") == "fetch_source_selected"
                ]
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.item.fetch_done",
                    status="success" if resources else "warning",
                    message=(f"[{sub_title}] {source_summary}"),
                    trace_id=run_id,
                    extra={
                        "subscription_id": sub_id,
                        "title": sub_title,
                        "resource_count": len(resources),
                        "sources_hit": fetch_sources_tried,
                        "source_attempt_summary": source_summary,
                    },
                )
                store_stats = await self._store_new_resources(db, sub_id, resources)
                created_records = store_stats["created_records"]
                duplicate_urls = store_stats["duplicate_urls"]
                result["new_resource_count"] += len(created_records)
                result["resource_checked_count"] += int(store_stats["checked_count"])
                result["resource_duplicate_count"] += int(
                    store_stats["duplicate_count"]
                )
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=normalized_channel,
                    subscription_id=sub_id,
                    subscription_title=sub_title,
                    step="store_new_resources",
                    status="info",
                    message=(
                        f"发现 {len(created_records)} 个新资源待处理"
                        if created_records
                        else "未发现新资源"
                    ),
                    payload={
                        "checked_count": store_stats["checked_count"],
                        "new_count": len(created_records),
                        "duplicate_count": store_stats["duplicate_count"],
                        "invalid_count": store_stats["invalid_count"],
                    },
                )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.item.store_done",
                    status="success" if created_records else "info",
                    message=(
                        f"[{sub_title}] 资源入库：新增 {len(created_records)} 条，"
                        f"重复 {store_stats['duplicate_count']} 条，无效 {store_stats['invalid_count']} 条"
                    ),
                    trace_id=run_id,
                    extra={
                        "subscription_id": sub_id,
                        "title": sub_title,
                        "new": len(created_records),
                        "dup": store_stats["duplicate_count"],
                    },
                )

                should_auto_download = force_auto_download or bool(sub.auto_download)
                if should_auto_download:
                    sub_saved_count = 0
                    sub_failed_transfer_count = 0
                    cleanup_after_auto: dict[str, Any] | None = None
                    retry_records = []
                    if sub.auto_download:
                        retry_records = await self._load_retryable_records(db, sub_id)
                    if force_auto_download and duplicate_urls:
                        duplicate_retry_records = await self._load_force_retry_records(
                            db,
                            sub_id,
                            duplicate_urls,
                        )
                        retry_records = self._merge_records(
                            retry_records, duplicate_retry_records
                        )
                    retry_records = self._exclude_new_records(
                        retry_records, created_records
                    )

                    if created_records:
                        await self._create_step_log(
                            db,
                            run_id=run_id,
                            channel=normalized_channel,
                            subscription_id=sub_id,
                            subscription_title=sub_title,
                            step="auto_transfer_new_start",
                            status="info",
                            message=f"开始转存 {len(created_records)} 个新资源",
                        )
                        await operation_log_service.log_background_event(
                            source_type="background_task",
                            module="subscriptions",
                            action="subscription.item.transfer_new_start",
                            status="info",
                            message=f"[{sub_title}] 开始自动转存新资源 {len(created_records)} 条",
                            trace_id=run_id,
                            extra={
                                "subscription_id": sub_id,
                                "title": sub_title,
                                "count": len(created_records),
                            },
                        )
                        new_auto_stats = await self._auto_save_resources(
                            db,
                            run_id,
                            normalized_channel,
                            sub,
                            created_records,
                            source="new",
                            tv_missing_snapshot=tv_missing_snapshot,
                        )
                        sub_saved_count += int(new_auto_stats.get("saved") or 0)
                        sub_failed_transfer_count += int(
                            new_auto_stats.get("failed") or 0
                        )
                        result["auto_saved_count"] += new_auto_stats["saved"]
                        result["auto_failed_count"] += new_auto_stats["failed"]
                        result["auto_new_saved_count"] += new_auto_stats["saved"]
                        result["auto_new_failed_count"] += new_auto_stats["failed"]
                        if new_auto_stats["errors"]:
                            result["errors"].extend(new_auto_stats["errors"])
                        await self._create_step_log(
                            db,
                            run_id=run_id,
                            channel=normalized_channel,
                            subscription_id=sub_id,
                            subscription_title=sub_title,
                            step="auto_transfer_new_done",
                            status="success"
                            if new_auto_stats["failed"] == 0
                            else "partial",
                            message=(
                                f"新资源转存完成：成功 {new_auto_stats['saved']} 条"
                                + (f"，失败 {new_auto_stats['failed']} 条" if new_auto_stats['failed'] else "")
                            ),
                        )
                        await operation_log_service.log_background_event(
                            source_type="background_task",
                            module="subscriptions",
                            action="subscription.item.transfer_new_done",
                            status="success"
                            if new_auto_stats["failed"] == 0
                            else "warning",
                            message=f"[{sub_title}] 新资源转存完成：成功 {new_auto_stats['saved']} 条，失败 {new_auto_stats['failed']} 条",
                            trace_id=run_id,
                            extra={
                                "subscription_id": sub_id,
                                "title": sub_title,
                                "saved": new_auto_stats["saved"],
                                "failed": new_auto_stats["failed"],
                            },
                        )
                        if new_auto_stats.get("subscription_completed"):
                            cleanup_after_auto = new_auto_stats

                    if retry_records and cleanup_after_auto is None:
                        await self._create_step_log(
                            db,
                            run_id=run_id,
                            channel=normalized_channel,
                            subscription_id=sub_id,
                            subscription_title=sub_title,
                            step="auto_transfer_retry_start",
                            status="info",
                            message=f"开始重试之前失败的 {len(retry_records)} 个资源",
                        )
                        await operation_log_service.log_background_event(
                            source_type="background_task",
                            module="subscriptions",
                            action="subscription.item.transfer_retry_start",
                            status="info",
                            message=f"[{sub_title}] 开始重试历史记录 {len(retry_records)} 条",
                            trace_id=run_id,
                            extra={
                                "subscription_id": sub_id,
                                "title": sub_title,
                                "count": len(retry_records),
                            },
                        )
                        retry_auto_stats = await self._auto_save_resources(
                            db,
                            run_id,
                            normalized_channel,
                            sub,
                            retry_records,
                            source="retry",
                            tv_missing_snapshot=tv_missing_snapshot,
                        )
                        sub_saved_count += int(retry_auto_stats.get("saved") or 0)
                        sub_failed_transfer_count += int(
                            retry_auto_stats.get("failed") or 0
                        )
                        result["auto_saved_count"] += retry_auto_stats["saved"]
                        result["auto_failed_count"] += retry_auto_stats["failed"]
                        result["auto_retry_saved_count"] += retry_auto_stats["saved"]
                        result["auto_retry_failed_count"] += retry_auto_stats["failed"]
                        if retry_auto_stats["errors"]:
                            result["errors"].extend(retry_auto_stats["errors"])
                        await self._create_step_log(
                            db,
                            run_id=run_id,
                            channel=normalized_channel,
                            subscription_id=sub_id,
                            subscription_title=sub_title,
                            step="auto_transfer_retry_done",
                            status="success"
                            if retry_auto_stats["failed"] == 0
                            else "partial",
                            message=(
                                f"重试完成：成功 {retry_auto_stats['saved']} 条"
                                + (f"，失败 {retry_auto_stats['failed']} 条" if retry_auto_stats['failed'] else "")
                            ),
                        )
                        await operation_log_service.log_background_event(
                            source_type="background_task",
                            module="subscriptions",
                            action="subscription.item.transfer_retry_done",
                            status="success"
                            if retry_auto_stats["failed"] == 0
                            else "warning",
                            message=f"[{sub_title}] 历史重试完成：成功 {retry_auto_stats['saved']} 条，失败 {retry_auto_stats['failed']} 条",
                            trace_id=run_id,
                            extra={
                                "subscription_id": sub_id,
                                "title": sub_title,
                                "saved": retry_auto_stats["saved"],
                                "failed": retry_auto_stats["failed"],
                            },
                        )
                        if retry_auto_stats.get("subscription_completed"):
                            cleanup_after_auto = retry_auto_stats

                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=normalized_channel,
                        subscription_id=sub_id,
                        subscription_title=sub_title,
                        step="auto_transfer_summary",
                        status="success"
                        if sub_failed_transfer_count == 0
                        else "partial",
                        message=(
                            f"本轮转存汇总：成功 {sub_saved_count} 条"
                            + (f"，失败 {sub_failed_transfer_count} 条" if sub_failed_transfer_count else "")
                            + f"（新资源 {len(created_records)} 个"
                            + (f"，重试 {len(retry_records)} 个" if retry_records else "")
                            + "）"
                        ),
                    )
                    if cleanup_after_auto is not None:
                        await self._delete_subscription_with_records(db, sub_id)
                        await operation_log_service.log_background_event(
                            source_type="background_task",
                            module="subscriptions",
                            action="subscription.item.cleanup_after_transfer",
                            status="success",
                            message=f"[{sub_title}] 转存完成后自动清理订阅：{str(cleanup_after_auto.get('cleanup_message') or '订阅已自动清理')}",
                            trace_id=run_id,
                            extra={
                                "subscription_id": sub_id,
                                "title": sub_title,
                                "reason": cleanup_after_auto.get("cleanup_step"),
                            },
                        )
                        await self._create_step_log(
                            db,
                            run_id=run_id,
                            channel=normalized_channel,
                            subscription_id=sub_id,
                            subscription_title=sub_title,
                            step=str(
                                cleanup_after_auto.get("cleanup_step")
                                or "subscription_cleanup_after_transfer"
                            ),
                            status="success",
                            message=str(
                                cleanup_after_auto.get("cleanup_message")
                                or "订阅已自动清理"
                            ),
                            payload=cleanup_after_auto.get("cleanup_payload")
                            if isinstance(
                                cleanup_after_auto.get("cleanup_payload"), dict
                            )
                            else None,
                        )
                        self._apply_cleanup_stats(result, sub.media_type)
                else:
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=normalized_channel,
                        subscription_id=sub_id,
                        subscription_title=sub_title,
                        step="auto_transfer_skip",
                        status="info",
                        message="未开启自动转存，已记录资源供手动处理",
                    )

                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=normalized_channel,
                    subscription_id=sub_id,
                    subscription_title=sub_title,
                    step="subscription_done",
                    status="success",
                    message="订阅处理完成",
                )
                # 构建每部影视的摘要信息
                item_parts = [f"[{sub_title}]"]
                item_new = result["new_resource_count"]
                if should_auto_download:
                    item_parts.append(
                        f"新资源 {len(created_records)} 条，"
                        f"转存成功 {sub_saved_count} 条，失败 {sub_failed_transfer_count} 条"
                    )
                else:
                    item_parts.append(
                        f"新资源 {len(created_records)} 条（未启用自动转存）"
                    )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.item.done",
                    status="success" if sub_failed_transfer_count == 0 else "warning",
                    message="，".join(item_parts),
                    trace_id=run_id,
                    extra={
                        "subscription_id": sub_id,
                        "title": sub_title,
                        "channel": normalized_channel,
                        "new_resources": len(created_records),
                        "auto_saved": sub_saved_count if should_auto_download else None,
                        "auto_failed": sub_failed_transfer_count
                        if should_auto_download
                        else None,
                    },
                )
                await db.commit()
            except Exception as exc:
                await db.rollback()
                result["failed_count"] += 1
                result["errors"].append(
                    {
                        "subscription_id": sub_id,
                        "title": sub_title,
                        "error": str(exc),
                    }
                )
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=normalized_channel,
                    subscription_id=sub_id,
                    subscription_title=sub_title,
                    step="subscription_failed",
                    status="failed",
                    message=f"处理出错：{str(exc)[:200]}",
                )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.item.failed",
                    status="failed",
                    message=f"[{sub_title}] 订阅处理失败: {str(exc)[:200]}",
                    trace_id=run_id,
                    extra={
                        "subscription_id": sub_id,
                        "title": sub_title,
                        "channel": normalized_channel,
                        "error": str(exc)[:500],
                    },
                )
                await db.commit()
            finally:
                result["processed_count"] += 1
                if progress_callback:
                    await progress_callback(
                        {
                            "channel": normalized_channel,
                            "status": "running",
                            "processed_count": result["processed_count"],
                            "checked_count": result["checked_count"],
                            "new_resource_count": result["new_resource_count"],
                            "auto_saved_count": result["auto_saved_count"],
                            "auto_failed_count": result["auto_failed_count"],
                            "auto_new_saved_count": result["auto_new_saved_count"],
                            "auto_new_failed_count": result["auto_new_failed_count"],
                            "auto_retry_saved_count": result["auto_retry_saved_count"],
                            "auto_retry_failed_count": result[
                                "auto_retry_failed_count"
                            ],
                            "failed_count": result["failed_count"],
                            "message": f"已处理 {result['processed_count']}/{result['checked_count']} 项订阅",
                        }
                    )

        status = self._resolve_status(
            result["failed_count"],
            result["checked_count"],
            result["auto_failed_count"],
        )
        unlock_stats = hdhive_unlock_context.get("stats", {})
        result["hdhive_unlock_attempted_count"] = int(
            unlock_stats.get("attempted") or 0
        )
        result["hdhive_unlock_success_count"] = int(unlock_stats.get("success") or 0)
        result["hdhive_unlock_failed_count"] = int(unlock_stats.get("failed") or 0)
        result["hdhive_unlock_skipped_count"] = int(unlock_stats.get("skipped") or 0)
        result["hdhive_unlock_points_spent"] = int(
            unlock_stats.get("points_spent") or 0
        )
        message = self._build_message(result)
        finished_at = datetime.utcnow()
        result["finished_at"] = finished_at.isoformat()
        result["status"] = status.value
        result["message"] = message

        await operation_log_service.log_background_event(
            source_type="background_task",
            module="subscriptions",
            action="subscription.check.finish",
            status=status.value,
            message=(
                f"订阅检查任务完成（频道：{normalized_channel}）：检查 {result['checked_count']} 项，"
                f"新增资源 {result['new_resource_count']} 条，"
                f"转存成功 {result['auto_saved_count']} 条，转存失败 {result['auto_failed_count']} 条，"
                f"自动清理 {result['cleanup_deleted_count']} 项，"
                f"失败 {result['failed_count']} 项"
            ),
            trace_id=run_id,
            extra={
                "channel": normalized_channel,
                "checked_count": result["checked_count"],
                "new_resource_count": result["new_resource_count"],
                "auto_saved_count": result["auto_saved_count"],
                "auto_failed_count": result["auto_failed_count"],
                "cleanup_deleted_count": result["cleanup_deleted_count"],
                "failed_count": result["failed_count"],
                "hdhive_unlock_attempted_count": result[
                    "hdhive_unlock_attempted_count"
                ],
                "hdhive_unlock_success_count": result["hdhive_unlock_success_count"],
                "hdhive_unlock_points_spent": result["hdhive_unlock_points_spent"],
            },
        )

        finalize_error = ""
        try:
            await self._create_execution_log(
                db=db,
                channel=normalized_channel,
                status=status,
                message=message,
                checked_count=result["checked_count"],
                new_resource_count=result["new_resource_count"],
                failed_count=result["failed_count"],
                details=result["errors"],
                started_at=started_at,
                finished_at=finished_at,
            )
            await self._create_step_log(
                db,
                run_id=run_id,
                channel=normalized_channel,
                step="run_finish",
                status=status.value,
                message=message,
                payload={
                    "checked_count": result["checked_count"],
                    "resource_checked_count": result["resource_checked_count"],
                    "new_resource_count": result["new_resource_count"],
                    "resource_duplicate_count": result["resource_duplicate_count"],
                    "auto_saved_count": result["auto_saved_count"],
                    "auto_failed_count": result["auto_failed_count"],
                    "failed_count": result["failed_count"],
                    "cleanup_deleted_count": result["cleanup_deleted_count"],
                    "cleanup_movie_deleted_count": result[
                        "cleanup_movie_deleted_count"
                    ],
                    "cleanup_tv_deleted_count": result["cleanup_tv_deleted_count"],
                    "hdhive_unlock_attempted_count": result[
                        "hdhive_unlock_attempted_count"
                    ],
                    "hdhive_unlock_success_count": result[
                        "hdhive_unlock_success_count"
                    ],
                    "hdhive_unlock_failed_count": result["hdhive_unlock_failed_count"],
                    "hdhive_unlock_skipped_count": result[
                        "hdhive_unlock_skipped_count"
                    ],
                    "hdhive_unlock_points_spent": result["hdhive_unlock_points_spent"],
                },
            )
            await self._prune_step_logs(db)
            await db.commit()
        except Exception as exc:
            finalize_error = str(exc)
            await db.rollback()
            result["errors"].append({"stage": "run_finalize", "error": finalize_error})
            result["finalize_error"] = finalize_error
            result["message"] = f"{message}；收尾阶段异常: {finalize_error[:200]}"
            if result["status"] == ExecutionStatus.SUCCESS.value:
                result["status"] = ExecutionStatus.PARTIAL.value

            try:
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=normalized_channel,
                    step="run_finalize_failed",
                    status="warning",
                    message=f"写入执行日志失败：{finalize_error[:200]}",
                    payload={
                        "error": finalize_error[:500],
                        "status_before_finalize": status.value,
                    },
                )
                await db.commit()
            except Exception:
                await db.rollback()
        return result

    async def _create_step_log(
        self,
        db: AsyncSession,
        run_id: str,
        channel: str,
        step: str,
        status: str,
        message: str,
        subscription_id: int | None = None,
        subscription_title: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        row = SubscriptionStepLog(
            run_id=run_id,
            channel=channel,
            subscription_id=subscription_id,
            subscription_title=subscription_title,
            step=step,
            status=status,
            message=message[:500],
            payload=json.dumps(payload, ensure_ascii=False) if payload else None,
        )
        db.add(row)

    async def _prune_step_logs(self, db: AsyncSession) -> None:
        keep_ids_subquery = (
            select(SubscriptionStepLog.id)
            .order_by(
                SubscriptionStepLog.created_at.desc(), SubscriptionStepLog.id.desc()
            )
            .limit(1000)
            .subquery()
        )
        await db.execute(
            delete(SubscriptionStepLog).where(
                ~SubscriptionStepLog.id.in_(select(keep_ids_subquery.c.id))
            )
        )

    async def _evaluate_pre_scan_cleanup(
        self,
        db: AsyncSession,
        *,
        run_id: str,
        channel: str,
        sub: "SubscriptionSnapshot",
    ) -> dict[str, Any]:
        if sub.media_type == MediaType.MOVIE:
            if sub.has_successful_transfer:
                await self._delete_subscription_with_records(db, sub.id)
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=channel,
                    subscription_id=sub.id,
                    subscription_title=sub.title,
                    step="subscription_cleanup_movie_transferred",
                    status="success",
                    message="电影已有转存记录，无需重复处理",
                    payload={"reason": "successful_transfer"},
                )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.item.cleanup_pre_scan",
                    status="success",
                    message=f"[{sub.title}] 预扫描清理：电影已有成功转存记录，自动删除订阅",
                    trace_id=run_id,
                    extra={
                        "subscription_id": sub.id,
                        "title": sub.title,
                        "reason": "successful_transfer",
                    },
                )
                return {"deleted": True}

            if sub.tmdb_id is None:
                return {"deleted": False, "tv_missing_snapshot": None}

            # Emby 检查
            movie_status = await emby_service.get_movie_status_by_tmdb(sub.tmdb_id)
            status_text = str(movie_status.get("status") or "")
            if status_text == "ok":
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=channel,
                    subscription_id=sub.id,
                    subscription_title=sub.title,
                    step="movie_emby_check_done",
                    status="info",
                    message="已检查媒体库中电影的入库状态",
                    payload={
                        "tmdb_id": sub.tmdb_id,
                        "exists": bool(movie_status.get("exists")),
                        "matched_count": len(movie_status.get("item_ids") or []),
                    },
                )
                if bool(movie_status.get("exists")):
                    await self._delete_subscription_with_records(db, sub.id)
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=channel,
                        subscription_id=sub.id,
                        subscription_title=sub.title,
                    step="subscription_cleanup_movie_emby_exists",
                    status="success",
                    message="电影已在媒体库中，无需继续订阅",
                        payload={
                            "tmdb_id": sub.tmdb_id,
                            "matched_item_ids": movie_status.get("item_ids") or [],
                        },
                    )
                    await operation_log_service.log_background_event(
                        source_type="background_task",
                        module="subscriptions",
                        action="subscription.item.cleanup_pre_scan",
                        status="success",
                        message=f"[{sub.title}] 预扫描清理：电影已存在于 Emby，自动删除订阅",
                        trace_id=run_id,
                        extra={
                            "subscription_id": sub.id,
                            "title": sub.title,
                            "reason": "emby_exists",
                            "tmdb_id": sub.tmdb_id,
                        },
                    )
                    return {"deleted": True}
            elif status_text:
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=channel,
                    subscription_id=sub.id,
                    subscription_title=sub.title,
                    step="movie_emby_check_failed",
                    status="warning",
                    message=f"媒体库查询失败，暂跳过自动清理：{movie_status.get('message') or '未知错误'}",
                    payload={"tmdb_id": sub.tmdb_id, "status": status_text},
                )

            # 飞牛检查
            feiniu_movie_status = await self._check_feiniu_movie_status(sub.tmdb_id)
            if feiniu_movie_status.get("checked") and feiniu_movie_status.get("exists"):
                await self._delete_subscription_with_records(db, sub.id)
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=channel,
                    subscription_id=sub.id,
                    subscription_title=sub.title,
                    step="subscription_cleanup_movie_feiniu_exists",
                    status="success",
                    message="电影已在飞牛媒体库中，无需继续订阅",
                    payload={
                        "tmdb_id": sub.tmdb_id,
                        "matched_item_ids": feiniu_movie_status.get("item_ids") or [],
                    },
                )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.item.cleanup_pre_scan",
                    status="success",
                    message=f"[{sub.title}] 预扫描清理：电影已存在于飞牛，自动删除订阅",
                    trace_id=run_id,
                    extra={
                        "subscription_id": sub.id,
                        "title": sub.title,
                        "reason": "feiniu_exists",
                        "tmdb_id": sub.tmdb_id,
                    },
                )
                return {"deleted": True}

            return {"deleted": False, "tv_missing_snapshot": None}

        if sub.media_type != MediaType.TV or sub.tmdb_id is None:
            return {"deleted": False, "tv_missing_snapshot": None}

        # Emby 缺集检查
        await self._create_step_log(
            db,
            run_id=run_id,
            channel=channel,
            subscription_id=sub.id,
            subscription_title=sub.title,
            step="tv_missing_fetch_start",
            status="info",
            message="正在检查剧集的缺集状态",
            payload={"tmdb_id": sub.tmdb_id},
        )
        tv_missing_result = await tv_missing_service.get_tv_missing_status(
            sub.tmdb_id,
            include_specials=bool(sub.tv_include_specials),
            season_number=sub.tv_season_number
            if sub.tv_scope in {"season", "episode_range"}
            else None,
            episode_start=sub.tv_episode_start
            if sub.tv_scope == "episode_range"
            else None,
            episode_end=sub.tv_episode_end
            if sub.tv_scope == "episode_range"
            else None,
            aired_only=sub.tv_follow_mode == "new",
        )
        status_text = str(tv_missing_result.get("status") or "")
        if status_text == "ok":
            counts = (
                tv_missing_result.get("counts")
                if isinstance(tv_missing_result.get("counts"), dict)
                else {}
            )
            missing_count = int(counts.get("missing") or 0)
            await self._create_step_log(
                db,
                run_id=run_id,
                channel=channel,
                subscription_id=sub.id,
                subscription_title=sub.title,
                step="tv_missing_fetch_done",
                status="success",
                message=f"缺集检查完成：共 {int(counts.get('aired') or 0)} 集，已有 {int(counts.get('existing') or 0)} 集，缺失 {missing_count} 集",
                payload={
                    "aired_count": int(counts.get("aired") or 0),
                    "existing_count": int(counts.get("existing") or 0),
                    "missing_count": missing_count,
                },
            )
            if missing_count <= 0:
                await self._delete_subscription_with_records(db, sub.id)
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=channel,
                    subscription_id=sub.id,
                    subscription_title=sub.title,
                    step="subscription_cleanup_tv_no_missing",
                    status="success",
                    message="剧集已全部入库，无需继续订阅",
                    payload={"tmdb_id": sub.tmdb_id, "missing_count": 0},
                )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.item.cleanup_pre_scan",
                    status="success",
                    message=f"[{sub.title}] 预扫描清理：剧集已不缺集，自动删除订阅",
                    trace_id=run_id,
                    extra={
                        "subscription_id": sub.id,
                        "title": sub.title,
                        "reason": "tv_no_missing",
                        "tmdb_id": sub.tmdb_id,
                    },
                )
                return {"deleted": True, "tv_missing_snapshot": tv_missing_result}
            return {"deleted": False, "tv_missing_snapshot": tv_missing_result}

        # Emby 缺集查询失败，尝试飞牛缺集检查
        feiniu_missing_result = await self._check_feiniu_tv_missing_status(sub.tmdb_id)
        if feiniu_missing_result.get("checked"):
            feiniu_missing_count = int(feiniu_missing_result.get("missing_count") or -1)
            if feiniu_missing_count == 0:
                await self._delete_subscription_with_records(db, sub.id)
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=channel,
                    subscription_id=sub.id,
                    subscription_title=sub.title,
                    step="subscription_cleanup_tv_no_missing_feiniu",
                    status="success",
                    message="剧集在飞牛媒体库中已全部入库，无需继续订阅",
                    payload={"tmdb_id": sub.tmdb_id, "missing_count": 0, "source": "feiniu"},
                )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.item.cleanup_pre_scan",
                    status="success",
                    message=f"[{sub.title}] 预扫描清理：剧集在飞牛中已不缺集，自动删除订阅",
                    trace_id=run_id,
                    extra={
                        "subscription_id": sub.id,
                        "title": sub.title,
                        "reason": "tv_no_missing_feiniu",
                        "tmdb_id": sub.tmdb_id,
                    },
                )
                return {"deleted": True, "tv_missing_snapshot": None}

        await self._create_step_log(
            db,
            run_id=run_id,
            channel=channel,
            subscription_id=sub.id,
            subscription_title=sub.title,
            step="tv_missing_fetch_failed",
            status="warning",
            message=f"缺集检查失败，暂跳过自动清理：{tv_missing_result.get('message') or '未知错误'}",
            payload={"tmdb_id": sub.tmdb_id, "status": status_text or "unknown"},
        )
        return {"deleted": False, "tv_missing_snapshot": None}

    async def _delete_subscription_with_records(
        self, db: AsyncSession, subscription_id: int
    ) -> None:
        await db.execute(
            delete(DownloadRecord).where(
                DownloadRecord.subscription_id == subscription_id
            )
        )
        await db.execute(delete(Subscription).where(Subscription.id == subscription_id))

    @staticmethod
    def _apply_cleanup_stats(result: dict[str, Any], media_type: MediaType) -> None:
        result["cleanup_deleted_count"] = (
            int(result.get("cleanup_deleted_count") or 0) + 1
        )
        if media_type == MediaType.TV:
            result["cleanup_tv_deleted_count"] = (
                int(result.get("cleanup_tv_deleted_count") or 0) + 1
            )
        else:
            result["cleanup_movie_deleted_count"] = (
                int(result.get("cleanup_movie_deleted_count") or 0) + 1
            )

    async def cleanup_completed_subscriptions(
        self, db: AsyncSession
    ) -> dict[str, Any]:
        """离线下载完成后检查并清理已完成的订阅（电影已转存或剧集不缺集）"""
        result: dict[str, Any] = {"deleted_count": 0, "details": []}

        has_successful_transfer = (
            select(DownloadRecord.id)
            .where(
                DownloadRecord.subscription_id == Subscription.id,
                or_(
                    DownloadRecord.completed_at.is_not(None),
                    DownloadRecord.status.in_(
                        (MediaStatus.COMPLETED, MediaStatus.OFFLINE_COMPLETED)
                    ),
                ),
            )
            .exists()
            .label("has_successful_transfer")
        )

        subs_result = await db.execute(
            select(
                Subscription.id,
                Subscription.tmdb_id,
                Subscription.title,
                Subscription.media_type,
                Subscription.tv_scope,
                Subscription.tv_season_number,
                Subscription.tv_episode_start,
                Subscription.tv_episode_end,
                Subscription.tv_follow_mode,
                Subscription.tv_include_specials,
                has_successful_transfer,
            )
            .where(Subscription.is_active == True)  # noqa: E712
            .order_by(Subscription.id.asc())
        )

        for row in subs_result.all():
            sub_id = int(row.id)
            title = str(row.title or "")
            media_type = row.media_type
            tmdb_id = int(row.tmdb_id) if row.tmdb_id is not None else None
            sub_has_transfer = bool(row.has_successful_transfer)

            should_delete = False
            reason = ""

            if media_type == MediaType.MOVIE:
                if sub_has_transfer:
                    should_delete = True
                    reason = "电影已有成功转存记录"
                elif tmdb_id is not None:
                    try:
                        movie_status = await emby_service.get_movie_status_by_tmdb(
                            tmdb_id
                        )
                        if str(movie_status.get("status") or "") == "ok" and bool(
                            movie_status.get("exists")
                        ):
                            should_delete = True
                            reason = "电影已存在于 Emby"
                    except Exception:
                        logger.exception(
                            "离线完成后检查电影 Emby 状态失败: %s", title
                        )
                    if not should_delete:
                        feiniu_movie = await self._check_feiniu_movie_status(tmdb_id)
                        if feiniu_movie.get("checked") and feiniu_movie.get("exists"):
                            should_delete = True
                            reason = "电影已存在于飞牛"
            elif media_type == MediaType.TV and tmdb_id is not None:
                try:
                    tv_missing_result = (
                        await tv_missing_service.get_tv_missing_status(
                            tmdb_id,
                            include_specials=bool(row.tv_include_specials),
                            season_number=row.tv_season_number
                            if str(row.tv_scope or "all")
                            in {"season", "episode_range"}
                            else None,
                            episode_start=row.tv_episode_start
                            if str(row.tv_scope or "all") == "episode_range"
                            else None,
                            episode_end=row.tv_episode_end
                            if str(row.tv_scope or "all") == "episode_range"
                            else None,
                            aired_only=str(row.tv_follow_mode or "missing") == "new",
                        )
                    )
                    if str(tv_missing_result.get("status") or "") == "ok":
                        counts = (
                            tv_missing_result.get("counts")
                            if isinstance(tv_missing_result.get("counts"), dict)
                            else {}
                        )
                        missing_count = int(counts.get("missing") or 0)
                        if missing_count <= 0:
                            should_delete = True
                            reason = "剧集已不缺集（Emby）"
                    if not should_delete:
                        feiniu_tv = await self._check_feiniu_tv_missing_status(tmdb_id)
                        if feiniu_tv.get("checked") and feiniu_tv.get("missing_count", -1) == 0:
                            should_delete = True
                            reason = "剧集已不缺集（飞牛）"
                except Exception:
                    logger.exception("离线完成后检查剧集缺集状态失败: %s", title)

            if should_delete:
                await self._delete_subscription_with_records(db, sub_id)
                result["deleted_count"] += 1
                result["details"].append(
                    {
                        "subscription_id": sub_id,
                        "title": title,
                        "media_type": str(media_type.value)
                        if hasattr(media_type, "value")
                        else str(media_type),
                        "reason": reason,
                    }
                )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.item.cleanup_offline_completed",
                    status="success",
                    message=f"[{title}] 离线完成触发清理：{reason}，自动删除订阅",
                    extra={
                        "subscription_id": sub_id,
                        "title": title,
                        "reason": reason,
                    },
                )

        if result["deleted_count"] > 0:
            await db.commit()
            logger.info(
                "离线完成触发订阅清理，共删除 %d 项订阅",
                result["deleted_count"],
            )
        return result

    async def _check_feiniu_movie_status(
        self, tmdb_id: int
    ) -> dict[str, Any]:
        """检查电影在飞牛中是否已存在，返回 {"checked": bool, "exists": bool, "item_ids": list}"""
        if not runtime_settings_service.get_feiniu_url().strip():
            return {"checked": False}
        try:
            indexed_result = await feiniu_sync_index_service.get_movie_status(tmdb_id)
            if indexed_result is not None:
                if str(indexed_result.get("status") or "") == "ok" and bool(
                    indexed_result.get("exists")
                ):
                    return {
                        "checked": True,
                        "exists": True,
                        "item_ids": indexed_result.get("item_ids") or [],
                    }
                return {
                    "checked": True,
                    "exists": False,
                    "item_ids": [],
                }
            live_result = await feiniu_service.get_movie_status_by_tmdb(tmdb_id)
            if str(live_result.get("status") or "") == "ok" and bool(
                live_result.get("exists")
            ):
                return {
                    "checked": True,
                    "exists": True,
                    "item_ids": live_result.get("item_ids") or [],
                }
            if str(live_result.get("status") or "") == "not_logged_in":
                return {"checked": False}
            return {
                "checked": str(live_result.get("status") or "") == "ok",
                "exists": False,
                "item_ids": [],
            }
        except Exception:
            logger.exception("飞牛电影状态查询失败: tmdb_id=%s", tmdb_id)
            return {"checked": False}

    async def _check_feiniu_tv_missing_status(
        self, tmdb_id: int
    ) -> dict[str, Any]:
        """检查剧集在飞牛中的缺集状态，返回 {"checked": bool, "missing_count": int}"""
        if not runtime_settings_service.get_feiniu_url().strip():
            return {"checked": False}
        try:
            from app.services.tmdb_service import tmdb_service as _tmdb

            indexed_result = (
                await feiniu_sync_index_service.get_tv_existing_episodes(tmdb_id)
            )
            feiniu_result = (
                indexed_result
                if indexed_result is not None
                else await feiniu_service.get_tv_episode_status_by_tmdb(tmdb_id)
            )
            status_text = str(feiniu_result.get("status") or "")
            if status_text not in ("ok",):
                return {"checked": False}

            feiniu_existing = feiniu_result.get("existing_episodes") or set()
            feiniu_existing_pairs = {
                (int(p[0]), int(p[1]))
                for p in feiniu_existing
                if isinstance(p, (list, tuple)) and len(p) == 2
            } if isinstance(feiniu_existing, (list, set)) else feiniu_existing

            tmdb_detail = await _tmdb.get_tv_detail(tmdb_id)
            seasons = (
                tmdb_detail.get("seasons")
                if isinstance(tmdb_detail, dict)
                else []
            )
            if not isinstance(seasons, list):
                seasons = []
            tmdb_pairs: set[tuple[int, int]] = set()
            for season in seasons:
                if not isinstance(season, dict):
                    continue
                sn = season.get("season_number")
                ec = season.get("episode_count")
                if sn is None or ec is None:
                    continue
                sn = int(sn)
                ec = int(ec)
                if sn == 0:
                    continue
                for ep in range(1, ec + 1):
                    tmdb_pairs.add((sn, ep))

            if not tmdb_pairs:
                return {"checked": False}

            missing = tmdb_pairs - feiniu_existing_pairs
            return {"checked": True, "missing_count": len(missing)}
        except Exception:
            logger.exception("飞牛剧集缺集状态查询失败: tmdb_id=%s", tmdb_id)
            return {"checked": False}

    async def _fetch_resources(
        self,
        channel: str,
        sub: "SubscriptionSnapshot",
        hdhive_unlock_context: dict[str, Any] | None = None,
        source_order: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        traces: list[dict[str, Any]] = []
        source_attempts: list[dict[str, Any]] = []  # 记录每个来源的尝试结果
        active_order = list(source_order or self._resolve_source_order(channel))
        traces.append(
            {
                "step": "fetch_source_order",
                "status": "info",
                "message": f"按优先级执行资源搜索: {' > '.join(active_order) if active_order else '无可用来源'}",
                "payload": {"source_order": active_order},
            }
        )
        if not active_order:
            traces.append(
                {
                    "step": "fetch_source_order_empty",
                    "status": "warning",
                    "message": "当前优先级来源均不可用，请检查配置",
                }
            )
            return (
                [],
                traces,
                {"source_order": active_order, "attempts": [], "summary": "无可用来源"},
            )

        primary_resources: list[dict[str, Any]] = []
        for source in active_order:
            source_resources: list[dict[str, Any]] = []
            source_traces: list[dict[str, Any]] = []
            attempt_info: dict[str, Any] = {
                "source": source,
                "status": "empty",
                "count": 0,
            }
            try:
                if source == "hdhive":
                    source_resources, source_traces = await self._fetch_from_hdhive(sub)
                elif source == "tg":
                    source_resources, source_traces = await self._fetch_from_tg(sub)
                else:
                    source_resources, source_traces = await self._fetch_from_pansou(sub)
            except Exception as exc:
                source_traces.append(
                    {
                        "step": f"fetch_{source}_failed",
                        "status": "warning",
                        "message": f"{source} 抓取失败，继续尝试下一个来源",
                        "payload": {"error": str(exc)[:300]},
                    }
                )
                attempt_info["status"] = "failed"
                attempt_info["error"] = str(exc)[:100]
                source_resources = []

            traces.extend(source_traces)
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="subscriptions",
                action="subscription.item.fetch_source",
                status="success" if source_resources else "info",
                message=f"[{sub.title}] 来源 {source} 返回 {len(source_resources)} 条资源",
                extra={
                    "subscription_id": sub.id,
                    "title": sub.title,
                    "source": source,
                    "count": len(source_resources),
                },
            )
            if source_resources:
                traces.append(
                    {
                        "step": "fetch_source_selected",
                        "status": "success",
                        "message": f"来源 {source} 命中资源 {len(source_resources)} 条，已加入候选列表",
                        "payload": {"source": source, "count": len(source_resources)},
                    }
                )
                attempt_info["status"] = "success"
                attempt_info["count"] = len(source_resources)
                if source == "hdhive":
                    source_resources = await self._prepare_hdhive_locked_resources(
                        source_resources,
                        hdhive_unlock_context or self._build_hdhive_unlock_context(),
                        traces,
                    )
                # Sort by user's resolution/format preferences
                pref_res = self._resolve_subscription_resolutions(sub)
                pref_fmt = self._resolve_subscription_formats(sub)
                if pref_res or pref_fmt:
                    source_resources = sort_by_preference(
                        source_resources, pref_res, pref_fmt
                    )
                primary_resources.extend(source_resources)

            source_attempts.append(attempt_info)

            # 发送来源尝试事件到 Kafka
            try:
                from app.analytics import kafka_producer

                if kafka_producer._enabled:
                    kafka_producer.send(
                        event_type="source_attempt",
                        data={
                            "subscription_id": sub.id,
                            "title": sub.title,
                            "source": source,
                            "status": attempt_info.get("status", "empty"),
                            "resource_count": attempt_info.get("count", 0),
                        },
                        key=str(sub.id),
                    )
            except Exception:
                pass

        if not primary_resources:
            traces.append(
                {
                    "step": "fetch_all_empty",
                    "status": "warning",
                    "message": "所有优先级来源都未命中可用资源",
                }
            )

        # 离线转存：追加磁力资源（SeedHub + 不太灵）
        offline_resources, offline_traces = await self._fetch_offline_magnets(sub)
        traces.extend(offline_traces)
        if offline_resources:
            pref_res = self._resolve_subscription_resolutions(sub)
            pref_fmt = self._resolve_subscription_formats(sub)
            if pref_res or pref_fmt:
                offline_resources = sort_by_preference(
                    offline_resources, pref_res, pref_fmt
                )
            primary_resources.extend(offline_resources)
            source_attempts.append(
                {
                    "source": "offline",
                    "status": "success",
                    "count": len(offline_resources),
                }
            )

        # 生成来源尝试链路摘要
        summary = self._build_source_attempt_summary(source_attempts, active_order)

        # 按订阅质量偏好过滤资源
        quality_filter = self._resolve_subscription_quality_filter(sub)
        if any(v for v in quality_filter.values() if v is not None):
            before_count = len(primary_resources)
            primary_resources = filter_and_sort_by_quality(primary_resources, **quality_filter)
            filtered_count = before_count - len(primary_resources)
            if filtered_count > 0:
                traces.append(
                    {
                        "step": "quality_filter_applied",
                        "status": "info",
                        "message": f"质量筛选过滤掉 {filtered_count} 个不符合偏好的资源",
                    }
                )

        return (
            primary_resources,
            traces,
            {
                "source_order": active_order,
                "attempts": source_attempts,
                "summary": summary,
            },
        )

    def _build_source_attempt_summary(
        self, attempts: list[dict[str, Any]], source_order: list[str]
    ) -> str:
        """构建来源尝试链路的中文摘要"""
        if not attempts:
            return "未尝试任何来源"

        # 来源名称映射
        source_names = {
            "hdhive": "HDHive",
            "pansou": "Pansou",
            "tg": "TG",
            "offline": "离线磁力",
        }

        # 构建尝试链路
        chain_parts: list[str] = []
        success_sources: list[str] = []

        for attempt in attempts:
            source = attempt.get("source", "")
            status = attempt.get("status", "")
            count = attempt.get("count", 0)
            source_name = source_names.get(source, source)

            if status == "success":
                chain_parts.append(f"{source_name}({count}条)")
                success_sources.append(source_name)
            elif status == "failed":
                error = attempt.get("error", "")
                chain_parts.append(f"{source_name}(失败)")
            else:  # empty
                chain_parts.append(f"{source_name}(无资源)")

        if not chain_parts:
            return "未尝试任何来源"

        chain_str = " → ".join(chain_parts)

        if success_sources:
            return f"尝试来源 [{chain_str}]，最终命中 {', '.join(success_sources)}"
        else:
            return f"尝试来源 [{chain_str}]，均未命中可用资源"

    def _resolve_source_order(self, channel: str) -> list[str]:
        _ = channel
        priority = runtime_settings_service.get_subscription_resource_priority()
        source_order = [item for item in priority if item in {"hdhive", "pansou", "tg"}]
        tg_ready = bool(
            runtime_settings_service.get_tg_api_id().strip()
            and runtime_settings_service.get_tg_api_hash().strip()
            and runtime_settings_service.get_tg_session().strip()
            and runtime_settings_service.get_tg_channel_usernames()
        )
        if not tg_ready:
            source_order = [item for item in source_order if item != "tg"]
        return source_order

    async def _fetch_from_pansou(
        self, sub: "SubscriptionSnapshot"
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        traces: list[dict[str, Any]] = []
        media_type = "tv" if sub.media_type == MediaType.TV else "movie"

        if sub.tmdb_id is not None:
            try:
                traces.append(
                    {
                        "step": "fetch_pansou_tmdb_start",
                        "status": "info",
                        "message": "开始通过 tmdb_id 调用 Pansou",
                        "payload": {"tmdb_id": sub.tmdb_id, "media_type": media_type},
                    }
                )
                pansou_result = await _search_pansou_pan115_resources(
                    sub.tmdb_id, media_type
                )
                pansou_list = list(pansou_result.get("list") or [])
                if pansou_list:
                    traces.append(
                        {
                            "step": "fetch_pansou_tmdb_done",
                            "status": "success",
                            "message": f"Pansou(TMDB) 返回 {len(pansou_list)} 条候选资源",
                            "payload": {"count": len(pansou_list)},
                        }
                    )
                    return pansou_list, traces
                traces.append(
                    {
                        "step": "fetch_pansou_tmdb_empty",
                        "status": "warning",
                        "message": "Pansou(TMDB) 未命中资源，尝试关键词兜底",
                    }
                )
            except Exception as exc:
                traces.append(
                    {
                        "step": "fetch_pansou_tmdb_failed",
                        "status": "warning",
                        "message": "Pansou(TMDB) 请求失败，尝试关键词兜底",
                        "payload": {"error": str(exc)[:300]},
                    }
                )

        keyword = self._build_pansou_keyword(sub)
        if not keyword:
            traces.append(
                {
                    "step": "fetch_pansou_keyword_skip",
                    "status": "warning",
                    "message": "缺少关键词，无法执行 Pansou 兜底搜索",
                }
            )
            return [], traces
        traces.append(
            {
                "step": "fetch_pansou_keyword_start",
                "status": "info",
                "message": "开始通过关键词调用 Pansou",
                "payload": {"keyword": keyword},
            }
        )
        payload = await pansou_service.search_115(keyword, res="results")
        resources = _normalize_pansou_pan115_list(payload)
        traces.append(
            {
                "step": "fetch_pansou_keyword_done",
                "status": "success" if resources else "warning",
                "message": f"Pansou(关键词) 返回 {len(resources)} 条候选资源",
                "payload": {"count": len(resources)},
            }
        )
        return resources, traces

    async def _fetch_from_hdhive(
        self, sub: "SubscriptionSnapshot"
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        traces: list[dict[str, Any]] = []
        resources: list[dict[str, Any]] = []
        if sub.tmdb_id is not None:
            try:
                traces.append(
                    {
                        "step": "fetch_hdhive_tmdb_start",
                        "status": "info",
                        "message": "开始通过 tmdb_id 调用 HDHive",
                        "payload": {
                            "tmdb_id": sub.tmdb_id,
                            "media_type": sub.media_type.value,
                        },
                    }
                )
                if sub.media_type == MediaType.TV:
                    resources = await hdhive_service.get_tv_pan115(sub.tmdb_id)
                else:
                    resources = await hdhive_service.get_movie_pan115(sub.tmdb_id)
                resources = self._normalize_hdhive_subscription_items(resources)
                if runtime_settings_service.get_subscription_hdhive_prefer_free():
                    resources = hdhive_service.sort_free_first(resources)
                traces.append(
                    {
                        "step": "fetch_hdhive_tmdb_done",
                        "status": "success" if resources else "warning",
                        "message": f"HDHive(TMDB) 返回 {len(resources)} 条候选资源",
                        "payload": {"count": len(resources)},
                    }
                )
                if resources:
                    return resources, traces
            except Exception as exc:
                traces.append(
                    {
                        "step": "fetch_hdhive_tmdb_failed",
                        "status": "warning",
                        "message": "HDHive(TMDB) 请求失败，尝试关键词兜底",
                        "payload": {"error": str(exc)[:300]},
                    }
                )

        keyword = self._build_hdhive_keyword(sub)
        if not keyword:
            traces.append(
                {
                    "step": "fetch_hdhive_keyword_skip",
                    "status": "warning",
                    "message": "缺少关键词，无法执行 HDHive 兜底搜索",
                }
            )
            return [], traces

        traces.append(
            {
                "step": "fetch_hdhive_keyword_start",
                "status": "info",
                "message": "开始通过关键词调用 HDHive",
                "payload": {"keyword": keyword},
            }
        )
        media_type = "tv" if sub.media_type == MediaType.TV else "movie"
        keyword_resources = await hdhive_service.get_pan115_by_keyword(
            keyword, media_type=media_type
        )
        keyword_resources = self._normalize_hdhive_subscription_items(keyword_resources)
        if runtime_settings_service.get_subscription_hdhive_prefer_free():
            keyword_resources = hdhive_service.sort_free_first(keyword_resources)
        traces.append(
            {
                "step": "fetch_hdhive_keyword_done",
                "status": "success" if keyword_resources else "warning",
                "message": f"HDHive(关键词) 返回 {len(keyword_resources)} 条候选资源",
                "payload": {"count": len(keyword_resources)},
            }
        )
        return keyword_resources, traces

    async def _fetch_from_tg(
        self, sub: "SubscriptionSnapshot"
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        traces: list[dict[str, Any]] = []
        keyword = self._build_tg_keyword(sub)
        if not keyword:
            traces.append(
                {
                    "step": "fetch_tg_keyword_skip",
                    "status": "warning",
                    "message": "缺少关键词，无法执行 Telegram 搜索",
                }
            )
            return [], traces

        traces.append(
            {
                "step": "fetch_tg_keyword_start",
                "status": "info",
                "message": "开始通过关键词调用 Telegram 频道搜索",
                "payload": {"keyword": keyword},
            }
        )
        media_type = "tv" if sub.media_type == MediaType.TV else "movie"
        resources = await tg_service.search_115_by_keyword(
            keyword, media_type=media_type
        )
        traces.append(
            {
                "step": "fetch_tg_keyword_done",
                "status": "success" if resources else "warning",
                "message": f"Telegram 返回 {len(resources)} 条候选资源",
                "payload": {"count": len(resources)},
            }
        )
        return resources, traces

    async def _fetch_offline_magnets(
        self,
        sub: "SubscriptionSnapshot",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """离线转存启用时，从 SeedHub / 不太灵并发抓取磁力资源。"""
        if not runtime_settings_service.get_subscription_offline_transfer_enabled():
            return [], []

        traces: list[dict[str, Any]] = []
        keyword = self._build_pansou_keyword(sub)
        media_type = "tv" if sub.media_type == MediaType.TV else "movie"

        async def _seedhub() -> list[dict[str, Any]]:
            if not keyword:
                return []
            return await seedhub_service.search_magnets_by_keyword(keyword, limit=20)

        async def _butailing() -> list[dict[str, Any]]:
            if not keyword:
                return []
            return await butailing_service.search_magnets(
                keyword, media_type=media_type
            )

        seedhub_result, butailing_result = await asyncio.gather(
            _seedhub(),
            _butailing(),
            return_exceptions=True,
        )

        merged: list[dict[str, Any]] = []
        for label, result in [
            ("SeedHub", seedhub_result),
            ("不太灵", butailing_result),
        ]:
            if isinstance(result, BaseException):
                traces.append(
                    {
                        "step": "fetch_offline_magnet_error",
                        "status": "warning",
                        "message": f"{label} 磁力抓取失败: {str(result)[:200]}",
                    }
                )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.item.fetch_offline_source",
                    status="warning",
                    message=f"[{sub.title}] 离线来源 {label} 抓取失败：{str(result)[:200]}",
                    extra={
                        "subscription_id": sub.id,
                        "title": sub.title,
                        "source": label,
                        "error": str(result)[:300],
                    },
                )
            elif result:
                merged.extend(result)
                traces.append(
                    {
                        "step": "fetch_offline_magnet_done",
                        "status": "info",
                        "message": f"{label} 磁力资源 {len(result)} 条",
                        "payload": {"source": label, "count": len(result)},
                    }
                )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.item.fetch_offline_source",
                    status="success",
                    message=f"[{sub.title}] 离线来源 {label} 返回 {len(result)} 条磁力资源",
                    extra={
                        "subscription_id": sub.id,
                        "title": sub.title,
                        "source": label,
                        "count": len(result),
                    },
                )

        if merged:
            traces.append(
                {
                    "step": "fetch_offline_magnet_summary",
                    "status": "success",
                    "message": f"离线磁力资源合计 {len(merged)} 条",
                    "payload": {"total": len(merged)},
                }
            )

        return merged, traces

    def _build_hdhive_unlock_context(self) -> dict[str, Any]:
        budget_total = runtime_settings_service.get_subscription_hdhive_unlock_budget_points_per_run()
        return {
            "enabled": runtime_settings_service.get_subscription_hdhive_auto_unlock_enabled(),
            "max_points_per_item": runtime_settings_service.get_subscription_hdhive_unlock_max_points_per_item(),
            "budget_total": budget_total,
            "budget_left": budget_total,
            "threshold_inclusive": runtime_settings_service.get_subscription_hdhive_unlock_threshold_inclusive(),
            "consecutive_failed_limit": 3,
            "consecutive_failed_count": 0,
            "request_interval_seconds": 0.35,
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

    async def _prepare_hdhive_locked_resources(
        self,
        resources: list[dict[str, Any]],
        context: dict[str, Any],
        traces: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized_items = self._normalize_hdhive_subscription_items(resources)
        if not normalized_items:
            return normalized_items

        enabled = bool(context.get("enabled", False))
        max_points = int(context.get("max_points_per_item", 10) or 10)
        budget_total = int(context.get("budget_total", 30) or 30)
        budget_left = int(context.get("budget_left", budget_total) or budget_total)
        threshold_inclusive = bool(context.get("threshold_inclusive", True))
        traces.append(
            {
                "step": "hdhive_unlock_policy",
                "status": "info",
                "message": (
                    "HDHive 解锁策略已加载"
                    if enabled
                    else "HDHive 自动积分解锁未启用，锁定资源将跳过自动解锁"
                ),
                "payload": {
                    "enabled": enabled,
                    "max_points_per_item": max_points,
                    "budget_total": budget_total,
                    "budget_left": budget_left,
                    "threshold_inclusive": threshold_inclusive,
                },
            }
        )

        stats = context.setdefault(
            "stats",
            {
                "attempted": 0,
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "points_spent": 0,
            },
        )
        local_attempted = 0
        local_success = 0
        local_failed = 0
        local_skipped = 0
        local_points_spent = 0
        for item in normalized_items:
            if not isinstance(item, dict):
                continue
            if str(item.get("source_service") or "").strip().lower() != "hdhive":
                continue

            if self._extract_resource_url(item):
                continue

            slug = str(item.get("slug") or "").strip()
            unlock_points = self._safe_int(item.get("unlock_points"), default=0)
            locked = bool(item.get("hdhive_locked")) or (
                unlock_points > 0 and not self._extract_resource_url(item)
            )
            if not locked:
                continue

            skip_reason = ""
            if not enabled:
                skip_reason = "disabled"
            elif not slug:
                skip_reason = "missing_slug"
            elif unlock_points <= 0:
                skip_reason = "invalid_unlock_points"
            elif not self._allow_unlock_by_threshold(
                unlock_points, max_points, threshold_inclusive
            ):
                skip_reason = "over_threshold"
            elif context.get("stopped_by_circuit"):
                skip_reason = "circuit_open"
            elif unlock_points > int(context.get("budget_left", 0) or 0):
                skip_reason = "budget_exceeded"

            if skip_reason:
                local_skipped += 1
                stats["skipped"] = int(stats.get("skipped") or 0) + 1
                traces.append(
                    {
                        "step": "hdhive_unlock_item_skip",
                        "status": "warning",
                        "message": f"跳过资源解锁: {slug or 'unknown'} ({skip_reason})",
                        "payload": {
                            "slug": slug,
                            "unlock_points": unlock_points,
                            "reason": skip_reason,
                            "budget_left": int(context.get("budget_left", 0) or 0),
                        },
                    }
                )
                continue

            traces.append(
                {
                    "step": "hdhive_unlock_item_start",
                    "status": "info",
                    "message": f"开始自动解锁资源: {slug}",
                    "payload": {
                        "slug": slug,
                        "unlock_points": unlock_points,
                        "budget_remaining_before": int(
                            context.get("budget_left", 0) or 0
                        ),
                    },
                }
            )

            stats["attempted"] = int(stats.get("attempted") or 0) + 1
            local_attempted += 1
            try:
                unlock_result = await hdhive_service.unlock_resource(slug)
                unlock_message = str(unlock_result.get("message") or "").strip()
                share_link = self._normalize_share_url(
                    str(unlock_result.get("share_link") or "").strip()
                )
                if share_link:
                    item["pan115_share_link"] = share_link
                    item["share_link"] = share_link
                    item["pan115_savable"] = True
                    context["budget_left"] = max(
                        0, int(context.get("budget_left", 0) or 0) - unlock_points
                    )
                    context["consecutive_failed_count"] = 0
                    stats["success"] = int(stats.get("success") or 0) + 1
                    stats["points_spent"] = (
                        int(stats.get("points_spent") or 0) + unlock_points
                    )
                    local_success += 1
                    local_points_spent += unlock_points
                    traces.append(
                        {
                            "step": "hdhive_unlock_item_done",
                            "status": "success",
                            "message": f"资源解锁成功: {slug}",
                            "payload": {
                                "slug": slug,
                                "unlock_points": unlock_points,
                                "budget_remaining_after": int(
                                    context.get("budget_left", 0) or 0
                                ),
                            },
                        }
                    )
                else:
                    context["consecutive_failed_count"] = (
                        int(context.get("consecutive_failed_count", 0) or 0) + 1
                    )
                    stats["failed"] = int(stats.get("failed") or 0) + 1
                    local_failed += 1
                    traces.append(
                        {
                            "step": "hdhive_unlock_item_failed",
                            "status": "failed",
                            "message": f"资源解锁失败: {slug}",
                            "payload": {
                                "slug": slug,
                                "unlock_points": unlock_points,
                                "error": unlock_message or "解锁后未获取可转存链接",
                            },
                        }
                    )
                    if self._should_stop_unlocking_on_message(unlock_message):
                        context["stopped_by_circuit"] = True
                        context["stopped_reason"] = unlock_message or "unlock_error"
            except Exception as exc:
                context["consecutive_failed_count"] = (
                    int(context.get("consecutive_failed_count", 0) or 0) + 1
                )
                stats["failed"] = int(stats.get("failed") or 0) + 1
                local_failed += 1
                message = str(exc)[:300]
                traces.append(
                    {
                        "step": "hdhive_unlock_item_failed",
                        "status": "failed",
                        "message": f"资源解锁失败: {slug}",
                        "payload": {
                            "slug": slug,
                            "unlock_points": unlock_points,
                            "error": message,
                        },
                    }
                )
                if self._should_stop_unlocking_on_message(message):
                    context["stopped_by_circuit"] = True
                    context["stopped_reason"] = message

            failed_count = int(context.get("consecutive_failed_count", 0) or 0)
            if failed_count >= int(context.get("consecutive_failed_limit", 3) or 3):
                context["stopped_by_circuit"] = True
                if not str(context.get("stopped_reason") or "").strip():
                    context["stopped_reason"] = f"连续失败 {failed_count} 次"

            if context.get("stopped_by_circuit"):
                traces.append(
                    {
                        "step": "hdhive_unlock_stop",
                        "status": "warning",
                        "message": "触发 HDHive 解锁熔断，本订阅剩余锁定资源停止自动解锁",
                        "payload": {
                            "reason": str(context.get("stopped_reason") or "unknown"),
                            "consecutive_failed_count": int(
                                context.get("consecutive_failed_count", 0) or 0
                            ),
                            "budget_left": int(context.get("budget_left", 0) or 0),
                        },
                    }
                )
                break

            await asyncio.sleep(
                float(context.get("request_interval_seconds", 0.35) or 0.35)
            )

        traces.append(
            {
                "step": "hdhive_unlock_summary",
                "status": "info",
                "message": (
                    f"HDHive 自动解锁汇总: 尝试 {local_attempted}，"
                    f"成功 {local_success}，失败 {local_failed}，"
                    f"跳过 {local_skipped}，消耗 {local_points_spent} 积分"
                ),
                "payload": {
                    "attempted": local_attempted,
                    "success": local_success,
                    "failed": local_failed,
                    "skipped": local_skipped,
                    "points_spent": local_points_spent,
                    "total_attempted": int(stats.get("attempted") or 0),
                    "total_success": int(stats.get("success") or 0),
                    "total_failed": int(stats.get("failed") or 0),
                    "total_skipped": int(stats.get("skipped") or 0),
                    "total_points_spent": int(stats.get("points_spent") or 0),
                    "budget_left": int(context.get("budget_left", 0) or 0),
                    "unlocked_count": local_success,
                    "stopped_by_circuit": bool(context.get("stopped_by_circuit")),
                },
            }
        )
        return normalized_items

    @staticmethod
    def _allow_unlock_by_threshold(
        unlock_points: int, threshold: int, inclusive: bool
    ) -> bool:
        if inclusive:
            return unlock_points <= threshold
        return unlock_points < threshold

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _should_stop_unlocking_on_message(message: str) -> bool:
        text = str(message or "").lower()
        if not text:
            return False
        stop_tokens = (
            "积分不足",
            "余额不足",
            "token",
            "unauthorized",
            "forbidden",
            "cookie",
            "登录",
            "认证",
        )
        return any(token in text for token in stop_tokens)

    async def _store_new_resources(
        self,
        db: AsyncSession,
        subscription_id: int,
        resources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from app.models.models import MediaStatus

        if not resources:
            return {
                "created_records": [],
                "checked_count": 0,
                "duplicate_count": 0,
                "duplicate_urls": [],
                "invalid_count": 0,
            }

        with db.no_autoflush:
            existing_result = await db.execute(
                select(DownloadRecord.resource_url).where(
                    DownloadRecord.subscription_id == subscription_id
                )
            )
        existing_urls = {str(row[0]) for row in existing_result.all() if row and row[0]}

        offline_enabled = (
            runtime_settings_service.get_subscription_offline_transfer_enabled()
        )
        created_records: list[DownloadRecord] = []
        duplicate_urls: set[str] = set()
        duplicate_count = 0
        invalid_count = 0
        for item in resources:
            resource_url = self._extract_resource_url(item)
            resource_type = "pan115"
            if not resource_url and offline_enabled:
                resource_url = self._extract_offline_url(item)
                if resource_url:
                    resource_type = self._determine_resource_type(resource_url)
            if not resource_url:
                invalid_count += 1
                continue
            if resource_url in existing_urls:
                duplicate_count += 1
                duplicate_urls.add(resource_url)
                continue

            record = DownloadRecord(
                subscription_id=subscription_id,
                resource_name=self._extract_resource_name(item),
                resource_url=resource_url,
                resource_type=resource_type,
                status=MediaStatus.MATCHED,
            )
            db.add(record)
            existing_urls.add(resource_url)
            created_records.append(record)

        return {
            "created_records": created_records,
            "checked_count": len(resources),
            "duplicate_count": duplicate_count,
            "duplicate_urls": list(duplicate_urls),
            "invalid_count": invalid_count,
        }

    async def _load_retryable_records(
        self, db: AsyncSession, subscription_id: int
    ) -> list[DownloadRecord]:
        from app.models.models import MediaStatus

        with db.no_autoflush:
            failed_result = await db.execute(
                select(DownloadRecord)
                .where(
                    DownloadRecord.subscription_id == subscription_id,
                    DownloadRecord.status == MediaStatus.FAILED,
                )
                .order_by(DownloadRecord.created_at.desc())
                .limit(8)
            )
            pending_result = await db.execute(
                select(DownloadRecord)
                .where(
                    DownloadRecord.subscription_id == subscription_id,
                    DownloadRecord.status.in_((MediaStatus.PENDING, MediaStatus.MATCHED)),
                )
                .order_by(DownloadRecord.created_at.desc())
                .limit(5)
            )

        failed_rows = list(failed_result.scalars().all())
        pending_rows = list(pending_result.scalars().all())

        retryable: list[DownloadRecord] = []
        for row in failed_rows:
            is_offline = str(row.resource_type or "") in ("magnet", "ed2k")
            if not is_offline and not self._is_likely_115_share_identifier(
                row.resource_url
            ):
                continue
            if not self._is_retryable_transfer_error(row.error_message or ""):
                continue
            retryable.append(row)

        for row in pending_rows:
            is_offline = str(row.resource_type or "") in ("magnet", "ed2k")
            if not is_offline and not self._is_likely_115_share_identifier(
                row.resource_url
            ):
                continue
            retryable.append(row)

        return retryable

    async def _load_force_retry_records(
        self,
        db: AsyncSession,
        subscription_id: int,
        duplicate_urls: list[str],
    ) -> list[DownloadRecord]:
        from app.models.models import MediaStatus

        url_values = [
            str(item or "").strip()
            for item in duplicate_urls
            if str(item or "").strip()
        ]
        if not url_values:
            return []

        with db.no_autoflush:
            rows_result = await db.execute(
                select(DownloadRecord)
                .where(
                    DownloadRecord.subscription_id == subscription_id,
                    DownloadRecord.resource_url.in_(url_values),
                    DownloadRecord.status.in_(
                        (MediaStatus.FAILED, MediaStatus.PENDING, MediaStatus.MATCHED)
                    ),
                )
                .order_by(DownloadRecord.created_at.desc())
            )

        selected: list[DownloadRecord] = []
        seen_urls: set[str] = set()
        for row in rows_result.scalars().all():
            key = str(row.resource_url or "").strip()
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            selected.append(row)
        return selected

    @staticmethod
    def _exclude_new_records(
        retry_records: list[DownloadRecord], new_records: list[DownloadRecord]
    ) -> list[DownloadRecord]:
        new_keys: set[str] = set()
        for item in new_records:
            if not item:
                continue
            new_keys.add(str(item.resource_url or "").strip())
        if not new_keys:
            return retry_records
        return [
            item
            for item in retry_records
            if str(item.resource_url or "").strip() not in new_keys
        ]

    @staticmethod
    def _merge_records(
        primary: list[DownloadRecord], secondary: list[DownloadRecord]
    ) -> list[DownloadRecord]:
        merged: list[DownloadRecord] = []
        seen_keys: set[str] = set()
        for record in primary + secondary:
            if not record:
                continue
            key = (
                f"id:{record.id}"
                if record.id is not None
                else f"url:{record.resource_url}"
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(record)
        return merged

    async def _auto_save_resources(
        self,
        db: AsyncSession,
        run_id: str,
        channel: str,
        sub: "SubscriptionSnapshot",
        records: list[DownloadRecord],
        source: str,
        tv_missing_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.models.models import MediaStatus

        runtime_cookie = runtime_settings_service.get_pan115_cookie()
        pan_service = Pan115Service(runtime_cookie)
        # 订阅自动转存应使用“默认转存文件夹”，而不是离线下载目录。
        default_folder_id = runtime_settings_service.get_pan115_default_folder().get(
            "folder_id", "0"
        )
        parent_folder_id = str(default_folder_id or "0")

        saved = 0
        failed = 0
        errors: list[dict[str, Any]] = []
        tv_missing_enabled = False
        missing_episodes: set[tuple[int, int]] = set()
        is_tv_subscription = sub.media_type == MediaType.TV and sub.tmdb_id is not None
        subscription_completed = False
        cleanup_step = ""
        cleanup_message = ""
        cleanup_payload: dict[str, Any] = {}

        if is_tv_subscription:
            tv_missing_result = tv_missing_snapshot
            if tv_missing_result is None:
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=channel,
                    subscription_id=sub.id,
                    subscription_title=sub.title,
                    step="tv_missing_fetch_start",
                    status="info",
                    message="正在检查剧集的缺集状态",
                    payload={"tmdb_id": sub.tmdb_id},
                )
                tv_missing_result = await tv_missing_service.get_tv_missing_status(
                    sub.tmdb_id,
                    include_specials=bool(sub.tv_include_specials),
                    season_number=sub.tv_season_number
                    if sub.tv_scope in {"season", "episode_range"}
                    else None,
                    episode_start=sub.tv_episode_start
                    if sub.tv_scope == "episode_range"
                    else None,
                    episode_end=sub.tv_episode_end
                    if sub.tv_scope == "episode_range"
                    else None,
                    aired_only=sub.tv_follow_mode == "new",
                )
            if str(tv_missing_result.get("status") or "") == "ok":
                tv_missing_enabled = True
                missing_episodes = {
                    (int(pair[0]), int(pair[1]))
                    for pair in (tv_missing_result.get("missing_episodes") or [])
                    if isinstance(pair, (list, tuple)) and len(pair) == 2
                }
                if tv_missing_snapshot is None:
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=channel,
                        subscription_id=sub.id,
                        subscription_title=sub.title,
                        step="tv_missing_fetch_done",
                        status="success",
                        message=f"缺集检查完成：共 {int(counts.get('aired') or 0)} 集，已有 {int(counts.get('existing') or 0)} 集，缺失 {len(missing_episodes)} 集",
                        payload={
                            "aired_count": int(
                                (tv_missing_result.get("counts") or {}).get("aired")
                                or 0
                            ),
                            "existing_count": int(
                                (tv_missing_result.get("counts") or {}).get("existing")
                                or 0
                            ),
                            "missing_count": len(missing_episodes),
                        },
                    )
            elif tv_missing_snapshot is None:
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=channel,
                    subscription_id=sub.id,
                    subscription_title=sub.title,
                        step="tv_missing_fetch_failed",
                        status="warning",
                        message=f"缺集检查失败，将按全量转存处理：{tv_missing_result.get('message') or '未知错误'}",
                    payload={
                        "status": tv_missing_result.get("status"),
                        "message": tv_missing_result.get("message"),
                    },
                )

        for record in records:
            await self._create_step_log(
                db,
                run_id=run_id,
                channel=channel,
                subscription_id=sub.id,
                subscription_title=sub.title,
                    step="auto_transfer_item_start",
                    status="info",
                    message=f"正在处理资源：{record.resource_name}",
                payload={
                    "source": source,
                    "record_id": record.id,
                    "resource_url": record.resource_url,
                },
            )
            try:
                # 磁力/ED2K 离线下载路径
                if str(record.resource_type or "") in ("magnet", "ed2k"):
                    offline_folder_id = str(
                        runtime_settings_service.get_pan115_offline_folder().get(
                            "folder_id", "0"
                        )
                        or "0"
                    )
                    record.status = MediaStatus.DOWNLOADING
                    async with transfer_guard_service.acquire("订阅离线下载提交"):
                        offline_result = await pan_service.offline_task_add(
                            url=record.resource_url,
                            wp_path_id=offline_folder_id,
                        )
                    record.status = MediaStatus.OFFLINE_SUBMITTED
                    record.offline_submitted_at = datetime.utcnow()
                    record.offline_status = "submitted"
                    record.offline_info_hash = (
                        self._extract_offline_info_hash(offline_result)
                        or self._extract_hash_from_offline_url(record.resource_url)
                    )
                    record.offline_task_id = self._extract_offline_task_id(
                        offline_result
                    )
                    record.completed_at = None
                    record.error_message = None
                    record.file_id = offline_folder_id
                    saved += 1
                    await self._notify_transfer_success(
                        sub.title,
                        record.resource_name,
                        source,
                        "离线下载",
                        getattr(sub, "poster_path", None),
                    )
                    await operation_log_service.log_background_event(
                        source_type="background_task",
                        module="subscriptions",
                        action="subscription.offline_transfer",
                        status="success",
                        message=f"[{sub.title}] 离线下载已提交：{record.resource_name}（{record.resource_type}）",
                        extra={
                            "subscription_id": sub.id,
                            "resource_type": record.resource_type,
                            "source": source,
                            "record_id": record.id,
                            "offline_info_hash": record.offline_info_hash,
                            "offline_task_id": record.offline_task_id,
                        },
                    )
                    # 发送转存成功事件到 Kafka
                    try:
                        from app.analytics import kafka_producer

                        if kafka_producer._enabled:
                            kafka_producer.send(
                                event_type="transfer_success",
                                data={
                                    "subscription_id": sub.id,
                                    "title": sub.title,
                                    "source": source,
                                    "resource_name": record.resource_name,
                                    "transfer_type": "offline",
                                    "status": "offline_submitted",
                                },
                                key=str(sub.id),
                            )
                    except Exception:
                        pass
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=channel,
                        subscription_id=sub.id,
                        subscription_title=sub.title,
                        step="auto_transfer_offline_done",
                        status="success",
                        message=f"已提交离线下载，等待完成后自动入库：{record.resource_name}",
                        payload={
                            "source": source,
                            "record_id": record.id,
                            "resource_type": record.resource_type,
                            "target_folder_id": offline_folder_id,
                            "offline_info_hash": record.offline_info_hash,
                            "offline_task_id": record.offline_task_id,
                        },
                    )
                    if sub.media_type != MediaType.TV:
                        # 离线提交不再等同完成；等待 offline_monitor 绑定 hash 后确认完成。
                        break
                    continue

                share_link, receive_code = self._split_share_link_and_receive_code(
                    record.resource_url
                )
                record.status = MediaStatus.TRANSFERRING
                if tv_missing_enabled and is_tv_subscription:
                    share_code = pan_service._extract_share_code(share_link)
                    if not share_code:
                        raise ValueError("无效的分享链接，无法提取分享码")

                    all_files = await pan_service.get_share_all_files_recursive(
                        share_code, receive_code
                    )
                    matched_candidates: dict[tuple[int, int], list[dict[str, Any]]] = {}
                    parsed_count = 0
                    unparsed_video_count = 0

                    for item in all_files:
                        if not isinstance(item, dict):
                            continue
                        fid = str(item.get("fid") or "").strip()
                        filename = str(item.get("name") or "").strip()
                        if not fid or not filename:
                            continue
                        is_video_file = self._is_video_filename(filename)
                        if not is_video_file:
                            continue
                        parsed = name_parser.parse_episode(filename)
                        if parsed:
                            parsed_count += 1
                            pair = (int(parsed[0]), int(parsed[1]))
                            if pair in missing_episodes:
                                matched_candidates.setdefault(pair, []).append(item)
                            continue
                        unparsed_video_count += 1

                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=channel,
                        subscription_id=sub.id,
                        subscription_title=sub.title,
                        step="tv_record_files_parsed",
                        status="info",
                        message=f"已解析资源文件，找到 {sum(len(items) for items in matched_candidates.values())} 个匹配缺集的文件：{record.resource_name}",
                        payload={
                            "record_id": record.id,
                            "total_files": len(all_files),
                            "parsed_count": parsed_count,
                            "matched_missing_count": sum(
                                len(items) for items in matched_candidates.values()
                            ),
                            "unparsed_video_count": unparsed_video_count,
                            "remaining_missing_count": len(missing_episodes),
                        },
                    )

                    selected_items: list[dict[str, Any]] = []
                    for items in matched_candidates.values():
                        if len(items) > 1:
                            selected_items.append(
                                pan_service.pick_best_video_file(items) or items[0]
                            )
                        else:
                            selected_items.extend(items)
                    selected_file_ids = list(
                        dict.fromkeys(
                            [
                                str(item.get("fid"))
                                for item in selected_items
                                if item.get("fid")
                            ]
                        )
                    )
                    matched_pairs = set(matched_candidates.keys())
                    selected_mode = "missing"

                    if not selected_file_ids:
                        record.status = MediaStatus.MATCHED
                        record.completed_at = None
                        record.error_message = None
                        await self._create_step_log(
                            db,
                            run_id=run_id,
                            channel=channel,
                            subscription_id=sub.id,
                            subscription_title=sub.title,
                        step="tv_record_skip_no_missing",
                        status="info",
                        message=f"该资源不包含需要的集数，已跳过：{record.resource_name}",
                            payload={
                                "record_id": record.id,
                                "remaining_missing_count": len(missing_episodes),
                            },
                        )
                        continue

                    async with transfer_guard_service.acquire("订阅剧集精准转存"):
                        result = await pan_service.save_share_files_directly(
                            share_url=share_link,
                            file_ids=selected_file_ids,
                            parent_id=parent_folder_id,
                            receive_code=receive_code,
                        )

                    if selected_mode == "missing":
                        for pair in matched_pairs:
                            missing_episodes.discard(pair)
                    record.status = MediaStatus.ARCHIVING
                    record.completed_at = None
                    record.error_message = None
                    record.file_id = parent_folder_id
                    saved += 1
                    await self._notify_transfer_success(
                        sub.title,
                        record.resource_name,
                        source,
                        "精准转存",
                        getattr(sub, "poster_path", None),
                    )
                    await media_postprocess_service.trigger_archive_after_transfer(
                        trigger="subscription_transfer"
                    )
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=channel,
                        subscription_id=sub.id,
                        subscription_title=sub.title,
                        step="tv_transfer_selected_done",
                        status="success",
                        message=f"已转存 {len(selected_file_ids)} 个文件到网盘（还剩 {len(missing_episodes)} 集待补）：{record.resource_name}",
                        payload={
                            "source": source,
                            "record_id": record.id,
                            "selected_mode": selected_mode,
                            "selected_count": len(selected_file_ids),
                            "remaining_missing_count": len(missing_episodes),
                            "target_parent_id": parent_folder_id,
                            "save_mode": "direct",
                        },
                    )
                    await operation_log_service.log_background_event(
                        source_type="background_task",
                        module="subscriptions",
                        action="subscription.record.transfer_ok",
                        status="success",
                        message=f"[{sub.title}] [{source}] 精准转存成功：{record.resource_name}（选中 {len(selected_file_ids)} 个文件，剩余缺集 {len(missing_episodes)} 集）",
                        trace_id=run_id,
                        extra={
                            "subscription_id": sub.id,
                            "record_id": record.id,
                            "source": source,
                            "selected_count": len(selected_file_ids),
                            "remaining_missing": len(missing_episodes),
                        },
                    )
                    # 发送转存成功事件到 Kafka
                    try:
                        from app.analytics import kafka_producer

                        if kafka_producer._enabled:
                            kafka_producer.send(
                                event_type="transfer_success",
                                data={
                                    "subscription_id": sub.id,
                                    "title": sub.title,
                                    "source": source,
                                    "resource_name": record.resource_name,
                                    "transfer_type": "precise",
                                    "status": "success",
                                    "selected_count": len(selected_file_ids),
                                },
                                key=str(sub.id),
                            )
                    except Exception:
                        pass
                    if not missing_episodes:
                        subscription_completed = True
                        cleanup_step = (
                            "subscription_cleanup_tv_completed_after_transfer"
                        )
                        cleanup_message = "剧集缺集已补齐，已自动删除订阅"
                        cleanup_payload = {
                            "source": source,
                            "record_id": record.id,
                            "remaining_missing_count": 0,
                            "target_parent_id": parent_folder_id,
                            "save_mode": "direct",
                        }
                        break
                else:
                    async with transfer_guard_service.acquire("订阅分享转存"):
                        result = await pan_service.save_share_directly(
                            share_url=share_link,
                            parent_id=parent_folder_id,
                            receive_code=receive_code,
                        )
                    record.status = MediaStatus.COMPLETED
                    record.completed_at = datetime.utcnow()
                    record.error_message = None
                    record.file_id = parent_folder_id
                    saved += 1
                    await self._notify_transfer_success(
                        sub.title,
                        record.resource_name,
                        source,
                        "分享转存",
                        getattr(sub, "poster_path", None),
                    )
                    await media_postprocess_service.trigger_archive_after_transfer(
                        trigger="subscription_transfer"
                    )
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=channel,
                        subscription_id=sub.id,
                        subscription_title=sub.title,
                        step="auto_transfer_item_done",
                        status="success",
                        message=f"转存成功：{record.resource_name}",
                        payload={
                            "source": source,
                            "record_id": record.id,
                            "target_parent_id": parent_folder_id,
                            "save_mode": "direct",
                        },
                    )
                    await operation_log_service.log_background_event(
                        source_type="background_task",
                        module="subscriptions",
                        action="subscription.record.transfer_ok",
                        status="success",
                        message=f"[{sub.title}] [{source}] 分享转存成功：{record.resource_name}",
                        trace_id=run_id,
                        extra={
                            "subscription_id": sub.id,
                            "record_id": record.id,
                            "source": source,
                            "save_mode": "direct",
                        },
                    )
                    # 发送转存成功事件到 Kafka
                    try:
                        from app.analytics import kafka_producer

                        if kafka_producer._enabled:
                            kafka_producer.send(
                                event_type="transfer_success",
                                data={
                                    "subscription_id": sub.id,
                                    "title": sub.title,
                                    "source": source,
                                    "resource_name": record.resource_name,
                                    "transfer_type": "share",
                                    "status": "success",
                                },
                                key=str(sub.id),
                            )
                    except Exception:
                        pass
                    subscription_completed = True
                    cleanup_step = "subscription_cleanup_transferred"
                    cleanup_message = "转存成功，已自动删除订阅"
                    cleanup_payload = {
                        "source": source,
                        "record_id": record.id,
                        "target_parent_id": parent_folder_id,
                        "save_mode": "direct",
                    }
                    break
            except Exception as exc:
                if self._is_already_received_error(str(exc)):
                    # 115 返回已接收时视为成功，避免重复任务被统计为失败。
                    if tv_missing_enabled and is_tv_subscription:
                        record.status = MediaStatus.ARCHIVING
                        record.completed_at = None
                    else:
                        record.status = MediaStatus.COMPLETED
                        record.completed_at = datetime.utcnow()
                    record.error_message = None
                    saved += 1
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=channel,
                        subscription_id=sub.id,
                        subscription_title=sub.title,
                        step="auto_transfer_item_done",
                        status="success",
                        message=f"资源已在网盘中，无需重复转存：{record.resource_name}",
                        payload={
                            "source": source,
                            "record_id": record.id,
                            "reason": "already_received",
                        },
                    )
                    await operation_log_service.log_background_event(
                        source_type="background_task",
                        module="subscriptions",
                        action="subscription.record.transfer_ok",
                        status="success",
                        message=f"[{sub.title}] [{source}] 资源已在网盘中：{record.resource_name}",
                        trace_id=run_id,
                        extra={
                            "subscription_id": sub.id,
                            "record_id": record.id,
                            "source": source,
                            "reason": "already_received",
                        },
                    )
                    if not is_tv_subscription:
                        subscription_completed = True
                        cleanup_step = "subscription_cleanup_transferred"
                        cleanup_message = "资源已在网盘中，已自动删除订阅"
                        cleanup_payload = {
                            "source": source,
                            "record_id": record.id,
                            "reason": "already_received",
                            "target_parent_id": parent_folder_id,
                            "save_mode": "direct",
                        }
                        break
                    continue
                record.status = MediaStatus.FAILED
                record.error_message = str(exc)[:1000]
                failed += 1
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=channel,
                    subscription_id=sub.id,
                    subscription_title=sub.title,
                        step="auto_transfer_item_failed",
                        status="failed",
                        message=f"转存失败：{record.resource_name}（{str(exc)[:100]}）",
                    payload={
                        "source": source,
                        "record_id": record.id,
                        "error": str(exc)[:500],
                    },
                )
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="subscriptions",
                    action="subscription.record.transfer_fail",
                    status="failed",
                    message=f"[{sub.title}] [{source}] 转存失败：{record.resource_name}（{str(exc)[:200]}）",
                    trace_id=run_id,
                    extra={
                        "subscription_id": sub.id,
                        "record_id": record.id,
                        "source": source,
                        "error": str(exc)[:300],
                    },
                )
                errors.append(
                    {
                        "source": source,
                        "subscription_id": sub.id,
                        "title": sub.title,
                        "resource": record.resource_name,
                        "error": str(exc),
                    }
                )

        return {
            "saved": saved,
            "failed": failed,
            "errors": errors,
            "subscription_completed": subscription_completed,
            "cleanup_step": cleanup_step,
            "cleanup_message": cleanup_message,
            "cleanup_payload": cleanup_payload,
            "remaining_missing_count": len(missing_episodes)
            if tv_missing_enabled
            else None,
        }

    async def _create_execution_log(
        self,
        db: AsyncSession,
        channel: str,
        status: ExecutionStatus,
        message: str,
        checked_count: int,
        new_resource_count: int,
        failed_count: int,
        details: list[dict[str, Any]],
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        log = SubscriptionExecutionLog(
            channel=channel,
            status=status,
            message=message,
            checked_count=checked_count,
            new_resource_count=new_resource_count,
            failed_count=failed_count,
            details=json.dumps(details, ensure_ascii=False) if details else None,
            started_at=started_at,
            finished_at=finished_at,
        )
        db.add(log)
        await db.flush()

        keep_ids_result = await db.execute(
            select(SubscriptionExecutionLog.id)
            .order_by(
                SubscriptionExecutionLog.started_at.desc(),
                SubscriptionExecutionLog.id.desc(),
            )
            .limit(5)
        )
        keep_ids = [row[0] for row in keep_ids_result.all() if row and row[0]]
        if keep_ids:
            await db.execute(
                delete(SubscriptionExecutionLog).where(
                    SubscriptionExecutionLog.id.notin_(keep_ids)
                )
            )

    @staticmethod
    def _extract_list(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            data = payload.get("list")
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        return []

    @staticmethod
    def _normalize_share_url(url: str) -> str:
        url = url.strip()
        if not url:
            return ""
        if "#" in url:
            url = url.split("#")[0]
        url = url.replace("https://115cdn.com/", "https://115.com/")
        return url

    @staticmethod
    def _extract_resource_url(item: dict[str, Any]) -> str:
        raw_url = str(
            item.get("pan115_share_link")
            or item.get("share_link")
            or item.get("shareLink")
            or item.get("share_link")
            or item.get("share_url")
            or item.get("url")
            or ""
        ).strip()
        return SubscriptionService._normalize_share_url(raw_url)

    @staticmethod
    def _extract_offline_url(item: dict[str, Any]) -> str:
        """从资源条目中提取磁力链接或 ED2K 链接。"""
        for key in ("magnet", "magnet_link", "magnet_url"):
            val = str(item.get(key) or "").strip()
            if val and val.lower().startswith("magnet:"):
                return val
        for key in ("ed2k", "ed2k_link", "ed2k_url"):
            val = str(item.get(key) or "").strip()
            if val and val.lower().startswith("ed2k://"):
                return val
        return ""

    @staticmethod
    def _extract_hash_from_offline_url(url: str) -> str:
        raw = str(url or "").strip()
        if not raw:
            return ""
        magnet_match = re.search(r"btih:([a-zA-Z0-9]{32,40})", raw, re.IGNORECASE)
        if magnet_match:
            return magnet_match.group(1).upper()
        return ""

    @classmethod
    def _extract_offline_info_hash(cls, payload: Any) -> str:
        return cls._extract_first_nested_value(
            payload,
            {
                "info_hash",
                "infoHash",
                "hash",
                "task_hash",
                "taskHash",
            },
        )

    @classmethod
    def _extract_offline_task_id(cls, payload: Any) -> str:
        return cls._extract_first_nested_value(
            payload,
            {
                "task_id",
                "taskId",
                "taskid",
                "id",
            },
        )

    @classmethod
    def _extract_first_nested_value(cls, payload: Any, keys: set[str]) -> str:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in keys and value not in (None, ""):
                    return str(value).strip()
            for value in payload.values():
                found = cls._extract_first_nested_value(value, keys)
                if found:
                    return found
        if isinstance(payload, list):
            for item in payload:
                found = cls._extract_first_nested_value(item, keys)
                if found:
                    return found
        return ""

    @staticmethod
    def _parse_json_list_field(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            import json as _json
            parsed = _json.loads(value)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if v]
        except Exception:
            pass
        return []

    def _resolve_subscription_resolutions(self, sub: "SubscriptionSnapshot") -> list[str]:
        return self._parse_json_list_field(getattr(sub, "preferred_resolutions", None)) or runtime_settings_service.get_resource_preferred_resolutions()

    def _resolve_subscription_formats(self, sub: "SubscriptionSnapshot") -> list[str]:
        return self._parse_json_list_field(getattr(sub, "preferred_codecs", None)) or runtime_settings_service.get_resource_preferred_formats()

    def _resolve_subscription_quality_filter(self, sub: "SubscriptionSnapshot") -> dict[str, Any]:
        return {
            "preferred_resolutions": self._parse_json_list_field(getattr(sub, "preferred_resolutions", None)) or None,
            "preferred_formats": self._parse_json_list_field(getattr(sub, "preferred_codecs", None)) or None,
            "exclude_labels": self._parse_json_list_field(getattr(sub, "exclude_tags", None)) or None,
            "preferred_languages": self._parse_json_list_field(getattr(sub, "preferred_audio", None)) or None,
            "preferred_subtitles": self._parse_json_list_field(getattr(sub, "preferred_subtitles", None)) or None,
            "min_size_gb": getattr(sub, "min_size_gb", None),
            "max_size_gb": getattr(sub, "max_size_gb", None),
        }

    @staticmethod
    def _determine_resource_type(url: str) -> str:
        lowered = url.lower()
        if lowered.startswith("magnet:"):
            return "magnet"
        if lowered.startswith("ed2k://"):
            return "ed2k"
        return "pan115"

    @staticmethod
    def _extract_resource_name(item: dict[str, Any]) -> str:
        name = str(
            item.get("resource_name") or item.get("title") or item.get("name") or ""
        ).strip()
        return name or "未命名资源"

    @staticmethod
    def _build_pansou_keyword(sub: "SubscriptionSnapshot") -> str:
        if sub.year:
            return f"{sub.title} {sub.year}".strip()
        return sub.title

    @staticmethod
    def _build_hdhive_keyword(sub: "SubscriptionSnapshot") -> str:
        if sub.year:
            return f"{sub.title} {sub.year}".strip()
        return str(sub.title or "").strip()

    @staticmethod
    def _build_tg_keyword(sub: "SubscriptionSnapshot") -> str:
        return SubscriptionService._build_pansou_keyword(sub)

    @staticmethod
    def _normalize_hdhive_subscription_items(
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            if not row.get("pan115_share_link"):
                row["pan115_share_link"] = str(row.get("share_link") or "").strip()
            if not row.get("name") and row.get("resource_name"):
                row["name"] = str(row.get("resource_name") or "").strip()
            normalized.append(row)
        return normalized

    @staticmethod
    def _build_target_folder_name(sub: "SubscriptionSnapshot") -> str:
        base_name = str(sub.title or "订阅资源").strip() or "订阅资源"
        if sub.year:
            base_name = f"{base_name} ({sub.year})"
        return re.sub(r'[\\/:*?"<>|]+', "_", base_name)

    @staticmethod
    async def _notify_transfer_success(
        sub_title: str,
        resource_name: str,
        source: str,
        method: str,
        poster_path: str | None = None,
    ) -> None:
        """转存成功时通过 TG Bot 发送通知。"""
        try:
            from html import escape
            from app.services.tg_bot.notifications import tg_bot_notify

            lines = [
                f"<b>订阅转存成功</b>",
                f"订阅：{escape(sub_title)}",
                f"资源：{escape(resource_name)}",
                f"来源：{escape(source)}　方式：{escape(method)}",
            ]
            await tg_bot_notify("\n".join(lines), poster_path=poster_path)
        except Exception:
            pass

    @staticmethod
    def _split_share_link_and_receive_code(raw_link: str) -> tuple[str, str]:
        value = str(raw_link or "").strip()
        if not value:
            return "", ""

        code_receive_match = re.fullmatch(r"([A-Za-z0-9]+)-([A-Za-z0-9]{4})", value)
        if code_receive_match:
            return code_receive_match.group(1), code_receive_match.group(2)

        receive_code = ""
        for pattern in (
            r"(?:password|receive_code|pickcode|code)=([A-Za-z0-9]{4})",
            r"(?:提取码|访问码|密码)[:：\s]*([A-Za-z0-9]{4})",
        ):
            matched = re.search(pattern, value, re.IGNORECASE)
            if matched:
                receive_code = matched.group(1)
                break

        return value, receive_code

    @staticmethod
    def _is_video_filename(filename: str) -> bool:
        value = str(filename or "").strip().lower()
        if not value:
            return False
        return value.endswith(
            (".mp4", ".mkv", ".avi", ".ts", ".rmvb", ".flv", ".mov", ".wmv", ".m4v")
        )

    @staticmethod
    def _is_pan115_save_success(result: Any) -> bool:
        if isinstance(result, list):
            return True
        if not isinstance(result, dict):
            return False
        if "success" in result:
            return bool(result.get("success"))
        if "state" in result:
            return bool(result.get("state"))
        if "errNo" in result:
            return str(result.get("errNo")) == "0"
        if "code" in result:
            return str(result.get("code")) in {"0", "200"}
        return False

    @staticmethod
    def _is_likely_115_share_identifier(raw_link: str) -> bool:
        value = str(raw_link or "").strip()
        if not value:
            return False
        lowered = value.lower()
        if lowered.startswith(("http://", "https://", "//")):
            return bool(
                re.search(r"(?:115(?:cdn)?\.com|share\.115\.com|anxia\.com)", lowered)
            )
        return bool(re.fullmatch(r"[a-zA-Z0-9]+(?:-[a-zA-Z0-9]{4})?", value))

    @staticmethod
    def _is_retryable_transfer_error(error_text: str) -> bool:
        text = str(error_text or "").lower()
        if not text:
            return False
        tokens = (
            "share_api_method_not_allowed",
            "code=405",
            "code=404",
            "method not allowed",
            "nothing matches the given uri",
            "rate",
            "timeout",
            "频繁",
            "受限",
            "已有转存任务",
        )
        return any(token in text for token in tokens)

    @staticmethod
    def _is_already_received_error(error_text: str) -> bool:
        text = str(error_text or "").lower()
        if not text:
            return False
        tokens = (
            "4200045",
            "已接收",
            "重复接收",
            "already received",
        )
        return any(token in text for token in tokens)

    @staticmethod
    def _normalize_channel(channel: str) -> str:
        normalized = str(channel or "").strip().lower()
        if normalized not in {"pansou", "hdhive", "tg", "priority", "all"}:
            raise ValueError("unsupported channel")
        return normalized

    @staticmethod
    def _resolve_status(
        failed_count: int, checked_count: int, auto_failed_count: int
    ) -> ExecutionStatus:
        total_failed = failed_count + auto_failed_count
        if total_failed <= 0:
            return ExecutionStatus.SUCCESS
        if failed_count >= max(checked_count, 1):
            return ExecutionStatus.FAILED
        return ExecutionStatus.PARTIAL

    @staticmethod
    def _build_message(result: dict[str, Any]) -> str:
        parts = [
            f"共 {result['checked_count']} 个订阅",
        ]
        if result["new_resource_count"] > 0:
            parts.append(f"发现 {result['new_resource_count']} 个新资源")
        else:
            parts.append("未发现新资源")
        if result["auto_saved_count"] > 0:
            parts.append(f"转存成功 {result['auto_saved_count']} 个")
        if result["auto_failed_count"] > 0:
            parts.append(f"转存失败 {result['auto_failed_count']} 个")
        if result["cleanup_deleted_count"] > 0:
            parts.append(f"自动完成 {result['cleanup_deleted_count']} 个订阅")
        if result["failed_count"] > 0:
            parts.append(f"处理出错 {result['failed_count']} 个")
        return "，".join(parts)


subscription_service = SubscriptionService()


@dataclass(slots=True)
class SubscriptionSnapshot:
    id: int
    tmdb_id: int | None
    title: str
    media_type: MediaType
    year: str | None
    auto_download: bool
    tv_scope: str
    tv_season_number: int | None
    tv_episode_start: int | None
    tv_episode_end: int | None
    tv_follow_mode: str
    tv_include_specials: bool
    preferred_resolutions: str | None
    preferred_codecs: str | None
    preferred_hdr: str | None
    preferred_audio: str | None
    preferred_subtitles: str | None
    exclude_tags: str | None
    min_size_gb: float | None
    max_size_gb: float | None
    has_successful_transfer: bool
