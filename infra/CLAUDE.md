# `infra/` — deployment and DB migrations

`Dockerfile`, `docker-compose.yml`, `dev.sh` — see root `CLAUDE.md`. The Docker build copies
the split package roots plus `infra/alembic/` so the installed wheel contains migrations.

## `infra/alembic/` — DB schema migrations

Alembic-managed, raw SQL only — no ORM models, no SQLAlchemy `Table`/`Base` definitions
anywhere in this repo. `env.py` sets `target_metadata` implicitly to none; every revision's
`upgrade()`/`downgrade()` calls `op.execute("...")` with hand-written SQL, matching
`backend/agentkit/core/store.py`'s existing plain-`sqlite3` style. `store.py` remains the only
runtime DB access point — Alembic only evolves the schema it reads/writes, it does not become
a second way to touch the database.

- Config: root `alembic.ini` → `script_location = infra/alembic`. `sqlalchemy.url` in that
  file is a placeholder; the real target is set per-invocation by
  `backend/agentkit/cli.py:_alembic_config` from the `agentkit migrate --db <path>` flag.
- Revisions live in `infra/alembic/versions/`, named `NNNN_description.py` with explicit
  `revision = "NNNN"` (not Alembic's default random hex) so ordering reads the same as the
  filename. `0001_baseline_schema.py` is the first — it mirrors the schema `Store` already
  creates today (`agents`, `runs`, `test_results`), written with `CREATE TABLE IF NOT EXISTS`
  so it's safe to apply to a DB `Store` already initialized directly.
- New revision: `alembic revision -m "<name>"` from the repo root (picks up `alembic.ini`
  automatically), then hand-write `upgrade()`/`downgrade()` following `0001`'s pattern. Or
  copy `0001_baseline_schema.py` and bump the revision id/`down_revision` by hand.
- Apply: `agentkit migrate --db <path>`. Status: `agentkit migrate --db <path> --status`
  (lists pending revisions in application order, or prints `up to date`).
- Migrations are forward-only in production — applied at deploy time by explicit command,
  never implicitly on app startup, so two replicas booting together can't race.

Originally planned as a hand-rolled raw-SQL runner (no Alembic) — the user overrode that
decision during implementation. See the amendment at the end of `docs/plan.md` for why.
