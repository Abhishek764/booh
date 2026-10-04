"""Initial SQLAlchemy mappings for authorized user histories."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid
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
    """Minimal local user record; provider identities belong to TASK-004."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
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

    events: Mapped[list[Event]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
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
