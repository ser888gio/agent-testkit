"""Browser crawl of the SPA: visit every route, exercise every form.

Opt-in (`-m crawl`), because unlike the rest of the suite this needs a real
browser and a real server. It is the only coverage that exercises the built
bundle the way a user meets it -- `test_web.py` asserts on the JSON API and the
SPA *sources*, so a page that renders those correctly and still throws in the
browser passes there and fails here.

The oracle is deliberately narrower than "no console errors". Every 404 this
app returns is correct behavior with a correct message on screen, so a bare
console-error check would be red on a healthy app. What counts as a finding:

  * an uncaught exception or unhandled rejection
  * a 5xx from any endpoint
  * a 4xx on a route that did *not* render a handled message

The last rule is the interesting one: it catches a request that should never
have been sent, while staying quiet about a 404 the page handles cleanly.
"""

from __future__ import annotations

import os
import re
import socket
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agentaudit.core.config import CallableSpec, TargetConfig
from agentaudit.core.redaction import EvidencePolicy
from agentaudit.core.runner import run
from agentaudit.core.schema import Assertion, Category
from agentaudit.core.schema import TestCase as SchemaTestCase
from agentaudit.core.scoring import score
from agentaudit.core.store import DEFAULT_ORG, Store

pytestmark = pytest.mark.crawl

MODULE = "tests.test_crawl"

# Buttons whose click costs money, mutates shared state, or launches work. The
# crawler fills and submits forms, so without this it would queue runs and spend
# attacker-model calls on every invocation.
DESTRUCTIVE = (
    "delete",
    "remove",
    "abort",
    "cancel",
    "run ",
    "launch",
    "start run",
    "generate",
    "promote",
    "archive",
    "profile agent",
    "save allowlist",
)

# Filled into any free-text input. Carries an XSS payload: if a page renders it
# unescaped, `window.__xss_fired` goes true and the probe reports it.
XSS_PROBE = '<img src=x onerror="window.__xss_fired=true">'

FORM_VALUES = {
    "url": "https://example.invalid/agent",
    "email": "crawler@example.invalid",
    "number": "1",
    "search": "crawl",
}


def agent_for_crawl():
    return lambda input: "ok"


@dataclass
class Finding:
    route: str
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.route}: {self.detail}"


@dataclass
class RouteProbe:
    """What one visited route did, in the terms the oracle judges."""

    route: str
    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    bad_status: list[tuple[str, int]] = field(default_factory=list)
    handled_message: bool = False
    xss_fired: bool = False


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed(db_path: str) -> tuple[str, str]:
    """One completed run, so the :runId / :testId routes resolve to content."""
    cfg = TargetConfig(
        id="crawl-target",
        agent=CallableSpec(type="callable", callable=f"{MODULE}:agent_for_crawl"),
        evidence=EvidencePolicy(),
    )
    test_id = "crawl.seed.case"
    tests = [
        SchemaTestCase(
            id=test_id,
            category=Category.reliability,
            input="hi",
            assertions=[Assertion(name="status_ok")],
        ),
    ]
    result = run(cfg, tests)
    report = score(result)
    Store(db_path).save_run(DEFAULT_ORG, cfg, result, report)
    return result.run_id, test_id


