"""Turning a request to run something into rows the worker can execute.

Between "an operator picked a target and a pack" and "a job exists" sits a
policy: which paths may be loaded at all, which host a tenant's target may be
dialled at, which secret reference a shipped config maps to, and whether the
test ids a client sent actually belong to the pack that was imported. None of
that is HTTP, and none of it is persistence -- but all of it used to live
inside FastAPI route handlers, so the only way to assert any of it was to
serve a request and read the response back.

That mattered for more than test ergonomics. The same questions are answered a
second time, differently, by the CLI: `cli._load_target_or_exit` resolves a
target from a path or an endpoint with no allowlist seeding at all. Two
spellings of one policy, and the security-relevant half was the one with no
interface of its own.

Everything here raises `IntakeError` and knows nothing about status codes.
`web/app.py` maps that onto a 400; the CLI can print it. Callers pass a
`Store`; this module never opens one, and never dials an agent -- it produces
rows, and the worker is what executes them.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

import agentaudit
from agentaudit.core.attacks import TRANSFORMS
from agentaudit.core.config import ConfigError, load_target_dict
from agentaudit.core.loader import LoaderError, discover
from agentaudit.core.schema import TestCase

PACKAGE_DIR = Path(agentaudit.__file__).resolve().parent

# Roots a run may load targets and packs from. Callers pass paths relative to
# these; anything resolving outside is rejected, so intake can never be coaxed
# into loading an arbitrary Python callable.
ALLOWED_ROOTS = (PACKAGE_DIR / "config", PACKAGE_DIR / "packs")

_ENV_REFS_RE = re.compile(r"\$\{([A-Za-z_]\w*)\}")

_DEMO_TRUTHY = frozenset({"1", "true", "yes"})


class IntakeError(ValueError):
    """A run could not be assembled from what the caller asked for.

    Always the caller's fault and always safe to show them: these carry the
    name of a target or pack the caller supplied, never internal state.
    """


def resolve_within_allowed(value: str) -> Path:
    """The file `value` names, if it sits under an allowed root.

    Relative values are resolved against `PACKAGE_DIR.parent`, not the process
    CWD. Those coincide in a repo checkout and do not in the container, where
    the package sits in site-packages and the CWD is elsewhere.
    """
    raw = Path(value)
    candidate = (raw if raw.is_absolute() else PACKAGE_DIR.parent / raw).resolve()
    for root in ALLOWED_ROOTS:
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        if candidate.exists():
            return candidate
    raise IntakeError("target/packs must resolve to a file under config/ or packs/")


def first_party_secret_ref(raw: dict) -> str | None:
    """Map a shipped config's single `${VAR}` reference to an `env://VAR` ref."""
    names = sorted(set(_ENV_REFS_RE.findall(json.dumps(raw))))
    if not names:
        return None
    if len(names) > 1:
        raise IntakeError(
            f"target references several secrets ({', '.join(names)}); "
            "register it as a target with an explicit secret_ref instead"
        )
    return f"env://{names[0]}"


def first_party_hosts(raw: dict) -> list[str] | None:
    """Seed the egress allowlist from the endpoint the shipped config declares."""
    agent = raw.get("agent") or {}
    if not isinstance(agent, dict) or agent.get("type") != "http":
        return None
    host = urlsplit(str(agent.get("endpoint", ""))).hostname
    return [host] if host else []


def is_pack_dir(p: Path) -> bool:
    """Tooling and cache directories live beside the packs; they are not packs."""
    return p.is_dir() and not p.name.startswith((".", "__"))


def demo_mode() -> bool:
    return os.environ.get("AGENTAUDIT_DEMO_MODE", "").strip().lower() in _DEMO_TRUTHY


def is_offerable_target(path: Path) -> bool:
    """Whether a shipped target is worth offering in the picker.

    Under demo mode only in-process (`type: callable`) targets are offered. The
    shipped HTTP configs point at hosts that do not exist, at loopback (which
    the worker egress policy refuses), or at credential templates -- each a
    dead end for a visitor on a hosted instance.
    """
    if not demo_mode():
        return True
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(loaded, dict):
        return False
    agent = loaded.get("agent")
    return isinstance(agent, dict) and agent.get("type") == "callable"


def register_http_target(
    store,
    org_id: str,
    *,
    target_id: str,
    endpoint: str,
    sandbox: str = "",
    method: str = "POST",
    text_path: str = "$.text",
    input_path: str = "input",
) -> str:
    """Persist a tenant-authored HTTP target; returns its id.

    The endpoint host seeds the egress allowlist, so a target the tenant typed
    is only reachable at the host they typed. The assembled config is validated
    through `load_target_dict` -- the same shape a shipped YAML config produces
    -- so a bad endpoint fails here rather than in a worker later.
    """
    target_id = target_id.strip()
    endpoint = endpoint.strip()
    if not target_id:
        raise IntakeError("Target id is required.")
    parts = urlsplit(endpoint)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise IntakeError("Endpoint must be an absolute http:// or https:// URL.")

    raw: dict = {
        "id": target_id,
        "agent": {
            "type": "http",
            "endpoint": endpoint,
            "method": method,
            # Without a request body the agent is POSTed nothing; the shipped
            # YAML configs all carry this. One JSON key is the whole shape a
            # form can ask for -- nested bodies need a YAML config.
            "request": {"json": {input_path or "input": "{{ input }}"}},
            "response": {"text_path": text_path or "$.text"},
        },
    }
    if sandbox:
        raw["sandbox"] = sandbox
    try:
        load_target_dict(raw, source=f"target '{target_id}'")
    except ConfigError as exc:
        raise IntakeError(str(exc)) from exc
    try:
        store.save_target(org_id, target_id, target_id, raw, allowed_hosts=[parts.hostname])
    except (LoaderError, ValueError) as exc:
        raise IntakeError(str(exc)) from exc
    return target_id


