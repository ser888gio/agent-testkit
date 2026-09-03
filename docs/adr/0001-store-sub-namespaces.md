# ADR-0001: `Store` keeps one module and grows sub-namespaces, not sibling modules

- **Status:** accepted
- **Date:** 2026-09-03
- **Affects:** `backend/agentaudit/core/store.py`, `.claude/rules/dependency-boundaries.md`

## Context

`CLAUDE.md` and `.claude/rules/dependency-boundaries.md` state a hard rule:

> SQLite is reached only through `core/store.py:Store`. No other module opens
> the database or issues SQL.

The rule is load-bearing. It is what makes org scoping auditable: every query
that could cross a tenant boundary is in one file, and `tests/test_store.py`
can assert that every public method takes `org_id` first.

`Store` had also grown to 1,503 lines and roughly forty public methods
spanning three unrelated jobs: persisting evidence, holding tenant
configuration, and answering reporting questions about accumulated runs. A
caller that only needed a score trend was handed an object that could also
`save_run`, `delete_target` and `purge_runs`.

The obvious reading of "the file is too long" is to split it into
`core/store.py`, `core/analytics.py`, `core/targets.py`. That reading is
wrong here, and this ADR exists so the next architecture review does not
re-propose it.

## Decision

`Store` stays one module. Cohesive groups of its methods move into small
classes **inside `store.py`**, reached as attributes of a `Store` instance:

- `store.jobs` — `JobQueue` (pre-existing; this ADR records the pattern it set)
- `store.analytics` — `Analytics`, the six read-only reporting queries

Each sub-namespace takes the `Store` in its constructor and borrows its
connection pool. There is still exactly one `_SQLitePool` per process and
exactly one file containing SQL.

## Consequences

**Good.** A caller handed `store.analytics` can read rollups and cannot reach
`save_run`; the interface starts carrying intent. The grep that enforces the
boundary (`no other module opens the database`) stays a one-file grep. The
tenancy guard in `tests/test_store.py` extends to each new namespace by adding
it to one parametrize list, and derives its method set so a newly added method
is checked by default.

**Bad.** `store.py` keeps growing. That is accepted: file length is a cost we
can read, whereas a second module issuing SQL is a rule we would have to
enforce with a linter we do not have. `JobQueue`'s own docstring already made
this trade explicitly — *"moving the SQL out to buy a shorter file would trade
a rule that is enforced for one that is not."*

**Deferred.** Tenant configuration (targets, secret refs, allowlists, profiles,
LLM settings — roughly twelve methods) is the obvious next namespace,
`store.targets`. It was not done alongside `analytics` because it has call
sites in the worker, the CLI, the web API and `core/intake.py`, and three
feature branches were touching those files at the time. It is mechanical when
those land.

## Alternatives considered

**Separate modules per concern.** Rejected: it breaks the single documented
SQL boundary, which is the property the rule buys us, in exchange for shorter
files, which is not.

**A repository interface with per-concern implementations.** Rejected as
speculative. There is one backend (SQLite) and no second one planned; an
interface with a single implementation is a hypothetical seam, not a real one.

**Leave `Store` flat.** Rejected: forty undifferentiated methods is an
interface far larger than any caller needs, and `JobQueue` had already
demonstrated the alternative reads better.
