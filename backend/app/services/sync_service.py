import asyncio
import logging
import re
from typing import Any
from urllib.parse import unquote

from app.services.operation_log_service import operation_log_service
from app.services.pan115_service import pan115_service
from app.services.emby_service import emby_service
from app.utils.name_parser import name_parser

logger = logging.getLogger(__name__)


class SyncService:
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
        receive_code: str = ""
    ) -> dict[str, Any]:
        """
        基于 Emby 查漏补缺的 115 转存策略
        """
        await operation_log_service.log_background_event(
            source_type="background_task", module="sync",
            action="sync.tv_show.start", status="info",
            message=f"开始同步剧集 (TMDB ID: {tmdb_id})",
            extra={"tmdb_id": tmdb_id},
        )
        try:
            # 1. 查询 Emby 媒体库
            existing_episodes = await emby_service.get_downloaded_episodes(tmdb_id)
            logger.info("Emby 中已存在的剧集 (TMDB ID: %s): %s", tmdb_id, existing_episodes)

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
            all_files = await pan115_service.get_share_all_files_recursive(share_code, receive_code)
            if not all_files:
                return {"success": False, "message": "分享链接中没有找到文件", "saved_count": 0}

            missing_fids = []
            matched_files = []

            # 4. 文件名解析与过滤
            for f in all_files:
                filename = f.get("name", "")
                fid = f.get("fid")
                if not fid or not filename:
                    continue
                    
                # 尝试解析季号和集号
                parsed = name_parser.parse_episode(filename)
                
                # 如果无法解析出集号，为了保险起见，我们选择转存它，或者根据需求选择忽略。
                # 默认策略：如果解析成功且 Emby 中已存在，则跳过；否则转存。
                if parsed:
                    season, episode = parsed
                    if (season, episode) in existing_episodes:
                        logger.info("跳过已存在剧集: %s (S%02dE%02d)", filename, season, episode)
                        continue
                else:
                    logger.info("未能解析出集数的视频，默认加入转存队列: %s", filename)

                missing_fids.append(str(fid))
                matched_files.append(filename)

            # 5. 精准转存
            if not missing_fids:
                return {"success": True, "message": "所有剧集均已存在，无需转存", "saved_count": 0}

            # 调用 115 API 批量转存
            # 注意: missing_fids 需要去重
            missing_fids = list(dict.fromkeys(missing_fids))
            logger.info("准备转存 %s 个文件: %s", len(missing_fids), matched_files)

            save_result = await pan115_service.save_share_files(
                share_code=share_code,
                file_ids=missing_fids,
                pid=target_folder_id,
                receive_code=receive_code
            )

            # 判断转存结果
            success = False
            if isinstance(save_result, dict):
                success = save_result.get("state", False) or save_result.get("success", False)

            if success:
                # 6. 触发 Emby 刷新 (不阻塞等待)
                asyncio.create_task(emby_service.refresh_library())
                await operation_log_service.log_background_event(
                    source_type="background_task", module="sync",
                    action="sync.tv_show.success", status="success",
                    message=f"剧集同步完成：成功转存 {len(missing_fids)} 集 (TMDB ID: {tmdb_id})",
                    extra={"tmdb_id": tmdb_id, "saved_count": len(missing_fids), "files": matched_files[:10]},
                )
                return {
                    "success": True,
                    "message": f"成功转存 {len(missing_fids)} 集",
                    "saved_count": len(missing_fids),
                    "files": matched_files
                }
            else:
                await operation_log_service.log_background_event(
                    source_type="background_task", module="sync",
                    action="sync.tv_show.failed", status="failed",
                    message=f"剧集转存失败 (TMDB ID: {tmdb_id})：{str(save_result)[:200]}",
                    extra={"tmdb_id": tmdb_id},
                )
                return {
                    "success": False,
                    "message": f"转存失败: {save_result}",
                    "saved_count": 0
                }

        except Exception as e:
            await operation_log_service.log_background_event(
                source_type="background_task", module="sync",
                action="sync.tv_show.error", status="failed",
                message=f"剧集同步异常 (TMDB ID: {tmdb_id})：{str(e)[:200]}",
                extra={"tmdb_id": tmdb_id, "error": str(e)[:300]},
            )
            return {"success": False, "message": f"同步过程中发生异常: {str(e)}", "saved_count": 0}


sync_service = SyncService()
