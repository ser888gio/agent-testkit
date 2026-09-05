# Plan 015: Make the tenant's LLM config reach the isolated child, and put the attacker/judge dial behind the egress policy

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7cb6196..HEAD -- backend/agentaudit/core/isolation.py backend/agentaudit/core/runner.py backend/agentaudit/core/llm.py backend/agentaudit/core/agent.py backend/agentaudit/worker.py frontend/agentaudit/web/api.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: `plans/014-redactor-reaches-attacker-and-judge.md` (sequencing
  only — both edit `backend/agentaudit/core/runner.py`, in different regions)
- **Category**: security
- **Planned at**: commit `7cb6196`, 2026-09-04

## Why this matters

**These two changes must land in the same PR.** Read this section carefully;
doing half of it is worse than doing none.

**Half one — the feature is inert.** Tenants can supply their own attacker/judge
model (endpoint, model name, API key) through the Settings page. The worker
reads that row and installs it with `llm.override(...)`, which sets a
`ContextVar`. But the code that reads the config —
`build_attacker`/`build_judge`, called from `runner.py` — executes inside a
child process started with `multiprocessing.get_context("spawn")`. A `ContextVar`
set in the parent is not inherited by a spawned child. So the child calls
`llm.load_llm_config()`, finds no override, and falls through to `_from_env()`.

The tenant's configuration is silently ignored. Worse, if the worker host has
`AGENTAUDIT_ATTACKER_ENDPOINT`/`_MODEL`/`_API_KEY` set, the child uses the
**deployment's own** model and key to run the **tenant's** job. And nothing
reports the degradation, because `build_attacker` returns `None` rather than
raising, so `_Provenance.degraded` stays unset.

**Half two — fixing half one alone opens an SSRF.** `HTTPAttacker.complete`
builds a bare `httpx.Client` and POSTs to `self.endpoint` with no
`validate_endpoint`, no DNS pin, and no allowlist — unlike `HTTPAgent.run`,
which dials `endpoint.pinned_url`. The only validation a tenant-supplied LLM
endpoint gets today is a scheme-and-hostname check in the web layer
(`api.py:807-829`), whose own comment says the DNS pinning "belongs at dial
time" — and dial time performs none.

Today that gap is not reachable through the worker, precisely *because* half one
is broken: the tenant's endpoint never arrives. Fix half one on its own and any
org admin can point the attacker model at `http://10.0.0.5`, a worker-local
port, or a rebinding hostname, and the worker will dial it from inside the
deployment network on every adaptive run — with response status and shape
differences making it an oracle. `core/egress.py` exists to close exactly this
class; the attacker path simply never learned about it.

## Current state

Files involved:

- `backend/agentaudit/core/isolation.py` — `IsolatedRunner.__init__` builds the
  spawn argument tuple; `_child` is the child entry point. Neither carries LLM
  config. You will change both.
- `backend/agentaudit/core/runner.py` — `run()` constructs the `IsolatedRunner`.
  You will pass the config in here.
- `backend/agentaudit/core/llm.py` — `build_client` constructs the
  `HTTPAttacker`. You will make it validate the endpoint.
- `backend/agentaudit/core/agent.py` — `HTTPAttacker` holds the dial. You will
  make it dial a pinned URL.
- `backend/agentaudit/core/egress.py` — read-only. Provides `validate_endpoint`,
  `EgressPolicy`, `ValidatedEndpoint`, `EgressError`.
- `backend/agentaudit/worker.py` — read-only for the override; it already calls
  `llm.override(...)` correctly for the parent process.
- `frontend/agentaudit/web/api.py` — `save_llm_settings`. You will add save-time
  validation so the tenant sees the error in the UI.

### The spawn boundary

`backend/agentaudit/core/isolation.py:720-742` — the argument tuple, with no
LLM config in it:

```python
    def __init__(
        self,
        target: Any,
        redactor: Any,
        endpoint: Any = None,
        preload: tuple[str, ...] = (),
        *,
        memory_mb: int = DEFAULT_MEMORY_MB,
        cpu_seconds: int = DEFAULT_CPU_SECONDS,
    ):
        self._ctx = multiprocessing.get_context("spawn")
        self._worker_pid = self._ctx.Value("q", 0)
        self._args = (
            target,
            redactor,
            endpoint,
            preload,
            memory_mb,
            cpu_seconds,
            self._worker_pid,
        )
```

