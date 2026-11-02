# QA spec — pr-2e06289: sync-detected GitHub merges must pass the sign-off integrity check

Grounded in `pm/specs/pr-2e06289/impl.md`, the diff (`pm_core/merge_integrity.py`
(new), `pm_core/pr_sync.py`, `pm_core/tui/sync.py`, `pm_core/cli/pr.py`,
`pm_core/git_ops.py`) and `tests/test_sync_merge_integrity.py`.

The bug: a PR is signed off (`SIGNOFF_MERGE` bound to an integration check —
approved head, signed-off base, candidate tree), a teammate pushes an
unreviewed commit onto its branch and merges the PR on GitHub. The TUI's
5-minute background GitHub sync (and the startup sync, `pm pr sync`,
`pm pr sync-github`) marked the PR `merged` without checking what GitHub
actually published — no `merge_integrity`, no note. `pm pr merge` already did
the check (pr-ac10f03). The fix routes every sync-discovered merge of a PR
holding a *bound* `SIGNOFF_MERGE` through the same verification, records a
mismatch as `pr["merge_integrity"]` + one `Merge integrity: …` note, and shows
a held TUI log line.

User-facing surfaces under test:
- TUI background GitHub sync (the 300 s tick, no user action).
- TUI startup GitHub sync (TUI opened on a github-backend project).
- TUI manual refresh (`r` key).
- CLI: `pm pr sync`, `pm pr sync-github`, `pm pr merge [--no-signoff-check]`.
- Recorded evidence: `pm pr show` / `pm pr note list` (the
  `Merge integrity: …` note), `pm pr list` / TUI tech tree (status `merged`),
  `pm/project.yaml` (`merge_integrity`, for cross-checking).
- Backend: `github` via `pm fake-github` (the fake's local `remote.git` stands
  in for GitHub; a "teammate" merges there or the fake is re-seeded `MERGED`).

## 1. Requirements (Given / When / Then)

### Background sync (the reported bug)

- **R1.1** Given a github-backed project with a PR in sign-off holding a bound
  `SIGNOFF_MERGE`, and a teammate has pushed an unreviewed commit onto the PR's
  branch and merged the PR on GitHub, When the TUI's periodic background sync
  runs (the user does nothing), Then the PR is shown `merged`, the log line
  shows a `Merge integrity: …` message naming the approved head and the merge
  that actually published the branch, the line stays readable for several
  seconds instead of being painted over by `Synced: N PR(s) merged`, and the PR
  now carries one `Merge integrity: …` note.
- **R1.2** Given the same project and a PR whose approved candidate was merged
  on GitHub unchanged, When the background sync runs, Then the PR is `merged`
  and no `Merge integrity:` log line and no such note appear (a clean merge is
  not flagged).
- **R1.3** Given two PRs merged on GitHub before one tick — one of the signed-off
  candidate, one after an unreviewed commit — When the background sync runs,
  Then both become `merged`, exactly one `Merge integrity:` line is shown (for
  the mismatched PR), and only that PR carries the note.
- **R1.4** Given a PR approved against a base that has since moved and then
  merged on GitHub onto the newer base, When the background sync runs, Then the
  PR is `merged` and the `Merge integrity:` message says GitHub merged it onto
  a different commit than the signed-off base (the signed-off base is named).

### Startup and manual TUI sync

- **R2.1** Given a merge (after an unreviewed commit) already completed on
  GitHub while the TUI was not running, When the user starts the TUI on the
  github-backed project, Then the startup sync shows the PR `merged`, displays
  the `Merge integrity:` log line, and records the note.
- **R2.2** Given the TUI is running on that project and the merge happens while
  it runs, When the user presses refresh (`r`), Then the same evidence appears
  (log line + note) and the PR is `merged`.
- **R2.3** Given a PR merged on GitHub that holds no sign-off record at all,
  When the TUI sync runs, Then the PR is `merged` with no `Merge integrity:`
  line and no note (nothing to compare against).

### CLI sync surfaces

- **R3.1** Given a merge after an unreviewed commit, When the user runs
  `pm pr sync`, Then it reports the PR as merged, prints a `WARNING:` naming
  the approved head / the publishing merge, records `merge_integrity`, and adds
  one note visible in `pm pr note list` / `pm pr show`.
- **R3.2** Given a merge of the signed-off candidate, When the user runs
  `pm pr sync`, Then the PR is merged with no `WARNING:` and no note.
