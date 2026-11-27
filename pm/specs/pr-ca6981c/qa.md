# QA Spec: pr-ca6981c — pm merge's stash/pop must never corrupt project.yaml or leak stashes

Supersedes `qa-pre-master-integration-2026-05.md` (written for the
revert-and-reapply design before master's pr-ac10f03 publish flow). Grounded
in `impl.md` and the code at 951bd840 / fa4aa91b.

## Context

`pm pr merge` now *publishes* a signed-off candidate. After publication pm
fast-forwards the user's **main repo checkout**. The checkout holds pm's
live, uncommitted registry `pm/project.yaml` and often other uncommitted
user work. Two places do this, both through `_ff_with_autostash`:

- **local backend**: `_publish_local` fast-forwards the checked-out base to
  the approved merge commit;
- **vanilla / github backend**: `_pull_after_merge` fetches origin and then
  fast-forwards to `origin/<base>`. This also runs for
  `pm pr merge --propagation-only` (recovery).

Before the fix, an overlap between the incoming commit and dirty files went
through git's *text* `stash push` / `stash pop`, the registry included.
Concurrent pm writes, or a committed registry change on the branch, then
made the pop conflict. Markers were written into `pm/project.yaml`, every pm
command broke, the PR stayed un-merged, and `pm: auto-stash for merge`
entries piled up.

The fix:
- **Registry.** It is never text-stashed. It is merged structurally (live
  state wins true conflicts; id-keyed lists such as notes are unioned) and
  swapped in with one atomic rename. The target's blob is staged so git never
  rewrites the file.
- **Lock.** The registry lock is held across the whole local
  fast-forward. Concurrent pm writers serialize against it. A busy lock
  (10 s) fails safe and touches nothing.
- **Other dirty files.** They are stashed by explicit path and popped by
  commit. A conflicted or refused pop keeps the stash and prints
  instructions.
- **Leaked stashes.** Old auto-stashes whose changes are already in the
  working tree are reaped after a successful update. Others are listed.
  User WIP stashes are never touched.
- **Load guard.** `store.load` reports conflict markers clearly instead of
  showing a raw YAML traceback.
- **Git config.** `--no-autostash` overrides a user's `merge.autoStash`.
  `-unormal` overrides `status.showUntrackedFiles=no`. Staged
  deletions and renames stay staged in place.
- **Other.** `pm project set` writes under the lock. The `pr start`
  persist of a GitHub PR number retries under lock contention.

## User-facing surfaces

- `pm pr merge <id>`: local, vanilla and github (fake-github) backends.
- `pm pr merge --propagation-only <id>`: recovery after a failed or
  skipped main-repo update.
- Every command that loads state (`pm pr list`, `pm pr note add`,
  `pm pr edit`, `pm project set`, `pm tui` / `pm session`). These are the
  concurrent writers and readers, and they surface the load guard.
- `pm edit`: holds the registry lock while `$EDITOR` is open. It is the
  natural way to make the lock "busy".
- The TUI: merge key `g` (runs `pr merge --resolve-window`), its file-watch
  reload of `project.yaml`, its YAML-load-error display, and the
  merge-lock overlay shown while pm/ files are stashed.
- `git stash list` / `git status` / the working tree of the main repo.
  This is the user-visible evidence of leaks, staged state and restored
  work.

## Shared resources (concurrency inventory)

| resource | who touches it |
|---|---|
| `pm/project.yaml` (live registry) | every pm command reads it, also before taking the lock; writers via atomic rename; the merge's structural swap; the TUI's reload |
| `pm/project.yaml.lock` (registry flock) | `locked_update` writers (2 s timeout); `pm edit`; the merge (10 s); the reaper's drops (2 s) |
| `pm/project.yaml.tmp` | every atomic save; must never be swept into a stash |
| git stash stack of the main repo | pm auto-stash push and pop (by commit); the reaper; user WIP stashes; leaked pre-fix entries |
| git index of the main repo (`index.lock`) | staging of the registry blob; the user's staged hunks, deletions and renames |
| checked-out base / HEAD of the main repo | two PRs' post-publish updates racing; a user's own commit |
| `origin/<base>` remote-tracking ref | the post-publish fetch; a user's concurrent `git fetch` while pm plans |
| publish lock / per-PR merge lock (`~/.pm/workdirs/.publish-*.lock`, `.merge-*-<pr>.lock`) | concurrent `pm pr merge` of the same PR or of different PRs |
| TUI merge-lock marker | raised and cleared around a stash that contains pm/ files |

## Setup (cross-cutting)

1. **Run the PR's code.** `export PYTHONPATH=<clone>` (the container default
   `/opt/pm-src` is master). `pm which` must print the clone. If `pm` is
   missing, run `./install.sh --local` from the clone.
