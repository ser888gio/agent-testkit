#!/usr/bin/env bash
# Run agentkit's validation ladder: lint + tests.
#
# Usage:
#   tools/validate.sh                 lint changed files + full pytest suite
#   tools/validate.sh --affected      lint changed files + only the affected tests
#   tools/validate.sh --affected --base <ref>
#                                     affected scope relative to <ref>
#   tools/validate.sh --lint-only     lint changed files, skip tests
#   tools/validate.sh --lint-all      lint the entire repository (see note below)
#
# The full suite runs in a few seconds, so --affected is for tight iteration loops;
# prefer the default before declaring work complete.
#
# Exit codes: the first failing step's exit code is preserved; 2 on usage error.
set -euo pipefail

cd "$(dirname "$0")/.."

AFFECTED=0
LINT_ONLY=0
LINT_ALL=0
BASE_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --affected)  AFFECTED=1; shift ;;
    --lint-only) LINT_ONLY=1; shift ;;
    --lint-all)  LINT_ALL=1; shift ;;
    --base)
      [[ $# -ge 2 ]] || { echo "error: --base requires a ref" >&2; exit 2; }
      BASE_ARGS=(--base "$2")
      shift 2
      ;;
    -h|--help)   sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)           echo "error: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

# Pick a python runner that actually works here.
#
# CI uses `uv run --extra dev`. That currently fails on Windows with
# "package directory 'frontend\agentkit\config' does not exist" (setuptools cannot resolve
# the multi-root namespace package layout), so probe uv before committing to it and fall
# back to the local venv or bare python.
# Candidates in preference order. Not every environment has every tool: the local .venv
# here has pytest but no ruff, so prefer a candidate that provides BOTH before settling.
candidates=()
command -v uv >/dev/null 2>&1                 && candidates+=("uv run --extra dev")
[[ -x ".venv/Scripts/python.exe" ]]           && candidates+=(".venv/Scripts/python.exe -m")
[[ -x ".venv/bin/python" ]]                   && candidates+=(".venv/bin/python -m")
command -v python >/dev/null 2>&1             && candidates+=("python -m")

RUN=()
FALLBACK=()
for c in "${candidates[@]}"; do
  read -r -a parts <<< "$c"
  "${parts[@]}" pytest --version >/dev/null 2>&1 || continue
  [[ ${#FALLBACK[@]} -eq 0 ]] && FALLBACK=("${parts[@]}")
  if "${parts[@]}" ruff --version >/dev/null 2>&1; then
    RUN=("${parts[@]}")
    break
  fi
done

if [[ ${#RUN[@]} -eq 0 && ${#FALLBACK[@]} -gt 0 ]]; then
  echo "error: found a python runner ('${FALLBACK[*]}') but ruff is not available in it" >&2
  echo "       install it with 'uv sync --extra dev' or 'pip install ruff'" >&2
  exit 1
fi

if [[ ${#RUN[@]} -eq 0 ]]; then
  echo "error: no working python runner found (tried uv, .venv, python)" >&2
  echo "       run 'uv sync --extra dev' or activate a virtualenv first" >&2
  exit 1
fi
echo "==> runner: ${RUN[*]}"

if [[ "$LINT_ALL" -eq 1 ]]; then
  echo "==> ruff check . (whole repository)"
  "${RUN[@]}" ruff check .
else
  # shellcheck disable=SC2207
  LINT_FILES=($(bash tools/affected.sh --files-only "${BASE_ARGS[@]}" | grep '\.py$' || true))
  if [[ ${#LINT_FILES[@]} -eq 0 ]]; then
    echo "==> ruff: no changed Python files to lint"
  else
    echo "==> ruff check ${LINT_FILES[*]}"
    "${RUN[@]}" ruff check "${LINT_FILES[@]}"
  fi
fi

if [[ "$LINT_ONLY" -eq 1 ]]; then
  echo "==> lint only: done"
  exit 0
fi

if [[ "$AFFECTED" -eq 1 ]]; then
  # shellcheck disable=SC2207
  TARGETS=($(bash tools/affected.sh --tests-only "${BASE_ARGS[@]}"))
  if [[ ${#TARGETS[@]} -eq 0 ]]; then
    echo "==> no affected tests; nothing to run"
    echo "    (run 'bash tools/affected.sh' to see why, or 'tools/validate.sh' for the full suite)"
    exit 0
  fi
  echo "==> pytest ${TARGETS[*]}"
  "${RUN[@]}" pytest "${TARGETS[@]}"
else
  echo "==> pytest (full suite)"
  "${RUN[@]}" pytest
fi

echo "==> validation passed"
