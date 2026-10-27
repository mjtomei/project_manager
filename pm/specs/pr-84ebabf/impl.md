# Implementation Spec — pr-84ebabf

**Bug:** a claude-type provider `api_key` (even a `${VAR}` reference) is written
as `ANTHROPIC_API_KEY=<value>` into the logged launch command and the tmux pane
command.

## 1. Requirements (grounded in the code)

### R1. Provider env values must not appear in `build_claude_shell_cmd()` output
- `pm_core/claude_launcher.py:870` `build_claude_shell_cmd()` resolves provider
  config via `_resolve_provider()` (`pm_core/claude_launcher.py:284`) and
  currently builds `env_prefix = "K=<value> ..."` (line ~929) which is prefixed
  to the returned shell string.
- `pm_core/providers.py:73` `ProviderConfig.env_vars()` resolves `${VAR}`
  references (`_resolve_env_ref`, `providers.py:113`) and returns concrete
  values (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_BASE_URL`,
  `ANTHROPIC_MODEL`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_BASE_URL`).
- **Requirement:** the returned command string must contain no provider env
  *value* at all. The model flag (`--model ...`) is unaffected.

### R2. The same values must still reach the launched process (host panes)
- Host panes are created with a shell-string command by:
  - `tmux_mod.new_window` / `new_window_get_pane` / `create_window` /
    `create_session` / `split_pane` / `split_pane_at` /
    `split_pane_background` (`pm_core/tmux.py`).
  - `os.execvp("bash", ["bash", "-c", cmd])` in `pm_core/cli/guide.py`,
    `pm_core/cli/qa.py`.
  - `launch_pane()` in `pm_core/tui/pane_ops.py` (wraps in `bash -c` and calls
    `split_pane`).
  - `launch_claude_in_tmux()` in `pm_core/claude_launcher.py` (uses
    `send_keys`; currently has no production callers, only tests).
- **Requirement:** transport the values through the launched process's
  environment without putting them in the command string:
  - tmux pane creation: write the values to a `0600` file under `~/.pm/run/`
    and make the pane command source it (`set -a; . file; set +a; rm -f file`)
    before the real command, wrapped in `sh -c` so a non-POSIX `default-shell`
    (fish) can run the prefix. The file is removed before claude starts.
    **Not** `tmux -e NAME`: on tmux 3.2 (the supported floor) `new-window`
    resolves a bare name from the server environment and `split-window` from
    the session environment — not the client's — so it silently drops the
    variable or injects an unrelated value. Only `new-session -e NAME` reads
    the client env on 3.2. (Verified empirically on tmux 3.2a; see §7.)
  - `execvp` sites: `os.execvpe("bash", [...], {**os.environ, **env})`.
  - `launch_claude_in_tmux` (`send_keys`): same env file, sourced by the typed
    `sh -c` command; the file is removed before claude starts.

### R3. Keep OpenAI (`OPENAI_API_KEY`) the same
- The openai branch of `ProviderConfig.env_vars()` (`providers.py:87`) must be
  treated identically: no values in the command; values via process env.

### R4. Logs and other metadata must not carry the values
- `log_shell_command(cmd, prefix="claude")` (`pm_core/paths.py:687`) writes the
  command at INFO to `~/.pm/debug/<tag>.log`. Removing values from `cmd` fixes
  this.
- `tmux list-panes -F "#{pane_start_command}"` must not expose values (fixed by
  R1/R2).
- `pane_registry.register_pane(..., cmd)` stores the command in
  `~/.pm/pane-registry/<session>.json` (e.g. `pane_layout.py:359`,
  `pm_core/cli/pr.py:1518`, `signoff.py:561`, `pane_ops.py:182`). Fixed by R1.
- `launch_claude()` logs `_log.debug("Claude env vars: %s", {... values ...})`
  (`claude_launcher.py:722`). Redact so only variable *names* are logged.

### R5. Container launches must still receive provider env
- Container paths embed the same `claude_cmd` in a runtime exec string:
  `container.build_exec_cmd()` (`pm_core/container.py:991`) and
  `wrap_claude_cmd()` (`container.py:1065`).
