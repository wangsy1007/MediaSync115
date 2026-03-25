import asyncio
from collections import defaultdict, deque
from typing import Any

from app.services.operation_log_service import operation_log_service


class WorkflowExecutor:
    def __init__(self):
        self._handlers = {
            "send_log_message": self._action_send_log_message,
            "search_media": self._action_search_media,
            "save_share_to_115": self._action_save_share_to_115,
            "create_download_record": self._action_create_download_record,
            "refresh_emby": self._action_refresh_emby,
        }

    async def execute(
        self,
        workflow_id: int,
        actions: list[dict],
        flows: list[dict],
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, str, dict[str, Any]]:
        context_data = dict(context or {})
        actions_map = {str(item.get("id")): item for item in actions if item.get("id") is not None}
        if not actions_map:
            return False, "工作流没有可执行动作", context_data

        graph: dict[str, list[str]] = defaultdict(list)
        indegree: dict[str, int] = {action_id: 0 for action_id in actions_map.keys()}
        for flow in flows:
            source = str(flow.get("source") or "")
            target = str(flow.get("target") or "")
            if source in actions_map and target in actions_map:
                graph[source].append(target)
                indegree[target] = indegree.get(target, 0) + 1

        queue = deque([node for node, degree in indegree.items() if degree == 0])
        if not queue:
            queue = deque(actions_map.keys())

        await operation_log_service.log_background_event(
            source_type="background_task", module="workflow",
            action="workflow.execute.start", status="info",
            message=f"工作流开始执行（ID: {workflow_id}，共 {len(actions_map)} 个动作）",
            extra={"workflow_id": workflow_id, "action_count": len(actions_map)},
        )

        visited = 0
        while queue:
            node = queue.popleft()
            action = actions_map.get(node)
            if not action:
                continue

            ok, message = await self._execute_action(workflow_id, action, context_data)
            if not ok:
                await operation_log_service.log_background_event(
                    source_type="background_task", module="workflow",
                    action="workflow.execute.action_failed", status="failed",
                    message=f"工作流动作执行失败（ID: {workflow_id}）：{message[:200]}",
                    extra={"workflow_id": workflow_id, "action_id": node, "error": message[:300]},
                )
                return False, message, context_data

            visited += 1
            for nxt in graph.get(node, []):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)

        if visited == 0:
            await operation_log_service.log_background_event(
                source_type="background_task", module="workflow",
                action="workflow.execute.empty", status="warning",
                message=f"工作流未执行任何动作（ID: {workflow_id}）",
                extra={"workflow_id": workflow_id},
            )
            return False, "工作流未执行任何动作", context_data

        await operation_log_service.log_background_event(
            source_type="background_task", module="workflow",
            action="workflow.execute.success", status="success",
            message=f"工作流执行成功（ID: {workflow_id}，执行 {visited} 个动作）",
            extra={"workflow_id": workflow_id, "executed_actions": visited},
        )
        return True, "工作流执行成功", context_data

    async def _execute_action(self, workflow_id: int, action: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
        action_type = str(action.get("type") or "").strip()
        action_name = str(action.get("name") or action.get("id") or action_type)
        if not action_type:
            return False, f"动作 {action_name} 缺少 type"

        handler = self._handlers.get(action_type)
        if not handler:
            return False, f"未支持的动作类型: {action_type}"

        params = action.get("params") or {}
        if not isinstance(params, dict):
            return False, f"动作 {action_name} 的 params 必须是对象"

        try:
            return await handler(workflow_id=workflow_id, action=action, params=params, context=context)
        except Exception as exc:
            return False, f"动作 {action_name} 执行失败: {str(exc)}"

    async def _action_send_log_message(self, **kwargs) -> tuple[bool, str]:
        params = kwargs.get("params") or {}
        context = kwargs.get("context") or {}
        message = str(params.get("message") or "").strip()
        if not message:
            return False, "send_log_message 缺少 message"
        logs = context.setdefault("logs", [])
        logs.append(message)
        return True, "日志动作执行完成"

    async def _action_search_media(self, **kwargs) -> tuple[bool, str]:
        from app.services.nullbr_service import nullbr_service

        params = kwargs.get("params") or {}
        context = kwargs.get("context") or {}
        query = str(params.get("query") or context.get("query") or "").strip()
        page = int(params.get("page") or 1)
        if not query:
            return False, "search_media 缺少 query"

        payload = await asyncio.to_thread(nullbr_service.search, query, page)
        context["search_result"] = payload
        context["query"] = query
        return True, "媒体搜索完成"

    async def _action_save_share_to_115(self, **kwargs) -> tuple[bool, str]:
        from app.services.pan115_service import pan115_service
        from app.services.runtime_settings_service import runtime_settings_service

        params = kwargs.get("params") or {}
        context = kwargs.get("context") or {}

        share_url = str(params.get("share_url") or context.get("share_url") or "").strip()
        folder_name = str(params.get("folder_name") or context.get("folder_name") or "").strip()
        parent_id = str(runtime_settings_service.get_pan115_default_folder().get("folder_id") or "0").strip() or "0"
        receive_code = str(params.get("receive_code") or context.get("receive_code") or "").strip()
        tmdb_id_raw = params.get("tmdb_id") or context.get("tmdb_id")

        if not share_url or not folder_name:
            return False, "save_share_to_115 缺少 share_url 或 folder_name"

        if tmdb_id_raw:
            from app.services.sync_service import sync_service

            result = await sync_service.sync_tv_show(
                tmdb_id=int(tmdb_id_raw),
                share_url=share_url,
                target_folder_id=await pan115_service.get_or_create_folder(parent_id, folder_name),
                receive_code=receive_code,
            )
        else:
            result = await pan115_service.save_share_to_folder(
                share_url=share_url,
                folder_name=folder_name,
                parent_id=parent_id,
                receive_code=receive_code,
            )

        context["save_result"] = result
        success = bool(result.get("success", result.get("state", True))) if isinstance(result, dict) else True
        if not success:
            return False, f"转存失败: {result}"
        return True, "115 转存完成"

    async def _action_create_download_record(self, **kwargs) -> tuple[bool, str]:
        from app.core.database import async_session_maker
        from app.models.models import DownloadRecord, MediaStatus

        params = kwargs.get("params") or {}
        context = kwargs.get("context") or {}
        subscription_id = params.get("subscription_id") or context.get("subscription_id")
        resource_name = params.get("resource_name") or context.get("resource_name") or "workflow-resource"
        resource_url = params.get("resource_url") or context.get("resource_url") or "workflow://generated"
        resource_type = params.get("resource_type") or context.get("resource_type") or "115"
        file_id = params.get("file_id") or context.get("file_id")

        if not subscription_id:
            return False, "create_download_record 缺少 subscription_id"

        async with async_session_maker() as db:
            record = DownloadRecord(
                subscription_id=int(subscription_id),
                resource_name=str(resource_name),
                resource_url=str(resource_url),
                resource_type=str(resource_type),
                file_id=str(file_id) if file_id else None,
                status=MediaStatus.PENDING,
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)
            context["download_record_id"] = record.id

        return True, "下载记录创建成功"

    async def _action_refresh_emby(self, **kwargs) -> tuple[bool, str]:
        from app.services.emby_service import emby_service

        await emby_service.refresh_library()
        return True, "Emby 刷新已触发"


workflow_executor = WorkflowExecutor()
