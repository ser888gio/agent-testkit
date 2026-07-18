# Using Claude Code in this repository

How the Claude Code setup here is wired, and how to get useful work out of it. For the
instructions Claude itself reads, see [`../CLAUDE.md`](../CLAUDE.md).

## Where to start a session

Start Claude Code from the **repository root** for almost everything. The package is a
namespace package assembled from `./agentkit`, `./backend`, and `./frontend`, so a change
that looks local usually is not — editing `core/schema.py` ripples into `reports/`,
`web/app.py`, and the YAML packs.

Start from a subdirectory only when the work is genuinely contained: authoring YAML packs
(`agentkit/packs/`) or iterating on dashboard templates
(`frontend/agentkit/web/`). You still get the root `CLAUDE.md` plus that directory's own.

For cross-component work spanning directories, stay at the root rather than adding
directories — the whole repo is small enough that root context is cheap.

## Instruction hierarchy

Claude reads these together, most general first:

1. `CLAUDE.md` (root) — overview, commands, architecture rules, working rules
2. Directory `CLAUDE.md` — local rules that differ from the root:
   - `backend/agentkit/core/` — the trust-sensitive engine
   - `backend/agentkit/domains/` — adding a vertical
   - `frontend/agentkit/web/` — the dashboard
   - `agentkit/packs/` — test content authoring
   - `tests/` — suite conventions
3. `.claude/rules/*.md` — path-scoped rules that activate for matching files:
   `generated-files`, `security-sensitive`, `dependency-boundaries`, `test-packs`

Keep each layer non-duplicative. If a rule is true everywhere, it belongs in the root file;
if it only matters for one tree, it belongs in that tree's file or a path rule.

## Subagents

Defined in `.claude/agents/`. All are read-only except where noted; they exist to keep
high-volume searching out of the main conversation's context.

| Agent | Use it for |
| --- | --- |
| `architecture-explorer` | entry points, runtime flow, which module owns what |
| `dependency-tracer` | consumers of a symbol, blast radius before a contract change |
| `test-finder` | existing tests, the pattern to copy, the narrowest command to run |
| `code-reviewer` | reviewing a diff before you call it done |

The three discovery agents run on a faster model since their work is mechanical;
`code-reviewer` uses a stronger one because judgement matters there.

Ask for them explicitly ("use dependency-tracer to find everything that reads
`TestResult.sandbox_diff`"). They are most valuable before a change to `core/schema.py`,
`core/config.py`, or the assertion registry, where the consumer list includes YAML packs
and Jinja templates that no Python tool will find for you.

## Workflows

Slash commands in `.claude/commands/`:

- `/explore <thing>` — trace how something works. Does not edit.
- `/plan <change>` — turn findings into the smallest viable plan. Does not edit.
- `/implement` — execute an approved plan, staying in scope.
- `/review` — review the diff independently.

The intended loop is explore → plan → **read the plan yourself** → implement → review. The
plan step is where you catch a misunderstanding cheaply; skipping it usually costs more than
it saves on anything touching `core/`.

## Affected validation

```bash
bash tools/affected.sh              # what changed, which components, which tests
bash tools/validate.sh --affected   # lint changed files + run affected tests
bash tools/validate.sh              # lint changed files + full suite (default)
bash tools/validate.sh --lint-all   # lint everything (currently red, see below)
```

`affected.sh` maps changed files to components and pytest targets by convention
(`tests/test_<module>.py` ↔ module). It includes untracked files, and escalates to the full
suite when a contract file (`schema.py`, `config.py`, `assertions.py`) or build config
changes. Use `--base <ref>` to scope against a branch point.

The full suite is 174 tests in about 2.5 seconds, so `--affected` is a convenience for tight
loops, not a necessary optimization. Run the default before finishing.

### Environment caveats

- `uv run` currently fails on Windows (`package directory 'frontend\agentkit\config' does
  not exist`) — a setuptools multi-root namespace issue, reproducible on a clean checkout.
  CI on Linux is unaffected. Use `python -m pytest`, or `tools/validate.sh`, which probes
  for a runner that actually works.
- The repo has ~15 pre-existing ruff violations and CI does not run ruff. `validate.sh`
  lints only changed files so this backlog does not mask new problems. Cleaning it up is
  worthwhile follow-up work.

## Hooks

`.claude/settings.json` configures:

- **PreToolUse** → `tools/guard-protected-paths.sh` blocks edits to generated and vendored
  paths (`dist/`, `uv.lock`, `agentkit.db`, `__pycache__/`, `docs/diagrams/*.svg`,
  `agentkit.egg-info/`, `.venv/`) and prints how to regenerate each. It fails open, so a
  malformed payload never blocks ordinary work.
- **PostToolUse** → `aislop hook claude`, the pre-existing code-quality scan.

## Session hygiene

Start a **fresh session** when you switch tasks. Context from an unrelated investigation
makes the model likelier to "helpfully" touch files outside the current change, which is the
main way scope creep enters this repo. One task per session; the explore/plan/implement/
review loop is designed to fit in one.

Start fresh also after a long debugging detour, even on the same task — once the transcript
is full of dead ends, a clean session given the conclusion outperforms one carrying the
whole search.

## Keeping the architecture map current

`docs/components.yaml` is the machine-readable component map: paths, import paths, ownership,
dependencies, contracts, and validation commands. Update it when you:

- add or remove a component (a new vertical under `domains/`, a new report renderer)
- change a dependency direction or add a cross-component import
- move an entry point
- change the validation command for a component

Relationships that could not be verified from an import statement are marked
`inferred: true` — the `packs` and `infra` entries depend by string reference and runtime
invocation, not imports. Preserve that distinction when editing; an unmarked relationship is
a claim that an import proves it.
