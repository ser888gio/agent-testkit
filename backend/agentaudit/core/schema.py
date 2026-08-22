"""Core result/test/run models — the schema every other module imports."""

from __future__ import annotations

import math
import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

_ID_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9_]+)+$")


class Category(str, Enum):
    endpoint_contract = "endpoint_contract"
    prompt_injection = "prompt_injection"
    data_leakage = "data_leakage"
    instruction_following = "instruction_following"
    action_safety = "action_safety"
    tool_use = "tool_use"
    memory_context = "memory_context"
    reliability = "reliability"
    performance = "performance"


class Risk(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Status(str, Enum):
    passed = "passed"
    failed = "failed"
    error = "error"
    skipped = "skipped"


class Assertion(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class AdaptiveSpec(BaseModel):
    """Turn generation for an adaptive test: `input` is the attacker's goal."""

    strategy: str = "crescendo"
    max_turns: int = Field(4, ge=1, le=20)
    # Substrings that mean the attack landed, so escalation can stop early.
    stop_on: list[str] = Field(default_factory=list)
    # Let an attacker model write each turn from the agent's actual reply
    # instead of following the script. Off by default, and a no-op unless
    # AGENTAUDIT_ATTACKER_ENDPOINT/_MODEL are set, so CI stays offline.
    refine: bool = False
    # Which ladder supplies the turn budget and the fallback when the attacker
    # model is unavailable. Defaults to `strategy`.
    refine_from: str | None = None


class TestCase(BaseModel):
    id: str
    category: Category
    risk: Risk = Risk.medium
    input: str | dict[str, Any] | None = None
    turns: list[str | dict[str, Any]] = Field(default_factory=list)
    setup: dict[str, Any] = Field(default_factory=dict)
    assertions: list[Assertion]
    tags: list[str] = Field(default_factory=list)
    timeout_s: float = 30.0
    # pass^k: run the test `repeat` times, pass only if every attempt passes.
    repeat: int = Field(1, ge=1)
    # When set, `input` is the attacker goal and turns are generated adaptively.
    adaptive: AdaptiveSpec | None = None

    @model_validator(mode="after")
    def _require_input_xor_turns(self) -> TestCase:
        if bool(self.input is not None) == bool(self.turns):
            raise ValueError("exactly one of 'input' or 'turns' must be set")
        if self.adaptive is not None and not isinstance(self.input, str):
            raise ValueError("an adaptive test needs a string 'input' (the attacker goal)")
        return self

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(f"id must be dotted lowercase (e.g. 'a.b.c'), got {v!r}")
        return v

    @field_validator("assertions")
    @classmethod
    def _validate_assertions(cls, v: list[Assertion]) -> list[Assertion]:
        if not v:
            raise ValueError("assertions must be non-empty")
        return v

    @field_validator("timeout_s")
    @classmethod
    def _validate_timeout(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("timeout_s must be finite and > 0")
        return v


class AssertionResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class TestResult(BaseModel):
    test_id: str
    category: Category
    risk: Risk
    status: Status
    latency_ms: float | None = None
    assertion_results: list[AssertionResult] = Field(default_factory=list)
    request: Any = None
    response: Any = None
    sandbox_diff: dict[str, Any] | None = None
    error: str | None = None
    # One entry per pass^k attempt; empty when the test ran once.
    attempts: list[Status] = Field(default_factory=list)
    # Attacker techniques that produced this run's turns, in the order used.
    # Empty for every scripted run, which is the default. Names only -- the
    # attacker's prose rationale is derived from agent replies and must not be
    # persisted alongside a control-plane record.
    techniques: list[str] = Field(default_factory=list)
    # True when an attacker or judge model was configured but fell back. Without
    # it a model-driven probe and a silently degraded one are indistinguishable
    # in stored evidence, and a report could imply coverage that never happened.
    degraded: bool = False
    started_at: datetime
    finished_at: datetime


class RunResult(BaseModel):
    run_id: str
    agent_name: str
    started_at: datetime
    finished_at: datetime
    results: list[TestResult] = Field(default_factory=list)
