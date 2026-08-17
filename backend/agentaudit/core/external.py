"""Spawn promptfoo/garak, collect the report, hand it to the adapter.

`adapters.py` maps foreign reports into `TestResult`s and generates the config
and argv each tool needs. This module is the missing middle: it runs the tool.
Until it existed, a plan could select `promptfoo.pii`, rank it, and persist that
selection next to a run holding no evidence for it -- coverage on paper only.

Three properties this module owes, none of them optional:

1. **Bounded.** An external scan is minutes-to-hours of traffic against a
   partner endpoint. Every spawn carries a wall-clock timeout and is killed by
   process tree, not by `Popen.kill`, which orphans the children a Node or
   Python launcher spawns.
2. **Never fatal.** A missing binary, a timeout, or a garbage report becomes an
   `ExternalRunError` that the caller turns into evidence. Same contract as
   `runner.py`: the absence of a result is itself a finding, never a traceback.
3. **Honest about egress.** See `ExternalRunError` and the note on
   `run_external` -- the pinning that `core/agent.py` applies in-process cannot
   be extended to a child that resolves the hostname itself.

No `httpx` here: this module spawns, it does not dial.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from agentaudit.core.adapters import ExternalEvalAdapter
from agentaudit.core.egress import ValidatedEndpoint
from agentaudit.core.profile import AgentProfile
from agentaudit.core.redaction import EvidencePolicy, Redactor
from agentaudit.core.schema import TestResult

# An external scan is long by nature; this is a ceiling, not a target.
DEFAULT_TIMEOUT_S = 900.0


class ExternalRunError(Exception):
    """The tool could not produce a usable report.

    Carries the reason so a caller can record *why* a selected test produced no
    evidence. "garak is not installed" and "garak ran for 15 minutes and was
    killed" are different findings, and collapsing them into a silent skip is
    how a scan overstates its own coverage.
    """


@dataclass(frozen=True)
class ExternalRun:
    """One completed external tool invocation."""

    tool: str
    results: list[TestResult]
    argv: list[str]
    returncode: int
    duration_s: float
    started_at: datetime

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status.value == "failed")


def _kill_tree(process: subprocess.Popen) -> None:
    """Kill the process and everything it spawned.

    `promptfoo` is a Node launcher and `garak` a Python one; both fork children
    that outlive a plain `kill()` on the parent and keep hitting the partner
    endpoint after we have stopped reading. Mirrors the process-tree teardown in
    `core/isolation.py`.
    """
    if process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), 9)
    except (OSError, subprocess.SubprocessError):
        # Best effort: the process may have exited between poll and kill.
        process.kill()
    finally:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def _spawn(argv: Sequence[str], *, cwd: Path, timeout_s: float, env: dict[str, str] | None):
    """Run argv to completion under a wall-clock ceiling, killing the tree on overrun."""
    # Resolve to the absolute path `which` found: on Windows a bare name that
    # maps to a .cmd/.bat shim is not directly executable by CreateProcess, and
    # resolving once also pins which binary we launch.
    executable = shutil.which(argv[0])
    if executable is None:
        raise ExternalRunError(f"{argv[0]} is not installed on this runner")

    # start_new_session puts the child in its own process group so the whole
    # tree can be signalled at once. Windows gets the taskkill path instead.
    popen_kwargs = {"start_new_session": True} if sys.platform != "win32" else {}
    try:
        process = subprocess.Popen(  # noqa: S603 - argv is adapter-generated, never shell
            [executable, *list(argv)[1:]],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            **popen_kwargs,
        )
    except OSError as exc:
        raise ExternalRunError(f"could not start {argv[0]}: {exc}") from exc

    try:
        _, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        _kill_tree(process)
        raise ExternalRunError(
            f"{argv[0]} exceeded its {timeout_s:.0f}s budget and was killed"
        ) from exc
    return process.returncode, stderr or ""


def _redacted_stderr(stderr: str, limit: int = 500) -> str:
    """Tool stderr can echo the prompt it just sent, so it is evidence too."""
    return Redactor(EvidencePolicy().redact).redact(stderr.strip()[-limit:])


def run_external(
    adapter: ExternalEvalAdapter,
    profile: AgentProfile,
    endpoint: ValidatedEndpoint,
    *,
    evidence: EvidencePolicy | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    workdir: Path | None = None,
    env: dict[str, str] | None = None,
) -> ExternalRun:
    """Run one external tool against a validated endpoint and normalize its report.

    **Egress caveat, deliberately not hidden.** `endpoint` must already have
    passed `validate_endpoint`, which is what authorizes the host and proves it
    resolved public at run start. But the child process is handed a URL and
    resolves the name *itself*, so it does not inherit `pinned_url`/SNI pinning
    the way `core/agent.py` does in-process. The allowlist and the
    resolve-time check still apply; the rebinding window between our check and
    the tool's own lookup does not close. Treat an external scan as a weaker
    egress guarantee than a native run, and do not describe it otherwise.
    """
    evidence = evidence or EvidencePolicy()
    started_at = datetime.now(timezone.utc)

    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        work = Path(tmp)
        try:
            argv, report_path = adapter.invocation(profile, endpoint.url, work)
        except OSError as exc:
            raise ExternalRunError(f"could not prepare {adapter.name}: {exc}") from exc

        begin = datetime.now(timezone.utc)
        returncode, stderr = _spawn(argv, cwd=work, timeout_s=timeout_s, env=env)
        duration = (datetime.now(timezone.utc) - begin).total_seconds()

        if not report_path.exists():
            # A non-zero exit with no report is a failed scan. A zero exit with
            # no report is worse -- the tool thinks it succeeded -- so neither
            # gets to look like a clean run.
            raise ExternalRunError(
                f"{adapter.name} exited {returncode} without writing a report: "
                f"{_redacted_stderr(stderr)}"
            )

        raw = report_path.read_text(encoding="utf-8", errors="replace")
        try:
            results = adapter.normalize(raw, evidence=evidence, started_at=started_at)
        except ValidationError:
            # A ValidationError is our mapping being wrong, not the tool's report
            # being bad. ValidationError subclasses ValueError, so without this
            # it would be reported as "the tool wrote an unreadable report" and
            # send the reader to debug the wrong process.
            raise
        except (ValueError, json.JSONDecodeError) as exc:
            raise ExternalRunError(f"{adapter.name} wrote an unreadable report: {exc}") from exc

    return ExternalRun(
        tool=adapter.name,
        results=results,
        argv=list(argv),
        returncode=returncode,
        duration_s=duration,
        started_at=started_at,
    )
