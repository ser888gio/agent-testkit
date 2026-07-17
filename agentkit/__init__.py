"""agentkit package root with split frontend/backend package paths."""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"

_PACKAGE_ROOT = Path(__file__).resolve().parent
__path__ = [str(_PACKAGE_ROOT)]

for _relative in ("BE/agentkit", "FE/agentkit"):
    _candidate = _PACKAGE_ROOT.parent / _relative
    if _candidate.exists():
        __path__.append(str(_candidate))
