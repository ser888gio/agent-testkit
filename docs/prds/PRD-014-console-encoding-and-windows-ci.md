# PRD-014 — Console encoding correctness and a Windows CI lane

**Type:** Fix · **Status:** Fix implemented (`fix/md-report-windows-encoding`); CI lane proposed

## Problem
`agentaudit report --run <id> --format md` exited **1** with an unhandled traceback on a
Windows console:

```
UnicodeEncodeError: 'charmap' codec can't encode character '❌' in position 146
```

`reports/md.py:46,48` emit `❌`; `typer.echo` inherited the console cp1252 codepage.

Three properties made this survive to `develop`:

1. **Only the failure path emits the emoji.** A green run never crashes — so every demo,
   quickstart, and happy-path check looked fine. It broke exactly when a safety test failed,
   i.e. the only time the report matters.
2. **`--out FILE` never crashed** (`cli.py:495` writes UTF-8 explicitly), so file-based use
   masked it.
3. **`CliRunner` captures in-process** and never touches the console codec, so
   `tests/test_cli.py` could not catch it.

Markdown is the **PR-comment** format — the one CI pipes to stdout. The README documents a
Windows *pytest* quirk but not this.

The generalizable defect: **Windows is the maintainer's daily driver and CI is Linux**, so
console-encoding bugs are invisible to both. Any future non-ASCII in console output has the
same blind spot. Verified on `develop` 2026-08-27
([assessment-addendum.md §Finding 1](evaluation/assessment-addendum.md)).

## Proposed solution
**Done** — `_force_utf8_stdio()` reconfigures `sys.stdout`/`sys.stderr` to UTF-8
(`errors="replace"`) in the Typer `@app.callback()`, so every subcommand is covered rather
than just this one report format. Tolerates streams without `.reconfigure` (pytest capture,
wrapped CI runners). Two regression tests in `tests/test_cli.py`; 44 tests pass, ruff clean.

**Remaining (the part that stops recurrence):**
- Add a **Windows job to CI** running at least `tests/test_cli.py` and one
  `report --format md` on a run *with failures*, under a legacy codepage (`chcp 1252`).
  Without this, the class of bug returns.
- Consider whether report glyphs should be ASCII-safe at source. UTF-8 stdout is the right
  fix; an ASCII fallback for genuinely legacy pipes is a smaller, separate question.

## Success criteria
- `report --format md` on a failing run exits 0 and renders on a cp1252 console. **(Met.)**
- Regression tests cover both the reconfigure call and the no-`reconfigure` stream. **(Met.)**
- CI has a Windows lane exercising console output of a failing run; it fails if a future
  change reintroduces an unencodable glyph on stdout. *(Open.)*
- README's Limits section drops or updates any claim implying Windows issues are confined to
  pytest invocation.

## Priority & effort
**P0** for the fix (a documented command crashed on the maintainer's own platform, in the
failure case, in the format CI consumes) · **P1** for the Windows CI lane ·
**Effort: S** (fix done) + **S** (CI lane)

## Open questions
- Windows CI on every PR, or nightly only (runner-minute cost)?
- Any other non-ASCII on stdout? (`reports/md.py` was the only `grep` hit for `❌`/`✅`, but
  the dashboard and compliance renderers deserve a sweep.)
- Should `--out` remain the documented path for CI, with stdout best-effort?
