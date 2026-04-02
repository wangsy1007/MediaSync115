#!/usr/bin/env python3
"""
验证飞牛登录返回的 secret 是否能用于飞牛影视 API

根据论坛抓包信息:
1. WebSocket 连接到 ws://{ip}:5666/websocket?type=main
2. 获取 RSA 公钥: util.crypto.getRSAPub
3. 加密登录: user.login (AES+RSA 加密)
4. 登录响应返回 secret
5. 验证该 secret 是否能用于 /mdb/count 等 API
"""

import asyncio
import base64
import hashlib
import json
import re
import time
import uuid
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from typing import Optional
import websockets


class FeiniuLoginTester:
    def __init__(self, host: str, port: int = 5666):
        self.host = host
        self.port = port
        self.ws_url = f"ws://{host}:{port}/websocket?type=main"
        self.public_key: Optional[str] = None
        self.si: Optional[str] = None
        self.backId: Optional[str] = None
        self.token: Optional[str] = None
        self.login_secret: Optional[str] = None
        self.uid: Optional[int] = None
        self.session_cookies: dict = {}

    def _get_reqid(self) -> str:
        """生成请求ID"""
        t = format(int(time.time()), "x").zfill(8)
        e = format(1, "x").zfill(4)
        backId = self.backId or "0000000000000000"
        return f"{t}{backId}{e}"

    async def connect_and_get_rsa(self) -> bool:
        """连接WebSocket并获取RSA公钥"""
        print(f"[1] 连接到 {self.ws_url}")
        try:
            async with websockets.connect(self.ws_url, max_size=10 * 1024 * 1024) as ws:
                # 获取RSA公钥
                reqid = self._get_reqid()
                get_rsa_msg = {"reqid": reqid, "req": "util.crypto.getRSAPub"}
                print(f"[2] 获取RSA公钥: {json.dumps(get_rsa_msg)}")
                await ws.send(json.dumps(get_rsa_msg))

                response = await ws.recv()
                resp_data = json.loads(response)
                print(f"[2] RSA响应: {json.dumps(resp_data, ensure_ascii=False)}")

                if resp_data.get("result") == "succ":
                    self.public_key = resp_data.get("pub")
                    self.si = resp_data.get("si")
                    print(f"[2] RSA公钥获取成功, si={self.si}")
                    return True
                return False
        except Exception as e:
            print(f"[!] WebSocket连接失败: {e}")
            return False

    @staticmethod
    def generate_aes_key_iv():
        """生成随机的AES key和iv"""
        key = uuid.uuid4().hex[:16].encode()  # 16 bytes for AES-128
        iv = uuid.uuid4().hex[:16].encode()  # 16 bytes for AES-CBC
        return key, iv

    def aes_encrypt(self, data: str, key: bytes, iv: bytes) -> str:
        """AES加密"""
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_data = data.encode("utf-8") + b"\0" * (
            AES.block_size - len(data.encode("utf-8")) % AES.block_size
        )
        ciphertext = cipher.encrypt(padded_data)
        return base64.b64encode(ciphertext).decode("utf-8")

    def rsa_encrypt(self, public_key_str: str, plaintext: bytes) -> str:
        """RSA加密"""
        key = RSA.import_key(public_key_str)
        cipher = PKCS1_v1_5.new(key)
        ciphertext = cipher.encrypt(plaintext)
        return base64.b64encode(ciphertext).decode()

    def encrypt_login_data(self, login_data: dict) -> dict:
        """加密登录数据"""
        key, iv = self.generate_aes_key_iv()

        # AES加密原始数据
        json_data = json.dumps(login_data, separators=(",", ":"))
        aes_encrypted = self.aes_encrypt(json_data, key, iv)

        # RSA加密AES key
        rsa_encrypted = self.rsa_encrypt(self.public_key, key)

        return {
            "req": "encrypted",
            "iv": base64.b64encode(iv).decode("utf-8"),
            "rsa": rsa_encrypted,
            "aes": aes_encrypted,
        }

    async def login(self, username: str, password: str, stay: bool = True) -> bool:
        """执行登录"""
        if not self.public_key:
            print("[!] 未获取RSA公钥，无法登录")
            return False

        # 构建登录数据
        login_data = {
            "req": "user.login",
            "reqid": self._get_reqid(),
            "user": username,
            "password": password,
            "deviceType": "Browser",
            "deviceName": "Windows-Google Chrome",
            "stay": stay,
            "si": self.si,
        }

        # 加密
        encrypted_data = self.encrypt_login_data(login_data)
        encrypted_data["reqid"] = self._get_reqid()

        print(f"[3] 发送加密登录请求")
        print(f"[3] 原始登录数据: {json.dumps(login_data, ensure_ascii=False)}")

        try:
            async with websockets.connect(self.ws_url, max_size=10 * 1024 * 1024) as ws:
                await ws.send(json.dumps(encrypted_data))
                response = await ws.recv()
                resp_data = json.loads(response)
                print(f"[3] 登录响应: {json.dumps(resp_data, ensure_ascii=False)}")

                if resp_data.get("result") == "succ":
                    self.token = resp_data.get("token")
                    self.login_secret = resp_data.get("secret")
                    self.uid = resp_data.get("uid")
                    self.backId = resp_data.get("backId")
                    print(f"[3] 登录成功!")
                    print(f"    uid: {self.uid}")
                    print(f"    token: {self.token}")
                    print(f"    secret: {self.login_secret}")
                    print(f"    backId: {self.backId}")
                    return True
                else:
                    print(f"[3] 登录失败: errno={resp_data.get('errno')}")
                    return False
        except Exception as e:
            print(f"[!] 登录请求失败: {e}")
            return False

    async def test_api_with_login_secret(self, api_key: str) -> dict:
        """使用登录返回的secret测试飞牛影视API"""
        if not self.login_secret:
            return {"success": False, "message": "未登录，无secret"}

        print(f"\n[4] 使用登录secret测试飞牛影视API")
        print(f"    API Key: {api_key}")
        print(f"    Login Secret: {self.login_secret}")

        # 计算authx
        timestamp = str(int(time.time()))
        raw = f"{self.login_secret}{timestamp}{api_key}"
        authx = hashlib.md5(raw.encode("utf-8")).hexdigest()

        headers = {
            "authx": authx,
            "authn": timestamp,
        }

        import httpx

        url = f"http://{self.host}:{self.port}/mdb/count"
        print(f"    请求URL: {url}")
        print(f"    authx: {authx}")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)
                print(f"    响应状态: {response.status_code}")
                print(
                    f"    响应内容: {response.text[:500] if response.text else 'empty'}"
                )

                if response.status_code == 200:
                    return {
                        "success": True,
                        "message": "API调用成功",
                        "data": response.json(),
                    }
                else:
                    return {
                        "success": False,
                        "message": f"API调用失败: HTTP {response.status_code}",
                        "data": response.text,
                    }
        except Exception as e:
            return {"success": False, "message": f"API调用异常: {e}"}

    async def fetch_js_to_extract_secret(self) -> Optional[dict]:
        """登录后从飞牛影视页面提取secret和api_key"""
        if not self.token:
            return None

        print(f"\n[5] 登录后获取飞牛影视页面，提取secret和api_key")

        import httpx

        # 首先获取媒体库页面
        url = f"http://{self.host}:{self.port}/media"

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                # 使用token作为Cookie
                response = await client.get(url, timeout=10.0)
                print(f"    页面响应状态: {response.status_code}")

                if response.status_code == 200:
                    content = response.text
                    print(f"    页面内容长度: {len(content)} bytes")

                    # 查找JS文件
                    js_files = re.findall(
                        r'src=["\']([^"\']+\.js[^"\']*)["\']', content
                    )
                    print(f"    找到JS文件: {js_files[:5]}")

                    # 查找secret和api_key
                    # Secret: 搜索 ",s,l,c,o,e].join("_")
                    # API Key: 搜索 `${Ld}/sys/progressThumb`

                    for js_url in js_files[:10]:  # 只检查前10个
                        if not js_url.startswith("http"):
                            js_url = f"http://{self.host}:{self.port}{js_url}"

                        try:
                            js_response = await client.get(js_url, timeout=10.0)
                            if js_response.status_code == 200:
                                js_content = js_response.text

                                # 搜索secret模式
                                secret_match = re.search(
                                    r'["\']([a-f0-9]{32})["\']', js_content
                                )
                                if secret_match:
                                    potential_secret = secret_match.group(1)
                                    print(f"    找到可能的secret: {potential_secret}")

                                # 搜索api_key模式
                                api_key_match = re.search(
                                    r'["\']([^"\']{20,})["\']', js_content
                                )
                                if api_key_match:
                                    potential_key = api_key_match.group(1)
                                    if len(potential_key) > 20:
                                        print(f"    找到可能的api_key: {potential_key}")

                        except:
                            pass

                return None
        except Exception as e:
            print(f"    获取页面失败: {e}")
            return None


