"""
代理配置工具模块
提供统一的代理配置解析和 httpx 客户端代理支持
"""

from typing import Optional, Dict, Any
from urllib.parse import urlparse
from app.core.config import settings


def get_proxy_config() -> Dict[str, Optional[str]]:
    """
    获取代理配置

    Returns:
        包含 http, https, all, socks 代理设置的字典
    """
    return {
        "http": settings.HTTP_PROXY,
        "https": settings.HTTPS_PROXY,
        "all": settings.ALL_PROXY,
        "socks": settings.SOCKS_PROXY,
    }


def get_httpx_proxy_mounts() -> Optional[Dict[str, Any]]:
    """
    获取 httpx 客户端的代理配置 mounts

    Returns:
        httpx.AsyncClient 可用的 mounts 字典，如果没有配置代理则返回 None
    """
    http_proxy = settings.HTTP_PROXY or settings.ALL_PROXY
    https_proxy = settings.HTTPS_PROXY or settings.ALL_PROXY

    mounts = {}

    if http_proxy:
        mounts["http://"] = httpx.HTTPTransport(proxy=http_proxy)

    if https_proxy:
        mounts["https://"] = httpx.HTTPTransport(proxy=https_proxy)

    return mounts if mounts else None


def get_httpx_client_kwargs() -> Dict[str, Any]:
    """
    获取创建 httpx.AsyncClient 时的关键字参数（包含代理配置）

    Returns:
        可用于 httpx.AsyncClient(**kwargs) 的字典
    """
    kwargs: Dict[str, Any] = {}
    mounts = get_httpx_proxy_mounts()
    if mounts:
        kwargs["mounts"] = mounts
    return kwargs


def parse_proxy_url(proxy_url: str) -> Dict[str, Any]:
    """
    解析代理 URL

    Args:
        proxy_url: 代理 URL，如 http://127.0.0.1:7890 或 socks5://user:pass@host:port

    Returns:
        包含 scheme, host, port, username, password 的字典
    """
    parsed = urlparse(str(proxy_url or ""))
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "username": parsed.username,
        "password": parsed.password,
        "url": proxy_url,
    }


def should_use_proxy_for_url(url: str) -> bool:
    """
    检查是否应该对给定 URL 使用代理

    Args:
        url: 目标 URL

    Returns:
        是否应该使用代理
    """
    parsed = urlparse(str(url or ""))
    scheme = parsed.scheme.lower()

    if scheme == "http" and (settings.HTTP_PROXY or settings.ALL_PROXY):
        return True
    if scheme == "https" and (settings.HTTPS_PROXY or settings.ALL_PROXY):
        return True

    return False


# 延迟导入 httpx，避免循环导入
httpx = None


def _get_httpx():
    """延迟加载 httpx 模块"""
    global httpx
    if httpx is None:
        import httpx as _httpx
        httpx = _httpx
    return httpx


class ProxyManager:
    """代理管理器，用于统一管理代理配置"""

    def __init__(self):
        self._http_proxy: Optional[str] = None
        self._https_proxy: Optional[str] = None
        self._all_proxy: Optional[str] = None
        self._socks_proxy: Optional[str] = None
        self._reload()

    def _reload(self) -> None:
        """从设置重新加载代理配置"""
        self._http_proxy = settings.HTTP_PROXY
        self._https_proxy = settings.HTTPS_PROXY
        self._all_proxy = settings.ALL_PROXY
        self._socks_proxy = settings.SOCKS_PROXY

    def update_proxy(
        self,
        http_proxy: Optional[str] = None,
        https_proxy: Optional[str] = None,
        all_proxy: Optional[str] = None,
        socks_proxy: Optional[str] = None,
    ) -> None:
        """
        更新代理配置

        Args:
            http_proxy: HTTP 代理 URL
            https_proxy: HTTPS 代理 URL
            all_proxy: 通用代理 URL
            socks_proxy: SOCKS 代理 URL
        """
        if http_proxy is not None:
            self._http_proxy = http_proxy if http_proxy.strip() else None
            settings.HTTP_PROXY = self._http_proxy
        if https_proxy is not None:
            self._https_proxy = https_proxy if https_proxy.strip() else None
            settings.HTTPS_PROXY = self._https_proxy
        if all_proxy is not None:
            self._all_proxy = all_proxy if all_proxy.strip() else None
            settings.ALL_PROXY = self._all_proxy
        if socks_proxy is not None:
            self._socks_proxy = socks_proxy if socks_proxy.strip() else None
            settings.SOCKS_PROXY = self._socks_proxy

    def get_proxy_for_scheme(self, scheme: str) -> Optional[str]:
        """
        获取指定协议的代理

        Args:
            scheme: 协议类型 (http, https, socks5)

        Returns:
            代理 URL 或 None
        """
        scheme = scheme.lower()
        if scheme == "http":
            return self._http_proxy or self._all_proxy
        elif scheme == "https":
            return self._https_proxy or self._all_proxy
        elif scheme in ("socks", "socks5"):
            return self._socks_proxy or self._all_proxy
        return self._all_proxy

    def create_httpx_client(self, **kwargs) -> "httpx.AsyncClient":
        """
        创建配置了代理的 httpx.AsyncClient

        Args:
            **kwargs: 传递给 httpx.AsyncClient 的其他参数

        Returns:
            配置了代理的 AsyncClient 实例
        """
        httpx_module = _get_httpx()

        client_kwargs = dict(kwargs)
        mounts = {}

        http_proxy = self._http_proxy or self._all_proxy
        https_proxy = self._https_proxy or self._all_proxy

        if http_proxy:
            mounts["http://"] = httpx_module.HTTPTransport(proxy=http_proxy)
        if https_proxy:
            mounts["https://"] = httpx_module.HTTPTransport(proxy=https_proxy)

        if mounts:
            client_kwargs["mounts"] = mounts

        return httpx_module.AsyncClient(**client_kwargs)

    def get_current_config(self) -> Dict[str, Optional[str]]:
        """获取当前代理配置"""
        return {
            "http_proxy": self._http_proxy,
            "https_proxy": self._https_proxy,
            "all_proxy": self._all_proxy,
            "socks_proxy": self._socks_proxy,
        }


# 全局代理管理器实例
proxy_manager = ProxyManager()
