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
2. `all_mode` present and not exactly `False` → reject the **whole**
   autostart state (`targets={}`). A truthy value yields
   `error="saved auto-start state requested all-mode (whole backlog);
   all-mode autostart has been removed"`; a non-boolean value such as
   `"no"`/`0`/`null` is rejected too, with its own "non-boolean all_mode
   flag" diagnostic (the shape must be unambiguous). The consumer appends
   the remedy so it is not repeated twice in one message. A truthy
   `all_mode` is an explicit request for wildcard authority and is never
   narrowed into a partial restore.
3. `auto_start` present and not a `bool` → reject (wrong type).
4. `run_id` present and not `str`/`None` → reject.
5. `targets` **key present**:
   - must be a `list`; `dict`, `str`, `None`, number, bool → reject. This is
     the incident shape and must never fall through to legacy parsing.
   - every entry must be:
     - a non-empty `str` with no whitespace (see `valid_pr_id`; a padded id
       could never match a real PR, so it is malformed rather than coerced),
       or
     - a `dict` with a non-empty `str` `pr_id`; its other fields are copied.
       If `wait_for_merge` is present it must be `bool`; `added_at`/`source`
       if present must be `str`. Any other malformed field/entry rejects the
       entire set (all-or-nothing; never silently drop a merge gate).
       Legacy record fields (`policy`/`merge_policy`/`stop_before_merge`)
       are folded into `wait_for_merge` when they do not name the automatic
       policy (fail closed; master's pr-25f4038 behaviour).  A bare-string
       entry is a legacy shape whose policy is unknown, so it fails closed
       to `wait_for_merge` (`source="legacy-breadcrumb"`, `migrated=True`).
   - a `stop_before_merge` top-level key, when present, must be a `list` of
     valid PR ids (or `null`); any other type (a dict/string/set) or an
     invalid/padded/empty id rejects the whole restore with the
     "malformed stop_before_merge merge-gate set" diagnostic.  On a valid
     restore the marks migrate to `wait_for_merge` targets (a mark on an
     existing target forces its flag; a mark on a non-target becomes a
     standalone wait target, terminal ids dropped) so a saved hold is never
     silently lost.
   - empty list:
     - if `auto_start` is truthy, or `run_id` is present **and non-null** →
       reject with "saved auto-start state has no target PRs; auto-start
       remains off".  (A `null` run_id is not a request: no producer ever
       wrote one, and it carries no authority either way.)
     - otherwise → no autostart data (`targets={}`, no error).
   - `auto_start` explicitly `False` → do not restore (explicit off, no error).
   - valid non-empty list + `auto_start` absent/true → restore exactly those
     targets, preserving records in order and their `wait_for_merge` flags.
