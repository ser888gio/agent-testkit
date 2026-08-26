# Tiered Gating & Flake Quarantine — Design Note

**PRD-004 · Status: draft · Characterization baseline:** `tests/test_scoring_tiers.py`

## Goal

Stop eval CI from being "an expensive random number generator": let operators
declare which tests block merges and which only report, and give persistently
flaky tests a visible, expiring quarantine instead of inviting rerun-until-green.

## Baseline (today, pinned by characterization tests)

`core/scoring.py::score` computes one undifferentiated gate:

- `overall_score` is risk-weighted (`low=1, medium=2, high=4, critical=8`);
- `gate_passed = overall_score >= fail_under and not
  (block_on_critical and critical_failures > 0)`;
- an empty or all-skipped run **fails closed** — `gate_passed=False`,
  `incomplete=True`, zero scores (see `scoring.py:74-88`, MERGED-PLAN §0a);
- pass^k attempts folded by `runner._fold_attempts` surface as `flaky`
  (count of results whose `attempts` disagree); it never moves the gate;
- `weak_category_score` / `weakest_category` report the worst quartile category,
  explicitly reported but never gated on.

Default mode must remain exactly this: everything blocking. Tiers are opt-in.

## Design

### Tier declaration

Run/target YAML gains a `gating:` section, parsed and validated by
`core/config.py` alongside `TargetConfig` (same `${ENV_VAR}` interpolation and
`ConfigError` discipline). Shape:

```yaml
gating:
  blocking_categories: [action_safety, prompt_injection]   # default: all
  reporting_categories: [performance, reliability]          # opt-in carve-out
```

Unknown categories, or a category in both lists, is a config error at load
time. Absent section = today's behavior (all blocking).

### Gate computation placement

The gate verdict moves into `scoring.score` behind an explicit tiered mode
(e.g. `tiers=` parameter), so every consumer — CLI exit code, worker, reports —
derives the gate from one place and none re-derive it. In tiered mode:

- failures in `blocking` categories fail the gate exactly as today;
- failures in `reporting` categories lower scores and appear in reports but
  can never flip `gate_passed` to false on their own;
- **fail-closed semantics are preserved unchanged**: an empty/all-skipped run
  fails the gate regardless of tier configuration — no evidence, no green gate;
- `block_on_critical` continues to apply to critical-risk failures wherever
  they appear (see invariant below).

### Quarantine

New store table (Alembic migration `infra/alembic/versions/00NN_quarantine.py`,
following the existing `00NN_name.py` convention):

```sql
CREATE TABLE quarantines (
    id          TEXT PRIMARY KEY,
    org_id      TEXT NOT NULL,
    test_id     TEXT NOT NULL,      -- or category-level scope; see open questions
    reason      TEXT NOT NULL,
    owner       TEXT NOT NULL,
    created_at  TEXT NOT NULL,      -- ISO-8601 UTC
    expires_at  TEXT NOT NULL       -- required, never null
);
```

A quarantined test automatically moves to the reporting tier for runs whose
plan is computed while the quarantine is live. Expiry is enforced at plan/load
time (`planner.plan` / plan application): expired quarantines are ignored and
the test returns to its configured tier. Quarantines surface prominently in
reports (`reports/{json,junit,md,html}.py`) and the dashboard — visible, not
silent.

### The critical invariant

A still-failing CRITICAL safety test can never be quarantined away from
blocking. Concretely: quarantine moves a test toward reporting, but any result
with `risk == critical` that fails still counts as a critical failure and still
blocks via `block_on_critical`. This mirrors `evolve`'s rule of never retiring
a still-failing critical test. Enforced in `score` itself, not in callers, so
no config mistake or dashboard path can route around it.

## Open questions (from the PRD)

- Should `flaky` folded outcomes in the blocking tier warn-only or hard-fail
  when attempts are exhausted?
- Dashboard UX for quarantine creation — reuse the generated-test review UI
  patterns?

## Tests required

- `tests/test_scoring.py` — tiered gating incl. fail-closed preservation.
- `tests/test_store.py` — quarantine CRUD/expiry.
- `tests/test_web.py` — dashboard endpoints authz.
- `tests/test_scoring_tiers.py` — this PRD's first step: characterization
  baselines pinning current single-tier behavior before any change.
