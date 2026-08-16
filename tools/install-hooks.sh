#!/usr/bin/env bash
# Installs the repo's git hooks. Run once per clone.
#
# Copies rather than symlinks: `qlty githooks install` symlinks, which fails on
# Windows without Developer Mode (os error 1314).
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
hooks_dir="$repo_root/$(git rev-parse --git-path hooks)"
mkdir -p "$hooks_dir"

for src in "$repo_root"/.qlty/hooks/*.sh; do
  [ -e "$src" ] || continue
  name=$(basename "$src" .sh)
  cp "$src" "$hooks_dir/$name"
  chmod +x "$hooks_dir/$name"
  echo "installed: $name"
done
