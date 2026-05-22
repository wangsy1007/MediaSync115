"""夸克网盘服务

封装夸克网盘的逆向接口（参考 quark-auto-save 等社区项目）。
所有远程调用使用 httpx.AsyncClient，超时阈值默认 30s。
Cookie 失效时在内存内标记 invalid 并在 5 分钟内短路 401。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

from app.core.config import settings
from app.utils.proxy import proxy_manager

logger = logging.getLogger(__name__)

_QUARK_SHARE_URL_PATTERN = re.compile(
    r"https?://pan\.quark\.cn/s/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


class QuarkService:
    """夸克网盘服务"""

    _BASE_URL = "https://drive-pc.quark.cn"
    _CONNECT_TIMEOUT = 15.0
    _READ_TIMEOUT = 30.0
    _SAVE_OPERATION_TIMEOUT = 180.0
    _INVALID_COOKIE_TTL_SECONDS = 5 * 60

    def __init__(self, cookie: Optional[str] = None) -> None:
        self._cookie = (cookie or "").strip()
        self._invalid_until: float = 0.0
        self._invalid_reason: str = ""

    # ───── cookie 管理 ─────

    def update_cookie(self, cookie: str) -> None:
        """更新 Cookie 并清除 invalid 标记"""
        self._cookie = str(cookie or "").strip()
        self.clear_invalid()

    def is_configured(self) -> bool:
        return bool(self._cookie)

    def is_invalidated(self) -> bool:
        if self._invalid_until <= 0:
            return False
        return time.time() < self._invalid_until

    def mark_invalid(self, reason: str = "cookie_invalid") -> None:
        self._invalid_until = time.time() + self._INVALID_COOKIE_TTL_SECONDS
        self._invalid_reason = reason

    def clear_invalid(self) -> None:
        self._invalid_until = 0.0
        self._invalid_reason = ""

    def _check_preconditions(self) -> None:
        """检查前置条件，不满足时抛异常"""
        if not self._cookie:
            raise ValueError("quark_cookie_missing")
        if self.is_invalidated():
            raise ValueError("quark_cookie_invalid")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Cookie": self._cookie,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://pan.quark.cn/",
            "Accept": "application/json, text/plain, */*",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """发起夸克 API 请求"""
        self._check_preconditions()
        url = f"{self._BASE_URL}{path}"
        effective_timeout = timeout or self._READ_TIMEOUT
        client = proxy_manager.create_httpx_client(timeout=effective_timeout)
        try:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=self._build_headers(),
            )
            if response.status_code == 401 or response.status_code == 403:
                self.mark_invalid("cookie_expired")
                raise ValueError("quark_cookie_invalid")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {}
            # 夸克 API 通用错误码检查
            code = int(payload.get("code") or payload.get("status") or 0)
            if code == 401 or code == 403:
                self.mark_invalid("cookie_expired")
                raise ValueError("quark_cookie_invalid")
            if code == 429:
                raise ValueError("quark_rate_limited")
            return payload
        except ValueError:
            raise
        except Exception as exc:
            error_text = str(exc).lower()
            if "429" in error_text or "rate" in error_text:
                raise ValueError("quark_rate_limited")
            raise
        finally:
            await client.aclose()

    # ───── 连通性 / 用户 ─────

    async def check_cookie_valid(self) -> dict[str, Any]:
        """检查 Cookie 是否有效，返回用户信息"""
        try:
            payload = await self._request(
                "GET",
                "/1/clouddrive/capacity/growth/info",
                params={"pr": "ucpro", "fr": "pc"},
            )
            data = payload.get("data") or {}
            return {
                "valid": True,
                "user_info": {
                    "total_capacity": data.get("total_capacity"),
                    "use_capacity": data.get("use_capacity"),
                },
                "message": "连接成功",
            }
        except ValueError as exc:
            reason = str(exc)
            if reason in ("quark_cookie_missing", "quark_cookie_invalid"):
                return {"valid": False, "user_info": None, "message": "Cookie 无效或已过期"}
            return {"valid": False, "user_info": None, "message": str(exc)}
        except Exception as exc:
            return {"valid": False, "user_info": None, "message": f"连接失败: {str(exc)[:100]}"}

    async def get_account_info(self) -> dict[str, Any]:
        """获取账号信息"""
        payload = await self._request(
            "GET",
            "/1/clouddrive/capacity/growth/info",
            params={"pr": "ucpro", "fr": "pc"},
        )
        return payload.get("data") or {}

    # ───── 目录浏览 ─────

    async def list_folders(
        self, parent_fid: str = "0", *, page: int = 1, size: int = 200
    ) -> dict[str, Any]:
        """列出指定目录下的子目录"""
        self._check_preconditions()
        payload = await self._request(
            "GET",
            "/1/clouddrive/file/sort",
            params={
                "pr": "ucpro",
                "fr": "pc",
                "pdir_fid": parent_fid,
                "_page": page,
                "_size": size,
                "_fetch_total": 1,
                "_sort": "file_type:asc,updated_at:desc",
            },
        )
        data = payload.get("data") or {}
        items = data.get("list") or []
        # 只返回目录
        folders = [
            {
                "fid": item.get("fid"),
                "file_name": item.get("file_name"),
                "pdir_fid": item.get("pdir_fid"),
                "dir_type": item.get("dir") or item.get("file_type") == 0,
            }
            for item in items
            if isinstance(item, dict) and (item.get("dir") or item.get("file_type") == 0)
        ]
        return {
            "folders": folders,
            "total": int(data.get("_total") or len(folders)),
            "page": page,
            "size": size,
        }

    # ───── 分享解析与转存 ─────

    def parse_share_url(self, share_url: str) -> dict[str, Any]:
        """从 https://pan.quark.cn/s/{share_id} 解析 share_id 和提取码"""
        raw = str(share_url or "").strip()
        if not raw:
            raise ValueError("share_url 不能为空")

        match = _QUARK_SHARE_URL_PATTERN.search(raw)
        if not match:
            raise ValueError(f"无法识别的夸克分享链接: {raw[:80]}")

        share_id = match.group(1)
        # 尝试从 URL 参数中提取提取码
        parsed = urlparse(raw)
        qs = parse_qs(parsed.query)
        passcode = (qs.get("passcode") or qs.get("pwd") or [""])[0]

        return {
            "share_id": share_id,
            "passcode": passcode,
        }

    async def get_share_token(
        self, share_id: str, passcode: str = ""
    ) -> dict[str, Any]:
        """获取分享 token（用于后续操作）"""
        payload = await self._request(
            "POST",
            "/1/clouddrive/share/sharepage/token",
            params={"pr": "ucpro", "fr": "pc"},
            json_body={
                "pwd_id": share_id,
                "passcode": passcode,
            },
        )
        data = payload.get("data") or {}
        stoken = data.get("stoken") or ""
        if not stoken:
            raise ValueError("获取分享 token 失败，分享可能已失效或需要提取码")
        return {"stoken": stoken, "share_id": share_id}

    async def list_share_files(
        self,
        share_id: str,
        stoken: str,
        *,
        parent_fid: str = "0",
        page: int = 1,
        size: int = 200,
    ) -> list[dict[str, Any]]:
        """列出分享内的文件"""
        payload = await self._request(
            "GET",
            "/1/clouddrive/share/sharepage/detail",
            params={
                "pr": "ucpro",
                "fr": "pc",
                "pwd_id": share_id,
                "stoken": stoken,
                "pdir_fid": parent_fid,
                "_page": page,
                "_size": size,
                "_fetch_total": 1,
            },
        )
        data = payload.get("data") or {}
        items = data.get("list") or []
        return [item for item in items if isinstance(item, dict)]

    async def save_share_to_folder(
        self,
        share_url: str,
        target_folder_fid: str,
        *,
        folder_name: Optional[str] = None,
        passcode: str = "",
        tmdb_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """转存分享到指定目录

        流程：
        1. 解析分享 URL
        2. 获取 stoken
        3. 列出分享内文件
        4. 如果指定 folder_name，在目标目录下创建子目录
        5. 批量转存
        """
        self._check_preconditions()

        # 1. 解析
        parsed = self.parse_share_url(share_url)
        share_id = parsed["share_id"]
        effective_passcode = passcode or parsed.get("passcode") or ""

        # 2. 获取 stoken
        token_result = await self.get_share_token(share_id, effective_passcode)
        stoken = token_result["stoken"]

        # 3. 列出文件
        files = await self.list_share_files(share_id, stoken)
        if not files:
            return {
                "success": False,
                "item_count": 0,
                "message": "分享内无文件或分享已失效",
            }

        # 4. 创建子目录（如果需要）
        save_fid = target_folder_fid
        if folder_name:
            try:
                save_fid = await self._create_folder(target_folder_fid, folder_name)
            except Exception as exc:
                logger.warning("创建夸克子目录失败: %s, 使用父目录", exc)
                save_fid = target_folder_fid

        # 5. 批量转存
        file_ids = [f.get("fid") for f in files if f.get("fid")]
        if not file_ids:
            return {
                "success": False,
                "item_count": 0,
                "message": "分享内无有效文件 ID",
            }

        save_result = await self._save_files(
            share_id=share_id,
            stoken=stoken,
            file_ids=file_ids,
            target_fid=save_fid,
        )

        return {
            "success": True,
            "item_count": len(file_ids),
            "target_folder": {"folder_id": save_fid, "folder_name": folder_name or ""},
            "message": f"成功转存 {len(file_ids)} 个文件",
            "save_result": save_result,
        }

    async def _create_folder(self, parent_fid: str, folder_name: str) -> str:
        """在指定目录下创建子目录，返回新目录的 fid"""
        payload = await self._request(
            "POST",
            "/1/clouddrive/file",
            params={"pr": "ucpro", "fr": "pc"},
            json_body={
                "pdir_fid": parent_fid,
                "file_name": folder_name,
                "dir_init_lock": False,
                "dir_path": "",
            },
        )
        data = payload.get("data") or {}
        fid = data.get("fid") or ""
        if not fid:
            raise ValueError(f"创建目录失败: {payload.get('message') or '未知错误'}")
        return fid

    async def _save_files(
        self,
        share_id: str,
        stoken: str,
        file_ids: list[str],
        target_fid: str,
    ) -> dict[str, Any]:
        """批量转存文件到目标目录"""
        fid_list = [{"fid": fid} for fid in file_ids]
        payload = await self._request(
            "POST",
            "/1/clouddrive/share/sharepage/save",
            params={"pr": "ucpro", "fr": "pc"},
            json_body={
                "pwd_id": share_id,
                "stoken": stoken,
                "fid_list": fid_list,
                "fid_token_list": [],
                "to_pdir_fid": target_fid,
                "scene": "link",
            },
            timeout=self._SAVE_OPERATION_TIMEOUT,
        )
        data = payload.get("data") or {}
        task_id = data.get("task_id") or ""
        return {
            "task_id": task_id,
            "saved_count": len(file_ids),
        }


# 全局单例
quark_service = QuarkService()
