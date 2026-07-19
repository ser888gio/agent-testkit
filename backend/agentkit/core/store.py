"""SQLite persistence for runs + scores; read helpers for the CLI and UI."""

from __future__ import annotations

import json
import queue
import re
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentkit.core.config import TargetConfig, load_target_dict
from agentkit.core.loader import LoaderError, load_tests_from_rows
from agentkit.core.redaction import Redactor
from agentkit.core.schema import RunResult, TestResult
from agentkit.core.scoring import ScoreReport

DEFAULT_ORG = "default"
"""Org used by the local CLI, which has no authenticated user context."""

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
    created_by TEXT,
    created_by_email TEXT,
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
CREATE TABLE IF NOT EXISTS targets (
    id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    secret_ref TEXT,
    PRIMARY KEY (org_id, id),
    FOREIGN KEY (org_id) REFERENCES orgs(id)
);
CREATE TABLE IF NOT EXISTS packs (
    id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, id),
    FOREIGN KEY (org_id) REFERENCES orgs(id)
);
CREATE TABLE IF NOT EXISTS pack_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    test_id TEXT NOT NULL,
    test_json TEXT NOT NULL,
    created_by TEXT,
    created_by_email TEXT,
    UNIQUE (org_id, pack_id, test_id),
    FOREIGN KEY (org_id, pack_id) REFERENCES packs(org_id, id) ON DELETE CASCADE
);
-- target_id/pack_id are deliberately not foreign keys: the web run route still
-- names targets and packs by filesystem path (web/app.py:run_again), so a key
-- into targets/packs would reject every job T13 enqueues. Tighten once the
-- route is on DB rows.
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed')),
    run_id TEXT,
    created_by TEXT,
    error TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    FOREIGN KEY (org_id) REFERENCES orgs(id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(state, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_org ON jobs(org_id, created_at);
CREATE INDEX IF NOT EXISTS idx_targets_org ON targets(org_id);
CREATE INDEX IF NOT EXISTS idx_packs_org ON packs(org_id);
CREATE INDEX IF NOT EXISTS idx_pack_tests_pack ON pack_tests(org_id, pack_id);
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
class TargetRow:
    id: str
    org_id: str
    name: str
    created_at: str


@dataclass
class PackRow:
    id: str
    org_id: str
    name: str
    created_at: str
    test_count: int


@dataclass
class RunRow:
    id: str
    agent_id: str
    started_at: str
    finished_at: str
    status: str
    summary: dict
    score: dict
    created_by: str | None = None
    created_by_email: str | None = None


@dataclass
class JobRow:
    id: str
    org_id: str
    target_id: str
    pack_id: str
    state: str
    run_id: str | None
    created_by: str | None
    error: str | None
    priority: int
    attempt_count: int
    created_at: str
    started_at: str | None
    finished_at: str | None
    lease_owner: str | None
    lease_expires_at: str | None


JOB_STATES = ("queued", "running", "done", "failed")
_TERMINAL_JOB_STATES = ("done", "failed")

Matrix = dict[str, dict[str, str]]

_ENV_REFERENCE_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "client_secret",
    "credential",
    "credentials",
    "literals",
    "password",
    "proxy_authorization",
    "secret",
    "token",
    "x_api_key",
}
_CREDENTIAL_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{8,}|(?:Bearer|Basic)\s+[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
_SECRET_REF_RE = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        ("_api_key", "_password", "_secret", "_token")
    )


def _is_secret_reference(value: object, *, authorization: bool = False) -> bool:
    if isinstance(value, list):
        return bool(value) and all(
            _is_secret_reference(item, authorization=authorization) for item in value
        )
    if not isinstance(value, str):
        return False
    if authorization:
        return bool(
            re.fullmatch(
                r"\s*(?:(?:Bearer|Basic)\s+)?\$\{[A-Za-z_][A-Za-z0-9_]*\}\s*",
                value,
                re.IGNORECASE,
            )
        )
    return bool(re.fullmatch(r"\s*\$\{[A-Za-z_][A-Za-z0-9_]*\}\s*", value))


def _validate_secret_safe_config(value: object, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if key_text == "secret_ref":
                raise ValueError("secret_ref must be stored separately from config_json")
            if _is_sensitive_key(key_text) and not _is_secret_reference(
                item, authorization="authorization" in key_text.lower()
            ):
                location = ".".join((*path, key_text))
                raise ValueError(f"literal credential is not allowed in config_json at {location}")
            _validate_secret_safe_config(item, (*path, key_text))
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_secret_safe_config(item, (*path, str(index)))
        return
    if isinstance(value, str):
        if _CREDENTIAL_PATTERN.search(value):
            location = ".".join(path) or "<root>"
            raise ValueError(f"literal credential is not allowed in config_json at {location}")


def _contains_secret_reference(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            (_is_sensitive_key(str(key)) and _is_secret_reference(
                item, authorization="authorization" in str(key).lower()
            ))
            or _contains_secret_reference(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret_reference(item) for item in value)
    return False


def _replace_env_references(value: object) -> object:
    if isinstance(value, str):
        return _ENV_REFERENCE_RE.sub("agentkit-secret-reference", value)
    if isinstance(value, dict):
        return {key: _replace_env_references(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_env_references(item) for item in value]
    return value


def _validated_target_config(target_id: str, config: dict) -> None:
    _validate_secret_safe_config(config)
    validated = load_target_dict(
        _replace_env_references(config), source=f"stored target '{target_id}'"
    )
    if validated.id != target_id:
        raise ValueError(
            f"target id {target_id!r} does not match config id {validated.id!r}"
        )


def _sanitized_result_payload(result: TestResult, agent: TargetConfig) -> dict:
    payload = json.loads(result.model_dump_json())
    redactor = Redactor(agent.evidence.redact)
    payload["request"] = (
        redactor.redact(payload["request"]) if agent.evidence.store_request else None
    )
    payload["response"] = (
        redactor.redact(payload["response"]) if agent.evidence.store_response else None
    )
    payload["sandbox_diff"] = redactor.redact(payload["sandbox_diff"])
    payload["error"] = redactor.redact_text(payload["error"]) if payload["error"] else None
    for assertion in payload["assertion_results"]:
        assertion["detail"] = redactor.redact_text(assertion["detail"])
    return payload


def _summarize(run: RunResult) -> dict:
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for r in run.results:
        by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        by_category[r.category.value] = by_category.get(r.category.value, 0) + 1
    return {"by_status": by_status, "by_category": by_category}


class _SQLitePool:
    """A small bounded pool of connections, each leased to one caller at a time."""

    def __init__(self, path: str, max_size: int) -> None:
        self._path = path
        self._max_size = 1 if path == ":memory:" else max_size
        self._idle: queue.LifoQueue[sqlite3.Connection] = queue.LifoQueue(self._max_size)
        self._lock = threading.Lock()
        self._created = 0
        self._closed = False

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.executescript(_SCHEMA)
        conn.commit()
        return conn

    def _acquire(self) -> sqlite3.Connection:
        with self._lock:
            if self._closed:
                raise RuntimeError("Store is closed")
            try:
                return self._idle.get_nowait()
            except queue.Empty:
                if self._created < self._max_size:
                    self._created += 1
                    create = True
                else:
                    create = False
        if not create:
            while True:
                try:
                    conn = self._idle.get(timeout=0.1)
                except queue.Empty:
                    with self._lock:
                        if self._closed:
                            raise RuntimeError("Store is closed") from None
                    continue
                with self._lock:
                    if self._closed:
                        conn.close()
                        self._created -= 1
                        raise RuntimeError("Store is closed")
                return conn
        try:
            conn = self._open()
        except BaseException:
            with self._lock:
                self._created -= 1
            raise
        with self._lock:
            if self._closed:
                self._created -= 1
                conn.close()
                raise RuntimeError("Store is closed")
        return conn

    def _release(self, conn: sqlite3.Connection) -> None:
        with self._lock:
            if self._closed:
                self._created -= 1
                conn.close()
            else:
                self._idle.put_nowait(conn)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._acquire()
        try:
            yield conn
        finally:
            self._release(conn)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            while True:
                try:
                    conn = self._idle.get_nowait()
                except queue.Empty:
                    break
                conn.close()
                self._created -= 1


class Store:
    """The only SQLite access point. Safe to share across threads."""

    def __init__(self, path: str = "database/agentkit.db", pool_size: int = 4):
        if pool_size < 1:
            raise ValueError("pool_size must be at least 1")
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(db_path)
        self._pool = _SQLitePool(self._path, pool_size)
        with self._connection():
            pass

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._pool.connection() as conn:
            yield conn

    def close(self) -> None:
        """Close all idle connections and close leased connections when returned."""
        self._pool.close()

    def _ensure_org(self, conn: sqlite3.Connection, org_id: str, now: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO orgs (id, name, created_at) VALUES (?, ?, ?)",
            (org_id, org_id, now),
        )

    def save_target(
        self,
        org_id: str,
        target_id: str,
        name: str,
        config: dict,
        *,
        secret_ref: str | None = None,
    ) -> None:
        """Store a target's raw (un-interpolated) config. `${ENV_VAR}` refs stay
        literal here so no resolved credential is ever persisted -- see T15."""
        _validated_target_config(target_id, config)
        if _contains_secret_reference(config) and secret_ref is None:
            raise ValueError("secret_ref is required when config_json contains secret references")
        if secret_ref is not None and not _SECRET_REF_RE.fullmatch(secret_ref.strip()):
            raise ValueError("secret_ref must be an opaque scheme:// reference")
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn, conn:
            self._ensure_org(conn, org_id, now)
            conn.execute(
                """
                INSERT INTO targets (id, org_id, name, config_json, secret_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, id) DO UPDATE SET
                    name = excluded.name,
                    config_json = excluded.config_json,
                    secret_ref = excluded.secret_ref
                """,
                (target_id, org_id, name, json.dumps(config), secret_ref, now),
            )

    def get_target(self, org_id: str, target_id: str) -> dict:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT config_json FROM targets WHERE org_id = ? AND id = ?",
                (org_id, target_id),
            ).fetchone()
        if row is None:
            raise KeyError(target_id)
        return json.loads(row["config_json"])

    def get_target_secret_ref(self, org_id: str, target_id: str) -> str | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT secret_ref FROM targets WHERE org_id = ? AND id = ?",
                (org_id, target_id),
            ).fetchone()
        if row is None:
            raise KeyError(target_id)
        return row["secret_ref"]

    def list_targets(self, org_id: str) -> list[TargetRow]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id, org_id, name, created_at FROM targets "
                "WHERE org_id = ? ORDER BY created_at DESC, id",
                (org_id,),
            ).fetchall()
        return [TargetRow(**dict(row)) for row in rows]

    def delete_target(self, org_id: str, target_id: str) -> bool:
        with self._connection() as conn, conn:
            cursor = conn.execute(
                "DELETE FROM targets WHERE org_id = ? AND id = ?", (org_id, target_id)
            )
        return cursor.rowcount == 1

    def save_pack(self, org_id: str, pack_id: str, name: str, tests: list[dict]) -> None:
        """Replace a pack and its tests wholesale. One serialized TestCase per row."""
        validated_tests = load_tests_from_rows(tests)
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn, conn:
            self._ensure_org(conn, org_id, now)
            conn.execute(
                """
                INSERT INTO packs (id, org_id, name, created_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(org_id, id) DO UPDATE SET name = excluded.name
                """,
                (pack_id, org_id, name, now),
            )
            conn.execute(
                "DELETE FROM pack_tests WHERE org_id = ? AND pack_id = ?",
                (org_id, pack_id),
            )
            conn.executemany(
                "INSERT INTO pack_tests (org_id, pack_id, test_id, test_json) "
                "VALUES (?, ?, ?, ?)",
                [
                    (
                        org_id,
                        pack_id,
                        test.id,
                        test.model_dump_json(exclude_defaults=True),
                    )
                    for test in validated_tests
                ],
            )

    def ensure_pack(self, org_id: str, pack_id: str, name: str) -> None:
        """Create a pack if absent, leaving any existing tests alone.

        `save_pack` replaces a pack wholesale, so it cannot be used to
        lazily create the pack an authored test is about to be added to.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn, conn:
            self._ensure_org(conn, org_id, now)
            conn.execute(
                "INSERT INTO packs (id, org_id, name, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(org_id, id) DO NOTHING",
                (pack_id, org_id, name, now),
            )

    def list_authored_tests(self, org_id: str) -> list[dict]:
        """Every stored pack test for this org, across all its packs."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT pack_id, test_id, test_json, created_by, created_by_email "
                "FROM pack_tests WHERE org_id = ? ORDER BY pack_id, test_id",
                (org_id,),
            ).fetchall()
        out = []
        for row in rows:
            test = json.loads(row["test_json"])
            out.append(
                {
                    "pack_id": row["pack_id"],
                    "test_id": row["test_id"],
                    "category": test.get("category", "reliability"),
                    "risk": test.get("risk", "medium"),
                    "created_by": row["created_by"],
                    "created_by_email": row["created_by_email"],
                }
            )
        return out

    def save_pack_test(
        self,
        org_id: str,
        pack_id: str,
        test: dict,
        created_by: str | None = None,
        created_by_email: str | None = None,
    ) -> None:
        validated = load_tests_from_rows([test])[0]
        try:
            with self._connection() as conn, conn:
                pack = conn.execute(
                    "SELECT id FROM packs WHERE org_id = ? AND id = ?", (org_id, pack_id)
                ).fetchone()
                if pack is None:
                    raise KeyError(pack_id)
                conn.execute(
                    "INSERT INTO pack_tests (org_id, pack_id, test_id, test_json, "
                    "created_by, created_by_email) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        org_id,
                        pack_id,
                        validated.id,
                        validated.model_dump_json(exclude_defaults=True),
                        created_by,
                        created_by_email,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise LoaderError(
                f"duplicate test id '{validated.id}' in stored pack '{pack_id}'"
            ) from exc

    def get_pack_tests(self, org_id: str, pack_id: str) -> list[dict]:
        with self._connection() as conn:
            pack = conn.execute(
                "SELECT id FROM packs WHERE org_id = ? AND id = ?", (org_id, pack_id)
            ).fetchone()
            if pack is None:
                raise KeyError(pack_id)
            rows = conn.execute(
                "SELECT test_json FROM pack_tests "
                "WHERE org_id = ? AND pack_id = ? ORDER BY id",
                (org_id, pack_id),
            ).fetchall()
        return [json.loads(row["test_json"]) for row in rows]

    def list_packs(self, org_id: str) -> list[PackRow]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.org_id, p.name, p.created_at,
                       COUNT(pt.id) AS test_count
                FROM packs p
                LEFT JOIN pack_tests pt ON pt.org_id = p.org_id AND pt.pack_id = p.id
                WHERE p.org_id = ?
                GROUP BY p.id, p.org_id, p.name, p.created_at
                ORDER BY p.created_at DESC, p.id
                """,
                (org_id,),
            ).fetchall()
        return [PackRow(**dict(row)) for row in rows]

    def delete_pack_test(self, org_id: str, pack_id: str, test_id: str) -> bool:
        with self._connection() as conn, conn:
            cursor = conn.execute(
                "DELETE FROM pack_tests WHERE org_id = ? AND pack_id = ? AND test_id = ?",
                (org_id, pack_id, test_id),
            )
        return cursor.rowcount == 1

    def delete_pack(self, org_id: str, pack_id: str) -> bool:
        with self._connection() as conn, conn:
            conn.execute(
                "DELETE FROM pack_tests WHERE org_id = ? AND pack_id = ?", (org_id, pack_id)
            )
            cursor = conn.execute(
                "DELETE FROM packs WHERE org_id = ? AND id = ?", (org_id, pack_id)
            )
        return cursor.rowcount == 1

    # ---- jobs -------------------------------------------------------------
    #
    # Reads are org-scoped like everything else. `claim_job`, `heartbeat_job`,
    # `release_job`, and `reclaim_jobs` are deliberately *not*: a worker serves
    # every org, and its authority comes from `lease_owner`, not from a tenant
    # claim. They never return another org's evidence -- only job control rows.

    def enqueue_job(
        self,
        org_id: str,
        target_id: str,
        pack_id: str,
        *,
        created_by: str | None = None,
        priority: int = 0,
    ) -> str:
        job_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn, conn:
            self._ensure_org(conn, org_id, now)
            conn.execute(
                "INSERT INTO jobs (id, org_id, target_id, pack_id, state, created_by, "
                "priority, created_at) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)",
                (job_id, org_id, target_id, pack_id, created_by, priority, now),
            )
        return job_id

    def claim_job(
        self, owner: str, *, lease_seconds: int = 60, max_per_org: int | None = None
    ) -> JobRow | None:
        """Lease the highest-priority queued job, or return None if there is none.

        Two workers racing is resolved by the `AND state = 'queued'` guard on the
        update: the loser sees `rowcount == 0` and gets None, then polls again.
        This is portable to Postgres as-is; `FOR UPDATE SKIP LOCKED` is an
        optimization to add there if claim contention ever shows up in practice,
        not a correctness requirement.

        `max_per_org` skips orgs already at their running-job cap, so one partner
        cannot starve the others.
        """
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=lease_seconds)).isoformat()
        select = "SELECT id FROM jobs WHERE state = 'queued'"
        params: tuple = ()
        if max_per_org is not None:
            # ponytail: two workers can each admit the last slot for one org and
            # overshoot the cap by one, because the count is read before either
            # commits. This is anti-starvation, not a safety limit, so ±1 is
            # fine; make it exact with SELECT ... FOR UPDATE on Postgres if not.
            select += (
                " AND org_id NOT IN (SELECT org_id FROM jobs WHERE state = 'running'"
                " GROUP BY org_id HAVING COUNT(*) >= ?)"
            )
            params = (max_per_org,)
        with self._connection() as conn, conn:
            candidate = conn.execute(
                f"{select} ORDER BY priority DESC, created_at, id LIMIT 1", params
            ).fetchone()
            if candidate is None:
                return None
            cursor = conn.execute(
                "UPDATE jobs SET state = 'running', lease_owner = ?, lease_expires_at = ?, "
                "started_at = COALESCE(started_at, ?), attempt_count = attempt_count + 1 "
                "WHERE id = ? AND state = 'queued'",
                (owner, expires, now.isoformat(), candidate["id"]),
            )
            if cursor.rowcount != 1:
                return None
            return self._job_by_id(conn, candidate["id"])

    def heartbeat_job(self, job_id: str, owner: str, *, lease_seconds: int = 60) -> bool:
        """Extend the lease. False means the lease was lost -- stop working."""
        expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with self._connection() as conn, conn:
            cursor = conn.execute(
                "UPDATE jobs SET lease_expires_at = ? "
                "WHERE id = ? AND lease_owner = ? AND state = 'running'",
                (expires, job_id, owner),
            )
        return cursor.rowcount == 1

    def release_job(
        self,
        job_id: str,
        owner: str,
        *,
        state: str,
        run_id: str | None = None,
        error: str | None = None,
    ) -> bool:
        """Finish a job the caller holds the lease on. False means it was reclaimed."""
        if state not in _TERMINAL_JOB_STATES:
            raise ValueError(f"release state must be one of {_TERMINAL_JOB_STATES}")
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn, conn:
            cursor = conn.execute(
                "UPDATE jobs SET state = ?, run_id = ?, error = ?, finished_at = ?, "
                "lease_owner = NULL, lease_expires_at = NULL "
                "WHERE id = ? AND lease_owner = ? AND state = 'running'",
                (state, run_id, error, now, job_id, owner),
            )
        return cursor.rowcount == 1

    def reclaim_jobs(self, *, max_attempts: int = 3) -> int:
        """Requeue jobs whose lease expired; fail those past `max_attempts`.

        A live worker keeps its lease alive with `heartbeat_job`, so an expired
        lease means the worker is gone -- not that the job is slow.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn, conn:
            expired = (
                "state = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?"
            )
            failed = conn.execute(
                f"UPDATE jobs SET state = 'failed', error = 'lease expired', finished_at = ?, "
                f"lease_owner = NULL, lease_expires_at = NULL "
                f"WHERE {expired} AND attempt_count >= ?",
                (now, now, max_attempts),
            ).rowcount
            requeued = conn.execute(
                f"UPDATE jobs SET state = 'queued', lease_owner = NULL, lease_expires_at = NULL "
                f"WHERE {expired}",
                (now,),
            ).rowcount
        return failed + requeued

    def get_job(self, org_id: str, job_id: str) -> JobRow:
        # Another org's job is KeyError, same as missing -- see get_run.
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE org_id = ? AND id = ?", (org_id, job_id)
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return JobRow(**dict(row))

    def list_jobs(self, org_id: str, *, state: str | None = None, limit: int = 50) -> list[JobRow]:
        query = "SELECT * FROM jobs WHERE org_id = ?"
        params: tuple = (org_id,)
        if state is not None:
            query += " AND state = ?"
            params += (state,)
        query += " ORDER BY created_at DESC, id LIMIT ?"
        with self._connection() as conn:
            rows = conn.execute(query, (*params, limit)).fetchall()
        return [JobRow(**dict(row)) for row in rows]

    @staticmethod
    def _job_by_id(conn: sqlite3.Connection, job_id: str) -> JobRow:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return JobRow(**dict(row))

    def save_run(
        self,
        org_id: str,
        agent: TargetConfig,
        run: RunResult,
        score: ScoreReport,
        created_by: str | None = None,
        created_by_email: str | None = None,
    ) -> None:
        """Persist a run.

        `created_by` is the Keycloak `sub` of whoever launched it, with the
        email denormalized alongside for display. Both are optional because the
        CLI has no human principal; unlike `org_id` a missing value here is a
        display gap, not a cross-tenant read.
        """
        now = datetime.now(timezone.utc).isoformat()
        status = "passed" if score.gate_passed else "failed"

        with self._connection() as conn, conn:
            self._ensure_org(conn, org_id, now)
            conn.execute(
                """
                INSERT INTO agents (id, org_id, name, target_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(org_id, id) DO UPDATE SET
                    name = excluded.name,
                    target_type = excluded.target_type
                """,
                (agent.id, org_id, agent.id, agent.agent.type, now),
            )
            conn.execute(
                """
                INSERT INTO runs (id, org_id, agent_id, started_at, finished_at, status,
                                   summary_json, score_json, created_by, created_by_email)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    created_by,
                    created_by_email,
                ),
            )
            rows = []
            for r in run.results:
                payload = _sanitized_result_payload(r, agent)
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
            conn.executemany(
                """
                INSERT INTO test_results (org_id, run_id, test_id, category, risk, status,
                                           latency_ms, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def list_agents(self, org_id: str) -> list[AgentRow]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id, org_id, name, target_type, created_at FROM agents "
                "WHERE org_id = ? ORDER BY created_at DESC",
                (org_id,),
            ).fetchall()
        return [AgentRow(**dict(row)) for row in rows]

    def list_tests(self, org_id: str) -> list[dict]:
        """Distinct tests seen across this org's runs, with their latest status."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT tr.test_id, tr.category, tr.risk, tr.status,
                       r.id AS run_id, r.agent_id
                FROM test_results tr
                JOIN runs r ON r.id = tr.run_id AND r.org_id = tr.org_id
                WHERE tr.org_id = ? AND r.org_id = ?
                ORDER BY r.started_at DESC, tr.id
                """,
                (org_id, org_id),
            ).fetchall()
        seen: dict[str, dict] = {}
        for row in rows:
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
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM runs WHERE org_id = ? AND agent_id = ?",
                (org_id, agent_id),
            ).fetchone()
        return row["n"]

    def list_runs(self, org_id: str, agent_id: str | None = None, limit: int = 50) -> list[RunRow]:
        with self._connection() as conn:
            if agent_id is not None:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE org_id = ? AND agent_id = ? "
                    "ORDER BY started_at DESC LIMIT ?",
                    (org_id, agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE org_id = ? ORDER BY started_at DESC LIMIT ?",
                    (org_id, limit),
                ).fetchall()
        return [
            RunRow(
                id=row["id"],
                agent_id=row["agent_id"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                status=row["status"],
                summary=json.loads(row["summary_json"]),
                score=json.loads(row["score_json"]),
                created_by=row["created_by"],
                created_by_email=row["created_by_email"],
            )
            for row in rows
        ]

    def get_run(self, org_id: str, run_id: str) -> tuple[RunResult, ScoreReport]:
        # Another org's run is KeyError, same as missing -- do not leak existence.
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE org_id = ? AND id = ?", (org_id, run_id)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)

            result_rows = conn.execute(
                "SELECT result_json FROM test_results "
                "WHERE org_id = ? AND run_id = ? ORDER BY id",
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
        with self._connection() as conn:
            latest = conn.execute(
                "SELECT id FROM runs WHERE org_id = ? AND agent_id = ? "
                "ORDER BY started_at DESC LIMIT 1",
                (org_id, agent_id),
            ).fetchone()
            if latest is None:
                return {}

            rows = conn.execute(
                "SELECT category, test_id, status FROM test_results "
                "WHERE org_id = ? AND run_id = ? ORDER BY id",
                (org_id, latest["id"]),
            ).fetchall()
        matrix: Matrix = {}
        for row in rows:
            matrix.setdefault(row["category"], {})[row["test_id"]] = row["status"]
        return matrix
