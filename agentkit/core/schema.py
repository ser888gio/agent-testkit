"""Core result/test/run models — the schema every other module imports."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

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


class TestCase(BaseModel):
    id: str
    category: Category
    risk: Risk = Risk.medium
    input: str | dict[str, Any]
    setup: dict[str, Any] = Field(default_factory=dict)
    assertions: list[Assertion]
    tags: list[str] = Field(default_factory=list)
    timeout_s: float = 30.0

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(
                f"id must be dotted lowercase (e.g. 'a.b.c'), got {v!r}"
            )
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
        if v <= 0:
            raise ValueError("timeout_s must be > 0")
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
    started_at: datetime
    finished_at: datetime


class RunResult(BaseModel):
    run_id: str
    agent_name: str
    started_at: datetime
    finished_at: datetime
    results: list[TestResult] = Field(default_factory=list)
