# Implementation Spec: Review & QA Regression Benchmark Suite

## Scope of This PR (pr-8aa9411)

This PR delivers the **architecture spec only** — the document you're reading. The actual implementation is broken into four child PRs:

- **pr-83fee65** (PR A): Corpus format, loader, and internal test cases
- **pr-e07f72d** (PR B): Benchmark runner with multi-judge scoring
- **pr-09e8420** (PR C): Agent-driven corpus miner for OSS repos
- **pr-d3a9f46** (PR D): ELO ranking and IRT difficulty calibration

Plus **pr-24f2958** which runs the miner (PR C) against OSS repos to populate the corpus.

This spec is the shared reference for all child PRs. Each PR's notes point back to the relevant spec sections.

---

## 1. Requirements

### R1: Test Case Corpus

Build a structured corpus of before/after code pairs representing known bugs, using **actual diffs** from real commits — not synthetic/handcrafted code. All YAML files are created as part of **pr-83fee65** (PR A) for internal cases and **pr-24f2958** for OSS cases.

Test cases are organized by two orthogonal axes:
- **Source**: `internal` (our own post-merge bugs) vs `oss` (real bugs from open-source projects)
- **Project type & language**: Each case is tagged with its project type and language for filtering and aggregate analysis

**Sources of test cases:**

1. **Internal post-merge bugs** (`source: internal`, `language: python`) — Each test case uses the **actual diff that introduced the bug** (found via `git blame` on the lines the fix commit changed, tracing back to the introducing commit). The `buggy_diff` is the real commit diff that a reviewer should have caught. The `fix_diff` is the actual corrective commit.

   Known fix commits to trace back from (50+ fixes across these categories):
   - `_ensure_workdir` saga: `35d9c88`, `5fbacb7`, `20e4ce7`
   - QA workdir fallback: `ae18778`, `3965601`, `95c3086`
   - Container push proxy: `c4f48c1`, `f2c80ce`, `b147970`, `9d54f8b`, `18b6c54`, `be87c46`, `8218647`, `3c72253`, `d821245`, `2b3ff25`
   - Container isolation: `d4c4bbe`, `bc3cd46`, `61adf28`, `2508ff3`, `4b830cd`, `ded83e1`
   - QA system: `8af7d49`, `ddd8788`, `01d3d46`, `08995c2`, `2d1155b`, `08e5e6a`, `5fd9406`, `a77451b`
   - Race conditions: `b1a4792`, `cdef122`, `6e5eef9`, `1ff43a2`, `8e50573`, `f25c3a2`, `d131173`, `76fd096`
   - Review loop / timeout: `1673578`, `966a692`
   - Dead code / unused imports: `9fe9997`, `491a4b9`, `c70efce`, `39a6da5`
   - Shell quoting: `9c0eea2`, `8e8b38c`, `4194e03`, `1e00755`

   **Process for each fix commit**:
   1. `git show <fix_commit>` — read the fix to understand what was wrong
   2. `git blame <file> <fix_commit>~1` on the buggy lines — find which commit introduced them
   3. `git show <introducing_commit>` — extract the diff that introduced the bug
   4. Record both diffs in the YAML file with metadata

2. **Open source project bugs** (`source: oss`) — **Actual diffs from real bug-introducing commits** in public repos, found by tracing from known fix PRs/CVEs back to the introducing change. Spans diverse project types and languages:

   | Project Type | Example Projects | Language(s) | Bug Patterns |
   |---|---|---|---|
   | `ml-framework` | LangChain, Transformers, vLLM | Python | Model loading races, tokenizer edge cases, prompt injection, tensor shape mismatches |
   | `ml-inference` | llama.cpp, ggml | C/C++ | Memory leaks, buffer overflows, quantization errors, thread safety |
   | `database` | PostgreSQL, Redis | C | Race conditions, null handling, memory leaks, crash recovery |
   | `language-runtime` | CPython, Node.js | C, C++ | Event loop deadlocks, GC bugs, buffer overflows, type confusion |
   | `web-framework` | Django, Express | Python, JavaScript | Injection vulnerabilities, auth bypasses, CSRF, path traversal |
   | `hardware-rtl` | OpenTitan, PULP, Rocket Chip | SystemVerilog, Verilog, Chisel | Clock domain crossings, reset glitches, FSM deadlocks, timing violations, synthesis/simulation mismatches, metastability, incorrect bit-width truncation |

   **Process for OSS bugs**: For each project type, find 3-5 cases by:
   1. Searching the project's issue tracker / CVE database for bugs with known fixes
   2. From the fix commit, `git blame` to find the introducing commit
   3. Extract the actual introducing diff and fix diff
   4. Verify the diff is self-contained enough to review without full repo context (may need to include surrounding file context in the YAML)

