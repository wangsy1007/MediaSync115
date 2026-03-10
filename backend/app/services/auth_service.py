import base64
import hashlib
import hmac
import secrets
import time
from typing import Any

from fastapi import Request

from app.services.runtime_settings_service import runtime_settings_service

SESSION_COOKIE_NAME = "mediasync_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
PBKDF2_ITERATIONS = 390000


class AuthService:
    def _get_signing_key(self) -> bytes:
        secret = runtime_settings_service.get_auth_secret().strip()
        material = f"{secret}:{runtime_settings_service.get_auth_password_hash()}".encode("utf-8")
        return hashlib.sha256(material).digest()

    def hash_password(self, password: str, salt: str | None = None) -> str:
        raw_password = str(password or "")
        if not raw_password:
            raise ValueError("密码不能为空")
        normalized_salt = salt or secrets.token_hex(16)
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            raw_password.encode("utf-8"),
            normalized_salt.encode("utf-8"),
            PBKDF2_ITERATIONS,
        )
        return f"{normalized_salt}${derived.hex()}"

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            salt, _ = str(password_hash or "").split("$", 1)
        except ValueError:
            return False
        expected = self.hash_password(password, salt=salt)
        return hmac.compare_digest(expected, str(password_hash or ""))

    def build_session_token(self, username: str) -> str:
        expires_at = int(time.time()) + SESSION_MAX_AGE_SECONDS
        payload = f"{username}|{expires_at}"
        signature = hmac.new(self._get_signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        token = f"{payload}|{signature}"
        return base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii")

    def verify_session_token(self, token: str) -> dict[str, Any] | None:
        raw_token = str(token or "").strip()
        if not raw_token:
            return None
        try:
            decoded = base64.urlsafe_b64decode(raw_token.encode("ascii")).decode("utf-8")
            username, expires_at_raw, signature = decoded.split("|", 2)
            payload = f"{username}|{expires_at_raw}"
        except Exception:
            return None

        expected_signature = hmac.new(
            self._get_signing_key(),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return None

        try:
            expires_at = int(expires_at_raw)
        except Exception:
            return None
        if expires_at <= int(time.time()):
            return None
        if username != runtime_settings_service.get_auth_username():
            return None
        return {
            "username": username,
            "expires_at": expires_at,
        }

    def get_request_session(self, request: Request) -> dict[str, Any] | None:
        token = request.cookies.get(SESSION_COOKIE_NAME) or ""
        return self.verify_session_token(token)


auth_service = AuthService()
