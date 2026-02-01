#!/usr/bin/env bash
set -euo pipefail
echo "Running integrity checks..."
for check in checks/check-*.sh; do
  [ -f "$check" ] && bash "$check"
done
echo "All checks passed."
