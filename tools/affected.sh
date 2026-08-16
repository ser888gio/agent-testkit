#!/usr/bin/env bash
# Map changed files to the agentaudit components and pytest targets they affect.
#
# Usage:
#   tools/affected.sh [--base <ref>] [--tests-only | --components-only | --files-only]
#
#   (no args)          diff the working tree (unstaged + staged) against HEAD;
#                      if that is empty, fall back to the merge-base with the default branch
#   --base <ref>       diff against <ref> instead (e.g. --base develop, --base origin/main)
#   --tests-only       print only the pytest target list (for scripting)
#   --components-only  print only the affected component names
#   --files-only       print only the changed files that still exist on disk
#
# Exit codes: 0 success (even when nothing is affected), 2 usage error.
set -euo pipefail

cd "$(dirname "$0")/.."

DEFAULT_BRANCH="develop"
BASE=""
MODE="full"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      [[ $# -ge 2 ]] || { echo "error: --base requires a ref" >&2; exit 2; }
      BASE="$2"
      shift 2
      ;;
    --tests-only)      MODE="tests"; shift ;;
    --components-only) MODE="components"; shift ;;
    --files-only)      MODE="files"; shift ;;
    -h|--help)         sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)                 echo "error: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

if [[ -n "$BASE" ]]; then
  git rev-parse --verify --quiet "$BASE" >/dev/null \
    || { echo "error: '$BASE' is not a valid git ref" >&2; exit 2; }
  CHANGED="$(git diff --name-only "$BASE")"
  SOURCE="diff vs $BASE"
else
  # Untracked files matter too: a brand-new module or test is "affected" but invisible to
  # `git diff`.
  CHANGED="$(git diff --name-only
             git diff --name-only --staged
             git ls-files --others --exclude-standard)"
  SOURCE="working tree, including untracked"
  if [[ -z "$CHANGED" ]]; then
    if MB="$(git merge-base HEAD "$DEFAULT_BRANCH" 2>/dev/null)"; then
      CHANGED="$(git diff --name-only "$MB")"
      SOURCE="diff vs merge-base with $DEFAULT_BRANCH"
    fi
  fi
fi

CHANGED="$(printf '%s\n' "$CHANGED" | sed '/^$/d' | sort -u)"

components=""
tests=""
full_suite=0

add_component() { case " $components " in *" $1 "*) ;; *) components="$components $1" ;; esac; }
add_test()      { case " $tests "      in *" $1 "*) ;; *) tests="$tests $1"           ;; esac; }

while IFS= read -r file; do
  [[ -n "$file" ]] || continue
  case "$file" in
    # Documentation has no test implication. Must precede the directory patterns below,
    # or a CLAUDE.md inside a source tree would select that tree's tests.
    *.md|docs/*) ;;

    # Build/config changes invalidate the whole selection.
    pyproject.toml|uv.lock)
      full_suite=1 ;;

    backend/agentaudit/core/sandbox.py)
      add_component core; add_test tests/test_sandbox_core.py ;;
    backend/agentaudit/core/*.py)
      add_component core
      module="$(basename "$file" .py)"
      candidate="tests/test_${module}.py"
      # Not every core module has a same-named test file; fall back to the full suite.
      if [[ -f "$candidate" ]]; then add_test "$candidate"; else full_suite=1; fi
      # Contract modules ripple through every consumer.
      case "$module" in
        schema|config|assertions) full_suite=1 ;;
      esac
      # Security-sensitive modules always pull in the security invariants.
      case "$module" in
        redaction|store|runner|config) add_test tests/test_security_p0.py ;;
      esac
      ;;

    backend/agentaudit/domains/treasury/*) add_component domains; add_test tests/test_treasury.py ;;
    backend/agentaudit/domains/email/*)    add_component domains; add_test tests/test_email.py ;;
    backend/agentaudit/domains/*)          add_component domains; add_test tests/test_sandbox_core.py ;;

    backend/agentaudit/reports/*)
      add_component reports
      add_test tests/test_reports.py
      add_test tests/test_compliance.py ;;

    frontend/agentaudit/web/*)
      add_component web
      add_test tests/test_web.py
      add_test tests/test_security_p0.py ;;

    backend/agentaudit/cli.py)      add_component cli;  add_test tests/test_cli.py ;;
    agentaudit/config/*)    add_component cli;  add_test tests/test_config.py ;;
    agentaudit/packs/*)
      add_component packs
      add_test tests/test_packs_core.py
      add_test tests/test_packs_domain.py
      add_test tests/test_loader.py ;;

    tests/*.py)  add_component tests; add_test "$file" ;;
    tools/*|infra/*) add_component infra ;;
    *) ;;                                # unmapped: no test implication
  esac
done <<< "$CHANGED"

if [[ "$full_suite" -eq 1 ]]; then
  tests="tests"
  add_component core
fi

components="$(printf '%s' "$components" | tr ' ' '\n' | sed '/^$/d' | sort -u | tr '\n' ' ')"
tests="$(printf '%s' "$tests" | tr ' ' '\n' | sed '/^$/d' | sort -u | tr '\n' ' ')"

case "$MODE" in
  tests)      printf '%s\n' "$tests" ;;
  components) printf '%s\n' "$components" ;;
  files)
    # Only files that still exist; a deleted file cannot be linted.
    for f in $CHANGED; do [[ -f "$f" ]] && printf '%s\n' "$f"; done
    ;;
  full)
    echo "Changed files ($SOURCE):"
    if [[ -z "$CHANGED" ]]; then
      echo "  (none)"
    else
      printf '  %s\n' $CHANGED
    fi
    echo
    echo "Affected components: ${components:-(none)}"
    echo "Pytest targets:      ${tests:-(none)}"
    if [[ "$full_suite" -eq 1 ]]; then
      echo
      echo "Note: a contract or build-config file changed, so the full suite is selected."
    fi
    ;;
esac