- The separate `create_container` `-e NAME=value` argv leak is **out of scope**
  (#249 / 75f0dde6, not yet merged here). Do not duplicate that fix.
- **Requirement:** for provider overrides, emit `-e NAME` (name only) in the
  runtime `exec` argv in `build_exec_cmd()` and rely on the same process-env
  transport into the pane; the runtime reads `NAME` from its own environment.
  This is the same mechanism #249 uses for `create_container`, applied to exec,
  and does not touch `create_container`'s argv fix.
- For `${VAR}` provider keys the container already gets the value from host env
  at creation (`_CLAUDE_ENV_VARS`); `-e NAME` on exec is idempotent.

### R6. Tests use synthetic canaries only
- Never print or embed real credentials. Test fixtures use a fabricated canary
  such as `canary-84ebabf-do-not-use`.

## 2. Implicit requirements

- **No behavioural change when provider env is empty** (built-in `claude`):
  identical command string, no env file.
- **Every production caller of `build_claude_shell_cmd` must forward the env.**
  A caller that forgets would silently run Claude unauthenticated. Mitigation:
  `build_claude_shell_cmd(..., env_out=...)` populates the dict; when provider
  env is non-empty and `env_out is None`, log a warning so missed sites surface.
- **The env must be snapshotted at build time** — the values are resolved once
  and passed to the launch; no re-resolution in the pane.
- **Quoting/encoding safety:** values may contain spaces/newlines/quotes. The
  env file quotes each value with `shlex.quote`; `execvpe(env=...)` avoids shell
  quoting entirely.
- **`pane_start_command` parsing must keep working.** `pane_transcript_path`
  matches a leading `cd <dir> && ` at the start of the command, so the wrapper
  hoists that prefix outside the `sh -c` (`cd '/w' && sh -c '...'`).
- **Concurrency:** each launch writes its own uniquely-named env file; no
  shared global/session state is modified.
- **Container foreground path:** `cli/qa.py` `foreground` uses `execvp`; pass
  env there too so `podman exec -e NAME` can read it.
- **`pane_layout.register_and_rebalance(..., cmd)`** stores the command; it is
  clean after R1.

## 3. Ambiguities and resolutions

- **A1. Which transport?** Task lists "process env of the tmux client", "shell
  reference for `${VAR}` keys", or "redaction at least in the log".
  **Resolution:** a private env file sourced by the pane command (all pane
  creation paths and `send_keys`); `execvpe` env for foreground. Redaction
  alone is explicitly insufficient (tmux copy), a bare shell reference breaks
  when the pane does not inherit the variable, and `tmux -e NAME` from the
  client env only works for `new-session` on tmux 3.2 (§7).
- **A2. All provider env or only the API key?** All provider env values.
  Simpler invariant ("no provider env value in the command"), and
  `ANTHROPIC_AUTH_TOKEN` is secret-class too. Non-secret `*_BASE_URL`/`MODEL`
  values also move; behaviour is unchanged because they arrive via process env.
- **A3. Unset `${VAR}` reference:** `_resolve_env_ref` currently returns `""`;
  keep that (empty value transported as empty, matching today's
  `ANTHROPIC_API_KEY=` prefix).
- **A4. `send_keys` has no pane-env channel.** Use the same short-lived `0600`
  env file, sourced via `sh -c` and removed before claude starts. This path has
  no production callers; keep it functional without putting values in the
  typed command.
- **A5. tmux version.** `tmux -e NAME` is not usable for `new-window`/
  `split-window` on tmux 3.2 (host has 3.2a; repo supports 3.2+). The env-file
  transport is version-independent, so no version gate is needed.
- **A6. Container `-e NAME` on `exec`.** Docker/Podman env parsing reads the
  value from the runtime client's environment when no `=value` is given. The
  pane command sources the env file before running the runtime, so the runtime
  client sees the value.

No **[UNRESOLVED]** ambiguities.

## 4. Edge cases

- Empty values (`ANTHROPIC_API_KEY=""` for local providers): the env file
  writes an empty assignment; keep it.
- Local provider sets `ANTHROPIC_AUTH_TOKEN="ollama"` — transported, not
  inlined.
- Fake-claude launches (`_FAKE_CLAUDE_BIN`) still receive the env
  (harmless) and keep the same command shape minus the prefix.
- Over-limit prompts, transcript symlinks, container path rewrites: unaffected
  (env no longer participates in string rewrites).
- `PM_PROVIDER`/default provider (no explicit `provider=` argument): still
  resolved and transported; every call site passes `env_out`.
- Duplicate launches in the same pane/window: each writes its own env file.
- A provider env value containing `=` or newline: safe via the quoted env file.
- A pane killed before its command runs leaves the env file behind; files older
  than 24 h are swept on the next write.

## 5. Implementation outline

1. `pm_core/providers.py`: no behavioural change required; optionally document
   that `env_vars()` returns concrete values that must be transported via the
   process env, never interpolated into loggable command strings.
2. `pm_core/claude_launcher.py`:
   - `build_claude_shell_cmd(..., env_out: dict[str, str] | None = None)`:
     drop `env_prefix`; populate `env_out` with `provider_env`; warn when
     non-empty and `env_out is None`.
   - `launch_claude_in_tmux`: `env_out` + the shared env-file source prefix,
     wrapped in `sh -c`.
   - Redact the debug env dump in `launch_claude`.
3. `pm_core/paths.py`: `write_env_file(env)` writes a `0600` file under
   `~/.pm/run/` and returns `(source_prefix, path)`.
4. `pm_core/tmux.py`: pane-creating helpers take `env`; `_run_with_env` rewrites
   the pane command to source the env file (`sh -c`, with a leading `cd` kept
   outside the wrapper) and unlinks the file if tmux fails.
5. `pm_core/container.py`: `build_exec_cmd(..., env=None)` emits `-e NAME`
   (name only) on the runtime exec command; `wrap_claude_cmd(..., env=None)`
   forwards it.
6. Call sites: forward `env_out` to the tmux helper / `execvpe` /
   container helper.

## 6. Verification

- Pre-fix capture: `$CAP/impl/pre-fix/` (already captured; canary leaks into
  build output, `pane_start_command`, and the command log).
- Failing tests first (see R6), then fix, then:
  - targeted: `tests/test_providers.py`, `tests/test_provider_integration.py`,
    `tests/test_claude_launcher.py`, tmux/container tests;
  - a **real-tmux** test that reads the value back out of the pane's
    environment (`tests/test_tmux.py::TestProviderEnvReachesRealPane`) — the
    mocked argv-only tests passed while the `-e NAME` transport silently
    dropped the value on tmux 3.2;
  - related suites for regressions;
  - post-fix capture: `$CAP/impl/post-fix/` showing the canary absent from the
    command, `pane_start_command`, and the log, while present in the pane's
    process environment.

## 7. Review iteration 1 — tmux 3.2 finding

The original implementation transported values with `tmux -e NAME` and the
values in the tmux client's environment. On the host's tmux 3.2a this is only
honoured by `new-session`; `new-window` resolves a bare name from the *server*
environment and `split-window` from the *session* environment. Consequence:
every provider-override launch through `new_window` / `new_window_get_pane` /
`split_pane` / `split_pane_at` (impl, review, QA, signoff, watcher, TUI panes)
would silently run Claude without the provider key — or with an unrelated
value that happened to be in the server/session env (e.g. the user's real
`ANTHROPIC_API_KEY` sent to a third-party base URL). The post-fix evidence had
only exercised `create_session`, the one path that works.

Replaced with the env-file transport described in R2/A1. The new real-tmux
tests assert both that the value lands in the pane environment and that
`pane_start_command` stays clean; they fail on the `-e NAME` implementation.

## 8. Review iteration 2 — doc/test follow-ups

No behavioural changes. Three docstrings still described the superseded
`tmux -e NAME` transport (`container.wrap_claude_cmd`,
`TestBuildExecCmdProviderEnv`, `tui.pane_ops.launch_pane`); corrected to the
env-file mechanism. Added
`tests/test_claude_launcher.py::TestLaunchClaude::test_debug_env_dump_names_only`
covering R4 (`launch_claude`'s debug dump names provider vars but never logs
their values, and the command handed to `log_shell_command` is clean).
