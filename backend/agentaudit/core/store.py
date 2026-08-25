"""SQLite persistence for runs + scores; read helpers for the CLI and UI."""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import uuid
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentaudit.core import credentials
from agentaudit.core.artifacts import artifact_key
from agentaudit.core.config import TargetConfig, load_target_dict
from agentaudit.core.egress import EgressPolicy
from agentaudit.core.loader import LoaderError, load_tests_from_rows
from agentaudit.core.profile import AgentProfile, HarnessPlan
from agentaudit.core.redaction import Redactor
from agentaudit.core.schema import RunResult, TestResult
from agentaudit.core.scoring import ScoreReport

DEFAULT_ORG = "default"
"""Org used by the local CLI, which has no authenticated user context."""

_STORE_CLOSED = "Store is closed"

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
    plan_json TEXT,
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
    allowed_hosts TEXT,
    profile_json TEXT,
    profiled_at TEXT,
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
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed', 'cancelled')),
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
    heartbeat_at TEXT,
    test_ids_json TEXT,
    tests_total INTEGER,
    tests_done INTEGER NOT NULL DEFAULT 0,
    progress_json TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (org_id) REFERENCES orgs(id)
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, id),
    UNIQUE (path),
    FOREIGN KEY (org_id) REFERENCES orgs(id),
    FOREIGN KEY (org_id, run_id) REFERENCES runs(org_id, id)
);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(org_id, run_id);
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
class ArtifactRow:
    id: str
    org_id: str
    run_id: str
    kind: str
    size: int
    path: str
    created_at: str


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
    heartbeat_at: str | None
    # JSON list of selected test ids, or None for "the whole pack". Defaulted
    # because `SELECT *` feeds JobRow(**dict(row)) and older rows predate it.
    test_ids_json: str | None = None
    # Live progress while the worker runs. Operational state, not evidence:
    # discarded once the run lands in `runs`.
    tests_total: int | None = None
    tests_done: int = 0
    progress_json: str | None = None
    cancel_requested: int = 0


JOB_STATES = ("queued", "running", "done", "failed", "cancelled")
_TERMINAL_JOB_STATES = ("done", "failed", "cancelled")

# worker.py releases a job cancelled after its last test as 'failed' with this
# error text, matching how any other job failure is reported.
CANCELLED_ERROR = "cancelled by user"

Matrix = dict[str, dict[str, str]]

# A discovery job carries no pack: it probes the endpoint and writes a profile.
# `jobs.pack_id` is NOT NULL, so the kind rides in a reserved id rather than a
# new column -- the queue, lease, retry and status machinery then works
# unchanged for both kinds. The leading "__" cannot collide with a pack id,
# which is a filesystem-derived name.
DISCOVERY_PACK_ID = "__discovery__"


def _validated_target_config(target_id: str, config: dict) -> None:
    credentials.scan_config(config)
    validated = load_target_dict(
        credentials.mask_references(config), source=f"stored target '{target_id}'"
    )
    if validated.id != target_id:
        raise ValueError(f"target id {target_id!r} does not match config id {validated.id!r}")


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
    return {
        "by_status": dict(Counter(r.status.value for r in run.results)),
        "by_category": dict(Counter(r.category.value for r in run.results)),
    }


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

    def _wait_for_idle(self) -> sqlite3.Connection:
        while True:
            try:
                conn = self._idle.get(timeout=0.1)
            except queue.Empty:
                with self._lock:
                    if self._closed:
                        raise RuntimeError(_STORE_CLOSED) from None
                continue
            with self._lock:
                if self._closed:
                    conn.close()
                    self._created -= 1
                    raise RuntimeError(_STORE_CLOSED)
            return conn

    def _acquire(self) -> sqlite3.Connection:
        with self._lock:
            if self._closed:
                raise RuntimeError(_STORE_CLOSED)
            try:
                return self._idle.get_nowait()
            except queue.Empty:
                if self._created < self._max_size:
                    self._created += 1
                    create = True
                else:
                    create = False
        if not create:
            return self._wait_for_idle()
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
                raise RuntimeError(_STORE_CLOSED)
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


def _job_by_id(conn: sqlite3.Connection, job_id: str) -> JobRow:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return JobRow(**dict(row))


