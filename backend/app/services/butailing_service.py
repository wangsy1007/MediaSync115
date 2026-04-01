"""
不太灵 (Butailing) 服务层
通过不太灵 API 搜索影视磁力资源
"""

import hashlib
import httpx
from typing import Any

from app.utils.proxy import proxy_manager

_BTL_API_BASE = "https://web5.mukaku.com/prod/api/v1/"
_BTL_DEFAULT_APP_ID = "83768d9ad4"
_BTL_DEFAULT_IDENTITY = "23734adac0301bccdcb107c4aa21f96c"


class ButailingService:
    """不太灵 API 服务类"""

    def __init__(self):
        self.base_url = _BTL_API_BASE
        self.app_id = _BTL_DEFAULT_APP_ID
        self.identity = _BTL_DEFAULT_IDENTITY
        self.client = self._build_client()

    def _build_client(self) -> httpx.AsyncClient:
        return proxy_manager.create_httpx_client(
            base_url=self.base_url,
            timeout=30.0,
            follow_redirects=True,
        )

    def _auth_params(self) -> dict[str, str]:
        return {"app_id": self.app_id, "identity": self.identity}

    async def search_videos(
        self, keyword: str, page: int = 1, limit: int = 24
    ) -> dict[str, Any]:
        """搜索影视列表"""
        params = {**self._auth_params(), "sb": keyword, "page": page, "limit": limit}
        try:
            resp = await self.client.get("getVideoList", params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {"success": False, "data": {"data": []}}

    async def get_video_detail(self, douban_id: int) -> dict[str, Any]:
        """获取影视详情，包含磁力资源"""
        params = {**self._auth_params(), "id": douban_id}
        try:
            resp = await self.client.get("getVideoDetail", params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {"success": False, "data": {}}

    async def search_magnets(
        self,
        keyword: str,
        media_type: str = "movie",
        douban_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        搜索不太灵并提取磁力资源

        流程:
        1. 用关键词搜索视频列表
        2. 从结果中找到匹配的影视
        3. 获取详情页中的 all_seeds 磁力资源
        """
        # 步骤1: 搜索视频
        search_result = await self.search_videos(keyword)
        data = search_result.get("data", {})
        video_list = data.get("data", []) if isinstance(data, dict) else []
        if not isinstance(video_list, list) or not video_list:
            return []

        # 步骤2: 选择最匹配的视频
        target_type = 2 if media_type == "tv" else 1
        target_video = None

        # 优先通过 douban_id 精确匹配
        if douban_id:
            for v in video_list:
                if v.get("doub_id") == douban_id:
                    target_video = v
                    break

        # 其次通过类型和标题匹配
        if not target_video:
            for v in video_list:
                if v.get("type") == target_type:
                    target_video = v
                    break

        if not target_video:
            return []

        # 步骤3: 获取详情
        video_douban_id = target_video.get("doub_id")
        if not video_douban_id:
            return []

        detail_result = await self.get_video_detail(video_douban_id)
        detail_data = detail_result.get("data", {})
        if not isinstance(detail_data, dict):
            return []

        # 步骤4: 提取磁力资源
        all_seeds = detail_data.get("all_seeds", [])
        if not isinstance(all_seeds, list):
            return []

        resources: list[dict[str, Any]] = []
        video_title = target_video.get("title", keyword)

        for index, seed in enumerate(all_seeds):
            if not isinstance(seed, dict):
                continue
            magnet_link = str(seed.get("zlink", "")).strip()
            if not magnet_link or not magnet_link.startswith("magnet:"):
                continue

            seed_name = str(seed.get("zname", "")).strip()
            title = seed_name or f"{video_title} - 磁力资源 #{index + 1}"
            size = str(seed.get("zsize", "")).strip()
            quality = str(seed.get("zqxd", "")).strip()

            unique_key = f"btl:{magnet_link}"
            resource_id = f"btl-{hashlib.md5(unique_key.encode('utf-8')).hexdigest()[:12]}-{index}"

            resources.append(
                {
                    "id": resource_id,
                    "name": title,
                    "size": size,
                    "quality": quality,
                    "magnet": magnet_link,
                    "source_service": "butailing",
                }
            )

        return resources


butailing_service = ButailingService()
