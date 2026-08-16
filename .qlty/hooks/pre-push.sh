#!/bin/sh
# Blocks a push when qlty finds high-severity issues in the commits being pushed.
# Installed to .git/hooks/pre-push by tools/install-hooks.sh (copied, not symlinked:
# Windows refuses symlinks without Developer Mode -- os error 1314).
#
# Bypass with: git push --no-verify
set -e

# Compare against the upstream branch when it exists; on a brand-new branch
# there is nothing to diff, so fall back to the default branch.
upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo "develop")

exec qlty check --no-formatters --upstream "$upstream" --fail-level high
