"""
115网盘API路由
提供115网盘文件管理、离线下载、分享转存等接口
"""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Response
from app.services.pan115_service import Pan115Service, pan115_service
from app.services.media_postprocess_service import media_postprocess_service
from app.services.runtime_settings_service import runtime_settings_service


async def _trigger_archive_if_enabled(trigger: str = "transfer") -> None:
    await media_postprocess_service.trigger_archive_after_transfer(trigger=trigger)


from pydantic import BaseModel
from typing import Optional, List
from app.services.sync_service import sync_service

router = APIRouter(prefix="/pan115", tags=["115网盘"])


def is_retryable_115_error(error_msg: str) -> bool:
    text = str(error_msg or "").lower()
    if not text:
        return False
    retry_tokens = (
        "code=405",
        "method not allowed",
        "too many",
        "rate limit",
        "频繁",
        "繁忙",
        "timeout",
        "timed out",
        "590075",
        "990005",
        "ebusy",
        "eagain",
    )
    return any(token in text for token in retry_tokens)


def build_retry_delay(attempt: int) -> float:
    return min(0.8 * (2**attempt), 6.0)


def classify_115_error(error_msg: str) -> str:
    text = str(error_msg or "")
    lowered = text.lower()
    if (
        "cookie" in lowered
        or "eauth" in lowered
        or "errno': 990001" in lowered
        or '"errno": 990001' in lowered
        or "errno=990001" in lowered
        or "errno': 99" in lowered
        or '"errno": 99' in lowered
        or "errno=99" in lowered
        or "重新登录" in text
        or "登录超时" in text
    ):
        return "auth_invalid"
    if is_retryable_115_error(text):
        return "rate_limited"
    return "unavailable"


# ==================== 请求模型 ====================


def _get_transfer_default_folder_id() -> str:
    folder = runtime_settings_service.get_pan115_default_folder()
    folder_id = str(folder.get("folder_id") or "0").strip()
    return folder_id or "0"


class OfflineTaskCreate(BaseModel):
    """离线下载任务创建请求"""

    url: str
    wp_path_id: Optional[str] = ""


class SaveShareRequest(BaseModel):
    """转存分享文件请求"""

    share_code: str
    file_id: str
    pid: str = "0"
    receive_code: str = ""


class SaveShareFilesRequest(BaseModel):
    """批量转存分享文件请求"""

    share_code: str
    file_ids: List[str]
    pid: str = "0"
    receive_code: str = ""


class SaveShareToFolderRequest(BaseModel):
    """转存分享到指定文件夹请求"""

    share_url: str
    folder_name: str
    parent_id: str = "0"
    receive_code: str = ""
    tmdb_id: Optional[int] = None


class ShareExtractFilesRequest(BaseModel):
    """提取分享链接文件请求"""

    share_url: str
    receive_code: str = ""


class SaveShareFilesToFolderRequest(BaseModel):
    """选集转存到指定文件夹请求"""

    share_url: str
    file_ids: List[str]
    folder_name: str
    parent_id: str = "0"
    receive_code: str = ""


class UpdateCookieRequest(BaseModel):
    """更新Cookie请求"""

    cookie: str


class Pan115QrStatusRequest(BaseModel):
    """115扫码状态查询请求"""

    token: str


class Pan115QrStartRequest(BaseModel):
    """115扫码启动请求"""

    app: Optional[str] = "alipaymini"


class Pan115QrCancelRequest(BaseModel):
    """115扫码取消请求"""

    token: str


class CreateFolderRequest(BaseModel):
    """创建文件夹请求"""

    pid: str
    name: str


class RenameFileRequest(BaseModel):
    """重命名文件请求"""

    fid: str
    name: str


class DefaultFolderRequest(BaseModel):
    """默认转存文件夹请求"""

    folder_id: str
    folder_name: Optional[str] = ""


# ==================== 错误处理 ====================