- **R3.3** Given the same unapproved merge, When the user runs
  `pm pr sync-github`, Then it prints the same `WARNING:` and records the same
  evidence.
- **R3.4** Given the GitHub-side repository cannot be reached for the base
  fetch (so what landed cannot be checked), When the user runs `pm pr sync`,
  Then the PR is still finalized `merged`, a `WARNING: could not verify …` is
  printed, and no `merge_integrity` / note is written (unknown ≠ mismatch).
- **R3.5** Given the PR's own workdir has been removed but another workdir (or
  the project repo) shows the merge, When the user runs `pm pr sync`, Then the
  PR is merged and the integrity problem is still recorded (the check falls
  back to the directory the sync used).

### Publisher path unchanged (adjacent regression)

- **R4.1** Given a PR holding a bound `SIGNOFF_MERGE` and its approved candidate
  mergeable, When the user runs `pm pr merge`, Then it publishes and finalizes
  as before, with no `WARNING:` and no `merge_integrity`.
- **R4.2** Given GitHub already merged the PR after an unreviewed commit, When
  the user runs `pm pr merge --no-signoff-check`, Then it recovers, prints the
  existing `WARNING: GitHub merged … commits that were not signed off`, records
  `merge_integrity` + one note, and a second run adds no second note.
- **R4.3** Given GitHub already merged the signed-off candidate, When the user
  runs `pm pr merge --no-signoff-check`, Then it recovers silently (no
  `WARNING:`, no `merge_integrity`).

### Concurrent use

- **R5.1** Given a merge after an unreviewed commit, When the TUI sync and
  `pm pr sync` (or two TUI sync paths) finalize the same PR at nearly the same
  time, Then the PR ends `merged`, exactly one `merge_integrity` record and one
  note exist, no duplicate note and no store-lock error is shown, and the TUI
  and CLI agree.
- **R5.2** Given the TUI is started while another pm process finalizes the same
  merge, When both settle, Then the PR is `merged` and the `merge_integrity`
  record + note are present regardless of which writer set the status first
  (evidence is applied even when the status was already `merged`).
- **R5.3** Given another pm integration check holds the repository's integration
  lock, When a bound-approved PR's merge is detected by the background/manual
  sync, Then the TUI stays responsive (navigation/refresh still work), the
  status bar shows the sync is still pulling while it waits, and once the lock
  is released the merge is finalized with the record + log line — no error, no
  half-applied state. A PR without a bound approval detected in the same
  situation finalizes without waiting on that lock (it never fetches).

## 2. Setup

Per `tui-manual-test.md`, plus the fake-GitHub recipe proven in the pr-ac10f03
QA notes (project.yaml note-99a6f1d / note-1c373f5):

1. Install pm from this PR clone (`./install.sh --local`, or venv +
   `PYTHONPATH`); `pm which` must point at the clone, not `/opt/pm-src`.
2. In a throwaway directory, run every `pm` / `pm fake-github` command from
   that directory (the fake-github session tag is derived from the git root,
   not tmux).
3. Seed the fake GitHub **before** initialising pm:
   `pm fake-github config set '{"git_backed": true, "default_branch": "master",
   "prs": [{"head": "pm/pr-<id>", "title": "…", "files": {"app.py": "…"}}]}'`.
   This creates `~/.pm/sessions/<tag>/fake-github/remote.git` (a real local git
   repo) and its PR head branches.
4. Make the test project a clone of that `remote.git` (so the project repo and
   every PR workdir share it as `origin`), then
   `pm init --backend github --no-import`: the GitHub import picks up the seeded
   PRs with `gh_pr_number` and `branch`.
5. `pm pr start <pr>` to create the PR workdir on its branch.
6. Approve it the way sign-off does: `pm pr signoff integrate <pr> --record`
   (integration check bound to head/base/candidate tree) and a sign-off verdict
   of merge through the normal flow (fake-claude can supply
   `{"signoff": {"verdicts": ["SIGNOFF_MERGE"]}}`); confirm `pm pr list` shows
   the merge-ready marker.
7. Simulate the teammate: clone `remote.git`, commit on the PR branch, push it
   back (the unreviewed commit), then merge the branch into `master` there
   (`git merge --no-ff`) — or re-seed the fake with the same PRs and
   `"state": "MERGED"`, which performs that merge in `remote.git`. The fake's
   `pr view` state is what the sync detects; the merge commit in `remote.git`
   is what the verifier fetches.
