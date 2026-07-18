import sqlite3
import subprocess
import sys

import pytest
from agentkit.cli import _alembic_config, app
from agentkit.core.store import Store
from alembic import command as alembic_command
from typer.testing import CliRunner

runner = CliRunner()

# Bump when a new revision lands in infra/alembic/versions/.
HEAD = "0002"


def _schema_signature(db: str, table: str) -> tuple:
    conn = sqlite3.connect(db)
    try:
        columns = [tuple(row[1:]) for row in conn.execute(f"PRAGMA table_info({table})")]
        foreign_keys = sorted(
            tuple(row[2:]) for row in conn.execute(f"PRAGMA foreign_key_list({table})")
        )
        indexes = []
        for row in conn.execute(f"PRAGMA index_list({table})"):
            index_name = row[1]
            indexed_columns = tuple(
                index_row[2] for index_row in conn.execute(f"PRAGMA index_info({index_name})")
            )
            indexes.append((row[2], row[3], row[4], indexed_columns))
        return columns, foreign_keys, sorted(indexes)
    finally:
        conn.close()


def test_migrated_schema_matches_what_store_creates(tmp_path):
    """Store initializes a DB directly as well as reading a migrated one."""
    migrated = str(tmp_path / "migrated.db")
    assert runner.invoke(app, ["migrate", "--db", migrated]).exit_code == 0
    direct = str(tmp_path / "direct.db")
    Store(direct).close()

    for table in ("orgs", "agents", "runs", "test_results"):
        assert _schema_signature(migrated, table) == _schema_signature(direct, table), table

    conn = sqlite3.connect(migrated)
    conn.execute("PRAGMA foreign_keys = ON")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO runs (id, agent_id, started_at, finished_at, status, "
            "summary_json, score_json) VALUES ('missing-org', 'agent', 's', 'f', "
            "'passed', '{}', '{}')"
        )
    conn.close()


def test_cli_migrate_preserves_and_backfills_populated_baseline(tmp_path):
    db_path = tmp_path / "legacy.db"
    cfg = _alembic_config(db_path)
    alembic_command.upgrade(cfg, "0001")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO agents (id, name, target_type, created_at) VALUES (?, ?, ?, ?)",
        ("legacy-agent", "Legacy", "callable", "2026-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO runs (id, agent_id, started_at, finished_at, status, summary_json, "
        "score_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("legacy-run", "legacy-agent", "start", "finish", "passed", "{}", "{}"),
    )
    conn.execute(
        "INSERT INTO test_results (run_id, test_id, category, risk, status, result_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("legacy-run", "legacy.test", "reliability", "medium", "passed", "{}"),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["migrate", "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    assert conn.execute("SELECT id, org_id FROM agents").fetchall() == [("legacy-agent", "default")]
    assert conn.execute("SELECT id, org_id, agent_id FROM runs").fetchall() == [
        ("legacy-run", "default", "legacy-agent")
    ]
    assert conn.execute("SELECT run_id, org_id FROM test_results").fetchall() == [
        ("legacy-run", "default")
    ]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_downgrade_rejects_duplicate_agent_ids_without_data_loss(tmp_path):
    db_path = tmp_path / "tenant.db"
    cfg = _alembic_config(db_path)
    alembic_command.upgrade(cfg, "head")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO orgs (id, name, created_at) VALUES ('org-a', 'A', 'now'), "
        "('org-b', 'B', 'now')"
    )
    conn.execute(
        "INSERT INTO agents (id, org_id, name, target_type, created_at) VALUES "
        "('shared', 'org-a', 'A', 'callable', 'now'), "
        "('shared', 'org-b', 'B', 'callable', 'now')"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="multiple organizations use agent id 'shared'"):
        alembic_command.downgrade(cfg, "0001")

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM agents WHERE id = 'shared'").fetchone()[0] == 2
    assert _current_revision(str(db_path)) == HEAD
    conn.close()


def test_offline_migrations_fail_before_emitting_partial_sql():
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head", "--sql"],
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "offline SQL generation is not supported" in output
    assert "CREATE TABLE" not in result.stdout


def _current_revision(db: str) -> str | None:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def test_cli_migrate_applies_baseline_schema(tmp_path):
    db = str(tmp_path / "a.db")

    result = runner.invoke(app, ["migrate", "--db", db])

    assert result.exit_code == 0, result.output
    conn = sqlite3.connect(db)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"agents", "runs", "test_results", "alembic_version"} <= tables
    assert _current_revision(db) == HEAD


def test_cli_migrate_is_idempotent(tmp_path):
    db = str(tmp_path / "a.db")

    first = runner.invoke(app, ["migrate", "--db", db])
    second = runner.invoke(app, ["migrate", "--db", db])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert _current_revision(db) == HEAD


def test_cli_migrate_resumes_partially_applied_migration(tmp_path):
    db = str(tmp_path / "a.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            target_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["migrate", "--db", db])

    assert result.exit_code == 0, result.output
    conn = sqlite3.connect(db)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    assert {"agents", "runs", "test_results", "alembic_version"} <= tables
    assert _current_revision(db) == HEAD


def test_cli_migrate_status_lists_pending_migrations(tmp_path):
    db = str(tmp_path / "a.db")

    result = runner.invoke(app, ["migrate", "--db", db, "--status"])

    assert result.exit_code == 0, result.output
    assert "pending 0001: baseline schema" in result.output
    assert "pending 0002: orgs table + org_id on agents, runs, test_results" in result.output
    assert _current_revision(db) is None


def test_cli_migrate_status_reports_up_to_date(tmp_path):
    db = str(tmp_path / "a.db")
    migrated = runner.invoke(app, ["migrate", "--db", db])

    result = runner.invoke(app, ["migrate", "--db", db, "--status"])

    assert migrated.exit_code == 0, migrated.output
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "up to date"
