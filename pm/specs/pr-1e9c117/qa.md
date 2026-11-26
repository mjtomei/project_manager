# pr-1e9c117 — QA spec: fail-closed capture routing for `/pm-captures`

Implementation spec: `pm/specs/pr-1e9c117/impl.md`.
Change under test: `pm_core/paths.py:captures_dir()` now returns the
container mount only when the container's owner marker
(`PM_CAPTURES_PR`, whitespace-stripped) equals the requested PR id.
Absent, empty, whitespace-only or mismatched markers fall back to the
per-session host path (`~/.pm/sessions/<tag>/captures/<pr>/`) and, when
no session tag resolves, to `None`. `pm qa captures-path`'s docstring
and its "cannot resolve" error message were updated to match.

The incident being fixed: a throwaway pm project driven inside a
scenario container (harness mistake — `PM_CAPTURES_PR` unset) wrote its
own `scenarios/<n>/{prompt.md,scenario.json,verdict.md}` into the
enclosing PR's `/pm-captures`, destroying real evidence.

## 1. Requirements

**R1 — Owner inside a container still finds its evidence at the mount.**
GIVEN a worker session running inside a scenario container that pm
created for PR `pr-X` (the PR's captures dir is bind-mounted at
`/pm-captures`, and the container carries `PM_CAPTURES_PR=pr-X`),
WHEN the worker asks pm for the captures directory of `pr-X`,
THEN it is given `/pm-captures`, and a file written there shows up
under `~/.pm/sessions/<tag>/captures/pr-X/` on the host.

**R2 — Host-side resolution is unchanged.**
GIVEN a pm checkout on a machine where the PR's captures directory
already exists under `~/.pm/sessions/<tag>/captures/<pr>/` (or where no
mount is visible),
WHEN the user resolves the captures directory for that PR,
THEN the printed path is the `~/.pm/sessions/...` path and the
directory exists — never `/pm-captures`.

**R3 — A nested throwaway project with no owner marker fails closed.**
GIVEN a scenario container for `pr-X` with `/pm-captures` mounted, and
a throwaway pm project created inside it whose environment does *not*
carry `PM_CAPTURES_PR` (the harness mistake),
WHEN the throwaway project resolves the captures directory for its own
PR,
THEN the path is under the throwaway project's own
`~/.pm/sessions/<its-tag>/captures/<its-pr>/`, not `/pm-captures`, and
the directory exists.

**R4 — A mismatched owner marker fails closed.**
GIVEN the same container but with `PM_CAPTURES_PR=pr-X` inherited by
the nested throwaway project (the realistic inheritance case),
WHEN the throwaway project resolves captures for its own different PR,
THEN it again gets its own `~/.pm/sessions/<its-tag>/captures/<its-pr>/`
path and `/pm-captures` is untouched.

**R5 — Empty / whitespace-only marker counts as no marker.**
GIVEN a nested project whose `PM_CAPTURES_PR` is set to the empty
string or to whitespace only,
WHEN it resolves captures for its PR,
THEN it gets its own host-style path, not the mount.

**R6 — A matching marker with stray whitespace still routes to the mount.**
GIVEN the owning PR's session with `PM_CAPTURES_PR` set to the PR id
plus a trailing newline/space (the shape a shell `export` can produce),
WHEN it resolves its captures directory,
THEN it still gets `/pm-captures` (the marker is stripped before
comparison).

**R7 — The enclosing PR's evidence is never modified (the incident).**
GIVEN the enclosing PR's `/pm-captures` already holds scenario evidence
(`scenarios/<n>/prompt.md`, `scenario.json`, `verdict.md`, recordings),
WHEN a nested throwaway QA run writes its own scenario prompt,
scenario definition and verdict,
THEN those files appear under the nested project's own captures tree,
and every pre-existing file under `/pm-captures` is byte-identical
(checksums unchanged) and no new directory appeared under it.

**R8 — Concurrent writers do not cross-contaminate.**
GIVEN a container where the owning PR's worker and two independent
nested throwaway projects are all writing scenario evidence at the same
time,
WHEN all three finish,
THEN each nested project's files are under its own captures tree, the
owning worker's files are under `/pm-captures`, no file appears in more
than one place, and no writer's file was overwritten by another.

