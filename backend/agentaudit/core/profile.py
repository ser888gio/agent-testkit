"""Adaptive-harness contracts: what an agent is, what a test needs, what we planned.

These are control-plane models. Nothing here touches an agent, and nothing here
may carry agent output: a `HarnessPlan` is persisted next to a run, so any raw
response text stored in it would bypass the redaction pass in `runner.py`.
Discovery records *shapes and booleans*, never bodies.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from agentaudit.core.schema import Category, Risk

# Prerequisites a test may declare. A test whose requirement the agent cannot
# satisfy is excluded rather than run-and-failed: a stateless endpoint failing a
# memory test is a harness error, not agent evidence.
CAPABILITIES = ("multi_turn", "tool_use", "sandbox", "structured_input")


class AgentProfile(BaseModel):
    """What we know about a tested agent, and therefore which tests are worth running."""

    id: str
    purpose: str = ""
    domain: str = "generic"
    interface: str = "http"
    multi_turn: bool = False
    tool_use: bool = False
    structured_input: bool = False
    sandbox: str | None = None
    tool_classes: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    risk_level: Risk = Risk.medium
    policy_tags: list[str] = Field(default_factory=list)
    # Free-text notes from discovery, for the "why did you pick this" report.
    notes: list[str] = Field(default_factory=list)

    def capabilities(self) -> set[str]:
        """The `TestCatalogEntry.requires` names this agent can actually satisfy."""
        present = {
            "multi_turn": self.multi_turn,
            "tool_use": self.tool_use,
            "sandbox": self.sandbox is not None,
            "structured_input": self.structured_input,
        }
        return {name for name, ok in present.items() if ok}


class TestCatalogEntry(BaseModel):
    """A test described in selection terms, whatever library it originally came from."""

    test_id: str
    source: str = "local"
    category: Category
    risk: Risk = Risk.medium
    # Empty means domain-agnostic — applies everywhere rather than nowhere.
    domains: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    # Relative execution cost; a pass^k or multi-turn test costs more than one call.
    cost: float = 1.0


class SelectedTest(BaseModel):
    test_id: str
    source: str
    score: float
    reasons: list[str] = Field(default_factory=list)


class ExcludedTest(BaseModel):
    test_id: str
    source: str
    reason: str


class StopConditions(BaseModel):
    max_tests: int | None = None
    stop_on_critical: bool = False


class HarnessPlan(BaseModel):
    """The assembled harness for one agent: what runs, what does not, and why."""

    profile: AgentProfile
    selected: list[SelectedTest] = Field(default_factory=list)
    excluded: list[ExcludedTest] = Field(default_factory=list)
    sandbox: str | None = None
    attack_transforms: list[str] = Field(default_factory=list)
    stop_conditions: StopConditions = Field(default_factory=StopConditions)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def selected_ids(self) -> list[str]:
        return [s.test_id for s in self.selected]
