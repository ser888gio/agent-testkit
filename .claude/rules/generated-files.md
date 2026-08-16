---
description: Generated, vendored, and build-artifact paths that must never be hand-edited
paths:
  - "dist/**"
  - "agentaudit.egg-info/**"
  - "uv.lock"
  - "agentaudit.db"
  - "docs/diagrams/**"
  - "**/__pycache__/**"
---

# Generated and vendored files

Never edit these by hand. A `PreToolUse` hook (`tools/guard-protected-paths.sh`) blocks
writes to most of them.

| Path | Regenerate with |
| --- | --- |
| `dist/` | `uv build` |
| `agentaudit.egg-info/` | any editable install (`pip install -e .`) |
| `uv.lock` | `uv lock` (or `uv add <pkg>`) — never hand-merge |
| `agentaudit.db` | delete it; the next `agentaudit run` recreates it |
| `docs/diagrams/*.svg` | re-render from the `.d2` source beside it |
| `**/__pycache__/` | delete freely; Python recreates it |

`agentaudit.db` is a gitignored local artifact — safe to delete when its schema drifts after a
`store.py` change. Do not write migrations for it; it is a developer cache, not user data.

`docs/diagrams/` ships light and dark SVG variants per diagram. Editing one and not the
other leaves the README broken in the opposite colour scheme — always re-render both from
the `.d2` source.
