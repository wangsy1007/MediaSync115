from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.services.auth_service import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS, auth_service
from app.services.operation_log_service import operation_log_service
from app.services.runtime_settings_service import runtime_settings_service

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangeCredentialsRequest(BaseModel):
    current_password: str
    username: str | None = None
    new_password: str | None = None


@router.get("/session")
async def get_auth_session(request: Request):
    session = auth_service.get_request_session(request)
    if not session:
        return {"authenticated": False, "username": ""}
    return {
        "authenticated": True,
        "username": session["username"],
        "expires_at": session["expires_at"],
    }


@router.post("/login")
async def login(payload: LoginRequest, response: Response):
    username = str(payload.username or "").strip()
    password = str(payload.password or "")
    if username != runtime_settings_service.get_auth_username() or not auth_service.verify_password(
        password,
        runtime_settings_service.get_auth_password_hash(),
    ):
        await operation_log_service.log_background_event(
            source_type="api", module="auth",
            action="auth.login.failed", status="warning",
            message=f"登录失败：账号或密码错误（用户名：{username}）",
        )
        raise HTTPException(status_code=401, detail="账号或密码错误")

    token = auth_service.build_session_token(username)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    await operation_log_service.log_background_event(
        source_type="api", module="auth",
        action="auth.login.success", status="success",
        message=f"用户登录成功（用户名：{username}）",
    )
    return {"success": True, "username": username}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"success": True}


@router.post("/change-credentials")
async def change_credentials(payload: ChangeCredentialsRequest, request: Request, response: Response):
    session = auth_service.get_request_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="请先登录")

    current_password = str(payload.current_password or "")
    if not auth_service.verify_password(current_password, runtime_settings_service.get_auth_password_hash()):
        raise HTTPException(status_code=400, detail="当前密码错误")

    next_username = str(payload.username or runtime_settings_service.get_auth_username()).strip()
    next_password = str(payload.new_password or "")
    if not next_username:
        raise HTTPException(status_code=400, detail="账号不能为空")
    if payload.new_password is not None and len(next_password) < 6:
        raise HTTPException(status_code=400, detail="新密码长度不能少于 6 位")

    runtime_settings_service.update_auth_credentials(
        username=next_username,
        new_password=next_password if payload.new_password is not None else None,
    )
    changes = []
    if next_username != runtime_settings_service.get_auth_username():
        changes.append("用户名")
    if payload.new_password is not None:
        changes.append("密码")
    await operation_log_service.log_background_event(
        source_type="api", module="auth",
        action="auth.credentials.changed", status="success",
        message=f"账号凭证已修改（{'、'.join(changes) if changes else '无变更'}）",
    )

    token = auth_service.build_session_token(next_username)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return {"success": True, "username": next_username}
