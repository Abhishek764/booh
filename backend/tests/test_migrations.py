from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, table, column
from sqlalchemy import DateTime, Integer, String, Uuid


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def migration_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "backend" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_initial_migration_upgrade_and_rollback_are_isolated(tmp_path: Path) -> None:
    database_path = tmp_path / "migration-test.sqlite3"
    database_url = f"sqlite:///{database_path}"
    config = migration_config(database_url)

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    inspector = inspect(engine)

    assert set(inspector.get_table_names()) == {
        "alembic_version",
        "auth_sessions",
        "audio",
        "babies",
        "events",
        "oauth_transactions",
        "predictions",
        "summaries",
        "user_identities",
        "users",
    }
    assert {
        index["name"] for index in inspector.get_indexes("events")
    } == {"ix_events_baby_start", "ix_events_baby_type_start"}
    assert inspector.get_foreign_keys("events")[0]["referred_table"] == "babies"
    assert {
        column["name"] for column in inspector.get_columns("oauth_transactions")
    } == {
        "id",
        "state_hash",
        "nonce_hash",
        "binding_hash",
        "code_challenge",
        "created_at",
        "expires_at",
        "used_at",
    }
    assert {
        index["name"] for index in inspector.get_indexes("user_identities")
    } == {"ix_user_identities_user_id"}
    assert inspector.get_unique_constraints("user_identities")[0]["name"] == (
        "uq_user_identities_issuer_subject"
    )
    assert inspector.get_indexes("auth_sessions")[0]["name"] in {
        "ix_auth_sessions_token_hash",
        "ix_auth_sessions_user_id",
    }
    assert inspector.get_indexes("oauth_transactions")[0]["name"] in {
        "ix_oauth_transactions_state_hash",
        "ix_oauth_transactions_expires_at",
    }

    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}


def test_domain_migration_backfills_legacy_events_to_owned_babies(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "migration-backfill.sqlite3"
    database_url = f"sqlite:///{database_path}"
    config = migration_config(database_url)
    command.upgrade(config, "0002_authentication_boundary")
    engine = create_engine(database_url)
    user_id = uuid4()
    event_id = uuid4()
    occurred_at = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
    users = table("users", column("id", Uuid()))
    events = table(
        "events",
        column("id", Uuid()),
        column("user_id", Uuid()),
        column("event_type", String(16)),
        column("source", String(16)),
        column("occurred_at", DateTime(timezone=True)),
        column("duration_seconds", Integer()),
    )
    with engine.begin() as connection:
        connection.execute(users.insert().values(id=user_id))
        connection.execute(
            events.insert().values(
                id=event_id,
                user_id=user_id,
                event_type="sleep",
                source="manual",
                occurred_at=occurred_at,
                duration_seconds=600,
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        babies = table("babies", column("id", Uuid()), column("user_id", Uuid()))
        migrated_events = table(
            "events",
            column("id", Uuid()),
            column("baby_id", Uuid()),
            column("start_time", DateTime(timezone=True)),
        )
        baby = connection.execute(
            select(babies.c.id, babies.c.user_id)
        ).one()
        migrated_event = connection.execute(
            select(migrated_events.c.id, migrated_events.c.baby_id)
        ).one()

    assert baby.user_id == user_id
    assert migrated_event.id == event_id
    assert migrated_event.baby_id == baby.id