**Corpus format**: Each test case is a YAML file under `pm/bench/review_corpus/` with fields:
- `id`: Unique identifier (e.g., `internal-ensure-workdir-clone-path`)
- `source`: `internal` | `oss`
- `language`: Primary language of the code (e.g., `python`, `c`, `cpp`, `systemverilog`, `verilog`, `chisel`, `javascript`)
- `project_type`: Domain classification (e.g., `devtool`, `ml-framework`, `ml-inference`, `database`, `language-runtime`, `web-framework`, `hardware-rtl`)
- `origin`: Where the bug came from — for internal: `{introducing_commit, fix_commit}` hashes; for OSS: `{repo, introducing_commit, fix_commit, issue_url}`
- `bug_type`: Classification tag (e.g., `race-condition`, `security-bypass`, `stale-reference`, `dead-code`, `shell-quoting`, `clock-domain-crossing`, `bit-width-truncation`, `fsm-deadlock`)
- `description`: What the bug is and why it matters
- `buggy_diff`: The **actual diff from the introducing commit** — the real code change that a reviewer should have caught during the original PR review
- `fix_diff`: The **actual diff from the fix commit** — used by the LLM judge to understand what the correct fix looks like
- `file_context`: Optional surrounding file content to give the reviewer enough context to understand the diff (especially for OSS cases where the reviewer doesn't have the full repo)
- `bug_location`: File path and line range where the actual bug lives
- `expected_finding`: What a correct review should identify (human-readable description for the LLM judge)
- `severity`: `critical` | `major` | `minor`
- `difficulty`: `easy` | `medium` | `hard` — initial estimate used as IRT cold-start prior; replaced by empirical IRT parameters after sufficient runs
- `patterns`: List of common-pattern tags for aggregate analysis

**Grounding**: The existing benchmark infrastructure in `pm_core/bench/` provides the pattern — `Exercise` dataclass, loaders (`load_exercises`, `load_evalplus_exercises`), and `orchestrator.py` pipeline. The review benchmark follows the same structure but for code review rather than code generation.

### R2: Benchmark Runner

A runner module at `pm_core/bench/review_bench.py` that:

1. **Loads test cases** from the corpus directory (`pm/bench/review_corpus/`)

2. **Presents buggy code to the review system** by reusing `prompt_gen.py:generate_review_prompt()` directly. For each test case, construct a synthetic PR data dict with the fields that `generate_review_prompt()` expects:
   - `pr["id"]`, `pr["title"]`, `pr["description"]` — from the test case metadata
   - `pr["branch"]` — synthetic branch name
   - `pr["specs"]["impl"]` — **omitted by default** (tests raw review without spec context). Test cases may optionally include an `impl_spec` field; if present, it's injected into the PR dict so the review prompt includes it. This lets us test whether specs help bug detection.
   - The buggy diff is injected where the prompt normally instructs the reviewer to run `git diff` — we replace that instruction with the inline diff text.

   The prompt is generated with `review_loop=False` (no fix/commit instructions — we only want the review analysis). Plan context and sibling PRs are omitted since they don't exist for synthetic test cases.

   **Implementation note**: `generate_review_prompt()` always emits a `Run git diff ...` instruction; it does not accept inline diff text. The runner must post-process the returned prompt string to replace the `git diff` instruction line with the inline buggy diff. This is a simple string replacement and keeps the benchmark decoupled from prompt_gen internals.

   This approach maximizes code reuse: any changes to the review prompt template automatically flow into the benchmark.

3. **Invokes Claude** in headless `--print` mode via CLI subprocess, capturing the full output text. No tmux infrastructure needed.

4. **Scores the output** via LLM-as-judge (see R3)

**Aggregate metrics**:
- **Bug detection rate** (recall): % of test cases where the known bug was found
- **Precision**: % of flagged issues that are real bugs (vs false positives / style nits)
- **Verdict accuracy**: % of test cases where the reviewer correctly output NEEDS_WORK
- **Per-dimension breakdowns**: Metrics split by `project_type`, `language`, and `bug_type`

**Grounding**: Follows the pattern of `pm_core/bench/orchestrator.py` (`BenchmarkRun`, `ExerciseResult`) but adapted for review scoring rather than code generation scoring.

### R3: Scoring Engine (Multi-Judge Panel)

A scoring module at `pm_core/bench/review_scorer.py` that uses a configurable panel of LLM judges to assess whether the review output correctly identified the known bug.

1. **Judge panel configuration**: A `JudgePanel` dataclass specifying one or more judge slots:
   - Each slot has a `model` (e.g., haiku, sonnet, opus) and a `count` (how many copies to run)
   - Example: `[{model: "haiku", count: 3}]` — three haiku judges for cheap majority voting
   - Example: `[{model: "haiku", count: 2}, {model: "sonnet", count: 1}]` — two cheap judges plus one stronger judge for tie-breaking
   - Default panel: `[{model: "haiku", count: 1}]` — single haiku judge for fast/cheap runs
   - Judge slots run in parallel for speed

2. **Per-judge call**: For each (review_output, test_case) pair, each judge is invoked with a structured prompt:
   - Input: the `expected_finding` (what the bug actually is), the `fix_diff` (what the correct fix looks like), and the review output
   - Output: a structured JSON response classifying each distinct issue the reviewer flagged as one of:
     - `SAME_BUG` — the reviewer identified the same bug described in `expected_finding`
     - `REAL_BUG` — the reviewer identified a genuine issue, but not the one we're testing for
     - `FALSE_POSITIVE` — the reviewer flagged something that isn't actually a bug
   - Multiple classifications can be returned simultaneously (a review may find the target bug AND a different real bug AND flag some false positives)

3. **Aggregation across judges**: The panel's individual verdicts are combined:
   - `SAME_BUG`: majority vote across all judges (>50% must agree)
   - `REAL_BUG` / `FALSE_POSITIVE` counts: median count across judges
   - Agreement rate tracked per case — low agreement flags ambiguous cases for corpus refinement
   - Each judge's raw output preserved for debugging

4. **Verdict scoring** (non-LLM): Compare the emitted verdict against expected using `loop_shared.py:extract_verdict_from_content()`. All test cases contain bugs, so NEEDS_WORK is always the correct verdict. This is a simple string match — no judge needed.

5. **Per-case result**: `CaseResult` dataclass with all fields in one place:
   - `bug_found: bool` — majority vote across judges on whether any SAME_BUG finding exists
   - `different_bugs_found: int` — median count of other real bugs identified (REAL_BUG findings)
   - `false_positives: int` — median count of non-issues flagged (FALSE_POSITIVE findings)
   - `quality_score: float` — mean of judges' 1-5 Prometheus scores, normalized to 0.0-1.0
   - `precision: float` — fraction of findings that are SAME_BUG or REAL_BUG (vs FALSE_POSITIVE)
   - `verdict_correct: bool` — did the reviewer output NEEDS_WORK?
   - `judge_agreement: float` — 0.0-1.0, fraction of judges that agreed on `bug_found`
   - `judge_results: list[dict]` — per-judge raw results for debugging

6. **Judge prompt and criteria**: Each judge receives a Prometheus-style structured rubric (adapted from Kim et al., 2024) with explicit per-level descriptions. This format is shown to achieve high inter-judge agreement:

   ```
   You are judging whether a code review correctly identified a known bug.

   ## The Known Bug
   {expected_finding}

   ## The Fix (what correct code looks like)
   {fix_diff}

   ## The Review Output
   {review_output}

   ## Task 1: Classify each finding
   List every distinct issue the reviewer flagged. For each, classify it:

   - SAME_BUG: The reviewer identified the same bug described above,
     even if using different words or focusing on a different symptom
     of the same root cause. Partial identification counts (e.g.,
     "this could race" for a race condition). Identifying the correct
     location but the wrong reason does NOT count.
   - REAL_BUG: A genuine bug or security issue, but different from
     the known bug above.
   - FALSE_POSITIVE: Not actually a bug (style preference, hypothetical
     concern, or misunderstanding of correct code).

   ## Task 2: Rate the review quality (1-5 Prometheus scale)
   Score the overall review on a 1-5 scale:

   1 - Missed the bug entirely, review is unhelpful or misleading
   2 - Vaguely gestured at the problem area but did not identify the
       bug or identified the wrong issue
   3 - Identified the bug but with significant noise (many false
       positives) or weak justification
   4 - Correctly identified the bug with reasonable justification
       and few false positives
   5 - Precisely identified the bug with clear explanation, no false
       positives, and actionable fix suggestion

   Respond with JSON:
   {
     "findings": [{"description": "...", "classification": "SAME_BUG|REAL_BUG|FALSE_POSITIVE"}],
     "quality_score": 1-5,
     "rationale": "Brief explanation of the quality score"
   }
   ```

7. **Aggregate scoring**: The `quality_score` is the primary metric for ranking — it captures detection, precision, and explanation quality in a single graded score, following the established Prometheus rubric methodology. Binary `bug_found` and `verdict_correct` are tracked separately for clear pass/fail reporting.

   Aggregate scores across the corpus: mean `quality_score`, detection rate (% `bug_found`), precision, verdict accuracy. Per-project-type, per-language, and per-bug-type breakdowns.

**Cost**: One LLM call per judge per test case. The judge prompt is small (~500 tokens input). Using multiple cheap judges (haiku) is more cost-effective than a single expensive one and produces more reliable scores through majority voting.

**Prior art**: This scoring approach draws from:
- **CRQBench** (Li et al., 2023): Binary bug-detection scoring per item with real-world code review cases
- **Prometheus** (Kim et al., 2024): Structured 1-5 rubric with explicit per-level criteria for LLM-as-judge
- **MT-Bench** (Zheng et al., 2023): Single-point scoring is more reliable than pairwise for absolute quality; multi-judge panels improve agreement

**Grounding**: The existing `pm_core/bench/executor.py` (`ScoreResult`) provides the pattern for structured scoring results.

### R4: Parameterized Runs, Comparison & Ranking

The runner supports parameterized execution for comparing different configurations, with both percentage success metrics and ELO ranking.

1. **Parameters that can vary**:
   - `model`: Model identifier (sonnet, opus, haiku) — maps to `pm_core/model_config.py` session types
   - `effort`: Effort level (low, medium, high) — from `model_config.EFFORT_LEVELS`
   - `prompt_variant`: Which review prompt template to use — allows testing modified prompts against the baseline from `prompt_gen.py:generate_review_prompt()`
   - `system_prompt_additions`: Extra instructions prepended/appended to the review prompt (e.g., watcher instructions, adversarial voting instructions)

2. **Run configuration** stored as a dataclass `ReviewBenchConfig`:
   - `name`: Human-readable run name (e.g., "baseline-sonnet", "with-oversight-watcher")
   - `model`, `effort`, `prompt_variant`, `system_prompt_additions`
   - `corpus_filter`: Optional filter by source, project_type, language, bug_type, severity
   - `max_parallel`: Concurrency limit for API calls

3. **Difficulty calibration via Item Response Theory (IRT)**: Rather than static easy/medium/hard labels, use the 2-Parameter Logistic (2PL) IRT model (adapted from Polo et al., 2024, "tinyBenchmarks"):
   - After accumulating results from 5+ configs, fit IRT parameters per test case:
     - `b` (difficulty): higher = harder to detect. Cases most configs catch get low `b`, cases few catch get high `b`
     - `a` (discrimination): how well this case separates strong from weak configs. High `a` = useful test case; low `a` = either too easy, too hard, or ambiguous
   - Before enough data exists (cold start), use the initial `difficulty` field from the YAML (`easy`/`medium`/`hard` mapped to `b` = -1/0/+1)
   - IRT parameters are stored in `~/.pm/bench/review/irt.json` and updated after each run
   - Enables **adaptive evaluation**: when evaluating a new config, prioritize high-discrimination cases and cases near the config's estimated ability level — fewer cases needed for accurate ranking

4. **Percentage metrics** (per-run): mean quality score, bug detection rate, precision, verdict accuracy, per-category/per-bug-type breakdowns. Directly actionable for a single run.

5. **ELO ranking via Bradley-Terry model** (cross-run, adapted from Chatbot Arena / LMSYS):
   - Each (config, test_case) evaluation produces a pointwise quality score (1-5 from judge panel)
   - For any two configs evaluated on the same test case, the higher-scoring one "wins" the matchup (tie if equal)
   - ELO update: `R_new = R_old + K * (S - E)` where `E = 1/(1 + 10^((R_opp - R_old)/400))`, K=4 for stability
   - IRT difficulty weights the K-factor: matches on high-difficulty cases produce larger ELO updates
   - Bootstrap resampling (100 iterations) provides confidence intervals on rankings
   - ELO scores stored in persistent leaderboard (`~/.pm/bench/review/elo.json`)
   - New configs can be ranked efficiently by running them on a targeted subset of high-discrimination cases — no need to evaluate the full corpus
   - `pm bench review leaderboard` shows rankings with confidence intervals

**Grounding**: Follows the `HyperParams` pattern from `pm_core/bench/solve.py` and the `BenchmarkRun` comparison pattern from `orchestrator.py`.

### R5: Corpus Mining Tool (Agent-Driven)

A tool at `pm_core/bench/review_miner.py` that can be pointed at any git repo to discover bug-fix commits, trace them back to the introducing commit, and generate candidate YAML test cases for the corpus. The core logic is **agent-driven** — rather than hardcoding regex patterns or keyword lists, each stage delegates to a Claude agent with access to git tools, letting the agent use its judgment about what constitutes a bug fix and how to trace it.

**Pipeline:**

1. **Discovery agent** — Given a repo path and optional constraints (date range, path scope, project type), a Claude agent is launched with access to `git log`, `git show`, `git blame`, and the repo's issue tracker (via `gh` if it's a GitHub repo). The agent is prompted to:
   - Browse the commit history and identify commits that fix bugs (using whatever signals it finds: commit messages, issue references, code patterns, `Fixes:` trailers, revert commits, etc.)
   - For each candidate fix, briefly describe what the bug was and why it's a good test case
   - Output a structured list of fix commit hashes with descriptions
   - The agent uses its own judgment — it can look at commit message conventions specific to each project (e.g., Linux kernel uses `Fixes:` tags, PostgreSQL uses `Bug #NNNN`, CPython uses `bpo-NNNN`)
   - Constraints passed to the agent: max candidates to return, date range, file path scope, preference for certain bug types