2. **Use real git.** `~/.local/bin/git` in the QA container is a push-proxy
   shim. It hijacks fetch/pull/ls-remote and breaks local-file fetches.
   Put `/usr/bin/git` first on PATH (for example
   `mkdir /tmp/realgit && ln -s /usr/bin/git /tmp/realgit/git`, then
   `export PATH=/tmp/realgit:$PATH`), and run
   `git config --global protocol.file.allow always`.
3. **Disposable fixture only.** Use a throwaway HOME and a throwaway main
   repo, `git init -b master`. Commit a file or two, then
   `pm init --backend local|vanilla --no-import --base-branch master`, add
   PRs with `pm pr add`, and commit the initial `pm/` state. Add
   `pm/project.yaml.lock` to `.gitignore`. For vanilla and github,
   create a bare repo as `origin` and clone the main checkout from it.
   Never publish to a real remote.
4. **A signed-off PR (gate prerequisite).** The PR needs:
   - a workdir clone on its branch (`pm/<id>-<slug>`, from `pm pr add`)
     with committed changes;
   - status `sign_off`;
   - a recorded SIGNOFF_MERGE bound to a clean integration.

   User path: `pm pr signoff integrate <id> --record`. Then put a
   `report.html` in the session captures dir, with
   `<meta name="pm-signoff-verdict" content="SIGNOFF_MERGE">` and
   `pm-signoff-head` / `pm-signoff-base` set to the recorded head and base
   SHAs (this stands in for the sign-off session's report). Then run
   `pm pr signoff record <id>`. The S74 harness's `setup_fixture.py`
   (captures `impl/s74-harness/`) does the same through the sign-off API
   and can be used as the bootstrap. Setting `status`/`workdir` in the
   registry during bootstrap is allowed (tui-manual-test.md rule).
5. **A committed registry change on the PR branch.** To reach the
   registry-reconcile path, the PR branch must carry a committed
   `pm/project.yaml` change, such as an agent's `pm pr note add` on
   another PR or a `pm pr edit` description run in the workdir. The main
   repo's live registry must also be dirty, which it is after any pm
   command there.
6. **Observation.** There is no `pm pr show`. Use:
   - `pm pr list` / `pm pr list --status merged` for status;
   - `pm pr note list <id>` for notes;
   - the file `pm/project.yaml` for `merged_at`, markers and validity
     (`python -c 'import yaml,sys; yaml.safe_load(open(sys.argv[1]))'`);
   - `git stash list`, `git status --porcelain` and
     `git diff --cached --name-status` in the main repo.

## 1. Requirements (Given / When / Then)

**R1. A merge never writes conflict markers into the registry (the bug).**
- Given: a local-backend project whose signed-off PR P's branch commits a
  registry change (a note on PR Q, a field edit on P), and the main repo's
  live registry has uncommitted edits to the same records (a `pm pr edit`
  title change, a `pm pr note add` on Q).
- When: the user runs `pm pr merge P`.
- Then:
  - the command exits 0;
  - `pm/project.yaml` is valid YAML with no marker lines;
  - `pm pr list` and every other pm command still work;
  - P shows `merged` and the file has `merged_at` set;
  - the branch's note and the local note on Q are both listed;
  - the local title edit and the branch's field change both survive (live
    wins a true conflict);
  - the base has fast-forwarded to the merge commit (the PR's code file is
    present).

