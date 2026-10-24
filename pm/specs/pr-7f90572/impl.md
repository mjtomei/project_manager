# Spec: pr-7f90572 — meta window override cleanup (stale + overbroad)

## Context

`pm meta` (pm_core/cli/meta.py) sets a session override
(`~/.pm/sessions/<tag>/override` → `~/.pm/workdirs/meta-<tag>`) so every later
`pm` invocation in the tmux session loads the meta clone's `pm_core`
(pm_core/wrapper.py `_override_for_tag`). Two defects in how that override is
cleaned up:

1. **Stale override on abnormal exit** (QA pr-b53bfe2 scenario 2, t16): the
   pane command is `"<claude cmd> ; rm -rf ~/.pm/sessions/<tag>"`, so cleanup
   only runs if Claude exits normally. `tmux kill-window` (prefix-&) sends
   SIGHUP; the shell dies before the trailing `rm`, the override stays, and pm
   silently keeps using the meta clone (`pm which` → meta workdir) until the
   file is removed by hand.
2. **Overbroad cleanup on normal exit** (QA pr-592e4bd S50, note-2bc73f1):
   the trailing `rm -rf ~/.pm/sessions/<tag>` deletes the *whole shared
   session dir* — fake-claude config, scripted cursor, debug marker,
   `captures/<pr>/` QA evidence, fake-github state — not just the override.
   Seen live: a meta session ended and `~/.pm/sessions/p2-*/` was emptied, so
   the next planner ran as real Claude and stopped at the workspace-trust
   prompt (INPUT_REQUIRED).

## Requirements

