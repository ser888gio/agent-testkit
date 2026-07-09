"""agentkit CLI: run, report, ui."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

# Eagerly import built-in domains so their sandboxes are registered before
# `build_sandbox` is ever called (see docs/notes/errors-and-improvements.md,
# "feat/runner" section, for why this matters).
import agentkit.domains.email.sandbox  # noqa: F401
import agentkit.domains.treasury.sandbox  # noqa: F401
from agentkit.core.config import ConfigError, load_target
from agentkit.core.loader import LoaderError, discover, filter_tests
from agentkit.core.runner import run as run_tests
from agentkit.core.schema import Category
from agentkit.core.scoring import score
from agentkit.core.store import Store
from agentkit.reports import render as render_report

app = typer.Typer(no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo("agentkit 0.1.0")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True
    ),
) -> None:
    pass


def _print_table(rr, report) -> None:
    typer.echo(f"agentkit run - target: {rr.agent_name}   ({len(rr.results)} tests)")
    by_cat: dict[str, dict[str, int]] = {}
    for r in rr.results:
        counts = by_cat.setdefault(r.category.value, {"pass": 0, "fail": 0, "err": 0, "skip": 0})
        counts[{"passed": "pass", "failed": "fail", "error": "err", "skipped": "skip"}[r.status.value]] += 1

    typer.echo(f"{'CATEGORY':<20}{'PASS':>6}{'FAIL':>6}{'ERR':>6}{'SKIP':>6}")
    for cat, counts in sorted(by_cat.items()):
        typer.echo(
            f"{cat:<20}{counts['pass']:>6}{counts['fail']:>6}{counts['err']:>6}{counts['skip']:>6}"
        )
    typer.echo("-" * 44)
    typer.echo(
        f"Overall (weighted): {report.overall_score * 100:.0f}%   "
        f"Pass rate: {report.pass_rate * 100:.0f}%   "
        f"Critical failures: {report.critical_failures}"
    )
    typer.echo(f"Gate: {'PASS' if report.gate_passed else 'BLOCK'}")


@app.command("run")
def run_cmd(
    packs_dir: str = typer.Argument(...),
    target: str = typer.Option(..., "--target"),
    db: str = typer.Option("agentkit.db", "--db"),
    fail_under: float = typer.Option(0.0, "--fail-under"),
    block_on_critical: bool = typer.Option(
        True, "--block-on-critical/--no-block-on-critical"
    ),
    tag: list[str] = typer.Option([], "--tag"),
    category: list[str] = typer.Option([], "--category"),
    format: str = typer.Option("table", "--format"),
) -> None:
    try:
        cfg = load_target(target)
    except (ConfigError, FileNotFoundError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2)

    try:
        tests = discover(packs_dir)
    except LoaderError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2)

    categories = [Category(c) for c in category] if category else None
    tests = filter_tests(tests, tags=tag or None, categories=categories)

    if not tests:
        typer.echo("warning: no tests discovered", err=True)
        raise typer.Exit(2)

    rr = run_tests(cfg, tests)
    report = score(rr, fail_under=fail_under, block_on_critical=block_on_critical)

    store = Store(db)
    store.save_run(cfg, rr, report)

    if format == "json":
        typer.echo(
            json.dumps(
                {
                    "run_id": rr.run_id,
                    "agent_name": rr.agent_name,
                    "overall_score": report.overall_score,
                    "pass_rate": report.pass_rate,
                    "critical_failures": report.critical_failures,
                    "gate_passed": report.gate_passed,
                    "threshold": report.threshold,
                }
            )
        )
    else:
        _print_table(rr, report)

    raise typer.Exit(0 if report.gate_passed else 1)


@app.command("report")
def report_cmd(
    run: str = typer.Option(..., "--run"),
    format: str = typer.Option("json", "--format"),
    out: Optional[str] = typer.Option(None, "--out"),
    db: str = typer.Option("agentkit.db", "--db"),
) -> None:
    store = Store(db)
    try:
        rr, report = store.get_run(run)
    except KeyError:
        typer.echo(f"error: run '{run}' not found", err=True)
        raise typer.Exit(2)

    try:
        content = render_report(rr, report, format)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2)

    if out:
        Path(out).write_text(content, encoding="utf-8")
    else:
        typer.echo(content)


@app.command("ui")
def ui_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    db: str = typer.Option("agentkit.db", "--db"),
) -> None:
    try:
        import uvicorn

        import agentkit.web.app  # noqa: F401
    except ModuleNotFoundError as exc:
        typer.echo(f"error: web UI is not available yet: {exc}", err=True)
        raise typer.Exit(1)

    typer.echo(f"agentkit ui running at http://{host}:{port}")
    uvicorn.run("agentkit.web.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
