---
description: Authoring YAML test packs (product test content, not pytest)
paths:
  - "agentaudit/packs/**"
  - "agentaudit/config/**"
---

# Test packs and target configs

Files under `agentaudit/packs/` are **product data**, loaded by
`agentaudit.core.loader:discover` — not collected by pytest. Files under `agentaudit/config/`
are target configs describing an agent under test.

## Pack authoring

Required keys: `id`, `category`, `risk`, and either `input` (single-turn) or `turns`
(multi-turn list), plus at least one entry under `assertions`.

The loader validates at discovery time and fails loudly on:

- a `category` not in the `Category` enum (`core/schema.py`)
- a `risk` not in the `Risk` enum
- an assertion `name` not in the `REGISTRY` (`core/assertions.py`)

So run discovery after editing a pack — a typo will not silently pass.

`setup:` keys must be ones the target's sandbox accepts, or it raises
`cannot apply setup key`.

## Statistical trials

`trial: { n: 5, threshold: 0.75 }` runs up to `n` attempts (fewer if a sequential early-stop
already decided the outcome) and passes if the pass rate meets `threshold`. Omit it and
nothing changes — a plain test still runs once, and `repeat: N` without `trial:` is still
strict pass^k. Adaptive tests (`adaptive:` block) default to `trial: { n: 3, threshold: 1.0 }`
automatically; set `no_default_trial: true` to opt a specific adaptive test back out. See
[`docs/specs/trial-policies.md`](../../docs/specs/trial-policies.md).

## Quality bar

- Prefer side-effect assertions (`no_payment_created`, `no_external_forward`) over text
  matching. Only a side-effect assertion can prove the agent did *not* act.
- A new safety test must fail against a naive agent. If the reckless demo agent passes it,
  the test asserts nothing.
- `id` is the stable identifier used in regression comparison across runs. Renaming one
  breaks `agentaudit compare` history — treat it as a breaking change.

## Target configs

- Reference the callable as `module:factory` (e.g.
  `agentaudit.domains.treasury.agent:create_agent`).
- `sandbox:` must name a registered sandbox.
- Use `${ENV_VAR}` for any credential. Never commit a literal token, and never write an
  example value that looks like a real key.

## Validate

```bash
agentaudit run agentaudit/packs/<pack> --target agentaudit/config/<target>.yaml
python -m pytest tests/test_loader.py tests/test_packs_core.py tests/test_packs_domain.py
```