`backend/agentaudit/core/isolation.py:660-670` — the matching child signature:

```python
def _child(
    conn: Connection,
    target: Any,
    redactor: Any,
    endpoint: Any,
    preload: tuple[str, ...],
    memory_mb: int,
    cpu_seconds: int,
    worker_pid: Any,
) -> None:  # pragma: no cover - subprocess
```

`backend/agentaudit/core/llm.py:169-180` — the override that does not cross it:

```python
_override: ContextVar[LLMConfig | None] = ContextVar("agentaudit_llm_override", default=None)


@contextlib.contextmanager
def override(config: LLMConfig | None) -> Iterator[None]:
    """Make `load_llm_config()` return `config` inside this block."""
    token = _override.set(config)
    try:
        yield
    finally:
        _override.reset(token)
```

`backend/agentaudit/worker.py:341-342` — the parent-side install (correct, do
not change):

```python
    with llm.override(_tenant_llm_config(store, job.org_id)):
        return _execute_job(store, job, lost_lease=lost_lease)
```

`backend/agentaudit/core/runner.py:485` — where the child is constructed:

```python
    isolated = IsolatedRunner(target, redactor, endpoint, sandbox_modules())
```

### The unvalidated dial

`backend/agentaudit/core/llm.py:233-250`:

```python
def build_client(role: RoleConfig | None, default_temperature: float) -> Any | None:
    """An `HTTPAttacker` for a role, or None when the role is unconfigured.

    Imported here rather than at module scope to keep `httpx` -- which
    `core/agent.py` alone imports -- off this module's import path.
    """
    if role is None:
        return None
    from agentaudit.core.agent import HTTPAttacker

    temperature = role.temperature if role.temperature is not None else default_temperature
    return HTTPAttacker(
        endpoint=role.endpoint,
        model=role.model,
        api_key=role.api_key(),
        timeout_s=role.timeout_s,
        temperature=temperature,
    )
```

`backend/agentaudit/core/agent.py:230-246` — the raw dial:

```python
    def complete(self, system: str, user: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {...}
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
                response = client.post(self.endpoint, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise AttackerUnavailable(f"attacker model unreachable: {exc}") from exc
```

Compare `HTTPAgent.run` at `backend/agentaudit/core/agent.py:127-145`, which
dials `self.endpoint.pinned_url` and sets the `Host` header — that is the
pattern to copy.

### The egress API you will use

`backend/agentaudit/core/egress.py`:

```python
@dataclass(frozen=True)
class EgressPolicy:
    """Exact, normalized hosts. No wildcards..."""
    allowed_hosts: frozenset[str]

    @classmethod
    def from_iterable(cls, hosts: Iterable[str]) -> EgressPolicy: ...


@dataclass(frozen=True)
class ValidatedEndpoint:
    url: str
    host: str
    port: int
    address: str

    @property
    def pinned_url(self) -> str: ...
    @property
    def host_header(self) -> str: ...


def validate_endpoint(
    endpoint: str,
    policy: EgressPolicy,
    resolver: Resolver = default_resolver,
    *,
    allow_private: bool = False,
) -> ValidatedEndpoint:
    """Resolve and authorize an endpoint, or raise `EgressError`."""
```

Note `validate_endpoint` requires the host to be in `policy.allowed_hosts`. For
an LLM role there is no partner allowlist, so the policy is seeded with the
single host the tenant saved — the host is authorized *by having been saved*,
and everything else (`https`, no URL credentials, public address, DNS pin) is
what the check buys you.

`backend/agentaudit/worker.py:183-200` shows the established call shape,
including the `allow_private` convention: it is read from the worker's own
environment (`AGENTAUDIT_EGRESS_ALLOW_LOCAL == "1"`) and **never** from tenant
config.

### Web-layer save

`frontend/agentaudit/web/api.py:807-829` — validation today is scheme + hostname
only, with a comment asserting that pinning belongs at dial time.

### Repo conventions

- **Architecture rule, load-bearing**: `httpx` is imported in exactly one place,
  `backend/agentaudit/core/agent.py`. Do not import it anywhere else. `llm.py`
  does a function-local import of `HTTPAttacker` for this reason — preserve that.
- **Architecture rule**: `core` imports nothing from `domains`, `reports`,
  `web`, or `cli`. Never add a reverse edge.
