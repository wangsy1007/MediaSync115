"""
飞牛影视服务 - 支持浏览器自动化登录和 API Key 认证
"""

import asyncio
import base64
import hashlib
import json
import logging
import random
import time
import uuid
from typing import Any, Optional

import httpx
import websockets
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from playwright.async_api import async_playwright

from app.core.config import settings

logger = logging.getLogger(__name__)


class FeiniuService:
    """飞牛影视服务"""

    API_KEY = "NDzZTVxnRKP8Z0jXg1VAMonaG8akvh"
    API_SECRET = "16CCEB3D-AB42-077D-36A1-F355324E4237"

    def __init__(self):
        self.base_url = settings.FEINIU_URL.rstrip("/") if settings.FEINIU_URL else ""
        self.secret = settings.FEINIU_SECRET
        self.api_key = settings.FEINIU_API_KEY
        self.session_token: Optional[str] = None

    def set_config(self, base_url: str, secret: str, api_key: str) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.secret = str(secret or "").strip()
        self.api_key = str(api_key or "").strip() or self.API_KEY
        self.session_token = None

    def set_session_token(self, token: str) -> None:
        self.session_token = token

    def _generate_nonce(self) -> str:
        return str(random.randint(100000, 999999))

    def _md5(self, data: str) -> str:
        if isinstance(data, str):
            data = data.encode("utf-8")
        elif not isinstance(data, bytes):
            data = str(data).encode("utf-8")
        return hashlib.md5(data).hexdigest()

    def _compute_authx(self, url: str, data: Optional[dict] = None) -> str:
        nonce = self._generate_nonce()
        timestamp = int(time.time() * 1000)
        data_json = json.dumps(data, separators=(",", ":")) if data else ""
        data_md5 = self._md5(data_json)
        sign_array = [
            self.API_KEY,
            url,
            nonce,
            str(timestamp),
            data_md5,
            self.API_SECRET,
        ]
        sign_str = "_".join(sign_array)
        sign_hash = self._md5(sign_str)
        return f"nonce={nonce}&timestamp={timestamp}&sign={sign_hash}"

    def _auth_headers(self, use_session: bool = False) -> dict[str, str]:
        timestamp = str(int(time.time()))
        raw = f"{self.secret}{timestamp}{self.api_key}"
        authx = self._md5(raw)
        headers = {
            "authx": authx,
            "authn": timestamp,
        }
        if use_session and self.session_token:
            headers["Authorization"] = self.session_token
            headers["Cookie"] = f"mode=relay; Trim-MC-token={self.session_token}"
        return headers

    async def browser_login(self, username: str, password: str) -> dict[str, Any]:
        """
        使用浏览器自动化登录飞牛影视

        Args:
            username: 用户名
            password: 密码

        Returns:
            包含 success, token, message 等字段的字典
        """
        if not self.base_url:
            return {
                "success": False,
                "message": "飞牛影视 URL 未配置",
                "token": None,
            }

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()

                login_url = (
                    f"{self.base_url}/v/login?redirect_uri=http%3A%2F%2F"
                    f"{self.base_url.split('://')[1]}%2Fv"
                )
                await page.goto(login_url, wait_until="networkidle", timeout=60000)

                await page.fill("#username", username)
                await page.fill("#password", password)
                await page.click("button[type='submit']")

                try:
                    await page.wait_for_url(f"{self.base_url}/v", timeout=60000)
                except Exception:
                    pass

                cookies = await context.cookies()
                await browser.close()

                for cookie in cookies:
                    if cookie["name"] == "Trim-MC-token":
                        token = cookie["value"]
                        self.session_token = token
                        logger.info(f"浏览器登录成功，获取 Token: {token[:20]}...")
                        return {
                            "success": True,
                            "message": "登录成功",
                            "token": token,
                        }

                return {
                    "success": False,
                    "message": "未找到登录凭证",
                    "token": None,
                }

        except Exception as exc:
            logger.exception("浏览器登录失败")
            return {
                "success": False,
                "message": f"登录异常: {str(exc)}",
                "token": None,
            }

    def _generate_reqid(self, backId: Optional[str] = None) -> str:
        """生成请求ID"""
        t = format(int(time.time()), "x").zfill(8)
        e = format(1, "x").zfill(4)
        bid = backId or "0000000000000000"
        return f"{t}{bid}{e}"

    def _generate_aes_key_iv(self) -> tuple[bytes, bytes]:
        """生成随机的AES key和iv"""
        key = uuid.uuid4().hex[:16].encode()
        iv = uuid.uuid4().hex[:16].encode()
        return key, iv

    def _aes_encrypt(self, data: str, key: bytes, iv: bytes) -> str:
        """AES加密"""
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_data = data.encode("utf-8") + b"\0" * (
            AES.block_size - len(data.encode("utf-8")) % AES.block_size
        )
        ciphertext = cipher.encrypt(padded_data)
        return base64.b64encode(ciphertext).decode("utf-8")

    def _rsa_encrypt(self, public_key_str: str, plaintext: bytes) -> str:
        """RSA加密"""
        key = RSA.import_key(public_key_str)
        cipher = PKCS1_v1_5.new(key)
        ciphertext = cipher.encrypt(plaintext)
        return base64.b64encode(ciphertext).decode()

    async def websocket_login(self, username: str, password: str) -> dict[str, Any]:
        """
        使用 WebSocket 登录飞牛影视（推荐方式）

        通过 WebSocket 连接获取登录凭证，返回的 secret 可直接用于 API 认证。

        Args:
            username: 用户名
            password: 密码

        Returns:
            包含 success, token, secret, message 等字段的字典
        """
        if not self.base_url:
            return {
                "success": False,
                "message": "飞牛影视 URL 未配置",
                "token": None,
                "secret": None,
            }

        try:
            host = (
                self.base_url.split("://")[1]
                if "://" in self.base_url
                else self.base_url
            )
            port = 5666
            if ":" in host:
                host, port_str = host.rsplit(":", 1)
                try:
                    port = int(port_str)
                except ValueError:
                    port = 5666

            ws_url = f"ws://{host}:{port}/websocket?type=main"
            logger.info(f"[Feiniu WS] 连接到 {ws_url}")

            async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
                reqid = self._generate_reqid()

                get_rsa_msg = {"reqid": reqid, "req": "util.crypto.getRSAPub"}
                await ws.send(json.dumps(get_rsa_msg))
                response = await ws.recv()
                resp_data = json.loads(response)

                if resp_data.get("result") != "succ":
                    return {
                        "success": False,
                        "message": f"获取RSA公钥失败: {resp_data}",
                        "token": None,
                        "secret": None,
                    }

                public_key = resp_data.get("pub")
                si = resp_data.get("si")
                backId = resp_data.get("backId", "0000000000000000")
                logger.info(f"[Feiniu WS] RSA公钥获取成功, si={si}")

                login_data = {
                    "req": "user.login",
                    "reqid": self._generate_reqid(backId),
                    "user": username,
                    "password": password,
                    "deviceType": "Browser",
                    "deviceName": "Windows-Google Chrome",
                    "stay": True,
                    "si": si,
                }

                key, iv = self._generate_aes_key_iv()
                json_data = json.dumps(login_data, separators=(",", ":"))
                aes_encrypted = self._aes_encrypt(json_data, key, iv)
                rsa_encrypted = self._rsa_encrypt(public_key, key)

                encrypted_data = {
                    "req": "encrypted",
                    "iv": base64.b64encode(iv).decode("utf-8"),
                    "rsa": rsa_encrypted,
                    "aes": aes_encrypted,
                    "reqid": self._generate_reqid(backId),
                }

                await ws.send(json.dumps(encrypted_data))
                response = await ws.recv()
                resp_data = json.loads(response)

                if resp_data.get("result") != "succ":
                    return {
                        "success": False,
                        "message": f"登录失败: errno={resp_data.get('errno')}",
                        "token": None,
                        "secret": None,
                    }

                token = resp_data.get("token")
                secret = resp_data.get("secret")
                uid = resp_data.get("uid")
                logger.info(
                    f"[Feiniu WS] 登录成功! uid={uid}, token={token[:20] if token else None}..."
                )

                self.session_token = token
                if secret:
                    self.secret = secret

                return {
                    "success": True,
                    "message": "登录成功",
                    "token": token,
                    "secret": secret,
                    "uid": uid,
                }

        except Exception as exc:
            logger.exception("[Feiniu WS] WebSocket登录失败")
            return {
                "success": False,
                "message": f"WebSocket登录异常: {str(exc)}",
                "token": None,
                "secret": None,
            }

    async def check_connection(self) -> dict[str, Any]:
        """检查连接状态（使用 API Key 认证）"""
        if not self.base_url:
            return {
                "valid": False,
                "message": "飞牛影视 URL 未配置",
                "user": None,
            }

        api_key = self.api_key or self.API_KEY
        secret = self.secret

        if not secret:
            return {
                "valid": False,
                "message": "请先登录飞牛影视获取凭证",
                "user": None,
            }

        url = f"{self.base_url}/mdb/count"
        headers = self._auth_headers()
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, timeout=10.0)
                if response.status_code == 200:
                    return {
                        "valid": True,
                        "message": "飞牛影视连接成功",
                        "user": {"server": "feiniu"},
                    }
                return {
                    "valid": False,
                    "message": f"连接失败 (HTTP {response.status_code})",
                    "user": None,
                }
            except Exception as exc:
                return {
                    "valid": False,
                    "message": str(exc),
                    "user": None,
                }

    async def check_connection_with_session(self) -> dict[str, Any]:
        """使用 session token 检查连接状态"""
        if not self.session_token:
            return {
                "valid": False,
                "message": "未登录，无 session token",
                "user": None,
            }

        url = f"{self.base_url}/v/api/v1/user/info"
        headers = {
            "Authx": self._compute_authx("/v/api/v1/user/info"),
            "Authorization": self.session_token,
            "Cookie": f"mode=relay; Trim-MC-token={self.session_token}",
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("code") == 0:
                        return {
                            "valid": True,
                            "message": "飞牛影视连接成功",
                            "user": data.get("data", {}),
                        }
                    return {
                        "valid": False,
                        "message": f"API错误: {data.get('msg', 'Unknown')}",
                        "user": None,
                    }
                return {
                    "valid": False,
                    "message": f"连接失败 (HTTP {response.status_code})",
                    "user": None,
                }
            except Exception as exc:
                return {
                    "valid": False,
                    "message": str(exc),
                    "user": None,
                }

    async def get_movie_status_by_tmdb(self, tmdb_id: int) -> dict[str, Any]:
        """使用 session token 检查电影是否存在（需要先登录）"""
        if not self.session_token:
            return {
                "status": "not_logged_in",
                "message": "未登录，无法查询媒体状态",
                "exists": False,
                "item_ids": [],
            }

        url = f"{self.base_url}/v/api/v1/mdb/search"
        headers = {
            "Authx": self._compute_authx(f"/v/api/v1/mdb/search"),
            "Authorization": self.session_token,
            "Cookie": f"mode=relay; Trim-MC-token={self.session_token}",
        }
        params = {"tmdb": str(tmdb_id), "type": "movie"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url, headers=headers, params=params, timeout=15.0
                )
                if response.status_code != 200:
                    return {
                        "status": "request_failed",
                        "message": f"请求失败 (HTTP {response.status_code})",
                        "exists": False,
                        "item_ids": [],
                    }
                payload = response.json()
                if payload.get("code") != 0:
                    return {
                        "status": "api_error",
                        "message": payload.get("msg", "Unknown error"),
                        "exists": False,
                        "item_ids": [],
                    }
                items = payload.get("data", {}).get("items") or []
                item_ids = [
                    str(item.get("id") or "") for item in items if item.get("id")
                ]
                return {
                    "status": "ok",
                    "message": "查询成功"
                    if item_ids
                    else "飞牛影视中未匹配到该 TMDB 电影",
                    "exists": bool(item_ids),
                    "item_ids": item_ids,
                }
            except Exception as exc:
                return {
                    "status": "request_failed",
                    "message": str(exc),
                    "exists": False,
                    "item_ids": [],
                }

    async def get_tv_episode_status_by_tmdb(self, tmdb_id: int) -> dict[str, Any]:
        """使用 session token 检查剧集是否存在"""
        if not self.session_token:
            return {
                "status": "not_logged_in",
                "message": "未登录，无法查询媒体状态",
                "existing_episodes": set(),
            }

        url = f"{self.base_url}/v/api/v1/mdb/search"
        headers = {
            "Authx": self._compute_authx(f"/v/api/v1/mdb/search"),
            "Authorization": self.session_token,
            "Cookie": f"mode=relay; Trim-MC-token={self.session_token}",
        }
        params = {"tmdb": str(tmdb_id), "type": "tv"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url, headers=headers, params=params, timeout=15.0
                )
                if response.status_code != 200:
                    return {
                        "status": "request_failed",
                        "message": f"请求失败 (HTTP {response.status_code})",
                        "existing_episodes": set(),
                    }
                payload = response.json()
                if payload.get("code") != 0:
                    return {
                        "status": "api_error",
                        "message": payload.get("msg", "Unknown error"),
                        "existing_episodes": set(),
                    }
                items = payload.get("data", {}).get("items") or []
                existing_episodes: set[tuple[int, int]] = set()
                for item in items:
                    season = int(item.get("season") or item.get("seasonNumber") or 1)
                    episode = int(item.get("episode") or item.get("episodeNumber") or 0)
                    if episode > 0:
                        existing_episodes.add((season, episode))
                return {
                    "status": "ok",
                    "message": "查询成功",
                    "existing_episodes": existing_episodes,
                }
            except Exception as exc:
                return {
                    "status": "request_failed",
                    "message": str(exc),
                    "existing_episodes": set(),
                }

    async def refresh_library(self, path: Optional[str] = None) -> dict[str, Any]:
        """触发媒体库扫描"""
        if not self.base_url or not self.secret or not self.api_key:
            return {
                "status": "not_configured",
                "message": "飞牛影视未配置",
            }

        url = f"{self.base_url}/mdb/scan"
        headers = self._auth_headers()
        payload: dict[str, Any] = {}
        if path:
            payload["path"] = path

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url, headers=headers, json=payload, timeout=30.0
                )
                if response.status_code == 200:
                    return {
                        "status": "ok",
                        "message": "扫描任务已触发",
                    }
                error_text = response.text
                if "-14" in error_text:
                    return {
                        "status": "duplicate",
                        "message": "扫描任务冲突，请稍后重试",
                    }
                return {
                    "status": "error",
                    "message": f"扫描失败 (HTTP {response.status_code}): {error_text}",
                }
            except Exception as exc:
                return {
                    "status": "request_failed",
                    "message": str(exc),
                }


feiniu_service = FeiniuService()
