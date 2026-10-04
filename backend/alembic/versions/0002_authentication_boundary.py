"""Add provider-neutral identities and server-side auth lifecycle tables.

Revision ID: 0002_authentication_boundary
Revises: 0001_initial_schema
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_authentication_boundary"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=320)))

    op.create_table(
        "user_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "issuer", "subject", name="uq_user_identities_issuer_subject"
        ),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], unique=False)

    op.create_table(
        "oauth_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("binding_hash", sa.String(length=64), nullable=False),
        sa.Column("code_challenge", sa.String(length=43), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_oauth_transactions_state_hash",
        "oauth_transactions",
        ["state_hash"],
        unique=True,
    )
    op.create_index(
        "ix_oauth_transactions_expires_at",
        "oauth_transactions",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_oauth_transactions_expires_at", table_name="oauth_transactions")
    op.drop_index("ix_oauth_transactions_state_hash", table_name="oauth_transactions")
    op.drop_table("oauth_transactions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")
    op.drop_column("users", "email")