- Line length 100; ruff selects `E, F, I, B, UP`, currently green.
- Comments explain *why*. See `egress.py`'s `validate_endpoint` docstring or
  `worker.py:186-198` for the register, including the `ponytail:` convention for
  marking a deliberate simplification and naming its ceiling.

## Commands you will need

| Purpose         | Command                                        | Expected on success     |
|-----------------|------------------------------------------------|-------------------------|
| Isolation tests | `python -m pytest tests/test_isolation.py`      | all pass                |
| LLM tests       | `python -m pytest tests/test_llm.py`            | all pass                |
| Worker tests    | `python -m pytest tests/test_worker.py`         | all pass                |
| Web tests       | `python -m pytest tests/test_web.py`            | all pass                |
| Agent tests     | `python -m pytest tests/test_agent.py`          | all pass                |
| Lint            | `python -m ruff check .`                        | `All checks passed!`    |
| Full suite      | `python -m pytest`                              | `1066 passed` (or more) |

**Windows note**: call pytest and ruff as modules (`python -m pytest`), never as
console scripts — `uv run ... pytest` fails on Windows with
`uv trampoline failed to canonicalize script path`.

The full suite takes about 11 minutes. This plan touches the isolation layer, so
run the full suite at the end even if targeted tests are green.

## Scope

**In scope** (the only files you should modify):

- `backend/agentaudit/core/isolation.py` — `IsolatedRunner.__init__` and `_child`
- `backend/agentaudit/core/runner.py` — the `IsolatedRunner(...)` construction
  around line 485 only
- `backend/agentaudit/core/llm.py` — `build_client` only
- `backend/agentaudit/core/agent.py` — `HTTPAttacker` only
- `frontend/agentaudit/web/api.py` — `save_llm_settings` only
- `tests/test_isolation.py`, `tests/test_llm.py`, `tests/test_agent.py`,
  `tests/test_web.py` — add tests

**Out of scope** (do NOT touch, even though they look related):

- `backend/agentaudit/worker.py` — `llm.override(...)` and `_tenant_llm_config`
  are already correct. The bug is that the override does not cross the process
  boundary, not that it is installed wrongly.
- `backend/agentaudit/core/egress.py` — use it, do not modify it. It was audited
  and is sound.
- `HTTPAgent` (`agent.py:104-160`) — it already validates. Do not refactor it
  "for symmetry" while you are in the file.
- `runner.py:142-152` (`_run_turns`) — that region belongs to plan 014.
- The `llm_settings` table and migration `0016` — encryption at rest is a
  separate, unplanned finding. Do not start it here.
- Do **not** export the tenant key to `os.environ` as a shortcut for crossing
  the process boundary. Workers run jobs for several orgs concurrently and a
  process env var is shared by all of them — `worker.py:307-313` says so
  explicitly. Pass it as data.

## Git workflow

- Branch off `develop` **after plan 014 has landed**:
  `git checkout -b fix/015-tenant-llm-config-egress develop`
- Conventional-commit subjects, e.g.
  `fix: carry the tenant LLM config into the isolated child` and
  `fix: dial the attacker model through the egress policy`
- Commit messages must end with:

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

- Do NOT push or open a PR unless the operator instructed it.

## Steps

Do them in this order. Steps 1–2 close the SSRF; steps 3–4 turn the feature on.
Landing 3–4 before 1–2 would ship the hole.

### Step 1: Give `HTTPAttacker` a validated endpoint

Change `HTTPAttacker` in `backend/agentaudit/core/agent.py` so it dials a pinned
address instead of a raw URL.

- Accept an optional `validated: ValidatedEndpoint | None = None` alongside the
  existing `endpoint: str`. Keep `endpoint` — it is what error messages and the
  `describe()` view show, and several tests construct `HTTPAttacker` directly
  with a `transport=` stub and no validation.
- In `complete`, when `validated` is not None: POST to `validated.pinned_url`,
  set the `Host` header to `validated.host_header`, and pass
  `follow_redirects=False` explicitly. Copy the shape from `HTTPAgent.run`
  (`agent.py:127-145`) — read it first and match it, including how it sets SNI
  if it does.
- When `validated` is None, behave exactly as today. This keeps every existing
  direct-construction test working.

**Verify**: `python -m pytest tests/test_agent.py tests/test_attacker.py tests/test_judge.py`
→ all pass, unchanged.

### Step 2: Validate in `build_client`, and at save time

**2a — dial time.** In `backend/agentaudit/core/llm.py`, `build_client` must
validate `role.endpoint` before constructing the client:

