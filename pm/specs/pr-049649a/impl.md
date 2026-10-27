# Spec — Remove all-PR autostart and fail closed on malformed/targetless saved state

PR: `pr-049649a` · Branch: `pm/pr-049649a-remove-all-pr-autostart-and-fail-closed-on-malform`

## Incident grounding

2026-10-27 18:52 UTC: `~/.pm/autostart-resume.json` contained
`{"auto_start": true, "all_mode": false, "targets": {<mapping>}}` (a mapping
instead of the required list of records). `targets_from_breadcrumb` only
handled `targets` when it was a `list`; any other type fell through to the
legacy branch, where `auto_start: true` with no `target` was interpreted as
"all ready PRs" (`all_mode=True`). The scheduler then had wildcard scope:
`managed_ids()` returned `None` ("everything"), unrelated eligible PRs
started, per-target `wait_for_merge` holds disappeared, #254 merged, and
drafts #265/#266 were created. The malformed input was a shepherd error; the
product must reject it without expanding authority.

The user asked to remove whole-backlog/all-PR autostart entirely, not merely
to fix the malformed-state branch.

## Requirements (grounded in code)

### R1 — Autostart authority is an explicit, validated, non-empty target collection

- `pm_core/autostart_state.py`
  - `managed_ids(prs, targets)` already computes only the union of target
    dependency closures. It is the only scope primitive; it must never be
    bypassed with a wildcard.
  - `pm_core/tui/auto_start.py:managed_ids` currently returns `None` in
    all-mode, and `in_scope` treats `None` as "everything". Remove the
    `None` return: always return `autostart_state.managed_ids(...)`, and
    return `set()` when autostart is off / has no targets. `in_scope`
    becomes `pr_id in managed_ids(...)`.
- `pm_core/tui/auto_start.py:is_all_mode`, `enable_all`,
  `app._auto_start_all`, and every branch that reads them are removed.
- `_sync_enabled` enables iff `bool(_targets(app))`; an empty collection is
  OFF. No targetless fallback anywhere.

### R2 — Remove every entry point to all-PR mode

- TUI command bar / IPC: `auto_start._dispatch` must reject the `all` verb
  with a non-ok result (`error: "all_mode_removed"`) and an actionable
  message ("add explicit targets with `autostart add PR_ID...`"). No state
  change, no scheduler pass.
- `auto_start.USAGE` no longer lists `all`.
- CLI `pm autostart`: no `all` subcommand exists; docstrings must not
  advertise one. `add` with no IDs already rejects.
- Keybindings: `A` with no selection only turns autostart OFF (or prints
  "No PR selected"); it must not suggest or enter all-mode.
- `app._auto_start_label` drops the `"all"` status-bar suffix.
- `pm_core/tui/screens.py:AutoRunsScreen` drops the "backlog mode" title;
  status modes are only `off` / `targets`.
- `pm_core/cli/tui.py` help drops `all` from the command-bar verbs and
  drops the "`autostart all`" migration note.
- `pm_core/cli/autostart.py` group/add/remove/clear help drops
  "`autostart all`".

### R3 — Saved-state parsing fails closed (never wildcard)

Replace `autostart_state.targets_from_breadcrumb` with a fail-closed
parser. Proposed API (all callers/tests updated):

```python
@dataclass(frozen=True)
class BreadcrumbTargets:
    targets: dict[str, dict]      # {} when nothing may be restored
    migrated: bool = False        # legacy single-target migration happened
    error: str | None = None      # actionable diagnostic; targets is {} on error

def targets_from_breadcrumb(data: dict) -> BreadcrumbTargets
```

Rules, in order:

1. `data` must be a mapping; otherwise `error` (defensive; `consume_breadcrumb`
   only calls it after a successful `json.loads`).
2. `all_mode` present and truthy → reject the **whole** autostart state
   (`targets={}`, `error="saved auto-start state requested all-mode
   (whole backlog); all-mode autostart is removed — re-add explicit targets"`).
   A truthy `all_mode` is an explicit request for wildcard authority and is
   never narrowed into a partial restore.
3. `auto_start` present and not a `bool` → reject (wrong type).
4. `run_id` present and not `str`/`None` → reject.
5. `targets` **key present**:
   - must be a `list`; `dict`, `str`, `None`, number, bool → reject. This is
     the incident shape and must never fall through to legacy parsing.
   - every entry must be:
     - a non-empty `str` (no whitespace-only), or
     - a `dict` with a non-empty `str` `pr_id`; its other fields are copied.
       If `wait_for_merge` is present it must be `bool`; `added_at`/`source`
       if present must be `str`. Any other malformed field/entry rejects the
       entire set (all-or-nothing; never silently drop a merge gate).
   - empty list:
     - if `auto_start` is truthy, or `run_id` is present → reject with
       "saved auto-start state has no target PRs; auto-start remains off".
     - otherwise → no autostart data (`targets={}`, no error).
   - `auto_start` explicitly `False` → do not restore (explicit off, no error).
   - valid non-empty list + `auto_start` absent/true → restore exactly those
     targets, preserving records in order and their `wait_for_merge` flags.
