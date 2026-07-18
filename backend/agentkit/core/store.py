"""SQLite persistence for runs + scores; read helpers for the CLI and UI."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agentkit.core.config import TargetConfig
from agentkit.core.schema import RunResult, TestResult
from agentkit.core.scoring import ScoreReport

DEFAULT_ORG = "default"
"""Org the CLI and the not-yet-authenticated dashboard write under (see T8)."""

# Keep in sync with infra/alembic/versions/*.py -- Store initializes a DB directly
# as well as reading one Alembic built, so both must produce the same schema.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
    id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    name TEXT NOT NULL,
    target_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, id),
    FOREIGN KEY (org_id) REFERENCES orgs(id)
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    score_json TEXT NOT NULL,
    UNIQUE (org_id, id),
    FOREIGN KEY (org_id) REFERENCES orgs(id),
    FOREIGN KEY (org_id, agent_id) REFERENCES agents(org_id, id)
);
CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    test_id TEXT NOT NULL,
    category TEXT NOT NULL,
    risk TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms REAL,
    result_json TEXT NOT NULL,
    FOREIGN KEY (org_id) REFERENCES orgs(id),
    FOREIGN KEY (org_id, run_id) REFERENCES runs(org_id, id)
);
CREATE INDEX IF NOT EXISTS idx_results_run ON test_results(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs(agent_id);
CREATE INDEX IF NOT EXISTS idx_runs_org_started ON runs(org_id, started_at);
CREATE INDEX IF NOT EXISTS idx_agents_org ON agents(org_id);
CREATE INDEX IF NOT EXISTS idx_results_org ON test_results(org_id);
"""


@dataclass
class AgentRow:
    id: str
    org_id: str
    name: str
    target_type: str
    created_at: str


@dataclass
class RunRow:
    id: str
    agent_id: str
    started_at: str
    finished_at: str
    status: str
    summary: dict
    score: dict


Matrix = dict[str, dict[str, str]]


def _summarize(run: RunResult) -> dict:
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for r in run.results:
        by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        by_category[r.category.value] = by_category.get(r.category.value, 0) + 1
    return {"by_status": by_status, "by_category": by_category}


class Store:
    def __init__(self, path: str = "database/agentkit.db"):
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save_run(
        self, org_id: str, agent: TargetConfig, run: RunResult, score: ScoreReport
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        status = "passed" if score.gate_passed else "failed"

        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO orgs (id, name, created_at) VALUES (?, ?, ?)",
                (org_id, org_id, now),
            )
            self._conn.execute(
                """
                INSERT INTO agents (id, org_id, name, target_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(org_id, id) DO UPDATE SET
                    name = excluded.name,
                    target_type = excluded.target_type
                """,
                (agent.id, org_id, agent.id, agent.agent.type, now),
            )
            self._conn.execute(
                """
                INSERT INTO runs (id, org_id, agent_id, started_at, finished_at, status,
                                   summary_json, score_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    org_id,
                    agent.id,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat(),
                    status,
                    json.dumps(_summarize(run)),
                    score.model_dump_json(),
                ),
            )
            rows = []
            for r in run.results:
                payload = json.loads(r.model_dump_json())
                rows.append(
                    (
                        org_id,
                        run.run_id,
                        r.test_id,
                        r.category.value,
                        r.risk.value,
                        r.status.value,
                        r.latency_ms,
                        json.dumps(payload),
                    )
                )
            self._conn.executemany(
                """
                INSERT INTO test_results (org_id, run_id, test_id, category, risk, status,
                                           latency_ms, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def list_agents(self, org_id: str) -> list[AgentRow]:
        cur = self._conn.execute(
            "SELECT id, org_id, name, target_type, created_at FROM agents "
            "WHERE org_id = ? ORDER BY created_at DESC",
            (org_id,),
        )
        return [AgentRow(**dict(row)) for row in cur.fetchall()]

    def list_tests(self, org_id: str) -> list[dict]:
        """Distinct tests seen across this org's runs, with their latest status."""
        cur = self._conn.execute(
            """
            SELECT tr.test_id, tr.category, tr.risk, tr.status,
                   r.id AS run_id, r.agent_id
            FROM test_results tr
            JOIN runs r ON r.id = tr.run_id AND r.org_id = tr.org_id
            WHERE tr.org_id = ? AND r.org_id = ?
            ORDER BY r.started_at DESC, tr.id
            """,
            (org_id, org_id),
        )
        seen: dict[str, dict] = {}
        for row in cur.fetchall():
            if row["test_id"] in seen:
                seen[row["test_id"]]["run_count"] += 1
                continue
            seen[row["test_id"]] = {
                "test_id": row["test_id"],
                "category": row["category"],
                "risk": row["risk"],
                "latest_status": row["status"],
                "latest_run_id": row["run_id"],
                "latest_agent_id": row["agent_id"],
                "run_count": 1,
            }
        return sorted(seen.values(), key=lambda t: (t["category"], t["test_id"]))

    def run_count(self, org_id: str, agent_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE org_id = ? AND agent_id = ?",
            (org_id, agent_id),
        ).fetchone()
        return row["n"]

    def list_runs(self, org_id: str, agent_id: str | None = None, limit: int = 50) -> list[RunRow]:
        if agent_id is not None:
            cur = self._conn.execute(
                "SELECT * FROM runs WHERE org_id = ? AND agent_id = ? "
                "ORDER BY started_at DESC LIMIT ?",
                (org_id, agent_id, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM runs WHERE org_id = ? ORDER BY started_at DESC LIMIT ?",
                (org_id, limit),
            )
        return [
            RunRow(
                id=row["id"],
                agent_id=row["agent_id"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                status=row["status"],
                summary=json.loads(row["summary_json"]),
                score=json.loads(row["score_json"]),
            )
            for row in cur.fetchall()
        ]

    def get_run(self, org_id: str, run_id: str) -> tuple[RunResult, ScoreReport]:
        # Another org's run is KeyError, same as missing -- do not leak existence.
        row = self._conn.execute(
            "SELECT * FROM runs WHERE org_id = ? AND id = ?", (org_id, run_id)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)

        result_rows = self._conn.execute(
            "SELECT result_json FROM test_results WHERE org_id = ? AND run_id = ? ORDER BY id",
            (org_id, run_id),
        ).fetchall()
        results = [TestResult.model_validate_json(r["result_json"]) for r in result_rows]

        run = RunResult(
            run_id=row["id"],
            agent_name=row["agent_id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            results=results,
        )
        score_report = ScoreReport.model_validate_json(row["score_json"])
        return run, score_report

    def pass_fail_matrix(self, org_id: str, agent_id: str) -> Matrix:
        latest = self._conn.execute(
            "SELECT id FROM runs WHERE org_id = ? AND agent_id = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (org_id, agent_id),
        ).fetchone()
        if latest is None:
            return {}

        cur = self._conn.execute(
            "SELECT category, test_id, status FROM test_results "
            "WHERE org_id = ? AND run_id = ? ORDER BY id",
            (org_id, latest["id"]),
        )
        matrix: Matrix = {}
        for row in cur.fetchall():
            matrix.setdefault(row["category"], {})[row["test_id"]] = row["status"]
        return matrix
