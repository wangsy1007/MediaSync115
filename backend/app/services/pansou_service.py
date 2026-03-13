"""
Pansou 服务层
提供网盘资源搜索功能
"""

import asyncio
import httpx
import json
from typing import List, Union
from app.core.config import settings
from app.utils.proxy import proxy_manager


class PansouService:
    """Pansou API 服务类"""

    def __init__(self, base_url: str | None = None):
        self.base_url = self._normalize_base_url(base_url or settings.PANSOU_BASE_URL)
        self.client = self._build_client()

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        cleaned = str(base_url or "").strip()
        if not cleaned:
            raise ValueError("pansou base_url 不能为空")
        if not cleaned.endswith("/"):
            cleaned = cleaned + "/"
        return cleaned

    def _build_client(self) -> httpx.AsyncClient:
        return proxy_manager.create_httpx_client(
            base_url=self.base_url,
            timeout=30.0,
            follow_redirects=True
        )

    def set_base_url(self, base_url: str) -> str:
        normalized_base_url = self._normalize_base_url(base_url)
        if normalized_base_url == self.base_url:
            return self.base_url

        old_client = self.client
        self.base_url = normalized_base_url
        self.client = self._build_client()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(old_client.aclose())
        except RuntimeError:
            # no running event loop
            pass
        return self.base_url

    def get_base_url(self) -> str:
        return self.base_url

    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()

    async def health_check(self, base_url: str | None = None) -> dict:
        """
        检查 pansou 服务健康状态。
        使用临时 client 避免长生命周期 client 的连接状态问题。

        Args:
            base_url: 可选，指定要检测的地址；为空则使用当前配置的地址

        Returns:
            dict: 健康状态
        """
        target_url = self._normalize_base_url(base_url) if base_url else self.base_url
        try:
            async with httpx.AsyncClient(
                base_url=target_url,
                timeout=5.0,
                follow_redirects=True,
            ) as client:
                response = await client.get("/api/health")
                return {
                    "status": "healthy" if response.status_code == 200 else "unhealthy",
                    "code": response.status_code,
                    "data": response.json() if response.status_code == 200 else None
                }
        except Exception as e:
            return {
                "status": "error",
                "error": f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            }

    async def search(
        self,
        keyword: str,
        cloud_types: Union[str, List[str]] = "115",
        res: str = "results",
        refresh: bool = False
    ) -> dict:
        """
        搜索网盘资源

        Args:
            keyword: 搜索关键词
            cloud_types: 网盘类型过滤，默认 ["115"]，支持 baidu/aliyun/quark/xunlei/uc/115/tianyiyun/123 等
            res: 结果类型 (all/results/merge)
            refresh: 是否强制刷新缓存

        Returns:
            dict: 搜索结果
        """
        # 将字符串转换为列表
        if isinstance(cloud_types, str):
            cloud_types = [cloud_types]

        try:
            response = await self.client.post(
                "/api/search",
                json={
                    "kw": keyword,
                    "cloud_types": cloud_types,
                    "res": res,
                    "refresh": refresh
                }
            )
            if response.status_code == 200:
                try:
                    return response.json()
                except Exception as e:
                    # 尝试使用其他方式解析
                    content = response.content
                    # 尝试 latin-1 可以解码任何字节
                    text = content.decode('latin-1')
                    # 然后尝试解析
                    try:
                        return json.loads(text)
                    except:
                        # 最后尝试忽略错误
                        text = content.decode('utf-8', errors='ignore')
                        return json.loads(text)
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "message": response.text[:500]
                }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": str(e),
                "message": "请求失败"
            }

    async def search_115(self, keyword: str, res: str = "results") -> dict:
        """
        搜索 115 网盘资源（便捷方法）

        Args:
            keyword: 搜索关键词
            res: 结果类型

        Returns:
            dict: 搜索结果
        """
        return await self.search(keyword, cloud_types=["115"], res=res)


# 创建服务实例
pansou_service = PansouService()
