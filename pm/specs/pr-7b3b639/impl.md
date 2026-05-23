# pr-7b3b639 — popup hangs after `pr start <new-pr>`

## Symptom
Inside a tmux popup launched via `display-popup -E pm _popup-cmd "$S"`
(`pm_core/cli/session.py:1783`), running `pr start <pr_id>` for a PR with
`status=pending` correctly opens the implementation window and switches the
client to it, but the popup overlay remains stuck on screen and ignores
Ctrl-C / Esc / q. The fast-path (`status=in_progress`, which only calls
`tmux select-window`) closes the popup cleanly.

## Root cause

When `pr start` opens a new impl window it goes through
`pr.py:1048 wrap_claude_cmd` → `container.create_container` →
`push_proxy.start_push_proxy` → `push_proxy._start_proxy_subprocess`
(`pm_core/push_proxy.py:629`).

That helper spawns the long-lived push-proxy daemon with:

```python
subprocess.Popen(
    [...], start_new_session=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
```

`stdin` is **not** redirected, so the daemon inherits FD 0 from its parent
chain: `pm pr start` ← `pm _popup-cmd` ← the tmux popup's pty.

`tmux display-popup -E` keeps the overlay alive until every FD on the popup
pty is closed — not just until the foreground command exits. The detached
proxy holds the pty open for the lifetime of the container, so the popup
hangs even though `subprocess.run` in `popup_cmd_cmd` returns cleanly.

The fast-path doesn't spawn any daemon, so no FD leaks and the popup closes.

## Requirements

1. **Fix the FD leak** (`pm_core/push_proxy.py:629`): pass
   `stdin=subprocess.DEVNULL` when spawning the proxy daemon so it cannot
   hold the popup's pty open after the parent exits.
2. **Regression test** (`tests/test_push_proxy.py`): assert that
   `_start_proxy_subprocess` invokes `subprocess.Popen` with
   `stdin=subprocess.DEVNULL` (and the existing `stdout`/`stderr` DEVNULL
   redirects, `start_new_session=True`). A mock-based test is sufficient and
   pins down the precise regression contract.

## Implicit requirements

- Don't change the daemon's runtime behaviour: it must still detach
  (`start_new_session=True`) and silently consume any stray writes.
- Don't disturb the `proxy_is_alive` poll loop — readiness detection is
  unchanged.

## Out of scope

- Hypothesis (2) from the task description (`tmux select-window` in
  `tmux.py:156` not using `check=True`) — not the cause of the popup hang
  per the FD analysis above. Leave as-is.
- Hypothesis (3) (`--background` for popup-launched commands) — user
  explicitly wants the client to switch.
- Other detached subprocesses in the codebase: only one detached `Popen`
  participates in the `pr start` path (`grep` confirms).

## Edge cases

- The push-proxy module is also invoked from contexts that already detach
  (e.g. cleanup loops); redirecting stdin to `/dev/null` is strictly safer
  in every case — no caller relies on the daemon reading stdin.
- `_start_proxy_subprocess` is mocked in existing tests via patching, so the
  Popen kwargs change doesn't alter test setup paths.