2. **Tracing agent** — For each fix commit identified in step 1, a separate agent is launched to trace back to the introducing commit:
   - The agent reads the fix diff (`git show <fix_commit>`)
   - Uses `git blame` on the pre-fix state to find which commit introduced the buggy lines
   - Handles complex cases: multiple introducing commits, refactored code, moved files
   - Decides whether the introducing diff is self-contained enough for a reviewer (can add `file_context` if needed)
   - Outputs: introducing commit hash, relevant portion of the introducing diff, file context
   - Skips cases it judges to be poor test cases (introducing commit too large, bug too subtle to catch from the diff alone, etc.)

3. **Classification agent** — For each (introducing, fix) commit pair, an agent classifies and generates metadata:
   - `description`: What the bug is and why it matters
   - `bug_type`: Classification from a provided list of standard tags, or a new tag if none fit
   - `expected_finding`: What a correct reviewer should identify — written as a clear statement for the LLM judge
   - `severity`, `difficulty` estimates
   - `language`, `project_type` detection
   - `file_context`: Surrounding code if needed for the diff to make sense in isolation

4. **Output candidate YAML files** to a staging directory (`~/.pm/bench/review/candidates/`), not directly into the corpus. Each candidate includes an `auto_generated: true` flag.

5. **Human review step** — `pm bench review candidates` lists staged candidates for the user to accept, edit, or reject:
   - `pm bench review accept <id>` — moves the candidate into the corpus directory
   - `pm bench review reject <id>` — deletes the candidate
   - User can edit the YAML before accepting (fix description, adjust severity, etc.)

