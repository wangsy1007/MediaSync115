import asyncio
import json
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
from app.api.search import _normalize_pansou_pan115_list, _search_pansou_pan115_resources
from app.services.hdhive_service import hdhive_service
from app.services.nullbr_service import nullbr_service
from app.services.pan115_service import Pan115Service
from app.services.pansou_service import pansou_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.tg_service import tg_service
from app.services.tv_missing_service import tv_missing_service
from app.utils.name_parser import name_parser


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
                    DownloadRecord.file_id.is_not(None),
                    DownloadRecord.status == MediaStatus.COMPLETED,
                ),
            )
            .exists()
        )
        subs_result = await db.execute(
            select(
                Subscription.id,
                Subscription.tmdb_id,
                Subscription.title,
                Subscription.media_type,
                Subscription.year,
                Subscription.auto_download,
            )
            .where(
                Subscription.is_active == True,  # noqa: E712
                ~has_successful_transfer,
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
            message=f"任务启动，待处理订阅 {len(subscriptions)} 项",
            payload={
                "checked_count": len(subscriptions),
                "source_order": source_order,
                "scope": {
                    "is_active": True,
                    "exclude_transferred_success": True,
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
                    message="开始处理订阅",
                )
                resources, fetch_trace = await self._fetch_resources(
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
                        payload=trace.get("payload") if isinstance(trace.get("payload"), dict) else None,
                    )
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=normalized_channel,
                    subscription_id=sub_id,
                    subscription_title=sub_title,
                    step="fetch_resources",
                    status="info",
                    message=f"资源抓取完成，候选 {len(resources)} 条",
                )
                store_stats = await self._store_new_resources(db, sub_id, resources)
                created_records = store_stats["created_records"]
                duplicate_urls = store_stats["duplicate_urls"]
                result["new_resource_count"] += len(created_records)
                result["resource_checked_count"] += int(store_stats["checked_count"])
                result["resource_duplicate_count"] += int(store_stats["duplicate_count"])
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=normalized_channel,
                    subscription_id=sub_id,
                    subscription_title=sub_title,
                    step="store_new_resources",
                    status="info",
                    message=(
                        f"资源入库完成：新增 {len(created_records)} 条，"
                        f"重复 {store_stats['duplicate_count']} 条，"
                        f"无效 {store_stats['invalid_count']} 条"
                    ),
                    payload={
                        "checked_count": store_stats["checked_count"],
                        "new_count": len(created_records),
                        "duplicate_count": store_stats["duplicate_count"],
                        "invalid_count": store_stats["invalid_count"],
                    },
                )

                should_auto_download = force_auto_download or bool(sub.auto_download)
                if should_auto_download:
                    sub_saved_count = 0
                    sub_failed_transfer_count = 0
                    retry_records = []
                    if sub.auto_download:
                        retry_records = await self._load_retryable_records(db, sub_id)
                    if force_auto_download and duplicate_urls:
                        duplicate_retry_records = await self._load_force_retry_records(
                            db,
                            sub_id,
                            duplicate_urls,
                        )
                        retry_records = self._merge_records(retry_records, duplicate_retry_records)
                    retry_records = self._exclude_new_records(retry_records, created_records)

                    if created_records:
                        await self._create_step_log(
                            db,
                            run_id=run_id,
                            channel=normalized_channel,
                            subscription_id=sub_id,
                            subscription_title=sub_title,
                            step="auto_transfer_new_start",
                            status="info",
                            message=f"开始自动转存新资源 {len(created_records)} 条",
                        )
                        new_auto_stats = await self._auto_save_resources(
                            db,
                            run_id,
                            normalized_channel,
                            sub,
                            created_records,
                            source="new",
                        )
                        sub_saved_count += int(new_auto_stats.get("saved") or 0)
                        sub_failed_transfer_count += int(new_auto_stats.get("failed") or 0)
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
                            status="success" if new_auto_stats["failed"] == 0 else "partial",
                            message=(
                                f"新资源转存完成，成功 {new_auto_stats['saved']} 条，"
                                f"失败 {new_auto_stats['failed']} 条"
                            ),
                        )

                    if retry_records:
                        await self._create_step_log(
                            db,
                            run_id=run_id,
                            channel=normalized_channel,
                            subscription_id=sub_id,
                            subscription_title=sub_title,
                            step="auto_transfer_retry_start",
                            status="info",
                            message=f"开始重试历史记录 {len(retry_records)} 条",
                        )
                        retry_auto_stats = await self._auto_save_resources(
                            db,
                            run_id,
                            normalized_channel,
                            sub,
                            retry_records,
                            source="retry",
                        )
                        sub_saved_count += int(retry_auto_stats.get("saved") or 0)
                        sub_failed_transfer_count += int(retry_auto_stats.get("failed") or 0)
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
                            status="success" if retry_auto_stats["failed"] == 0 else "partial",
                            message=(
                                f"历史重试完成，成功 {retry_auto_stats['saved']} 条，"
                                f"失败 {retry_auto_stats['failed']} 条"
                            ),
                        )

                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=normalized_channel,
                        subscription_id=sub_id,
                        subscription_title=sub_title,
                        step="auto_transfer_summary",
                        status="success" if sub_failed_transfer_count == 0 else "partial",
                        message=(
                            f"自动转存汇总：成功 {sub_saved_count} 条，失败 {sub_failed_transfer_count} 条，"
                            f"新资源 {len(created_records)} 条，历史重试 {len(retry_records)} 条"
                        ),
                    )
                else:
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=normalized_channel,
                        subscription_id=sub_id,
                        subscription_title=sub_title,
                        step="auto_transfer_skip",
                        status="info",
                        message="该订阅未启用自动转存，本轮仅抓取并记录资源",
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
                    message=f"订阅处理失败: {str(exc)[:300]}",
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
                            "auto_retry_failed_count": result["auto_retry_failed_count"],
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
        result["hdhive_unlock_attempted_count"] = int(unlock_stats.get("attempted") or 0)
        result["hdhive_unlock_success_count"] = int(unlock_stats.get("success") or 0)
        result["hdhive_unlock_failed_count"] = int(unlock_stats.get("failed") or 0)
        result["hdhive_unlock_skipped_count"] = int(unlock_stats.get("skipped") or 0)
        result["hdhive_unlock_points_spent"] = int(unlock_stats.get("points_spent") or 0)
        message = self._build_message(result)
        finished_at = datetime.utcnow()
        result["finished_at"] = finished_at.isoformat()
        result["status"] = status.value
        result["message"] = message

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
                    "hdhive_unlock_attempted_count": result["hdhive_unlock_attempted_count"],
                    "hdhive_unlock_success_count": result["hdhive_unlock_success_count"],
                    "hdhive_unlock_failed_count": result["hdhive_unlock_failed_count"],
                    "hdhive_unlock_skipped_count": result["hdhive_unlock_skipped_count"],
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
                    status="failed",
                    message=f"执行收尾失败: {finalize_error[:300]}",
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
            .order_by(SubscriptionStepLog.created_at.desc(), SubscriptionStepLog.id.desc())
            .limit(1000)
            .subquery()
        )
        await db.execute(
            delete(SubscriptionStepLog).where(
                ~SubscriptionStepLog.id.in_(select(keep_ids_subquery.c.id))
            )
        )

    async def _fetch_resources(
        self,
        channel: str,
        sub: "SubscriptionSnapshot",
        hdhive_unlock_context: dict[str, Any] | None = None,
        source_order: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        traces: list[dict[str, Any]] = []
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
            return [], traces

        for source in active_order:
            source_resources: list[dict[str, Any]] = []
            source_traces: list[dict[str, Any]] = []
            try:
                if source == "nullbr":
                    source_resources, source_traces = await self._fetch_from_nullbr(sub)
                elif source == "hdhive":
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
                source_resources = []

            traces.extend(source_traces)
            if source_resources:
                traces.append(
                    {
                        "step": "fetch_source_selected",
                        "status": "success",
                        "message": f"来源 {source} 命中资源 {len(source_resources)} 条",
                        "payload": {"source": source, "count": len(source_resources)},
                    }
                )
                if source == "hdhive":
                    source_resources = await self._prepare_hdhive_locked_resources(
                        source_resources,
                        hdhive_unlock_context or self._build_hdhive_unlock_context(),
                        traces,
                    )
                return source_resources, traces

        traces.append(
            {
                "step": "fetch_all_empty",
                "status": "warning",
                "message": "所有优先级来源都未命中可用资源",
            }
        )
        return [], traces

    def _resolve_source_order(self, channel: str) -> list[str]:
        _ = channel
        priority = runtime_settings_service.get_subscription_resource_priority()
        source_order = [item for item in priority if item in {"nullbr", "hdhive", "pansou", "tg"}]
        tg_ready = bool(
            runtime_settings_service.get_tg_api_id().strip()
            and runtime_settings_service.get_tg_api_hash().strip()
            and runtime_settings_service.get_tg_session().strip()
            and runtime_settings_service.get_tg_channel_usernames()
        )
        if not tg_ready:
            source_order = [item for item in source_order if item != "tg"]
        return source_order

    async def _fetch_from_nullbr(self, sub: "SubscriptionSnapshot") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        traces: list[dict[str, Any]] = []
        if sub.tmdb_id is None:
            traces.append(
                {
                    "step": "fetch_nullbr_skip",
                    "status": "warning",
                    "message": "Nullbr 依赖 tmdb_id，当前订阅缺少 tmdb_id，已跳过",
                }
            )
            return [], traces

        traces.append(
            {
                "step": "fetch_nullbr_start",
                "status": "info",
                "message": "开始从 Nullbr 获取资源",
                "payload": {"tmdb_id": sub.tmdb_id, "media_type": sub.media_type.value},
            }
        )
        payload = await self._fetch_nullbr(sub.tmdb_id, sub.media_type)
        resources = self._extract_list(payload)
        traces.append(
            {
                "step": "fetch_nullbr_done",
                "status": "success" if resources else "warning",
                "message": f"Nullbr 返回 {len(resources)} 条候选资源",
                "payload": {"count": len(resources)},
            }
        )
        return resources, traces

    async def _fetch_from_pansou(self, sub: "SubscriptionSnapshot") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
                pansou_result = await _search_pansou_pan115_resources(sub.tmdb_id, media_type)
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

    async def _fetch_from_hdhive(self, sub: "SubscriptionSnapshot") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        traces: list[dict[str, Any]] = []
        resources: list[dict[str, Any]] = []
        if sub.tmdb_id is not None:
            try:
                traces.append(
                    {
                        "step": "fetch_hdhive_tmdb_start",
                        "status": "info",
                        "message": "开始通过 tmdb_id 调用 HDHive",
                        "payload": {"tmdb_id": sub.tmdb_id, "media_type": sub.media_type.value},
                    }
                )
                if sub.media_type == MediaType.TV:
                    resources = await hdhive_service.get_tv_pan115(sub.tmdb_id)
                else:
                    resources = await hdhive_service.get_movie_pan115(sub.tmdb_id)
                resources = self._normalize_hdhive_subscription_items(resources)
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
        keyword_resources = await hdhive_service.get_pan115_by_keyword(keyword, media_type=media_type)
        keyword_resources = self._normalize_hdhive_subscription_items(keyword_resources)
        traces.append(
            {
                "step": "fetch_hdhive_keyword_done",
                "status": "success" if keyword_resources else "warning",
                "message": f"HDHive(关键词) 返回 {len(keyword_resources)} 条候选资源",
                "payload": {"count": len(keyword_resources)},
            }
        )
        return keyword_resources, traces

    async def _fetch_from_tg(self, sub: "SubscriptionSnapshot") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
        resources = await tg_service.search_115_by_keyword(keyword, media_type=media_type)
        traces.append(
            {
                "step": "fetch_tg_keyword_done",
                "status": "success" if resources else "warning",
                "message": f"Telegram 返回 {len(resources)} 条候选资源",
                "payload": {"count": len(resources)},
            }
        )
        return resources, traces

    async def _fetch_nullbr(self, tmdb_id: int, media_type: MediaType) -> dict[str, Any]:
        if media_type == MediaType.TV:
            return await asyncio.to_thread(nullbr_service.get_tv_pan115, tmdb_id, 1)
        return await asyncio.to_thread(nullbr_service.get_movie_pan115, tmdb_id, 1)

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
            {"attempted": 0, "success": 0, "failed": 0, "skipped": 0, "points_spent": 0},
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
            locked = bool(item.get("hdhive_locked")) or (unlock_points > 0 and not self._extract_resource_url(item))
            if not locked:
                continue

            skip_reason = ""
            if not enabled:
                skip_reason = "disabled"
            elif not slug:
                skip_reason = "missing_slug"
            elif unlock_points <= 0:
                skip_reason = "invalid_unlock_points"
            elif not self._allow_unlock_by_threshold(unlock_points, max_points, threshold_inclusive):
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
                        "budget_remaining_before": int(context.get("budget_left", 0) or 0),
                    },
                }
            )

            stats["attempted"] = int(stats.get("attempted") or 0) + 1
            local_attempted += 1
            try:
                unlock_result = await hdhive_service.unlock_resource(slug)
                unlock_message = str(unlock_result.get("message") or "").strip()
                share_link = self._normalize_share_url(str(unlock_result.get("share_link") or "").strip())
                if share_link:
                    item["pan115_share_link"] = share_link
                    item["share_link"] = share_link
                    item["pan115_savable"] = True
                    context["budget_left"] = max(0, int(context.get("budget_left", 0) or 0) - unlock_points)
                    context["consecutive_failed_count"] = 0
                    stats["success"] = int(stats.get("success") or 0) + 1
                    stats["points_spent"] = int(stats.get("points_spent") or 0) + unlock_points
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
                                "budget_remaining_after": int(context.get("budget_left", 0) or 0),
                            },
                        }
                    )
                else:
                    context["consecutive_failed_count"] = int(context.get("consecutive_failed_count", 0) or 0) + 1
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
                context["consecutive_failed_count"] = int(context.get("consecutive_failed_count", 0) or 0) + 1
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
                            "consecutive_failed_count": int(context.get("consecutive_failed_count", 0) or 0),
                            "budget_left": int(context.get("budget_left", 0) or 0),
                        },
                    }
                )
                break

            await asyncio.sleep(float(context.get("request_interval_seconds", 0.35) or 0.35))

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
    def _allow_unlock_by_threshold(unlock_points: int, threshold: int, inclusive: bool) -> bool:
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
                select(DownloadRecord.resource_url).where(DownloadRecord.subscription_id == subscription_id)
            )
        existing_urls = {str(row[0]) for row in existing_result.all() if row and row[0]}

        created_records: list[DownloadRecord] = []
        duplicate_urls: set[str] = set()
        duplicate_count = 0
        invalid_count = 0
        for item in resources:
            resource_url = self._extract_resource_url(item)
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
                resource_type="pan115",
                status=MediaStatus.PENDING,
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

    async def _load_retryable_records(self, db: AsyncSession, subscription_id: int) -> list[DownloadRecord]:
        from app.models.models import MediaStatus
        with db.no_autoflush:
            failed_result = await db.execute(
                select(DownloadRecord).where(
                    DownloadRecord.subscription_id == subscription_id,
                    DownloadRecord.status == MediaStatus.FAILED,
                ).order_by(DownloadRecord.created_at.desc()).limit(8)
            )
            pending_result = await db.execute(
                select(DownloadRecord).where(
                    DownloadRecord.subscription_id == subscription_id,
                    DownloadRecord.status == MediaStatus.PENDING,
                ).order_by(DownloadRecord.created_at.desc()).limit(5)
            )

        failed_rows = list(failed_result.scalars().all())
        pending_rows = list(pending_result.scalars().all())

        retryable: list[DownloadRecord] = []
        for row in failed_rows:
            if not self._is_likely_115_share_identifier(row.resource_url):
                continue
            if not self._is_retryable_transfer_error(row.error_message or ""):
                continue
            retryable.append(row)

        for row in pending_rows:
            if not self._is_likely_115_share_identifier(row.resource_url):
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

        url_values = [str(item or "").strip() for item in duplicate_urls if str(item or "").strip()]
        if not url_values:
            return []

        with db.no_autoflush:
            rows_result = await db.execute(
                select(DownloadRecord).where(
                    DownloadRecord.subscription_id == subscription_id,
                    DownloadRecord.resource_url.in_(url_values),
                    DownloadRecord.status.in_((MediaStatus.FAILED, MediaStatus.PENDING)),
                ).order_by(DownloadRecord.created_at.desc())
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
    def _exclude_new_records(retry_records: list[DownloadRecord], new_records: list[DownloadRecord]) -> list[DownloadRecord]:
        new_keys: set[str] = set()
        for item in new_records:
            if not item:
                continue
            new_keys.add(str(item.resource_url or "").strip())
        if not new_keys:
            return retry_records
        return [item for item in retry_records if str(item.resource_url or "").strip() not in new_keys]

    @staticmethod
    def _merge_records(primary: list[DownloadRecord], secondary: list[DownloadRecord]) -> list[DownloadRecord]:
        merged: list[DownloadRecord] = []
        seen_keys: set[str] = set()
        for record in primary + secondary:
            if not record:
                continue
            key = f"id:{record.id}" if record.id is not None else f"url:{record.resource_url}"
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
    ) -> dict[str, Any]:
        from app.models.models import MediaStatus
        runtime_cookie = runtime_settings_service.get_pan115_cookie()
        pan_service = Pan115Service(runtime_cookie)
        # 订阅自动转存应使用“默认转存文件夹”，而不是离线下载目录。
        default_folder_id = runtime_settings_service.get_pan115_default_folder().get("folder_id", "0")
        parent_folder_id = str(default_folder_id or "0")
        target_folder_name = self._build_target_folder_name(sub)

        saved = 0
        failed = 0
        errors: list[dict[str, Any]] = []
        target_folder_id = ""
        tv_missing_enabled = False
        missing_episodes: set[tuple[int, int]] = set()
        is_tv_subscription = sub.media_type == MediaType.TV and sub.tmdb_id is not None

        if is_tv_subscription:
            await self._create_step_log(
                db,
                run_id=run_id,
                channel=channel,
                subscription_id=sub.id,
                subscription_title=sub.title,
                step="tv_missing_fetch_start",
                status="info",
                message="开始查询 Emby 缺集状态",
                payload={"tmdb_id": sub.tmdb_id},
            )
            tv_missing_result = await tv_missing_service.get_tv_missing_status(sub.tmdb_id, include_specials=False)
            if str(tv_missing_result.get("status") or "") == "ok":
                tv_missing_enabled = True
                missing_episodes = {
                    (int(pair[0]), int(pair[1]))
                    for pair in (tv_missing_result.get("missing_episodes") or [])
                    if isinstance(pair, (list, tuple)) and len(pair) == 2
                }
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=channel,
                    subscription_id=sub.id,
                    subscription_title=sub.title,
                    step="tv_missing_fetch_done",
                    status="success",
                    message="缺集状态查询完成",
                    payload={
                        "aired_count": int((tv_missing_result.get("counts") or {}).get("aired") or 0),
                        "existing_count": int((tv_missing_result.get("counts") or {}).get("existing") or 0),
                        "missing_count": len(missing_episodes),
                    },
                )
            else:
                await self._create_step_log(
                    db,
                    run_id=run_id,
                    channel=channel,
                    subscription_id=sub.id,
                    subscription_title=sub.title,
                    step="tv_missing_fetch_failed",
                    status="warning",
                    message=f"缺集状态查询失败，回退全量转存: {tv_missing_result.get('message') or 'unknown'}",
                    payload={"status": tv_missing_result.get("status"), "message": tv_missing_result.get("message")},
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
                message=f"[{source}] 开始转存：{record.resource_name}",
                payload={
                    "source": source,
                    "record_id": record.id,
                    "resource_url": record.resource_url,
                },
            )
            try:
                share_link, receive_code = self._split_share_link_and_receive_code(record.resource_url)
                if tv_missing_enabled and is_tv_subscription:
                    share_code = pan_service._extract_share_code(share_link)
                    if not share_code:
                        raise ValueError("无效的分享链接，无法提取分享码")

                    all_files = await pan_service.get_share_all_files_recursive(share_code, receive_code)
                    matched_fids: list[str] = []
                    matched_pairs: set[tuple[int, int]] = set()
                    parsed_count = 0
                    unparsed_video_count = 0

                    for item in all_files:
                        if not isinstance(item, dict):
                            continue
                        fid = str(item.get("fid") or "").strip()
                        filename = str(item.get("name") or "").strip()
                        if not fid or not filename:
                            continue
                        parsed = name_parser.parse_episode(filename)
                        if parsed:
                            parsed_count += 1
                            pair = (int(parsed[0]), int(parsed[1]))
                            if pair in missing_episodes:
                                matched_fids.append(fid)
                                matched_pairs.add(pair)
                            continue
                        if self._is_video_filename(filename):
                            unparsed_video_count += 1

                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=channel,
                        subscription_id=sub.id,
                        subscription_title=sub.title,
                        step="tv_record_files_parsed",
                        status="info",
                        message=f"[{source}] 文件解析完成：{record.resource_name}",
                        payload={
                            "record_id": record.id,
                            "total_files": len(all_files),
                            "parsed_count": parsed_count,
                            "matched_missing_count": len(matched_fids),
                            "unparsed_video_count": unparsed_video_count,
                            "remaining_missing_count": len(missing_episodes),
                        },
                    )

                    selected_file_ids = list(dict.fromkeys(matched_fids))
                    selected_mode = "missing"

                    if not selected_file_ids:
                        record.status = MediaStatus.PENDING
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
                            message=f"[{source}] 缺集已补齐，跳过该资源：{record.resource_name}",
                            payload={
                                "record_id": record.id,
                                "remaining_missing_count": len(missing_episodes),
                            },
                        )
                        continue

                    if not target_folder_id:
                        target_folder_id = await pan_service.get_or_create_folder(parent_folder_id, target_folder_name)
                    result = await pan_service.save_share_files(
                        share_code=share_code,
                        file_ids=selected_file_ids,
                        pid=target_folder_id,
                        receive_code=receive_code,
                    )
                    if not self._is_pan115_save_success(result):
                        raise ValueError(
                            str(
                                (result or {}).get("error")
                                or (result or {}).get("message")
                                or (result or {}).get("msg")
                                or "115转存失败"
                            )
                        )

                    if selected_mode == "missing":
                        for pair in matched_pairs:
                            missing_episodes.discard(pair)
                    record.status = MediaStatus.PENDING
                    record.completed_at = None
                    record.error_message = None
                    record.file_id = str(target_folder_id or "")
                    saved += 1
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=channel,
                        subscription_id=sub.id,
                        subscription_title=sub.title,
                        step="tv_transfer_selected_done",
                        status="success",
                        message=f"[{source}] 精准转存成功：{record.resource_name}",
                        payload={
                            "source": source,
                            "record_id": record.id,
                            "selected_mode": selected_mode,
                            "selected_count": len(selected_file_ids),
                            "remaining_missing_count": len(missing_episodes),
                            "folder_id": record.file_id,
                        },
                    )
                else:
                    result = await pan_service.save_share_to_folder(
                        share_url=share_link,
                        folder_name=target_folder_name,
                        parent_id=parent_folder_id,
                        receive_code=receive_code,
                    )
                    record.status = MediaStatus.COMPLETED
                    record.completed_at = datetime.utcnow()
                    record.error_message = None
                    folder_id = str((result or {}).get("folder_id") or "").strip()
                    if folder_id:
                        record.file_id = folder_id
                    saved += 1
                    await self._create_step_log(
                        db,
                        run_id=run_id,
                        channel=channel,
                        subscription_id=sub.id,
                        subscription_title=sub.title,
                        step="auto_transfer_item_done",
                        status="success",
                        message=f"[{source}] 转存成功：{record.resource_name}",
                        payload={
                            "source": source,
                            "record_id": record.id,
                            "folder_id": record.file_id,
                        },
                    )
            except Exception as exc:
                if self._is_already_received_error(str(exc)):
                    # 115 返回已接收时视为成功，避免重复任务被统计为失败。
                    if tv_missing_enabled and is_tv_subscription:
                        record.status = MediaStatus.PENDING
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
                        message=f"[{source}] 资源已在网盘中，按成功处理：{record.resource_name}",
                        payload={
                            "source": source,
                            "record_id": record.id,
                            "reason": "already_received",
                        },
                    )
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
                    message=f"[{source}] 转存失败：{record.resource_name}",
                    payload={
                        "source": source,
                        "record_id": record.id,
                        "error": str(exc)[:500],
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

        return {"saved": saved, "failed": failed, "errors": errors}

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
            .order_by(SubscriptionExecutionLog.started_at.desc(), SubscriptionExecutionLog.id.desc())
            .limit(5)
        )
        keep_ids = [row[0] for row in keep_ids_result.all() if row and row[0]]
        if keep_ids:
            await db.execute(
                delete(SubscriptionExecutionLog).where(SubscriptionExecutionLog.id.notin_(keep_ids))
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
    def _extract_resource_name(item: dict[str, Any]) -> str:
        name = str(item.get("resource_name") or item.get("title") or item.get("name") or "").strip()
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
    def _normalize_hdhive_subscription_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        return value.endswith((".mp4", ".mkv", ".avi", ".ts", ".rmvb", ".flv", ".mov", ".wmv", ".m4v"))

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
            return bool(re.search(r"(?:115(?:cdn)?\.com|share\.115\.com|anxia\.com)", lowered))
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
        if normalized not in {"nullbr", "pansou", "hdhive", "tg", "priority"}:
            raise ValueError("unsupported channel")
        return normalized

    @staticmethod
    def _resolve_status(failed_count: int, checked_count: int, auto_failed_count: int) -> ExecutionStatus:
        total_failed = failed_count + auto_failed_count
        if total_failed <= 0:
            return ExecutionStatus.SUCCESS
        if failed_count >= max(checked_count, 1):
            return ExecutionStatus.FAILED
        return ExecutionStatus.PARTIAL

    @staticmethod
    def _build_message(result: dict[str, Any]) -> str:
        new_resource_desc = (
            f"新增资源 {result['new_resource_count']} 条"
            if result["new_resource_count"] > 0
            else "本轮未发现新资源"
        )
        return (
            f"{result['channel']} 检查完成: 订阅 {result['checked_count']} 项, "
            f"扫描资源 {result['resource_checked_count']} 条(重复 {result['resource_duplicate_count']}), "
            f"{new_resource_desc}, "
            f"HDHive 解锁 尝试 {result['hdhive_unlock_attempted_count']} 条(成功 {result['hdhive_unlock_success_count']} / 失败 {result['hdhive_unlock_failed_count']} / 跳过 {result['hdhive_unlock_skipped_count']} / 消耗 {result['hdhive_unlock_points_spent']} 积分), "
            f"自动转存成功 {result['auto_saved_count']} 条(新资源 {result['auto_new_saved_count']} / 历史重试 {result['auto_retry_saved_count']}), "
            f"自动转存失败 {result['auto_failed_count']} 条(新资源 {result['auto_new_failed_count']} / 历史重试 {result['auto_retry_failed_count']}), "
            f"检查失败 {result['failed_count']} 项"
        )


subscription_service = SubscriptionService()


@dataclass(slots=True)
class SubscriptionSnapshot:
    id: int
    tmdb_id: int | None
    title: str
    media_type: MediaType
    year: str | None
    auto_download: bool
