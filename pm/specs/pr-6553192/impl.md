# pr-6553192: suppress-switch flag leaks across action invocations

## Requirements
1. In `pm_core/runtime_state.py::set_action_state`, when transitioning an
   action's `state` to `launching` or `running` and the prior state was
   anything else (including absent), clear any pending `suppress_switch`
   flag for that `(pr_id, action)` as part of the same locked write.
2. Behavior of `request_suppress_switch` / `consume_suppress_switch`
   inside a single picker spinner invocation is preserved: setting
   on dismiss + consuming when window appears continues to work, and
   nothing pre-clears the flag before the spinner consumes it.
3. Add tests covering: dismiss sets flag; transitioning to launching
   for the same `(pr_id, action)` clears it; transitioning to running
   from absent state clears it; same-state re-write does not clear;
   transitions to other states (done/failed/idle) do not clear.

## Implicit Requirements
- The clear must happen atomically with the state change (same flock).
- The fix must not interfere with `extras={'suppress_switch': True}`
  passed in the same call (request_suppress_switch passes
  `state=None`, so this is safe).
- The clear is scoped to the prior state being different — re-writes
  of the same `launching`/`running` state should not retroactively
  clear a flag set during that same invocation. Practically the flag
  is set with `state=None` so the prior `state` is unchanged (still
  the same launching/running). To detect a *fresh* invocation we must
  check that the prior `state` was not already `launching` or
  `running` — i.e. transition is a real change.

## Ambiguities
- Should `queued` → `launching` clear? The flag is about a prior
  invocation — `queued` is the start of a new one. But by the spec,
  if state is set to `queued` first then `launching`, only the
  `launching` step clears. To be safe, also clear on transition into
  `queued` from absent or from a terminal state. **Resolution:**
  treat any transition into `launching`/`running` from a prior state
  that is not already `launching`/`running` as a fresh invocation
  trigger. `queued` is upstream of `launching` — when `launching`
  fires, the flag clears. This matches the task description exactly.

## Edge Cases
- `request_suppress_switch` calls `set_action_state(pr_id, action,
  None, suppress_switch=True)`. Since `state` is `None`, no transition
  happens, no clear triggered — flag survives. ✓
- Picker consumes flag via `consume_suppress_switch` which writes
  `suppress_switch=None` with `state=None`. No transition, no
  interference. ✓
- A re-entry where state is `running` and we set `running` again
  (idempotent updates) must not clear an in-flight suppress flag.
- `done` / `failed` transitions: leave flag alone (it is stale anyway,
  but next launching transition will clear it).
