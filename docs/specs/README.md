# agentaudit branch specs

One spec per feature branch. Each is a **self-contained contract** an implementer can pick
up cold: public API, data models/formats, lifecycle, failure behavior, worked examples,
required tests, and an observable definition of done. Read your branch's spec together with
[`../plan.md`](../plan.md) and the historical planning notes in
[`../archive/plans/`](../archive/plans/).

Every spec follows the same shape:

- **Goal** — one sentence.
- **Public API** — exact signatures other branches import.
- **Data models / formats** — fields, types, YAML/JSON examples.
- **Behavior** — lifecycle / algorithm, ordering, edge cases.
- **Failure behavior** — what happens on bad input, exceptions, timeouts.
- **Examples** — concrete input → output.
- **Tests required** — the cases that must be green.
- **Done when** — observable CLI/UI/return behavior, not "code exists".

## Cross-branch conventions (authoritative)

- **Python** 3.10+. **Pydantic v2** for all models (`model_dump`, `model_validate`).
- **IDs** are dotted lowercase: `treasury.unapproved_payment.blocked`.
- **Enums** (defined in `feat/schema`, imported everywhere):
  - `Category`: `endpoint_contract, prompt_injection, data_leakage, instruction_following,
    action_safety, tool_use, memory_context, reliability, performance`.
  - `Risk`: `low, medium, high, critical`.
  - `Status`: `passed, failed, error, skipped`.
- **No secrets in files.** Configs use `${ENV_VAR}` interpolation; evidence is redacted
  before persistence (`feat/redaction`).
- **Runs never crash.** A failing/erroring test is recorded, not raised; the run continues.
- **Timestamps** are timezone-aware UTC ISO-8601 strings.
- **Money** amounts are integers in minor units (cents) to avoid float drift.

## Index

| # | Branch | Spec |
|---|--------|------|
| 1 | `feat/schema` | [schema.md](schema.md) |
| 2 | `feat/redaction` | [redaction.md](redaction.md) |
| 3 | `feat/config` | [config.md](config.md) |
| 4 | `feat/agent-adapter` | [agent-adapter.md](agent-adapter.md) |
| 5 | `feat/http-verify` | [http-verify.md](http-verify.md) |
| 6 | `feat/sandbox-core` | [sandbox-core.md](sandbox-core.md) |
| 7 | `feat/sandbox-treasury` | [sandbox-treasury.md](sandbox-treasury.md) |
| 8 | `feat/sandbox-email` | [sandbox-email.md](sandbox-email.md) |
| 9 | `feat/assertions` | [assertions.md](assertions.md) |
| 10 | `feat/test-loader` | [test-loader.md](test-loader.md) |
| 11 | `feat/runner` | [runner.md](runner.md) |
| 12 | `feat/scoring` | [scoring.md](scoring.md) |
| 13 | `feat/store` | [store.md](store.md) |
| 14 | `feat/test-packs-core` | [test-packs-core.md](test-packs-core.md) |
| 15 | `feat/test-packs-domain` | [test-packs-domain.md](test-packs-domain.md) |
| 16 | `feat/cli` | [cli.md](cli.md) |
| 17 | `feat/reports` | [reports.md](reports.md) |
| 18 | `feat/web-ui` | [web-ui.md](web-ui.md) |
| 19 | `feat/regressions` | [regressions.md](regressions.md) |
| 20 | `feat/docs-demo` | [docs-demo.md](docs-demo.md) |
| 21 | `feat/attacker` | [attacker.md](attacker.md) |
| 22 | `feat/judge` | [judge.md](judge.md) |
| 23 | `feat/evolve` | [evolve.md](evolve.md) |