**R9 — Unresolvable tag plus an unowned mount is an error, not the mount.**
GIVEN a shell that is not inside a tmux pm session and whose working
directory is not a git repository, with `/pm-captures` present but not
owned by the PR being asked about,
WHEN the user asks pm for that PR's captures directory,
THEN the command exits non-zero with a message that names both causes
(no session tag; no mount owned by this PR) and does **not** print
`/pm-captures`.

**R10 — The reproduction tests from the diff pass.**
GIVEN a checkout of this branch,
WHEN the captures-routing test module from the diff is run,
THEN every case passes, including the cases that failed on the
pre-fix tree (unset / empty / whitespace owner, nested throwaway
projects, unowned mount with no tag).

## 2. Setup

- Run everything with pm resolving to the checkout under test
  (`pm which` must print it, not a site-packages or master copy). In
  the scenario container `PYTHONPATH=/opt/pm-src` shadows the checkout,
  so point it at the checkout and/or `./install.sh --local`.
- The container under test has the PR's captures mounted at
  `/pm-captures` and `PM_CAPTURES_PR` naming this PR. Confirm with
  `pm qa captures-path pr-1e9c117` before starting.
- **Evidence safety.** `/pm-captures` is real, irreplaceable evidence
  for this PR. Record a recursive listing plus checksums of it before
  any nested run, write only into your own `scenarios/<n>/`
  subdirectory, and re-check the listing afterwards. Never delete or
  rewrite another scenario's files.
- Throwaway projects: `mkdir` under a scratch dir, `git init`,
  `pm init --backend local --no-import`, `pm pr add ...`. Put the real
  git first on `PATH` (`/usr/bin` ahead of `~/.local/bin`) — the
  container's git proxy forwards fetches/pulls into the enclosing
  checkout.
- To make nested runs deterministic, drive Claude with the bundled
  fake (`pm fake-claude config set ...`, see the TUI instruction's
  "Driving Claude sessions with the fake"). A nested fake QA run needs
  a `pm/specs/<throwaway-pr>/qa.md` in the throwaway project, else the
  loop stops at `INPUT_REQUIRED` after planning.
- Record the host-side result from the container's point of view: the
  container's `~/.pm/sessions/<tag>/captures/` is the "own" tree; the
  host's view of the same evidence is `/pm-captures`.

## 3. Edge cases

**E1 — Empty PR id.** `captures_dir("")` with a non-empty owner marker
can never match, so it must fall through to the host path / `None`,
never the mount.

**E2 — Owner marker matches but the mount is missing.** Resolution
falls back to the host path and creates it (unchanged behaviour).

**E3 — Mount exists, marker matches, and the host path also exists.**
The existing host path wins (host-first precedence preserved); the
mount is not written.

**E4 — Marker names a different PR and no tag resolves.** `None` is
returned; callers degrade (QA capture writes warn and skip; the CLI
errors). No silent write into the mount.

**E5 — Repeated resolution.** Asking twice for the same owner in a
container returns the mount both times and does not create a stray
`~/.pm/sessions/<tag>/captures/<pr>/` in the container.

## 4. Pass / Fail criteria

Pass = every `THEN` above is observed on the user's surface: the path
printed by `pm qa captures-path`, the files created on disk, the
checksums of pre-existing evidence, the exit status and stderr of the
error case, and the diff's test module going green.

Fail = any nested project's files land in `/pm-captures`; any
pre-existing file under `/pm-captures` changes; the owning PR stops
resolving `/pm-captures`; the host path is no longer created/returned
where it used to be; the error case prints the mount or exits zero; or
the reproduction tests fail.

## 5. Ambiguities

- **A1 — Full nested QA loop vs. a worker-style write.** The incident
  wrote scenario files through the QA loop, but running a whole loop in
  a nested project is heavy and environment-sensitive. Resolved: drive
  the real nested QA pass where feasible (fake Claude), and treat the
  resolved captures path plus the files written there as the surface of
  record. Either way the assertions are about *where the files land*,
  not how they were produced.
- **A2 — `PM_CAPTURES_PR` presence in the outer scenario container.**
  Containers created by this code set the marker; older harnesses may
  not. Resolved: the owning-PR requirements assume the marker is set
  (that is what `container.create_container` does); if a scenario
  observes it absent, the owning-PR expectation is not a failure of the
  fix but a note about the harness.
- **A3 — Exact error wording.** The new message is descriptive prose;
  assertions are on the *substance* (both causes named, non-zero exit,
  no `/pm-captures` printed), not on exact characters.

No **[UNRESOLVED]** items.
