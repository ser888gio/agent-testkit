# `infra/` — deployment and DB migrations

`Dockerfile`, `docker-compose.yml`, `dev.sh` — see root `CLAUDE.md`. The Docker build copies
the split package roots plus `infra/alembic/` so the installed wheel contains migrations.

## `infra/alembic/` — DB schema migrations

Alembic-managed, raw SQL only — no ORM models, no SQLAlchemy `Table`/`Base` definitions
anywhere in this repo. `env.py` sets `target_metadata` implicitly to none; every revision's
`upgrade()`/`downgrade()` calls `op.execute("...")` with hand-written SQL, matching
`backend/agentaudit/core/store.py`'s existing plain-`sqlite3` style. `store.py` remains the only
runtime DB access point — Alembic only evolves the schema it reads/writes, it does not become
a second way to touch the database.

- Config: root `alembic.ini` → `script_location = infra/alembic`. `sqlalchemy.url` in that
  file is a placeholder; the real target is set per-invocation by
  `backend/agentaudit/cli.py:_alembic_config` from the `agentaudit migrate --db <path>` flag.
- Revisions live in `infra/alembic/versions/`, named `NNNN_description.py` with explicit
  `revision = "NNNN"` (not Alembic's default random hex) so ordering reads the same as the
  filename. `0001_baseline_schema.py` is the first — it mirrors the schema `Store` already
  creates today (`agents`, `runs`, `test_results`), written with `CREATE TABLE IF NOT EXISTS`
  so it's safe to apply to a DB `Store` already initialized directly.
- New revision: `alembic revision -m "<name>"` from the repo root (picks up `alembic.ini`
  automatically), then hand-write `upgrade()`/`downgrade()` following `0001`'s pattern. Or
  copy `0001_baseline_schema.py` and bump the revision id/`down_revision` by hand.
- Apply: `agentaudit migrate --db <path>`. Status: `agentaudit migrate --db <path> --status`
  (lists pending revisions in application order, or prints `up to date`).
- Docker Compose implements the explicit deploy step with a one-shot `migrate` service; the UI
  depends on its successful completion. CLI database options fall back to `AGENTAUDIT_DB`, so the
  Compose `/data/agentaudit.db` volume is used unless `--db` explicitly overrides it.
- Migrations are forward-only in production — applied at deploy time by explicit command,
  never implicitly on app startup, so two replicas booting together can't race.

## Egress policy (T15)

Worker-side environment, deployment-owned. Never derived from target config.

- `AGENTAUDIT_EGRESS_ALLOW_LOCAL=1` relaxes the https requirement and the
  public-address check so a worker can reach a loopback stub. It exists for
  local development against `agentaudit/config/treasury-http.yaml` and must not be
  set on any partner-facing deployment. The per-target host allowlist still
  applies in this mode.
- Secrets reach a run as an explicit interpolation mapping resolved from the
  worker's own environment via the target's `secret_ref` (`env://VAR` today).
  Nothing mutates `os.environ`, so concurrent runs cannot read each other's
  credentials. Provision each `env://VAR` on the worker, not on the web service.
- Workers belong in a network segment with no route to the control-plane
  database or the cloud metadata endpoint. The allowlist is defense in depth,
  not a substitute for that. That segment now exists — see "Worker container
  isolation" below.

## Worker container isolation

The `worker` service in `docker-compose.yml` is the only process that dials an
untrusted third-party endpoint, so the container is treated as the isolation
boundary rather than a deployment convenience.

- **Network.** `worker` is alone on the `egress` network; every other service
  (`agentaudit`, `keycloak`, `keycloak-db`, `migrate`) stays on `default`. The
  worker therefore has no TCP route to the control plane. Verify after any
  compose edit: no other service may join `egress`.
- **Database access is a file, not a route.** The worker reaches SQLite through
  the shared `agentaudit-data` volume. This is what lets it be network-isolated
  and still persist runs — there is no DB server to be routable to. If the store
  ever moves to a networked database, this property is lost and the worker needs
  a write-through API instead of a socket to it.
- **Filesystem/process.** `read_only: true` with a `/tmp` tmpfs, `cap_drop: ALL`,
  `no-new-privileges`, plus `pids_limit`/`mem_limit` as container-level backstops
  to the per-run ceilings in `core/isolation.py`.
- **Secrets.** Provision each target's `secret_ref` (`env://VAR`) on `worker`,
  not on `agentaudit`. The web service never needs a partner credential.

### Known gaps — do not describe these as closed

- **Link-local / cloud metadata (`169.254.169.254`) is not blocked by compose.**
  No network driver blocks it portably. `core/egress.py` rejects it at the app
  layer; an OS-level guarantee requires a host firewall rule on the deployment
  host. This is deployment-operator responsibility.
- **An agent can still reach `isolation.py`'s module globals** via
  `sandbox.__class__` on the RPC proxy. Python resolves class-level dunders
  without calling `__getattr__`, so no guard there can intercept it; the proxy
  refuses only dunders that would be *forwarded* to the supervisor. Pinned by
  `tests/test_isolation.py::test_proxy_class_dunders_are_a_known_isolation_gap`.
  The container boundary is what makes this survivable: escalation buys a
  scratch container, not the host. Closing it needs a proxy with no reachable
  attributes, which is a design change, not another check.

Originally planned as a hand-rolled raw-SQL runner (no Alembic) — the user overrode that
decision during implementation. See the amendment at the end of `docs/plan.md` for why.
