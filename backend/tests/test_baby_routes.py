from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.database import create_database_engine, create_session_factory
from backend.app.main import app
from backend.app.models import Base, User
from backend.app.providers.google import ExternalIdentity
from backend.app.repositories.auth import InMemoryAuthRepository
from backend.app.repositories.babies import SqlAlchemyBabyRepository
from backend.app.services.auth import AuthService
from backend.app.services.babies import BabyService
from backend.tests.test_auth_service import NOW, settings


class MultiUserProvider:
    def __init__(self) -> None:
        self.identities = {
            "user-a-code": ExternalIdentity(
                "https://accounts.google.com", "subject-a", "a@example.test"
            ),
            "user-b-code": ExternalIdentity(
                "https://accounts.google.com", "subject-b", "b@example.test"
            ),
        }
        self.nonce: str | None = None

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        self.nonce = nonce
        return "https://accounts.google.com/auth?" + urlencode(
            {"state": state, "code_challenge": code_challenge}
        )

    def exchange_code(
        self, *, code: str, expected_nonce: str, code_verifier: str
    ) -> ExternalIdentity:
        del code_verifier
        if expected_nonce != self.nonce or code not in self.identities:
            raise ValueError("invalid synthetic authentication response")
        return self.identities[code]


@pytest.fixture
def configured_client(tmp_path: Path):
    auth_repository = InMemoryAuthRepository()
    provider = MultiUserProvider()
    user_a = auth_repository.get_or_create_identity_user(
        issuer="https://accounts.google.com",
        subject="subject-a",
        email="a@example.test",
        now=NOW,
    )
    user_b = auth_repository.get_or_create_identity_user(
        issuer="https://accounts.google.com",
        subject="subject-b",
        email="b@example.test",
        now=NOW,
    )

    database_url = f"sqlite:///{tmp_path / 'babies.sqlite3'}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                User(id=user_a.id, email=user_a.email),
                User(id=user_b.id, email=user_b.email),
            ]
        )
        session.commit()

    auth_service = AuthService(settings(), provider, auth_repository, clock=lambda: NOW)
    baby_service = BabyService(
        SqlAlchemyBabyRepository(create_session_factory(engine))
    )
    app.state.auth_service = auth_service
    app.state.baby_service = baby_service
    client = TestClient(app, base_url="https://testserver")

    def login(code: str) -> None:
        started = auth_service.start_login()
        state = started.authorization_url.split("state=", 1)[1].split("&", 1)[0]
        result = auth_service.complete_login(
            code=code, state=state, oauth_flow_cookie=started.oauth_flow_cookie
        )
        client.cookies.set(auth_service.cookie_names.session, result.session_cookie)
        client.cookies.set(auth_service.cookie_names.csrf, result.csrf_cookie)

    try:
        yield client, login, user_a.id, user_b.id
    finally:
        client.close()
        app.state.auth_service = None
        app.state.baby_service = None


def test_baby_crud_is_authenticated_and_owner_scoped(configured_client) -> None:
    client, login, owner_id, other_id = configured_client
    login("user-a-code")

    assert client.get("/api/v1/babies").json() == []
    created = client.post(
        "/api/v1/babies",
        json={
            "display_name": "  Synthetic baby  ",
            "date_of_birth": "2025-01-02",
            "timezone": "America/Los_Angeles",
        },
    )
    assert created.status_code == 201
    baby = created.json()
    baby_id = UUID(baby["id"])
    assert baby["display_name"] == "Synthetic baby"
    assert baby["timezone"] == "America/Los_Angeles"
    assert "user_id" not in baby
    assert baby["date_of_birth"] == "2025-01-02"

    fetched = client.get(f"/api/v1/babies/{baby_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == str(baby_id)

    patched = client.patch(
        f"/api/v1/babies/{baby_id}",
        json={"display_name": "Updated synthetic baby", "timezone": "UTC"},
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Updated synthetic baby"
    assert patched.json()["timezone"] == "UTC"

    login("user-b-code")
    assert client.get("/api/v1/babies").json() == []
    for method in ("get", "patch", "delete"):
        response = getattr(client, method)(
            f"/api/v1/babies/{baby_id}",
            **({"json": {"display_name": "Attacker"}} if method == "patch" else {}),
        )
        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "resource_not_found",
            "message": "The requested resource was not found.",
        }

    login("user-a-code")
    assert client.get(f"/api/v1/babies/{baby_id}").status_code == 200
    deleted = client.delete(f"/api/v1/babies/{baby_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/babies/{baby_id}").status_code == 404
    assert client.get("/api/v1/babies").json() == []
    assert owner_id != other_id


def test_baby_routes_require_server_session(configured_client) -> None:
    client, _, _, _ = configured_client
    for method, path in (
        ("get", "/api/v1/babies"),
        ("post", "/api/v1/babies"),
        ("get", "/api/v1/babies/not-a-uuid"),
    ):
        response = getattr(client, method)(
            path, **({"json": {"display_name": "No session"}} if method == "post" else {})
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_required"


def test_baby_request_validation_rejects_unknown_fields_bad_values_and_empty_patch(
    configured_client,
) -> None:
    client, login, _, _ = configured_client
    login("user-a-code")
    invalid_payloads = [
        {"user_id": "attacker", "display_name": "Should reject"},
        {"display_name": "   "},
        {"display_name": "Bad\nName"},
        {"timezone": "PST"},
        {"timezone": "../etc/passwd"},
        {"date_of_birth": "not-a-date"},
        {"date_of_birth": "2999-01-01"},
    ]
    for payload in invalid_payloads:
        response = client.post("/api/v1/babies", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    assert client.patch("/api/v1/babies/00000000-0000-0000-0000-000000000000", json={}).status_code == 422
    assert client.patch(
        "/api/v1/babies/00000000-0000-0000-0000-000000000000",
        json={"unknown": "field"},
    ).status_code == 422
    assert client.patch(
        "/api/v1/babies/00000000-0000-0000-0000-000000000000",
        json={"timezone": None},
    ).status_code == 422
    assert client.get("/api/v1/babies/not-a-uuid").status_code == 422


def test_baby_request_size_is_bounded(configured_client) -> None:
    client, login, _, _ = configured_client
    login("user-a-code")
    response = client.post(
        "/api/v1/babies",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": "4097"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "invalid_request"
