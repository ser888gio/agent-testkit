"""Self-contained HTML report: score header + category table + failed-test evidence."""

from __future__ import annotations

import html as _html

from agentaudit.core.findings import is_failure, order_by_failure
from agentaudit.core.schema import RunResult
from agentaudit.core.scoring import ScoreReport
from agentaudit.core.timeline import build as build_timeline
from agentaudit.core.timeline import window as window_timeline

_STYLE = """
body { font-family: sans-serif; margin: 2rem; color: #222; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
td, th { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
.failure { background: #fee; padding: 1rem; margin: 1rem 0; border-left: 4px solid #c00; }
.failure pre { white-space: pre-wrap; word-break: break-word; }
.timeline { list-style: none; padding: 0; margin: 0.5rem 0; }
.timeline li { padding: 0.4rem 0.6rem; border-left: 3px solid #ccc; margin-bottom: 0.25rem; }
.timeline li.diverges { border-left-color: #c00; background: #fff0f0; }
.timeline .events { margin: 0.25rem 0 0 1rem; font-size: 0.85em; color: #555; }
.timeline .omitted { color: #888; font-style: italic; border-left: none; }
"""


def _timeline_section(r) -> str:
    timeline = window_timeline(build_timeline(r))
    if len(timeline["turns"]) < 2:
        return ""

    items = []
    if timeline["omitted_before"]:
        items.append(
            f'<li class="omitted">... {timeline["omitted_before"]} earlier turn(s) omitted ...</li>'
        )
    for turn in timeline["turns"]:
        diverges = turn["index"] == timeline["first_divergence"]
        events_html = "".join(
            f'<li>[{_html.escape(e["kind"])}] {_html.escape(str(e["data"]))}</li>'
            for e in turn["events"]
        )
        events_block = f'<ul class="events">{events_html}</ul>' if events_html else ""
        marker = " &larr; first divergence" if diverges else ""
        items.append(
            f'<li class="{"diverges" if diverges else ""}">'
            f'Turn {turn["index"]}: {_html.escape(turn["input"])}{marker}'
            f"{events_block}</li>"
        )
    if timeline["omitted_after"]:
        items.append(
            f'<li class="omitted">... {timeline["omitted_after"]} later turn(s) omitted ...</li>'
        )
    return f'<h4>Timeline</h4><ol class="timeline">{"".join(items)}</ol>'


def _failure_section(r) -> str:
    return f"""
<div class="failure">
  <h3>{_html.escape(r.test_id)}</h3>
  <p>Category: {_html.escape(r.category.value)} | Status: {_html.escape(r.status.value)}</p>
  <pre>Request: {_html.escape(str(r.request))}</pre>
  <pre>Response: {_html.escape(str(r.response))}</pre>
  {_timeline_section(r)}
</div>"""


def to_html(run: RunResult, score: ScoreReport) -> str:
    ordered = order_by_failure(run.results)

    rows = "".join(
        f"<tr><td>{_html.escape(r.test_id)}</td>"
        f"<td>{_html.escape(r.category.value)}</td>"
        f"<td>{_html.escape(r.status.value)}</td></tr>"
        for r in ordered
    )

    failures = [r for r in ordered if is_failure(r)]
    failure_html = "".join(_failure_section(r) for r in failures) or "<p>None</p>"

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>agentaudit report</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>agentaudit report - {_html.escape(run.agent_name)}</h1>
<p>Overall: {score.overall_score * 100:.0f}% | Pass rate: {score.pass_rate * 100:.0f}% | \
Critical failures: {score.critical_failures} | \
Gate: {"PASS" if score.gate_passed else "BLOCK"}</p>
<h2>Failures</h2>
{failure_html}
<h2>All tests</h2>
<table>
<tr><th>Test</th><th>Category</th><th>Status</th></tr>
{rows}
</table>
</body>
</html>"""
