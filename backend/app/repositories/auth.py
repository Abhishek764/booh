"""Repositories for users, OAuth transactions, and server-side sessions."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database import session_scope
from backend.app.models import AuthSession, OAuthTransaction, User, UserIdentity


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: uuid.UUID
    issuer: str
    subject: str
    email: str


@dataclass(frozen=True, slots=True)
class OAuthTransactionRecord:
    state_hash: str
    nonce_hash: str
    binding_hash: str
    code_challenge: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: uuid.UUID
    user: UserRecord
    token_hash: str
    csrf_hash: str
    last_seen_at: datetime
    expires_at: datetime


class AuthRepository(Protocol):
    """Persistence contract consumed by the auth service."""

    def get_or_create_identity_user(
        self, *, issuer: str, subject: str, email: str, now: datetime
    ) -> UserRecord: ...

    def create_oauth_transaction(
        self,
        *,
        state_hash: str,
        nonce_hash: str,
        binding_hash: str,
        code_challenge: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...

    def consume_oauth_transaction(
        self,
        *,
        state_hash: str,
        binding_hash: str,
        code_challenge: str,
        now: datetime,
    ) -> OAuthTransactionRecord | None: ...

    def create_session(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        csrf_hash: str,
        created_at: datetime,
        last_seen_at: datetime,
        expires_at: datetime,
    ) -> uuid.UUID: ...

    def get_active_session(
        self, *, token_hash: str, now: datetime, idle_after: datetime
    ) -> SessionRecord | None: ...

    def revoke_session(self, *, token_hash: str, revoked_at: datetime) -> None: ...


class SqlAlchemyAuthRepository:
    """SQLAlchemy implementation with owner and lifecycle predicates in queries."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_or_create_identity_user(
        self, *, issuer: str, subject: str, email: str, now: datetime
    ) -> UserRecord:
        """Resolve `(issuer, subject)` and retry a uniqueness race safely."""

        for attempt in range(2):
            try:
                with session_scope(self._session_factory) as session:
                    identity = session.scalar(
                        select(UserIdentity)
                        .where(
                            UserIdentity.issuer == issuer,
                            UserIdentity.subject == subject,
                        )
                        .with_for_update()
                    )
                    if identity is None:
                        user = User(email=email)
                        session.add(user)
                        session.flush()
                        identity = UserIdentity(
                            user_id=user.id,
                            issuer=issuer,
                            subject=subject,
                            created_at=now,
                            last_seen_at=now,
                        )
                        session.add(identity)
                    else:
                        user = session.get(User, identity.user_id)
                        if user is None:
                            raise RuntimeError("identity owner does not exist")
                        user.email = email
                        identity.last_seen_at = now
                    session.flush()
                    return UserRecord(user.id, issuer, subject, user.email or email)
            except IntegrityError:
                if attempt == 1:
                    raise
        raise RuntimeError("identity resolution failed")

    def create_oauth_transaction(
        self,
        *,
        state_hash: str,
        nonce_hash: str,
        binding_hash: str,
        code_challenge: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        with session_scope(self._session_factory) as session:
            session.add(
                OAuthTransaction(
                    state_hash=state_hash,
                    nonce_hash=nonce_hash,
                    binding_hash=binding_hash,
                    code_challenge=code_challenge,
                    created_at=created_at,
                    expires_at=expires_at,
                )
            )

    def consume_oauth_transaction(
        self,
        *,
        state_hash: str,
        binding_hash: str,
        code_challenge: str,
        now: datetime,
    ) -> OAuthTransactionRecord | None:
        with session_scope(self._session_factory) as session:
            consumed = session.execute(
                update(OAuthTransaction)
                .where(
                    OAuthTransaction.state_hash == state_hash,
                    OAuthTransaction.binding_hash == binding_hash,
                    OAuthTransaction.code_challenge == code_challenge,
                    OAuthTransaction.used_at.is_(None),
                    OAuthTransaction.expires_at > now,
                )
                .values(used_at=now)
            )
            if consumed.rowcount != 1:
                return None
            transaction = session.scalar(
                select(OAuthTransaction).where(
                    OAuthTransaction.state_hash == state_hash
                )
            )
            if transaction is None:
                return None
            return OAuthTransactionRecord(
                state_hash=transaction.state_hash,
                nonce_hash=transaction.nonce_hash,
                binding_hash=transaction.binding_hash,
                code_challenge=transaction.code_challenge,
                expires_at=_utc(transaction.expires_at),
            )

    def create_session(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        csrf_hash: str,
        created_at: datetime,
        last_seen_at: datetime,
        expires_at: datetime,
    ) -> uuid.UUID:
        session_id = uuid.uuid4()
        with session_scope(self._session_factory) as session:
            session.add(
                AuthSession(
                    id=session_id,
                    user_id=user_id,
                    token_hash=token_hash,
                    csrf_hash=csrf_hash,
                    created_at=created_at,
                    last_seen_at=last_seen_at,
                    expires_at=expires_at,
                )
            )
        return session_id

    def get_active_session(
        self, *, token_hash: str, now: datetime, idle_after: datetime
    ) -> SessionRecord | None:
        with session_scope(self._session_factory) as session:
            result = session.execute(
                select(AuthSession, User)
                .join(User, User.id == AuthSession.user_id)
                .where(
                    AuthSession.token_hash == token_hash,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > now,
                    AuthSession.last_seen_at > idle_after,
                )
            ).one_or_none()
            if result is None:
                return None
            auth_session, user = result
            if user.email is None:
                return None
            auth_session.last_seen_at = now
            session.flush()
            return SessionRecord(
                id=auth_session.id,
                user=UserRecord(user.id, "", "", user.email),
                token_hash=auth_session.token_hash,
                csrf_hash=auth_session.csrf_hash,
                last_seen_at=_utc(auth_session.last_seen_at),
                expires_at=_utc(auth_session.expires_at),
            )

    def revoke_session(self, *, token_hash: str, revoked_at: datetime) -> None:
        with session_scope(self._session_factory) as session:
            auth_session = session.scalar(
                select(AuthSession).where(
                    AuthSession.token_hash == token_hash,
                    AuthSession.revoked_at.is_(None),
                )
            )
            if auth_session is not None:
                auth_session.revoked_at = revoked_at


class InMemoryAuthRepository:
    """Deterministic repository for tests and explicit non-production app wiring."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.users: dict[tuple[str, str], UserRecord] = {}
        self.transactions: dict[str, tuple[OAuthTransactionRecord, bool]] = {}
        self.sessions: dict[str, SessionRecord] = {}
        self.revoked: set[str] = set()

    def get_or_create_identity_user(
        self, *, issuer: str, subject: str, email: str, now: datetime
    ) -> UserRecord:
        del now
        with self._lock:
            key = (issuer, subject)
            current = self.users.get(key)
            if current is not None:
                updated = UserRecord(current.id, issuer, subject, email)
                self.users[key] = updated
                return updated
            created = UserRecord(uuid.uuid4(), issuer, subject, email)
            self.users[key] = created
            return created

    def create_oauth_transaction(
        self,
        *,
        state_hash: str,
        nonce_hash: str,
        binding_hash: str,
        code_challenge: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        del created_at
        with self._lock:
            self.transactions[state_hash] = (
                OAuthTransactionRecord(
                    state_hash, nonce_hash, binding_hash, code_challenge, expires_at
                ),
                False,
            )

    def consume_oauth_transaction(
        self,
        *,
        state_hash: str,
        binding_hash: str,
        code_challenge: str,
        now: datetime,
    ) -> OAuthTransactionRecord | None:
        with self._lock:
            entry = self.transactions.get(state_hash)
            if entry is None:
                return None
            transaction, used = entry
            if (
                used
                or transaction.binding_hash != binding_hash
                or transaction.code_challenge != code_challenge
                or now >= transaction.expires_at
            ):
                return None
            self.transactions[state_hash] = (transaction, True)
            return transaction

    def create_session(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        csrf_hash: str,
        created_at: datetime,
        last_seen_at: datetime,
        expires_at: datetime,
    ) -> uuid.UUID:
        with self._lock:
            user = next((item for item in self.users.values() if item.id == user_id), None)
            if user is None:
                raise RuntimeError("authenticated user does not exist")
            session_id = uuid.uuid4()
            self.sessions[token_hash] = SessionRecord(
                session_id, user, token_hash, csrf_hash, last_seen_at, expires_at
            )
            return session_id

    def get_active_session(
        self, *, token_hash: str, now: datetime, idle_after: datetime
    ) -> SessionRecord | None:
        with self._lock:
            current = self.sessions.get(token_hash)
            if (
                current is None
                or token_hash in self.revoked
                or now >= current.expires_at
                or current.last_seen_at <= idle_after
            ):
                return None
            if (current.user.issuer, current.user.subject) not in self.users:
                return None
            touched = SessionRecord(
                current.id,
                current.user,
                current.token_hash,
                current.csrf_hash,
                now,
                current.expires_at,
            )
            self.sessions[token_hash] = touched
            return touched

    def revoke_session(self, *, token_hash: str, revoked_at: datetime) -> None:
        del revoked_at
        with self._lock:
            self.revoked.add(token_hash)


__all__ = [
    "AuthRepository",
    "InMemoryAuthRepository",
    "OAuthTransactionRecord",
    "SessionRecord",
    "SqlAlchemyAuthRepository",
    "UserRecord",
]
