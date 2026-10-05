"""Probability migration data preservation, schema parity, rollback, and PG DDL."""

import io
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import Float, create_engine, inspect, text

from backend.app.database import create_database_engine
from backend.tests.test_migrations import migration_config


def test_probability_migration_preserves_rows_children_and_exact_new_values(tmp_path):
    url = f"sqlite:///{tmp_path / 'probability-migration.sqlite3'}"
    config = migration_config(url)
    command.upgrade(config, "0003_domain_database_foundation")
    engine = create_engine(url)
    user_id, baby_id, prediction_id, summary_id = [uuid4().hex for _ in range(4)]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users(id) VALUES (:id)"), {"id": user_id})
        connection.execute(text("INSERT INTO babies(id,user_id,timezone) VALUES (:id,:owner,'UTC')"), {"id": baby_id, "owner": user_id})
        connection.execute(text("INSERT INTO predictions(id,baby_id,prediction_timestamp,expected_sleep_minutes,wake_probability_within_60m,baseline_expected_sleep_minutes,model_version,feature_version) VALUES (:id,:baby,:now,47,0.25,53,'baseline-7d-v1','sleep-remaining-v1')"), {"id": prediction_id, "baby": baby_id, "now": now})
        connection.execute(text("INSERT INTO summaries(id,prediction_id,summary_text,provider_version) VALUES (:id,:prediction,'Timing can vary.','sleep-summary-v1')"), {"id": summary_id, "prediction": prediction_id})
    command.upgrade(config, "head")
    assert isinstance(next(column for column in inspect(engine).get_columns("predictions") if column["name"] == "wake_probability_within_60m")["type"], Float)
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT count(*) FROM summaries")) == 1
        assert connection.scalar(text("SELECT wake_probability_within_60m FROM predictions")) == 0.25
        value = 0.12345678912345678
        connection.execute(text("UPDATE predictions SET wake_probability_within_60m=:p"), {"p": value})
        assert connection.scalar(text("SELECT wake_probability_within_60m FROM predictions")) == value
    command.check(config)
    command.downgrade(config, "0003_domain_database_foundation")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM predictions")) == 1
        assert connection.scalar(text("SELECT count(*) FROM summaries")) == 1
    assert {key["referred_table"] for key in inspect(engine).get_foreign_keys("predictions")} == {"babies"}
    command.downgrade(config, "base")
    engine.dispose()


def test_enabled_sqlite_foreign_keys_fail_closed_before_batch_parent_rebuild(tmp_path):
    url = f"sqlite:///{tmp_path / 'foreign-key-guard.sqlite3'}"
    config = migration_config(url)
    command.upgrade(config, "0003_domain_database_foundation")
    engine = create_database_engine(url)
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="^sqlite_batch_requires_foreign_keys_disabled$"):
            command.upgrade(config, "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003_domain_database_foundation"
    engine.dispose()


def test_postgresql_migration_uses_explicit_precision_and_reviewed_casts():
    config = migration_config("postgresql+psycopg://localhost/synthetic")
    output = io.StringIO()
    config.output_buffer = output
    command.upgrade(config, "0003_domain_database_foundation:head", sql=True)
    sql = output.getvalue()
    assert "FLOAT(53)" in sql and "USING wake_probability_within_60m::double precision" in sql
    output.seek(0)
    output.truncate(0)
    command.downgrade(config, "head:0003_domain_database_foundation", sql=True)
    assert "USING wake_probability_within_60m::numeric(5,4)" in output.getvalue()
