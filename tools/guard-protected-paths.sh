#!/usr/bin/env bash
# Claude Code PreToolUse hook: block writes to generated, vendored, and build-artifact paths.
#
# Reads the tool-call JSON on stdin, extracts the target file path, and exits 2 with an
# explanation on stderr when the path is one that must be regenerated rather than edited.
# Exit 0 allows the call. Any unexpected condition allows the call (fail open) so a hook
# problem never blocks ordinary work.
set -uo pipefail

payload="$(cat)"

# Extract .tool_input.file_path without requiring jq (not guaranteed on Windows dev boxes).
path="$(printf '%s' "$payload" \
  | tr ',' '\n' \
  | grep -m1 '"file_path"' \
  | sed 's/.*"file_path"[[:space:]]*:[[:space:]]*"//; s/"[[:space:]]*}*[[:space:]]*$//')"

[[ -n "$path" ]] || exit 0

# Normalise Windows separators and escaped backslashes to forward slashes.
norm="$(printf '%s' "$path" | sed 's/\\\\/\//g; s/\\/\//g')"

deny() {
  echo "BLOCKED: $norm is a generated/vendored artifact and must not be hand-edited." >&2
  echo "Regenerate it instead: $1" >&2
  echo "See .claude/rules/generated-files.md." >&2
  exit 2
}

case "$norm" in
  */dist/*|dist/*)                       deny "uv build" ;;
  *agentkit.egg-info/*)                  deny "pip install -e ." ;;
  */.venv/*|.venv/*)                     deny "uv sync --extra dev" ;;
  *uv.lock)                              deny "uv lock (or uv add <pkg>)" ;;
  *agentkit.db)                          deny "delete the file; the next 'agentkit run' recreates it" ;;
  */__pycache__/*)                       deny "delete the directory; Python recreates it" ;;
  *.pyc)                                 deny "delete the file; Python recreates it" ;;
  */docs/diagrams/*.svg|docs/diagrams/*.svg)
    deny "re-render from the .d2 source beside it (both light and dark variants)" ;;
esac

exit 0
