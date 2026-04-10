# Impl Spec for PR pr-4db3696: Add pm pr split command for breaking large PRs into smaller pieces

## Requirements

1. **`pm pr split <pr_id>` CLI command** in `pm_core/cli/pr.py` — A new Click subcommand under the `pr` group that launches an interactive Claude session in the PR's workdir to decompose a large PR into multiple smaller child PRs.

   The command must:
   - Accept an optional `pr_id` argument (auto-select active PR if omitted, same pattern as `pr_start` at line 726)
   - Accept `--fresh` flag to force a new session
   - Load project state via `store.load(state_root())`
   - Validate the PR exists via `_require_pr(data, pr_id)`
   - Require a workdir (the PR must have been started, or one must be created)
   - Generate a split-specific prompt (see requirement 2)
   - Launch Claude in the PR's workdir via tmux window (following `pr_start` pattern) or terminal fallback
   - Use session key `"pr:split:{pr_id}"` for resume support

2. **Split prompt generation** — A new function `generate_split_prompt()` in `pm_core/prompt_gen.py`. The prompt instructs Claude to:
   - Read the PR's diff (`git diff origin/<base_branch>...HEAD`) and code
   - Read the PR's spec file if one exists
   - If the PR belongs to a plan, read the plan file (path provided in prompt) for sibling PR context
   - Discuss the split strategy with the user
   - For each child PR: create a git branch in the workdir, cherry-pick or write the relevant code
   - Write a **split manifest** file at a known path (e.g., `pm/specs/<pr_id>/split.md`) with a standardized format listing all child PRs (see requirement 3)
   - After writing the manifest, run `pm pr split-load <pr_id>` to trigger post-processing
   - NOT call `pm pr add` or push branches directly — the manifest is the output contract

3. **Split manifest format** — A markdown file parseable by `plan_parser.py`'s `_parse_section()` pattern. Uses a `## Child PRs` section with `### PR:` blocks:

   ```markdown
   ## Child PRs

   ### PR: First child title
   - **description**: What this child PR does
   - **branch**: pm/split-<pr_id>-first-child-slug
   - **depends_on**: (empty or comma-separated titles of other child PRs)

   ---

   ### PR: Second child title
   - **description**: What this child PR does
   - **branch**: pm/split-<pr_id>-second-child-slug
   - **depends_on**: First child title
   ```

   Add a `parse_split_prs()` function in `pm_core/plan_parser.py` that calls `_parse_section("Child PRs", "PR", ["description", "branch", "depends_on"])`. This returns a list of dicts with keys: `title`, `description`, `branch`, `depends_on`.

4. **`pm pr split-load <pr_id>` CLI command** — A separate subcommand that runs post-processing from the **base pm directory**. Analogous to `plan load` (which runs after `plan breakdown`): the split agent writes the manifest, then calls `pm pr split-load` to materialize the child PRs. This separation is necessary because the split session runs in a tmux window (non-blocking), so `pm pr split` can't wait for it to finish. It also works if the session is interrupted and resumed — the manifest is on disk. The command:
   a. Reads and parses the split manifest from `pm/specs/<pr_id>/split.md`
   b. For each child PR in the manifest:
      - Pushes the branch from the workdir to origin: `git_ops.run_git("push", "-u", "origin", branch, cwd=workdir)`
      - Generates a PR ID via `store.generate_pr_id(title, desc, existing_ids)`
      - Creates a PR entry via `_make_pr_entry(pr_id, title, branch, plan=original_plan, depends_on=resolved_deps, description=desc)` — note: `_make_pr_entry` already accepts a `branch` parameter, so we use the agent's branch name directly
      - Resolves `depends_on` titles to PR IDs (same pattern as `plan_load`, plan.py:572-582)
      - Appends the entry to `data["prs"]`
   c. Updates the original PR's description to reference the child PRs (via `pm pr edit` or direct mutation)
   d. Saves state via `save_and_push(data, root, ...)`
   e. Triggers TUI refresh
   f. For GitHub backend: optionally creates draft PRs for each child (like `pr_start` does)

5. **TUI keybinding** in `pm_core/tui/app.py` — Add a `P` keybinding for `action_split_pr()`.