6. `targets` key **absent** → legacy handling:
   - `target` present:
     - non-empty `str` → `{target: record(source="legacy-breadcrumb")}`,
       `migrated=True`. This is the only permitted migration and it names
       exactly one validated target; no other PR gains authority.
     - any other type (`None`, dict, number, empty/whitespace string) →
       reject with a diagnostic.
   - `target` absent and (`auto_start` truthy or `run_id` present) →
     reject as targetless legacy data. It must **not** become `all_mode`.
   - otherwise → no autostart data.
7. No result may ever set a wildcard/all flag. `targets` is the sole
   authority; empty means OFF.

### R4 — `consume_breadcrumb` validates against the project and stays off on rejection

`pm_core/tui/auto_start.py:consume_breadcrumb`:

- On unreadable/corrupt/truncated JSON: remain OFF, log a warning, surface
  an actionable diagnostic via `app.log_message`, and **quarantine** the
  file (rename to `autostart-resume.rejected-<UTC stamp>.json`) instead of
  silently deleting the evidence. Never enable autostart.
- Parse via `targets_from_breadcrumb`. If `error` is set: remain OFF,
  log + `app.log_message("Auto-start: <error>; auto-start remains off")`,
  quarantine the file, and **do not** call `check_and_start`.
  - Still restore non-autostart state that is safe and useful: a valid
    `stop_before_merge` list and review-loop state (so merge gates and
    in-flight work are not silently dropped). But with autostart off these
    cannot cause an automatic merge (every merge path checks `is_enabled`).
- Validate restored targets against the loaded project data:
  - unknown PR ids → reject the whole restore (remain OFF, diagnostic).
  - terminal (merged/closed) targets are kept; the existing
    `_prune_completed_targets` pass removes them and turns autostart off
    when none remain. (An exact saved target completing during downtime is
    normal, not a reason to reject the rest.)
  - legacy migration additionally requires that exact id to resolve in the
    project; otherwise remain OFF with a "legacy target not found; not
    migrating" diagnostic.
- If the project has no loaded PR list (`app._data.prs` empty), any saved
  targets cannot be validated → remain OFF with a diagnostic. (`on_mount`
  loads state before `_deferred_startup` runs `consume_breadcrumb`, so this
  is only a defensive path.)
- `had_auto_start = bool(targets)` only. Resume summary says
  `→ <targets>` (plus "migrated legacy breadcrumb" when applicable); never
  "all".
- `save_breadcrumb` writes `auto_start`, `targets`, `run_id`, and
  `stop_before_merge`; it never writes `all_mode`. If autostart is enabled
  with an empty target map (impossible through the public API), skip the
  autostart fields rather than writing an empty/ambiguous record.

### R5 — Watcher / background-driver scope is fail-closed

- `pm_core/tui/watcher_ui.start_watcher` already passes
  `get_targets(app)` (a list, possibly empty) for `auto-start` watchers.
- `pm_core/prompt_gen.generate_watcher_prompt` currently omits the
  Auto-Start Scope block when the target list is empty, leaving the watcher
  prompt's general "scan all active panes / auto-fix" instructions
  unscoped. When `auto_start_targets`/`auto_start_target` is **provided**
  but resolves to no targets, emit an explicit fail-closed scope block:
  "Auto-start has no targets: no PR is managed. Do not start, restart, fix,
  merge, or otherwise act on any PR or window; observation/reporting only."
  When the argument is `None` (callers that never had a scope, e.g. plain
  `generate_watcher_prompt(data)`), behavior is unchanged.
- No other background driver may derive scope without `is_enabled` +
  `in_scope`: review/QA/sign-off/merge paths already do
  (`review_loop_ui`, `qa_loop_ui`, `signoff_ui`); verify `in_scope` is
  false with no targets after R1.
- Watcher resume from a rejected breadcrumb resumes with an empty target
  list, which now yields the restrictive prompt block.

### R6 — Preserve legitimate behaviour

- Explicit multi-target autostart, additive/idempotent add, per-target
  `stop_before_merge` / `auto_merge` / `wait_for_merge`, dependency
  closures, shared dependencies, `O`/`A` keys, `pm autostart
  add/remove/clear/list/status`, model routing and spec gates are
  untouched.
- `wait_for_merge` records survive save/restore unchanged, so held PRs
  remain held.
- Manual review/QA loops and review-loop breadcrumb restore continue to
  work when autostart is off (the `test_restores_manual_loop_without_auto_start`
  path).
- `pm autostart clear` / bare `autostart` still turn autostart OFF.

## Implicit requirements

1. **No silent partial authority.** Any malformed entry rejects the whole
   target set. Restoring a subset could start work the user did not
   authorize or drop a `wait_for_merge` gate.
2. **No wildcard sentinel anywhere.** After removal, `managed_ids` has a
   single return type (`set[str]`). Every `is None` check in
   `collect_status_inputs`, `on_state_loaded`, `in_scope`, and status
   building must be removed so a future `None` cannot be read as "all".