6. `targets` key **absent** → legacy handling:
   - `target` present:
     - a valid id (`valid_pr_id`: non-empty `str`, no whitespace) →
       `{target: record(source="legacy-breadcrumb", wait_for_merge=True)}`,
       `migrated=True`. This is the only permitted migration and it names
       exactly one validated target; no other PR gains authority.  The
       single-target shape cannot distinguish `O` from `A`, so it fails
       closed to the manual policy (master's pr-25f4038 behaviour); valid
       `stop_before_merge` marks are folded in as wait targets too.
     - dict, number, empty/whitespace-containing string → reject with a
       diagnostic.
     - `None` → treated as "no target" rather than an invalid one: with
       `auto_start`/`run_id` present it is rejected by the targetless rule
       below (the pre-multi-target writer emitted exactly this shape for
       its all-mode: `{"auto_start": true, "target": null, "run_id": …}`),
       and on its own it is simply no autostart data.  The targetless
       diagnostic is more accurate than "invalid legacy target" for that
       historical shape, and no producer wrote `target: null` with an
       autostart request that was not all-mode.
   - `target` absent and (`auto_start` truthy or `run_id` present and
     non-null) → reject as targetless legacy data. It must **not** become
     `all_mode`.
   - otherwise → no autostart data.
7. No result may ever set a wildcard/all flag. `targets` is the sole
   authority; empty means OFF.

### R4 — `consume_breadcrumb` validates against the project and stays off on rejection

`pm_core/tui/auto_start.py:consume_breadcrumb`:

- On unreadable/corrupt/truncated JSON: remain OFF, log a warning, surface
  an actionable diagnostic via `app.log_message`, and **quarantine** the
  file (rename to `autostart-resume.rejected-<UTC stamp>.json`) instead of
  silently deleting the evidence. Never enable autostart.
- Parse via `targets_from_breadcrumb`. If `error` is set: clear the
  in-memory autostart fields (so a rejected restore can never leave a
  previous/wildcard scope active), log +
  `app.log_message("Auto-start: <error>; auto-start remains off")`,
  quarantine the file, and **do not** call `check_and_start`.
  - Still restore safe non-autostart state: review-loop state (so
    in-flight work is not silently dropped) and the watcher list.  With
    autostart off these cannot cause an automatic merge (every merge path
    checks `is_enabled`).  A valid `stop_before_merge` set is preserved in
    the quarantined evidence; it is not turned into an app-level stop set
    (master's pr-25f4038 removed that state) and cannot enable autostart on
    its own.  Malformed review-loop records/history entries are skipped
    with a warning (never raised out of startup); well-formed loop state
    and entries are still restored, including the failed-launch retry
    fields.  A record or entry whose scalar fields have the wrong type
    (e.g. a string `iteration`, a non-bool `input_required`) counts as
    malformed: adopting it would only fail later inside a review-loop
    worker, not at startup.
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
  "all". It reports the targets still active *after* the scheduler pass:
  a restored target that completed during downtime is pruned (which logs
  "auto-start OFF"), so it is omitted from the summary, and no summary is
  painted when none remain (that would claim a scope that is gone).
- `save_breadcrumb` writes `auto_start`, `targets`, and `run_id` (plus
  review-loop/watcher/session state); it never writes `all_mode` and never
  writes a `stop_before_merge` field (the policy no longer exists).  If
  autostart is enabled with an empty target map (impossible through the
  public API), skip the autostart fields rather than writing an
  empty/ambiguous record.

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
  Because the prompt's later generic "Auto-Fix Issues" / "take corrective
  actions" sections would otherwise contradict it, the block also states
  that the restriction overrides them.
  When the argument is `None` (callers that never had a scope, e.g. plain
  `generate_watcher_prompt(data)`), behavior is unchanged.
  Note: `AutoStartWatcher` always passes a list (never `None`), so a
  standalone `pm watcher` / `pm watcher start auto-start` outside the TUI —
  which owns no targets — is observation-only too. That is the intended
  fail-closed consequence of "a watcher started with no targets must not be
  a general fixer"; it is documented in the CLI/watcher docstrings.
- No other background driver may derive scope without `is_enabled` +
  `in_scope`: review/QA/sign-off/merge paths already do
  (`review_loop_ui`, `qa_loop_ui`, `signoff_ui`); verify `in_scope` is
  false with no targets after R1.
- Watcher resume from a rejected breadcrumb resumes with an empty target
  list, which now yields the restrictive prompt block.

### R6 — Preserve legitimate behaviour

- Explicit multi-target autostart, additive/idempotent add, per-target
  `auto_merge` / `wait_for_merge`, dependency closures, shared
  dependencies, `O`/`A` keys, `pm autostart add/remove/clear/list/status`,
  model routing and spec gates are untouched.
- Master's pr-25f4038 single-manual-policy behaviour is preserved: the
  removed `stop_before_merge` value/flag is a deprecated alias for
  `wait_for_merge` (never a target-only hold), and saved stop marks migrate
  to wait targets.
- `wait_for_merge` records survive save/restore unchanged, so held PRs
  remain held.
- Manual review/QA loops and review-loop breadcrumb restore continue to
  work when autostart is off (the `test_restores_manual_loop_without_auto_start`
  path).
- `pm autostart clear` / bare `autostart` still turn autostart OFF.
- `pm autostart status --json` carries an additive `ok` field — `true` on
  success, `false` (with `error`/`message`) on an owner-side failure —
  matching `add`/`remove`/`clear`/`list`, so a captured status snapshot is
  self-describing. The rest of the object is still the
  `pm.autostart.status/1` document; this is an additive field (cf.
  pr-e69afc4 "additive fields"; `pm/specs/pr-0b87a97/impl.md` R3 enumerates
  the fields without `ok`). *(PR note: QA S7 incidental fix @cfd01f0b.)*

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
   `stop_before_merge` (not a list of strings, or an entry that is not a
   valid PR id — e.g. whitespace-padded, which could never match a PR and
   would silently lose its hold) must reject autostart for that restore
   (no auto-merge without known holds) and produce a diagnostic.  A valid
   set is folded into `wait_for_merge` targets when autostart resumes; when
   the restore is rejected (or autostart was off) the original bytes stay
   in the quarantined evidence, and with no scheduler there is no merge
   path to gate.  Id validity is shared with the target parser
   (`autostart_state.valid_pr_id`).  Stale *in-memory* status inputs still
   fold permissively in `build_status` (`_legacy_ids`), which has no error
   channel and never restores anything.
5. **Persistence round-trip.** Save→consume of an explicit multi-target
   collection with mixed policies must reproduce exactly the same targets,
   order, and holds.
6. **Diagnostics are actionable.** Every rejection names the reason and a
   next step (`pm autostart add PR_ID...`) and says autostart remains off.
7. **Quarantine, don't destroy.** Malformed breadcrumb evidence is renamed
   aside so merge-gate/incident evidence is preserved. If the rename
   itself fails (e.g. a read-only directory) the file is left in place —
   never deleted — and the next startup re-rejects it (auto-start stays
   off either way).
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
  The resume summary lists only the remaining targets and is omitted when
  none remain, so it never claims a scope the prune just turned off.
- **Legacy target unknown to the project** — reject migration entirely
  (remain OFF, diagnostic), never enable a scope that cannot be resolved.
- **Malformed stop_before_merge** — reject autostart for that restore but
  keep review-loop state; do not guess holds.  The original bytes (with the
  stop set) are quarantined, so the gate is not lost as evidence.
- **Valid stop_before_merge with autostart resuming** — migrate the marks to
  `wait_for_merge` targets (master's pr-25f4038 behaviour) so the hold
  survives the restart; with autostart off there is no scheduler/merge path,
  so the marks are left in the evidence rather than enabling a scope.
- **Legacy single `target: X`** — migrate to exactly `X` as a
  `wait_for_merge` target: the old shape cannot distinguish `O` from `A`, so
  it fails closed to the manual policy rather than granting auto-merge.
- **Watcher started with no targets** — it must be observation-only, not a
  general fixer. Implemented via the explicit empty-scope prompt block.

No **[UNRESOLVED]** ambiguities.

## Edge cases

- Incident shape: `targets` is a dict → reject; never legacy fallback.
- `targets` is a string / null / number / bool → reject.
- `targets` list with `{}`, `{"pr_id": ""}`, `{"pr_id": 3}`,
  `{"pr_id": "a", "wait_for_merge": "yes"}` → reject whole set.
- `targets` list with duplicate ids → reject the whole set. First-wins
  could silently drop the other record's `wait_for_merge` merge gate, and
  our own writer (a dict keyed by id) never emits duplicates.
- Corrupt/truncated JSON → OFF, diagnostic, quarantined.
- `auto_start: true` + `targets: []` → reject.
- `auto_start: "true"` (string) → reject (wrong type).
- `run_id` without `target`/`targets` → reject (targetless legacy).
- `target: null` + `auto_start: true` → reject.
- Valid legacy `target: "pr-1"` → migrate exactly `pr-1` (as a
  `wait_for_merge` target); no all-mode.
- Bare-string target entry → legacy shape, migrates to `wait_for_merge`
  (`source="legacy-breadcrumb"`); an empty/whitespace string rejects the set.
- `stop_before_merge` as a dict/string/set, or a padded/empty id → reject
  the whole restore with the malformed merge-gate diagnostic.
- Valid `stop_before_merge` on a restored target set → marks become wait
  targets; terminal ids are dropped.
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
   worker queued; the same verb via IPC (`--reply`) writes a non-ok reply
   with `status.mode == "off"` and changes nothing; bare `autostart` when
   off still usage-errors.
6. Watcher prompt with explicit empty targets → restrictive scope block;
   with `None` → unchanged; with targets → managed set.
7. `build_status` with `all_mode`/`enabled` hints but no targets → `off`;
   `enabled: false` with targets → `off`.
8. Malformed `stop_before_merge` → autostart OFF, review-loop restore still
   happens, and the original bytes (with the stop set) are quarantined; a
   valid set is folded into wait targets on a valid restore.
9. Non-boolean `all_mode`, non-string `run_id`, a null `run_id` with no
   targets (off, no error), `auto_start` with no target key, and a legacy
   `target` without `auto_start` (migrates).
10. Save→consume while autostart is off writes no autostart fields;
    enabled-with-empty-targets writes no breadcrumb at all.
11. A malformed review-loop history entry does not abort the restore, a
    wrong-typed record/entry field is skipped rather than adopted, the
    loop-resume summary never paints over the rejection diagnostic, and an
    all-malformed `review_loops` file claims no resume.
12. Two back-to-back rejections in the same UTC second preserve both
    original files under distinct `-N` names (quarantine never overwrites
    evidence).
13. `pm autostart status --json` carries `ok: true` on success and
    `ok: false` with `error`/`message` on an owner-side failure.

Updated existing tests: remove `_auto_start_all` fields and all-mode
assertions; replace targetless fixtures with explicit targets; update
`targets_from_breadcrumb` call sites; update help-text expectations.

## Integration — origin/master merged 2026-10-29

Integrated master SHA: `4a74d88085edffcc300cb21f31777a798d647782`
("Merge pull request #276 …"), merged into
`pm/pr-049649a-remove-all-pr-autostart-and-fail-clo-registered-20261027`.

Master had moved substantially (352 commits, 101 files).  The two
autostart-touching master changes reconciled here are:

- **pr-25f4038 — `wait_for_merge` is the only manual policy.**  Master
  removed `stop_before_merge` as a distinct target policy and
  `app._stop_before_merge` as app state, migrated saved stop marks to wait
  targets, normalised legacy record fields fail-closed to wait, and forced
  legacy single/bare targets to wait.  This PR keeps those semantics and
  layers its fail-closed saved-state parser on top: a saved
  `stop_before_merge` must be a list of valid ids (anything else rejects
  the restore), valid marks become wait targets only when targets are
  restored, and a rejected restore leaves the original bytes quarantined.
  `build_status` keeps master's permissive `_legacy_ids` folding for stale
  *in-memory* inputs (it has no error channel and restores nothing).
- **pr-2c67d50 / pr-db3bf10 — QA-run adoption and review-loop retry
  fields.**  `consume_breadcrumb` keeps `_adopt_live_qa` +
  `check_and_start` ordering (restart loops → adopt QA → scheduler pass)
  and restores the failed-launch retry fields, now with strict type
  validation so a corrupt record cannot raise on restore.  Master's
  session-owner check and non-object/corrupt-shape guards are preserved,
  upgraded to quarantine rejected evidence instead of deleting it.

All-PR/all-mode removal is unchanged by the merge: `all_mode` is still
rejected by the parser, `managed_ids` still returns a concrete set, and
the `all` verb/CLI/help/keybinding/label/popup paths stay removed.

Validation: full suite `4580 passed, 1 skipped`, with one unrelated
timing-flaky `tests/test_push_proxy.py::TestWorkdirKeyedProxies::
test_restart_after_socket_death_does_not_disturb_other_workdir` (passes in
isolation; master's push-proxy code, not touched here).  Focused autostart
suites (parser, multi-target, single-policy, breadcrumb/loop, log-message,
signoff handoff, owed REQA, launch retry) all pass.
