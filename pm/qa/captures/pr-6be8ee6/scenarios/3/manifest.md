---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-10
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
pm qa list
pm qa show tui-manual-test
pm qa show tmux-screen-recording
pm qa show cli-recording --category artifacts
pm qa show does-not-exist
EDITOR=true pm qa add-instruction my-new-inst
pm qa --help | grep author
pm qa author-instruction my-new-inst   # already exists -> exit 1
pm qa regression nonexistent-id
pm qa regression --help | grep file-prs
pm tui --help
pm tui test                            # removed -> exit 2
pm qa docs
```

## What this demonstrates

End-to-end exercise of the `pm qa` CLI surface in a freshly-`pm
init`'d throwaway project: list with three labeled sections,
show across categories (auto-detect + explicit), add-* template
scaffolding, idempotent author-* short-circuit, regression help
flag, and confirmation that `pm tui test` is no longer a
subcommand. Includes `pm qa docs` which streams the packaged
qa_library.md.

## Pre-fix vs post-fix

This scenario is exercising the QA CLI surface, not a bug fix.
The capture covers a single state. Note: a packaging bug was found
during step 26 (fresh-install path) where `pm_core.watchers` was
not declared in `[tool.setuptools].packages`; the fix is committed
in this same QA run (see `qa: ` commit).

## Files

- recording.cast — asciinema replay (`asciinema play recording.cast`)
- transcript.log — plain-text run of the same script for grep/diff
- manifest.md — this file
