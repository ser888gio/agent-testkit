import sqlite3

from agentkit.cli import app
from typer.testing import CliRunner

runner = CliRunner()


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
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"agents", "runs", "test_results", "alembic_version"} <= tables
    assert _current_revision(db) == "0001"


def test_cli_migrate_is_idempotent(tmp_path):
    db = str(tmp_path / "a.db")

    first = runner.invoke(app, ["migrate", "--db", db])
    second = runner.invoke(app, ["migrate", "--db", db])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert _current_revision(db) == "0001"


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
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert {"agents", "runs", "test_results", "alembic_version"} <= tables
    assert _current_revision(db) == "0001"


def test_cli_migrate_status_lists_pending_migrations(tmp_path):
    db = str(tmp_path / "a.db")

    result = runner.invoke(app, ["migrate", "--db", db, "--status"])

    assert result.exit_code == 0, result.output
    assert "pending 0001: baseline schema" in result.output
    assert _current_revision(db) is None


def test_cli_migrate_status_reports_up_to_date(tmp_path):
    db = str(tmp_path / "a.db")
    migrated = runner.invoke(app, ["migrate", "--db", db])

    result = runner.invoke(app, ["migrate", "--db", db, "--status"])

    assert migrated.exit_code == 0, migrated.output
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "up to date"
