"""SQLite persistence for runs + scores; read helpers for the CLI and UI."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from agentkit.core.config import TargetConfig
from agentkit.core.redaction import Redactor
from agentkit.core.schema import RunResult, TestResult
from agentkit.core.scoring import ScoreReport

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    target_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    score_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    test_id TEXT NOT NULL,
    category TEXT NOT NULL,
    risk TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms REAL,
    result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_results_run ON test_results(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs(agent_id);
"""


@dataclass
class AgentRow:
    id: str
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
    def __init__(self, path: str = "agentkit.db"):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save_run(self, agent: TargetConfig, run: RunResult, score: ScoreReport) -> None:
        redactor = Redactor(agent.evidence.redact)
        now = datetime.now(timezone.utc).isoformat()
        status = "passed" if score.gate_passed else "failed"

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO agents (id, name, target_type, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    target_type = excluded.target_type
                """,
                (agent.id, agent.id, agent.agent.type, now),
            )
            self._conn.execute(
                """
                INSERT INTO runs (id, agent_id, started_at, finished_at, status,
                                   summary_json, score_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
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
                payload["request"] = (
                    redactor.redact(payload["request"]) if agent.evidence.store_request else None
                )
                payload["response"] = (
                    redactor.redact(payload["response"])
                    if agent.evidence.store_response
                    else None
                )
                rows.append(
                    (
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
                INSERT INTO test_results (run_id, test_id, category, risk, status,
                                           latency_ms, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def list_agents(self) -> list[AgentRow]:
        cur = self._conn.execute("SELECT * FROM agents ORDER BY created_at DESC")
        return [AgentRow(**dict(row)) for row in cur.fetchall()]

    def list_runs(self, agent_id: str | None = None, limit: int = 50) -> list[RunRow]:
        if agent_id is not None:
            cur = self._conn.execute(
                "SELECT * FROM runs WHERE agent_id = ? ORDER BY started_at DESC LIMIT ?",
                (agent_id, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
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

    def get_run(self, run_id: str) -> tuple[RunResult, ScoreReport]:
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)

        result_rows = self._conn.execute(
            "SELECT result_json FROM test_results WHERE run_id = ? ORDER BY id", (run_id,)
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

    def pass_fail_matrix(self, agent_id: str) -> Matrix:
        latest = self._conn.execute(
            "SELECT id FROM runs WHERE agent_id = ? ORDER BY started_at DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        if latest is None:
            return {}

        cur = self._conn.execute(
            "SELECT category, test_id, status FROM test_results WHERE run_id = ? ORDER BY id",
            (latest["id"],),
        )
        matrix: Matrix = {}
        for row in cur.fetchall():
            matrix.setdefault(row["category"], {})[row["test_id"]] = row["status"]
        return matrix
