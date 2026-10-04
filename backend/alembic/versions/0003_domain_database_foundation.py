"""Add babies, baby-owned events, predictions, summaries, and audio references.

Revision ID: 0003_domain_database_foundation
Revises: 0002_authentication_boundary
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "0003_domain_database_foundation"
down_revision = "0002_authentication_boundary"
branch_labels = None
depends_on = None


def _legacy_events_table() -> sa.TableClause:
    return sa.table(
        "events",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("event_type", sa.String(16)),
        sa.column("source", sa.String(16)),
        sa.column("occurred_at", sa.DateTime(timezone=True)),
        sa.column("duration_seconds", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )


def _create_babies() -> sa.Table:
    babies = op.create_table(
        "babies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'UTC'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR length(display_name) > 0",
            name="ck_babies_display_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(timezone) > 0", name="ck_babies_timezone_nonempty"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_babies_user_created_at", "babies", ["user_id", "created_at"])
    return babies


def _backfill_legacy_babies(bind: sa.Connection, babies: sa.Table) -> None:
    """Give pre-baby events a private UTC baby without copying event content."""

    legacy_events = _legacy_events_table()
    user_ids = bind.execute(
        sa.select(legacy_events.c.user_id).distinct()
    ).scalars()
    now = datetime.now(timezone.utc)
    for user_id in user_ids:
        bind.execute(
            babies.insert().values(
                id=uuid.uuid4(),
                user_id=user_id,
                display_name=None,
                date_of_birth=None,
                timezone="UTC",
                created_at=now,
                updated_at=now,
            )
        )


def _create_new_events() -> sa.Table:
    return op.create_table(
        "events_new",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("baby_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("feed_amount_ml", sa.Numeric(8, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('sleep', 'feed', 'wake')",
            name="ck_events_event_type",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'import')",
            name="ck_events_source",
        ),
        sa.CheckConstraint(
            "end_time IS NULL OR end_time >= start_time",
            name="ck_events_end_after_start",
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_events_duration_nonnegative",
        ),
        sa.CheckConstraint(
            "feed_amount_ml IS NULL OR feed_amount_ml >= 0",
            name="ck_events_feed_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "event_type = 'feed' OR feed_amount_ml IS NULL",
            name="ck_events_feed_amount_only_for_feed",
        ),
        sa.ForeignKeyConstraint(["baby_id"], ["babies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def _replace_events_with_baby_owned_table(
    bind: sa.Connection, babies: sa.Table
) -> None:
    legacy_events = _legacy_events_table()
    new_events = _create_new_events()
    user_babies = sa.table(
        "babies",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
    )
    baby_by_user = {
        row.user_id: row.id
        for row in bind.execute(sa.select(user_babies.c.id, user_babies.c.user_id))
    }
    rows = []
    for row in bind.execute(sa.select(legacy_events)).mappings():
        rows.append(
            {
                "id": row["id"],
                "baby_id": baby_by_user[row["user_id"]],
                "event_type": row["event_type"],
                "source": row["source"],
                "start_time": row["occurred_at"],
                "end_time": None,
                "duration_seconds": row["duration_seconds"],
                "feed_amount_ml": None,
                "created_at": row["created_at"],
                "updated_at": row["created_at"],
            }
        )
    if rows:
        bind.execute(new_events.insert(), rows)

    op.drop_table("events")
    op.rename_table("events_new", "events")
    op.create_index("ix_events_baby_start", "events", ["baby_id", "start_time"])
    op.create_index(
        "ix_events_baby_type_start",
        "events",
        ["baby_id", "event_type", "start_time"],
    )


def _create_predictions() -> None:
    op.create_table(
        "predictions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("baby_id", sa.Uuid(), nullable=False),
        sa.Column("prediction_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_sleep_minutes", sa.Integer(), nullable=False),
        sa.Column("wake_probability_within_60m", sa.Numeric(5, 4), nullable=False),
        sa.Column("baseline_expected_sleep_minutes", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("feature_version", sa.String(length=128), nullable=False),
        sa.Column("feature_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expected_sleep_minutes >= 0",
            name="ck_predictions_expected_sleep_nonnegative",
        ),
        sa.CheckConstraint(
            "baseline_expected_sleep_minutes >= 0",
            name="ck_predictions_baseline_nonnegative",
        ),
        sa.CheckConstraint(
            "wake_probability_within_60m >= 0 AND wake_probability_within_60m <= 1",
            name="ck_predictions_wake_probability_range",
        ),
        sa.ForeignKeyConstraint(["baby_id"], ["babies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_predictions_baby_timestamp",
        "predictions",
        ["baby_id", "prediction_timestamp"],
    )


def _create_summaries() -> None:
    op.create_table(
        "summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prediction_id", sa.Uuid(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("provider_version", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(summary_text) > 0 AND length(summary_text) <= 2000",
            name="ck_summaries_text_length",
        ),
        sa.CheckConstraint(
            "length(provider_version) > 0",
            name="ck_summaries_provider_version_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["prediction_id"], ["predictions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_summaries_prediction_created_at",
        "summaries",
        ["prediction_id", "created_at"],
    )


def _create_audio() -> None:
    op.create_table(
        "audio",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("summary_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_version", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(storage_key) > 0", name="ck_audio_storage_key_nonempty"
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_audio_byte_size_positive"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_audio_duration_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["summary_id"], ["summaries.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_audio_storage_key"),
    )
    op.create_index(
        "ix_audio_summary_created_at", "audio", ["summary_id", "created_at"]
    )
    op.create_index("ix_audio_expires_at", "audio", ["expires_at"])


def upgrade() -> None:
    bind = op.get_bind()
    babies = _create_babies()
    _backfill_legacy_babies(bind, babies)
    _replace_events_with_baby_owned_table(bind, babies)
    _create_predictions()
    _create_summaries()
    _create_audio()


def _create_legacy_events() -> sa.Table:
    return op.create_table(
        "events_legacy",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('sleep', 'feed', 'wake')",
            name="ck_events_event_type",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'import')",
            name="ck_events_source",
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_events_duration_nonnegative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    current_events = sa.table(
        "events",
        sa.column("id", sa.Uuid()),
        sa.column("baby_id", sa.Uuid()),
        sa.column("event_type", sa.String(16)),
        sa.column("source", sa.String(16)),
        sa.column("start_time", sa.DateTime(timezone=True)),
        sa.column("duration_seconds", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    babies = sa.table(
        "babies", sa.column("id", sa.Uuid()), sa.column("user_id", sa.Uuid())
    )

    op.drop_table("audio")
    op.drop_table("summaries")
    op.drop_table("predictions")
    legacy_events = _create_legacy_events()
    rows = []
    for row in bind.execute(
        sa.select(
            current_events.c.id,
            babies.c.user_id,
            current_events.c.event_type,
            current_events.c.source,
            current_events.c.start_time,
            current_events.c.duration_seconds,
            current_events.c.created_at,
        ).select_from(current_events.join(babies, current_events.c.baby_id == babies.c.id))
    ).mappings():
        rows.append(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "event_type": row["event_type"],
                "source": row["source"],
                "occurred_at": row["start_time"],
                "duration_seconds": row["duration_seconds"],
                "created_at": row["created_at"],
            }
        )
    if rows:
        bind.execute(legacy_events.insert(), rows)
    op.drop_table("events")
    op.rename_table("events_legacy", "events")
    op.create_index("ix_events_user_occurred_at", "events", ["user_id", "occurred_at"])
    op.drop_table("babies")
