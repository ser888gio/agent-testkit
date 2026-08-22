"""A coverage-keyed archive of attacks: one elite per (category, style) cell.

An attacker loop that keeps whatever scores highest converges. It finds one
framing that works and then spends its whole budget producing variants of that
framing, so the run ends with four hundred near-copies of a single jailbreak and
no probe at all in eight other categories. Optimising a scalar is what causes
that, and no amount of prompt engineering fixes it.

This is the MAP-Elites answer (Rainbow Teaming, Meta, arXiv 2402.16822): a
candidate competes only against the incumbent *of its own cell*, so a mediocre
attack in an empty cell survives while a superb one in a full cell has to beat a
superb incumbent. Diversity stops being something the search is rewarded for and
becomes a property of the data structure.

The grid reuses the taxonomy that already exists rather than inventing
descriptors: `Category` on one axis, attack style -- an `attacks.TRANSFORMS`
name, an `adaptive.STRATEGIES` ladder, or `plain` -- on the other. That choice is
what makes `empty_cells` meaningful: it names uncovered ground in the same terms
the packs and the compliance mapping already use.

Control-plane only. It reasons about test metadata and already-derived results,
never calls an agent, and holds no model. Every function here is deterministic:
`regressions.py` diffs by `test_id`, so an archive that admitted different tests
on a re-run would destroy comparison history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from agentaudit.core.adaptive import STRATEGIES
from agentaudit.core.attacks import TRANSFORMS, split_variant
from agentaudit.core.schema import Category, TestCase

# A cell is one (what we are testing, how we are testing it) pair.
CellKey = tuple[Category, str]

# The style axis. `plain` is the honest name for an unmutated single-turn probe:
# calling it "none" would read as missing data in a coverage report.
PLAIN_STYLE = "plain"
STYLES: frozenset[str] = frozenset({PLAIN_STYLE, *TRANSFORMS, *STRATEGIES})

# Above this, a candidate is a rewording of the incumbent rather than a new
# attack. Rainbow Teaming filters near-duplicates before spending a target
# query; the same reasoning applies harder here, where one run costs ~2.5s of
# process spawn.
# ponytail: lexical similarity only. Swap for embeddings if paraphrase-heavy
# candidates start slipping through -- SequenceMatcher will not catch a
# translation or a full restatement.
SIMILARITY_LIMIT = 0.85


@dataclass(frozen=True)
class Candidate:
    """One attack, and what running it revealed."""

    test: TestCase
    # Did the attack land -- did the agent do the thing the goal describes.
    landed: bool = False
    # Judge confidence, 0.0 when no judge was configured. Only ever compared
    # between two landed candidates in the same cell.
    confidence: float = 0.0
    techniques: list[str] = field(default_factory=list)

    @property
    def probe(self) -> str:
        """The prompt text novelty is measured against."""
        if isinstance(self.test.input, str):
            return self.test.input
        parts = [t for t in self.test.turns if isinstance(t, str)]
        return "\n".join(parts)


def style_of(test: TestCase) -> str:
    """The attack style a test exercises.

    Precedence is deliberate: an attack transform is applied to an already
    written test, so it is the outermost thing done to the prompt and the most
    useful label. `split_variant` owns the id convention, so this never parses
    ids itself.
    """
    _, transform = split_variant(test.id)
    if transform in TRANSFORMS:
        return transform
    if test.adaptive is not None and test.adaptive.strategy in STRATEGIES:
        return test.adaptive.strategy
    return PLAIN_STYLE


def cell_of(test: TestCase) -> CellKey:
    return (test.category, style_of(test))


def similarity(candidate: str, incumbent: str) -> float:
    """0.0 (unrelated) to 1.0 (identical), order-independent."""
    if not candidate or not incumbent:
        return 0.0
    return SequenceMatcher(None, candidate, incumbent).ratio()


class Archive:
    """One elite per cell, plus why everything else was turned away.

    Rejections are kept because they are evidence. "We generated forty
    candidates and admitted three" is a materially different claim from "we
    generated three", and a coverage report that cannot tell them apart is
    overstating its own search.
    """

    def __init__(self, elites: dict[CellKey, Candidate] | None = None) -> None:
        self.elites: dict[CellKey, Candidate] = dict(elites or {})
        self.rejections: list[tuple[str, str]] = []

    def __len__(self) -> int:
        return len(self.elites)

    def __contains__(self, cell: object) -> bool:
        return cell in self.elites

    def admit(self, candidate: Candidate) -> tuple[bool, str]:
        """Keep this candidate, or say why not.

        Always returns a reason, including on success, so a report can explain
        the archive's shape without re-deriving it.
        """
        cell = cell_of(candidate.test)
        incumbent = self.elites.get(cell)

        if incumbent is None:
            self.elites[cell] = candidate
            return True, f"first attack in {_cell_name(cell)}"

        score = similarity(candidate.probe, incumbent.probe)
        if score >= SIMILARITY_LIMIT:
            reason = f"too similar to the incumbent in {_cell_name(cell)} ({score:.2f})"
            self.rejections.append((candidate.test.id, reason))
            return False, reason

        if candidate.landed and not incumbent.landed:
            self.elites[cell] = candidate
            return True, f"landed where the incumbent in {_cell_name(cell)} did not"

        if candidate.landed and incumbent.landed and candidate.confidence > incumbent.confidence:
            self.elites[cell] = candidate
            return True, (
                f"landed with higher confidence than the incumbent in "
                f"{_cell_name(cell)} ({candidate.confidence:.2f} > "
                f"{incumbent.confidence:.2f})"
            )

        reason = f"the incumbent in {_cell_name(cell)} is at least as strong"
        self.rejections.append((candidate.test.id, reason))
        return False, reason

    def covered_cells(self) -> list[CellKey]:
        return sorted(self.elites, key=_cell_sort_key)

    def empty_cells(self, categories: list[Category] | None = None) -> list[CellKey]:
        """Cells with no attack in them -- the honest answer to "what did you not test".

        `categories` narrows the grid to what the agent under test can actually
        exercise; the full 9x25 product would otherwise report an agent as
        uncovered for categories nobody intended to probe.
        """
        wanted = list(categories) if categories is not None else list(Category)
        return sorted(
            (
                (category, style)
                for category in wanted
                for style in STYLES
                if (category, style) not in self.elites
            ),
            key=_cell_sort_key,
        )

    def landed(self) -> list[Candidate]:
        """Elites whose attack succeeded, worst news first."""
        return sorted(
            (c for c in self.elites.values() if c.landed),
            key=lambda c: (-c.confidence, c.test.id),
        )


def _cell_name(cell: CellKey) -> str:
    category, style = cell
    return f"{category.value}/{style}"


def _cell_sort_key(cell: CellKey) -> tuple[str, str]:
    category, style = cell
    return (category.value, style)


def build(candidates: list[Candidate]) -> Archive:
    """Fold candidates into an archive, in a fixed order.

    Sorted by test id first so the result cannot depend on the order results
    came back from a run: two identical runs must produce the same archive or
    the coverage report is not reproducible evidence.
    """
    archive = Archive()
    for candidate in sorted(candidates, key=lambda c: c.test.id):
        archive.admit(candidate)
    return archive
