# QA Spec: pr-9a5b86e
# Harden local LLM integration: model selection, real QA testing, init setup, and provider verification

## Requirements

### R1: Always-visible local providers in `pm model show`
**File**: `pm_core/cli/model.py` — `model_show()` (lines 56-71)

The "Available local/external providers" section must always appear in `pm model show` output:
- When providers are configured: displays a table with name, type, model, and api_base columns, plus usage instructions.
- When NO providers are configured: displays `(none configured — add with: pm provider add ollama --api-base http://localhost:11434)`.
- The section header "Available local/external providers:" prints unconditionally.

### R2: Provider verification reports inference separately from tool use
**File**: `pm_core/providers.py` — `ProviderTestResult` (lines 424-427), `_check_tools_anthropic`, `_check_tools_openai`

New fields `inference_ok` (bool|None) and `inference_detail` (str) track whether the model can produce output, independent of tool-use capability. Expected outcomes:
- Model responds but doesn't use tools: `inference_ok=True`, `tool_use=False`
- HTTP error during check: `inference_ok=False`, `tool_use=False`
- Empty choices from model: `inference_ok=False`, `tool_use=False`

### R3: Anthropic API probe for OpenAI-type providers
**File**: `pm_core/providers.py` — `_check_anthropic_api_support()` (lines 615-670)

For `type=openai` providers with a model, `check_provider` probes `/v1/messages` to detect Anthropic Messages API support:
- 200 or non-404 HTTP error: `anthropic_api=True`, suggests switching to `type=local`
- 404: `anthropic_api=False`
- Other exception: `anthropic_api=False`

### R4: Local provider fallback to OpenAI API on 404
**File**: `pm_core/providers.py` — `check_provider()` (lines 568-583)