**Agent invocation**: Each agent stage uses Claude CLI in `--print` mode (same as the benchmark runner). The discovery agent gets a larger context since it needs to browse commit history; the tracing and classification agents get smaller, focused prompts. Stages can run in parallel where independent (e.g., tracing multiple fix commits simultaneously).

**Quality guardrails** (passed as guidance to agents, not hardcoded filters):
- Prefer introducing diffs under ~500 lines (reviewable in a single sitting)
- Prefer cases where the bug and fix are in source code, not tests/docs/config
- Prefer cases where the introducing commit is clearly separable from the fix
- The agents apply these as judgment calls, not rigid rules — an 800-line diff with a critical security bug is still a good test case

**CLI:**
- `pm bench review mine <repo-path> [--since DATE] [--path-glob GLOB] [--max-candidates N] [--project-type TYPE]`
- `pm bench review candidates` — list staged candidates with descriptions
- `pm bench review accept <id> [--edit]` — accept a candidate into the corpus
- `pm bench review reject <id>` — reject a candidate

**Grounding**: Uses standard git operations via the agent's tool access and follows the existing CLI pattern. The agent invocation reuses the same Claude CLI subprocess pattern as the benchmark runner (R2).

### R6: CLI Integration

Add a CLI subcommand under `pm bench review` (in `pm_core/cli/bench.py`) with:

