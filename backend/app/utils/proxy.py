"""
代理配置工具模块
提供统一的代理配置解析和 httpx 客户端代理支持
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

PROXY_REACHABILITY_TTL_SECONDS = 60
PROXY_REACHABILITY_TIMEOUT_SECONDS = 3.0

from app.core.config import settings

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})
_DOCKER_HOST_ALIAS = "host.docker.internal"


def is_running_in_docker() -> bool:
    """检测当前进程是否运行在 Docker 容器内。"""
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
        return "docker" in content or "containerd" in content
    except OSError:
        return False


def _normalize_proxy_url(value: str | None) -> Optional[str]:
    cleaned = str(value or "").strip()
    return cleaned or None


def normalize_proxy_url(
    value: str | None,
    *,
    rewrite_loopback_for_docker: bool | None = None,
) -> Optional[str]:
    """
    规范化代理 URL。

    - 补全缺失的协议（默认 http://）
    - Docker 内将 127.0.0.1/localhost 改写为 host.docker.internal
    """
    cleaned = _normalize_proxy_url(value)
    if not cleaned:
        return None

    if "://" not in cleaned:
        cleaned = f"http://{cleaned}"

    parsed = urlparse(cleaned)
    if not parsed.scheme or not parsed.netloc:
        return cleaned

    host = (parsed.hostname or "").strip().lower()
    should_rewrite = (
        rewrite_loopback_for_docker
        if rewrite_loopback_for_docker is not None
        else is_running_in_docker()
    )
    if should_rewrite and host in _LOOPBACK_HOSTS:
        port = parsed.port
        userinfo = ""
        if parsed.username is not None:
            userinfo = parsed.username
            if parsed.password is not None:
                userinfo = f"{userinfo}:{parsed.password}"
            userinfo = f"{userinfo}@"
        netloc = f"{userinfo}{_DOCKER_HOST_ALIAS}"
        if port:
            netloc = f"{netloc}:{port}"
        cleaned = urlunparse(
            (
                parsed.scheme,
                netloc,
                parsed.path or "",
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )
        logger.info(
            "Docker 环境已将代理地址 %s 改写为 %s",
            value,
            cleaned,
        )

    return cleaned


def pick_effective_proxy_url(
    *,
    http_proxy: str | None = None,
    https_proxy: str | None = None,
    all_proxy: str | None = None,
    socks_proxy: str | None = None,
) -> Optional[str]:
    """从多字段中选出一个生效的代理 URL（优先通用代理）。"""
    for value in (all_proxy, https_proxy, http_proxy, socks_proxy):
        normalized = normalize_proxy_url(value)
        if normalized:
            return normalized
    return None


def _pick_proxy_for_scheme(
    *,
    scheme: str,
    http_proxy: str | None,
    https_proxy: str | None,
    all_proxy: str | None,
    socks_proxy: str | None,
) -> Optional[str]:
    normalized_scheme = str(scheme or "").strip().lower()
    http_value = normalize_proxy_url(http_proxy)
    https_value = normalize_proxy_url(https_proxy)
    all_value = normalize_proxy_url(all_proxy)
    socks_value = normalize_proxy_url(socks_proxy)

    # 精简模式下通常只配置 all_proxy；仍兼容旧的分协议字段
    if normalized_scheme == "http":
        return http_value or all_value or socks_value or https_value
    if normalized_scheme == "https":
        return https_value or all_value or socks_value or http_value
    if normalized_scheme in {"socks", "socks4", "socks5", "socks5h"}:
        return socks_value or all_value or https_value or http_value
    return all_value or socks_value or https_value or http_value


def _should_bypass_proxy_for_host(hostname: str | None) -> bool:
    host = str(hostname or "").strip().lower()
    if not host:
        return False

    if host in {"localhost", "host.docker.internal"} or host.endswith(".local"):
        return True

    try:
        parsed_ip = ipaddress.ip_address(host)
    except ValueError:
        return False

    return any(
        (
            parsed_ip.is_private,
            parsed_ip.is_loopback,
            parsed_ip.is_link_local,
            parsed_ip.is_reserved,
        )
    )


def should_bypass_proxy_for_url(url: str | None) -> bool:
    parsed = urlparse(str(url or "").strip())
    return _should_bypass_proxy_for_host(parsed.hostname)


def _build_httpx_mounts(*, async_mode: bool) -> Optional[Dict[str, Any]]:
    httpx_module = _get_httpx()
    transport_cls = httpx_module.AsyncHTTPTransport if async_mode else httpx_module.HTTPTransport

    http_proxy = _pick_proxy_for_scheme(
        scheme="http",
        http_proxy=settings.HTTP_PROXY,
        https_proxy=settings.HTTPS_PROXY,
        all_proxy=settings.ALL_PROXY,
        socks_proxy=settings.SOCKS_PROXY,
    )
    https_proxy = _pick_proxy_for_scheme(
        scheme="https",
        http_proxy=settings.HTTP_PROXY,
        https_proxy=settings.HTTPS_PROXY,
        all_proxy=settings.ALL_PROXY,
        socks_proxy=settings.SOCKS_PROXY,
    )

    mounts: Dict[str, Any] = {}
    if http_proxy:
        mounts["http://"] = transport_cls(proxy=http_proxy)
    if https_proxy:
        mounts["https://"] = transport_cls(proxy=https_proxy)
    return mounts or None


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
    return _build_httpx_mounts(async_mode=True)


def get_httpx_client_kwargs() -> Dict[str, Any]:
    """
    获取创建 httpx.AsyncClient 时的关键字参数（包含代理配置）

    Returns:
        可用于 httpx.AsyncClient(**kwargs) 的字典
    """
    kwargs: Dict[str, Any] = {"trust_env": False}
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
    normalized = normalize_proxy_url(proxy_url) or str(proxy_url or "")
    parsed = urlparse(normalized)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "username": parsed.username,
        "password": parsed.password,
        "url": normalized,
    }


def should_use_proxy_for_url(url: str) -> bool:
    """
    检查是否应该对给定 URL 使用代理

    Args:
        url: 目标 URL

    Returns:
        是否应该使用代理
    """
    if should_bypass_proxy_for_url(url):
        return False

    parsed = urlparse(str(url or ""))
    scheme = parsed.scheme.lower()

    if scheme == "http" and _pick_proxy_for_scheme(
        scheme="http",
        http_proxy=settings.HTTP_PROXY,
        https_proxy=settings.HTTPS_PROXY,
        all_proxy=settings.ALL_PROXY,
        socks_proxy=settings.SOCKS_PROXY,
    ):
        return True
    if scheme == "https" and _pick_proxy_for_scheme(
        scheme="https",
        http_proxy=settings.HTTP_PROXY,
        https_proxy=settings.HTTPS_PROXY,
        all_proxy=settings.ALL_PROXY,
        socks_proxy=settings.SOCKS_PROXY,
    ):
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


def create_direct_httpx_client(**kwargs) -> "httpx.AsyncClient":
    """创建不走系统环境代理的 httpx 客户端，适用于 Emby/飞牛等内网服务。"""
    httpx_module = _get_httpx()
    client_kwargs = dict(kwargs)
    client_kwargs.setdefault("trust_env", False)
    return httpx_module.AsyncClient(**client_kwargs)


def create_direct_sync_httpx_client(**kwargs) -> "httpx.Client":
    """创建不走系统环境代理的同步 httpx 客户端。"""
    httpx_module = _get_httpx()
    client_kwargs = dict(kwargs)
    client_kwargs.setdefault("trust_env", False)
    return httpx_module.Client(**client_kwargs)


class ProxyManager:
    """代理管理器，用于统一管理代理配置"""

    def __init__(self):
        self._http_proxy: Optional[str] = None
        self._https_proxy: Optional[str] = None
        self._all_proxy: Optional[str] = None
        self._socks_proxy: Optional[str] = None
        self._proxy_reachability_cache: dict[str, tuple[float, bool]] = {}
        self._proxy_unreachable_logged = False
        self._change_listeners: list[Callable[[], None]] = []
        self._reload()

    def _reload(self) -> None:
        """从设置重新加载代理配置"""
        self._http_proxy = normalize_proxy_url(settings.HTTP_PROXY)
        self._https_proxy = normalize_proxy_url(settings.HTTPS_PROXY)
        self._all_proxy = normalize_proxy_url(settings.ALL_PROXY)
        self._socks_proxy = normalize_proxy_url(settings.SOCKS_PROXY)

    def add_change_listener(self, callback: Callable[[], None]) -> None:
        """注册代理变更回调（用于刷新长连接客户端）。"""
        if callback not in self._change_listeners:
            self._change_listeners.append(callback)

    def _notify_change_listeners(self) -> None:
        for callback in list(self._change_listeners):
            try:
                callback()
            except Exception:
                logger.exception("代理变更回调执行失败")

    def update_proxy(
        self,
        http_proxy: Optional[str] = None,
        https_proxy: Optional[str] = None,
        all_proxy: Optional[str] = None,
        socks_proxy: Optional[str] = None,
        proxy_url: Optional[str] = None,
    ) -> None:
        """
        更新代理配置

        Args:
            http_proxy: HTTP 代理 URL
            https_proxy: HTTPS 代理 URL
            all_proxy: 通用代理 URL
            socks_proxy: SOCKS 代理 URL
            proxy_url: 精简模式单一代理 URL（写入 all_proxy 并清空其余字段）
        """
        if proxy_url is not None:
            normalized = normalize_proxy_url(proxy_url) or None
            self._all_proxy = normalized
            self._http_proxy = None
            self._https_proxy = None
            self._socks_proxy = None
            settings.ALL_PROXY = normalized
            settings.HTTP_PROXY = None
            settings.HTTPS_PROXY = None
            settings.SOCKS_PROXY = None
        else:
            if http_proxy is not None:
                self._http_proxy = normalize_proxy_url(http_proxy)
                settings.HTTP_PROXY = self._http_proxy
            if https_proxy is not None:
                self._https_proxy = normalize_proxy_url(https_proxy)
                settings.HTTPS_PROXY = self._https_proxy
            if all_proxy is not None:
                self._all_proxy = normalize_proxy_url(all_proxy)
                settings.ALL_PROXY = self._all_proxy
            if socks_proxy is not None:
                self._socks_proxy = normalize_proxy_url(socks_proxy)
                settings.SOCKS_PROXY = self._socks_proxy

        self._proxy_reachability_cache.clear()
        self._proxy_unreachable_logged = False
        self._notify_change_listeners()

    def _collect_proxy_urls(self) -> list[str]:
        urls: list[str] = []
        for value in (
            self._all_proxy,
            self._https_proxy,
            self._http_proxy,
            self._socks_proxy,
        ):
            cleaned = normalize_proxy_url(value)
            if cleaned and cleaned not in urls:
                urls.append(cleaned)
        return urls

    def get_effective_proxy_url(self) -> Optional[str]:
        """返回当前配置的单一生效代理地址。"""
        return pick_effective_proxy_url(
            http_proxy=self._http_proxy,
            https_proxy=self._https_proxy,
            all_proxy=self._all_proxy,
            socks_proxy=self._socks_proxy,
        )

    def _parse_proxy_endpoint(self, proxy_url: str) -> Optional[tuple[str, int]]:
        normalized = normalize_proxy_url(proxy_url) or str(proxy_url or "").strip()
        parsed = urlparse(normalized)
        host = parsed.hostname
        if not host:
            return None
        if parsed.port:
            port = parsed.port
        elif parsed.scheme in {"https", "socks5", "socks5h"}:
            port = 443
        else:
            port = 80
        return host, port

    def _is_proxy_endpoint_reachable(self, proxy_url: str) -> bool:
        now = time.time()
        cached = self._proxy_reachability_cache.get(proxy_url)
        if cached and now < cached[0]:
            return cached[1]

        endpoint = self._parse_proxy_endpoint(proxy_url)
        if endpoint is None:
            reachable = False
        else:
            host, port = endpoint
            reachable = self._tcp_reachable(host, port)
            # Docker 内若仍是环回地址且不可达，再尝试 host.docker.internal
            if (
                not reachable
                and is_running_in_docker()
                and host.lower() in _LOOPBACK_HOSTS
            ):
                reachable = self._tcp_reachable(_DOCKER_HOST_ALIAS, port)

        self._proxy_reachability_cache[proxy_url] = (
            now + PROXY_REACHABILITY_TTL_SECONDS,
            reachable,
        )
        return reachable

    @staticmethod
    def _tcp_reachable(host: str, port: int) -> bool:
        try:
            infos = socket.getaddrinfo(
                host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
            )
        except OSError:
            return False

        for family, socktype, proto, _canonname, sockaddr in infos:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(PROXY_REACHABILITY_TIMEOUT_SECONDS)
            try:
                sock.connect(sockaddr)
                return True
            except OSError:
                continue
            finally:
                sock.close()
        return False

    def check_proxy_reachability(self, proxy_url: str | None = None) -> dict[str, Any]:
        """检测代理端口是否可达（供健康检查 API 使用）。"""
        target = normalize_proxy_url(proxy_url) or self.get_effective_proxy_url()
        if not target:
            return {
                "configured": False,
                "reachable": False,
                "proxy_url": "",
                "message": "未配置代理",
            }

        # 强制刷新，避免检测时吃到旧缓存
        self._proxy_reachability_cache.pop(target, None)
        reachable = self._is_proxy_endpoint_reachable(target)
        endpoint = self._parse_proxy_endpoint(target)
        host_port = f"{endpoint[0]}:{endpoint[1]}" if endpoint else target
        return {
            "configured": True,
            "reachable": reachable,
            "proxy_url": target,
            "endpoint": host_port,
            "in_docker": is_running_in_docker(),
            "message": (
                f"代理可达 ({host_port})"
                if reachable
                else (
                    f"代理不可达 ({host_port})。"
                    + (
                        " Docker 内请使用 host.docker.internal 而非 127.0.0.1"
                        if is_running_in_docker()
                        else " 请确认代理软件已开启并允许局域网连接"
                    )
                )
            ),
        }

    def _should_apply_proxy_mounts(self) -> bool:
        proxy_urls = self._collect_proxy_urls()
        if not proxy_urls:
            return False
        return any(self._is_proxy_endpoint_reachable(url) for url in proxy_urls)

    def get_proxy_for_scheme(self, scheme: str) -> Optional[str]:
        """
        获取指定协议的代理

        Args:
            scheme: 协议类型 (http, https, socks5)

        Returns:
            代理 URL 或 None
        """
        return _pick_proxy_for_scheme(
            scheme=scheme,
            http_proxy=self._http_proxy,
            https_proxy=self._https_proxy,
            all_proxy=self._all_proxy,
            socks_proxy=self._socks_proxy,
        )

    def get_effective_https_proxy(self) -> Optional[str]:
        """返回当前可用且可达的 HTTPS 代理 URL，供 Telegram 等外网 API 使用。"""
        if not self._should_apply_proxy_mounts():
            return None
        return self.get_proxy_for_scheme("https")

    def _build_mounts(
        self, *, async_mode: bool, force: bool = False
    ) -> Optional[Dict[str, Any]]:
        httpx_module = _get_httpx()
        transport_cls = (
            httpx_module.AsyncHTTPTransport if async_mode else httpx_module.HTTPTransport
        )

        if not force and not self._should_apply_proxy_mounts():
            return None

        http_proxy = self.get_proxy_for_scheme("http")
        https_proxy = self.get_proxy_for_scheme("https")
        mounts: Dict[str, Any] = {}
        if http_proxy:
            mounts["http://"] = transport_cls(proxy=http_proxy)
        if https_proxy:
            mounts["https://"] = transport_cls(proxy=https_proxy)
        return mounts or None

    def create_httpx_client(
        self, *, require_proxy: bool = False, **kwargs
    ) -> "httpx.AsyncClient":
        """
        创建配置了代理的 httpx.AsyncClient

        Args:
            require_proxy: 为 True 时强制挂载已配置代理（检测场景）；不可达时不静默直连
            **kwargs: 传递给 httpx.AsyncClient 的其他参数

        Returns:
            配置了代理的 AsyncClient 实例
        """
        httpx_module = _get_httpx()

        client_kwargs = dict(kwargs)
        # 禁用系统环境代理，避免 Docker 注入的 HTTP_PROXY 在不可达时拖垮所有外网请求
        client_kwargs.setdefault("trust_env", False)
        base_url = client_kwargs.get("base_url")

        if should_bypass_proxy_for_url(base_url):
            return httpx_module.AsyncClient(**client_kwargs)

        mounts = self._build_mounts(async_mode=True, force=require_proxy)
        if mounts is None:
            if self._collect_proxy_urls() and not self._proxy_unreachable_logged:
                logger.warning(
                    "已配置代理但当前不可达，HTTP 客户端将自动改用直连；"
                    "请检查设置中的代理地址/端口，或确保代理监听 host.docker.internal"
                )
                self._proxy_unreachable_logged = True
            if require_proxy and self._collect_proxy_urls():
                raise RuntimeError(
                    "已配置代理但当前不可达，无法强制走代理。"
                    " Docker 部署请使用 host.docker.internal 而非 127.0.0.1"
                )
            return httpx_module.AsyncClient(**client_kwargs)

        client_kwargs["mounts"] = mounts
        return httpx_module.AsyncClient(**client_kwargs)

    def create_sync_httpx_client(
        self, *, require_proxy: bool = False, **kwargs
    ) -> "httpx.Client":
        """
        创建配置了代理的 httpx.Client (同步客户端)

        Args:
            require_proxy: 为 True 时强制挂载已配置代理
            **kwargs: 传递给 httpx.Client 的其他参数

        Returns:
            配置了代理的 Client 实例
        """
        httpx_module = _get_httpx()

        client_kwargs = dict(kwargs)
        client_kwargs.setdefault("trust_env", False)
        base_url = client_kwargs.get("base_url")

        if should_bypass_proxy_for_url(base_url):
            return httpx_module.Client(**client_kwargs)

        mounts = self._build_mounts(async_mode=False, force=require_proxy)
        if mounts is None:
            if self._collect_proxy_urls() and not self._proxy_unreachable_logged:
                logger.warning(
                    "已配置代理但当前不可达，HTTP 客户端将自动改用直连；"
                    "请检查设置中的代理地址/端口，或确保代理监听 host.docker.internal"
                )
                self._proxy_unreachable_logged = True
            if require_proxy and self._collect_proxy_urls():
                raise RuntimeError(
                    "已配置代理但当前不可达，无法强制走代理。"
                    " Docker 部署请使用 host.docker.internal 而非 127.0.0.1"
                )
            return httpx_module.Client(**client_kwargs)

        client_kwargs["mounts"] = mounts
        return httpx_module.Client(**client_kwargs)

    def get_current_config(self) -> Dict[str, Optional[str]]:
        """获取当前代理配置"""
        return {
            "http_proxy": self._http_proxy,
            "https_proxy": self._https_proxy,
            "all_proxy": self._all_proxy,
            "socks_proxy": self._socks_proxy,
            "proxy_url": self.get_effective_proxy_url(),
        }


# 全局代理管理器实例
proxy_manager = ProxyManager()