8. For the clean control, merge the branch without the extra commit. For the
   moved-base variant, push a commit to `master` on `remote.git` before merging
   the branch.
9. `pm session` to run the TUI; drive it with `pm tui view` / `pm tui send`.
   Background ticks are 300 s apart and the interval is measured from the last
   sync, so the first tick after a startup sync can be skipped — allow up to
   ~10 minutes, or trigger a manual `r` refresh where the scenario allows it.
10. Read evidence with `pm pr note list`, `pm pr show`, `pm pr list`, the TUI
    tech tree, and `pm/project.yaml` (`merge_integrity`).

## 3. Edge cases

- **E1 — Could not verify** (base fetch fails / repository unreachable): PR is
  still finalized `merged`; warning only; nothing recorded.
- **E2 — No approval**: a PR merged on GitHub with no `signoff` record is
  finalized untouched (no fetch, no record).
- **E3 — Legacy HEAD-only approval** (a `SIGNOFF_MERGE` without the integration
  binding): treated as unverifiable — merged, no record, no warning.
- **E4 — Repeated detection**: a re-detected merge (status reverted, second
  sync, or the publisher's repeated recovery) overwrites `merge_integrity` with
  the same problem but never appends a second identical note.
- **E5 — Multiple merges in one tick**: one verification per PR, applied and
  logged independently.
- **E6 — PR workdir gone**: verification falls back to the sync workdir / the
  project repo; a mismatch is still recorded (possibly with the general
  "did not publish the signed-off candidate" text when the fallback repo lacks
  the PR head object — deliberate pr-ac10f03 semantics).
- **E7 — Moved base during publication**: the problem names the commit GitHub
  actually merged onto.
- **E8 — Sync worker must not write state**: with the sync blocked (integration
  lock held) the user can change state elsewhere; after the sync finishes the
  concurrent change survives and no user edit is lost.
- **E9 — Verification crash / unexpected error**: the merge is still finalized;
  the failure is a log-only "could not verify", never a stuck sync.

## 4. Pass/Fail criteria

A scenario passes when every Then holds:

- A sync-discovered merge of a bound-approved PR that published anything other
  than the signed-off candidate ends `merged` **and** leaves
  `pr["merge_integrity"]` with a problem naming the approved head/base and the
  published merge, **and** exactly one `Merge integrity: …` note.
- The TUI additionally shows the held `Merge integrity:` log line; the CLI
  additionally prints the `WARNING:`.
- A clean merge of the signed-off candidate is finalized with no record, note
  or warning on every surface.
- A merge that cannot be checked is still finalized, with a warning and no
  invented record.
- A PR with no bound approval is finalized exactly as before the fix.
- The publisher path (`pm pr merge` and `--no-signoff-check` recovery) behaves
  as it did after pr-ac10f03.
- No sync path raises, hangs past the documented lock bound, corrupts
  `project.yaml`, duplicates a note, or loses a concurrent user edit.

A scenario fails if a mismatched merge is finalized silently on any surface, a
clean merge is flagged, an unverifiable merge is recorded as a mismatch (or a
mismatch is dropped), a note is duplicated, or the TUI blocks/crashes while the
sync verifies.

## 5. Ambiguities (resolved)

1. **Mismatch blocks the merge?** No — the fix records evidence and still
   finalizes the PR (the merge already happened on GitHub). Pass criteria
   require the record + note, not a refusal.
2. **"Could not verify" recording**: not recorded on the PR; log-file warning
   (TUI) or stderr `WARNING:` (CLI) only. Deliberate: unknown is not evidence.
3. **Legacy HEAD-only approval**: skipped (no base/tree to compare), matching
   `_recover_completed_merge`. A PR cannot be merged through pm with such an
   approval anyway.
4. **Lock wait during sync**: the sync worker now fetches the base under
   `<git-common-dir>/pm-integration.lock` (300 s bound), so a detected merge
   can delay the tick while another integration check runs. Acceptable as long
   as the UI stays responsive and the evidence lands after the lock frees;
   delay alone is not a failure.
5. **Fallback message text**: when the PR workdir is gone and the fallback repo
   is stale, the general "did not publish the signed-off candidate" problem is
   the expected text (deliberate pr-ac10f03 semantics), not a bug.
6. **Held log line duration**: ~6 s (`_INTEGRITY_HOLD_SECONDS`); the note is
   the authoritative record, so the scenario asserts the note even if the line
   was missed.

No **[UNRESOLVED]** ambiguities.
