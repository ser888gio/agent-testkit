---
description: Turn exploration findings into the smallest viable implementation plan. Read-only.
argument-hint: [the change to plan]
---

Plan: **$ARGUMENTS**

**Do not edit any files during this workflow.** Produce a plan for review.

Build on prior exploration findings if this session has them; otherwise investigate first
(`architecture-explorer`, `dependency-tracer`, `test-finder`) before planning. Do not plan
against assumptions.

Bias hard toward the **smallest complete change**. Reject speculative abstraction, unneeded
configurability, and interfaces with one implementation. If an existing helper or pattern in
this repo already covers part of the work, use it and say so.

## Report

1. **Smallest viable implementation** — the approach, in a few sentences
2. **Files to change** — each with what changes and why
3. **Files explicitly NOT to change** — especially adjacent files a reader might expect to
   need editing, with the reason they don't
4. **Interface implications** — does this touch `core/schema.py`, `core/config.py`, the
   assertion `REGISTRY`, or the `Sandbox` ABC? Those are high-blast-radius contracts; list
   every consumer, including YAML packs and Jinja templates that reference names as strings
5. **Data / migration implications** — `agentkit.db` is a gitignored developer artifact with
   no migration system; if `store.py`'s schema changes, the plan is "delete the local db",
   not a migration
6. **Risks** — what could regress, and the repo invariant most at risk (runner never raises,
   redaction before storage, compliance fails closed, dependency direction)
7. **Tests** — which `tests/test_<module>.py` files get new cases, and what each asserts.
   Failure paths, not just happy paths
8. **Validation commands** — the exact ladder for this change, narrowest first, ending with
   `bash tools/validate.sh`

If two approaches are genuinely viable, recommend one and give the tradeoff in a sentence —
do not present an undecided menu.
