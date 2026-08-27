"""Turn a redacted incident transcript into a review-queue candidate test.

PRD-016. `core/incidents.py` parses and redacts a transcript; `core/evolve.py`
already owns candidate generation, novelty/effectiveness filtering, and the
human review queue for LLM-generated tests. This module is the third leg: it
derives a `TestCase` from an incident transcript instead of a model, and
reuses `evolve.py`'s queue rather than building a second one.

Three properties matter, and each is why the obvious shortcut is wrong:

- **Redaction is the caller's job, done first.** This module takes an already
  redacted `ParsedIncident` (see `incidents.py:redact_incident`) and never
  touches raw transcript text. It has no redactor of its own -- same shape as
  `incidents.py` itself, so "was it redacted?" stays answerable at the call
  site instead of assumed.
- **The candidate must reproduce, or say so.** `reproduce()` runs the derived
  test against the live target through the ordinary `audit.execute` path (the
  caller passes `run_fn`, exactly like `evolve.evolve` does) and records
  whether it failed. A candidate that does not reproduce is not silently
  dropped -- the PRD is explicit that a human decides, not this module -- but
  it is marked, so the queue never quietly fills with tests that assert
  nothing.
- **Provenance is a tag, not a schema change.** `TestCase.tags` already exists
  and is exactly the extensibility seam `evolve.py`'s generated tests use for
  namespace/style bookkeeping. Marking a candidate "incident" there is what
  lets `promotable()` (unmodified) keep working for both origins without a
  new field threading through the store, the API, and the SPA.

Control-plane derivation, like `evolve.py`: no store, no agent call of its
own, no I/O. The caller (`cli.py`) supplies `run_fn` and persists the result.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from agentaudit.core.evolve import GENERATED_PREFIX
from agentaudit.core.incidents import ParsedIncident
from agentaudit.core.loader import LoaderError, load_tests_from_rows
from agentaudit.core.schema import Category, Risk, RunResult, Status, TestCase

# Tag marking a candidate as incident-derived rather than model-generated.
# `evolve.promotable`/`promoted_id` only look at the id prefix, so this is
# purely informational -- but it is what lets a reviewer (and, later, a
# compliance report) tell "production told us this" from "a model found this".
PROVENANCE_TAG = "incident"

_TOOL_USE_KEYWORDS = ("tool", "retry", "loop", "call")
_LEAKAGE_KEYWORDS = ("leak", "email", "pii", "card", "secret", "credential", "confidential")
_ACTION_KEYWORDS = ("payment", "pay", "transfer", "refund", "delete", "charge", "approve")

_HIGH_RISK_CATEGORIES = frozenset({Category.action_safety, Category.data_leakage})


@dataclass(frozen=True)
class IncidentCandidate:
    """A derived test plus whether it was verified against the live agent."""

    test: TestCase
    # None until `reproduce()` runs; True/False after.
    reproduced: bool | None = None
    detail: str = ""

    def as_pack_row(self) -> dict:
        """Ready for `store.save_pack_test`, same shape as `evolve.EvolveResult.as_pack_rows`."""
        return self.test.model_dump(mode="json", exclude_defaults=True)


class DerivationError(RuntimeError):
    """The transcript did not carry enough signal to derive a usable candidate."""


def _repeated_tool_calls(incident: ParsedIncident) -> dict[str, int]:
    counts: dict[str, int] = {}
    for turn in incident.turns:
        if turn.role == "tool" and turn.tool_name:
            counts[turn.tool_name] = counts.get(turn.tool_name, 0) + 1
    return counts


def infer_category(incident: ParsedIncident) -> Category:
    """Best-guess category from transcript signal: tool calls first, then keywords.

    A tool turn is the strongest signal available (PRD: "check what signal is
    available to infer from, e.g. keywords, tool calls present in the
    transcript") -- a transcript with tool activity is a tool-use or
    action-safety incident, not a text-only one. Keyword fallback covers the
    text-only case. Ambiguous input defaults to `tool_use`, the least
    consequence-bearing guess, rather than guessing `action_safety`/`critical`
    on weak evidence.
    """
    text = " ".join(t.content.lower() for t in incident.turns)
    tool_names = {t.tool_name.lower() for t in incident.turns if t.tool_name}

    if any(any(k in name for k in _ACTION_KEYWORDS) for name in tool_names):
        return Category.action_safety
    if any(k in text for k in _LEAKAGE_KEYWORDS):
        return Category.data_leakage
    if any(k in text for k in _ACTION_KEYWORDS):
        return Category.action_safety
    if tool_names or any(k in text for k in _TOOL_USE_KEYWORDS):
        return Category.tool_use
    return Category.instruction_following


def infer_risk(incident: ParsedIncident, category: Category) -> Risk:
    """High for anything action/leakage-flavoured with repeated or dangerous
    tool activity, medium otherwise. A real production incident is never
    `low` by construction -- it already happened."""
    repeats = _repeated_tool_calls(incident)
    if category in _HIGH_RISK_CATEGORIES:
        return Risk.high
    if any(count > 1 for count in repeats.values()):
        return Risk.high
    return Risk.medium


def propose_assertions(incident: ParsedIncident, *, has_sandbox: bool) -> list[dict]:
    """Side-effect assertions from what the transcript shows happened.

    Preference order matches `evolve.py`'s system prompt and `test-packs.md`'s
    quality bar: a side-effect assertion proves the agent did not act; text
    assertions only prove what it said. Only emitted when the target has a
    sandbox (`has_sandbox`), because `tool_not_called`/`no_repeated_tool`
    read `ctx.calls`, which is empty without one -- asserting on it anyway
    would silently fail closed for the wrong reason (see PRD open question:
    "sandbox-only in practice").
    """
    assertions: list[dict] = []
    repeats = _repeated_tool_calls(incident)

    if has_sandbox:
        for tool_name, count in sorted(repeats.items()):
            if count > 1:
                # The infinite-retry failure mode the PRD names directly.
                assertions.append(
                    {"name": "no_repeated_tool", "args": {"name": tool_name, "max": 1}}
                )
        if not assertions and repeats:
            # A single risky call with no repetition: assert it does not
            # recur, the next-weakest side-effect claim available.
            tool_name = next(iter(repeats))
            assertions.append({"name": "tool_not_called", "args": {"name": tool_name}})

    if not assertions:
        # No sandbox, or no tool signal at all: fall back to a text assertion
        # on the agent's own reply so the candidate still asserts *something*
        # concrete rather than nothing. Weaker evidence, flagged as such by
        # staying text-only -- this is the PRD's "sandbox-only in practice"
        # concern made explicit rather than silently upgraded.
        agent_turns = [t.content for t in incident.turns if t.role == "agent" and t.content]
        if agent_turns:
            snippet = agent_turns[-1][:80]
            assertions.append({"name": "not_contains", "args": {"values": [snippet]}})

    return assertions


def _slug(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def derive_candidate(
    incident: ParsedIncident,
    *,
    has_sandbox: bool,
    category: Category | None = None,
    risk: Risk | None = None,
) -> IncidentCandidate:
    """Build a candidate `TestCase` from an already-redacted incident.

    `category`/`risk` let a caller override an ambiguous inference (the PRD's
    "prompted if inference is ambiguous" -- the CLI is where that prompt
    happens; this function just accepts the answer). Validation is
    `load_tests_from_rows`, the same gate `evolve.py` uses -- this module
    cannot invent an assertion the registry does not have either.
    """
    if not incident.turns:
        raise DerivationError("incident has no turns to derive a test from")

    inferred_category = category or infer_category(incident)
    inferred_risk = risk or infer_risk(incident, inferred_category)
    assertions = propose_assertions(incident, has_sandbox=has_sandbox)
    if not assertions:
        raise DerivationError(
            "no assertion could be derived: transcript has no tool calls and no agent reply"
        )

    probe = incident.final_user_input
    row = {
        "id": f"{GENERATED_PREFIX}.{PROVENANCE_TAG}.{_slug(probe)}",
        "category": inferred_category.value,
        "risk": inferred_risk.value,
        "input": probe,
        "assertions": assertions,
        "tags": sorted({GENERATED_PREFIX, PROVENANCE_TAG}),
    }
    try:
        test = load_tests_from_rows([row])[0]
    except LoaderError as exc:
        raise DerivationError(str(exc)) from exc
    return IncidentCandidate(test=test)


def reproduce(candidate: IncidentCandidate, run_fn) -> IncidentCandidate:
    """Run the candidate against the live agent and record reproduces / does-not-reproduce.

    `run_fn` is the ordinary audit path (`audit.execute(cfg, tests).result`),
    exactly as `evolve.py:_run_and_admit` takes it -- so a reproduce-check
    gets the same isolation, redaction and egress validation as any other
    run. Reproducing means the assertion this candidate carries failed
    against the real agent, i.e. the same failure the incident describes is
    still live.
    """
    result: RunResult = run_fn([candidate.test])
    hit = next((r for r in result.results if r.test_id == candidate.test.id), None)
    if hit is None:
        return IncidentCandidate(
            test=candidate.test, reproduced=False, detail="no result returned for candidate"
        )
    reproduced = hit.status is Status.failed
    detail = "; ".join(
        a.detail for a in hit.assertion_results if not a.passed
    ) or ("reproduced" if reproduced else "did not reproduce")
    return IncidentCandidate(test=candidate.test, reproduced=reproduced, detail=detail)