- `pm bench review list` — List test cases with filtering by source/project_type/language/severity/difficulty
- `pm bench review run [--config CONFIG] [--model MODEL] [--effort EFFORT]` — Run the benchmark
- `pm bench review compare RUN_A RUN_B` — Compare two saved runs (percentage metrics + per-case deltas)
- `pm bench review report RUN` — Show detailed results for a run
- `pm bench review leaderboard` — Show ELO rankings across all evaluated configs
- `pm bench review mine <repo-path> [OPTIONS]` — Mine a repo for bug candidates (see R5)
- `pm bench review candidates` — List staged candidates from mining
- `pm bench review accept <id>` — Accept a candidate into the corpus
- `pm bench review reject <id>` — Reject a candidate

**Grounding**: Follows the existing `pm bench` CLI pattern in `pm_core/cli/bench.py`.

### R7: Result Persistence

Benchmark results saved to `~/.pm/bench/review/` as:
- **Run results**: Timestamped JSON files with full reproducibility metadata (config, corpus version, per-case results)
- **ELO leaderboard**: `elo.json` — persistent Bradley-Terry ELO scores with bootstrap confidence intervals, updated after each run
- **IRT parameters**: `irt.json` — per-case difficulty (`b`) and discrimination (`a`) parameters, updated after each run

**Grounding**: Follows the pattern from `pm_core/bench/orchestrator.py:BenchmarkRun.to_dict()`.

## 2. Implicit Requirements

### IR1: Review Prompt Isolation
The benchmark must be able to invoke review analysis without the full tmux/pane infrastructure. The existing review system (`review_loop.py`) is tightly coupled to tmux pane polling. The benchmark needs a "headless" review path that:
- Generates the review prompt via `prompt_gen.py:generate_review_prompt()` (or a parameterized variant)
- Invokes Claude directly via CLI or API (not through a tmux pane)
- Captures the full output text for scoring

### IR2: Deterministic Corpus
Test cases must be self-contained — no external repo clones needed at runtime. The buggy diffs and fix diffs are stored inline in the YAML files. This means extracting diffs from git history during corpus creation, not at benchmark runtime.

### IR3: Reproducibility
Each benchmark run must record enough metadata to reproduce: corpus file hashes, model used, prompt template version, effort level, timestamp. Two runs with identical configs against identical corpus should produce comparable (though not identical, due to LLM non-determinism) results.

### IR4: Cost Awareness
Running the full corpus against an LLM is expensive. The runner must support:
- Filtering to subsets (by source, project_type, language, severity, bug_type)
- Dry-run mode (show what would be tested without invoking the LLM)
- Token usage tracking per test case and aggregate

### IR5: No Circular Dependencies
The benchmark tests the review system but must not import or depend on the review loop machinery (`review_loop.py`, `qa_loop.py`). It should only share prompt generation utilities and the verdict parsing logic from `loop_shared.py`.

## 3. Ambiguities

### A1: How to present internal bugs as reviewable diffs
**Ambiguity**: Internal bugs were fixed in commits on master. To test whether the review system catches them, we need to present the *buggy* code as a diff. But the buggy code was the pre-existing state, not a diff itself.

**Resolution**: Use `git blame` on the lines changed by each fix commit to find the commit that originally **introduced** the buggy code. The introducing commit's diff is the actual code change that a reviewer should have caught — it's the real PR diff that was merged with the bug in it. This is maximally realistic: we're literally replaying the diff that was reviewed and merged with the bug.

