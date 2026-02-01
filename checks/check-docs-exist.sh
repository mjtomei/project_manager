#!/usr/bin/env bash
for f in CONTRIBUTING.md docs/governance.md docs/onboarding.md; do
  [ -f "$f" ] || { echo "FAIL: $f missing"; exit 1; }
done
echo "PASS: core docs exist"
