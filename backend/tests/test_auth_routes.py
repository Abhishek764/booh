from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from backend.app.main import app, create_app
from backend.app.repositories.auth import InMemoryAuthRepository
from backend.app.services.auth import AuthService
from backend.tests.test_auth_service import FakeProvider, MutableClock, NOW, settings


def test_login_callback_and_logout_use_secure_cookie_flags() -> None:
    provider = FakeProvider()
    service = AuthService(
        settings(), provider, InMemoryAuthRepository(), clock=lambda: NOW
    )
    app.state.auth_service = service
    client = TestClient(app, base_url="https://testserver")
    try:
        login = client.get("/api/v1/auth/google", follow_redirects=False)
        assert login.status_code == 303
        assert login.headers["cache-control"] == "no-store"
        flow_cookie = login.headers.get("set-cookie", "")
        assert "HttpOnly" in flow_cookie
        assert "Secure" in flow_cookie
        assert "SameSite=lax" in flow_cookie
        state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]

        callback = client.get(
            f"/api/v1/auth/google/callback?code=synthetic-code&state={state}",
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
        assert me.json()["csrf_token"] == csrf
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
        login = client.get("/api/v1/auth/google", follow_redirects=False)
        state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
        client.get(
            f"/api/v1/auth/google/callback?code=synthetic-code&state={state}",
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


def test_google_auth_routes_reject_open_redirect_and_require_authentication() -> None:
    service = AuthService(settings(), FakeProvider(), InMemoryAuthRepository())
    app.state.auth_service = service
    client = TestClient(app, base_url="https://testserver")
    try:
        response = client.get(
            "/api/v1/auth/google?next=https%3A%2F%2Fevil.example.test",
            follow_redirects=False,
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_callback"
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 401
        assert me.json()["error"]["code"] == "authentication_required"
    finally:
        app.state.auth_service = None


def test_google_callback_rejects_missing_state_and_expired_session() -> None:
    clock = MutableClock()
    service = AuthService(
        settings(), FakeProvider(), InMemoryAuthRepository(), clock=clock
    )
    app.state.auth_service = service
    client = TestClient(app, base_url="https://testserver")
    try:
        invalid = client.get(
            "/api/v1/auth/google/callback?code=synthetic-code",
            follow_redirects=False,
        )
        assert invalid.status_code == 401
        assert invalid.json()["error"]["code"] == "invalid_callback"

        login = client.get("/api/v1/auth/google", follow_redirects=False)
        state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
        callback = client.get(
            f"/api/v1/auth/google/callback?code=synthetic-code&state={state}",
            follow_redirects=False,
        )
        assert callback.status_code == 303
        clock.value = NOW + timedelta(days=8)
        expired = client.get("/api/v1/auth/me")
        assert expired.status_code == 401
        assert expired.json()["error"]["code"] == "authentication_required"
    finally:
        app.state.auth_service = None


def test_configured_origin_is_the_only_credentialed_cors_origin() -> None:
    configured_app = create_app(settings())
    client = TestClient(configured_app, base_url="https://testserver")
    for requested_method in ("GET", "POST", "PATCH", "DELETE"):
        allowed = client.options(
            "/api/v1/auth/me",
            headers={
                "Origin": "https://frontend.example.test",
                "Access-Control-Request-Method": requested_method,
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "https://frontend.example.test"
        assert allowed.headers["access-control-allow-credentials"] == "true"

    denied = client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": "https://evil.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
