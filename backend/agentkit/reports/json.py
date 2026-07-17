"""JSON report: exact model dumps of the run + score."""

from __future__ import annotations

import json as _json

from agentkit.core.schema import RunResult
from agentkit.core.scoring import ScoreReport


def to_json(run: RunResult, score: ScoreReport) -> str:
    return _json.dumps(
        {
            "run": _json.loads(run.model_dump_json()),
            "score": _json.loads(score.model_dump_json()),
        },
        indent=2,
        sort_keys=True,
    )