def import_pack(store, org_id: str, packs: str) -> str:
    """Copy a shipped pack into the caller's org as rows; returns the pack id.

    Idempotent upsert, so re-running the same pack is free.
    """
    pack_dir = resolve_within_allowed(packs)
    rows = []
    for test in discover(str(pack_dir)):
        if not isinstance(test, TestCase):
            raise IntakeError("Python test cases cannot be queued; use a YAML pack.")
        rows.append(test.model_dump(mode="json", exclude_defaults=True))
    try:
        store.save_pack(org_id, pack_dir.name, pack_dir.name, rows)
    except (LoaderError, ValueError) as exc:
        raise IntakeError(str(exc)) from exc
    return pack_dir.name


def import_first_party(store, org_id: str, target: str, packs: str) -> tuple[str, str]:
    """Copy a shipped target and pack into the caller's org as rows.

    The worker resolves jobs from the database only, so a run launched against
    a first-party target has to exist as rows before it can be queued. Both
    writes are idempotent upserts, so re-running the same pack is free.

    The config is stored **unexpanded**: only the worker resolves secrets, and
    only for the run it is executing.
    """
    target_path = resolve_within_allowed(target)
    try:
        raw = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise IntakeError(f"malformed target: {exc}") from exc
    if not isinstance(raw, dict) or not raw.get("id"):
        raise IntakeError("target config needs an 'id'")
    target_id = str(raw["id"])

    try:
        store.save_target(
            org_id,
            target_id,
            target_id,
            raw,
            secret_ref=first_party_secret_ref(raw),
            allowed_hosts=first_party_hosts(raw),
        )
    except (LoaderError, ValueError) as exc:
        raise IntakeError(str(exc)) from exc
    return target_id, import_pack(store, org_id, packs)


def resolve_target_and_pack(store, org_id: str, target: str, packs: str) -> tuple[str, str]:
    """The (target_id, pack_id) rows a run against `target` needs.

    `target` is either the id of a target the tenant registered by endpoint URL
    -- whose row already exists, so only the pack needs importing -- or a path
    to a shipped config under the allowed roots.
    """
    try:
        store.get_target(org_id, target)
    except KeyError:
        try:
            resolve_within_allowed(target)
        except IntakeError:
            raise IntakeError(f"unknown target '{target}'") from None
        return import_first_party(store, org_id, target, packs)
    return target, import_pack(store, org_id, packs)


def narrow_selection(store, org_id: str, pack_id: str, test_ids: list[str]) -> list[str] | None:
    """The subset of `pack_id` to run, or None for the whole pack.

    Checked against the pack that was just imported rather than trusted from
    the client. Selecting every test is the same as selecting none: storing it
    as a selection would freeze the pack's current contents into the job.
    """
    if not test_ids:
        return None
    available = {row["id"] for row in store.get_pack_tests(org_id, pack_id)}
    unknown = sorted(set(test_ids) - available)
    if unknown:
        raise IntakeError(f"unknown test(s) for this pack: {', '.join(unknown)}")
    if set(test_ids) == available:
        return None
    return sorted(set(test_ids))


def queue_run(
    store,
    org_id: str,
    *,
    target: str,
    packs: str,
    test_ids: list[str] | None = None,
    timeout_seconds: int | None = None,
    attack_transforms: list[str] | None = None,
    created_by: str | None = None,
) -> str:
    """Assemble the rows a run needs and enqueue it; returns the job id.

    Nothing here dials the agent: the worker executes the job, so this stays
    fast and cannot block on a slow endpoint.
    """
    target_id, pack_id = resolve_target_and_pack(store, org_id, target, packs)
    selection = narrow_selection(store, org_id, pack_id, test_ids or [])
    # `JobQueue.enqueue` rejects an unknown transform too; raising here as well
    # is what turns it into a 400 rather than a 500 on the web path.
    unknown = sorted(set(attack_transforms or []) - set(TRANSFORMS))
    if unknown:
        raise IntakeError(
            f"unknown attack transform(s): {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(TRANSFORMS))}."
        )
    return store.jobs.enqueue(
        org_id,
        target_id,
        pack_id,
        created_by=created_by,
        test_ids=selection,
        timeout_seconds=timeout_seconds,
        attack_transforms=attack_transforms,
    )