def _serve(port: int):
    import uvicorn

    import agentaudit.web.app as web_app

    config = uvicorn.Config(web_app.app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        if not thread.is_alive():
            raise RuntimeError("server thread died during startup")
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("server did not start within 30s")
    return server, thread


def routes_for(run_id: str, test_id: str) -> list[str]:
    """Every route in App.tsx, plus bogus-id variants that drive error paths.

    A literal list rather than scraped links: several routes are unreachable by
    clicking (the harness page, a 404), so link-following alone would skip them
    silently. `test_every_declared_route_is_crawled` keeps this honest.
    """
    return [
        "/",
        "/welcome",
        "/runs",
        f"/runs/{run_id}",
        f"/runs/{run_id}/harness",
        f"/runs/{run_id}/tests/{test_id}",
        "/agents",
        "/agents/register",
        "/agents/connect",
        "/tests",
        "/tests/new",
        "/generated",
        "/compare",
        "/settings",
        "/runs/no-such-run",
        "/runs/no-such-run/harness",
        "/runs/no-such-run/tests/no-such-test",
        "/agents/no-such-agent",
        "/jobs/no-such-job",
        "/no-such-page",
    ]


def _attach_listeners(page, probes: list[RouteProbe]) -> None:
    def on_console(message):
        if message.type == "error" and probes:
            probes[-1].console_errors.append(message.text)

    def on_page_error(error):
        if probes:
            probes[-1].page_errors.append(str(error))

    def on_response(response):
        if response.status >= 400 and probes:
            probes[-1].bad_status.append((response.url, response.status))

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("response", on_response)


def _handled_message(page) -> bool:
    """True when the page rendered a message rather than blanking or dying."""
    for selector in ("[role=alert]", "h2", ".empty-state"):
        for node in page.query_selector_all(selector):
            if (node.inner_text() or "").strip():
                return True
    return False


def _visit(page, base: str, route: str, probes: list[RouteProbe]) -> RouteProbe:
    probe = RouteProbe(route=route)
    probes.append(probe)
    page.evaluate("() => { window.__xss_fired = false; }")
    page.goto(f"{base}{route}", wait_until="networkidle")
    probe.handled_message = _handled_message(page)
    probe.xss_fired = bool(page.evaluate("() => window.__xss_fired === true"))
    return probe


def _judge(probe: RouteProbe) -> list[Finding]:
    findings: list[Finding] = []
    for error in probe.page_errors:
        findings.append(Finding(probe.route, "uncaught", error))
    if probe.xss_fired:
        findings.append(Finding(probe.route, "xss", "injected payload executed"))
    for url, status in probe.bad_status:
        if status >= 500:
            findings.append(Finding(probe.route, "server-error", f"{status} {url}"))
        elif not probe.handled_message:
            # A 4xx the page absorbed silently: either a request that should
            # never have been sent, or a real error the user is never shown.
            findings.append(Finding(probe.route, "unhandled-4xx", f"{status} {url}"))
    return findings


def _exercise_forms(page, route: str) -> list[Finding]:
    """Fill every input, then submit via the first non-destructive button."""
    findings: list[Finding] = []
    for form in page.query_selector_all("form"):
        for node in form.query_selector_all("input, textarea"):
            kind = (node.get_attribute("type") or "text").lower()
            if kind in ("checkbox", "radio", "file", "hidden", "submit"):
                continue
            if not node.is_editable():
                continue
            try:
                node.fill(FORM_VALUES.get(kind, XSS_PROBE))
            except Exception as exc:  # a field that refuses input is not a defect
                findings.append(Finding(route, "fill-failed", str(exc)))
        submit = None
        for button in form.query_selector_all("button"):
            label = (button.inner_text() or "").strip().lower()
            if any(word in label for word in DESTRUCTIVE):
                continue
            submit = button
            break
        if submit is None:
            continue
        submit.click()
        page.wait_for_timeout(500)
        if not _handled_message(page):
            findings.append(Finding(route, "silent-submit", "submitted with no message rendered"))
    return findings


@pytest.fixture(scope="module")
def crawl_server(tmp_path_factory):
    if not Path("frontend/agentaudit/web/spa_dist/index.html").is_file():
        pytest.skip("spa_dist is unbuilt; run `npm ci && npm run build` in frontend/spa")
    db = str(tmp_path_factory.mktemp("crawl") / "crawl.db")
    # Set before importing agentaudit.web.app: runtime.py reads it at import.
    os.environ["AGENTAUDIT_DB"] = db
    os.environ["AGENTAUDIT_AUTH_MODE"] = "dev"
    run_id, test_id = _seed(db)
    port = _free_port()
    server, thread = _serve(port)
    try:
        yield f"http://127.0.0.1:{port}", run_id, test_id
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="module")
def browser_page(crawl_server):
    api = pytest.importorskip(
        "playwright.sync_api",
        reason="pip install playwright && playwright install chromium",
    )
    with api.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page()
        try:
            yield page
        finally:
            browser.close()


def test_crawl_reports_no_findings(crawl_server, browser_page):
    base, run_id, test_id = crawl_server
    probes: list[RouteProbe] = []
    findings: list[Finding] = []
    _attach_listeners(browser_page, probes)

    for route in routes_for(run_id, test_id):
        probe = _visit(browser_page, base, route, probes)
        findings.extend(_judge(probe))
        before = len(probe.bad_status), len(probe.page_errors)
        form_findings = _exercise_forms(browser_page, route)
        findings.extend(form_findings)
        # Re-judge only what the form interaction added to the same probe.
        after = RouteProbe(
            route=route,
            page_errors=probe.page_errors[before[1] :],
            bad_status=probe.bad_status[before[0] :],
            handled_message=_handled_message(browser_page),
            xss_fired=bool(browser_page.evaluate("() => window.__xss_fired === true")),
        )
        findings.extend(_judge(after))

    assert not findings, "crawl findings:\n" + "\n".join(str(f) for f in findings)


def test_every_declared_route_is_crawled():
    """The route list is hand-maintained; fail when App.tsx grows past it."""
    source = Path("frontend/spa/src/App.tsx").read_text(encoding="utf-8")
    declared = set(re.findall(r'<Route path="([^"]+)"', source))
    covered = set(routes_for("RID", "TID"))
    missing = []
    for path in sorted(declared):
        if path == "*":
            continue
        concrete = (
            path.replace(":runId", "RID").replace(":testId", "TID").replace(":jobId", "no-such-job")
        )
        if concrete == "/agents/*":
            concrete = "/agents/no-such-agent"
        if concrete not in covered:
            missing.append(path)
    assert not missing, f"declared in App.tsx but never crawled: {missing}"
