"""Fake MCP toolbox: records tool invocations as side-effect events.

PRD-001 scaffolding. The generic tool assertions (`tool_called`,
`tool_not_called`, `no_repeated_tool`, ...) match `Event.kind` against a tool
name, so each invocation is recorded under the invoked tool's name. Argument
and response values never reach the event -- only SHA-256 digests do -- which
keeps secrets out of evidence while still proving *that* a tool fired and
whether the same call repeated. The timestamp lives on the event itself
(`Event.ts`); the snapshot mirrors it as ISO-8601 text so diffs stay
JSON-serializable and deterministic in shape.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from agentaudit.core.sandbox import Sandbox, register_sandbox


def _digest(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@register_sandbox("mcp")
class McpToolboxSandbox(Sandbox):
    def __init__(self) -> None:
        super().__init__()
        # name -> {"description": str, "response": payload}
        self.tools: dict[str, dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.tools = {}
        self.calls = []
        self._clear_events()

    def apply_setup(self, setup: dict[str, Any]) -> None:
        for key, value in setup.items():
            if key == "tools":
                for raw in value:
                    self.tools[raw["name"]] = {
                        "description": raw.get("description", ""),
                        "response": raw.get("response", {}),
                    }
            else:
                raise self._unknown_setup_key(key)

    def invoke(self, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Invoke a fake tool and record the attempt as a side-effect event."""
        args = args or {}
        spec = self.tools.get(tool)
        known = spec is not None
        response = dict(spec["response"]) if known else {"error": f"unknown tool '{tool}'"}
        record = {
            "tool": tool,
            "args_hash": _digest(args),
            "response_hash": _digest(response),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self.calls.append(record)
        self.record_event(
            tool,
            {
                "args_hash": record["args_hash"],
                "response_hash": record["response_hash"],
                "ok": known,
            },
        )
        return response

    def call_count(self, tool: str | None = None) -> int:
        if tool is None:
            return len(self.calls)
        return sum(1 for c in self.calls if c["tool"] == tool)

    def snapshot(self) -> dict[str, Any]:
        return {
            "tools": sorted(self.tools),
            "calls": [dict(c) for c in self.calls],
        }