async def main():
    import sys

    if len(sys.argv) < 4:
        print("用法: python test_feiniu_login.py <飞牛IP> <用户名> <密码> [API密钥]")
        print("示例: python test_feiniu_login.py 192.168.1.100 admin password123")
        sys.exit(1)

    host = sys.argv[1]
    username = sys.argv[2]
    password = sys.argv[3]
    api_key = sys.argv[4] if len(sys.argv) > 4 else ""

    tester = FeiniuLoginTester(host)

    # 1. 连接并获取RSA公钥
    if not await tester.connect_and_get_rsa():
        print("[!] 获取RSA公钥失败，退出")
        sys.exit(1)

    # 2. 登录
    if not await tester.login(username, password):
        print("[!] 登录失败，退出")
        sys.exit(1)

    # 3. 如果提供了API Key，测试登录secret是否能用于API
    if api_key:
        result = await tester.test_api_with_login_secret(api_key)
        print(f"\n[结果] API测试: {result}")

        if result["success"]:
            print("\n✅ 登录返回的secret可以用于飞牛影视API!")
        else:
            print(
                "\n❌ 登录返回的secret不能用于飞牛影视API，需要手动提取secret和api_key"
            )

    # 4. 尝试从页面提取
    await tester.fetch_js_to_extract_secret()


if __name__ == "__main__":
    asyncio.run(main())
