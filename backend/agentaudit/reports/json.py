"""JSON report: exact model dumps of the run + score."""

from __future__ import annotations

import json as _json

from agentaudit.core.schema import RunResult
from agentaudit.core.scoring import ScoreReport
from agentaudit.core.timeline import build as build_timeline
from agentaudit.core.timeline import window as window_timeline


def to_json(run: RunResult, score: ScoreReport) -> str:
    run_payload = _json.loads(run.model_dump_json())
    # Additive: a `timeline` block per result, alongside the raw fields it is
    # derived from (`request`, `events`). Only multi-turn results get one, so
    # existing single-turn-only consumers see no new keys on their results.
    for result, payload in zip(run.results, run_payload["results"], strict=True):
        timeline = window_timeline(build_timeline(result))
        if len(timeline["turns"]) >= 2:
            payload["timeline"] = timeline

    return _json.dumps(
        {
            "run": run_payload,
            "score": _json.loads(score.model_dump_json()),
        },
        indent=2,
        sort_keys=True,
    )
