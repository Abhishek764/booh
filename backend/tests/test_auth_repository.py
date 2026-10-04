from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, inspect

from backend.app.database import create_session_factory
from backend.app.models import Base
from backend.app.repositories.auth import SqlAlchemyAuthRepository


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_sql_identity_is_provider_neutral_and_session_lifecycle_is_bounded() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyAuthRepository(create_session_factory(engine))

    google = repository.get_or_create_identity_user(
        issuer="https://accounts.google.com",
        subject="same-subject",
        email="one@example.test",
        now=NOW,
    )
    same_identity = repository.get_or_create_identity_user(
        issuer="https://accounts.google.com",
        subject="same-subject",
        email="updated@example.test",
        now=NOW,
    )
    other_issuer = repository.get_or_create_identity_user(
        issuer="https://issuer.example.test",
        subject="same-subject",
        email="updated@example.test",
        now=NOW,
    )
    assert same_identity.id == google.id
    assert same_identity.email == "updated@example.test"
    assert other_issuer.id != google.id

    token_hash = "a" * 64
    csrf_hash = "b" * 64
    repository.create_session(
        user_id=google.id,
        token_hash=token_hash,
        csrf_hash=csrf_hash,
        created_at=NOW,
        last_seen_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    active = repository.get_active_session(
        token_hash=token_hash,
        now=NOW + timedelta(minutes=1),
        idle_after=NOW - timedelta(minutes=1),
    )
    assert active is not None
    assert active.user.email == "updated@example.test"
    assert repository.get_active_session(
        token_hash=token_hash,
        now=NOW + timedelta(minutes=3),
        idle_after=NOW + timedelta(minutes=2),
    ) is None

    unique_constraints = inspect(engine).get_unique_constraints("user_identities")
    assert unique_constraints[0]["name"] == "uq_user_identities_issuer_subject"


def test_sql_oauth_transaction_persists_pkce_and_consumes_once() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyAuthRepository(create_session_factory(engine))
    challenge = "C" * 43
    repository.create_oauth_transaction(
        state_hash="s" * 64,
        nonce_hash="n" * 64,
        binding_hash="b" * 64,
        code_challenge=challenge,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )

    assert repository.consume_oauth_transaction(
        state_hash="s" * 64,
        binding_hash="b" * 64,
        code_challenge="D" * 43,
        now=NOW,
    ) is None
    consumed = repository.consume_oauth_transaction(
        state_hash="s" * 64,
        binding_hash="b" * 64,
        code_challenge=challenge,
        now=NOW,
    )
    assert consumed is not None
    assert consumed.code_challenge == challenge
    assert repository.consume_oauth_transaction(
        state_hash="s" * 64,
        binding_hash="b" * 64,
        code_challenge=challenge,
        now=NOW,
    ) is None