**R2. No stash is created or left for a registry-only overlap.**
- Given: R1, and the registry is the only dirty file.
- When: the merge runs.
- Then:
  - `git stash list` is unchanged (empty);
  - `pm/project.yaml` stays dirty in the worktree (the live state) and is
    not staged;
  - the output says the registry was merged ("local pm state + merged
    changes").

**R3. Other dirty files that block the fast-forward are stashed and
restored.**
- Given: R1, plus an uncommitted edit to a tracked file the branch also
  changes (non-overlapping lines) and an untracked scratch file.
- When: the merge runs.
- Then:
  - it reports stashing N file(s) and "Restored N stashed file(s)";
  - both user changes are present on top of the merged content;
  - `git stash list` is empty;
  - the registry is never in the stash.

**R4. Concurrent pm writers serialize against the merge (#253 S74).**
- Given: R1/R3, with W writer loops (`pm pr note add Q`,
  `pm pr edit Q --description`, `pm project set skip-qa on/off`) running
  from before `pm pr merge P` until after it.
- When: the merge runs during the writes.
- Then:
  - every writer command exits 0, with no `Errno 2` (`project.yaml.tmp`),
    no "No project.yaml found", no "not valid YAML" and no traceback;
  - every acknowledged note is present afterwards;
  - R1's checks hold;
  - no stash and no unmerged path are left.

**R5. Leaked pm auto-stashes are reaped; others are listed; user WIP is
untouched.**
- Given: the main repo's stash stack holds:
  - an old `pm: auto-stash for merge` whose changes are already in the
    working tree;
  - one whose changes are not;
  - a user WIP stash.
- When: a merge's main-repo update succeeds with everything restored.
- Then:
  - the applied entry is dropped ("Dropped 1 leaked pm auto-stash(es)");
  - the unapplied one is listed with `git stash show -p` / `git stash drop`
    hints and kept;
  - the WIP stash is still present and unchanged.

**R6. Conflicted pop on a user file: the stash is kept on purpose.**
- Given: the user has an uncommitted edit on the same line that P's branch
  changes.
- When: the user runs `pm pr merge P`.
- Then:
  - the update lands (base at the merge commit; P merged with `merged_at`);
  - the registry is valid with no markers;
  - only the user's file holds markers;
  - a warning names that file and keeps the stash as `stash@{N}` with
    "resolve the files, then run `git stash drop stash@{N}`";
  - no recovery window opens on the local backend;
  - after the user resolves and drops, `git stash list` is empty.

**R7. Refused pop: "Nothing was lost".**
- Given: the user has an untracked file at a path P's branch adds as a
  tracked file with different content.
- When: the merge runs.
- Then:
  - the untracked file is stashed and the update lands;
  - git refuses to restore it, and the warning says nothing was lost, names
    the kept stash, tells the user to compare (`git stash show -p`,
    `git show <ref>^3:<path>`), restore what is missing and drop it, and
    does **not** tell them to pop again;
  - `git show <ref>^3:<path>` returns the user's original content.

**R8. A busy registry lock fails safe (local).**
- Given: another pm process holds the registry lock for more than 10 s (a
  `pm edit` with a slow `$EDITOR`, or an external flock).
- When: the user runs `pm pr merge P`.
- Then:
  - it exits 1 after about 10 s with the lock message and "pm did not touch
    <repo>";
  - "Nothing … was reset or discarded";
  - the base is unchanged and the live registry is byte-identical;
  - no stash is created;
  - P is not merged.

  Once the lock is released, re-running `pm pr merge P` succeeds.

**R9. A busy registry lock fails safe (post-publish pull,
vanilla/github).**
- Given: R8's lock holder, with a vanilla or github project.
- When: `pm pr merge P` publishes, and the post-publish update then finds
  the lock busy.
- Then:
  - the publish has already happened (origin's base advanced);
  - the command exits 1 with the lock message and a
    `pm pr merge --propagation-only P` hint;
  - no recovery window opens, even with `--resolve-window` / inside the
    tmux session;
  - the main checkout and its registry are untouched.

  `pm pr merge --propagation-only P` after release fast-forwards the
  checkout, reconciles the registry and marks P merged.

**R10. Post-publish pull reconciles the registry (vanilla/github).**
- Given: a vanilla project with a bare origin, whose signed-off P's branch
  commits a registry change, and the main checkout's registry is dirty (and
  optionally another overlapping dirty file).
- When: the user runs `pm pr merge P`.
- Then:
  - origin's base has the merge;
  - the main checkout is at `origin/master` ("Pulled latest master");
  - R1–R3's registry, stash and restore checks hold;
  - P is merged with `merged_at` set.

  The same holds on the github backend with `pm fake-github` installed.

**R11. Load guard: a registry with conflict markers.**
- Given: `pm/project.yaml` holds git conflict markers (left by an older pm,
  or a manual `git stash pop`).
- When: the user runs `pm pr list` (or any loading command), or opens the
  TUI.
- Then:
  - the command fails with a one-line pm error naming the full file path,
    the first marker's line number and text, `chmod u+w`, and that
    `git checkout -- <path>` discards uncommitted pm state;
  - there is no YAML scanner traceback;
  - the TUI shows the load error instead of crashing, and recovers once the
    file is fixed.

**R12. Load guard has no false positives, and "no project" is preserved.**
- Given: a PR note or description whose text contains lines like
  `<<<<<<< ours`, `=======` and `>>>>>>> theirs` (stored as indented YAML
  block text).
- When: the user lists PRs and notes.
- Then: nothing is flagged.

- Given: a directory with no `pm/project.yaml`.
- When: the user runs a pm command.
- Then: it reports the normal "no project" message (a missing-file error),
  not a parse/marker error.

**R13. A user's git config cannot reintroduce the bug.**
- Given: the user has `merge.autoStash=true`,
  `status.showUntrackedFiles=no` and `status.renames=false` set, and the
  main repo has:
  - a dirty registry;
  - an untracked file that blocks the fast-forward;
  - a staged rename;
  - a staged deletion of unrelated files.
- When: the merge runs.
- Then:
  - it exits 0;
  - no `autostash` or `pm: auto-stash for merge` entry is left;
  - the registry has no markers;
  - the untracked file is restored;
  - the staged rename and deletion are still staged exactly as before
    (`git diff --cached --name-status`);
  - nothing else was staged.

**R14. Two updates of the same checkout serialize.**

On vanilla/github the main-checkout update runs *outside* the publish
lock, so two updates can race there. Only the registry lock serializes
them.
- Given: a vanilla project.
  - PR A is already published, but its checkout update did not run (R9:
    the lock was busy), so A is still `sign_off` and waits for
    `--propagation-only`.
  - PR B is signed off against the new base.
  - Both branches commit registry changes.
  - The main checkout's registry is dirty.
- When: the user runs `pm pr merge --propagation-only A` and `pm pr merge B`
  from two terminals at once, while a third terminal runs `git fetch` in a
  loop.
- Then:
  - both exit 0;
  - the checkout ends at origin's final base;
  - A and B are both merged with `merged_at` set;
  - the registry holds both branches' committed changes and the local edits,
    with no reversion of the committed changes from whichever update landed
    first;
  - nothing is staged (no index-column `M` for `pm/project.yaml`);
  - no stash is left.

## 2. Edge cases

- **E1. Registry clean but the target changes it.** Given: a main checkout
  whose registry is unchanged since the last commit. When: P (which commits
  a registry change) is merged. Then: the file becomes the target's version,
  and `git status` shows it clean afterwards (no spurious dirtiness).
- **E2. Target already contained in HEAD.** Given: the main checkout already
  contains origin's base. When: `pm pr merge --propagation-only P` re-runs
  for an already-merged PR. Then: "Already up to date"; the live registry
  and the index are left alone; nothing is reverted.
- **E3. Paths with spaces or non-ASCII characters** among the dirty files.
  They are stashed and restored intact, and the warnings name them unsplit.
- **E4. Main repo not on the base branch (vanilla/github).** The pull is
  skipped ("Repo is on '<branch>', skipping pull") and the registry is
  untouched.
- **E5. Live registry invalid at merge time.** When: the user merges. Then:
  the merge fails like an overlapping file, leaves the registry untouched,
  and never writes markers. The load guard actually stops the command
  first, because `pm pr merge` loads state.
- **E6. Interrupt (Ctrl-C) during the fast-forward.** If git had finished
  (HEAD at the target), the merged registry stays. Otherwise the exact
  pre-merge registry and index entry are restored. In no case are there
  markers or a staged reversion. This is hard to drive deterministically;
  best-effort.
- **E7. The merge-lock overlay in the TUI.** When the stash includes pm/
  files (for example a dirty `pm/plans/*.md` the branch also changes), the
  TUI shows the merge-lock overlay during the update and clears it
  afterwards. A registry-only overlap shows no overlay.

## 3. Pass/Fail criteria

A scenario **fails** on any of:
- a conflict-marker line in `pm/project.yaml` at any point, or any pm
  command failing to load it after the merge;
- a `pm: auto-stash for merge` or `autostash` entry left after a merge whose
  restore succeeded;
- a user WIP stash dropped or altered;
- a merged PR not `merged`, or `merged_at` unset, after a merge that
  updated the checkout;
- a lost acknowledged write: a note added by a writer that exited 0
  missing, a local field edit reverted, or the branch's committed registry
  change missing;
- a writer failing with `Errno 2`, "No project.yaml found", "not valid YAML"
  or a traceback during the merge;
- user work lost: a dirty tracked or untracked file not restored, and not
  recoverable from a stash that the output names;
- a staged change altered, or `pm/project.yaml` left staged;
- a busy-lock merge that touched the checkout or opened a recovery window;
- a load-guard error that shows a raw YAML traceback, or a false positive
  on note text.

A scenario **passes** when every Then above is observed on the CLI/TUI
surface with captured evidence (recording plus command output and
`git stash list` / `git status` snapshots).

## 4. Ambiguities (resolved)

- **A true conflict on the same scalar** (branch vs live). Live wins
  (`merge_3way`, as on master). A local title edit survives a branch edit
  of the same title.
- **R6 and recovery windows.** On the local backend a conflicted pop
  never opens a window. Master no longer opens merge windows, and the old
  "launch a stash-pop resolution window" requirement was dropped by the
  rescope note. For vanilla/github, a *failed* post-publish update (not a
  conflicted pop after a landed update) still opens the pull-recovery
  window under `--resolve-window`. That is master behaviour and out of
  scope, except that its prompt now forbids stashing the registry.
- **Leaked stashes in a standalone pm dir's target repo** are deliberately
  not reaped (no lock serializes them). Not a failure.
- **Two concurrent merges.** The publish lock serializes publication. Two
  PRs signed off against the same base cannot both publish: the second is
  correctly refused back to sign-off ("moved since sign-off"), which is not
  a failure. The checkout update is the shared surface that can race, so R14
  races A's `--propagation-only` against B's full merge. On the local
  backend the checkout update runs inside the publish lock, so no race is
  possible there.
- **Signing off without a real Claude.** Writing a minimal `report.html`
  plus `pm pr signoff record` is the manual-approval user path. The
  fixture script's direct API call is allowed as bootstrap only.

No **[UNRESOLVED]** ambiguities.
