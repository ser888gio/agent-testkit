"""agentkit CLI: run, report, ui."""

from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path

import typer
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

# Eagerly import built-in domains so their sandboxes are registered before
# `build_sandbox` is ever called (see docs/notes/errors-and-improvements.md,
# "feat/runner" section, for why this matters).
import agentkit.domains.email.sandbox  # noqa: F401
import agentkit.domains.treasury.sandbox  # noqa: F401
from agentkit.core.config import ConfigError, load_target
from agentkit.core.loader import LoaderError, discover, filter_tests
from agentkit.core.regressions import compare
from agentkit.core.runner import run as run_tests
from agentkit.core.schema import Category
from agentkit.core.scoring import score
from agentkit.core.store import DEFAULT_ORG, Store
from agentkit.reports import render as render_report


def _alembic_config(db_path: Path) -> AlembicConfig:
    cfg = AlembicConfig()
    try:
        migration_package = files("agentkit.migrations")
    except ModuleNotFoundError:
        migration_package = Path(__file__).resolve().parents[2] / "infra" / "alembic"
    cfg.set_main_option("script_location", str(migration_package))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


def _pending_migrations(cfg: AlembicConfig) -> list[tuple[str, str]]:
    scripts = ScriptDirectory.from_config(cfg)
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    try:
        with engine.connect() as connection:
            current_heads = MigrationContext.configure(connection).get_current_heads()
    finally:
        engine.dispose()

    pending = list(scripts.iterate_revisions(scripts.get_heads(), current_heads))
    return [(revision.revision, revision.doc or "") for revision in reversed(pending)]

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
        counts = by_cat.setdefault(
            r.category.value, {"pass": 0, "fail": 0, "err": 0, "skip": 0}
        )
        counts[
            {"passed": "pass", "failed": "fail", "error": "err", "skipped": "skip"}[
                r.status.value
            ]
        ] += 1

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
    db: str = typer.Option("database/agentkit.db", "--db"),
    fail_under: float = typer.Option(0.0, "--fail-under"),
    block_on_critical: bool = typer.Option(
        True, "--block-on-critical/--no-block-on-critical"
    ),
    tag: list[str] = typer.Option([], "--tag"),
    category: list[str] = typer.Option([], "--category"),
    format: str = typer.Option("table", "--format"),
    compliance: bool = typer.Option(False, "--compliance"),
) -> None:
    try:
        cfg = load_target(target)
    except (ConfigError, FileNotFoundError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    try:
        tests = discover(packs_dir)
    except LoaderError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    categories = [Category(c) for c in category] if category else None
    tests = filter_tests(tests, tags=tag or None, categories=categories)

    if not tests:
        typer.echo("warning: no tests discovered", err=True)
        raise typer.Exit(2)

    rr = run_tests(cfg, tests)
    report = score(rr, fail_under=fail_under, block_on_critical=block_on_critical)

    store = Store(db)
    store.save_run(DEFAULT_ORG, cfg, rr, report)

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

    if compliance:
        typer.echo("")
        typer.echo(render_report(rr, report, "compliance"))

    raise typer.Exit(0 if report.gate_passed else 1)


@app.command("report")
def report_cmd(
    run: str = typer.Option(..., "--run"),
    format: str = typer.Option("json", "--format"),
    out: str | None = typer.Option(None, "--out"),
    db: str = typer.Option("database/agentkit.db", "--db"),
) -> None:
    store = Store(db)
    try:
        rr, report = store.get_run(DEFAULT_ORG, run)
    except KeyError as exc:
        typer.echo(f"error: run '{run}' not found", err=True)
        raise typer.Exit(2) from exc

    try:
        content = render_report(rr, report, format)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if out:
        Path(out).write_text(content, encoding="utf-8")
    else:
        typer.echo(content)


@app.command("compare")
def compare_cmd(
    run_a: str = typer.Argument(...),
    run_b: str = typer.Argument(...),
    db: str = typer.Option("database/agentkit.db", "--db"),
) -> None:
    store = Store(db)
    try:
        before, before_score = store.get_run(DEFAULT_ORG, run_a)
        after, after_score = store.get_run(DEFAULT_ORG, run_b)
    except KeyError as exc:
        typer.echo(f"error: run {exc} not found", err=True)
        raise typer.Exit(2) from exc

    diff = compare(before, after, before_score, after_score)

    typer.echo(f"agentkit compare - {run_a[:8]} -> {run_b[:8]}")
    if diff.critical_regressions:
        typer.echo(f"CRITICAL REGRESSIONS: {', '.join(diff.critical_regressions)}")
    typer.echo(
        f"Newly failing ({len(diff.newly_failing)}): {', '.join(diff.newly_failing)}"
    )
    typer.echo(
        f"Newly passing ({len(diff.newly_passing)}): {', '.join(diff.newly_passing)}"
    )
    typer.echo(f"Added: {', '.join(diff.added)}")
    typer.echo(f"Removed: {', '.join(diff.removed)}")
    typer.echo(
        f"Score delta - overall: {diff.score_delta['overall']:+.2%}  "
        f"pass_rate: {diff.score_delta['pass_rate']:+.2%}"
    )

    raise typer.Exit(1 if diff.critical_regressions else 0)


@app.command("migrate")
def migrate_cmd(
    db: str = typer.Option("database/agentkit.db", "--db"),
    status_only: bool = typer.Option(False, "--status"),
) -> None:
    db_path = Path(db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = _alembic_config(db_path)
    if status_only:
        pending = _pending_migrations(cfg)
        if not pending:
            typer.echo("up to date")
            return
        for revision, name in pending:
            typer.echo(f"pending {revision}: {name}")
    else:
        alembic_command.upgrade(cfg, "head")


@app.command("ui")
def ui_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    db: str = typer.Option("database/agentkit.db", "--db"),
) -> None:
    try:
        import uvicorn

        os.environ["AGENTKIT_DB"] = db
        import agentkit.web.app  # noqa: F401
    except ModuleNotFoundError as exc:
        typer.echo(f"error: web UI is not available yet: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"agentkit ui running at http://{host}:{port}")
    uvicorn.run("agentkit.web.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
