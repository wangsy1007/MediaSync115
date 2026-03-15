"""
Nullbr 通用 API 客户端
基于配置自动生成方法，支持所有 Nullbr API 接口
"""

import httpx
from typing import Any, Optional
from app.core.config import settings
from app.services.nullbr_api_config import API_CONFIG, AuthType
from app.utils.proxy import proxy_manager


class NullbrClient:
    """Nullbr API 通用客户端（同步版本）"""

    def __init__(
        self,
        app_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.app_id = app_id or settings.NULLBR_APP_ID
        self.api_key = api_key or settings.NULLBR_API_KEY
        self.base_url = base_url or settings.NULLBR_BASE_URL
        self._client: Optional[httpx.Client] = None
        self._timeout = 30.0

        # 为每个 API 配置生成对应的方法
        self._generate_methods()

    def _get_client(self) -> httpx.Client:
        """获取或创建配置了代理的 httpx 客户端"""
        if self._client is None:
            self._client = proxy_manager.create_sync_httpx_client(timeout=self._timeout)
        return self._client

    def _generate_methods(self):
        """根据 API 配置自动生成方法"""
        for name, config in API_CONFIG.items():
            method_name = self._to_method_name(name)
            setattr(self, method_name, self._create_method(name, config))

    def _to_method_name(self, name: str) -> str:
        """将 API 名称转换为方法名"""
        return name

    def _create_method(self, name: str, config: dict):
        """为单个 API 创建方法"""

        def method(*args, **kwargs):
            return self._request(name, config, *args, **kwargs)

        # 设置方法文档
        method.__doc__ = f"""
        调用 Nullbr API: {config['method']} {config['path']}

        鉴权方式: {config['auth']}
        """
        return method

    def _request(
        self,
        name: str,
        config: dict,
        *args,
        **kwargs
    ) -> dict:
        """
        执行 API 请求

        Args:
            name: API 名称
            config: API 配置
            *args: 位置参数，按 path_params 顺序传递
            **kwargs: 命名参数，支持 path_params, query_params, body_params
        """
        # 构建 URL 路径
        path = config["path"]
        path_params = config.get("path_params", [])

        # 处理位置参数
        for i, param in enumerate(path_params):
            if i < len(args):
                path = path.replace(f"{{{param}}}", str(args[i]))
            elif param in kwargs:
                path = path.replace(f"{{{param}}}", str(kwargs[param]))

        # 构建查询参数
        query_params = config.get("query_params", [])
        query = {}
        for param in query_params:
            if param in kwargs:
                query[param] = kwargs[param]

        # 构建请求体
        body_params = config.get("body_params", [])
        body = None
        if body_params:
            body_dict = {}
            for param in body_params:
                if param in kwargs:
                    body_dict[param] = kwargs[param]
            if body_dict:
                body = body_dict

        # 构建请求头
        headers = self._build_headers(config["auth"])

        # 发送请求
        url = f"{self.base_url}{path.lstrip('/')}"

        client = self._get_client()
        response = client.request(
            method=config["method"],
            url=url,
            params=query if query else None,
            json=body,
            headers=headers,
        )

        # 检查响应状态
        response.raise_for_status()

        data = response.json()

        # 返回完整响应数据
        return data

    def _build_headers(self, auth: AuthType) -> dict:
        """根据鉴权类型构建请求头"""
        headers = {
            "X-APP-ID": self.app_id,
            "User-Agent": "MediaSync115/v1.0.2",
        }

        if auth == "app_id+api_key":
            headers["X-API-KEY"] = self.api_key

        return headers

    def close(self):
        """关闭客户端"""
        if self._client is not None:
            self._client.close()
            self._client = None

    def update_config(
        self,
        app_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        """运行时更新 Nullbr 配置。"""
        if app_id is not None:
            cleaned_app_id = str(app_id).strip()
            if cleaned_app_id:
                self.app_id = cleaned_app_id
        if api_key is not None:
            cleaned_api_key = str(api_key).strip()
            if cleaned_api_key:
                self.api_key = cleaned_api_key
        if base_url is not None:
            cleaned_base_url = str(base_url).strip()
            if cleaned_base_url:
                self.base_url = cleaned_base_url
        # 关闭旧客户端，下次请求时会使用新配置创建
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 创建默认客户端实例
nullbr_client = NullbrClient()
