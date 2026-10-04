"""SQLAlchemy mappings for BOOH identity, baby history, and model outputs."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
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

    babies: Mapped[list[Baby]] = relationship(
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


class Baby(Base):
    """A baby profile owned by exactly one authenticated user."""

    __tablename__ = "babies"
    __table_args__ = (
        CheckConstraint(
            "display_name IS NULL OR length(display_name) > 0",
            name="ck_babies_display_name_nonempty",
        ),
        CheckConstraint("length(timezone) > 0", name="ck_babies_timezone_nonempty"),
        Index("ix_babies_user_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="babies")
    events: Mapped[list[Event]] = relationship(
        back_populates="baby",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    predictions: Mapped[list[Prediction]] = relationship(
        back_populates="baby",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Event(Base):
    """A typed sleep, feed, or wake event owned through its baby."""

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
            "end_time IS NULL OR end_time >= start_time",
            name="ck_events_end_after_start",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_events_duration_nonnegative",
        ),
        CheckConstraint(
            "feed_amount_ml IS NULL OR feed_amount_ml >= 0",
            name="ck_events_feed_amount_nonnegative",
        ),
        CheckConstraint(
            "event_type = 'feed' OR feed_amount_ml IS NULL",
            name="ck_events_feed_amount_only_for_feed",
        ),
        Index("ix_events_baby_start", "baby_id", "start_time"),
        Index("ix_events_baby_type_start", "baby_id", "event_type", "start_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    baby_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("babies.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[EventType] = mapped_column(String(16), nullable=False)
    source: Mapped[EventSource] = mapped_column(
        String(16), nullable=False, default=EventSource.MANUAL
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feed_amount_ml: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    baby: Mapped[Baby] = relationship(back_populates="events")


class Prediction(Base):
    """An advisory prediction generated for one baby and data window."""

    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint(
            "expected_sleep_minutes >= 0",
            name="ck_predictions_expected_sleep_nonnegative",
        ),
        CheckConstraint(
            "baseline_expected_sleep_minutes >= 0",
            name="ck_predictions_baseline_nonnegative",
        ),
        CheckConstraint(
            "wake_probability_within_60m >= 0 AND wake_probability_within_60m <= 1",
            name="ck_predictions_wake_probability_range",
        ),
        Index("ix_predictions_baby_timestamp", "baby_id", "prediction_timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    baby_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("babies.id", ondelete="CASCADE"),
        nullable=False,
    )
    prediction_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expected_sleep_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    wake_probability_within_60m: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False
    )
    baseline_expected_sleep_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(128), nullable=False)
    feature_metadata: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    baby: Mapped[Baby] = relationship(back_populates="predictions")
    summaries: Mapped[list[Summary]] = relationship(
        back_populates="prediction",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Summary(Base):
    """A bounded natural-language summary of a validated prediction."""

    __tablename__ = "summaries"
    __table_args__ = (
        CheckConstraint(
            "length(summary_text) > 0 AND length(summary_text) <= 2000",
            name="ck_summaries_text_length",
        ),
        CheckConstraint(
            "length(provider_version) > 0",
            name="ck_summaries_provider_version_nonempty",
        ),
        Index("ix_summaries_prediction_created_at", "prediction_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    prediction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("predictions.id", ondelete="CASCADE"),
        nullable=False,
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    prediction: Mapped[Prediction] = relationship(back_populates="summaries")
    audio_files: Mapped[list[Audio]] = relationship(
        back_populates="summary",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Audio(Base):
    """Reference to generated audio stored outside PostgreSQL."""

    __tablename__ = "audio"
    __table_args__ = (
        CheckConstraint("length(storage_key) > 0", name="ck_audio_storage_key_nonempty"),
        CheckConstraint("byte_size > 0", name="ck_audio_byte_size_positive"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_audio_duration_nonnegative",
        ),
        UniqueConstraint("storage_key", name="uq_audio_storage_key"),
        Index("ix_audio_summary_created_at", "summary_id", "created_at"),
        Index("ix_audio_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    summary_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("summaries.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    summary: Mapped[Summary] = relationship(back_populates="audio_files")
