"""Initial SQLAlchemy mappings for authorized user histories."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base metadata owned by the backend persistence layer."""


class EventType(str, enum.Enum):
    SLEEP = "sleep"
    FEED = "feed"
    WAKE = "wake"


class EventSource(str, enum.Enum):
    MANUAL = "manual"
    IMPORT = "import"


class User(Base):
    """Local user record; external identities are stored separately."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    events: Mapped[list[Event]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    identities: Mapped[list[UserIdentity]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class UserIdentity(Base):
    """Provider-neutral stable identity keyed by issuer and subject."""

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint(
            "issuer", "subject", name="uq_user_identities_issuer_subject"
        ),
        Index("ix_user_identities_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="identities")


class AuthSession(Base):
    """Server-side session state; only a hash of the bearer token is stored."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_token_hash", "token_hash", unique=True),
        Index("ix_auth_sessions_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="sessions")


class OAuthTransaction(Base):
    """Short-lived, single-use OAuth state bound to an initiating browser."""

    __tablename__ = "oauth_transactions"
    __table_args__ = (
        Index("ix_oauth_transactions_state_hash", "state_hash", unique=True),
        Index("ix_oauth_transactions_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(43), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Event(Base):
    """A timestamped, typed event owned by exactly one local user."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('sleep', 'feed', 'wake')",
            name="ck_events_event_type",
        ),
        CheckConstraint(
            "source IN ('manual', 'import')",
            name="ck_events_source",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_events_duration_nonnegative",
        ),
        Index("ix_events_user_occurred_at", "user_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[EventType] = mapped_column(String(16), nullable=False)
    source: Mapped[EventSource] = mapped_column(
        String(16), nullable=False, default=EventSource.MANUAL
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="events")