class JobQueue:
    """The run queue: lease, heartbeat, release, reclaim.

    Split out of `Store` because its interface is its invariants -- a lease
    expires, attempts cap, a terminal state is final -- and those were sitting
    among thirty row-mapping methods that hide nothing. A reader asking "what
    happens when a worker dies mid-job" now has one place to look, and the
    worker's tests name a queue instead of a store.

    It stays inside `store.py` on purpose: SQLite is reached only through this
    module, and moving the SQL out to buy a shorter file would trade a rule that
    is enforced for one that is not. `Store.jobs` is the whole seam.
    """

    def __init__(self, store: Store) -> None:
        self._store = store

    def enqueue(
        self,
        org_id: str,
        target_id: str,
        pack_id: str,
        *,
        created_by: str | None = None,
        priority: int = 0,
        test_ids: Sequence[str] | None = None,
    ) -> str:
        """Queue a run.

        `test_ids` restricts the run to a subset of the pack. None means the
        whole pack, which is what an unselected run has always meant. An empty
        selection is rejected rather than silently running everything: a run of
        nothing is a mistake, and scoring it as a pass would be evidence of
        coverage that never happened.
        """
        if test_ids is not None and not test_ids:
            raise ValueError("test_ids must name at least one test, or be None for the whole pack")
        job_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self._store._connection() as conn, conn:
            self._store._ensure_org(conn, org_id, now)
            conn.execute(
                "INSERT INTO jobs (id, org_id, target_id, pack_id, state, created_by, "
                "priority, created_at, test_ids_json) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)",
                (
                    job_id,
                    org_id,
                    target_id,
                    pack_id,
                    created_by,
                    priority,
                    now,
                    json.dumps(list(test_ids)) if test_ids is not None else None,
                ),
            )
        return job_id

    def enqueue_discovery(
        self, org_id: str, target_id: str, *, created_by: str | None = None
    ) -> str:
        """Queue a profile refresh for one target.

        Deliberately a job rather than an inline call: discovery dials a live
        endpoint, and the web process must not make outbound requests in a
        request handler -- see `worker.execute_discovery`.
        """
        return self.enqueue(org_id, target_id, DISCOVERY_PACK_ID, created_by=created_by)

    def claim(
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
        now_text = now.isoformat()
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
        with self._store._connection() as conn, conn:
            # SQLite has no FOR UPDATE SKIP LOCKED.  BEGIN IMMEDIATE acquires
            # the write lock before selecting a candidate, making the cap and
            # the claim one atomic operation even across worker processes.
            conn.execute("BEGIN IMMEDIATE")
            candidate = conn.execute(
                f"{select} ORDER BY priority DESC, created_at, id LIMIT 1", params
            ).fetchone()
            if candidate is None:
                return None
            cursor = conn.execute(
                "UPDATE jobs SET state = 'running', lease_owner = ?, lease_expires_at = ?, "
                "heartbeat_at = ?, started_at = COALESCE(started_at, ?), "
                "attempt_count = attempt_count + 1 "
                "WHERE id = ? AND state = 'queued'",
                (owner, expires, now_text, now_text, candidate["id"]),
            )
            if cursor.rowcount != 1:
                return None
            return _job_by_id(conn, candidate["id"])

    # How many recent outcomes a job carries. Enough to see the run moving
    # without turning an operational row into a second copy of the evidence.
    PROGRESS_WINDOW = 12

    def start_progress(self, job_id: str, total: int) -> None:
        """Record how many tests the job is about to run."""
        with self._store._connection() as conn, conn:
            conn.execute(
                "UPDATE jobs SET tests_total = ?, tests_done = 0, progress_json = NULL "
                "WHERE id = ?",
                (total, job_id),
            )

    def record_progress(self, job_id: str, test_id: str, status: str) -> None:
        """Append one completed test to a job's live progress.

        Best-effort operational state: it carries a test id and a status word,
        never agent output, so it needs no redaction pass. The window is capped
        so a long run cannot grow this row without bound.
        """
        with self._store._connection() as conn, conn:
            row = conn.execute(
                "SELECT progress_json FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return
            recent = json.loads(row["progress_json"]) if row["progress_json"] else []
            recent.append({"test_id": test_id, "status": status})
            conn.execute(
                "UPDATE jobs SET tests_done = tests_done + 1, progress_json = ? WHERE id = ?",
                (json.dumps(recent[-self.PROGRESS_WINDOW :]), job_id),
            )

    def heartbeat(self, job_id: str, owner: str, *, lease_seconds: int = 60) -> bool:
        """Extend the lease. False means the lease was lost -- stop working."""
        now = datetime.now(timezone.utc).isoformat()
        expires = (datetime.fromisoformat(now) + timedelta(seconds=lease_seconds)).isoformat()
        with self._store._connection() as conn, conn:
            cursor = conn.execute(
                "UPDATE jobs SET lease_expires_at = ?, heartbeat_at = ? "
                "WHERE id = ? AND lease_owner = ? AND state = 'running'",
                (expires, now, job_id, owner),
            )
        return cursor.rowcount == 1

    def release(
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
        with self._store._connection() as conn, conn:
            cursor = conn.execute(
                "UPDATE jobs SET state = ?, run_id = ?, error = ?, finished_at = ?, "
                "lease_owner = NULL, lease_expires_at = NULL "
                "WHERE id = ? AND lease_owner = ? AND state = 'running'",
                (state, run_id, error, now, job_id, owner),
            )
        return cursor.rowcount == 1

    def request_cancel(self, org_id: str, job_id: str) -> str:
        """Ask a job to stop. Returns the resulting state word.

        A queued job has no worker to interrupt, so it goes straight to
        'cancelled'. A running job only gets the flag set: the worker checks it
        between tests (see `is_cancelled`) and releases the job itself, the same
        way any other terminal transition happens under its own lease. A job
        that already reached a terminal state is left alone. Unknown ids raise
        KeyError, like `get`.
        """
        job = self.get(org_id, job_id)
        now = datetime.now(timezone.utc).isoformat()
        if job.state == "queued":
            with self._store._connection() as conn, conn:
                conn.execute(
                    "UPDATE jobs SET state = 'cancelled', finished_at = ? "
                    "WHERE org_id = ? AND id = ? AND state = 'queued'",
                    (now, org_id, job_id),
                )
            return "cancelled"
        if job.state == "running":
            with self._store._connection() as conn, conn:
                conn.execute(
                    "UPDATE jobs SET cancel_requested = 1 "
                    "WHERE org_id = ? AND id = ? AND state = 'running'",
                    (org_id, job_id),
                )
            return "running"
        return job.state

    def is_cancel_requested(self, job_id: str) -> bool:
        """Whether a running job's worker should stop (`is_cancelled` alias)."""
        return self.is_cancelled(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        """Whether a running job's worker should stop. Best-effort, no lease check."""
        with self._store._connection() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

    def reclaim(self, *, max_attempts: int = 3) -> int:
        """Requeue jobs whose lease expired; fail those past `max_attempts`.

        A live worker keeps its lease alive with `heartbeat`, so an expired
        lease means the worker is gone -- not that the job is slow.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._store._connection() as conn, conn:
            expired = "state = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?"
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

    def get(self, org_id: str, job_id: str) -> JobRow:
        # Another org's job is KeyError, same as missing -- see get_run.
        with self._store._connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE org_id = ? AND id = ?", (org_id, job_id)
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return JobRow(**dict(row))

    def list_recent(
        self, org_id: str, *, state: str | None = None, limit: int = 50
    ) -> list[JobRow]:
        query = "SELECT * FROM jobs WHERE org_id = ?"
        params: tuple = (org_id,)
        if state is not None:
            query += " AND state = ?"
            params += (state,)
        query += " ORDER BY created_at DESC, id LIMIT ?"
        with self._store._connection() as conn:
            rows = conn.execute(query, (*params, limit)).fetchall()
        return [JobRow(**dict(row)) for row in rows]


class Store:
    """The only SQLite access point. Safe to share across threads."""

    def __init__(self, path: str = "database/agentaudit.db", pool_size: int = 4):
        if pool_size < 1:
            raise ValueError("pool_size must be at least 1")
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(db_path)
        self._pool = _SQLitePool(self._path, pool_size)
        with self._connection():
            pass
        self.jobs = JobQueue(self)

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
        allowed_hosts: list[str] | None = None,
    ) -> None:
        """Store a target's raw (un-interpolated) config. `${ENV_VAR}` refs stay
        literal here so no resolved credential is ever persisted -- see T15."""
        _validated_target_config(target_id, config)
        if credentials.contains_reference(config) and secret_ref is None:
            raise ValueError("secret_ref is required when config_json contains secret references")
        if secret_ref is not None and not credentials.is_secret_ref(secret_ref):
            raise ValueError("secret_ref must be an opaque scheme:// reference")
        hosts_json = None
        if allowed_hosts is not None:
            # Normalize once here so the stored value is what the egress check
            # compares against; a host that only matches after normalization at
            # read time is a mismatch waiting to be exploited.
            hosts_json = json.dumps(sorted(EgressPolicy.from_iterable(allowed_hosts).allowed_hosts))
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn, conn:
            self._ensure_org(conn, org_id, now)
            conn.execute(
                """
                INSERT INTO targets (id, org_id, name, config_json, secret_ref,
                                     allowed_hosts, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, id) DO UPDATE SET
                    name = excluded.name,
                    config_json = excluded.config_json,
                    secret_ref = excluded.secret_ref,
                    allowed_hosts = excluded.allowed_hosts
                """,
                (target_id, org_id, name, json.dumps(config), secret_ref, hosts_json, now),
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

    def get_target_allowed_hosts(self, org_id: str, target_id: str) -> list[str]:
        """Hosts this target may be dialled at. Empty means no egress is permitted."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT allowed_hosts FROM targets WHERE org_id = ? AND id = ?",
                (org_id, target_id),
            ).fetchone()
        if row is None:
            raise KeyError(target_id)
        return json.loads(row["allowed_hosts"]) if row["allowed_hosts"] else []

    def save_target_profile(self, org_id: str, target_id: str, profile: AgentProfile) -> None:
        """Replace what discovery knows about a target.

        A profile describes the agent, so re-discovering overwrites rather than
        appends. `AgentProfile` carries only shapes, booleans and names -- never
        agent output -- so it needs no redaction pass of its own; see
        `core/discovery.py` for the fence that keeps it that way.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn, conn:
            cursor = conn.execute(
                "UPDATE targets SET profile_json = ?, profiled_at = ? WHERE org_id = ? AND id = ?",
                (profile.model_dump_json(), now, org_id, target_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(target_id)

    def get_target_profile(self, org_id: str, target_id: str) -> tuple[AgentProfile, str] | None:
        """The stored profile and when it was taken, or None if never discovered."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT profile_json, profiled_at FROM targets WHERE org_id = ? AND id = ?",
                (org_id, target_id),
            ).fetchone()
        if row is None:
            raise KeyError(target_id)
        if not row["profile_json"]:
            return None
        return AgentProfile.model_validate_json(row["profile_json"]), row["profiled_at"]

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
                "INSERT INTO pack_tests (org_id, pack_id, test_id, test_json) VALUES (?, ?, ?, ?)",
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
                "SELECT test_json FROM pack_tests WHERE org_id = ? AND pack_id = ? ORDER BY id",
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

    # ---- artifacts --------------------------------------------------------

    def save_artifact(
        self, org_id: str, run_id: str, artifact_id: str, kind: str, size: int
    ) -> str:
        """Record blob metadata. The path is derived, never caller-supplied.

        The run must belong to `org_id`; the foreign key would catch a mismatch
        anyway, but failing here keeps the error legible.
        """
        path = artifact_key(org_id, run_id, artifact_id)
        if size < 0:
            raise ValueError("artifact size must not be negative")
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn, conn:
            run = conn.execute(
                "SELECT id FROM runs WHERE org_id = ? AND id = ?", (org_id, run_id)
            ).fetchone()
            if run is None:
                raise KeyError(run_id)
            conn.execute(
                "INSERT INTO artifacts (id, org_id, run_id, kind, size, path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, org_id, run_id, kind, size, path, now),
            )
        return path

    def get_artifact(self, org_id: str, artifact_id: str) -> ArtifactRow:
        # Another org's artifact is KeyError, same as missing -- see get_run.
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE org_id = ? AND id = ?", (org_id, artifact_id)
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return ArtifactRow(**dict(row))

    def list_artifacts(self, org_id: str, run_id: str) -> list[ArtifactRow]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE org_id = ? AND run_id = ? ORDER BY created_at, id",
                (org_id, run_id),
            ).fetchall()
        return [ArtifactRow(**dict(row)) for row in rows]

    # ---- jobs -------------------------------------------------------------
    #
    # Reads are org-scoped like everything else. `claim_job`, `heartbeat_job`,
    # `release_job`, and `reclaim_jobs` are deliberately *not*: a worker serves
    # every org, and its authority comes from `lease_owner`, not from a tenant
    # claim. They never return another org's evidence -- only job control rows.

    def save_run(
        self,
        org_id: str,
        agent: TargetConfig,
        run: RunResult,
        score: ScoreReport,
        created_by: str | None = None,
        created_by_email: str | None = None,
        plan: HarnessPlan | None = None,
    ) -> None:
        """Persist a run.

        `plan` is the harness plan the run executed, when a planner produced one.
        It records why each test was selected, so a stored run stays explainable
        after the fact.

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
                                   summary_json, score_json, created_by, created_by_email,
                                   plan_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    plan.model_dump_json() if plan else None,
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

    def purge_runs(
        self, *, keep_days: int | None = None, keep_last: int | None = None
    ) -> tuple[int, list[str]]:
        """Delete old runs plus their results and artifact rows, across all orgs.

        `keep_days` drops runs started before the cutoff; `keep_last` drops runs
        beyond the newest N per (org, agent). Both given means both apply.
        Returns (deleted run count, orphaned artifact blob paths) -- the caller
        owns the blob directory and removes the files.
        """
        if keep_days is None and keep_last is None:
            raise ValueError("purge_runs needs keep_days and/or keep_last")
        victims: set[tuple[str, str]] = set()
        with self._connection() as conn, conn:
            if keep_days is not None:
                # Same aware-UTC isoformat save_run writes, so the string
                # comparison is chronological.
                cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
                victims.update(
                    (r["org_id"], r["id"])
                    for r in conn.execute(
                        "SELECT org_id, id FROM runs WHERE started_at < ?", (cutoff,)
                    )
                )
            if keep_last is not None:
                victims.update(
                    (r["org_id"], r["id"])
                    for r in conn.execute(
                        """
                        SELECT org_id, id FROM (
                            SELECT org_id, id, ROW_NUMBER() OVER (
                                PARTITION BY org_id, agent_id
                                ORDER BY started_at DESC, id
                            ) AS rn FROM runs
                        ) WHERE rn > ?
                        """,
                        (keep_last,),
                    )
                )
            blob_paths: list[str] = []
            for org_id, run_id in sorted(victims):
                blob_paths.extend(
                    row["path"]
                    for row in conn.execute(
                        "SELECT path FROM artifacts WHERE org_id = ? AND run_id = ?",
                        (org_id, run_id),
                    )
                )
                conn.execute(
                    "DELETE FROM artifacts WHERE org_id = ? AND run_id = ?",
                    (org_id, run_id),
                )
                conn.execute(
                    "DELETE FROM test_results WHERE org_id = ? AND run_id = ?",
                    (org_id, run_id),
                )
                conn.execute("DELETE FROM runs WHERE org_id = ? AND id = ?", (org_id, run_id))
        return len(victims), blob_paths

    def get_run(self, org_id: str, run_id: str) -> tuple[RunResult, ScoreReport]:
        # Another org's run is KeyError, same as missing -- do not leak existence.
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE org_id = ? AND id = ?", (org_id, run_id)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)

            result_rows = conn.execute(
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

    def get_run_plan(self, org_id: str, run_id: str) -> HarnessPlan | None:
        """The harness plan a run executed, or None for runs launched without a planner."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT plan_json FROM runs WHERE org_id = ? AND id = ?", (org_id, run_id)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return HarnessPlan.model_validate_json(row["plan_json"]) if row["plan_json"] else None

    def score_trend(
        self, org_id: str, *, agent_id: str | None = None, limit: int = 30
    ) -> list[dict]:
        """Score per run over time, oldest first, for a trend line.

        `score_json` is a stored blob rather than a column, so the percentage is
        computed here instead of in SQL. The row count is bounded by `limit`, so
        this stays a small parse rather than a table scan into Python.
        """
        sql = "SELECT id, agent_id, started_at, status, score_json FROM runs WHERE org_id = ?"
        params: list = [org_id]
        if agent_id is not None:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        points = []
        for r in rows:
            score = json.loads(r["score_json"])
            points.append(
                {
                    "run_id": r["id"],
                    "agent_id": r["agent_id"],
                    "started_at": r["started_at"],
                    "status": r["status"],
                    "score": round(score.get("overall_score", 0.0) * 100),
                    "critical_failures": score.get("critical_failures", 0),
                }
            )
        points.reverse()
        return points

    def category_failure_rates(self, org_id: str, *, since: str | None = None) -> list[dict]:
        """Failure rate per test category, worst first.

        Aggregated in SQL rather than by loading runs, because "which category
        breaks most often" is a question about every result this org ever
        recorded, not about the last page of them.
        """
        sql = (
            "SELECT category, "
            "COUNT(*) AS total, "
            "SUM(CASE WHEN status IN ('failed', 'error') THEN 1 ELSE 0 END) AS failed "
            "FROM test_results WHERE org_id = ?"
        )
        params: list = [org_id]
        if since:
            sql += " AND run_id IN (SELECT id FROM runs WHERE org_id = ? AND started_at >= ?)"
            params += [org_id, since]
        sql += " GROUP BY category ORDER BY failed * 1.0 / COUNT(*) DESC, category"
        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "category": r["category"],
                "total": r["total"],
                "failed": r["failed"],
                "rate": (r["failed"] / r["total"]) if r["total"] else 0.0,
            }
            for r in rows
        ]

    def flakiest_tests(self, org_id: str, *, limit: int = 10) -> list[dict]:
        """Tests that fail most often across runs, worst first.

        A test that has only ever run once is not flaky, it is untested, so
        single-run tests are excluded rather than shown at a 100% failure rate.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT test_id, category, "
                "COUNT(*) AS runs, "
                "SUM(CASE WHEN status IN ('failed', 'error') THEN 1 ELSE 0 END) AS failed "
                "FROM test_results WHERE org_id = ? "
                "GROUP BY test_id, category HAVING COUNT(*) > 1 AND failed > 0 "
                "ORDER BY failed * 1.0 / COUNT(*) DESC, failed DESC, test_id LIMIT ?",
                (org_id, limit),
            ).fetchall()
        return [
            {
                "test_id": r["test_id"],
                "category": r["category"],
                "runs": r["runs"],
                "failed": r["failed"],
                "rate": r["failed"] / r["runs"],
            }
            for r in rows
        ]

    def risk_breakdown(self, org_id: str) -> list[dict]:
        """Result counts per risk level, most severe first."""
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT risk, status, COUNT(*) AS n FROM test_results "
                "WHERE org_id = ? GROUP BY risk, status",
                (org_id,),
            ).fetchall()
        by_risk: dict[str, dict] = {}
        for r in rows:
            entry = by_risk.setdefault(r["risk"], {"risk": r["risk"], "total": 0, "failed": 0})
            entry["total"] += r["n"]
            if r["status"] in ("failed", "error"):
                entry["failed"] += r["n"]
        return sorted(by_risk.values(), key=lambda e: order.get(e["risk"], 9))

    def test_history(
        self, org_id: str, test_id: str, *, agent_id: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Every recorded outcome for one test, newest first.

        Answers the question a single run cannot: is this a new break or a
        standing one. Joined against `runs` for the timestamp because
        `test_results` carries no clock of its own.
        """
        sql = (
            "SELECT tr.run_id, tr.status, tr.risk, r.agent_id, r.started_at "
            "FROM test_results tr JOIN runs r ON r.id = tr.run_id AND r.org_id = tr.org_id "
            "WHERE tr.org_id = ? AND tr.test_id = ?"
        )
        params: list = [org_id, test_id]
        if agent_id is not None:
            sql += " AND r.agent_id = ?"
            params.append(agent_id)
        sql += " ORDER BY r.started_at DESC LIMIT ?"
        params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "run_id": r["run_id"],
                "agent_id": r["agent_id"],
                "started_at": r["started_at"],
                "status": r["status"],
                "risk": r["risk"],
            }
            for r in rows
        ]

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
