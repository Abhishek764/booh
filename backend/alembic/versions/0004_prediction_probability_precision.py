"""Preserve numerical prediction probability without four-decimal quantization.

Revision ID: 0004_prediction_probability
Revises: 0003_domain_database_foundation
Downgrade restores the historical four-decimal (lossy) representation.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_prediction_probability"
down_revision = "0003_domain_database_foundation"
branch_labels = None
depends_on = None


def _guard_sqlite_batch() -> None:
    context = op.get_context()
    if not context.as_sql and context.dialect.name == "sqlite" and op.get_bind().scalar(sa.text("PRAGMA foreign_keys")):
        # Dropping/rebuilding a referenced SQLite parent with FKs on can cascade
        # child deletion. The ordinary Alembic SQLite test connection has FKs off.
        raise RuntimeError("sqlite_batch_requires_foreign_keys_disabled")


def upgrade() -> None:
    _guard_sqlite_batch()
    with op.batch_alter_table("predictions") as batch:
        batch.alter_column("wake_probability_within_60m", existing_type=sa.Numeric(5, 4),
                           type_=sa.Float(precision=53), existing_nullable=False,
                           postgresql_using="wake_probability_within_60m::double precision")


def downgrade() -> None:
    _guard_sqlite_batch()
    with op.batch_alter_table("predictions") as batch:
        batch.alter_column("wake_probability_within_60m", existing_type=sa.Float(precision=53),
                           type_=sa.Numeric(5, 4), existing_nullable=False,
                           postgresql_using="wake_probability_within_60m::numeric(5,4)")