def handle_115_error(e: Exception) -> None:
    """统一处理115 API错误"""
    error_msg = str(e)
    lowered_error_msg = error_msg.lower()

    # Cookie相关错误
    if (
        "cookie" in lowered_error_msg
        or "未配置" in error_msg
        or "eauth" in lowered_error_msg
        or "errno': 990001" in lowered_error_msg
        or '"errno": 990001' in lowered_error_msg
        or "errno=990001" in lowered_error_msg
        or "errno: 990001" in lowered_error_msg
        or "errno 990001" in lowered_error_msg
        or "errno':990001" in lowered_error_msg
        or 'errno":990001' in lowered_error_msg
        or "errno': 99" in lowered_error_msg
        or '"errno": 99' in lowered_error_msg
        or "errno=99" in lowered_error_msg
        or "errno: 99" in lowered_error_msg
        or "重新登录" in error_msg
        or "登录超时" in error_msg
    ):
        raise HTTPException(
            status_code=401, detail="115网盘Cookie无效或未配置，请在设置中更新Cookie"
        )

    # 参数错误
    if "EINVAL" in error_msg or "参数" in error_msg:
        raise HTTPException(status_code=400, detail=f"参数错误: {error_msg}")

    # 文件不存在
    if "ENOENT" in error_msg or "不存在" in error_msg:
        raise HTTPException(status_code=404, detail=f"文件或目录不存在: {error_msg}")

    # 空间不足
    if "ENOSPC" in error_msg or "空间不足" in error_msg:
        raise HTTPException(status_code=507, detail="网盘空间不足")

    # 操作频繁
    if "ebusy" in lowered_error_msg or "频繁" in error_msg:
        raise HTTPException(status_code=429, detail="操作太频繁，请稍后再试")

    # 115接口风控
    if "code=405" in lowered_error_msg or "method not allowed" in lowered_error_msg:
        raise HTTPException(status_code=429, detail="115接口临时受限，请稍后重试")

    # 其他错误
    raise HTTPException(status_code=500, detail=f"操作失败: {error_msg}")


def get_service(cookie: Optional[str] = None) -> Pan115Service:
    """获取服务实例"""
    if cookie is None:
        cookie = runtime_settings_service.get_pan115_cookie()
    return Pan115Service(cookie)


def _mask_cookie(cookie: str) -> str:
    text = str(cookie or "").strip()
    if not text:
        return ""
    if len(text) > 20:
        return text[:5] + "*****" + text[-5:]
    return "*****"


# ==================== Cookie管理 ====================


@router.get("/cookie/check")
async def check_cookie_valid():
    """
    检查Cookie是否有效

    返回Cookie有效性状态和用户信息
    """
    service = get_service()
    try:
        result = await service.check_cookie_valid()
        return result
    except Exception as e:
        handle_115_error(e)


@router.post("/cookie/update")
async def update_cookie(request: UpdateCookieRequest):
    """
    更新Cookie

    更新并验证新的Cookie
    """
    try:
        service = get_service(request.cookie)
        result = await service.check_cookie_valid()
        if result["valid"]:
            # 更新运行时配置并持久化到 data/runtime_settings.json
            runtime_settings_service.update_pan115_cookie(request.cookie)
            return {
                "success": True,
                "message": "Cookie更新成功",
                "user_info": result["user_info"],
            }
        else:
            raise HTTPException(
                status_code=400, detail=f"Cookie验证失败: {result['message']}"
            )
    except Exception as e:
        handle_115_error(e)


@router.get("/cookie")
async def get_current_cookie():
    """
    获取当前配置的Cookie（脱敏）

    仅返回Cookie的前后几位字符，中间用*号替代
    """
    cookie = runtime_settings_service.get_pan115_cookie() or ""
    if cookie:
        # 脱敏处理
        if len(cookie) > 20:
            masked = cookie[:5] + "*****" + cookie[-5:]
        else:
            masked = "*****"
        return {"masked_cookie": masked, "configured": True}
    return {"masked_cookie": "", "configured": False}


