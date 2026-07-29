import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import unquote

from app.services.operation_log_service import operation_log_service
from app.services.pan115_service import pan115_service
from app.services.emby_service import emby_service
from app.utils.name_parser import name_parser

logger = logging.getLogger(__name__)


class SyncService:
    @staticmethod
    async def _log_tv_stage(
        *,
        tmdb_id: int,
        stage: str,
        started_at: float,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> int:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        payload = {
            "tmdb_id": tmdb_id,
            "stage": stage,
            "duration_ms": duration_ms,
            **(extra or {}),
        }
        await operation_log_service.log_background_event(
            source_type="background_task",
            module="sync",
            action=f"sync.tv_show.stage.{stage}",
            status="success",
            message=f"{message}，耗时 {duration_ms}ms",
            extra=payload,
        )
        return duration_ms

    @staticmethod
    def _extract_receive_code(
        share_url: str,
        share_payload: dict[str, Any] | None,
        receive_code: str = "",
    ) -> str:
        value = str(receive_code or "").strip()
        if value:
            return value

        if isinstance(share_payload, dict):
            value = str(share_payload.get("receive_code") or "").strip()
            if value:
                return value

        raw = str(share_url or "").strip()
        if not raw:
            return ""

        decoded = unquote(raw)
        for text in (raw, decoded):
            short_receive_match = re.match(r"^[A-Za-z0-9]+-([A-Za-z0-9]{4})$", text)
            if short_receive_match:
                return short_receive_match.group(1)

            password_match = re.search(
                r"(?:password|pwd|receive_code|pickcode|code)=([^&#]+)",
                text,
                re.IGNORECASE,
            )
            if password_match:
                return password_match.group(1).strip()

            text_receive_match = re.search(
                r"(?:提取码|提取碼|访问码|訪問碼|密码|密碼)\s*[:：=]?\s*([A-Za-z0-9]{4})",
                text,
                re.IGNORECASE,
            )
            if text_receive_match:
                return text_receive_match.group(1).strip()

        return ""

    @staticmethod
    def _extract_share_code(share_url: str, share_payload: dict[str, Any] | None) -> str:
        if isinstance(share_payload, dict):
            payload_code = str(share_payload.get("share_code") or "").strip()
            if payload_code:
                return payload_code

        share_code = pan115_service._extract_share_code(share_url or "")
        return str(share_code or "").strip()

    async def sync_tv_show(
        self,
        tmdb_id: int,
        share_url: str,
        target_folder_id: str,
        receive_code: str = "",
        show_title: str = "",
    ) -> dict[str, Any]:
        """
        基于 Emby 查漏补缺的 115 转存策略
        """
        overall_started_at = time.perf_counter()
        await operation_log_service.log_background_event(
            source_type="background_task", module="sync",
            action="sync.tv_show.start", status="info",
            message=f"开始同步剧集 (TMDB ID: {tmdb_id})",
            extra={"tmdb_id": tmdb_id},
        )
        try:
            # 1. 优先查询本地 Emby 同步索引，索引不可用时再访问 Emby。
            stage_started_at = time.perf_counter()
            emby_status = await emby_service.get_tv_episode_status_by_tmdb(tmdb_id)
            existing_episodes = set(emby_status.get("existing_episodes") or set())
            emby_source = str(emby_status.get("source") or "emby_api")
            await self._log_tv_stage(
                tmdb_id=tmdb_id,
                stage="emby_lookup",
                started_at=stage_started_at,
                message=f"Emby 已有集数查询完成（来源：{emby_source}）",
                extra={
                    "source": emby_source,
                    "existing_episode_count": len(existing_episodes),
                    "lookup_status": str(emby_status.get("status") or ""),
                },
            )
            logger.info(
                "Emby 中已存在的剧集 (TMDB ID: %s, source=%s): %s",
                tmdb_id,
                emby_source,
                existing_episodes,
            )

            # 2 & 3. 解析 115 分享链接获取所有文件
            # 获取 share_code
            share_payload = None
            try:
                from p115client.util import share_extract_payload

                share_payload = share_extract_payload(share_url)
            except Exception:
                logger.debug("p115client.share_extract_payload 解析失败，将使用本地兜底规则")

            share_code = self._extract_share_code(share_url, share_payload)
            if not share_code:
                raise ValueError("无效的分享链接")

            receive_code = self._extract_receive_code(share_url, share_payload, receive_code)

            # 递归获取分享链接内所有的文件
            stage_started_at = time.perf_counter()
            all_files = await pan115_service.get_share_all_files_recursive(share_code, receive_code)
            await self._log_tv_stage(
                tmdb_id=tmdb_id,
                stage="share_scan",
                started_at=stage_started_at,
                message="115 分享目录扫描完成",
                extra={"file_count": len(all_files)},
            )
            if not all_files:
                duration_ms = int((time.perf_counter() - overall_started_at) * 1000)
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="sync",
                    action="sync.tv_show.failed",
                    status="failed",
                    message=f"分享链接中没有找到文件 (TMDB ID: {tmdb_id})",
                    extra={"tmdb_id": tmdb_id, "duration_ms": duration_ms},
                )
                return {"success": False, "message": "分享链接中没有找到文件", "saved_count": 0}

            candidates_by_episode: dict[tuple[int, int], list[dict[str, Any]]] = {}
            unparsed_video_candidates: list[dict[str, Any]] = []

            # 4. 文件名解析与过滤
            for f in all_files:
                filename = f.get("name", "")
                fid = f.get("fid")
                if not fid or not filename:
                    continue
                if not pan115_service._is_video_file_name(filename):
                    continue

                coverage = name_parser.parse_episode_coverage(filename)
                if coverage:
                    episode_keys = name_parser.iter_episode_keys(coverage)
                    for season, episode in episode_keys:
                        candidates_by_episode.setdefault((season, episode), []).append(f)
                    continue

                logger.info("未能解析出集数的视频，加入候选队列: %s", filename)
                unparsed_video_candidates.append(f)

            from app.utils.resource_tags import build_quality_filter_from_settings
            from app.utils.tv_episode_dedup import dedupe_tv_transfer_files

            quality_filter = build_quality_filter_from_settings()
            selected_files: list[dict[str, Any]] = []
            for candidates in candidates_by_episode.values():
                if len(candidates) > 1:
                    best = pan115_service.pick_best_video_file(candidates, quality_filter)
                    selected_files.append(best or candidates[0])
                else:
                    selected_files.extend(candidates)

            if unparsed_video_candidates:
                if len(unparsed_video_candidates) > 1:
                    best = pan115_service.pick_best_video_file(unparsed_video_candidates, quality_filter)
                    selected_files.append(best or unparsed_video_candidates[0])
                else:
                    selected_files.extend(unparsed_video_candidates)

            stage_started_at = time.perf_counter()
            pan_existing = await pan115_service._collect_tv_existing_episodes_for_transfer(
                target_cid=str(target_folder_id or ""),
                show_title=show_title,
            )
            all_existing_episodes = existing_episodes | pan_existing
            selected_files, tv_skip = dedupe_tv_transfer_files(
                selected_files,
                existing_episodes=all_existing_episodes,
            )
            await self._log_tv_stage(
                tmdb_id=tmdb_id,
                stage="library_dedupe",
                started_at=stage_started_at,
                message="正式库及目标目录定向查重完成",
                extra={
                    "emby_episode_count": len(existing_episodes),
                    "pan_episode_count": len(pan_existing),
                    "existing_episode_count": len(all_existing_episodes),
                    "skipped_file_count": len(tv_skip),
                    "selected_file_count": len(selected_files),
                },
            )

            missing_fids = [str(f.get("fid")) for f in selected_files if f.get("fid")]
            matched_files = [str(f.get("name") or "") for f in selected_files]

            # 5. 精准转存
            if not missing_fids:
                duration_ms = int((time.perf_counter() - overall_started_at) * 1000)
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="sync",
                    action="sync.tv_show.success",
                    status="success",
                    message=f"所有剧集均已存在，无需转存 (TMDB ID: {tmdb_id})",
                    extra={
                        "tmdb_id": tmdb_id,
                        "saved_count": 0,
                        "duration_ms": duration_ms,
                    },
                )
                return {"success": True, "message": "所有剧集均已存在，无需转存", "saved_count": 0}

            # 调用 115 API 批量转存
            # 注意: missing_fids 需要去重
            missing_fids = list(dict.fromkeys(missing_fids))
            logger.info("准备转存 %s 个文件: %s", len(missing_fids), matched_files)

            stage_started_at = time.perf_counter()
            save_result = await pan115_service.save_share_files(
                share_code=share_code,
                file_ids=missing_fids,
                pid=target_folder_id,
                receive_code=receive_code
            )
            await self._log_tv_stage(
                tmdb_id=tmdb_id,
                stage="transfer",
                started_at=stage_started_at,
                message="115 文件转存请求完成",
                extra={"requested_file_count": len(missing_fids)},
            )

            # 判断转存结果
            success = False
            if isinstance(save_result, dict):
                success = save_result.get("state", False) or save_result.get("success", False)

            if success:
                # 6. 触发 Emby 刷新 (不阻塞等待)
                asyncio.create_task(emby_service.refresh_library())
                duration_ms = int((time.perf_counter() - overall_started_at) * 1000)
                await operation_log_service.log_background_event(
                    source_type="background_task", module="sync",
                    action="sync.tv_show.success", status="success",
                    message=f"剧集同步完成：成功转存 {len(missing_fids)} 集 (TMDB ID: {tmdb_id})",
                    extra={
                        "tmdb_id": tmdb_id,
                        "saved_count": len(missing_fids),
                        "files": matched_files[:10],
                        "duration_ms": duration_ms,
                    },
                )
                return {
                    "success": True,
                    "message": f"成功转存 {len(missing_fids)} 集",
                    "saved_count": len(missing_fids),
                    "files": matched_files
                }
            else:
                duration_ms = int((time.perf_counter() - overall_started_at) * 1000)
                await operation_log_service.log_background_event(
                    source_type="background_task", module="sync",
                    action="sync.tv_show.failed", status="failed",
                    message=f"剧集转存失败 (TMDB ID: {tmdb_id})：{str(save_result)[:200]}",
                    extra={"tmdb_id": tmdb_id, "duration_ms": duration_ms},
                )
                return {
                    "success": False,
                    "message": f"转存失败: {save_result}",
                    "saved_count": 0
                }

        except Exception as e:
            duration_ms = int((time.perf_counter() - overall_started_at) * 1000)
            await operation_log_service.log_background_event(
                source_type="background_task", module="sync",
                action="sync.tv_show.error", status="failed",
                message=f"剧集同步异常 (TMDB ID: {tmdb_id})：{str(e)[:200]}",
                extra={
                    "tmdb_id": tmdb_id,
                    "error": str(e)[:300],
                    "duration_ms": duration_ms,
                },
            )
            return {"success": False, "message": f"同步过程中发生异常: {str(e)}", "saved_count": 0}


sync_service = SyncService()