### R1 — Cleanup must run on abnormal pane death
The meta pane command must register the cleanup via a shell trap
(`trap <handler> EXIT HUP INT TERM`), not as a trailing `; rm` statement, so:
- Normal Claude exit → cleanup runs (EXIT).
- `tmux kill-window` / pane SIGHUP → cleanup runs (HUP) once the shell resumes
  after the foreground child dies (POSIX: trapped signals are deferred until
  the foreground command completes; the kernel delivers SIGHUP to the whole
  pane's process group, so the child dies first, then the shell traps).
- Interactive fallback (`subprocess.run(..., shell=True)` when no tmux
  session) → Ctrl-C (INT) / TERM also trigger cleanup.
  Source: pm_core/cli/meta.py:186-210 (`clear_cmd`, pane launch and fallback).

### R2 — Cleanup must remove only the override file
Never `rm -rf ~/.pm/sessions/<tag>`. Remove only
`~/.pm/sessions/<tag>/override`. All other session state must survive both
exit paths (preserving per pm_core/paths.py:188-196):
- `debug`, `dangerously-skip-permissions`, `fake-claude`
- `captures/<pr>/…` (QA evidence — outside sessions dir but session dirs are
  shared per-tag; anything else in the session dir)

### R3 — Ownership guard
The cleanup must delete the override only if its content still points at *this
meta workdir* (`~/.pm/workdirs/meta-<tag>`, exactly the path passed to
`set_override_path` at launch, pm_core/cli/meta.py:183). Rationale: the
override file is shared state — `qa_loop._setup_clone_override`
(pm_core/qa_loop.py:528-545) writes the same file for clone tags pointing at
the running pm_core parent; a meta pane's cleanup must not clobber an override
someone else owns.

### R4 — Interactive fallback must wait out a slow interrupting child
(added after sign-off SIGNOFF_IMPL, 2026-10-24, HEAD 2889b14c) The
interactive-fallback launch (no tmux session, `subprocess.run(..., shell=True)`,
pm_core/cli/meta.py ~207 as of commit 0b3f34b9) left the override stale when
the foreground child took longer than ~0.25 s to exit after SIGINT:
`subprocess.run` responds to KeyboardInterrupt by SIGKILLing the shell child
~0.25 s in, which beats the shell's deferred INT/EXIT trap — the same
staleness R1 fixes for the tmux path (sign-off repro
`/pm-captures/signoff/orch.py`: child INT-handler delays 0.5/2 s → override
EXISTS). The fallback must instead wait on the Popen and keep waiting across
repeated KeyboardInterrupts, never escalating to a kill, and exit with the
shell child's returncode (130 when interrupted). No SIG_IGN may be set
before spawning (a shell cannot trap a signal that is ignored on entry).
Source: sign-off 2026-10-24; QA scenario 4 re-run required after this change.

## Implicit requirements

- The shell guard compares `$(cat override)` (trailing newline stripped by
  command substitution) to the verbatim workdir string written by
  `set_override_path` (content is `str(workdir) + "\n"`). Paths must be
  `shell_quote`d.
- Missing override file at cleanup time must be a no-op, not an error
  (EXIT trap runs on every exit path, including launches that never got to
  write state).
- The generated snippet must be POSIX-sh compatible (tmux runs the pane
  command via the default shell as `sh -c`; dash, bash and zsh all support
  `trap name EXIT HUP INT TERM`). The existing `claude_cmd` already relies on
  POSIX syntax (`$(cat …)`, `&&`), so no new assumption is introduced.
- When the meta window already exists, `pm meta` only selects it
  (pm_core/cli/meta.py:164-170) and must not touch the override.
- `find_claude` failure exits before `set_override_path`
  (pm_core/cli/meta.py:173-179) — unchanged, no leak on that path.
- The meta prompt's statement "The override file is automatically deleted when
  this Claude session exits" (pm_core/cli/meta.py:358) stays true.

## Ambiguities

- **Trap vs `_pane-closed` teardown**: the task offers either. Resolution:
  trap — self-contained in the pane command, works for the interactive
  fallback and without TUI bookkeeping; `_pane-closed` fires only for
  registry-tracked panes.
- **Late-trap vs re-launch race**: if the user kills the window and reruns
  `pm meta` before the dying shell's trap executes, the trap could delete a
  fresh override (same content, same per-session workdir). Window: the trap
  runs at kill time, a re-launch happens human-time later. Accepted;
  content-guard is the agreed protection per the PR note.
- **The `meta-<tag>` workdir itself** is not removed on exit — the task asks
  only for override cleanup; workdir reuse/resume is a feature
  (pm_core/cli/meta.py:117-133).

## Edge cases

- Override content points at a foreign workdir (qa_loop clone) → left intact
  (content mismatch).
- Override content points at a nonexistent path → wrapper ignores such
  overrides (pm_core/wrapper.py:50-52); cleanup still clears it only on exact
  content match.
- Session dir entirely missing at cleanup → no-op.
- Multiple exit signals in flight (HUP then EXIT) → handler is idempotent.

## Implementation shape

- `pm_core/cli/meta.py`: replace `clear_cmd`/`cmd` assembly (lines 186-191)
  with a helper that builds the pane command: a `pm_meta_clear_override()`
  shell function (guard + `rm -f` of the override file only) + `trap` on
  EXIT HUP INT TERM + the existing `claude_cmd`.
- Tests: `tests/test_meta_override_cleanup.py` — unit tests on the generated
  command plus real `/bin/sh` behavior tests (temp HOME): normal exit removes
  only the override; SIGHUP (process-group kill, mirroring tmux kill-window)
  removes only the override; foreign-owned override preserved; other session
  state preserved in all cases.
- R4 (fallback wait): `_run_interactive()` helper in pm_core/cli/meta.py +
  `test_fallback_interrupt_waits_out_slow_int_handler` — a driver subprocess
  runs the real helper with a slow-exiting (1 s) INT-handling child, takes a
  process-group SIGINT, and asserts the override is cleared, the child's 130
  propagates, and other session state survives. Red on pre-fix `subprocess.run`
  code, green post-fix. Post-fix sweep capture:
  `/pm-captures/impl/post-fix/slow-child-sigint.txt` (pre-fix baseline in
  `/pm-captures/impl/pre-fix/`, from the sign-off repro).