@router.post("/login/qr/start")
async def start_qr_login(request: Pan115QrStartRequest):
    """
    启动115二维码登录
    """
    try:
        result = await pan115_service.start_qr_login(
            app=str(request.app or "alipaymini")
        )
        token = str(result.get("token") or "")
        return {
            "success": True,
            "token": token,
            "qr_url": result.get("qr_url"),
            "qr_image_url": f"/api/pan115/login/qr/image?token={token}"
            if token
            else "",
            "expires_at": result.get("expires_at"),
            "expire_seconds": result.get("expire_seconds"),
            "app": result.get("app"),
        }
    except Exception as exc:
        if is_retryable_115_error(str(exc)):
            raise HTTPException(
                status_code=429, detail="115扫码接口临时受限，请稍后重试"
            )
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/login/qr/image")
async def get_qr_login_image(token: str = Query(..., description="二维码会话标识")):
    """
    获取115扫码登录二维码图片（PNG）
    """
    normalized = str(token or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="二维码会话标识不能为空")
    try:
        image_bytes = await pan115_service.get_qr_login_image(normalized)
        return Response(content=image_bytes, media_type="image/png")
    except Exception as exc:
        if is_retryable_115_error(str(exc)):
            raise HTTPException(
                status_code=429, detail="115二维码图片接口临时受限，请稍后重试"
            )
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/login/qr/status")
async def check_qr_login_status(request: Pan115QrStatusRequest):
    """
    查询115二维码登录状态
    """
    token = str(request.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="二维码会话标识不能为空")

    try:
        result = await pan115_service.check_qr_login_status(token)
        authorized = bool(result.get("authorized"))
        cookie = str(result.get("cookie") or "").strip()
        status = str(result.get("status") or "pending")
        message = str(result.get("message") or "")
        expires_at = str(result.get("expires_at") or "")

        if not authorized:
            return {
                "success": True,
                "authorized": False,
                "pending": bool(result.get("pending", True)),
                "status": status,
                "message": message,
                "expires_at": expires_at,
            }

        if not cookie:
            raise HTTPException(
                status_code=400, detail="扫码状态异常：已授权但未获取到Cookie"
            )

        runtime_settings_service.update_pan115_cookie(cookie)
        verified = await get_service(cookie).check_cookie_valid()
        if not verified.get("valid"):
            raise HTTPException(
                status_code=400,
                detail=f"扫码成功但Cookie校验失败: {verified.get('message') or '未知错误'}",
            )

        return {
            "success": True,
            "authorized": True,
            "pending": False,
            "status": "authorized",
            "message": message or "扫码登录成功",
            "expires_at": expires_at,
            "configured": True,
            "masked_cookie": _mask_cookie(cookie),
            "user_info": verified.get("user_info"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        if is_retryable_115_error(str(exc)):
            raise HTTPException(
                status_code=429, detail="115扫码状态接口临时受限，请稍后重试"
            )
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/login/qr/cancel")
async def cancel_qr_login(request: Pan115QrCancelRequest):
    """
    取消115二维码登录会话
    """
    token = str(request.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="二维码会话标识不能为空")

    try:
        result = await pan115_service.cancel_qr_login(token)
        return {
            "success": True,
            "canceled": bool(result.get("canceled")),
            "message": str(result.get("message") or ""),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/health/risk")
async def get_pan115_risk_health():
    """检测 115 当前状态，区分凭证问题、临时受限和正常可用。"""
    service = get_service()
    checks: dict[str, dict] = {}

    try:
        cookie = await service.check_cookie_valid()
        checks["cookie"] = {
            "ok": bool(cookie.get("valid")),
            "message": cookie.get("message") or "",
        }
        if not cookie.get("valid"):
            return {
                "status": "auth_invalid",
                "summary": "Cookie 无效或已过期",
                "checks": checks,
            }
    except Exception as exc:
        status = classify_115_error(str(exc))
        return {
            "status": status,
            "summary": "Cookie 校验失败",
            "checks": {
                "cookie": {"ok": False, "message": str(exc)},
            },
        }

    try:
        files = await service.get_file_list(cid="0", offset=0, limit=1)
        checks["file_list"] = {
            "ok": True,
            "count": len(files.get("data", [])) if isinstance(files, dict) else 0,
        }
    except Exception as exc:
        status = classify_115_error(str(exc))
        checks["file_list"] = {
            "ok": False,
            "message": "115 文件列表接口短时受限，通常是临时风控，稍后重试即可"
            if status == "rate_limited"
            else str(exc),
        }
        return {
            "status": status,
            "summary": "文件列表接口临时受限"
            if status == "rate_limited"
            else "文件列表接口不可用",
            "checks": checks,
        }

    try:
        offline = await service.offline_task_list(1)
        checks["offline_tasks"] = {
            "ok": True,
            "count": len(offline.get("tasks", [])) if isinstance(offline, dict) else 0,
        }
    except Exception as exc:
        status = classify_115_error(str(exc))
        checks["offline_tasks"] = {"ok": False, "message": str(exc)}
        return {
            "status": status,
            "summary": "离线任务列表接口临时受限"
            if status == "rate_limited"
            else "离线任务列表接口受限",
            "checks": checks,
        }

    return {
        "status": "healthy",
        "summary": "115 接口可用",
        "checks": checks,
    }


# ==================== 用户信息 ====================


@router.get("/user")
async def get_user_info():
    """
    获取用户信息

    返回用户名、空间使用情况等
    """
    service = get_service()
    try:
        result = await service.get_user_info()
        return result
    except Exception as e:
        handle_115_error(e)


@router.get("/offline/quota")
async def get_offline_quota():
    """
    获取离线下载配额

    返回总配额、已用配额、剩余配额
    """
    service = get_service()
    return await service.check_offline_quota_valid()


# ==================== 文件操作 ====================


@router.get("/files")
async def get_file_list(
    cid: str = Query("0", description="目录ID"),
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(50, ge=1, le=115, description="返回数量"),
):
    """
    获取文件列表

    返回指定目录下的文件和文件夹列表
    """
    service = get_service()
    try:
        result = await service.get_file_list(cid=cid, offset=offset, limit=limit)
        return result
    except Exception as e:
        handle_115_error(e)


@router.post("/folder")
async def create_folder(request: CreateFolderRequest):
    """
    创建文件夹

    在指定目录下创建新文件夹
    """
    service = get_service()
    try:
        result = await service.create_folder(request.pid, request.name)
        return result
    except Exception as e:
        handle_115_error(e)


@router.post("/rename")
async def rename_file(request: RenameFileRequest):
    """
    重命名文件/文件夹

    修改文件或文件夹的名称
    """
    service = get_service()
    try:
        result = await service.rename_file(request.fid, request.name)
        return result
    except Exception as e:
        handle_115_error(e)


@router.delete("/files")
async def delete_file(fid: List[str] = Query(..., description="文件ID列表")):
    """
    删除文件/文件夹

    删除指定的文件或文件夹
    """
    service = get_service()
    try:
        result = await service.delete_file(fid)
        return result
    except Exception as e:
        handle_115_error(e)


@router.post("/copy")
async def copy_file(
    fid: List[str] = Query(..., description="源文件ID列表"),
    pid: str = Query(..., description="目标目录ID"),
):
    """
    复制文件

    将文件复制到指定目录
    """
    service = get_service()
    try:
        result = await service.copy_file(fid, pid)
        return result
    except Exception as e:
        handle_115_error(e)


@router.post("/move")
async def move_file(
    fid: List[str] = Query(..., description="源文件ID列表"),
    pid: str = Query(..., description="目标目录ID"),
):
    """
    移动文件

    将文件移动到指定目录
    """
    service = get_service()
    try:
        result = await service.move_file(fid, pid)
        return result
    except Exception as e:
        handle_115_error(e)


@router.get("/files/{fid}")
async def get_file_info(fid: str):
    """
    获取文件信息

    返回指定文件的详细信息
    """
    service = get_service()
    try:
        result = await service.get_file_info(fid)
        return result
    except Exception as e:
        handle_115_error(e)


@router.get("/search")
async def search_file(
    search_value: str = Query(..., description="搜索关键词"),
    cid: str = Query("0", description="搜索范围目录ID"),
):
    """
    搜索文件

    在指定目录下搜索文件
    """
    service = get_service()
    try:
        result = await service.search_file(search_value, cid)
        return result
    except Exception as e:
        handle_115_error(e)


@router.get("/download/{pick_code}")
async def get_download_url(pick_code: str):
    """
    获取下载链接

    返回指定文件的下载链接
    """
    service = get_service()
    try:
        result = await service.get_download_url(pick_code)
        return result
    except Exception as e:
        handle_115_error(e)


# ==================== 离线下载 ====================


@router.post("/offline/task")
async def add_offline_task(task: OfflineTaskCreate):
    """
    添加离线下载任务

    支持磁力链接、ed2k链接、HTTP链接等
    """
    service = get_service()
    try:
        wp_path_id = (task.wp_path_id or "").strip()
        if not wp_path_id:
            wp_path_id = runtime_settings_service.get_pan115_offline_folder()[
                "folder_id"
            ]
        result = await service.offline_task_add(task.url, wp_path_id)
        return result
    except Exception as e:
        handle_115_error(e)


@router.get("/offline/tasks")
async def get_offline_tasks(page: int = Query(1, ge=1, description="页码")):
    """
    获取离线任务列表

    返回离线下载任务列表
    """
    service = get_service()
    try:
        result = await service.offline_task_list(page)
        return result
    except Exception as e:
        error_msg = str(e)
        if (
            "code=405" in error_msg
            or "Method Not Allowed" in error_msg
            or "task_lists" in error_msg
        ):
            raise HTTPException(
                status_code=429, detail="离线任务列表请求过于频繁，请稍后重试"
            )
        handle_115_error(e)


@router.delete("/offline/tasks")
async def delete_offline_tasks(
    hash_list: List[str] = Query(..., description="任务hash列表"),
):
    """
    删除离线任务

    删除指定的离线下载任务
    """
    service = get_service()
    try:
        result = await service.offline_task_delete(hash_list)
        return result
    except Exception as e:
        handle_115_error(e)


@router.post("/offline/restart")
async def restart_offline_task(
    info_hash: str = Query(..., description="任务info_hash"),
):
    """
    重试单个离线任务

    常用于失败任务重试。
    """
    service = get_service()
    try:
        result = await service.offline_task_restart(info_hash)
        return result
    except Exception as e:
        handle_115_error(e)


@router.post("/offline/clear")
async def clear_offline_tasks(
    mode: str = Query("completed", description="completed/failed/all"),
):
    """
    清空离线任务

    清空所有已完成和失败的离线任务
    """
    service = get_service()
    try:
        mode_map = {
            "completed": 0,
            "failed": 2,
            "all": 1,
        }
        clear_flag = mode_map.get((mode or "completed").strip().lower(), 0)
        result = await service.offline_task_clear(clear_flag)
        return result
    except Exception as e:
        handle_115_error(e)


# ==================== 分享链接操作 ====================


@router.post("/share/parse")
async def parse_share_link(share_url: str = Query(..., description="分享链接或分享码")):
    """
    解析分享链接

    解析分享链接，获取分享信息
    """
    service = get_service()
    try:
        result = await service.parse_share_link(share_url)
        return result
    except Exception as e:
        handle_115_error(e)


@router.get("/share/files")
async def get_share_file_list(
    share_code: str = Query(..., description="分享码"),
    receive_code: str = Query("", description="提取码"),
    cid: str = Query("0", description="目录ID"),
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(50, ge=1, le=115, description="返回数量"),
):
    """
    获取分享文件列表

    返回分享链接中的文件列表
    """
    service = get_service()
    try:
        result = await service.get_share_file_list(
            share_code, receive_code, cid, offset, limit
        )
        return result
    except Exception as e:
        handle_115_error(e)


@router.post("/share/save")
async def save_share_file(request: SaveShareRequest):
    """
    转存分享文件

    将分享链接中的文件转存到网盘
    """
    service = get_service()
    try:
        target_pid = _get_transfer_default_folder_id()
        result = await service.save_share_file(
            request.share_code, request.file_id, target_pid, request.receive_code
        )
        asyncio.create_task(_trigger_archive_if_enabled("transfer"))
        return result
    except Exception as e:
        handle_115_error(e)


@router.post("/share/save-batch")
async def save_share_files(request: SaveShareFilesRequest):
    """
    批量转存分享文件

    将分享链接中的多个文件转存到网盘
    """
    service = get_service()
    try:
        target_pid = _get_transfer_default_folder_id()
        result = await service.save_share_files(
            request.share_code, request.file_ids, target_pid, request.receive_code
        )
        asyncio.create_task(_trigger_archive_if_enabled("transfer"))
        return result
    except Exception as e:
        handle_115_error(e)


@router.post("/share/save-all")
async def save_share_all(
    share_code: str = Query(..., description="分享码"),
    pid: str = Query("0", description="目标目录ID"),
    receive_code: str = Query("", description="提取码"),
):
    """
    转存分享链接中的所有文件

    将分享链接中的所有文件转存到网盘
    """
    service = get_service()
    try:
        target_pid = _get_transfer_default_folder_id()
        result = await service.save_share_all(share_code, target_pid, receive_code)
        asyncio.create_task(_trigger_archive_if_enabled("transfer"))
        return result
    except Exception as e:
        handle_115_error(e)


@router.post("/share/save-to-folder")
async def save_share_to_folder(request: SaveShareToFolderRequest):
    """
    转存分享到指定文件夹

    将分享链接中的文件转存到指定名称的文件夹中（如果文件夹不存在会自动创建）
    如果提供了 tmdb_id，则会使用 Emby 差集比对进行追更转存
    """
    service = get_service()
    transfer_parent_id = _get_transfer_default_folder_id()
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            # 1. 首先确保目标文件夹存在
            target_folder_id = await service.get_or_create_folder(
                transfer_parent_id, request.folder_name
            )

            # 2. 如果提供了 tmdb_id，说明这是一个剧集，进行查漏补缺式的转存
            if request.tmdb_id:
                result = await sync_service.sync_tv_show(
                    tmdb_id=request.tmdb_id,
                    share_url=request.share_url,
                    target_folder_id=target_folder_id,
                    receive_code=request.receive_code,
                )
                asyncio.create_task(_trigger_archive_if_enabled("transfer"))
                return result

            # 3. 如果没有 tmdb_id，走默认的全量转存逻辑
            result = await service.save_share_to_folder(
                request.share_url,
                request.folder_name,
                transfer_parent_id,
                request.receive_code,
            )
            asyncio.create_task(_trigger_archive_if_enabled("transfer"))
            return result
        except Exception as e:
            last_error = e
            if attempt < 3 and is_retryable_115_error(str(e)):
                await asyncio.sleep(build_retry_delay(attempt))
                continue
            if is_retryable_115_error(str(e)):
                return {
                    "success": False,
                    "message": "115接口临时受限，已自动重试多次，请稍后再试",
                    "retryable": True,
                    "saved_count": 0,
                }
            handle_115_error(e)

    if last_error:
        handle_115_error(last_error)


@router.post("/share/extract-files")
async def extract_share_files(request: ShareExtractFilesRequest):
    """
    提取分享链接内的所有文件

    返回分享链接内的所有文件列表，供用户勾选转存
    """
    service = get_service()
    try:
        # 使用服务层的 parse_share_link 或者直接提取分享码，调用递归获取方法
        from p115client.util import share_extract_payload
        import re

        share_url = (request.share_url or "").strip()
        try:
            share_payload = share_extract_payload(share_url)
        except Exception:
            share_payload = {
                "share_code": service._extract_share_code(share_url) or "",
                "receive_code": "",
            }

        share_code = share_payload.get("share_code")
        if not share_code:
            raise ValueError("无效的分享链接格式")

        receive_code = request.receive_code
        if not receive_code:
            receive_code = share_payload.get("receive_code") or ""
            if not receive_code:
                short_receive_match = re.match(
                    r"^[A-Za-z0-9]+-([A-Za-z0-9]{4})$", share_url
                )
                if short_receive_match:
                    receive_code = short_receive_match.group(1)
            if not receive_code:
                password_match = re.search(
                    r"(?:password|pwd)=([^&#]+)", share_url, re.IGNORECASE
                )
                receive_code = password_match.group(1) if password_match else ""
            if not receive_code:
                text_receive_match = re.search(
                    r"(?:提取码|提取碼|密码|密碼)\s*[:：=]?\s*([A-Za-z0-9]{4})",
                    share_url,
                    re.IGNORECASE,
                )
                receive_code = text_receive_match.group(1) if text_receive_match else ""

        all_files = await service.get_share_all_files_recursive(
            share_code, receive_code
        )
        return {"success": True, "list": all_files}
    except Exception as e:
        handle_115_error(e)


@router.post("/share/save-files-to-folder")
async def save_share_files_to_folder(request: SaveShareFilesToFolderRequest):
    """
    选集转存到指定文件夹

    将用户勾选的部分文件转存到指定名称的文件夹中
    """
    service = get_service()
    transfer_parent_id = _get_transfer_default_folder_id()
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            result = await service.save_share_files_to_folder(
                request.share_url,
                request.file_ids,
                request.folder_name,
                transfer_parent_id,
                request.receive_code,
            )
            asyncio.create_task(_trigger_archive_if_enabled("transfer"))
            return result
        except Exception as e:
            last_error = e
            if attempt < 3 and is_retryable_115_error(str(e)):
                await asyncio.sleep(build_retry_delay(attempt))
                continue
            if is_retryable_115_error(str(e)):
                return {
                    "success": False,
                    "message": "115接口临时受限，已自动重试多次，请稍后再试",
                    "retryable": True,
                    "saved_count": 0,
                }
            handle_115_error(e)

    if last_error:
        handle_115_error(last_error)


# ==================== 默认转存文件夹设置 ====================


@router.get("/default-folder")
async def get_default_folder():
    """
    获取默认转存文件夹设置
    """
    return runtime_settings_service.get_pan115_default_folder()


@router.post("/default-folder")
async def set_default_folder(request: DefaultFolderRequest):
    """
    设置默认转存文件夹
    """
    folder = runtime_settings_service.update_pan115_default_folder(
        request.folder_id,
        request.folder_name or "",
    )
    return {
        "success": True,
        "message": "设置成功",
        "folder_id": folder["folder_id"],
        "folder_name": folder["folder_name"],
    }


# ==================== 默认离线文件夹设置 ====================


@router.get("/offline/default-folder")
async def get_offline_default_folder():
    """
    获取默认离线文件夹设置
    """
    return runtime_settings_service.get_pan115_offline_folder()


@router.post("/offline/default-folder")
async def set_offline_default_folder(request: DefaultFolderRequest):
    """
    设置默认离线文件夹
    """
    folder = runtime_settings_service.update_pan115_offline_folder(
        request.folder_id,
        request.folder_name or "",
    )
    return {
        "success": True,
        "message": "设置成功",
        "folder_id": folder["folder_id"],
        "folder_name": folder["folder_name"],
    }
