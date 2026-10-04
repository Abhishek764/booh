from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


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
        "events",
        "oauth_transactions",
        "user_identities",
        "users",
    }
    assert inspector.get_indexes("events")[0]["name"] == "ix_events_user_occurred_at"
    assert inspector.get_foreign_keys("events")[0]["referred_table"] == "users"
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
