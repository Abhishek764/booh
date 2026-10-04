from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.repositories.auth import InMemoryAuthRepository
from backend.app.services.auth import AuthService
from backend.tests.test_auth_service import FakeProvider, NOW, settings


def test_login_callback_and_logout_use_secure_cookie_flags() -> None:
    provider = FakeProvider()
    service = AuthService(
        settings(), provider, InMemoryAuthRepository(), clock=lambda: NOW
    )
    app.state.auth_service = service
    client = TestClient(app, base_url="https://testserver")
    try:
        login = client.get("/api/v1/auth/login", follow_redirects=False)
        assert login.status_code == 303
        assert login.headers["cache-control"] == "no-store"
        flow_cookie = login.headers.get("set-cookie", "")
        assert "HttpOnly" in flow_cookie
        assert "Secure" in flow_cookie
        assert "SameSite=lax" in flow_cookie
        state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]

        callback = client.get(
            f"/api/v1/auth/callback?code=synthetic-code&state={state}",
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert callback.headers["cache-control"] == "no-store"
        assert callback.headers["location"] == "https://frontend.example.test"
        cookies = callback.headers.get_list("set-cookie")
        session_cookie = next(value for value in cookies if "booh_session=" in value)
        csrf_cookie = next(value for value in cookies if "booh_session_csrf=" in value)
        assert "HttpOnly" in session_cookie
        assert "Secure" in session_cookie
        assert "SameSite=strict" in session_cookie
        assert "Path=/api/v1" in session_cookie
        assert "HttpOnly" not in csrf_cookie
        assert "Secure" in csrf_cookie

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.headers["cache-control"] == "no-store"
        csrf = client.cookies.get("booh_session_csrf")
        logout = client.post(
            "/api/v1/auth/logout",
            headers={
                "X-CSRF-Token": csrf,
                "Origin": "https://frontend.example.test",
            },
        )
        assert logout.status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
    finally:
        app.state.auth_service = None


def test_logout_requires_csrf_header() -> None:
    provider = FakeProvider()
    service = AuthService(
        settings(), provider, InMemoryAuthRepository(), clock=lambda: NOW
    )
    app.state.auth_service = service
    client = TestClient(app, base_url="https://testserver")
    try:
        login = client.get("/api/v1/auth/login", follow_redirects=False)
        state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
        client.get(
            f"/api/v1/auth/callback?code=synthetic-code&state={state}",
            follow_redirects=False,
        )
        response = client.post(
            "/api/v1/auth/logout", headers={"Origin": "https://frontend.example.test"}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "csrf_failed"
    finally:
        app.state.auth_service = None


def test_logout_rejects_missing_or_untrusted_origin() -> None:
    provider = FakeProvider()
    app.state.auth_service = AuthService(
        settings(), provider, InMemoryAuthRepository(), clock=lambda: NOW
    )
    client = TestClient(app, base_url="https://testserver")
    try:
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "origin_failed"
        response = client.post(
            "/api/v1/auth/logout", headers={"Origin": "https://evil.example.test"}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "origin_failed"
    finally:
        app.state.auth_service = None