### A2: How to invoke Claude for headless review
**Ambiguity**: The existing review system runs Claude in a tmux pane and polls for verdicts. The benchmark needs a non-interactive path.

**Resolution**: Use the Claude CLI in non-interactive (`--print`) mode with the generated prompt piped via stdin. This avoids tmux entirely while using the same prompt. The `claude --print -p "prompt"` pattern returns the full response as text. For model/effort configuration, pass `--model` and `--effort` flags directly.

### A3: Scoring granularity — how to determine if a bug was "found"
**Ambiguity**: A reviewer might describe the bug using different terminology than `expected_finding`. Simple string matching may miss valid identifications or produce false matches.

**Resolution**: Use a configurable panel of LLM judges. Each judge classifies issues the reviewer flagged as: `same_bug_found`, `different_real_bug_found`, or `false_positive`. Multiple classifications can coexist per judge. Results are aggregated via majority vote (for boolean findings) and median (for counts). The verdict (NEEDS_WORK vs PASS) is scored separately via simple string matching (reusing `loop_shared.py`). Multiple judges improve reliability; judge agreement rate flags ambiguous test cases.

### A4: Scope of OSS test cases
**Ambiguity**: The task mentions specific repos but doesn't specify how many test cases or how to select them per project type.

**Resolution**: Use the corpus mining tool (R5) to generate an initial set of 3-5 cases per project type by pointing it at clones of the target repos. The mining agents find bug fixes, trace to introducing commits, and generate candidate YAML files. The user reviews and accepts the best candidates. The corpus is designed to grow over time — `pm bench review mine` can be re-run on any repo to add more cases. The diffs are stored inline in YAML files — no repo clones needed at benchmark runtime (IR2).

### A5: What "watcher configs" means for A/B testing
**Ambiguity**: The task mentions testing different "watcher configs" but watchers operate as continuous monitors, not per-review configurations.

**Resolution**: In the benchmark context, "watcher configs" means testing different system prompt additions that simulate watcher-like oversight. For example, adding adversarial voting instructions (from pr-4eb96ff), oversight watcher prompts (from pr-c21e2ed), or supervisor watcher prompts (from pr-871dbf5) as `system_prompt_additions` in the `ReviewBenchConfig`. This tests whether adding those instructions to the review prompt improves bug detection, without actually running the watcher infrastructure.

### A6: Integration with existing bench CLI
**Ambiguity**: Should review benchmarks be a subcommand of the existing `pm bench` or a separate command?

**Resolution**: Subcommand of `pm bench` — i.e., `pm bench review run`. This keeps all benchmarking under one namespace and reuses the existing CLI infrastructure in `pm_core/cli/bench.py`.

## 4. Edge Cases

### E1: Test cases with multiple bugs
Some commits fixed multiple issues. Each distinct bug should be a separate test case even if they were fixed in the same commit. The scorer handles this by checking each test case's `expected_finding` independently.

### E2: Review output format variation
Claude's review output format isn't strictly structured — the per-file notes and verdict can appear in varying formats:
- Verdict appearing with or without markdown bold (`**NEEDS_WORK**` vs `NEEDS_WORK`)
- File references using absolute paths, relative paths, or just filenames
- Issue descriptions using natural language rather than exact terminology

Verdict parsing is handled by reusing `loop_shared.py:extract_verdict_from_content()` (already battle-tested). Finding identification is handled by the LLM-as-judge, which naturally handles format variation.

### E3: Token limits for large diffs
Some test cases may have large diffs that approach context limits. The runner should:
- Track input token count per test case
- Skip (with a warning) test cases that exceed a configurable token limit
- Include the skip reason in results for transparency