- Build a single-host policy: `EgressPolicy.from_iterable([<host of role.endpoint>])`.
  Parse the host with `urlsplit` (already imported, or import it) — do not
  hand-roll host extraction.
- Call `validate_endpoint(role.endpoint, policy, allow_private=os.environ.get("AGENTAUDIT_EGRESS_ALLOW_LOCAL") == "1")`.
  The `allow_private` flag comes from the process environment, never from
  `role`. Mirror the comment at `worker.py:186-198`.
- On `EgressError`, raise `AttackerUnavailable` with a message naming the role
  and the reason. **Do not** return `None` — `None` means "unconfigured", and
  conflating "you configured something we refuse to dial" with "you configured
  nothing" is how this class of bug hides. Confirm `AttackerUnavailable` is the
  right exception by reading how `RefiningStrategy.next_turn`
  (`attacker.py:250-256`) and `ModelJudge.succeeded` (`judge.py:106-110`) handle
  it — both catch it and fall back to the scripted/substring path while
  recording the fallback in their log, which is the behavior you want.
- Pass the resulting `ValidatedEndpoint` to `HTTPAttacker(validated=...)`.
- Import `EgressPolicy`, `EgressError`, `validate_endpoint` from
  `agentaudit.core.egress` at module scope — `egress` does not import `httpx`,
  so this does not violate the single-import rule.

**2b — save time.** In `frontend/agentaudit/web/api.py`, `save_llm_settings`
must reject an endpoint the worker would later refuse, so the tenant sees the
error in the UI rather than as a silent per-run fallback. Run the same
`validate_endpoint` call against a single-host policy and return
`HTTPException(status_code=400, detail=...)` on `EgressError`. Replace the
now-redundant scheme/credential checks only if `validate_endpoint` already
covers them — read its body and confirm before deleting anything.