For `type=local` providers, if `_check_tools_anthropic` returns 404 (server doesn't support `/v1/messages`), the code resets tool_use/inference state and falls back to `_check_tools_openai` using `/v1/chat/completions`. The fallback appends `/v1` to the base URL if not already present.

### R5: Double /v1 fix in Anthropic API probe URL
**File**: `pm_core/providers.py` — `_check_tools_anthropic()` (lines 717-720), `_check_anthropic_api_support()` (lines 636-639)

When `api_base` already contains `/v1`, the code strips it before appending `/v1/messages` to avoid generating `/v1/v1/messages`.

### R6: Init detects Ollama and offers provider setup
**File**: `pm_core/cli/__init__.py` — `_detect_local_llm()` and `_offer_local_model_setup()`

During `pm init`, if stdin is a TTY:
- Detects Ollama binary via `shutil.which("ollama")`
- Tests connectivity at `http://localhost:11434/api/tags`
- If not installed: silently skips
- If installed but not running: prints advisory with `ollama serve` instructions
- If running but no models: prints recommended models and `ollama pull` instructions
- If running with models and no existing provider: prompts to configure (default=No)
- If running with provider already configured: prints "(provider already configured)"

### R7: Context window detection for OpenAI-type providers
**File**: `pm_core/providers.py` — `_check_context_window()` (lines 612-632)

For `type=openai` providers, reads `max_model_len` from the `/models` endpoint response (vLLM, SGLang style). Flags a warning if below `MIN_CONTEXT_TOKENS` (64,000).

### R8: `pm provider add` and `pm provider test` display expanded results
**File**: `pm_core/cli/provider.py` — `_display_test_result()`

The display now includes:
- Anthropic API support status (for openai providers)
- Inference result (OK/FAILED with detail)
- All prior fields (connectivity, context window, tool use)

### R9: Remote endpoint integration tests
**File**: `tests/test_provider_integration.py` — `TestRemoteLLMIntegration`

New test class, skipped when `PM_TEST_LLM_URL` is not set:
- `test_connectivity_check`: verifies endpoint is reachable
- `test_inference_with_real_model`: verifies inference (requires `PM_TEST_LLM_MODEL`)

### R10: `capabilities_summary()` structured output
**File**: `pm_core/providers.py` — `ProviderTestResult.capabilities_summary()`

Returns a dict with keys: `reachable`, `anthropic_api`, `tool_use`, `context_window`, `inference`.

### R11: `max_tokens` bump for tool-use checks
**File**: `pm_core/providers.py` — both `_check_tools_anthropic` and `_check_tools_openai`

Raised from 100 to 1024 to give reasoning models enough room to produce tool calls.

## Setup

### For unit tests (mocked)
- Standard pytest with no external dependencies: `pytest tests/test_providers.py tests/test_provider_integration.py -v -k "not RealOllama and not RemoteLLM"`

### For local integration tests (real Ollama)
- Ollama running locally with at least one model pulled
- `pytest tests/test_provider_integration.py::TestRealOllamaIntegration -v`

### For remote integration tests
- `PM_TEST_LLM_URL=http://spark-424d.lan:30002 PM_TEST_LLM_MODEL=openai/gpt-oss-120b pytest tests/test_provider_integration.py::TestRemoteLLMIntegration -v`

### For CLI-level testing
- A working `pm` install (`pip install -e .`)
- For init testing: Ollama installed and/or running
- For model show testing: providers.yaml at `~/.pm/providers.yaml`

## Edge Cases

1. **`pm model show` with empty providers.yaml**: Should show the "none configured" message with add instructions.
2. **`pm model show` when only a `type=claude` provider exists**: The filter `p.type != "claude" or p.api_base` excludes default claude providers, so it should show "none configured".
3. **`api_base` with trailing slash**: `api_base.rstrip("/")` handles this throughout.
4. **`api_base` with `/v1` suffix for local provider**: Stripped before appending `/v1/messages` to prevent double `/v1`.
5. **`api_base` with `/v1` suffix for OpenAI fallback**: When local provider falls back to OpenAI, it checks for existing `/v1` before appending.
6. **Model returns empty choices array**: `inference_ok=False`, `tool_use=False` with appropriate detail.
7. **HTTP 500 during tool check**: Both inference and tool_use marked False.
8. **Ollama not installed during init**: `_detect_local_llm()` returns `installed=False`, `_offer_local_model_setup()` returns silently.
9. **Ollama running but no models pulled during init**: Shows recommended models list and pull instructions.
10. **Provider already configured during init**: Shows "(provider already configured)" and does not prompt.
11. **Non-TTY stdin during init**: Skips entire LLM detection (no prompt in non-interactive mode).
12. **PM_TEST_LLM_URL not set**: Remote integration tests skip cleanly with reason message.
13. **PM_TEST_LLM_MODEL not set but PM_TEST_LLM_URL is**: Inference test skips, connectivity test still runs.
14. **Anthropic API probe on server returning non-404 error (e.g. 400, 401)**: Treated as `anthropic_api=True` (endpoint exists but rejected our minimal request).

## Pass/Fail Criteria

### PASS
- All unit tests pass: `pytest tests/test_providers.py tests/test_provider_integration.py -v` (excluding real endpoint tests)
- `pm model show` always displays the "Available local/external providers" section regardless of provider configuration state
- `pm provider add` and `pm provider test` display inference status separately from tool use
- For openai-type providers, `pm provider test` shows Anthropic API probe result
- Local providers that get a 404 on `/v1/messages` successfully fall back to OpenAI API
- No double `/v1/v1/` appears in any probe URL
- `pm init` detects Ollama correctly: skips when not installed, advises when not running, lists models and offers setup when running
- Init does not prompt in non-interactive mode
- Remote integration tests skip cleanly when env vars are not set

### FAIL
- `pm model show` hides the providers section when no providers are configured
- Provider verification conflates inference failure with tool-use failure (both marked False when only tool-use should fail)
- Anthropic API probe generates double `/v1` in URL
- Local provider 404 fallback does not attempt OpenAI API
- Init crashes when Ollama is not installed
- Init prompts in non-interactive (piped) stdin mode
- Remote integration tests fail instead of skipping when env vars are missing

## Ambiguities

### A1: What counts as "always visible" in model show?
**Resolution**: The section header "Available local/external providers:" always prints. The body shows either the provider table or a "none configured" message with add instructions. This matches the current implementation at model.py:56-71.

### A2: Should the Anthropic API probe result be a warning?
**Resolution**: No. `anthropic_api=True` is informational (displayed by CLI) but does NOT generate a warning that would trigger "Add anyway?" in `pm provider add`. This is verified by the test `test_anthropic_api_does_not_produce_warning`.

### A3: Should inference_ok be independent of tool_use?
**Resolution**: Yes. A model that responds but doesn't use tools has `inference_ok=True, tool_use=False`. This is the key distinction this PR adds. Verified by `test_tool_use_failure_but_inference_ok`.

### A4: What happens when local provider's `/v1/messages` returns 404?
**Resolution**: The code resets tool_use/inference state to None and falls back to OpenAI's `/v1/chat/completions`. This is NOT treated as a failure — it's an expected path for Ollama instances without Anthropic API support. Verified by `test_local_provider_fallback_to_openai_on_404`.

### A5: Remote integration test scope — tool-use or just connectivity/inference?
**Resolution**: Tests run `check_provider` with `check_tools=True` but accept that `tool_use` may be False. The key assertion is `inference_ok is True`. This is appropriate because we don't control the remote model's tool-use capability.

## Mocks

### For unit tests (tests/test_providers.py, tests/test_provider_integration.py)
All HTTP calls are mocked via `@patch("urllib.request.urlopen")`. The mock sequences follow the actual call order in `check_provider`:

1. **Connectivity check** — `/api/tags` (local) or `/models` (openai): mock returns HTTP 200
2. **Context window check** — `/api/show` (local) or `/models` (openai): mock returns JSON with model_info or data array
3. **Anthropic API probe** (openai only) — `/v1/messages`: mock returns success or HTTPError(404)
4. **Tool-use check** — `/v1/messages` (local/anthropic) or `/v1/chat/completions` (openai): mock returns JSON with tool_calls or content
5. **OpenAI fallback** (local only, after 404) — `/v1/chat/completions`: mock returns JSON with tool_calls

For CLI-level scenarios (`pm model show`, `pm provider test`, `pm init`), mocking is NOT recommended. These should run against real `pm` CLI with:
- A throwaway `~/.pm/providers.yaml` (or use a temp HOME)
- Ollama if available, or verify skip behavior
- The QA instruction `local-llm-provider.md` provides the manual steps

### What remains unmocked
- The `click` CLI framework (tested via `click.testing.CliRunner` if needed)
- File I/O for providers.yaml (real temp files in integration tests)
- `shutil.which("ollama")` in init detection (real binary lookup)
- `sys.stdin.isatty()` in init (real TTY check)