### E4: Model availability
If a configured model is unavailable (rate limited, API error), the runner should:
- Retry with exponential backoff (3 attempts)
- Record the error in the per-case result
- Continue with remaining test cases (don't abort the entire run)

### E5: Corpus versioning
As the corpus grows, benchmark results from different corpus versions aren't directly comparable. Each run records the corpus version (a hash of all YAML files) so comparisons flag version mismatches.

## 5. File Structure

```
pm/bench/review_corpus/               # Test case YAML files, organized by source
  internal/                           # Our own post-merge bugs (python, devtool)
    ensure-workdir-clone-path.yaml
    ensure-workdir-fetch-url.yaml
    ensure-workdir-stale-dict.yaml
    qa-workdir-fallback.yaml
    push-proxy-force-push.yaml
    push-proxy-multi-refspec.yaml
    container-leak.yaml
    container-blank-pane.yaml
    qa-split-pane-crash.yaml
    qa-standalone-crash.yaml
    race-keystroke-buffering.yaml
    race-watcher-accumulation.yaml
    review-loop-timeout.yaml
    tui-systemexit-crash.yaml
    dead-code-unused-imports.yaml
    shell-quoting-missing-shlex.yaml
  oss/                                # Open source project bugs
    ml-framework/                     # Python: LangChain, Transformers, vLLM
      langchain-prompt-injection.yaml
      transformers-tokenizer-edge.yaml
      vllm-model-loading-race.yaml
    ml-inference/                     # C/C++: llama.cpp, ggml
      llama-cpp-memory-leak.yaml
      llama-cpp-thread-safety.yaml
    database/                         # C: PostgreSQL, Redis
      postgresql-null-handling.yaml
      redis-race-condition.yaml
      redis-memory-leak.yaml
    language-runtime/                 # C/C++: CPython, Node.js
      cpython-buffer-overflow.yaml
      nodejs-event-loop-deadlock.yaml
    web-framework/                    # Python/JS: Django, Express
      django-path-traversal.yaml
      express-auth-bypass.yaml
    hardware-rtl/                     # SystemVerilog/Verilog/Chisel
      clock-domain-crossing.yaml
      fsm-deadlock.yaml
      bit-width-truncation.yaml
      reset-glitch.yaml
      synthesis-sim-mismatch.yaml

pm_core/bench/
  review_bench.py                     # Benchmark runner & orchestrator
  review_scorer.py                    # Scoring engine (multi-judge panel)
  review_corpus.py                    # Corpus loader & management
  review_miner.py                     # Agent-driven corpus mining tool
  review_elo.py                       # Bradley-Terry ELO ranking
  review_irt.py                       # IRT difficulty calibration

pm_core/cli/bench.py                  # Extended with `review` subcommand

tests/
  test_review_bench.py                # Unit tests for runner
  test_review_scorer.py               # Unit tests for scorer
  test_review_corpus.py               # Unit tests for corpus loader
  test_review_miner.py                # Unit tests for miner
```

## 6. Data Flow

```
CORPUS MINING (one-time per repo, grows corpus over time):

  pm bench review mine <repo-path>
    │
    ├── Discovery agent: browse git log → list of fix commits
    ├── Tracing agents (parallel): fix commit → introducing commit + diffs
    └── Classification agent: diffs → metadata (description, bug_type, etc.)
    │
    ▼
  Candidate YAML files in ~/.pm/bench/review/candidates/
    │
    ├── pm bench review candidates   (list & review)
    ├── pm bench review accept <id>  (move to corpus)
    └── pm bench review reject <id>  (discard)
    │
    ▼

BENCHMARK EXECUTION:

  Corpus YAML files (pm/bench/review_corpus/)
    │
    ▼
  review_corpus.load_corpus()  →  list[TestCase]
    │
    ▼
  review_bench.ReviewBenchRunner(config)
    │
    ├── For each TestCase:
    │     │
    │     ├── Generate review prompt (prompt_gen or variant)
    │     ├── Invoke Claude CLI (--print mode)
    │     ├── Capture output text
    │     └── review_scorer.score(output, test_case) → CaseResult
    │           │
    │           ├── Judge panel (parallel): classify findings
    │           ├── Verdict check (string match)
    │           └── Quality score (1-5 Prometheus rubric)
    │
    ▼
  ReviewBenchRun (aggregate results)
    │
    ├── Save to ~/.pm/bench/review/
    ├── Update ELO leaderboard (elo.json)
    ├── Update IRT parameters (irt.json)
    └── Display via CLI
```

## 7. PR Breakdown

This spec is too large for a single PR. It should be broken into four PRs with the dependency graph below. Each PR is self-contained and delivers usable functionality on its own.

### PR A: Corpus Format, Loader & Internal Test Cases

**Scope**: R1 (corpus format + internal bugs only), IR2 (deterministic corpus), A1 (tracing introducing commits), E1 (multiple bugs per commit), E5 (corpus versioning)

**Delivers**:
- `pm_core/bench/review_corpus.py` — `TestCase` dataclass matching the YAML schema, `load_corpus()` loader with filtering by source/project_type/language/bug_type/severity/difficulty, corpus version hashing
- `pm/bench/review_corpus/internal/` — YAML test cases mined from the 50+ known fix commits by tracing each to its introducing commit via `git blame`
- `pm bench review list` CLI subcommand (the list portion of R6)
- `tests/test_review_corpus.py` — unit tests for loader, filtering, schema validation

**Does NOT include**: OSS test cases (those come from the miner in PR C), benchmark runner, scoring, ELO, IRT.

**Dependencies**: None — this is the foundation.

**Key files**:
```
pm_core/bench/review_corpus.py        # NEW: TestCase dataclass, load_corpus(), corpus hash
pm/bench/review_corpus/internal/      # NEW: ~16 YAML test case files from internal bugs
pm_core/cli/bench.py                  # MODIFIED: add `review list` subcommand
tests/test_review_corpus.py           # NEW: unit tests
```

---

### PR B: Benchmark Runner & Multi-Judge Scorer

**Scope**: R2 (runner), R3 (multi-judge panel + Prometheus rubric), IR1 (headless review), IR3 (reproducibility), IR4 (cost awareness), IR5 (no circular deps), A2 (headless invocation), A3 (LLM-as-judge), A5 (watcher configs as prompt additions), E2 (output format variation), E3 (token limits), E4 (model availability), R7 (result persistence — run results only, not ELO/IRT)

**Delivers**:
- `pm_core/bench/review_bench.py` — `ReviewBenchConfig` dataclass, `ReviewBenchRunner` that loads corpus → generates review prompts via `prompt_gen.py` → invokes Claude CLI in `--print` mode → scores via judge panel. Supports parameterized model/effort/prompt_variant/system_prompt_additions. Dry-run mode, token tracking, parallel execution.
- `pm_core/bench/review_scorer.py` — `JudgePanel` and `JudgeSlot` dataclasses, `CaseResult` dataclass, structured Prometheus-style judge prompt, multi-judge invocation with parallel execution, majority-vote aggregation, agreement tracking. Verdict scoring via `loop_shared.py:extract_verdict_from_content()`.
- `pm bench review run` and `pm bench review report` CLI subcommands
- Result persistence: timestamped JSON run files in `~/.pm/bench/review/`
- `tests/test_review_bench.py`, `tests/test_review_scorer.py`

**Does NOT include**: ELO ranking, IRT calibration, corpus mining, compare/leaderboard commands.

**Dependencies**: PR A (needs corpus loader and test cases to run against).

**Key files**:
```
pm_core/bench/review_bench.py         # NEW: runner & orchestrator
pm_core/bench/review_scorer.py        # NEW: multi-judge scoring engine
pm_core/cli/bench.py                  # MODIFIED: add `review run`, `review report`
tests/test_review_bench.py            # NEW
tests/test_review_scorer.py           # NEW
```

---

### PR C: Agent-Driven Corpus Miner

**Scope**: R5 (corpus mining tool), A4 (OSS test case sourcing)

**Delivers**:
- `pm_core/bench/review_miner.py` — Three-stage agent pipeline: discovery agent (browse git log for fix commits), tracing agent (blame back to introducing commit), classification agent (generate metadata). Candidate staging to `~/.pm/bench/review/candidates/`.
- `pm bench review mine`, `pm bench review candidates`, `pm bench review accept`, `pm bench review reject` CLI subcommands
- Run the miner against target OSS repos to populate the corpus with cases across all project types (ml-framework, ml-inference, database, language-runtime, web-framework, hardware-rtl)
- `pm/bench/review_corpus/oss/` — Initial set of accepted OSS test cases (3-5 per project type)
- `tests/test_review_miner.py`

**Does NOT include**: Benchmark runner, scoring, ELO, IRT.

**Dependencies**: PR A (needs corpus format/loader so mined cases match the schema and can be loaded). Independent of PR B — can be developed in parallel.

**Key files**:
```
pm_core/bench/review_miner.py         # NEW: agent-driven mining pipeline
pm/bench/review_corpus/oss/           # NEW: mined OSS test cases
pm_core/cli/bench.py                  # MODIFIED: add mine/candidates/accept/reject
tests/test_review_miner.py            # NEW
```

---

### PR D: ELO Ranking & IRT Difficulty Calibration

**Scope**: R4 (parameterized comparison, IRT, ELO), E5 (corpus versioning for comparison)

**Delivers**:
- `pm_core/bench/review_elo.py` — Bradley-Terry ELO implementation: pointwise-to-pairwise conversion, ELO update with K-factor weighted by IRT difficulty, bootstrap resampling for confidence intervals, persistent leaderboard in `elo.json`
- `pm_core/bench/review_irt.py` — 2-Parameter Logistic IRT model: fit `a` (discrimination) and `b` (difficulty) per test case from accumulated run results, cold-start from YAML `difficulty` field, adaptive evaluation (prioritize high-discrimination cases), persistent parameters in `irt.json`
- `pm bench review compare`, `pm bench review leaderboard` CLI subcommands
- `tests/test_review_elo.py`, `tests/test_review_irt.py`

**Does NOT include**: Runner, scorer, miner, corpus creation.

**Dependencies**: PR B (needs run results with per-case quality scores to compute ELO and fit IRT).

**Key files**:
```
pm_core/bench/review_elo.py           # NEW: Bradley-Terry ELO
pm_core/bench/review_irt.py           # NEW: IRT difficulty calibration
pm_core/cli/bench.py                  # MODIFIED: add compare, leaderboard
tests/test_review_elo.py              # NEW
tests/test_review_irt.py              # NEW
```

---

### Dependency Graph

```
PR A: Corpus Format + Loader + Internal Cases
  │
  ├──→ PR B: Benchmark Runner + Multi-Judge Scorer
  │      │
  │      └──→ PR D: ELO Ranking + IRT Calibration
  │
  └──→ PR C: Agent-Driven Corpus Miner (parallel with B)
```

### Summary Table

| PR | Title | Requirements | Key Deliverables | Depends On |
|---|---|---|---|---|
| A | Review benchmark corpus format and internal test cases | R1, IR2, A1, E1, E5 | `review_corpus.py`, internal YAML cases, `list` CLI | — |
| B | Review benchmark runner with multi-judge scoring | R2, R3, IR1, IR3-5, A2-3, A5, E2-4 | `review_bench.py`, `review_scorer.py`, `run`/`report` CLI | A |
| C | Agent-driven corpus miner for OSS repos | R5, A4 | `review_miner.py`, `mine`/`candidates`/`accept`/`reject` CLI, OSS cases | A |
| D | ELO ranking and IRT difficulty calibration | R4, E5 | `review_elo.py`, `review_irt.py`, `compare`/`leaderboard` CLI | B |