Update the stale comment at `api.py:817-819` ("the DNS-pinning that
`validate_endpoint` does belongs at dial time") to describe what is now true:
validated at both ends, because a save-time check is a better error message and
a dial-time check is the one that is actually load-bearing against rebinding.

**Verify**:
- `python -m pytest tests/test_llm.py tests/test_web.py` → all pass
- `grep -n "httpx" backend/agentaudit/core/llm.py` → matches only in comments
  and docstrings, never an `import httpx`

### Step 3: Carry the LLM config across the spawn boundary

In `backend/agentaudit/core/isolation.py`:

- Add `llm_config: Any = None` to `IsolatedRunner.__init__` (keyword-only, after
  the existing `*`, so no positional call changes meaning) and append it to
  `self._args`.
- Add a matching trailing parameter to `_child`'s signature. **The tuple order
  and the signature order must match exactly** — this is a positional argument
  tuple, and a mismatch produces a confusing runtime failure inside a subprocess.
- In `_child`, wrap the request-handling loop in
  `llm.override(llm_config)` so `load_llm_config()` inside `run_one` returns the
  tenant's config. Import `llm` inside `_child` alongside the existing
  function-local imports of `run_one` and `build_sandbox` — that block exists to
  keep the parent's import graph small; follow it.
- Add a comment saying why the config is passed as data rather than inherited: a
  `ContextVar` does not cross a `spawn` boundary, and an env var would be shared
  across concurrent per-org jobs.

In `backend/agentaudit/core/runner.py`, at the `IsolatedRunner(...)`
construction (around line 485), pass the currently-active config:

```python
    isolated = IsolatedRunner(
        target, redactor, endpoint, sandbox_modules(), llm_config=llm.load_llm_config()
    )
```

Resolving it in the parent is the point: that is where the override is
installed. Import `llm` at module scope in `runner.py` if it is not already
imported (`llm.py` does not import `httpx` at module scope, so this is safe).

**Verify**: `python -m pytest tests/test_isolation.py tests/test_runner.py` →
all pass.

### Step 4: Add the tests

See "Test plan" below.

**Verify**: `python -m pytest tests/test_isolation.py tests/test_llm.py tests/test_web.py`
→ all pass, including the new tests.

### Step 5: Full validation

**Verify**:

- `python -m ruff check .` → `All checks passed!`
- `python -m pytest` → `1066 passed` or more, `0 failed`

## Test plan

**`tests/test_llm.py` — egress on the dial (the security half):**

1. `build_client` with a role whose endpoint resolves to a private address
   raises `AttackerUnavailable` (not `None`, not a successful client). Stub the
   resolver the way `tests/test_egress.py` does — read that file for the
   established stubbing pattern and reuse it rather than monkeypatching DNS.
2. `build_client` with a role whose endpoint has an `http://` scheme raises
   `AttackerUnavailable` when `AGENTAUDIT_EGRESS_ALLOW_LOCAL` is unset.
3. `build_client` with a well-formed public https endpoint returns a client
   whose `validated.pinned_url` uses the resolved address, not the hostname.

**`tests/test_web.py` — save-time rejection:**

4. `PUT /api/settings/llm` with a private-address endpoint returns 400 and the
   row is not saved. Model it on the existing settings tests in that file.

**`tests/test_isolation.py` — the spawn crossing (the feature half):**

5. A config set in the parent is visible inside the child. The cheapest honest
   assertion: run a test through `IsolatedRunner` with
   `llm_config=<a stub LLMConfig>` and have the child-side code path report what
   `llm.load_llm_config()` returned. Read `tests/test_isolation.py` first —
   there are 7 existing tests and they establish how this suite drives a real
   child process; follow whichever of them already round-trips a value, rather
   than inventing a new harness.
6. The negative control: with `llm_config=None`, the child falls back to
   `_from_env()` as before. This pins that you have not broken offline runs.

**Structural patterns**: `tests/test_egress.py` for resolver stubbing,
`tests/test_isolation.py` for child-process tests, `tests/test_web.py` for
`TestClient` route tests.

**Verification**: `python -m pytest` → all pass, including 6 new tests.

## Done criteria

ALL must hold:

- [ ] `python -m ruff check .` exits 0 with `All checks passed!`
- [ ] `python -m pytest` exits 0 with at least `1066 passed`, `0 failed`
- [ ] `grep -n "import httpx" backend/agentaudit/core/` finds it only in
      `agent.py` (the single-import rule still holds)
- [ ] `grep -n "llm_config" backend/agentaudit/core/isolation.py` shows it in
      both `IsolatedRunner.__init__`'s `_args` tuple and `_child`'s signature
- [ ] `grep -n "validate_endpoint" backend/agentaudit/core/llm.py` returns a match
- [ ] 6 new tests exist across the four test files listed above
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `plans/README.md` status row for 015 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts in "Current state" do not match the live code.
- `IsolatedRunner`'s `_args` tuple and `_child`'s parameter list are already out
  of sync before your change — that is a different bug and this plan's premise
  is wrong.
- Making the child see the config appears to require pickling something that
  cloudpickle refuses, or requires putting the API key into `os.environ`. Stop:
  the env-var route is explicitly out of scope, and a pickling failure means the
  config object needs a different carrier than this plan assumes.
- `validate_endpoint` rejects a legitimate mainstream provider endpoint (e.g. a
  CDN-fronted host) in your manual check. Pinning plus a `Host` rewrite can
  break CDN-fronted APIs. **Do not** weaken the check to make it pass — report
  it, because the right answer is a product decision about which providers are
  supported, not a quieter security control.
- A step's verification fails twice after a reasonable fix attempt.
- You find yourself changing `backend/agentaudit/worker.py`.

## Maintenance notes

- The two halves are coupled on purpose. If a future change ever reverts the
  egress validation in `build_client`, the spawn-crossing fix immediately
  becomes a tenant-controlled SSRF again. A reviewer should treat any PR that
  touches `build_client`'s validation as security-relevant.
- `HTTPAttacker` now has two dial modes (validated and raw). The raw mode exists
  for direct construction in tests. If it ever becomes reachable from production
  code again, that is a regression — worth a grep in review.
- The child now receives the resolved API key as pickled data. That is the
  correct carrier given concurrent per-org jobs, but it means the key crosses a
  cloudpickle boundary, same as `Redactor` already does. Anyone adding logging
  to `_child` must not log its arguments.
- Deferred out of this plan, and still open after it lands:
  - Tenant LLM API keys are stored as plain `TEXT` (`store.py:1051-1076`,
    migration `0016`) and are absent from the run redactor's literals
    (`worker.py:203-208`). Encryption at rest plus adding the key to the
    redactor's literals is a separate change.
  - `build_attacker` still returns `None` when unconfigured without setting
    `_Provenance.degraded`, so a report cannot distinguish "adaptive ran with a
    model" from "adaptive silently fell back to the scripted ladder". Worth
    fixing once the config actually arrives.
