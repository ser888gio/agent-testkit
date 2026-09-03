"""Process-wide state the web tier shares: the Store and the env-driven paths.

Split out of ``app.py`` so both the HTML entrypoint and the JSON API
(``api.py``) depend on it without importing each other.

Run *policy* -- which paths may be loaded, how a target is registered, how a
run is queued -- is not here. It moved to ``core.intake``, which knows nothing
about HTTP and is reusable from the CLI; see that module's docstring.
"""

from __future__ import annotations

import os
from pathlib import Path

from agentaudit.core.intake import PACKAGE_DIR, is_pack_dir
from agentaudit.core.loader import discover
from agentaudit.core.schema import TestCase
from agentaudit.core.store import Store

BASE_DIR = Path(__file__).parent

# Pack that tenant-authored tests land in, one per org.
USER_PACK_ID = "user"

__all__ = [
    "BASE_DIR",
    "PACKAGE_DIR",
    "USER_PACK_ID",
    "close_store",
    "get_artifacts_dir",
    "get_db_path",
    "get_packs_dir",
    "get_store",
    "is_pack_dir",
    "shipped_tests",
]


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
