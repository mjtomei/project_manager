---
pr: pr-6be8ee6
scenario: 38
workdir: /workspace
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
# Setup
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
cd /workspace && pip install -e . && export PYTHONPATH=/workspace
TEST_DIR=/tmp/pm-qa-cli-capture-...; mkdir -p $TEST_DIR && cd $TEST_DIR
git init && pm init --backend local --no-import && pm pr add "Seed PR"

# Steps exercised in the cast
pm qa add foo                                      # step 3 — removed
EDITOR=true pm qa add-instruction my-inst          # step 4
EDITOR=true pm qa add-regression  my-reg
EDITOR=true pm qa add-artifact    my-art
EDITOR=true pm qa add-instruction my-inst          # step 5 — clobber refused
pm qa list                                         # step 6
pm qa show my-art                                  # step 7 — auto-resolve
pm qa show -c instructions my-art                  # step 7 — wrong category, exit 1
EDITOR=true pm qa edit my-art                      # step 8
EDITOR=true pm qa edit does-not-exist              # step 8 — exit 1
# overwrite my-inst with legacy `tags: [foo]` frontmatter (step 9b)
pm qa list                                         # row reads "my-inst: My Inst — desc"
EDITOR=true pm qa add-instruction another-inst
PATH=/tmp/wrap-bin:$PATH pm qa author-instruction another-inst   # step 11 — refuses
```

## What this demonstrates

End-to-end pm qa CLI surface for scenario 38: the old `pm qa add` is
gone (click prints "No such command 'add'." with exit 2 and no
traceback); the three `add-*` siblings scaffold files with category-
appropriate templates and refuse to clobber existing files (exit 1);
`pm qa list` renders the three labeled sections in order
(Instructions, Regression Tests, Artifact Recipes) with parenthesised
counts; `pm qa show` auto-resolves an unqualified id but refuses to
fall back when `-c` pins the wrong category; `pm qa edit` round-trips
through `$EDITOR=true` and exits 1 for unknown ids; the frontmatter
loader tolerates a legacy `tags:` field (the row still renders
correctly and no tags are surfaced); and `pm qa author-*` refuses to
launch claude when the target file already exists.

Author-* path resolution and prompt embedding (step 10) is not
included in the cast because it requires intercepting the launched
`claude` argv via /proc; that verification was done out-of-band with
a wrapper script in /tmp/wrap-bin/claude and confirmed:
- final argv contains `pm/qa/instructions/another-inst.md`
- prompt contains `## Reference: pm QA library`
- prompt contains qa_library.md content (`Frontmatter` heading)
- argv contains `--session-id <uuid>` (no `--resume`)
- killing the launcher before any response leaves the target file
  uncreated.

## Files

- `recording.cast` — asciinema replay of the steps above (run via the
  no-TTY-friendly `asciinema rec -c <script>` form documented in the
  recipe).
- `transcript.log` — plain-text stdout/stderr captured in parallel
  with `tee` — load-bearing for grep.
- `manifest.md` — this file.
- `prompt.md` — scenario prompt as delivered to this QA session
  (pre-existing).
