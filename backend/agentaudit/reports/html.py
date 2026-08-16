"""Self-contained HTML report: score header + category table + failed-test evidence."""

from __future__ import annotations

import html as _html

from agentaudit.core.schema import RunResult, Status
from agentaudit.core.scoring import ScoreReport

_FAILURE_RANK = {Status.failed: 0, Status.error: 0, Status.passed: 1, Status.skipped: 2}

_STYLE = """
body { font-family: sans-serif; margin: 2rem; color: #222; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
td, th { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
.failure { background: #fee; padding: 1rem; margin: 1rem 0; border-left: 4px solid #c00; }
.failure pre { white-space: pre-wrap; word-break: break-word; }
"""


def _failure_section(r) -> str:
    return f"""
<div class="failure">
  <h3>{_html.escape(r.test_id)}</h3>
  <p>Category: {_html.escape(r.category.value)} | Status: {_html.escape(r.status.value)}</p>
  <pre>Request: {_html.escape(str(r.request))}</pre>
  <pre>Response: {_html.escape(str(r.response))}</pre>
</div>"""


def to_html(run: RunResult, score: ScoreReport) -> str:
    ordered = sorted(
        run.results, key=lambda r: (_FAILURE_RANK.get(r.status, 1), r.test_id)
    )

    rows = "".join(
        f"<tr><td>{_html.escape(r.test_id)}</td>"
        f"<td>{_html.escape(r.category.value)}</td>"
        f"<td>{_html.escape(r.status.value)}</td></tr>"
        for r in ordered
    )

    failures = [r for r in ordered if r.status in (Status.failed, Status.error)]
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
