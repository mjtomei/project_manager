---
title: TUI QA pane — three sections, status counter, picker routing
description: tmux + asciinema capture driving the QA pane open/close, empty-artifacts redraw, empty-name picker no-op, name+Artifact-recipe Enter launches author-artifact pane, regression Enter launches build_regression_test_prompt, and Esc dismisses the picker.
---

## Workdir

- Capture produced from a throwaway pm project at `/workspace/pm-test-rec` (re-created from scratch for the recording).
- PR workdir for the change under test: `/workspace`.

## Commands

```
# project setup
mkdir -p /workspace/pm-test-rec && cd /workspace/pm-test-rec && git init
pm init --backend local --no-import
pm pr add "Test PR A" --plan bugs --description t
pm pr add "Test PR B" --plan ux  --description t
mkdir -p pm/qa/{instructions,regression,artifacts}
# one minimal frontmatter file per category
( pm session >/dev/null 2>&1 ) &
TARGET=$(pm session name)

# transcript + asciinema recorder (recipe: tmux-screen-recording.md)
tmux pipe-pane -t "$TARGET:0.0" -o "cat >> .../transcript.log"
tmux new-session -d -s pm-recorder -x 200 -y 50 \
    "asciinema rec --quiet .../recording.cast -c 'tmux attach -t $TARGET'"

# driver (one Then per triple)
pm tui send q  -s "$TARGET"          # open QA pane    → 3 sections, total=3
pm tui send q  -s "$TARGET"          # close
rm pm/qa/artifacts/*.md
pm tui send q  -s "$TARGET"          # reopen          → Artifact Recipes (0) still shown, total=2
pm tui send a  -s "$TARGET"          # open picker
pm tui send Enter -s "$TARGET"       # empty-name submit → no-op, picker stays
pm tui send demo-recipe -s "$TARGET"
pm tui send down -s "$TARGET"        # → Regression test
pm tui send down -s "$TARGET"        # → Artifact recipe
pm tui send Enter -s "$TARGET"       # launches qa-author pane: pm qa author-artifact demo-recipe
# switch focus back to %0, navigate to regression, Enter
pm tui send j -s "$TARGET"
pm tui send Enter -s "$TARGET"       # launches qa-item pane: claude with build_regression_test_prompt
# re-open picker, Esc
pm tui send a -s "$TARGET"
pm tui send Escape -s "$TARGET"      # picker dismissed, no pane, no file
```

## Findings

- Triple 1 (q → three sections, status counter): PASS. Status bar read `QA    3 item(s)`; section headers `Instructions (1)`, `Regression Tests (1)`, `Artifact Recipes (1)` rendered in order.
- Triple 2 (empty artifacts, reopen): PASS. `Artifact Recipes (0)` header still rendered; total dropped to 2.
- Triple 3 (empty-name Enter): PASS. Picker stayed open; `pm/qa/artifacts/` remained empty.
- Triple 4 (name + Artifact recipe + Enter): PASS. TUI footer printed `Launched qa-author pane`; the new pane's scrollback shows the `pm qa author-artifact demo-recipe` prompt (text: "Work with the user to author a new artifact recipe ... pm/qa/artifacts/demo-recipe.md").
- Triple 5 (regression Enter): PASS. New pane runs `claude` with the regression prompt; scrollback contains the `## Captures` section referencing `pm/qa/captures/regression/<test-id>/<timestamp>/` (matches `build_regression_test_prompt`).
- Triple 6 (Esc on picker): PASS. Picker dismissed, no new pane, no file created.

## Files

- `transcript.log` — tmux `pipe-pane` scrollback of the home pane (%0) for the entire driver run.
- `recording.cast` — asciinema replay of the recorder's `tmux attach` against the same session.
- `prompt.md` — scenario prompt (pre-existing, planner-provided).
- `manifest.md` — this file.
