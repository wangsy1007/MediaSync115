"""认证接口 CORS / 局域网 Origin 登录预检测试。"""

from fastapi.testclient import TestClient


def test_login_preflight_allows_lan_origin(client: TestClient) -> None:
    """局域网 Origin 的 OPTIONS 预检应放行，避免 Edge 等新浏览器登录卡住。"""
    response = client.options(
        "/api/auth/login",
        headers={
            "Origin": "http://172.16.100.2:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-client-timezone",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://172.16.100.2:5173"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_login_with_lan_origin_sets_session_cookie(client: TestClient) -> None:
    """带局域网 Origin 的登录应成功并回写 Cookie / CORS 头。"""
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "password"},
        headers={"Origin": "http://172.16.100.2:5173"},
    )
    assert response.status_code == 200
    assert response.json().get("success") is True
    assert response.headers.get("access-control-allow-origin") == "http://172.16.100.2:5173"
    assert "mediasync_session=" in (response.headers.get("set-cookie") or "")
