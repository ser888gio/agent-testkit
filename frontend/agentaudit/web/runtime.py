"""Process-wide state the web tier shares: the Store, paths, and path safety.

Split out of ``app.py`` so both the HTML entrypoint and the JSON API
(``api.py``) depend on it without importing each other.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml
from fastapi import HTTPException

import agentaudit
from agentaudit.core.loader import LoaderError, discover
from agentaudit.core.schema import TestCase
from agentaudit.core.store import Store

BASE_DIR = Path(__file__).parent
PACKAGE_DIR = Path(agentaudit.__file__).resolve().parent
# Roots the web run route is allowed to load targets/packs from. Callers pass
# paths relative to these; anything resolving outside is rejected, so the route
# can never be coaxed into loading arbitrary Python callables.
ALLOWED_ROOTS = (PACKAGE_DIR / "config", PACKAGE_DIR / "packs")

# Pack that tenant-authored tests land in, one per org.
USER_PACK_ID = "user"

_ENV_REFS_RE = re.compile(r"\$\{([A-Za-z_]\w*)\}")


def resolve_within_allowed(value: str) -> Path:
    candidate = Path(value).resolve()
    for root in ALLOWED_ROOTS:
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        if candidate.exists():
            return candidate
    raise HTTPException(
        status_code=400,
        detail="target/packs must resolve to a file under config/ or packs/",
    )


def get_db_path() -> str:
    return os.environ.get("AGENTAUDIT_DB", "database/agentaudit.db")


def get_packs_dir() -> Path:
    return Path(os.environ.get("AGENTAUDIT_PACKS", str(PACKAGE_DIR / "packs")))


def get_artifacts_dir() -> Path:
    return Path(os.environ.get("AGENTAUDIT_ARTIFACTS_DIR", "database/artifacts"))


# One long-lived Store per process instead of one connection per handler call.
# Store hands each thread its own connection and reuses it, so the open-handle
# count tracks the (bounded) threadpool rather than the request count.
_store: Store | None = None
_store_path: str | None = None


def get_store() -> Store:
    global _store, _store_path
    path = get_db_path()
    if _store is None or _store_path != path:
        # The path only changes under tests, which point AGENTAUDIT_DB at a tmp
        # dir per case; closing the old one keeps them from accumulating.
        if _store is not None:
            _store.close()
        _store = Store(path)
        _store_path = path
    return _store


def close_store() -> None:
    global _store, _store_path
    if _store is not None:
        _store.close()
    _store = None
    _store_path = None


def is_pack_dir(p: Path) -> bool:
    """Tooling and cache directories live beside the packs; they are not packs."""
    return p.is_dir() and not p.name.startswith((".", "__"))


def shipped_tests() -> list[tuple[str, TestCase]]:
    """(pack_id, TestCase) for every YAML test in the shipped packs directory."""
    packs_root = get_packs_dir()
    if not packs_root.is_dir():
        return []
    return [
        (pack_dir.name, test)
        for pack_dir in sorted(p for p in packs_root.iterdir() if is_pack_dir(p))
        for test in discover(str(pack_dir))
        if isinstance(test, TestCase)
    ]


def first_party_secret_ref(raw: dict) -> str | None:
    """Map a shipped config's single `${VAR}` reference to an `env://VAR` ref."""
    names = sorted(set(_ENV_REFS_RE.findall(json.dumps(raw))))
    if not names:
        return None
    if len(names) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"target references several secrets ({', '.join(names)}); "
            "register it as a target with an explicit secret_ref instead",
        )
    return f"env://{names[0]}"


def first_party_hosts(raw: dict) -> list[str] | None:
    """Seed the egress allowlist from the endpoint the shipped config declares."""
    agent = raw.get("agent") or {}
    if not isinstance(agent, dict) or agent.get("type") != "http":
        return None
    from urllib.parse import urlsplit

    host = urlsplit(str(agent.get("endpoint", ""))).hostname
    return [host] if host else []


def import_first_party(store: Store, org_id: str, target: str, packs: str) -> tuple[str, str]:
    """Copy a shipped target and pack into the caller's org as rows.

    The worker resolves jobs from the database only, so a run launched against
    a first-party target has to exist as rows before it can be queued. Both
    writes are idempotent upserts, so re-running the same pack is free.

    The config is stored **unexpanded**: only the worker resolves secrets, and
    only for the run it is executing.
    """
    target_path = resolve_within_allowed(target)
    pack_dir = resolve_within_allowed(packs)
    tests = discover(str(pack_dir))
    rows = []
    for test in tests:
        if not isinstance(test, TestCase):
            raise HTTPException(
                status_code=400,
                detail="Python test cases cannot be queued; use a YAML pack.",
            )
        rows.append(test.model_dump(mode="json", exclude_defaults=True))

    try:
        raw = yaml.safe_load(target_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"malformed target: {exc}") from exc
    if not isinstance(raw, dict) or not raw.get("id"):
        raise HTTPException(status_code=400, detail="target config needs an 'id'")
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
        store.save_pack(org_id, pack_dir.name, pack_dir.name, rows)
    except (LoaderError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return target_id, pack_dir.name