6. **TUI action delegate** — Add `split_pr()` function in `pm_core/tui/pr_view.py` following the `start_pr()` pattern. Gets selected PR, guards against concurrent actions, dispatches `run_command(app, f"pr split {pr_id}", ...)`.

## Implicit Requirements

1. **Backend independence** — The split agent runs in the workdir and doesn't push. Post-processing pushes branches via `git_ops.run_git("push", ...)` from the workdir, which works across all backends. For GitHub, draft PR creation uses `gh_ops.create_draft_pr()` same as `pr_start`.

2. **Session resume support** — Session key `"pr:split:{pr_id}"` via `load_session()`/`save_session()`. If the session is interrupted before writing the manifest, no child PRs are created. When resumed, Claude can continue and write the manifest, then call `split-load`.

3. **Plan association** — If the original PR has a `plan` field, child PRs inherit it. The prompt includes the plan ID so Claude knows, and the post-processor passes it to `_make_pr_entry(plan=original_plan)`.

4. **Dependency ordering in post-processing** — Child PRs must be created in dependency order so `depends_on` title-to-ID resolution works. The post-processor pre-computes all IDs first (same pattern as `plan_load`, plan.py:549-558), then creates entries.

5. **Push proxy compatibility** — The split agent cannot push branches because the container push proxy only allows the original PR's branch. All pushing is deferred to post-processing, which runs outside the container on the host.

6. **Spec file writing** — The split agent can also write `pm/specs/<child-pr-id>/impl.md` files for each child. However, since child PR IDs aren't known until post-processing generates them, the agent uses placeholder names. Post-processing can rename spec dirs to match the generated IDs, or the agent skips spec writing and leaves it for each child's implementation session.

7. **Tmux window naming** — Window named `split-<display_id>` to distinguish from impl and review windows.

## Ambiguities

1. **Which TUI keybinding to use?**
   - Resolution: `P` (capital P). Not assigned in current BINDINGS. Mnemonic: "sPlit PR".

2. **Should the original PR status change?**
   - Resolution: No automatic status change. The user decides what to do with the original PR after splitting.

3. **Should the original PR's branch be reset?**
   - Resolution: No automatic reset. The branch retains implementation work. The prompt tells Claude to explain to the user what to do with the original PR, but the command doesn't enforce a particular outcome.

4. **What branch naming convention should child PRs use?**
   - Resolution: `pm/split-<original_pr_id>-<slug>` — makes it clear these came from a split. The post-processor uses whatever branch name the agent wrote in the manifest, so this is a prompt convention not a hard constraint.

5. **Should child PR spec files be written by the split agent?**
   - Resolution: The agent writes description-level content into the manifest's `description` field. Full impl specs are generated when each child PR is started (the normal Step 0 flow). This avoids the problem of not knowing child PR IDs at split time.

6. **When does post-processing run?**
   - Resolution: The split agent calls `pm pr split-load <pr_id>` after writing the manifest. This is a separate CLI command (analogous to `plan load` after `plan breakdown`). The split session runs in a tmux window (non-blocking `new_window()`), so `pm pr split` can't wait for exit. Having a separate command also handles interrupted/resumed sessions — the manifest is on disk and `split-load` can be run any time.

7. **What if some branches fail to push?**
   - Resolution: Post-processing reports errors per-branch but continues with the rest. Child PRs whose branches failed to push are still created in project.yaml (they can be pushed manually later or when `pm pr start` runs).

## Edge Cases

1. **No manifest file after session** — Post-processing is a no-op. No child PRs created.

2. **Manifest with no child PRs** — `parse_split_prs()` returns empty list. Post-processing is a no-op.

3. **PR with no workdir** — The split command must ensure a workdir exists. Either require the PR to have been started already, or create a workdir (clone + checkout branch) like `pr_start` does.

4. **PR with no plan** — Child PRs are standalone. `plan=None` in `_make_pr_entry`.

5. **Duplicate child PR titles** — `store.generate_pr_id()` handles hash collisions by extending the hash. Post-processing pre-computes all IDs before creating entries.

6. **Branch already exists on remote** — `git push` will fail for that branch. Post-processing reports the error and continues.

7. **Tmux not available** — Falls back to `launch_claude()` in current terminal. Post-processing still runs after.

8. **Claude CLI not found** — Prints the prompt to stdout. Post-processing still runs (and is a no-op since no manifest was written).