3. **Status cannot report an enabled/empty wildcard.** `build_status`
   must force `mode="off"` unless there is at least one target:
   `enabled = bool(targets) and bool(inp.get("enabled", True))`.
   `mode` is only `off`/`targets`; `status_rows` and `format_text` drop
   the all-mode branches.
4. **Merge gates are evidence, not optional.** Malformed
   `stop_before_merge` (not a list of strings) must reject autostart for
   that restore (no auto-merge without known holds) and produce a
   diagnostic; a valid list is still restored even when the target parse
   failed.
5. **Persistence round-trip.** Save→consume of an explicit multi-target
   collection with mixed policies must reproduce exactly the same targets,
   order, and holds.
6. **Diagnostics are actionable.** Every rejection names the reason and a
   next step (`pm autostart add PR_ID...`) and says autostart remains off.
7. **Quarantine, don't destroy.** Malformed breadcrumb evidence is renamed
   aside so merge-gate/incident evidence is preserved.
8. **Startup ordering.** `consume_breadcrumb` runs after `_load_state`, so
   validation against `app._data.prs` is meaningful; external commands are
   drained after it (existing ordering preserved).

## Ambiguities and resolutions

- **all_mode=true with otherwise valid targets** — restore the targets
  (narrower) or reject everything (fail closed)? → **Reject everything.**
  A truthy all-mode is an explicit wildcard request; silently narrowing it
  could mask a producer bug and would still act on saved state the user did
  not re-authorize. Diagnostic tells the user to re-add targets.
- **`targets: []` with no auto_start/run_id** — is that malformed? → No;
  it is simply no autostart data. Only a targetless *request* (auto_start
  truthy / run_id present) is rejected.
- **Legacy target now merged/closed** — reject or restore+prune? →
  Restore+prune: it is the exact validated target, and completion is normal.
- **Legacy target unknown to the project** — reject migration entirely
  (remain OFF, diagnostic), never enable a scope that cannot be resolved.
- **Malformed stop_before_merge** — reject autostart for that restore but
  keep review-loop state; do not guess holds.
- **Watcher started with no targets** — it must be observation-only, not a
  general fixer. Implemented via the explicit empty-scope prompt block.

No **[UNRESOLVED]** ambiguities.

## Edge cases

- Incident shape: `targets` is a dict → reject; never legacy fallback.
- `targets` is a string / null / number / bool → reject.
- `targets` list with `{}`, `{"pr_id": ""}`, `{"pr_id": 3}`,
  `{"pr_id": "a", "wait_for_merge": "yes"}` → reject whole set.
- `targets` list with duplicate ids → first record wins (stable order).
- Corrupt/truncated JSON → OFF, diagnostic, quarantined.
- `auto_start: true` + `targets: []` → reject.
- `auto_start: "true"` (string) → reject (wrong type).
- `run_id` without `target`/`targets` → reject (targetless legacy).
- `target: null` + `auto_start: true` → reject.
- Valid legacy `target: "pr-1"` → migrate exactly `pr-1`; no all-mode.
- Valid current-format multi-target with `wait_for_merge` → exact restore;
  held PRs never merge, unrelated PRs never start.
- `all` via command bar/IPC → error result, no state change, no worker.
- Restart while autostart off → no breadcrumb autostart fields; consume
  leaves it off.
- `pm autostart status --json` after a rejected restore → `mode: "off"`,
  empty targets/runs.
- A signed-off PR in a `wait_for_merge` closure stays held across a
  restart; a signed-off PR outside the targets is never merged.

## Regression tests (new/updated)

New `tests/test_autostart_fail_closed.py` (isolated `FakeApp`, fake
`_start_pr_quiet`/merge callbacks, no live project):

1. Parser matrix: missing targets, empty list, dict/string/null/int
   targets, malformed records, `all_mode` true/false, legacy single target,
   legacy targetless (`auto_start`/`run_id`), corrupt/truncated JSON.
2. `consume_breadcrumb` on the incident shape: stays OFF, no
   `check_and_start`, diagnostic logged, evidence quarantined.
3. Explicit multi-target restore + dependency scheduling: only closure PRs
   are launched; an unrelated eligible PR is never launched.
4. Signed-off PR in a `wait_for_merge` closure is not merged after restore
   (fake merge callback not called); unrelated signed-off PR is not merged.
5. `handle_command(["all"])` → `all_mode_removed`, state unchanged, no
   worker queued; bare `autostart` when off still usage-errors.
6. Watcher prompt with explicit empty targets → restrictive scope block;
   with `None` → unchanged; with targets → managed set.
7. `build_status` with `all_mode`/`enabled` hints but no targets → `off`.
8. Malformed `stop_before_merge` → autostart OFF but review-loop restore
   still happens.

Updated existing tests: remove `_auto_start_all` fields and all-mode
assertions; replace targetless fixtures with explicit targets; update
`targets_from_breadcrumb` call sites; update help-text expectations.
