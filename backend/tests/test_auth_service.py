from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from backend.app.config import AuthSettings
from backend.app.providers.google import ExternalIdentity, ProviderError
from backend.app.repositories.auth import InMemoryAuthRepository
from backend.app.security import digest, pkce_challenge
from backend.app.services.auth import AuthError, AuthService


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class FakeProvider:
    def __init__(self, identity: ExternalIdentity | None = None) -> None:
        self.identity = identity or ExternalIdentity(
            "https://accounts.google.com", "provider-subject", "synthetic@example.test"
        )
        self.state: str | None = None
        self.nonce: str | None = None
        self.code_challenge: str | None = None
        self.code_verifier: str | None = None
        self.fail_nonce = False

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        self.state = state
        self.nonce = nonce
        self.code_challenge = code_challenge
        return "https://accounts.google.com/auth?" + urlencode(
            {
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )

    def exchange_code(
        self, *, code: str, expected_nonce: str, code_verifier: str
    ) -> ExternalIdentity:
        self.code_verifier = code_verifier
        if code != "synthetic-code" or self.fail_nonce or expected_nonce != self.nonce:
            raise ProviderError("invalid synthetic provider response")
        return self.identity


def settings() -> AuthSettings:
    return AuthSettings(
        app_env="test",
        secret_key="synthetic-test-secret-key-with-at-least-32-bytes",
        frontend_origin="https://frontend.example.test",
        session_cookie_name="booh_session",
        session_cookie_secure=True,
        session_cookie_samesite="strict",
        google_client_id="synthetic-client-id",
        google_client_secret="synthetic-client-secret",
        google_redirect_uri="https://api.example.test/api/v1/auth/callback",
        google_issuer="https://accounts.google.com",
    )


def service(provider: FakeProvider | None = None) -> tuple[AuthService, FakeProvider]:
    selected = provider or FakeProvider()
    return AuthService(
        settings(),
        selected,
        InMemoryAuthRepository(),
        clock=lambda: NOW,
    ), selected


def begin(service_instance: AuthService, provider: FakeProvider) -> tuple[str, str]:
    result = service_instance.start_login()
    state = parse_qs(urlsplit(result.authorization_url).query)["state"][0]
    assert provider.state == state
    assert provider.code_challenge is not None
    return state, result.oauth_flow_cookie


def test_callback_rejects_state_mismatch_and_replay() -> None:
    auth, provider = service()
    state, flow_cookie = begin(auth, provider)

    with pytest.raises(AuthError, match="invalid_callback"):
        auth.complete_login(
            code="synthetic-code",
            state="wrong-state",
            oauth_flow_cookie=flow_cookie,
        )

    result = auth.complete_login(
        code="synthetic-code", state=state, oauth_flow_cookie=flow_cookie
    )
    with pytest.raises(AuthError, match="authentication_required"):
        auth.authenticate("tampered.cookie.value")

    # Reusing the same state and binding is rejected after the one-use consume.
    with pytest.raises(AuthError, match="invalid_callback"):
        auth.complete_login(
            code="synthetic-code", state=state, oauth_flow_cookie=flow_cookie
        )
    assert result.redirect_to == "https://frontend.example.test"


def test_pkce_is_present_and_verifier_is_bound_to_signed_flow() -> None:
    auth, provider = service()
    result = auth.start_login()
    query = parse_qs(urlsplit(result.authorization_url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [provider.code_challenge]
    state = query["state"][0]

    auth.complete_login(
        code="synthetic-code", state=state, oauth_flow_cookie=result.oauth_flow_cookie
    )
    assert provider.code_verifier is not None
    assert pkce_challenge(provider.code_verifier) == provider.code_challenge


def test_state_rejects_missing_expired_and_cross_session_flow_cookie() -> None:
    clock = MutableClock()
    provider = FakeProvider()
    auth = AuthService(settings(), provider, InMemoryAuthRepository(), clock=clock)
    first = auth.start_login()
    first_state = parse_qs(urlsplit(first.authorization_url).query)["state"][0]
    second = auth.start_login()
    second_state = parse_qs(urlsplit(second.authorization_url).query)["state"][0]

    with pytest.raises(AuthError, match="invalid_callback"):
        auth.complete_login(code="synthetic-code", state=None, oauth_flow_cookie=None)
    with pytest.raises(AuthError, match="invalid_callback"):
        auth.complete_login(
            code="synthetic-code", state=first_state, oauth_flow_cookie=second.oauth_flow_cookie
        )

    clock.value = NOW + timedelta(minutes=10, seconds=1)
    with pytest.raises(AuthError, match="invalid_callback"):
        auth.complete_login(
            code="synthetic-code", state=second_state, oauth_flow_cookie=second.oauth_flow_cookie
        )


def test_callback_rejects_nonce_failure_and_consumes_transaction() -> None:
    provider = FakeProvider()
    provider.fail_nonce = True
    auth, provider = service(provider)
    state, flow_cookie = begin(auth, provider)

    with pytest.raises(AuthError, match="invalid_callback"):
        auth.complete_login(
            code="synthetic-code", state=state, oauth_flow_cookie=flow_cookie
        )
    with pytest.raises(AuthError, match="invalid_callback"):
        auth.complete_login(
            code="synthetic-code", state=state, oauth_flow_cookie=flow_cookie
        )


def test_session_logout_invalidates_session_and_requires_csrf() -> None:
    auth, provider = service()
    state, flow_cookie = begin(auth, provider)
    result = auth.complete_login(
        code="synthetic-code", state=state, oauth_flow_cookie=flow_cookie
    )
    principal = auth.authenticate(result.session_cookie)

    with pytest.raises(AuthError, match="csrf_failed"):
        auth.logout(
            session_cookie=result.session_cookie,
            csrf_cookie=result.csrf_cookie,
            csrf_header="wrong-csrf",
            origin="https://frontend.example.test",
        )
    auth.logout(
        session_cookie=result.session_cookie,
        csrf_cookie=result.csrf_cookie,
        csrf_header=result.csrf_cookie,
        origin="https://frontend.example.test",
    )
    with pytest.raises(AuthError, match="authentication_required"):
        auth.authenticate(result.session_cookie)
    assert principal.email == "synthetic@example.test"


def test_sessions_rotate_and_enforce_idle_absolute_and_deleted_user_limits() -> None:
    clock = MutableClock()
    auth_settings = replace(
        settings(), session_ttl_seconds=100, session_idle_ttl_seconds=30
    )
    provider = FakeProvider()
    repository = InMemoryAuthRepository()
    auth = AuthService(auth_settings, provider, repository, clock=clock)

    first = auth.start_login()
    first_state = parse_qs(urlsplit(first.authorization_url).query)["state"][0]
    first_result = auth.complete_login(
        code="synthetic-code", state=first_state, oauth_flow_cookie=first.oauth_flow_cookie
    )
    second = auth.start_login()
    second_state = parse_qs(urlsplit(second.authorization_url).query)["state"][0]
    second_result = auth.complete_login(
        code="synthetic-code", state=second_state, oauth_flow_cookie=second.oauth_flow_cookie
    )
    assert first_result.session_cookie != second_result.session_cookie

    clock.value = NOW + timedelta(seconds=20)
    assert auth.authenticate(first_result.session_cookie).email == "synthetic@example.test"
    clock.value = NOW + timedelta(seconds=51)
    with pytest.raises(AuthError, match="authentication_required"):
        auth.authenticate(first_result.session_cookie)

    clock.value = NOW + timedelta(seconds=101)
    with pytest.raises(AuthError, match="authentication_required"):
        auth.authenticate(second_result.session_cookie)

    clock.value = NOW
    third = auth.start_login()
    third_state = parse_qs(urlsplit(third.authorization_url).query)["state"][0]
    third_result = auth.complete_login(
        code="synthetic-code", state=third_state, oauth_flow_cookie=third.oauth_flow_cookie
    )
    repository.users.clear()
    with pytest.raises(AuthError, match="authentication_required"):
        auth.authenticate(third_result.session_cookie)


def test_oauth_transaction_consumption_is_single_use_under_concurrency() -> None:
    repository = InMemoryAuthRepository()
    repository.create_oauth_transaction(
        state_hash=digest("state"),
        nonce_hash=digest("nonce"),
        binding_hash=digest("binding"),
        code_challenge="challenge",
        created_at=NOW,
        expires_at=NOW.replace(minute=5),
    )

    def consume() -> object:
        return repository.consume_oauth_transaction(
            state_hash=digest("state"),
            binding_hash=digest("binding"),
            code_challenge="challenge",
            now=NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(), range(2)))
    assert sum(result is not None for result in results) == 1


def test_provider_neutral_identity_uses_issuer_and_subject_not_email() -> None:
    repository = InMemoryAuthRepository()
    google = repository.get_or_create_identity_user(
        issuer="https://accounts.google.com",
        subject="same-subject",
        email="first@example.test",
        now=NOW,
    )
    same_identity = repository.get_or_create_identity_user(
        issuer="https://accounts.google.com",
        subject="same-subject",
        email="changed@example.test",
        now=NOW,
    )
    other_issuer = repository.get_or_create_identity_user(
        issuer="https://issuer.example.test",
        subject="same-subject",
        email="changed@example.test",
        now=NOW,
    )
    assert same_identity.id == google.id
    assert same_identity.email == "changed@example.test"
    assert other_issuer.id != google.id


def test_settings_fail_closed_for_missing_and_insecure_production_values() -> None:
    with pytest.raises(RuntimeError, match="APP_ENV"):
        AuthSettings.from_environment({})

    environment = {
        "APP_ENV": "production",
        "SECRET_KEY": "synthetic-test-secret-key-with-at-least-32-bytes",
        "FRONTEND_ORIGIN": "https://frontend.example.test",
        "SESSION_COOKIE_NAME": "booh_session",
        "SESSION_COOKIE_SECURE": "false",
        "SESSION_COOKIE_SAMESITE": "lax",
        "GOOGLE_OAUTH_CLIENT_ID": "synthetic-client-id",
        "GOOGLE_OAUTH_CLIENT_SECRET": "synthetic-client-secret",
        "GOOGLE_OAUTH_REDIRECT_URI": "https://api.example.test/api/v1/auth/callback",
        "GOOGLE_OAUTH_ISSUER": "https://accounts.google.com",
    }
    with pytest.raises(RuntimeError, match="SESSION_COOKIE_SECURE"):
        AuthSettings.from_environment(environment)
    environment["SESSION_COOKIE_SECURE"] = "true"
    configured = AuthSettings.from_environment(environment)
    assert configured.google_redirect_uri.endswith("/api/v1/auth/callback")
