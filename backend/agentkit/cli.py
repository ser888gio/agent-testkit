"""agentkit CLI: run, report, ui."""

from __future__ import annotations

import json
import os
from importlib.resources import files
from ipaddress import ip_address
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
from agentkit.core.attacks import expand
from agentkit.core.config import ConfigError, load_target
from agentkit.core.loader import LoaderError, discover, filter_tests
from agentkit.core.regressions import compare
from agentkit.core.runner import run as run_tests
from agentkit.core.schema import Category
from agentkit.core.scoring import score
from agentkit.core.store import DEFAULT_ORG, Store
from agentkit.reports import render as render_report

DEFAULT_DB_PATH = "database/agentkit.db"


def _resolve_db_path(db: str | None) -> str:
    return db or os.environ.get("AGENTKIT_DB", DEFAULT_DB_PATH)


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


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
    db: str | None = typer.Option(None, "--db"),
    fail_under: float = typer.Option(0.0, "--fail-under"),
    block_on_critical: bool = typer.Option(
        True, "--block-on-critical/--no-block-on-critical"
    ),
    tag: list[str] = typer.Option([], "--tag"),
    category: list[str] = typer.Option([], "--category"),
    format: str = typer.Option("table", "--format"),
    compliance: bool = typer.Option(False, "--compliance"),
    attack: str | None = typer.Option(
        None, "--attack", help="Comma-separated attack transforms to expand each test through."
    ),
) -> None:
    db = _resolve_db_path(db)
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

    if attack:
        try:
            tests = expand(tests, [n.strip() for n in attack.split(",") if n.strip()])
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(2) from exc

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
    db: str | None = typer.Option(None, "--db"),
) -> None:
    store = Store(_resolve_db_path(db))
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
    db: str | None = typer.Option(None, "--db"),
) -> None:
    store = Store(_resolve_db_path(db))
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
    db: str | None = typer.Option(None, "--db"),
    status_only: bool = typer.Option(False, "--status"),
) -> None:
    db_path = Path(_resolve_db_path(db))
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


@app.command("purge")
def purge_cmd(
    db: str | None = typer.Option(None, "--db"),
    keep_days: int | None = typer.Option(None, "--keep-days", min=0),
    keep_last: int | None = typer.Option(None, "--keep-last", min=0),
) -> None:
    """Delete runs older than --keep-days and/or beyond the newest --keep-last per agent."""
    if keep_days is None and keep_last is None:
        typer.echo("nothing to do: pass --keep-days and/or --keep-last", err=True)
        raise typer.Exit(2)
    store = Store(_resolve_db_path(db))
    deleted, blob_paths = store.purge_runs(keep_days=keep_days, keep_last=keep_last)
    artifacts_root = Path(os.environ.get("AGENTKIT_ARTIFACTS_DIR", "database/artifacts"))
    removed_blobs = 0
    for rel in blob_paths:
        blob = (artifacts_root / rel).resolve()
        # Rows are written by save_artifact with relative keys; anything that
        # escapes the root is corrupt data, not a delete instruction.
        if blob.is_relative_to(artifacts_root.resolve()) and blob.is_file():
            blob.unlink()
            removed_blobs += 1
    typer.echo(f"purged {deleted} runs, {removed_blobs} artifact blobs")


@app.command("worker")
def worker_cmd(
    db: str | None = typer.Option(None, "--db"),
    poll_seconds: float = typer.Option(1.0, "--poll-seconds"),
    lease_seconds: int = typer.Option(120, "--lease-seconds"),
    max_per_org: int = typer.Option(2, "--max-per-org"),
) -> None:
    """Run the job worker until interrupted. Same image as `ui`, different command."""
    from agentkit.worker import main as worker_main

    worker_main(
        _resolve_db_path(db),
        poll_seconds=poll_seconds,
        lease_seconds=lease_seconds,
        max_per_org=max_per_org,
    )


@app.command("ui")
def ui_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    db: str | None = typer.Option(None, "--db"),
) -> None:
    try:
        import uvicorn

        mode = os.environ.get("AGENTKIT_AUTH_MODE", "").strip().lower()
        if not mode:
            if not _is_loopback_host(host):
                typer.echo(
                    "error: public UI binding requires AGENTKIT_AUTH_MODE=oidc",
                    err=True,
                )
                raise typer.Exit(1)
            os.environ["AGENTKIT_AUTH_MODE"] = "dev"
        elif mode == "dev" and not _is_loopback_host(host):
            typer.echo("error: dev authentication is loopback-only", err=True)
            raise typer.Exit(1)

        os.environ["AGENTKIT_DB"] = _resolve_db_path(db)
        import agentkit.web.app as web_app

        web_app.auth_enabled()
    except ModuleNotFoundError as exc:
        typer.echo(f"error: web UI is not available yet: {exc}", err=True)
        raise typer.Exit(1) from exc
    except RuntimeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"agentkit ui running at http://{host}:{port}")
    uvicorn.run("agentkit.web.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
