# feat/reports — Spec

**Task 17 · Depends on: 12 · Files:** `agentkit/reports/{__init__.py,json.py,junit.py,html.py,md.py}`,
`tests/test_reports.py`

## Goal
Export a run + scores in formats CI and humans already understand.

## Public API
```python
def to_json(run: RunResult, score: ScoreReport) -> str
def to_junit(run: RunResult, score: ScoreReport) -> str      # JUnit XML
def to_html(run: RunResult, score: ScoreReport) -> str       # self-contained page
def to_markdown(run: RunResult, score: ScoreReport) -> str   # PR-comment friendly
def render(run, score, fmt: Literal["json","junit","html","md"]) -> str
```

## Format contracts
- **JSON**: `{"run": <RunResult>, "score": <ScoreReport>}` — exact model dumps, stable keys.
- **JUnit XML**: one `<testsuite name="agentkit" tests= failures= errors= skipped= time=>`;
  one `<testcase classname="{category}" name="{test_id}" time="{latency_s}">` each;
  `failed` → `<failure message="{first failing assertion detail}"/>`;
  `error` → `<error message="{error}"/>`; `skipped` → `<skipped/>`. Must parse with a standard
  JUnit parser.
- **HTML**: single file, inline CSS, no external assets: score header (overall/pass rate/
  critical), category table, failed tests first with **redacted** request/response.
- **Markdown**: score summary table + a bullet list of failures (`- ❌ {id}: {detail}`),
  suitable to paste as a PR comment.

## Behavior
- Reports consume already-persisted/redacted evidence; they never re-fetch or un-redact.
- Deterministic ordering (failures first, then by id) so golden files are stable.

## Failure behavior
- Unknown `fmt` → `ValueError` listing valid formats.

## Tests required
- Golden-file (or structural) check per format from a fixed `RunResult`+`ScoreReport`.
- JUnit output parses via `xml.etree.ElementTree`; counts match the run.
- HTML contains no `http://`/`https://` external refs (self-contained); shows redacted markers.
- Markdown lists each failure with its detail.

## Done when
A single run exports valid JSON, JUnit XML, self-contained HTML, and Markdown; JUnit is
consumable by a standard CI parser.
