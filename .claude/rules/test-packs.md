---
description: Authoring YAML test packs (product test content, not pytest)
paths:
  - "agentkit/packs/**"
  - "agentkit/config/**"
---

# Test packs and target configs

Files under `agentkit/packs/` are **product data**, loaded by
`agentkit.core.loader:discover` — not collected by pytest. Files under `agentkit/config/`
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

## Quality bar

- Prefer side-effect assertions (`no_payment_created`, `no_external_forward`) over text
  matching. Only a side-effect assertion can prove the agent did *not* act.
- A new safety test must fail against a naive agent. If the reckless demo agent passes it,
  the test asserts nothing.
- `id` is the stable identifier used in regression comparison across runs. Renaming one
  breaks `agentkit compare` history — treat it as a breaking change.

## Target configs

- Reference the callable as `module:factory` (e.g.
  `agentkit.domains.treasury.agent:create_agent`).
- `sandbox:` must name a registered sandbox.
- Use `${ENV_VAR}` for any credential. Never commit a literal token, and never write an
  example value that looks like a real key.

## Validate

```bash
agentkit run agentkit/packs/<pack> --target agentkit/config/<target>.yaml
python -m pytest tests/test_loader.py tests/test_packs_core.py tests/test_packs_domain.py
```
