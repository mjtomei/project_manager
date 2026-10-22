# Refactor Migration Map

Generated from the v2 file-migration workflow (run `wyrfqn51u`) plus post-workflow plan corrections (prompts fold into streams; pm_core/agent/ → pm_core/mind/; no separate SpecGenStream; companion pane in TUI). Every existing `pm_core/` Python file is listed with its disposition and per-responsibility migration target.

## Table of contents

1. [By-source dispositions](#by-source-dispositions) — every existing file, what happens to it
2. [By-target consolidation](#by-target-consolidation) — every new file, what existing code feeds it
3. [Stays bucket summary](#stays-bucket-summary)
4. [Deletes bucket summary](#deletes-bucket-summary)
5. [Gaps and proposed additions](#gaps-and-proposed-additions)

## By-source dispositions

Total files: 117.

- **STAYS_UNCHANGED**: 47
- **MOSTLY_STAYS**: 17
- **MIXED**: 11
- **MOSTLY_MOVES**: 30
- **DELETES_ENTIRELY**: 12

### STAYS_UNCHANGED (47)

#### `pm_core/__init__.py`
*Empty __init__.py marking pm_core as a Python package. No code, no exports.*

- **STAYS**: `package marker`
    - *Empty file remains as Python package marker; no functionality to migrate.*

  *Cross-cutting:* Empty package marker; no migration impact.

#### `pm_core/__main__.py`
*Three-line entry point enabling `python -m pm_core` invocation. Imports `main` from `pm_core.cli` and calls it.*

- **STAYS**: `python -m pm_core entry point`
    - *v2 'Stays' list keeps pm_core/cli/ as the CLI command surface; this shim continues to delegate to pm_core.cli.main with no changes needed.*

  *Cross-cutting:* Depends only on pm_core.cli.main existing as the CLI entry. Note that v2 also introduces pm_core/bootstrap.py as a console_scripts entry point shim (renamed from wrapper.py); __main__.py is a separate, complementary entry mechanism (`python -m pm_core`) and is unaffected by that rename.

#### `pm_core/backend.py`
*Abstract Backend ABC with LocalBackend, VanillaBackend, GitHubBackend concrete impls. Provides is_merged() for merge detection and pr_instructions() for generating finalize-PR guidance text. Also detect_backend() (URL heuristics) and get_backend() (config lookup).*

- **STAYS**: `Backend ABC + LocalBackend/VanillaBackend/GitHubBackend`
    - *v2 explicitly lists pm_core/backend.py under 'Stays (not refactored)'.*
- **STAYS**: `is_merged() merge detection (delegates to gh_ops for GitHub)`
    - *gh_ops.py also stays unchanged.*
- **STAYS**: `pr_instructions() — text fragments embedded in PR-start guidance`
    - *Consumed by PR-start flow; may be called from new ImplStream/PRStreamSupervisor but content itself stays here. The instruction text references 'press d in the TUI' / 'pm pr review <id>' — these CLI/TUI surfaces also stay per v2.*
- **STAYS**: `detect_backend() URL heuristic`
    - *Pure helper, no dependencies on refactored modules.*
- **STAYS**: `get_backend(data) — reads project.yaml dict`
    - *Now potentially consumed via ProjectYamlArtifact in sensorium, but the function itself is dict-based and unchanged. Call sites in new code would pass the artifact's underlying dict.*

  *Cross-cutting:* backend.py imports pm_core.git_ops (top-level) and pm_core.gh_ops (lazy). Both stay per v2, so no migration ordering risk. Callers that will move to streams/pr_action.py, streams/merge.py, and supervisors/pr_stream.py will continue importing get_backend()/Backend from here — those new files should import pm_core.backend directly rather than reintroducing the abstraction. The pr_instructions() text mentions TUI keybind 'd' and `pm pr review` CLI; if streams gain a tui_keybinding declaration, the instruction text may want to read it dynamically to stay in sync, but that's a future polish, not a refactor blocker.

#### `pm_core/bench/__init__.py`
*Package init for pm_core/bench — re-exports benchmark harness symbols (Runner, Backend, Exercise loaders for bigcodebench/evalplus, executor) from sibling modules.*

- **STAYS**: `Re-export bench harness API`
    - *v2 plan explicitly lists pm_core/bench/ under 'Stays (not refactored) — benchmark harness; out-of-refactor'.*

  *Cross-cutting:* None — bench is a self-contained harness with no dependencies on the streams/runtime/sensorium primitives being refactored.

#### `pm_core/bench/_utils.py`
*Single helper extract_code() that strips markdown code fences from model responses. Used internally by the bench benchmark harness.*

- **STAYS**: `extract_code`
    - *pm_core/bench/ is explicitly listed under 'Stays (not refactored)' as out-of-refactor benchmark harness. This internal utility stays put.*

  *Cross-cutting:* pm_core/bench/ is out-of-refactor per the v2 plan's Stays list, so this file and its consumers within bench/ are unaffected by the refactor.

#### `pm_core/bench/executor.py`
*Benchmark harness test execution and candidate scoring. Writes candidate solutions to temp dirs, builds/runs test suites for 6 polyglot languages (python, go, rust, javascript, cpp, and one more), and also supports stdin/stdout-based competitive-programming exercises (LiveCodeBench-style). Per-language config drives solution-file naming and test commands.*

- **STAYS**: `Polyglot test execution / candidate scoring`
    - *Proposed structure explicitly lists 'pm_core/bench/ (benchmark harness; out-of-refactor)' under the Stays section. This file is part of that benchmark harness and is not in scope for v2 refactor.*
- **STAYS**: `Stdin/stdout execution for competitive programming (LiveCodeBench)`
    - *Same as above — part of the bench harness, out-of-refactor.*
- **STAYS**: `Per-language build/test config table (_LANG_CONFIG)`
    - *Internal config for the bench harness; unaffected by v2.*

  *Cross-cutting:* pm_core/bench/ is declared out-of-refactor in v2. This file imports only stdlib + pm_core.bench.exercises (also in bench/), so it has no dependency on any module being refactored — nothing in v2 blocks or is blocked by it. If RuntimePlugin ever wants to subsume sandboxed subprocess execution, the bench harness could in principle be retargeted onto runtime/tmux_sandbox.py or runtime/raw_api.py's sandboxed_bash capability, but that is explicitly out of scope per the v2 plan.</cross_cutting_notes> <parameter name="not_in_plan">[]

#### `pm_core/bench/exercises.py`
*Load and parse Exercism exercises from the polyglot benchmark; part of the benchmark harness under pm_core/bench/.*

- **STAYS**: `Exercism exercise loading/parsing` → `/home/matt/claude-work/project-manager/pm_core/bench/exercises.py`
    - *v2 explicitly lists pm_core/bench/ under 'Stays (not refactored)' as benchmark harness, out-of-refactor.*

  *Cross-cutting:* pm_core/bench/ is explicitly out-of-scope for the v2 refactor. No migration required; no downstream blockers identified from this file.

#### `pm_core/bench/exercises_bigcodebench.py`
*Loads BigCodeBench exercises from HuggingFace datasets-server API (full and hard variants), caches them locally under ~/.cache/pm-bench/bigcodebench/, parses task metadata (instruct_prompt, complete_prompt, test, entry_point, libs), and exposes them as Exercise objects to the benchmark harness.*

- **STAYS**: `BigCodeBench dataset fetch + cache + Exercise adaptation`
    - *v2 explicitly lists pm_core/bench/ under 'Stays (not refactored)' as 'benchmark harness; out-of-refactor'. No responsibilities here overlap with mind/runtime/streams/sensorium concerns.*

  *Cross-cutting:* Imports pm_core.paths.bench_cache_dir — v2 notes 'pm_core/paths.py (most; some pieces split out)' stays, so bench_cache_dir likely stays in paths.py. Imports pm_core.bench.exercises.Exercise — sibling in the same out-of-refactor bench/ tree, no migration impact. This file neither blocks nor is blocked by the refactor.

#### `pm_core/bench/exercises_evalplus.py`
*Loads EvalPlus benchmark exercises (HumanEval+, MBPP+) for the bench harness.*

- **STAYS**: `EvalPlus exercise loader` → `pm_core/bench/exercises_evalplus.py`
    - *pm_core/bench/ is explicitly listed under Stays (not refactored) as 'benchmark harness; out-of-refactor'.*

  *Cross-cutting:* The bench/ package is out-of-refactor scope. If it indirectly imports refactored modules (e.g. bridge.py, claude_launcher), those call sites would need updating once those modules move/change, but this file alone (exercise data loading) is unlikely to depend on the refactored surface.

#### `pm_core/bench/exercises_livecodebench.py`
*Benchmark harness loader for LiveCodeBench competitive programming problems. Downloads JSONL chunks from HuggingFace into a local cache dir, decodes compressed/pickled fields, and yields Exercise objects. Pure benchmark plumbing — no agent/runtime/stream concerns.*

- **STAYS**: `HuggingFace JSONL download + caching`
    - *Lives under pm_core/bench/ which v2 explicitly lists as 'Stays (not refactored) — benchmark harness; out-of-refactor'.*
- **STAYS**: `Decode base64/zlib/pickle problem fields`
    - *Internal benchmark data-format detail; no v2 counterpart needed.*
- **STAYS**: `sync_exercises / load_exercises producing Exercise objects`
    - *Consumed by other bench modules; Exercise type stays in pm_core/bench/exercises.py.*
- **STAYS**: `Cache dir resolution via pm_core.paths.bench_cache_dir`
    - *v2 keeps pm_core/paths.py mostly intact ('most; some pieces split out'); bench_cache_dir is unlikely to be among the split pieces.*

  *Cross-cutting:* Depends on pm_core.bench.exercises.Exercise (stays) and pm_core.paths.bench_cache_dir (stays). No downstream agent/runtime/stream code imports this — it's a benchmark-side leaf. Migration of other v2 modules is not blocked by this file, and this file is not blocked by any v2 migration.

#### `pm_core/bench/orchestrator.py`
*Benchmark orchestrator that wires the bench pipeline: loads exercises, generates tests, generates N candidate solutions, scores them via tournament selection, compares against a single-pass baseline, and aggregates token/wall-clock cost. Defines ExerciseResult and BenchmarkRun dataclasses.*

- **STAYS**: `Benchmark orchestration pipeline (tournament + baseline)`
    - *v2 structure explicitly lists pm_core/bench/ under Stays (out-of-refactor).*
- **STAYS**: `ExerciseResult dataclass`
    - *Bench-internal result type; not referenced by mind/runtime/streams.*
- **STAYS**: `BenchmarkRun dataclass + aggregate properties`
    - *Bench-internal aggregation; unaffected by refactor.*

  *Cross-cutting:* pm_core/bench/ is explicitly out-of-refactor in v2. This file imports only from pm_core.bench.* siblings (exercises, executor, runner, solve, test_gen) — no dependencies on bridge.py, claude_launcher, runtime, streams, or anything being moved/deleted. No migration coupling to other plans.

#### `pm_core/bench/runner.py`
*Local-model benchmark harness runner: manages local LLM serving backends (llama.cpp, sglang, vllm) over a unified OpenAI-compatible chat/completions HTTP API. Includes Backend enum, platform-specific probe order, RequestStats dataclass, and HTTP client + server management glue. Self-contained module under pm_core/bench/, used only by the benchmark harness.*

- **STAYS**: `Local LLM backend runner (llama.cpp/sglang/vllm)`
    - *v2 structure explicitly lists pm_core/bench/ under 'Stays (not refactored)' with annotation 'benchmark harness; out-of-refactor'. Nothing in the file overlaps with the refactor surface (no Streams, no Runtime, no Artifacts, no Mind, no prompts) — it's a standalone benchmarking harness orthogonal to the agent runtime architecture.*

  *Cross-cutting:* No dependencies on or from the refactored layers (agent/, runtime/, streams/, prompts/, artifacts/, supervisors/, sensorium/, collaboration/, mind.py). Does not need to coordinate with any other file's migration. Note: this is distinct from pm_core/runtime/ (the new RuntimePlugin seam) and pm_core/providers.py / model_config.py — bench/runner.py is a separate local-inference harness for benchmarking and should not be confused with the RuntimePlugin abstraction.

#### `pm_core/bench/solve.py`
*Multi-candidate solution generator for the benchmark harness. Defines PROMPT_VARIANTS, HyperParams, Candidate, _build_prompt, and generate_candidates which dispatches via Runner.complete/complete_batch with optional chain mode and per-candidate test subsetting.*

- **STAYS**: `PROMPT_VARIANTS + _build_prompt + HyperParams + Candidate + generate_candidates`
    - *v2 'Stays' section explicitly lists pm_core/bench/ as 'benchmark harness; out-of-refactor'. All responsibilities here remain in pm_core/bench/solve.py untouched.*

  *Cross-cutting:* Depends only on sibling pm_core/bench/ modules (_utils, exercises, runner, test_gen), which are all in the out-of-refactor bench package. No cross-package coupling — bench is fully insulated from the refactor. Notably does NOT use bridge.py / RawApiRuntime; it has its own Runner abstraction, so the RawApi migration does not affect bench.

#### `pm_core/bench/test_gen.py`
*Bench harness module: generates test cases from problem descriptions via a local model (parallel or chain mode), merges/splits test suites, and supports subset sampling. Pure utility within pm_core/bench/, no integration with streams/runtime/sensorium.*

- **STAYS**: `Test prompt construction (_build_prompt, _SYSTEM_PROMPT, _TEST_HINTS)`
    - *Bench-local prompt construction; not part of the typed prompts/ tree which is for orchestrated streams.*
- **STAYS**: `Parallel/chain test generation (generate_tests, _generate_tests_chain)`
    - *Uses bench Runner abstraction, not RuntimePlugin. Out-of-refactor per v2 'pm_core/bench/ stays'.*
- **STAYS**: `Test suite merging (_merge_test_suites, _extract_func_name)`
    - *Bench-internal language-aware merging.*
- **STAYS**: `Test splitting and subset sampling (split_test_functions, sample_test_subset)`
    - *Bench-internal utilities.*

  *Cross-cutting:* File is self-contained within pm_core/bench/ (depends on pm_core.bench._utils, pm_core.bench.exercises, pm_core.bench.runner — all in the same out-of-refactor package). No imports from refactored areas; no other files outside bench/ depend on it. v2 explicitly lists 'pm_core/bench/ (benchmark harness; out-of-refactor)' under Stays.

#### `pm_core/cli/bench.py`
*Click CLI group registering `pm bench` with three subcommands: `models` (list backend models), `exercises` (list benchmark exercises across polyglot/livecodebench/evalplus/bigcodebench sources), and `run` (execute a benchmark with tournament selection and optional hyperparams). Thin CLI wrapper delegating to pm_core.bench.runner/orchestrator/solve/exercises_*.*

- **STAYS**: `bench CLI group + subcommand registration`
    - *v2 explicitly lists pm_core/bench/ as out-of-refactor and pm_core/cli/ as mostly stays. This file is a thin Click wrapper over the bench harness.*
- **STAYS**: `delegation to pm_core.bench.runner.Runner (models subcommand)`
    - *pm_core/bench/ stays per v2.*
- **STAYS**: `delegation to pm_core.bench.exercises_* loaders (exercises subcommand)`
- **STAYS**: `delegation to pm_core.bench.orchestrator.run_benchmark + HyperParams (run subcommand)`

  *Cross-cutting:* No dependencies on refactored subsystems (no Stream/Runtime/Artifact usage). Imports only from pm_core.bench.* which v2 lists as out-of-refactor. Safe to leave untouched throughout the migration; does not block or get blocked by other files.

#### `pm_core/cli/fake_github.py`
*CLI command group `pm fake-github config {set,show,clear}` that installs/inspects/clears a per-session fake GitHub backend at ~/.pm/sessions/<tag>/fake-github/. Reads JSON config (inline arg, --file, or stdin), resolves session tag, and delegates to pm_core.fake_github.install_session and pm_core.paths helpers (fake_github_dir, clear_fake_github, get_session_tag).*

- **STAYS**: `pm fake-github CLI command group`
    - *v2 explicitly lists pm_core/cli/ and pm_core/fake_github.py under Stays; this is the CLI surface for the fake-github testing primitive and has no role in the mind/runtime/streams refactor.*
- **STAYS**: `Session-tag resolution (_resolve_tag)`
    - *Wraps pm_core.paths.get_session_tag; paths.py is mostly-stays per v2.*
- **STAYS**: `JSON config ingestion (arg / --file / stdin)`
    - *Pure CLI ergonomics, no overlap with refactored layers.*
- **STAYS**: `install_session delegation`
    - *Calls pm_core.fake_github (listed under Stays).*
- **STAYS**: `state inspection / clearing via paths.fake_github_dir + clear_fake_github`
    - *Both helpers live in pm_core/paths.py (Stays).*

  *Cross-cutting:* Depends on pm_core/fake_github.py and pm_core/paths.py — both explicitly listed under "Stays" in v2, so no migration coupling. No interaction with sensorium/runtime/streams/mind layers. Sibling of pm fake-claude CLI (parallel structure should be preserved if/when FakeClaudeRuntime arrives in pm_core/runtime/fake.py — the runtime is for the in-process plugin, while this CLI manages the out-of-process per-session GitHub state and is orthogonal).

#### `pm_core/cli/model.py`
*Click CLI group `pm model` with show/set/unset subcommands for configuring per-session-type model + effort overrides at either global (~/.pm/settings) or project.yaml level. Thin wrapper over pm_core.model_config + store + paths.*

- **STAYS**: `model show command`
    - *Reads model_config + project.yaml + global settings; v2 keeps pm_core/cli/ and pm_core/model_config.py as-is.*
- **STAYS**: `model set command (global + project)`
    - *Uses store.locked_update + paths.set_global_setting_value. Both store.py and paths.py listed as stays.*
- **STAYS**: `model unset command (global + project)`
    - *Same as set; touches store + pm_home() settings dir.*
- **STAYS**: `validate_model_config display`
    - *Delegates to pm_core.model_config.validate_model_config — model_config.py stays.*
- **STAYS**: `Register `model` group with main CLI`
    - *Standard CLI registration pattern preserved across pm_core/cli/.*

  *Cross-cutting:* Depends only on pm_core/store.py, pm_core/model_config.py, pm_core/paths.py, pm_core/cli/helpers.py — all listed under "Stays" in v2. No coupling to bridge/runtime/stream refactors. If project.yaml access eventually routes through ProjectYamlArtifact (sensorium/artifact/project_yaml.py), the store.locked_update calls here would become call-site updates, but the v2 plan explicitly lists store.py as stays and notes ProjectYamlArtifact consumes it, so no migration required.

#### `pm_core/cli/project.py`
*Click CLI group `pm project` providing `set` and `list` subcommands for project-level boolean settings (currently only `skip-qa`). Reads/writes `project.yaml` via `pm_core.store`. ~96 LOC.*

- **STAYS**: `pm project set/list CLI surface`
    - *v2 plan explicitly says 'pm_core/cli/ (CLI command surface — most stays)'. This file is a pure command surface with no streams/runtime/loop concerns.*
- **STAYS**: `project.yaml read/write via store.load/save`
    - *store.py stays per v2; could later be refactored to go through ProjectYamlArtifact in sensorium/artifact/project_yaml.py, but the CLI seam itself does not need to move.*
- **UNCLEAR**: `skip-qa setting semantics (affects auto-start: review PASS merges directly without QA)`
    - *The setting's *consumer* lives in auto-start watcher / PR supervisor logic. v2 moves auto-start to streams/watchers/auto_start.py and merge gating to streams/merge.py + supervisors/pr_stream.py. Those consumers will need to read this flag — likely via ProjectYamlArtifact. The CLI write side itself stays.*

  *Not in plan:*
  - Generic project-level settings registry (extensible beyond skip-qa): Safe to leave as-is short term. Longer term consider routing all project-level settings through ProjectYamlArtifact (sensorium/artifact/project_yaml.py) and possibly auto-deriving the CLI list from StreamPolicy field metadata.

  *Cross-cutting:* Depends on pm_core.store (stays) and pm_core.cli.helpers.state_root (stays). The skip-qa flag is consumed by auto-start / merge-gating logic; whoever migrates streams/watchers/auto_start.py and streams/merge.py / supervisors/pr_stream.py needs to preserve the read path for project.skip_qa in project.yaml. Module-level `cli.add_command(project)` registration pattern is shared across pm_core/cli/*.py files — keep consistent during any CLI reshuffles.

#### `pm_core/cli/provider.py`
*Click CLI command group `pm provider` with subcommands list/add/remove/default/test for managing LLM provider configurations (Claude API alternatives like Ollama, vLLM, llama.cpp) stored in ~/.pm/providers.yaml. Delegates all real work to pm_core.providers module functions.*

- **STAYS**: `provider_group CLI definition`
    - *Falls under 'pm_core/cli/ — CLI command surface — most stays' per v2 Stays list. No Stream/runtime/sensorium concept involved — it's pure config management for providers.yaml.*
- **STAYS**: `provider list/add/remove/default subcommands`
    - *Thin wrappers over pm_core/providers.py which is explicitly in the Stays list.*
- **STAYS**: `provider test subcommand (connectivity + tool-use check)`
    - *Calls check_provider from pm_core.providers (Stays).*
- **STAYS**: `_display_test_result helper`
    - *Local rendering helper for click output.*

  *Cross-cutting:* Depends on pm_core/providers.py (explicitly Stays) and pm_core/cli/__init__.py (cli group root). No coupling to bridge.py, runtimes, streams, or sensorium — so the v2 refactor doesn't touch this file. RawApiRuntime in pm_core/runtime/raw_api.py will likely consume ProviderConfig from pm_core.providers, but that's a one-way dep that does not require changes here.

#### `pm_core/cluster/__init__.py`
*Package init re-exporting clustering primitives (Chunk, extract_chunks, compute_edges, Cluster, agglomerative_cluster, pre_partition, classify_file, output formatters) from sibling modules inside pm_core/cluster/.*

- **STAYS**: `Re-export cluster API`
    - *v2 explicitly lists pm_core/cluster/ under 'Stays (not refactored)' — clustering for plan-001 is out of refactor scope.*

  *Cross-cutting:* None — file only imports from its own sibling modules in pm_core/cluster/; no dependencies on refactored modules and nothing in the refactor imports it. No migration blockers either direction.

#### `pm_core/cluster/chunks.py`
*Extracts code chunks (functions, classes, files, directories) from a repository via git ls-files, AST parsing of Python sources, and regex tokenization for non-Python files. Provides the Chunk dataclass and the extract_chunks entry point used by the clustering pipeline.*

- **STAYS**: `Chunk dataclass`
    - *Data structure for cluster pipeline; stays in pm_core/cluster/chunks.py*
- **STAYS**: `Git ls-files enumeration with walk fallback`
- **STAYS**: `Python AST chunk extraction (functions/classes/imports/calls/tokens)`
- **STAYS**: `Generic regex tokenization for non-Python files`
- **STAYS**: `Binary detection + size cap filtering`
- **STAYS**: `extract_chunks entry point + directory-level chunk synthesis`

  *Cross-cutting:* v2 plan explicitly lists pm_core/cluster/ under "Stays (not refactored)" as the clustering substrate for plan-001. No imports from refactored layers (uses only stdlib + subprocess for git). No migration blockers either direction.

#### `pm_core/cluster/cluster_graph.py`
*Defines Edge and Cluster dataclasses, an internal Union-Find, an agglomerative average-linkage clustering algorithm, and a cluster naming helper. Pure algorithmic code over Chunk objects from pm_core/cluster/chunks.py. Used by plan-001 clustering feature.*

- **STAYS**: `Edge/Cluster dataclasses` → `pm_core/cluster/cluster_graph.py`
    - *Plan v2 explicitly lists pm_core/cluster/ under 'Stays (not refactored)'.*
- **STAYS**: `_UnionFind helper` → `pm_core/cluster/cluster_graph.py`
- **STAYS**: `agglomerative_cluster algorithm` → `pm_core/cluster/cluster_graph.py`
- **STAYS**: `name_cluster + _common_prefix + _average_linkage` → `pm_core/cluster/cluster_graph.py`

  *Cross-cutting:* Depends on pm_core/cluster/chunks.Chunk; that sibling file is also under pm_core/cluster/ which v2 keeps intact. No imports from any refactored modules, so no migration ordering constraint. Consumers may eventually become a ClusterExplorationStream (streams/cluster_exploration.py listed in v2) but that stream would import this file as-is.

#### `pm_core/cluster/metrics.py`
*Four similarity metrics for code-chunk clustering used by plan-001 (cluster exploration): structural_proximity (file/path), semantic_similarity (token overlap with stopword filtering), cochange_score (git history co-change matrix), and call_graph_score (BFS distance on call graph). Also provides compute_edges aggregator over a chunk list.*

- **STAYS**: `structural_proximity` → `/home/matt/claude-work/project-manager/pm_core/cluster/metrics.py`
    - Path-based proximity metric between two chunks.
- **STAYS**: `semantic_similarity + _build_stopwords` → `/home/matt/claude-work/project-manager/pm_core/cluster/metrics.py`
    - Token-overlap similarity with corpus-derived stopwords.
- **STAYS**: `build_cochange_matrix + cochange_score` → `/home/matt/claude-work/project-manager/pm_core/cluster/metrics.py`
    - Git-log-derived co-change matrix and pairwise score.
- **STAYS**: `build_call_graph + _bfs_distances + compute_call_distances + call_graph_score` → `/home/matt/claude-work/project-manager/pm_core/cluster/metrics.py`
    - Call-graph construction and BFS-distance similarity.
- **STAYS**: `compute_edges` → `/home/matt/claude-work/project-manager/pm_core/cluster/metrics.py`
    - Aggregate all four metrics across a chunk list to produce weighted edges.

  *Cross-cutting:* v2 plan explicitly lists `pm_core/cluster/` under "Stays (not refactored) — clustering for plan-001". No responsibility in this file overlaps with mind/runtime/streams/sensorium concerns. The new `streams/cluster_exploration.py` (ClusterExplorationStream) is the likely consumer of this module; consumer migration is unblocked since the metrics API stays put.

#### `pm_core/cluster/output.py`
*Three output formatters (plan markdown, JSON, text) for Cluster objects from pm_core.cluster.cluster_graph, plus two helpers (_cluster_files, _cluster_description). Pure formatting; no runtime/agent/sensorium coupling.*

- **STAYS**: `clusters_to_plan_markdown`
    - *Plan-markdown emission for `pm plan load` — part of cluster/ which v2 explicitly lists under Stays.*
- **STAYS**: `clusters_to_json`
    - *JSON serialization of clusters; unchanged.*
- **STAYS**: `clusters_to_text`
    - *Human-readable text summary; unchanged.*
- **STAYS**: `_cluster_files / _cluster_description helpers`
    - *Private helpers consumed only within this module.*

  *Cross-cutting:* v2 explicitly lists `pm_core/cluster/` under Stays ("clustering for plan-001"). This file has no dependencies on bridge/wrapper/runtime/agent layers — only on cluster.chunks and cluster.cluster_graph (also staying). No migration coupling. If/when a ClusterExplorationStream (per v2 streams/cluster_exploration.py) is added, it would import these formatters unchanged.

#### `pm_core/cluster/partition.py`
*Pre-partitioning logic for the clustering pipeline: classifies files as docs/config/code, splits code by top-level directory, and merges directories that share cross-imports using union-find. Pure helper module for pm_core/cluster/.*

- **STAYS**: `classify_file (docs/config/code)`
    - *Part of cluster subsystem*
- **STAYS**: `pre_partition by TLD + cross-import union-find`
    - *Internal to clustering pipeline*

  *Cross-cutting:* v2 plan explicitly lists `pm_core/cluster/` under "Stays (not refactored) — clustering for plan-001". This file is fully internal to that subsystem and depends only on `pm_core/cluster/chunks.Chunk`, which also stays. No migration impact on other files.

#### `pm_core/fake_github.py`
*Fake GitHub backend used by regression tests. Provides FakeGitHubRepo (real git repo on disk used as fake remote with worktree-based merges), FakePR (PR record + to_json), FakeGitHubBackend (in-memory PR store + scripted-response engine that intercepts `gh` CLI argv and dispatches to _pr_create/_view/_list/_ready/_merge/_close/_comment), plus session helpers (install_session, save_session, load_session, dispatch_session) that persist a FakeGitHubBackend across test invocations, and convenience flow helpers (create_draft_on_start, upgrade_on_done, merge_with_pull, sync_mid_flow). It is a self-contained test substrate consumed by the regression harness and CI scripts; nothing in the new Mind/Stream/Sensorium model depends on it.*

- **STAYS**: `FakeGitHubRepo (on-disk git repo + worktree-based merge_branch)`
    - *Test substrate; explicitly under 'Stays (not refactored)'.*
- **STAYS**: `FakePR record + to_json field projection`
- **STAYS**: `FakeGitHubBackend in-memory PR store (add_pr, resolve, create_draft, mark_ready, merge, close, add_comment)`
- **STAYS**: `Scripted-response engine (_Scripted, queue_response, simulate_rate_limit/server_error/conflict/not_found, clear_scripts)`
    - *Test-only fault injection; orthogonal to runtime refactor.*
- **STAYS**: `gh CLI argv interception + dispatch (run, _dispatch_pr, _pr_create/_view/_list/_ready/_merge/_close/_comment, _parse_opts)`
    - *Mirrors gh_ops surface; gh_ops.py is listed as Stays.*
- **STAYS**: `Session persistence (install_session, save_session, load_session, dispatch_session, to_state/from_state)`
    - *Cross-process test-state plumbing; not a Mind/Sensorium concern.*
- **STAYS**: `Flow helpers (create_draft_on_start, upgrade_on_done, merge_with_pull, sync_mid_flow)`
    - *Could conceivably be exercised by FakeClaudeRuntime regression tests but file itself doesn't need to move.*
- **STAYS**: `_resolve_real_git helper (find non-shim git binary)`

  *Cross-cutting:* Consumed by regression test harness and by gh_ops.py / git_ops.py / pr_sync.py call sites (all listed as Stays). FakeClaudeRuntime (runtime/fake.py, new) may want to integrate with FakeGitHubBackend.install_session for end-to-end fake-stack tests, but that is an additive consumer and does not force this file to move. No imports from this file block any migration.

#### `pm_core/gh_ops.py`
*Thin wrapper around the `gh` CLI for PR operations (create/list/view/merge/close/ready), plus a pluggable transport seam (set_gh_runner/gh_runner context + session-level fake-github dispatch) that lets FakeGitHubBackend intercept gh calls in tests. Listed under "Stays (not refactored)" in v2.*

- **STAYS**: `Pluggable gh transport (_GH_RUNNER, set_gh_runner, gh_runner ctx, lock+depth)`
    - *Used by fake_github.py (also in Stays list). Concurrency-safe global pointer for test-time interception. No new home needed.*
- **STAYS**: `Session-level fake-github dispatch (_maybe_dispatch_session_fake)`
    - *Bridges to pm_core/fake_github.py (Stays). Out-of-process gate for subprocess `pm pr ...` invocations.*
- **STAYS**: `gh CLI presence + auth check (_check_gh)`
    - *Local guidance/SystemExit; nothing in v2 supersedes it.*
- **STAYS**: `run_gh core (logging, transport dispatch, subprocess.run)`
    - *Foundational helper consumed by gh_ops's own PR fns and by backend.py / pr_sync.py.*
- **STAYS**: `create_pr / create_draft_pr (with idempotent already-exists recovery)`
    - *Consumed by PR backend; PRStreamSupervisor / MergeStream will call through backend.py which calls these.*
- **STAYS**: `get_pr_status / get_pr_state / is_pr_merged / list_prs`
    - *get_pr_state explicitly documented as used by pr_sync.sync_from_github (also Stays).*
- **STAYS**: `merge_pr / close_pr / mark_pr_ready`
    - *Will be invoked from MergeStream/SignoffStream via backend.py rather than directly, but the helpers themselves stay.*

  *Cross-cutting:* Consumers in v2: backend.py (Stays), pr_sync.py (Stays), fake_github.py (Stays), and new MergeStream / SignoffStream / PRStreamSupervisor (which will call these through backend.py rather than directly). No migration of gh_ops itself is required; it is leaf infra. Imports `pm_core.paths` (configure_logger, log_shell_command, fake_github_active) — paths.py is noted as "most stays; some pieces split out", so if logger/log_shell_command helpers or fake_github_active move during the paths.py split, gh_ops's import sites need updating. Also imports `pm_core.fake_github` lazily — that module is in Stays so no break.

#### `pm_core/git_ops.py`
*Low-level git operations: repo root discovery, GitHub repo name parsing, clone, branch checkout, pull-rebase, commit-and-push, dual-remote configuration, pm-branch state sync/push, and remote listing/selection. Used broadly across pm for workdir setup and pm-state synchronization.*

- **STAYS**: `get_git_root / is_git_repo`
    - *Filesystem-level git probing; foundational utility consumed everywhere.*
- **STAYS**: `get_github_repo_name`
    - *Parses GitHub owner/repo from remotes; used by backend/gh_ops.*
- **STAYS**: `run_git`
    - *Thin subprocess wrapper.*
- **STAYS**: `clone`
    - *Repo clone primitive; consumed by WorkdirRegistry/RepoCheckout setup.*
- **STAYS**: `configure_dual_remote`
    - *Sets origin + local mirror; consumed by container workdir setup (TmuxContainerRuntime) and workdirs.py.*
- **STAYS**: `checkout_branch`
    - *Branch checkout/create; consumed by PR stream startup and Workdir setup.*
- **STAYS**: `pull_rebase / commit_and_push`
    - *Generic git ops; used by sync_state and watchers.*
- **STAYS**: `sync_state / auto_commit_state / push_pm_branch / _checkout_and_restore_pm`
    - *pm-state-branch sync logic. v2 plan explicitly lists pm_core/git_ops.py under Stays. Callers in CLI may move but core stays.*
- **STAYS**: `list_remotes / select_remote`
    - *Remote enumeration/selection; consumed by guide/setup flows.*

  *Cross-cutting:* Explicitly listed under "Stays (not refactored)" in v2. Consumed by: TmuxContainerRuntime (dual-remote + push_proxy interaction), WorkdirRegistry/Workdir (sensorium/workdirs.py), RepoCheckout artifact (sensorium/paths.py), guide/setup stream, backend.py, pr_sync.py, and CLI pm-state sync commands. None of these migrations are blocked by git_ops.py since it stays put — but new consumers (push_proxy.py, TmuxContainerRuntime) will import from here rather than reimplementing.

#### `pm_core/graph.py`
*Pure-functional dependency-graph utilities over PR dicts: adjacency, topological sort, ready/blocked detection, layer assignment, edge-crossing count, and a text-based static graph renderer with status icons.*

- **STAYS**: `build_adjacency` → `pm_core/graph.py`
    - Build adjacency list mapping PR id -> dependents.
- **STAYS**: `topological_sort` → `pm_core/graph.py`
    - Kahn's-algorithm topo sort over PR dicts.
- **STAYS**: `ready_prs` → `pm_core/graph.py`
    - Compute PRs whose deps are merged and status==pending.
- **STAYS**: `blocked_prs` → `pm_core/graph.py`
    - Compute PRs with unmerged deps that are pending/blocked.
- **STAYS**: `compute_layers` → `pm_core/graph.py`
    - Assign PRs to layers by max dep depth, for graph rendering.
- **STAYS**: `count_crossings` → `pm_core/graph.py`
    - Count inverted-order edge crossings between adjacent layers.
- **STAYS**: `render_static_graph` → `pm_core/graph.py`
    - Render a text-based PR dependency graph with status icons; consumed by CLI/TUI graph views.
    - *Inline emoji dict at L142-151 DELETES; reads `PR_STATUS_DISPLAY[status].emoji` from `pm_core/mind/lifecycle.py`. Was the third independent copy of the same mapping (after `cli/__init__.py` and `cli/helpers.py`).*

  *Cross-cutting:* graph.py is pure-functional over PR dicts (which originate from project.yaml via store.py / ProjectYamlArtifact). v2 plan explicitly lists pm_core/graph.py under "Stays". Consumers (TUI tech_tree, CLI graph commands, PRStreamSupervisor for ready-PR detection / auto_start watcher) will need to either keep passing raw PR dicts or adapt by extracting dicts from ProjectYamlArtifact. The auto_start watcher (streams/watchers/auto_start.py) will likely consume ready_prs() — its migration should keep using this module as-is. The status icon set in render_static_graph hard-codes PR lifecycle states; if lifecycle.py's PRStatus StrEnum diverges, this icon map needs syncing (minor call-site update).

#### `pm_core/home_window/__init__.py`
*Defines the HomeWindowProvider Protocol and a small registry/resolver for the "park here" tmux window. Exposes ensure_home_window, park_if_on, refresh_home, park — utilities used by kill-window callsites to keep tmux focus on a stable landing window after pm tears down a window the user was viewing. Default provider is pr-list; lookup driven by the global setting home-window-provider.*

- **STAYS**: `HomeWindowProvider Protocol + registry (register / get_active_provider / _ensure_default_registered)` → `pm_core/home_window/__init__.py`
    - *Listed explicitly under 'Stays (not refactored)' as pm_core/home_window/. Foundational tmux substrate.*
- **STAYS**: `ensure_home_window(session) — create home window if absent` → `pm_core/home_window/__init__.py`
    - *Tmux window plumbing; consumed by kill-window callsites and (post-refactor) by TmuxHostRuntime teardown paths.*
- **STAYS**: `park_if_on(session, target_window_id) — cross-session parking before window kill` → `pm_core/home_window/__init__.py`
    - *Stays put. Will be called by Supervisor teardown / runtime cleanup (which absorb pr_cleanup.py) instead of pr_cleanup directly.*
- **STAYS**: `park(session, home_window) — switch caller's client to home window` → `pm_core/home_window/__init__.py`
    - *Stays.*
- **STAYS**: `refresh_home(session) — wake home window render loop` → `pm_core/home_window/__init__.py`
    - *Stays; still imports pm_core.cli.helpers._get_pm_session lazily.*
- **STAYS**: `Global-setting resolution of provider name ('home-window-provider')` → `pm_core/home_window/__init__.py`
    - *Continues to use pm_core.paths.get_global_setting_value. No sensorium reframing needed for this setting.*

  *Cross-cutting:* Depends on pm_core.tmux (explicitly listed as foundational substrate that stays) and pm_core.paths (mostly stays). Consumers of park_if_on are today in pr_cleanup.py (DELETED — fans out across Supervisor teardown + runtime cleanup hooks); those new callsites in pm_core/supervisors/pr_stream.py and pm_core/runtime/tmux_host.py will need to import from pm_core.home_window. Also consumed by kill-window paths in review_loop.py / qa_loop.py / watcher_manager.py (all DELETED → ReviewStream/Qa*Stream/WatcherSupervisor will be new callers). No migration blocker on this file.

#### `pm_core/home_window/pr_list.py`
*PrListProvider for the pm-home tmux window: ensures a `pm-home` window exists, runs an in-process polling loop that re-runs `pm pr list -t --open`, hashes output to avoid flicker, and refreshes on tick / sentinel-file touch / SIGWINCH. Includes per-session sentinel file management under pm_home()/runtime/.*

- **STAYS**: `PrListProvider.ensure_window`
    - *Tmux window creation for pm-home; explicitly in 'Stays (not refactored)' — pm_core/home_window/ listed as stays.*
- **STAYS**: `Polling render loop (tick + sentinel + SIGWINCH, hash-based repaint)`
    - *Self-contained home-window rendering loop; no overlap with Mind/Stream/Runtime layers.*
- *(Call-site fix)* Inline `{"merged","closed"}` list at `pr_list.py:156` rewrites to `PRStatus.is_terminal()` from `pm_core/mind/lifecycle.py`.
- **STAYS**: `_refresh_sentinel path management`
    - *Uses pm_core.paths.pm_home which v2 lists as 'mostly stays'.*
- **STAYS**: `Invocation of `pm pr list -t --open` subcommand`
    - *Consumes CLI surface, which v2 keeps.*

  *Cross-cutting:* Depends on pm_core.tmux (foundational substrate, stays) and pm_core.paths.pm_home (mostly stays) and pm_core.store.find_project_root (stays). No blockers — this file's stability is not gated on the refactor. Conversely, no other migrating file appears to depend on PrListProvider.

#### `pm_core/pane_registry.py`
*Per-session JSON registry for pm-created tmux panes: file I/O with flock-based locking, atomic writes, schema migration, register/unregister/find-by-role/reconcile operations. Tracks panes grouped by window with role, order, and cmd metadata.*

**Decision (revised per "locking story" consolidation):** pm-coordinated tmux panes are exactly the shape `ResourceLease` covers — named non-file resources with mutual-exclusion semantics. The per-session JSON registry becomes the lease store backing a new `PaneRoleKey`; register/unregister/find-by-role become lease operations; the flock + locked_read_modify_write disappears (replaced by `ResourceLease.acquire/release/renew` semantics).

- **MOVES**: `register_pane / unregister_pane / unregister_windows / find_live_pane_by_role / kill_and_unregister / _reconcile_registry` → `pm_core/sensorium/leases.py` as operations on a new `PaneRoleKey` `ResourceKey` subclass.
    - *Each (session, window, role) tuple is a `PaneRoleKey` lease held by the Stream that owns the pane. Reconcile (today's `_reconcile_registry` cross-checking tmux liveness) becomes `ResourceLease.reconcile(key_prefix='pane:')` invoked on `Supervisor.startup()` and by `OrphanedLeaseWatchdog`. Consumed by `TmuxHostRuntime` and `TmuxContainerRuntime` via the lease API, not via direct registry file I/O.*
- **MOVES**: `Per-session JSON registry I/O (load/save, schema migration, locked-read-modify-write)` → `pm_core/sensorium/leases.py` private store backend
    - *The on-disk JSON file becomes the lease-store backing detail; consumers don't see file paths or locks. The "flat → multi-window format" schema migration absorbs into the lease store's startup-time format detection.*
- **DELETES**: `locked_read_modify_write (fcntl-based concurrency primitive)` — graduated; subsumed by `ResourceLease`'s coordination semantics.
- **STAYS**: `base_session_name (strip ~N grouped-session suffix)`
    - *Pure helper — pure string transform, no coordination role; could move to a small util but no benefit.*

  *Cross-cutting:* v2 references this file at the path `pm_core/tui/pane_registry.py` (under the Stays list) whereas it currently lives at `pm_core/pane_registry.py`. Either v2 implies a relocation into `pm_core/tui/`, or the path in v2 is approximate — clarification needed but content is unchanged either way. Consumers: pm_core/tmux.py companions, TmuxHostRuntime, TmuxContainerRuntime, and current TUI layer. Imports `pm_core.paths.configure_logger` and `pm_core.paths.pane_registry_dir` (paths.py mostly stays); imports `pm_core.tmux` (stays). No incoming dependency blocks the migration of other files.</cross_cutting_notes> </invoke>

#### `pm_core/plans/__init__.py`
*One-line docstring marking pm_core/plans/ as a package containing plan-file parsing and post-step plan-command review logic. No code, no exports.*

- **STAYS**: `package marker`
    - *v2 explicitly lists pm_core/plans/parser.py under Stays, so the package directory and its __init__.py remain. Docstring may want a minor update once plan-command review functionality migrates to streams/plan/review.py, but the file itself stays.*

  *Cross-cutting:* Package houses pm_core/plans/parser.py (explicitly Stays in v2). The "post-step plan-command review" portion of the docstring describes functionality that will be re-encoded as streams/plan/review.py + prompts/plan/review.py + supervisors/plan_stream.py, so the docstring is mildly stale but not blocking.

#### `pm_core/plans/parser.py`
*Pure markdown parsing utilities for plan files: extracts plan intro, ## PRs section into PR dicts, ## Plans section into child-plan dicts, and a generic field extractor. No I/O, no side effects.*

**Decision (revised per "locking story" consolidation):** the file **deletes entirely**. Its parser body folds into `PlanArtifact` (`sensorium/artifact/plan.py`) which delegates structural knowledge to `_plan_markdown.py::PlanMarkdownSchema` and frontmatter handling to `_frontmatter.py`. Three files becoming two (Artifact + Schema) instead of three (Artifact + Schema + Parser) tightens the destination set and removes the temptation to import parser helpers from random call sites.

- **MOVES**: `extract_plan_intro / _parse_section / parse_plan_prs / parse_plan_children / extract_field` → `pm_core/sensorium/artifact/plan.py` (as `PlanArtifact.read()` + `parse_prs()` + `parse_plans()` methods)
    - *Pure parsers; their structural knowledge (heading names, field list, block prefix) consults `_plan_markdown.py::PlanMarkdownSchema` rather than restating literals. Callers `from pm_core.plans.parser import parse_plan_prs` rewrite to `PlanArtifact.read().parse_prs()` (or use a module-level `parse_plan_prs(text)` re-export on `_plan_markdown.py` for cases that have raw text but no Artifact instance).*

  *Cross-cutting:* `plans/parser.py` had ~6 callers across `cli/plan.py`, `cluster/output.py`, `plans/review.py`, and the to-be-created `streams/plan/*` files. After this PR each call site updates to either `PlanArtifact.parse_prs()` (when it has a path) or `PlanMarkdownSchema.parse_prs(text)` (when it has raw text). No `plans/parser.py` module remains for them to import from.

#### `pm_core/providers.py`
*LLM provider configuration layer: defines ProviderConfig dataclass (env vars, model flag, capabilities), load/save/get/set provider helpers backed by a providers.yaml, session-provider override, default-provider management, hardware-aware model recommendation (RAM/GPU detection + RecommendedModel catalog), and a provider health-check harness (context window probe + tool-use probe for Anthropic and OpenAI-compatible APIs).*

- **STAYS**: `ProviderConfig dataclass + env/model/capability accessors`
    - *Explicitly listed under 'Stays (not refactored)'. Consumed by runtime/raw_api.py and runtime/managed_agent.py for credential/model resolution.*
- **STAYS**: `providers.yaml load/save + env-ref resolution (_resolve_env_ref, load_providers, save_providers, _providers_path)`
    - *Config substrate; orthogonal to Mind/Stream refactor.*
- **STAYS**: `get_provider / list_providers / session + default provider management`
    - *Session-override pairs with bootstrap.py session-override resolution but logic stays here.*
- **STAYS**: `RecommendedModel catalog + hardware detection (_get_system_memory_gb, _get_gpu_memory_gb, get_recommended_models, format_model_recommendations)`
    - *Consumed by pm guide/setup flow (streams/guide/setup.py) but the recommendation data/logic itself stays.*
- **STAYS**: `Provider health-check (ProviderTestResult, check_provider, _check_context_window, _check_tools_anthropic, _check_tools_openai)`
    - *Diagnostic probe; not part of the runtime execution seam. RuntimePlugin capabilities (in runtime/protocol.py) are a separate concept from these network probes.*

  *Cross-cutting:* Downstream consumers in v2: runtime/raw_api.py and runtime/managed_agent.py will import ProviderConfig/get_provider to resolve credentials and model IDs (replacing today's bridge.py path). streams/guide/setup.py will consume get_recommended_models/format_model_recommendations. bootstrap.py handles session-override env plumbing but defers actual provider lookup to this module. No migration of this file is required, but the v2 RuntimePlugin Protocol's reports_cost / network_egress capabilities are distinct from ProviderConfig.has_capability — keep the two namespaces clearly separated to avoid confusion.

#### `pm_core/shell.py`
*Thin wrapper exposing shell_quote (shlex.quote re-export) for safe interpolation of user-controlled values into shell command strings.*

- **STAYS**: `shell_quote helper` → `/home/matt/claude-work/project-manager/pm_core/shell.py`
    - *Explicitly listed under 'Stays (not refactored)' in v2 structure ('pm_core/shell.py (shlex.quote helpers; 21 LOC)'). Foundational utility consumed by anything building shell pipelines (git_ops, gh_ops, claude_launcher, container glue, push_proxy).*

  *Cross-cutting:* Likely consumed by pm_core/git_ops.py, pm_core/gh_ops.py, pm_core/claude_launcher.py, and the future runtime/push_proxy.py + runtime/tmux_container.py. No migration blockers — it's a leaf utility.

#### `pm_core/tmux.py`
*Low-level tmux subprocess wrappers: session/window/pane lifecycle (create, kill, split, swap, zoom, layout), grouped-session/multi-client coordination, pane capture and geometry queries, hooks/options/environment, attached-client introspection. ~50 small functions that shell out to `tmux`. Used as foundational substrate by claude_launcher, container.py, TUI pane management, and all Tmux* runtimes.*

- **STAYS**: `tmux command construction + subprocess runner (_tmux_cmd, _run, has_tmux, in_tmux)` → `/home/matt/claude-work/project-manager/pm_core/tmux.py`
    - *Foundational substrate consumed by all Tmux* runtimes per v2 plan.*
- **STAYS**: `session lifecycle (session_exists, create_session, kill_session, attach, set_session_option, set_environment)` → `/home/matt/claude-work/project-manager/pm_core/tmux.py`
- **STAYS**: `window lifecycle (new_window, new_window_get_pane, create_window, kill_window, list_windows, find_window_by_name, select_window, select_window_in_session, get_window_id, get_window_size)` → `/home/matt/claude-work/project-manager/pm_core/tmux.py`
- **STAYS**: `pane operations (split_pane, split_pane_background, split_pane_at, select_pane, resize_pane, swap_pane, zoom_pane/unzoom/is_zoomed, select_pane_smart, get_pane_indices, get_pane_geometries, pane_exists, pane_window_id)` → `/home/matt/claude-work/project-manager/pm_core/tmux.py`
- **STAYS**: `send_keys / send_keys_literal` → `/home/matt/claude-work/project-manager/pm_core/tmux.py`
    - *Used by TmuxHostRuntime to inject input to Claude sessions.*
- **STAYS**: `capture_pane (scrollback capture)` → `/home/matt/claude-work/project-manager/pm_core/tmux.py`
    - *Consumed by StreamTranscript / CaptureService / TmuxHostRuntime.*
- **STAYS**: `layout + hooks (apply_layout, set_hook, refresh_client, set_shared_window_size)` → `/home/matt/claude-work/project-manager/pm_core/tmux.py`
    - *Consumed by tui/pane_layout.py (also listed as stays).*
- **STAYS**: `grouped-session / multi-client coordination (grant_server_access, current_or_base_session, create_grouped_session, list_grouped_sessions, find_unattached_grouped_session, next_grouped_session_name, attached_active_window, sessions_on_window, switch_sessions_to_window, list_clients_in_group, detach_client, get_session_name)` → `/home/matt/claude-work/project-manager/pm_core/tmux.py`
    - *Multi-client/shared-session substrate. Likely consumed by collaboration/transport/tmux_socket.py for same-host cross-mind tmux; consumer is new, but provider stays here.*

  *Cross-cutting:* v2 explicitly lists `pm_core/tmux.py + tui/pane_layout.py + tui/pane_registry.py` under "Stays (not refactored) — foundational substrate consumed by all Tmux* runtimes." This file is a dependency of: runtime/tmux_host.py (new), runtime/tmux_container.py (new), runtime/tmux_sandbox.py (new), claude_launcher.py (stays), tui/* (stays), and likely collaboration/transport/tmux_socket.py (new). No migration blockers — this file is leaf-level and unblocks its consumers rather than being blocked by them. Grouped-session helpers are a natural fit for collaboration/transport/tmux_socket.py's needs; that transport should import from here rather than reimplementing.

#### `pm_core/tui/__init__.py`
*Tiny TUI package init. Exports a single factory `item_message(name, field)` that dynamically constructs a (Selected, Activated) pair of Textual Message subclasses with one ID attribute. Used by TUI widgets (PR list, plan list, etc.) to spawn typed selection/activation messages without boilerplate.*

- **STAYS**: `item_message factory`
    - *Pure Textual UI plumbing; falls under 'pm_core/tui/ (most; UI rendering...)' in the Stays list. No mind/runtime/stream concerns.*
- **STAYS**: `TUI package marker`
    - *Package __init__; remains as-is.*

  *Cross-cutting:* Consumers are TUI widgets only (PR/Plan/Test lists). No coupling to bridge, wrapper, runtime, or stream layers — does not block any migration. The memory note about Textual handler-name camelCase pitfalls (e.g. PRActivated → on_practivated) is directly relevant to any code consuming this factory but does not change the disposition.

#### `pm_core/tui/_shell.py`
*Two tiny helpers (_run_shell sync + _run_shell_async) that wrap subprocess.run / asyncio.create_subprocess_exec with logging of the shlex-joined command and non-zero rc stderr. Used by TUI modules to invoke shell commands.*

- **STAYS**: `_run_shell sync helper with logging`
    - *Plan says 'pm_core/tui/ (most; UI rendering...) stays'. This is a TUI-internal shell helper unrelated to the Mind/Runtime/Stream refactor. No new home is named for it.*
- **STAYS**: `_run_shell_async helper with logging`
    - *Same as above — utility consumed by surviving TUI modules.*
- **STAYS**: `Logger configuration via configure_logger('pm.tui.shell')`
    - *Depends on pm_core/paths.py which v2 says 'mostly stays'.*

  *Not in plan:*
  - Generic shell-with-logging utility: Leave in place. Optionally consolidate with pm_core/shell.py if a non-TUI caller emerges, but no action needed for the refactor.

  *Cross-cutting:* Imports pm_core.paths.configure_logger — survives since paths.py mostly stays. Consumed by TUI modules (likely pane launching / tmux helpers); since tui/ and tmux.py stay, no downstream migrations are blocked by this file.

#### `pm_core/tui/command_bar.py`
*Textual Input widget for the bottom command bar of the TUI. Defines CommandSubmitted message, focus/blur placeholder swapping, buffered-keystroke replay from app-level command buffer, and posts CommandSubmitted on Enter.*

- **STAYS**: `CommandSubmitted message + CommandBar Input widget` → `pm_core/tui/command_bar.py`
    - *Falls under 'pm_core/tui/ (most; UI rendering ...) stays' clause in the v2 plan. Pure Textual UI widget with no agent/runtime semantics.*
- **STAYS**: `Buffered-keystroke replay coordination with app._command_pending/_command_buffer` → `pm_core/tui/command_bar.py`
    - *Tightly coupled to app.py's '/' chord handling; both live in tui/ and stay together.*
- **STAYS**: `Logger via pm_core.paths.configure_logger` → `pm_core/tui/command_bar.py`
    - *pm_core/paths.py is listed as 'mostly stays' so the configure_logger import remains valid.*

  *Cross-cutting:* Reaches into app-level attributes (`app._command_pending`, `app._command_buffer`); migration of app.py's command-chord buffering would need to keep these attributes or update both files together. No dependencies on agent/runtime/streams layers, so this file is not on any migration critical path.

#### `pm_core/tui/frame_capture.py`
*TUI frame capture infrastructure: captures tmux pane content snapshots on state changes (guide step, tech tree selection/PRs), maintains a ring-buffered frame log per session, watches Textual reactive attributes, and exposes a config file for live tuning of frame rate and buffer size. Used for debugging/observability of the TUI.*

- **STAYS**: `Capture config path / load`
    - *get_capture_config_path + load_capture_config — session-scoped JSON config under debug_dir. v2 'Stays' list explicitly retains pm_core/tui/frame_capture.py.*
- **STAYS**: `Frame capture from tmux pane`
    - *capture_frame uses tmux_mod.in_tmux + capture-pane. Consumes pm_core/tmux.py which also stays as foundational substrate.*
- **STAYS**: `Frame buffer persistence (save_frames)`
    - *Writes session-scoped frames JSON to debug_dir; orthogonal to StreamTranscript / EmissionLog.*
- **STAYS**: `Reactive watchers for guide/tech-tree changes`
    - *setup_frame_watchers + on_* callbacks hook Textual reactives — TUI-specific, no analog in agent/runtime layer.*

  *Cross-cutting:* Explicitly listed under v2 'Stays (not refactored)': `pm_core/tui/frame_capture.py, tui/perf.py`. Depends on pm_core.tmux (stays), pm_core.paths (mostly stays), pm_core.tui.guide_progress (TUI, stays), and pm_core.tui.tech_tree (stays). No migration blockers. Note: this is a TUI-side debug capture mechanism distinct from sensorium/captures.py (CaptureBundle/CaptureService) — names are similar but scopes differ; reviewers should not conflate them.

#### `pm_core/tui/guide_progress.py`
*Textual widget rendering a 3-item setup checklist (Project file / Plan file / PRs loaded) based on the current guide step, with done/current/todo markers and a footer pointing to the guide pane and the H rebind. Pure presentation; reads STEP_ORDER from pm_core.guide.*

- **STAYS**: `GuideProgress widget (checklist render)`
    - *UI rendering widget — falls under 'pm_core/tui/ (most; UI rendering ... stays)' in v2. No agent/runtime/stream concerns.*
- **STAYS**: `INTERACTIVE_STEPS / _CHECKLIST mapping from guide STEP_ORDER`
    - *Tightly coupled to pm_core.guide module's STEP_ORDER. v2 puts guide as Streams (streams/guide/{setup,assist}.py) and prompts (prompts/guide/), but the step-ordering constant pm_core.guide.STEP_ORDER is not explicitly addressed — see cross-cutting notes.*
- **STAYS**: `update_step / reactive current_step`
    - *Caller (likely the guide stream or TUI app) will need to push current_step; v2 makes this a thin delegator if it observes a GuideSetupStream's lifecycle, but the widget itself is unchanged.*

  *Not in plan:*
  - pm_core/guide.py STEP_ORDER constant (the data this widget consumes): Either keep pm_core/guide.py in the Stays list as the canonical owner of STEP_ORDER (with streams/guide/setup.py consuming it), or promote STEP_ORDER to a StrEnum inside streams/guide/setup.py and have guide_progress import from there. Recommend the former to keep the TUI widget untouched.

  *Cross-cutting:* Imports STEP_ORDER from pm_core.guide. v2 introduces streams/guide/{setup.py,assist.py} and prompts/guide/ but does not explicitly say what happens to pm_core/guide.py (the module exporting STEP_ORDER). If pm_core/guide.py is folded into streams/guide/setup.py, this import breaks and the widget needs to import STEP_ORDER from the new location (or STEP_ORDER must be re-exported / lifted to lifecycle-like enum). Worth flagging to the synthesizer: pm_core/guide.py (and its STEP_ORDER) has no explicit disposition in v2.

#### `pm_core/tui/perf.py`
*Opt-in keystroke-latency instrumentation for the TUI; explicitly listed under "Stays (not refactored)" in v2 (pm_core/tui/perf.py).*

- **STAYS**: `Keystroke-latency instrumentation` → `pm_core/tui/perf.py`
    - *Explicitly enumerated in the v2 'Stays' list (tui/perf.py). Pure UI-side perf debugging tool, no entanglement with runtime/streams/sensorium concerns.*

  *Cross-cutting:* None — file is self-contained perf instrumentation; no downstream migrations depend on it.

#### `pm_core/tui/plans_pane.py`
*Textual Widget rendering a scrollable list of plans with selection state, key-driven actions (a/w/c/l/e/D), arrow-key navigation, scroll-into-view logic, and PlanSelected/PlanActivated/PlanAction message emission. Pure TUI rendering + input handling over a plans: list[dict] data model fed externally.*

- **STAYS**: `PlanSelected / PlanActivated messages`
    - *Generated via item_message helper; standard TUI message pattern.*
- **STAYS**: `PlanAction message (shortcut keys)`
    - *Action strings consumed by app.py on_plan_action handler; will route to plan/* Streams (plan/add, breakdown, review, deps) after refactor but the Widget surface stays.*
- **STAYS**: `PlansPane Widget — render list + footer shortcuts`
    - *Pure rendering of plan list with status/pr_count/intro; falls under 'pm_core/tui/ (most; UI rendering ...) stays'.*
- **STAYS**: `update_plans(plans: list[dict])`
    - *Data is pushed in from app.py; in v2 the data will originate from PlanArtifact/store.py but the pane API is unchanged.*
- **STAYS**: `Selection state + scroll-into-view (_scroll_selected_into_view, _entry_lines)`
    - *Pure TUI viewport math.*
- **STAYS**: `on_key navigation + action dispatch`
    - *Keybinding map stays; downstream handler in app.py will delegate plan actions to streams/plan/{add,breakdown,review,deps}.py Streams via PlanStreamSupervisor.*

  *Cross-cutting:* Consumed by pm_core/tui/app.py — its on_plan_action handler is the seam that will need to migrate from invoking plan_loop/plan_breakdown helpers directly to calling Mind.stream(role=PlanAddStream|PlanBreakdownStream|PlanReviewStream|PlanDepsStream, ...) via PlanStreamSupervisor. The pane itself only emits PlanAction(action: str); no migration needed here. Data shape ({id, name, file, status, intro, pr_count}) is produced upstream and would in v2 likely be derived from PlanArtifact (pm_core/sensorium/artifact/plan.py) + store.py; pane is agnostic.

#### `pm_core/tui/screens.py`
*Modal screens for the Textual TUI: MergeLockScreen (shows merge-in-progress with countdown), ConnectScreen (shows command to copy to attach to a session), HelpScreen (keybinding help, with discuss action), PlanPickerScreen (pick plan for a PR), PlanAddScreen (create new plan), QACreatePickerScreen (create QA scenario picker), ConfirmCleanupScreen (confirm PR cleanup). All are pure UI/Textual ModalScreen subclasses.*

- **STAYS**: `MergeLockScreen` → `pm_core/tui/screens.py`
    - Modal showing merge progress + countdown for force-dismiss; falls under TUI rendering which the plan keeps under pm_core/tui/.
    - *May need call-site updates: 'merge in progress' state comes from MergeStream + ResourceLease (ChampionSlotKey) instead of legacy MergeLock. UI shell unchanged.*
- **STAYS**: `ConnectScreen` → `pm_core/tui/screens.py`
    - Modal displaying a shell command (tmux attach hint) for copy-paste.
    - *Command string will likely come from RuntimePlugin.attach_hint capability instead of being constructed inline at the call site, but screen itself stays.*
- **STAYS**: `HelpScreen` → `pm_core/tui/screens.py`
    - Modal showing keybinding cheat-sheet, with action_discuss to launch a discuss session.
    - *action_discuss currently launches discuss session directly; under v2 this would route through Mind.stream(role=DiscussStream) in streams/discuss.py. Screen body stays.*
- **STAYS**: `PlanPickerScreen` → `pm_core/tui/screens.py`
    - Modal listing plans to associate with a PR.
    - *Plans list still comes from store.py / ProjectYamlArtifact; UI unchanged.*
- **STAYS**: `PlanAddScreen` → `pm_core/tui/screens.py`
    - Modal prompting for new plan name.
    - *Submission would dispatch a PlanAddStream (streams/plan/add.py) instead of legacy plan-create code; screen body stays.*
- **STAYS**: `QACreatePickerScreen` → `pm_core/tui/screens.py`
    - Modal picker for creating a QA scenario.
    - *Submission delegates to QaAuthorStream / QaScenarioStream (streams/qa_*.py) under v2. UI body unchanged.*
- **STAYS**: `ConfirmCleanupScreen` → `pm_core/tui/screens.py`
    - Confirmation modal for PR cleanup.
    - *Confirm action now triggers PRStreamSupervisor teardown (which absorbs pr_cleanup.py); screen body stays.*

  *Cross-cutting:* screens.py is consumed by pm_core/tui/app.py and various tui modules. Migration of callers is what changes: action_discuss → DiscussStream (streams/discuss.py); PlanAddScreen submit → streams/plan/add.py; QACreatePickerScreen submit → streams/qa_author.py or qa_scenario.py; ConfirmCleanupScreen confirm → supervisors/pr_stream.py teardown (absorbing pr_cleanup.py); MergeLockScreen state → MergeStream + ChampionSlotKey ResourceLease; ConnectScreen command → RuntimePlugin.attach_hint capability. The v2 'Stays' list explicitly keeps pm_core/tui/ rendering, so this file does not move. No MISSING_FROM_PLAN responsibilities — every modal has a clear caller-side new home for its action wiring while the modal UI stays put.

#### `pm_core/tui/tree_layout.py`
*Sugiyama-style layered graph drawing algorithm for the TUI tech tree widget: layer assignment, barycenter crossing minimization, and coordinate assignment producing a TreeLayout dataclass consumed by tech_tree.py for rendering PR dependency graphs.*

- **STAYS**: `TreeLayout dataclass + Sugiyama layout algorithm` → `pm_core/tui/tree_layout.py`
    - *Pure TUI rendering concern; v2 explicitly lists pm_core/tui/ as staying (UI rendering). Consumes pm_core.graph which also stays.*
- **DELETES**: `status_priority dict (L343-351)` — the hardcoded `{"in_review": 0, ...}` map with implicit default-5 for unknown statuses (today's silent-drift source: a new PRStatus member without an entry sorts at priority 5). `_pr_sort_key` reads `PR_STATUS_DISPLAY[status].sort_priority` from `pm_core/mind/lifecycle.py`; the module-load assert `set(PR_STATUS_DISPLAY) == set(PRStatus)` makes the missing-status case impossible.

  *Cross-cutting:* Consumes pm_core.graph (stays). Consumed by pm_core/tui/tech_tree.py (stays as UI). No agent/runtime/stream/sensorium coupling; migration of other modules does not affect this file.

#### `pm_core/tui/widgets.py`
*Reusable Textual widgets for the TUI: TreeScroll (scrollable container for the tech tree), StatusBar (top status bar showing project/sync/PR-count/filter/sort/auto/watcher), SessionBar (override + dangerously-skip-permissions indicator, reads from pm_core.paths.session_dir / skip_permissions_enabled), and LogLine (single-line log output placeholder).*

- **STAYS**: `TreeScroll container`
    - *Pure Textual styling/widget; v2 keeps pm_core/tui/ rendering layer.*
- **STAYS**: `StatusBar with project/sync/watcher/auto indicators`
    - *Display widget. Watcher status string will be fed by WatcherSupervisor instead of watcher_manager, but the widget itself is unchanged. Call sites in app.py adjust.*
- **STAYS**: `SessionBar reading session override + skip-permissions flag`
    - *Reads pm_core.paths.session_dir() and skip_permissions_enabled(); pm_core/paths.py is listed under Stays. Widget unchanged.*
- **STAYS**: `LogLine placeholder Static`
    - *Trivial subclass; no behavioral change.*

  *Cross-cutting:* SessionBar imports pm_core.paths.session_dir and skip_permissions_enabled — paths.py is listed as STAYS (with some pieces split out), so these helpers need to remain accessible. StatusBar.update_status's watcher_status argument is currently driven by the legacy watcher_manager; after migration it will be fed by WatcherSupervisor (pm_core/supervisors/watcher.py) via the app — widget signature itself is stable.

### MOSTLY_STAYS (16)

(claude_launcher.py was previously listed under MOSTLY_STAYS; the decision changed — it DELETES with content split. See its entry under DELETES_ENTIRELY below.)

#### `pm_core/cli/__init__.py`
*Top-level Click CLI group for pm: defines cli group, main() entry, core commands (init, push, edit, which, set/setting, status, prompt, _check, help, getting-started), and wires submodule imports. Holds global settings registry, HELP_TEXT, and onboarding helpers.*

- **STAYS**: `cli group + main()` → `pm_core/cli/__init__.py`
- **STAYS**: `pm init` → `pm_core/cli/__init__.py`
- **STAYS**: `pm push` → `pm_core/cli/__init__.py`
- **STAYS**: `pm edit` → `pm_core/cli/__init__.py`
    - *May later delegate to ProjectYamlArtifact.edit_interactively in pm_core/sensorium/artifact/project_yaml.py.*
- **STAYS**: `pm which` → `pm_core/cli/__init__.py`
- **STAYS**: `settings registry + pm set/setting` → `pm_core/cli/__init__.py`
- **STAYS**: `pm status` → `pm_core/cli/__init__.py`
    - *Inline `status_icons` dict (L407-410) DELETES; replaced by `PR_STATUS_DISPLAY[status].emoji` reads from `pm_core/mind/lifecycle.py`. The hardcoded status-iteration order at L411 DELETES; iterates `PRStatus` enum directly. Eliminates the silent drift the audit found (cli/__init__ status_icons lacks `blocked`, helpers.py PR_STATUS_ICONS has it).*
- **MOVES**: `pm prompt` → `pm_core/streams/impl_system.py`
    - *prompt_gen.py is deleted in v2; body must be rewritten to use a typed InputType from pm_core/prompts/. Click shell stays in cli/__init__.py.*
- **STAYS**: `pm _check` → `pm_core/cli/__init__.py`
- **STAYS**: `_detect_git_repo` → `pm_core/cli/__init__.py`
- **STAYS**: `HELP_TEXT + _getting_started_text + pm help + pm getting-started` → `pm_core/cli/__init__.py`
- **STAYS**: `submodule import wiring` → `pm_core/cli/__init__.py`
    - *Submodule internals (watcher/qa/tui) migrate to streams/supervisors; the import-to-register wiring here stays.*
- **STAYS**: `main() exception wrapper` → `pm_core/cli/__init__.py`

  *Cross-cutting:* Imports pm_core.prompt_gen at module top — prompt_gen is in v2's Deleted list. Migration of prompt_gen blocks this import and the `pm prompt` command body. Submodules imported at bottom (watcher, qa, tui, etc.) have internals migrating to streams/supervisors per v2; the import wiring stays. HELP_TEXT enumerates commands (pm watcher, pm qa run, pm pr start/review, pm tui, pm rebalance) whose backing implementations move — surface text stays, but command bodies are rewritten in submodule files.

#### `pm_core/cli/fake_claude.py`
*CLI command group `pm fake-claude` with two subgroups: `emit` (the stand-in binary's behavior — emits verdicts with configurable preamble/body/delay/streaming/hold for integration testing) and `config` (set/show/clear per-session fake-claude config at ~/.pm/sessions/<tag>/fake-claude that redirects pm flows to the fake instead of real Claude).*

- **STAYS**: `pm fake-claude emit CLI surface`
    - *CLI command surface stays per v2 ('pm_core/cli/ — CLI command surface — most stays'). The underlying pm_core/fake_claude.py module it imports (run_fake_claude) becomes FakeClaudeRuntime in pm_core/runtime/fake.py per the Deleted list, so this command will delegate to the new runtime.*
- **STAYS**: `pm fake-claude config set/show/clear (per-session redirect config)`
    - *CLI commands stay; they call pm_core.paths.{set_fake_claude_config, fake_claude_config, clear_fake_claude}, which per v2 ('pm_core/paths.py — most; some pieces split out') stays. The 'redirect pm flow to fake' wiring conceptually corresponds to selecting FakeClaudeRuntime in runtime/fake.py at stream creation time.*
- **STAYS**: `_resolve_tag helper (session tag resolution)` → `pm_core/cli/fake_claude.py`
    - *Tiny local helper around pm_core.paths.get_session_tag; stays inline.*
- **MOVES**: `ALL_VERDICT_CHOICES import (verdict catalogue)` → `pm_core/streams/protocol.py`
    - *The verdict catalogue currently in pm_core/fake_claude.py corresponds to the ALLOWED_VERDICTS classvar pattern noted in prompts/protocol.py. The CLI's click.Choice will need to be re-sourced from the aggregated InputType catalogue once fake_claude.py is dissolved into runtime/fake.py.*

  *Not in plan:*
  - Per-session fake-claude config file at ~/.pm/sessions/<tag>/fake-claude (JSON mapping session-type → verdicts) — the 'redirect a pm flow to the fake' mechanism: Either (a) document that StreamPolicy / Mind.stream(runtime=...) selection is how fake-vs-real is chosen and have the CLI's config set/show/clear write a policy-overrides file consumed by Mind at stream creation, or (b) add a small note to pm_core/runtime/fake.py that it consumes the existing ~/.pm/sessions/<tag>/fake-claude config for per-role verdict selection. Safe to keep the paths.py helpers as-is in either case.

  *Cross-cutting:* Imports pm_core.fake_claude (ALL_VERDICT_CHOICES, run_fake_claude) — that module is on the Deleted list and becomes pm_core/runtime/fake.py (FakeClaudeRuntime). This CLI file's migration is downstream of runtime/fake.py landing: the `emit` subcommand must be re-pointed at the new runtime's emit entry point, and ALL_VERDICT_CHOICES must be re-exported from runtime/fake.py (or prompts/protocol.py aggregation). Also imports pm_core.paths.{get_session_tag, set_fake_claude_config, fake_claude_config, clear_fake_claude}; those stay per v2's note that pm_core/paths.py mostly stays.

#### `pm_core/cli/log.py`
*Click command group `pm log` that tails/shows/greps/clears the pm session log file (command_log_file()), plus a `sources` subcommand that extracts bracketed source prefixes from log lines. Operates on a flat text log on disk.*

- **STAYS**: `pm log CLI command group (tail/show/grep/clear/path/sources)`
    - *v2 keeps pm_core/cli/ as CLI command surface; this is a user-facing inspection command on the legacy text log.*
- **STAYS**: `Reading/tailing the flat command_log_file() text log`
    - *Relies on pm_core/paths.command_log_file (paths.py stays). However, v2 introduces EmissionLog (SQLite) in pm_core/agent/log.py as the new structured log substrate — this CLI continues to target the legacy session log unless explicitly redirected.*
- **UNCLEAR**: `Source-prefix filtering / sources enumeration`
    - *Bracketed [source] prefix convention is an artifact of today's free-form log emitters. Under v2 the structured equivalent is Emission.stream_id / tag / channel queried via EmissionLog — but the legacy CLI surface can remain as-is over the flat log.*

  *Not in plan:*
  - CLI for querying the new EmissionLog (SQLite) by stream_id / tag / correlation_id / visibility tier: Add a sibling pm_core/cli/emissions.py (or extend pm_core/cli/log.py with subcommands like `pm log emissions --stream <id> --tag <t>`) that queries EmissionLog. Belongs in plan-mind alongside agent/log.py.

  *Cross-cutting:* Depends only on pm_core.paths.command_log_file and pm_core.cli (Click group root). No blockers on other migrations. If/when the legacy text session log is retired in favor of EmissionLog, this file would shift from STAYS to MOSTLY_MOVES (toward a new emissions-inspector CLI), but the v2 plan does not call that out — flagged above.

#### `pm_core/cli/session.py`
*Click CLI module implementing the `pm session` command group and its tmux popup/pane/window internal commands. Responsibilities cluster into: (1) the `pm session` user-facing subcommands (start, name, tag, kill, mobile, home); (2) internal tmux hook handlers (_pane-exited, _pane-closed, _pane-opened, _window-resized, _pane-switch, rebalance); (3) tmux popup launchers and the popup picker / popup command-prompt UIs that drive PR actions via fzf with z/zz chord state-machines; (4) helpers for routing picker commands either directly to pm or through the TUI via SIGUSR2 + queue-file IPC; (5) two registry-write internal commands (_save-session, _clear-session) for claude_launcher's session-id store. It also installs Claude Code hooks (via hook_install) at session start, computes shared-session sockets, and persists pm_root per session-tag so popups can resolve project root.*

**Module-level disposition:** the FILE itself STAYS as the home for `pm session` subcommands and tmux popup launchers. However, the PR-action picker code-path inside it loses its parallel-registry constants (see DELETES below) and is rewired to enumerate `PRActionTUIType.__subclasses__()` at popup-launch time. A future reader should NOT re-introduce a hardcoded `"merge-{display_id}"` or `_ALL_ACTIONS`-style table here; the typed bindings are the source.

- **STAYS**: `pm session group + session_start (tmux session create/attach, shared-socket setup, TUI pane spawn, key/popup bindings registration)` → `pm_core/cli/session.py`
    - *v2 explicitly says 'pm_core/cli/ (CLI command surface — most stays)'. Tmux session orchestration belongs under tmux.py + tui/pane_layout.py which all STAY. Call sites need to swap hook_install import for runtime/hook_entry.py.*
- **MOVES**: `Claude Code hook installation at session start (ensure_hooks_installed import from pm_core.hook_install)` → `pm_core/runtime/hook_entry.py`
    - *hook_install.py is in the Deleted list ('runtime/hook_entry.py + TmuxHostRuntime internals'). The call from _session_start needs to be retargeted; the session entry path should ask the active TmuxHostRuntime to ensure its hook entry is registered, not call a module-level installer.*
- **STAYS**: `session subcommands: name, tag, mobile, home (thin wrappers over paths/pane_layout/home_window)` → `pm_core/cli/session.py`
    - *All call into modules in the STAYS list (paths.py, pane_layout.py, home_window/).*
- **MIXED**: `session kill — kills grouped tmux sessions plus per-session cleanup of containers (cleanup_session_containers) and push proxies (stop_session_proxies)` → `pm_core/cli/session.py`
    - *The CLI handler stays, but `from pm_core.container import cleanup_session_containers` retargets to TmuxContainerRuntime, and `from pm_core.push_proxy import stop_session_proxies` retargets to runtime/push_proxy.py. Cleanup also fans out via Supervisor teardown per the pr_cleanup.py delete note — session kill must invoke the per-PR Supervisor teardown for the PRs in this session, not direct container/proxy module calls.*
- **STAYS**: `Internal tmux hook commands: _pane-exited, _pane-closed, _pane-opened, _window-resized, _pane-switch, rebalance (delegates to pane_layout/pane_registry/tmux)` → `pm_core/cli/session.py`
    - *tmux.py + tui/pane_layout.py + tui/pane_registry.py are foundational substrate per the STAYS list.*
- **STAYS**: `Popup binding registration (_bind_popups, _register_tmux_bindings) and _popup-show dynamic-width launcher` → `pm_core/cli/session.py`
    - *Pure tmux key/popup wiring; no semantic overlap with Streams/Mind.*
- **STAYS**: `_popup-picker (fzf-based PR action picker with z/zz chord state-machine, navigation, ●/○ session indicators)` → `pm_core/cli/session.py`
    - *TUI-adjacent UI surface that drives `pr start/review/qa/merge` and `tui:` commands. Stays as CLI surface; the commands it dispatches (pr review, pr qa, review-loop) are what change per v2 (they delegate to Streams). The picker itself stays as glue.*
- **STAYS**: `_popup-cmd command prompt with abort-key (Esc/Ctrl+C) intercept (_run_with_abort_keys, _wait_dismiss)` → `pm_core/cli/session.py`
    - *Self-contained popup UX glue. Routes 'pr qa' / 'review-loop' through the TUI command bar; under v2 the underlying review-loop/qa command groups delegate to Streams but the dispatch surface here is unchanged.*
- **MIXED**: `TUI IPC routing (_run_picker_command using trigger_tui_command via SIGUSR2 + queue-file, _wait_for_tui_command polling runtime_state)` → `pm_core/cli/session.py`
    - *Function stays in CLI but the runtime_state polling must retarget: v2 deletes runtime_state.py ('folds into EmissionLog + lifecycle.py'). The progress-display poll should instead consult Mind/Supervisor stream LifecycleState via EmissionLog tail, or be reframed as Mailbox/AttentionRequest delivery to the TUI command bar Stream.*
- **DELETES**: `Action/status maps (_ALL_ACTIONS, _MODIFIED_ACTION_CMDS, _ACTION_WINDOW_PATTERNS, _LIST_ACTIONS, _SHORTCUT_FOLD_INTO, _STATUS_PHASE, _SHORTCUT_KEYS, _actions_for_status, _status_phase)` → consolidated into `PRActionTUIType` ClassVars (`command_template`, `modifier_variants`, `window_role`, `picker_list_row`, `fold_into`, `phase_label`, `picker_shortcut`, `applicable_statuses`) — see plan-mind "typed TUI bindings" PR.
- **DELETES**: `_TERMINAL_STATUSES` → `PRStatus.is_terminal()` + `TERMINAL_PR_STATUSES` frozenset on `pm_core/mind/lifecycle.py`. Also replaces the four inline `{"merged","closed"}` checks at `qa_loop.py:2972, 3060, 3095, 3147` and the inline list at `home_window/pr_list.py:156`.
- **MOVES**: `_current_window_phase`, `_current_window_pr_id`, `_build_picker_lines`, `_format_action_status` → rewritten to enumerate `PRActionTUIType.__subclasses__()` and read `window_role` rather than hardcoding the `(?:review-|merge-|qa-)?` alternation. The regex builder is regenerated from registered `window_role` values; renaming a role updates one place.
    - *These encode the picker's UI taxonomy. Under v2 they could optionally be cross-checked against PRActionStream.tui_keybinding/tui_window_role declarations (streams/pr_action.py) so the picker discovers actions from the Stream registry instead of a hard-coded dict — that would be a nice cleanup but is not required by the v2 structure as written.*
- **STAYS**: `_session_active_windows (per-session active-window discovery for ●/○ indicators)` → `pm_core/cli/session.py`
    - *tmux query helper; sits with the picker.*
- **STAYS**: `_resolve_root_from_session (reads persisted pm_root for a session tag)` → `pm_core/cli/session.py`
    - *Wraps paths.get_session_pm_root which STAYS.*
- **STAYS**: `_save-session / _clear-session internal commands (write claude_launcher's session-id registry)` → `pm_core/cli/session.py`
    - *claude_launcher.py is in the STAYS list (consumed by TmuxHostRuntime); these thin wrappers stay too. Could equivalently move into TmuxHostRuntime as a side-channel hook, but the v2 plan does not list claude_launcher session-id persistence as moving.*
- **MIXED**: `Direct CLI dispatch via 'python -m pm_core.wrapper' for non-TUI picker commands and the popup-cmd prompt` → `pm_core/cli/session.py`
    - *wrapper.py is RENAMED to bootstrap.py per v2. All 'python -m pm_core.wrapper' invocations here (lines 1642, 2067) must be updated to 'pm_core.bootstrap'.*

  *Cross-cutting:* Migration blockers from this file: 1. pm_core.wrapper -> pm_core.bootstrap rename: this file invokes `python -m pm_core.wrapper` in two places (_run_picker_command direct path, popup-cmd full_cmd). Bootstrap rename PR must update both call sites. 2. pm_core.hook_install import: _session_start calls ensure_hooks_installed; that module is deleted per v2. Either keep a thin shim or have the TmuxHostRuntime expose an install_hooks method that the CLI calls. 3. pm_core.container.cleanup_session_containers and pm_core.push_proxy.stop_session_proxies imports in session_kill: container.py becomes TmuxContainerRuntime and push_proxy moves to runtime/push_proxy.py. Session kill needs a Supervisor-mediated teardown path (per pr_cleanup.py delete note). 4. runtime_state polling inside _wait_for_tui_command: v2 deletes runtime_state.py. This file's progress-display polling depends on it; either rewrite the wait against EmissionLog/StreamRecord, or keep a compatibility view. 5. The picker's hard-coded action/window-pattern tables duplicate information that PRActionStream declares (tui_keybinding/tui_glyph/tui_window_role/pr_lifecycle_state). Not a blocker, but flagging as a candidate simplification when Streams land. Nothing in this file is MISSING_FROM_PLAN — every responsibility has a clear home, mostly STAYS with import retargets.</cross_cutting_notes> <parameter name="not_in_plan">[]

#### `pm_core/cli/tui.py`
*CLI command surface for the `pm tui` group: launches the interactive Textual TUI (internal `_tui` cmd with crash logging + hook installation), and provides subcommands to view/send-keys/restart the running TUI pane plus capture/replay TUI frame snapshots (history + capture config + frames + clear).*

- **STAYS**: `_tui internal launcher (crash logging, thread excepthook, stderr redirect, ProjectManagerApp.run)` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
    - *Per v2 'Stays': pm_core/cli/ is the CLI command surface and most of it stays. This remains the entry point for spawning the TUI.*
- **MOVES**: `Claude Code hook installation at TUI launch (ensure_hooks_installed)` → `pm_core/runtime/hook_entry.py`
    - *v2 deletes hook_install.py and routes hook plumbing through runtime/hook_entry.py + TmuxHostRuntime internals. The call here needs to be replaced with whatever TmuxHostRuntime's setup invokes.*
- **STAYS**: `tui group dispatcher / alias to `pm session`` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
- **STAYS**: `tui view — capture current pane content via tmux capture-pane` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
    - *Could optionally be reframed as a CaptureBundle / CaptureService call (sensorium/captures.py) but the CLI command itself stays.*
- **STAYS**: `tui history (load/save/_add_frame_to_history; pane_registry_dir/tui-history JSON)` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
    - *Plausibly belongs to CaptureService (sensorium/captures.py) as a CaptureBundle, but v2 keeps cli/ as-is and tui/frame_capture.py also explicitly stays.*
- **STAYS**: `tui send — forward keys to TUI pane via tmux send-keys` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
- **STAYS**: `tui keys — static help text listing keybindings` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
    - *Could be generated from PRActionStream.tui_keybinding declarations on Stream subclasses, but the CLI command stays.*
- **STAYS**: `tui restart — send C-r + optional merge-restart breadcrumb marker` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
    - *merge-restart marker may move into MergeStream / PRStreamSupervisor as a lifecycle signal; CLI surface stays.*
- **STAYS**: `tui clear-history` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
- **STAYS**: `tui capture (frame_rate / buffer_size config JSON in debug_dir)` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
    - *Underlying capture writer is tui/frame_capture.py which v2 says stays.*
- **STAYS**: `tui frames — view captured frames (JSON or pretty)` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
- **STAYS**: `tui clear-frames` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
- **STAYS**: `_find_tui_pane usage / dependence on pane_registry_dir` → `/home/matt/claude-work/project-manager/pm_core/cli/tui.py`
    - *pane_registry stays as foundational substrate (tui/pane_registry.py).*

  *Not in plan:*
  - merge-restart breadcrumb marker semantics (pm_home()/merge-restart used to preserve auto-start + review-loop state across restarts): Encode as a lifecycle/policy concern on PRStreamSupervisor / WatcherSupervisor — on TUI restart, supervisors rehydrate from EmissionLog rather than relying on a filesystem marker. Add a note in plan-mind that restart-survival is a supervisor responsibility and delete the marker file.
  - TUI crash diagnostics: stderr-to-file redirect + threading.excepthook for SystemExit from executor callbacks: Keep in cli/tui.py as bootstrap detail, or move to a small pm_core/tui/crash.py helper. Not worth a plan entry.
  - Static 'pm tui keys' help text — currently hardcoded but should reflect PRActionStream subclasses' tui_keybinding declarations: Auto-generate from the Stream subclass registry once streams/pr_action.py exists; the CLI command stays but its body becomes a registry walk.

  *Cross-cutting:* Imports `pm_core.hook_install.ensure_hooks_installed` and `HookConflictError` — these symbols are slated for deletion (v2: hook_install.py deleted, replaced by runtime/hook_entry.py + TmuxHostRuntime). This file's _tui launcher must be updated when TmuxHostRuntime is introduced. Also imports `pm_core.tmux` and `pm_core.paths.pane_registry_dir/debug_dir` (all stay) and `pm_core.tui.app.ProjectManagerApp` (stays). Consumed by the Click entry point graph in pm_core/cli/__init__.py.

#### `pm_core/cli/watcher.py`
*Click CLI command group for `pm watcher` providing: a bare blocking watcher loop, `start [TYPE]` (including regression-loop meta), `stop`, `list`, and an internal `--iteration N` mode that builds a per-iteration tmux window with a generated prompt and a Claude shell command. Coordinates with WatcherManager, watcher classes (AutoStartWatcher etc.), tmux_mod, claude_launcher, prompt_gen, store, home_window, and model_config.*

- **STAYS**: `pm watcher CLI command group + subcommand surface (start/stop/list/bare)` → `pm_core/cli/watcher.py`
    - *v2 explicitly says 'pm_core/cli/ (CLI command surface — most stays; pm watcher / pm review-loop / pm qa command groups change to delegate to Streams/Supervisors)'. Surface stays; internals rewire.*
- **MOVES**: `Blocking user watcher loop (_run_user_watcher_loop)` → `pm_core/supervisors/watcher.py`
    - *Loop semantics move into WatcherSupervisor; the CLI becomes a thin delegator that asks Mind.supervisor('watcher') to run a chosen watcher Stream.*
- **MOVES**: `Regression-loop meta (_run_regression_loop) — fan-out of discovery + bug-fix-impl + improvement-fix-impl` → `pm_core/supervisors/watcher.py`
    - *WatcherManager is being deleted (watcher_manager.py -> 'rewritten as Stream base + WatcherSupervisor'). Multi-watcher orchestration becomes WatcherSupervisor spawning multiple watcher Streams.*
- **MOVES**: `Internal --iteration mode: build per-iteration tmux watcher window (_create_watcher_window)` → `pm_core/runtime/tmux_host.py`
    - *Tmux window creation, kill+recreate-per-iteration semantics, home_window parking, session switching are all TmuxHostRuntime concerns. Watcher Stream declares loop_mode=kill_restart and TmuxHostRuntime implements the window churn.*
- **MOVES**: `Per-watcher-type prompt selection (discovery / bug-fix-impl / improvement-fix-impl / auto-start)` → `pm_core/streams/watcher/auto_start.py`
    - *Dispatch goes away — each watcher Stream subclass (streams/watchers/{auto_start,bug_fix_impl,improvement_fix_impl,discovery_supervisor}.py) declares its own InputType from prompts/watcher/{auto_start,bug_fix,improvement_fix,watcher_review}.py. prompt_gen.py is in the deleted list.*
- **MOVES**: `Watcher type registry lookup (get_watcher_class / list_watcher_types)` → `pm_core/streams/watchers/__init__.py`
    - *v2 names this explicitly: 'streams/watchers/__init__.py with WATCHER_REGISTRY'. The CLI keeps calling a registry; only the module path and class shape change.*
- **MOVES**: `Transcript directory creation + finalize_transcript symlink cleanup` → `pm_core/mind/transcript.py`
    - *Per-stream transcript handling moves to StreamTranscript (pm-owned, not Claude-owned). CLI no longer pokes the transcript dir directly.*
- **MOVES**: `tmux precondition checks (has_tmux + in_tmux + session_exists)` → `pm_core/runtime/tmux_host.py`
    - *These become capability/precondition checks inside TmuxHostRuntime (declared via required_capabilities on the watcher Stream and validated by the runtime).*
- **STAYS**: `Model/provider/effort resolution for the watcher session` → `pm_core/model_config.py`
    - *model_config.py is in 'Stays (not refactored)'. Call site moves from CLI to runtime/stream policy resolution, but the resolver itself stays.*
- **STAYS**: `Claude shell command construction (build_claude_shell_cmd)` → `pm_core/claude_launcher.py`
    - *claude_launcher.py explicitly 'consumed by TmuxHostRuntime' per v2. Call site moves out of cli/watcher.py into tmux_host.py.*
- **STAYS**: `home_window parking on kill-recreate` → `pm_core/home_window/`
    - *home_window/ stays; consumed from TmuxHostRuntime's kill_restart path instead of CLI.*
- **STAYS**: ``pm watcher stop` help-only stub message` → `pm_core/cli/watcher.py`
    - *Trivial CLI message; stays in CLI surface (or becomes a real stop call into WatcherSupervisor).*

  *Not in plan:*
  - Re-entrant CLI pattern: `pm watcher --iteration N --loop-id ... --transcript ... --watcher-type ...` is the actual subprocess invocation a parent loop uses to spawn the next tmux iteration. Nothing in v2 explicitly names this 'engine spawns child pm invocation for the next iteration' pattern.: Either (a) make WatcherSupervisor + TmuxHostRuntime drive iterations entirely in-process so the --iteration CLI flag goes away, or (b) add a documented `pm_core/runtime/hook_entry.py`-style internal entry point (e.g. an `--iteration` subcommand of hook_entry) that v2 acknowledges. Recommend (a) — the v2 design already implies it via loop_mode=kill_restart on the watcher Stream.
  - 'regression-loop' as a user-visible meta watcher type that bundles three watcher types into one start command: Either add streams/watchers/regression_loop.py as a composite Stream that spawns the three children under one WatcherSupervisor, or document that `pm watcher start regression-loop` is implemented at the CLI layer in pm_core/cli/watcher.py by calling Mind.supervisor('watcher') three times. The former is more consistent with v2's 'one class per role' pattern.
  - Per-watcher-type custom prompt parameters (auto_start_target, meta_pm_root passed through to prompt_gen): meta_pm_root resolution should land in pm_core/sensorium/workdirs.py (WorkdirRegistry) and watcher InputType classes consume it from there rather than via CLI flags.

  *Cross-cutting:* Imports being deleted in v2: prompt_gen (deleted — generate_watcher_prompt + generate_discovery_supervisor_prompt + generate_bug_fix_impl_prompt + generate_improvement_fix_impl_prompt move to prompts/watcher/*), watcher_manager.WatcherManager (deleted — replaced by WatcherSupervisor), pm_core.watchers.auto_start_watcher (rewritten as streams/watchers/auto_start.py), watcher class registry (moves to streams/watchers/__init__.py WATCHER_REGISTRY). Migration of cli/watcher.py is blocked until: (1) WatcherSupervisor exists in supervisors/watcher.py, (2) the streams/watchers/* tree + registry exists, (3) TmuxHostRuntime supports loop_mode=kill_restart with window churn semantics (kill+recreate+park+switch_sessions_to_window). The internal `--iteration N` re-entrant CLI pattern is currently how the watcher loop engine spawns Claude — once TmuxHostRuntime owns the loop, this internal mode flag likely disappears entirely (a behavioral simplification worth noting to the synthesizer).

#### `pm_core/model_config.py`
*Resolves per-session-type model + effort + provider via a precedence hierarchy (PM_MODEL/PM_EFFORT env, PR override, project.yaml model_config, ~/.pm/settings, built-in defaults). Exposes SESSION_TYPES, ModelResolution dataclass, resolve_model, resolve_model_and_provider, get_model_config_summary, validate_model_config, get_pr_model_override. Listed under "Stays (not refactored)" in v2 plan.*

- **STAYS**: `ModelResolution dataclass + resolve_model_and_provider hierarchy`
    - *v2 explicitly lists pm_core/model_config.py under Stays. Core resolution logic remains.*
    - *Per locking-story consolidation: model_config.py is now the typed **schema definition** that pairs with `GlobalSettingsArtifact` (sensorium/artifact/global_settings.py). Today's free-form `get_global_setting_value('default_model')` reads become `global_settings.read().default_model` (typed field access on the schema this module defines). The resolver hierarchy stays here; the persistence + change-notify lives on the Artifact.*
- **STAYS**: `SESSION_TYPES constant + _FALLBACK_TYPES`
    - *Session-type taxonomy is consumed by Stream subclasses (impl/review/qa_*/signoff/watcher/merge). Call sites will reference these via Stream classes, but the constant table itself stays here. May need a new 'meta_development' / 'cluster_exploration' / 'discuss' / 'container_build' / 'plan_*' / 'guide_*' entry as new Stream subclasses arrive — minor extension, not relocation.*
- **STAYS**: `PR-level model override extraction (get_pr_model_override)`
    - *Still reads from PR entry dict; PR data continues to live in project.yaml via ProjectYamlArtifact.*
- **STAYS**: `validate_model_config (project.yaml schema check)`
    - *Consumed by ProjectYamlArtifact validation hook and by 'pm model show' CLI; logic stays in place.*
- **STAYS**: `get_model_config_summary (display helper)`
    - *Used by CLI display; stays.*
- **STAYS**: `Provider-prefix routing (provider:<name>)`
    - *Coupled to pm_core/providers.py which also Stays.*
- **STAYS**: `Effort suppression for Haiku (_NO_EFFORT_MODELS)`
    - *Runtime-agnostic model-capability quirk; remains here.*

  *Not in plan:*
  - Session-type taxonomy extension for new Stream roles: Either (a) extend SESSION_TYPES here as Stream subclasses are added, or (b) derive SESSION_TYPES dynamically from Stream subclass registry (Stream.__init_subclass__ in pm_core/streams/base.py). Option (b) is cleaner — add a note to streams/base.py that it should expose a registry that model_config.py consults.
  - Coupling model selection to Stream class rather than string session_type: Add a thin adapter at the Stream base level (streams/base.py): each Stream subclass declares a session_type classvar that is passed to resolve_model_and_provider. No file relocation needed for model_config.py itself.

  *Cross-cutting:* Imports pm_core.paths.configure_logger + get_global_setting_value — paths.py is mostly Stays (with some pieces split out), so this dependency is stable. Consumed by claude_launcher.py, bridge.py (being deleted; RawApiRuntime will need equivalent model selection), backend.py, and many CLI/TUI sites. RawApiRuntime (runtime/raw_api.py) and TmuxHostRuntime (runtime/tmux_host.py) must both call resolve_model_and_provider when launching a Stream — confirm the new RuntimePlugin Protocol accepts a ModelResolution or that runtimes call this helper themselves. SESSION_TYPES tuple may need to be extended (or replaced by a Stream-class-derived registry) as new Stream subclasses land.

#### `pm_core/notes.py`
*Manages a sectioned notes file (notes.txt committed + notes-local.txt gitignored) with per-prompt-type section filtering. Provides file ensure/migrate/gitignore management, section load/save, edit-template build/parse for editor round-trip, and prompt integration helpers that produce formatted blocks for impl/review/qa/merge/watcher prompts.*

- **STAYS**: `File ensure / create / migrate-old-format / gitignore management`
    - *ensure_notes_file, _migrate_old_format, _update_gitignore — low-level disk plumbing. Per v2 'Stays' list pm_core/notes.py remains; NotesSectionArtifact wraps it.*
- **MOVES (mechanism)** / **STAYS (parser)**: `load_sections, save_sections, _parse_sections` — graduated per "locking story" consolidation. The read-modify-write *mechanism* (file open + write) folds into `NotesSectionArtifact.apply`'s atomic-write + optimistic-version path; `notes.py` keeps only the *pure section-format parser/serializer* (`_parse_sections` and its inverse) which `NotesSectionArtifact` calls during read/write. No flock-style file mutation remains in `notes.py` after this PR.
- **MOVES**: `Edit template build/parse (build_edit_template, parse_edit_template)` → `pm_core/sensorium/artifact/notes.py`
    - *These are the editor round-trip — NotesSectionArtifact's edit_interactively / watch_for_save / propose_edit semantics live on Artifact base. Composite-view editing is artifact-layer concern, though current functions are pure string transforms and could equally stay as helpers consumed by the Artifact.*
- **MOVES**: `Prompt integration: notes_section / notes_for_prompt / load_notes` → `pm_core/streams/_shared_prompts.py`
    - *These produce formatted prompt blocks ('## Session Notes', '## Additional X Instructions') for impl/review/qa/merge/watcher. v2 has prompts/_shared.py for cross-prompt fragments — notes injection is exactly that. The underlying load_sections call stays in notes.py; the formatting helpers move.*
- **MOVES**: `PROMPT_SECTIONS mapping (impl/review/qa/merge/watcher → sections)` → `pm_core/streams/_shared_prompts.py`
    - *Couples notes to prompt taxonomy; belongs alongside the prompt-side consumers.*
- **MOVES**: `Constants: NOTES_HEADER, NOTES_WELCOME, _SECTION_DESCS` → `pm_core/sensorium/artifact/notes.py`
    - *UI/edit-template chrome — belongs with NotesSectionArtifact's interactive-edit surface.*
- **STAYS**: `COMMITTED_SECTIONS / ALL_SECTIONS / section regex constants`
    - *Schema for the file format itself — stays in notes.py as canonical.*

  *Not in plan:*
  - Two-file split (committed notes.txt vs gitignored notes-local.txt) as a sensorium concept: Document that NotesSectionArtifact internally delegates to pm_core/notes.py which manages the two-file split; or model 'Local' section as a second NotesSectionArtifact with VisibilityTier.local — clarify in plan-sensorium.
  - Gitignore mutation (notes.py edits .gitignore): Safe to leave inside ensure_notes_file in notes.py; or factor into sensorium/paths.py if other artifacts need similar gitignore registration. Note in plan-sensorium.
  - Old-format migration (single-file gitignored → sectioned): Safe to keep in notes.py indefinitely or delete once user base has migrated.

  *Cross-cutting:* notes.py is consumed by (a) prompt builders (prompt_gen.py, bug_fix_prompts.py, qa_finalize_prompt.py, etc. — all DELETED in v2 and re-encoded as pm_core/prompts/*.py InputType classes), and (b) the editor flow (editor.py — DELETED, becomes Artifact.open_in_editor + watch_for_save). Migration order: pm_core/prompts/_shared.py must absorb notes_for_prompt/notes_section before the old prompt_gen.py modules are removed. sensorium/artifact/notes.py (NotesSectionArtifact) must wrap load_sections/save_sections before editor.py is removed. PROMPT_SECTIONS keys ('impl','review','qa','merge','watcher') map 1:1 to ImplStream/ReviewStream/Qa*Stream/MergeStream/watcher streams — keep that taxonomy stable across the move.

#### `pm_core/pane_layout.py`
*Tmux pane layout management — recursive binary split algorithm for arranging panes, mobile-mode detection, pane lifecycle event handling (opened/exited/closed), and backward-compat re-exports from pm_core.pane_registry. Explicitly listed under v2 "Stays" as foundational substrate consumed by all Tmux* runtimes (under the path tui/pane_layout.py).*

- **STAYS**: `Recursive binary split layout algorithm` → `pm_core/tui/pane_layout.py`
    - *v2 lists 'tmux.py + tui/pane_layout.py + tui/pane_registry.py (foundational substrate consumed by all Tmux* runtimes)' under Stays. File path moves from pm_core/pane_layout.py to pm_core/tui/pane_layout.py.*
- **STAYS**: `Mobile-mode width detection / threshold reading` → `pm_core/tui/pane_layout.py`
    - *Reads pm-set global config; remains here as TUI layout policy.*
- **STAYS**: `Pane lifecycle event handlers (opened/exited/closed)` → `pm_core/tui/pane_layout.py`
    - *Triggers layout recompute; consumed by TmuxHostRuntime + TmuxContainerRuntime + TmuxSandboxRuntime.*
- **STAYS**: `Backward-compat re-exports of pane_registry functions` → `pm_core/tui/pane_layout.py`
    - *Re-exports from pm_core.pane_registry (also Stays). Likely re-targeted to pm_core/tui/pane_registry.py after the move; pure import shim.*
- **STAYS**: `Min-pane-width setting read` → `pm_core/tui/pane_layout.py`
    - *TUI layout config knob.*

  *Cross-cutting:* v2 places this file at pm_core/tui/pane_layout.py (currently pm_core/pane_layout.py — a path move, not a content refactor). All Tmux* runtimes (tmux_host, tmux_container, tmux_sandbox) in pm_core/runtime/ depend on this substrate; their migration assumes this file (and pane_registry) is importable. Callers using `from pm_core.pane_layout import ...` need a redirect or compat shim during migration. The file already re-exports from pm_core.pane_registry, similarly slated for pm_core/tui/pane_registry.py — the two should move together. pm_core.paths.configure_logger dependency is unaffected.

#### `pm_core/pr_sync.py`
*PR-sync orchestrator: timestamp-throttled detection of merged PRs via gh, updates project.yaml status, finds workdir, and triggers a TUI refresh after sync. Listed in v2 as "Stays".*

- **STAYS**: `SyncResult dataclass + sync_prs / sync_prs_quiet / sync_from_github (gh-driven merged-PR detection and project.yaml status update)`
    - *Explicitly listed under 'Stays' in v2. Core PR-status reconciliation is unchanged; call sites may shift to be invoked by a Supervisor or watcher but the module itself remains.*
- **STAYS**: `get_last_sync_timestamp / set_last_sync_timestamp / should_sync (timestamp throttling on project.yaml)`
    - *Reads/writes project.yaml via store. Once ProjectYamlArtifact exists (sensorium/artifact/project_yaml.py), these may become Artifact.apply call-site updates, but logic itself stays here.*
- **STAYS**: `find_workdir (locates workdir for a PR from project.yaml)` → `pm_core/pr_sync.py`
    - *Overlaps conceptually with sensorium/workdirs.py (WorkdirRegistry+Workdir). Eventually find_workdir should delegate to WorkdirRegistry, but the function itself stays here as a thin adapter.*
- **MOVES**: `_trigger_tui_refresh (signals TUI app to redraw after sync)` → `pm_core/sensorium/artifact/project_yaml.py`
    - *External-write notification — fits Artifact._on_change / _on_external_change pattern on ProjectYamlArtifact. TUI should subscribe to artifact change events rather than pr_sync poking it directly. Until the Artifact layer lands, the helper stays inline; mark as MOVES eventually.*
- **STAYS**: `apply(fresh_data) inner closures that mutate project.yaml under store.update`
    - *Will be retargeted to ProjectYamlArtifact.propose_edit/apply once that exists, but the closure pattern itself lives in pr_sync.*

  *Not in plan:*
  - Push-style notification to TUI after a background PR-sync mutation (_trigger_tui_refresh): Add a note in plan-sensorium that ProjectYamlArtifact.apply must fire on_change so pr_sync (and any other writer) can drop _trigger_tui_refresh and let the TUI subscribe via the Artifact. No new file needed.

  *Cross-cutting:* Depends on: store (project.yaml read/write), gh_ops/backend (gh CLI calls), TUI app singleton for refresh. Consumers: watcher supervisors, auto-start, TUI refresh path, CLI sync commands. Migration order: once ProjectYamlArtifact + on_change exist, _trigger_tui_refresh should be replaced by Artifact-change subscriptions; once WorkdirRegistry exists, find_workdir should delegate. Neither blocks pr_sync from staying put in v2.

#### `pm_core/push_proxy.py`
*Host-side git-push-proxy daemon (~877 LOC) supporting containerized sessions. Resolves real origin URLs for bind-mounted workdirs, starts/stops Unix-socket proxy subprocesses that forward git operations from containers to host credentials, manages shared sockets keyed by session+PR, and provides lifecycle teardown helpers. Consumed by container.py for credential-isolated git access.*

- **MOVES**: `PushProxy daemon (class PushProxy, lines 112-502)` → `pm_core/runtime/push_proxy.py`
    - *v2 explicitly lists runtime/push_proxy.py as ~870 LOC consumed by TmuxContainerRuntime; this is the primary relocation target.*
- **MOVES**: `_resolve_local_remote_url / resolve_real_origin (origin URL resolution for bind-mounted workdirs)` → `pm_core/runtime/push_proxy.py`
    - *Tightly coupled helpers for the proxy; move together. Could alternatively land in git_ops.py, but they exist solely to serve the proxy.*
- **MOVES**: `Shared socket directory / key derivation (_shared_proxy_key, _shared_sock_dir_path, _shared_sock_dir)` → `pm_core/runtime/push_proxy.py`
    - *Internal to proxy lifecycle.*
- **MOVES**: `Proxy subprocess lifecycle (_start_proxy_subprocess, start_push_proxy, _kill_proxy_socket, stop_push_proxy)` → `pm_core/runtime/push_proxy.py` (mechanism) + `pm_core/sensorium/leases.py` (identity)
    - *Revised per locking-story consolidation. The proxy socket file is a pm-coordinated shared resource with mutex semantics ("one proxy per container") — graduates to a new `PushProxySocketKey` `ResourceLease`. The lifecycle code stays in `runtime/push_proxy.py`; lease acquisition/release wraps subprocess start/stop so `OrphanedLeaseWatchdog` can sweep dead proxies whose holder runtime crashed without firing the release. Lease holder = the Stream (or runtime instance) that asked for the proxy.*
- **MOVES**: `Bulk teardown (stop_all_proxies, stop_session_proxies)` → `pm_core/runtime/push_proxy.py`
    - *Becomes `ResourceLease.reconcile(key_prefix='push-proxy:', holder_filter=session_predicate)` invoked from Supervisor teardown — uniform with how every other resource cleans up.*
- **MOVES**: `Liveness/introspection (proxy_is_alive, get_proxy_socket_path, container_socket_path)` → `pm_core/runtime/push_proxy.py`
    - *Used by container runtime to wire socket into the container. Now also consulted by the lease store's reconcile pass to detect dead-but-leased sockets.*

  *Cross-cutting:* container.py is the primary consumer and is itself being rewritten as pm_core/runtime/tmux_container.py — push_proxy can move in the same migration step. Any pr_cleanup.py code path that calls stop_session_proxies / stop_all_proxies must be retargeted; v2 says pr_cleanup fans out across Supervisor teardown + runtime cleanup hooks, so those bulk-stop calls become runtime cleanup hooks on TmuxContainerRuntime. resolve_real_origin may also be called from git_ops / pr_sync flows — verify before moving; if so, leave a thin re-export.

#### `pm_core/store.py`
*YAML read/write for pm/project.yaml: load/save with libyaml fast path, atomic write with read-only safety, advisory file locking (_lock, locked_update, locked_edit), async coalescing WriteQueue for TUI per-keypress mutations, validation of PR/plan statuses and parent cycles, ID generators (plan/pr/note hash-based + sequential), root discovery, init_project bootstrap, and small helpers (get_pr, get_plan, slugify).*

- **STAYS**: `load/save project.yaml (libyaml fast path, atomic write, read-only chmod)`
    - *Explicitly listed under 'Stays' — consumed by ProjectYamlArtifact in sensorium/artifact/project_yaml.py*
- **STAYS**: `find_project_root / is_internal_pm_dir`
    - *Path-walk root discovery; may be partially consumed by sensorium/paths.py PathService but the helper itself stays in store.py*
- **STAYS**: `_validate_pr_statuses / _validate_plans (status normalization, parent-ref check, cycle detection)`
    - *Stays with store; references VALID_PR_STATES from pr_utils which moves — VALID_PR_STATES needs to be importable from lifecycle.py (PRStatus) after pr_utils deletion*
- **DELETES**: `_lock / StoreLockTimeout (fcntl advisory file lock)` — graduated (per "locking story" consolidation). `ProjectYamlArtifact.apply(edit, base_version)` provides optimistic cross-process coordination via the sidecar `.version` file; the pessimistic fcntl path disappears. Writers retry on `VersionConflict` rather than blocking on a lock.
- **DELETES**: `locked_update (atomic read-modify-write)` — graduated. Replaced by `Artifact.apply`'s atomic-write + optimistic-version path. Callers `from pm_core.store import locked_update` rewrite to `project_yaml_artifact.apply(edit, base_version)`.
- **DELETES**: `WriteQueue (async coalescing writer for TUI per-keystroke mutations)` — graduated. Replaced by `Artifact.apply(debounce=timedelta(...))`. The debounce/coalesce semantics live on the Artifact base, not in a per-file queue; TUI per-keystroke writes pass `debounce=` to the same `apply()` entry point that batch writes use.
- **MOVES**: `locked_edit (open $EDITOR under lock, re-read + re-save)` → `pm_core/sensorium/artifact/project_yaml.py`
    - *v2 introduces Artifact.open_in_editor + watch_for_save + edit_interactively on the Artifact base — locked_edit becomes ProjectYamlArtifact.edit_interactively. The lock acquisition + reload logic stays here as a primitive that the Artifact calls.*
- **STAYS**: `make_plan_entry / next_plan_id / next_pr_id / generate_plan_id / generate_pr_id / generate_note_id`
    - *ID generation utilities; PlanArtifact and PR creation flows will consume these*
- **STAYS**: `get_pr / get_plan accessors`
- **STAYS**: `slugify`
    - *Branch-name slug helper; consumed broadly*
- **STAYS**: `init_project (bootstrap new pm/ dir)`
    - *Consumed by CLI 'pm init'; could later move to bootstrap.py but v2 explicitly keeps store.py and bootstrap.py is for sys.path/cwd shim only*
- **STAYS**: `_YAML_HEADER + read-only chmod safety`
- **STAYS**: `ProjectYamlParseError / PlanValidationError exceptions`

  *Not in plan:*
  - VALID_PR_STATES import from pr_utils (which is deleted): Migration note: update store.py import to 'from pm_core.agent.lifecycle import PRStatus' (or equivalent VALID set) when pr_utils is removed.

  *Cross-cutting:* store.py is consumed broadly: TUI app._data, CLI commands, every Supervisor/Stream that mutates PR/plan state will go through ProjectYamlArtifact, which wraps store.load/save/locked_update/WriteQueue. Migration order: ProjectYamlArtifact in sensorium/artifact/project_yaml.py can be introduced as a thin wrapper around store.py without touching store.py itself. BLOCKED-BY: pr_utils deletion — store._validate_pr_statuses imports VALID_PR_STATES from pr_utils; when pr_utils is folded into agent/lifecycle.py (PRStatus), store.py needs the import swap. locked_edit will become a delegator: Artifact.edit_interactively on ProjectYamlArtifact calls store.locked_edit (or store.locked_edit becomes a private helper called by the Artifact). The Artifact base's watch_for_save / _on_external_change hooks need to integrate with the read-only chmod safety so external editors trip the override correctly.

#### `pm_core/tui/app.py`
*Top-level Textual TUI App: composes widgets (status bar, tech tree, command bar, plans/QA panes), defines all keybindings + actions (start/review/merge/signoff/cleanup PR, plans/QA toggles, watcher chord, auto-start), wires message handlers to delegate to pr_view/pane_ops/sync/review_loop_ui/qa_loop_ui/watcher_ui modules, manages in-memory app state (z-modifier, w/y chord modes, review_loops, qa_loops, auto_start, watcher_manager, merge propagation tracking, pane_idle_tracker), runs frame capture, runs background GitHub sync timer, manages SIGUSR1/SIGUSR2 reload + external command-queue IPC, manages pidfile lifecycle, decides between guide/normal/plans/QA views and orientation, and owns the WriteQueue for project.yaml mutations.*

- **STAYS**: `Textual widget composition (compose, CSS)` → `pm_core/tui/app.py`
    - *UI rendering stays per v2 plan.*
- **PARTIAL**: `BINDINGS table and keybinding actions` → `pm_core/tui/app.py` (non-PR-action bindings only) + `pm_core/tui/pr_actions/` (PR-action bindings)
    - *Resolves the audit's `tui-bindings-consolidate` contradiction (consolidation round). PR-action bindings — `s`/`d`/`t`/`o`/`g`/`Y` (start, review, qa, signoff, merge, cleanup) — DELETE from the inline `BINDINGS` tuple and re-emerge from `PRActionTUIType.__subclasses__()` at app init. Non-PR-action bindings — `q` (toggle_qa), `p` (toggle_plans), `?` (show_help), `c` (launch_claude), `f` (cycle_filter), `b` (rebalance), `ctrl+r` (restart), `w` (focus_watcher), `/` (focus_command), and the z/zz/y chord modifiers — STAY as inline `Binding(...)` entries in `app.py`; they have no PRActionStream sibling and the consolidation explicitly does not promote them. `app.py` constructs its final `BINDINGS` tuple at startup by concatenating the static non-PR list with the dynamic `[t.keybinding for t in PRActionTUIType.__subclasses__()]`. The completeness check from `tui/pr_actions/_registry.py` then asserts every PRActionStream has its binding present.*
    - *Keybindings stay; delegate targets change.*
- **STAYS**: `check_action gating (block actions in guide/plans/QA mode)` → `pm_core/tui/app.py`
- **STAYS**: `on_key handler + z/w/y vim-style prefix mode state` → `pm_core/tui/app.py`
    - *Pure TUI input concern.*
- **STAYS**: `Frame capture forwarder (_capture_frame)` → `pm_core/tui/frame_capture.py`
    - *frame_capture explicitly listed as STAYS in v2.*
- **STAYS**: `PR action delegates (start/review/merge/signoff/cleanup/etc.)` → `pm_core/tui/app.py`
    - *Methods stay; pr_view delegates rewired to PRStreamSupervisor + Mind.stream(role=ImplStream/MergeStream/SignoffStream).*
- **STAYS**: `Review loop action wiring (action_review_pr → review_loop_ui)` → `pm_core/tui/app.py`
    - *review_loop_ui becomes thin delegator to ReviewStream per v2.*
- **STAYS**: `QA loop action wiring (action_start_qa_on_pr → qa_loop_ui)` → `pm_core/tui/app.py`
    - *qa_loop_ui becomes thin delegator to Qa*Stream per v2.*
- **STAYS**: `Watcher chord handlers (_action_watcher_*, _action_focus_watcher)` → `pm_core/tui/app.py`
    - *Call sites rewire from WatcherManager to WatcherSupervisor (supervisors/watcher.py).*
- **STAYS**: `Auto-start toggle / auto-sequence actions` → `pm_core/tui/app.py`
    - *Delegates to watchers/auto_start.py per v2; tui/auto_start.py becomes thin delegator.*
- **DELETES**: `WatcherManager instantiation (_watcher_manager)`
    - *WatcherManager deleted per v2 ('watcher_base.py + watcher_manager.py rewritten as Stream base + WatcherSupervisor'); replaced by Mind.supervisor('watcher').*
- **DELETES**: `PaneIdleTracker instantiation + _impl_poll_counter`
    - *pane_idle.py deleted per v2 ('runtime-internal detail moves into TmuxHostRuntime'). Idle detection becomes a runtime capability.*
- **DELETES**: `runtime_state.sweep_stale_states call on mount`
    - *runtime_state.py deleted per v2; folds into EmissionLog + lifecycle.py. Stale-state sweep becomes Mind/Supervisor startup concern.*
- **DELETES**: `_review_loops dict + _review_loop_timer`
    - *Replaced by Mind.streams(role=ReviewStream) lookup; loop timer becomes ReviewStream/CallbackRegistry concern.*
- **DELETES**: `_qa_loops dict + _self_driving_qa pass counts`
    - *Replaced by Qa*Stream state + StreamPolicy.consecutive_pass_threshold (policy.py).*
- **MOVES**: `_stop_before_merge set` → `pm_core/mind/policy.py`
    - *Per v2 changes: StreamPolicy has stop_before_merge field.*
- **MOVES**: `_pending_merge_prs / _merge_input_required_prs / _merge_propagation_phase tracking` → `pm_core/streams/merge.py`
    - *Merge phase state belongs in MergeStream lifecycle + MergeConflictResolverStream.*
- **MOVES**: `action_review_spec (spec_gen.oldest_pending_spec_pr)` → `pm_core/sensorium/artifact/spec.py`
    - *spec_gen.py deleted; SpecArtifact + prompts/spec_gen.py replace it. Action stays in app.py but call site moves.*
- **MOVES**: `QA pane refresh (qa_instructions.list_all)` → `pm_core/sensorium/artifact/qa_library/instructions.py`
    - *qa_instructions.py deleted → QaLibraryArtifact subclasses. _refresh_qa_pane + _update_qa_status_bar call sites switch to QaLibraryArtifact.read().*
- **STAYS**: `Background GitHub sync timer (_background_sync, _do_normal_sync)` → `pm_core/tui/sync.py`
    - *sync delegated to tui/sync.py which stays.*
- **STAYS**: `SIGUSR1 reload + SIGUSR2 command-queue IPC (_install_reload_signal, _drain_command_queue, pidfile mgmt)` → `pm_core/tui/app.py`
    - *TUI-specific external IPC; not covered by v2 mailbox/attention substrate (those are intra-Mind). See MISSING_FROM_PLAN entry.*
- **MOVES**: `WriteQueue ownership for project.yaml mutations` → `pm_core/sensorium/artifact/project_yaml.py`
    - *ProjectYamlArtifact owns project.yaml writes per v2; debounced WriteQueue semantics fold into Artifact.apply + on_change mechanism.*
- **STAYS**: `_load_state / store.find_project_root / store.load` → `pm_core/tui/app.py`
    - *store.py stays; call site stays, possibly mediated by ProjectYamlArtifact.*
- **STAYS**: `Guide view detection + auto-launch (guide.detect_state, guide.needs_guide)` → `pm_core/tui/app.py`
    - *guide module not refactored in v2.*
- **STAYS**: `View switching (_show_guide_view/_show_normal_view/_show_plans_view/_show_qa_view)` → `pm_core/tui/app.py`
- **STAYS**: `Plans pane refresh + plan-action dispatch (on_plan_action, plan add screen)` → `pm_core/tui/app.py`
    - *PlanActionStream dispatch via pane_ops.handle_plan_action eventually routes through PlanStreamSupervisor.*
- **STAYS**: `Orientation switching (_update_orientation, on_resize, _recompute_tree_layout)` → `pm_core/tui/app.py`
- **STAYS**: `Status bar / log line / error display (_update_status_bar, log_message, log_error)` → `pm_core/tui/app.py`
- **STAYS**: `Restart with merge-restart-marker handling` → `pm_core/tui/app.py`
    - *auto_start breadcrumb mechanism stays via watchers/auto_start.py shim.*
- **MOVES**: `MergeLockScreen overlay on action_reload` → `pm_core/streams/merge.py`
    - *Merge-lock is a MergeStream-owned ResourceLease per v2 (sensorium/leases.py); overlay trigger remains in app.py but lock state queried from ResourceLease.*
- **STAYS**: `perf instrumentation (PM_PERF_DEBUG)` → `pm_core/tui/perf.py`
- **STAYS**: `Session name detection (tmux display-message)` → `pm_core/tui/app.py`
    - *tmux.py stays as foundational substrate.*
- **MOVES**: `Stale merge-lock cleanup on startup` → `pm_core/supervisors/pr_stream.py`
    - *Merge-lock lifecycle belongs to PRStreamSupervisor/MergeStream teardown.*

  *Not in plan:*
  - External-process command-queue IPC (SIGUSR2 + ~/.pm/tui-<session>.cmd-queue file with fcntl flock): Either keep as-is in app.py (TUI-process-local concern, not a Mind primitive), or formalize as a new pm_core/tui/external_command_queue.py and reference from a new sensorium primitive (e.g. sensorium/external_ipc.py for host-process file-based IPC). Lean toward: stays in app.py as the TUI's own concern; not Mind-substrate.
  - SIGUSR1 state-reload + pidfile lifecycle keyed by tmux session: Stays in app.py; could be split into pm_core/tui/external_reload.py for tidiness but not part of v2 substrate.
  - Frame-capture single-flight guard + worker thread offload (_capture_in_flight): Stays as-is.
  - _command_pending + _command_buffer race-condition buffer for keystrokes between / and command bar focus: Stays in app.py.

  *Cross-cutting:* Per v2 plan, pm_core/tui/ "most stays" with review_loop_ui/qa_loop_ui/watcher_ui/auto_start becoming thin delegators to Streams. So app.py's keybindings and action methods stay, but their delegate targets (review_loop_ui, qa_loop_ui, watcher_ui, auto_start) are being rewritten as Stream-backed shims. Concretely: action_review_pr's call into review_loop_ui must route to ReviewStream (streams/review.py) via Mind.stream(); action_start_qa_on_pr must route to QA*Stream; _action_watcher_* must route to WatcherSupervisor (supervisors/watcher.py); action_toggle_auto_start / action_auto_sequence_pr route through watchers/auto_start.py + WatcherSupervisor; action_signoff_pr / action_cleanup_pr / action_merge_pr eventually route through PRStreamSupervisor (supervisors/pr_stream.py). Imports that DIE and need replacement at call sites in this file: pm_core.runtime_state (sweep_stale_states — folded into EmissionLog+lifecycle.py), pm_core.pane_idle.PaneIdleTracker (runtime-internal in TmuxHostRuntime), pm_core.watcher_manager.WatcherManager (replaced by WatcherSupervisor), pm_core.spec_gen (replaced by SpecArtifact + prompts/spec_gen.py), pm_core.qa_instructions (replaced by QaLibraryArtifact). This file is a major consumer of the deleted modules, so its migration unblocks deletion of those modules. _stop_before_merge in-memory set should migrate to StreamPolicy.stop_before_merge (policy.py). _merge_propagation_phase and _merge_input_required_prs should fold into MergeStream lifecycle (streams/merge.py). review_loops / qa_loops dicts should be replaced by Mind.streams() lookup.

#### `pm_core/tui/pr_view.py`
*TUI module: key-handler functions (called by app.py) for PR workflow actions (start/review/signoff/merge/qa/cleanup), command-bar text dispatch (run_command + async spinner wrapping subprocess pm_core.wrapper invocation), tree filter/sort/hide-merged toggles, plan movement (PlanPickerScreen flow), action-guard (in-flight PR action mutex), and PR-selection persistence to project.yaml. Heavy ties to tech_tree.py state, store.locked_update, pr_cleanup, loop_shared.get_pm_session, review_loop_ui/qa_loop_ui/auto_start, and the wrapper subprocess pattern.*

- **STAYS**: `guard_pr_action (in-flight mutex)` → `pm_core/tui/pr_view.py`
    - *TUI-local UX guard; in v2 the underlying lease is owned by ChampionSlotKey/WorkdirKey in sensorium/leases.py, but the user-facing 'Busy: ...' toast stays TUI-side. Reimplement to query ResourceLease state instead of app._inflight_pr_action.*
- **STAYS**: `handle_pr_selected (persist active_pr)` → `pm_core/tui/pr_view.py`
    - *Write should route through ProjectYamlArtifact.propose_edit (sensorium/artifact/project_yaml.py) instead of store.locked_update + write_queue directly.*
- **MOVES**: `start_pr / review_pr / signoff_pr / merge_pr` → `pm_core/tui/pr_view.py`
    - *Function names stay in TUI as keybinding entry points (thin delegators per 'TUI integration shim pattern'), but bodies move to Mind.stream(role=ImplStream|ReviewStream|SignoffStream|MergeStream, instance_key=pr_id, ...). The actual stream classes live in pm_core/streams/{impl,review,signoff,merge}.py.*
- **STAYS**: `hide_plan / toggle_merged / cycle_sort / cycle_filter (tree view state)` → `pm_core/tui/pr_view.py`
    - *Pure TUI view-state mutations on TechTree. toggle_merged persists hide_merged via ProjectYamlArtifact.propose_edit in v2.*
- **STAYS**: `move_to_plan / handle_plan_pick (PR<->plan reassignment)` → `pm_core/tui/pr_view.py`
    - *TUI flow stays; the locked_update bodies should call ProjectYamlArtifact.propose_edit (sensorium/artifact/project_yaml.py) and PlanArtifact creation (sensorium/artifact/plan.py) instead of store.locked_update + writing plan file directly.*
- **MOVES**: `_do_cleanup / _cleanup_worker / cleanup_pr / cleanup_then_action` → `pm_core/supervisors/pr_stream.py`
    - *pr_cleanup.py is deleted; cleanup logic fans out into PRStreamSupervisor teardown + runtime cleanup hooks + ResourceLease release. The TUI keybinding entry (cleanup_pr) stays but delegates to supervisor.teardown(pr_id). loop_shared.get_pm_session() goes away (loop_shared is deleted); replaced by CallbackRegistry.*
- **STAYS**: `handle_command_submitted (command bar dispatch)` → `pm_core/tui/pr_view.py`
    - *Stays as command-bar dispatcher but each branch (review-loop, edit, autostart, pr qa, pr start/review/merge, plan add) becomes a call into Mind.stream(...) instead of run_command subprocess. The auto-start branch delegates to streams/watchers/auto_start.py.*
- **DELETES**: `run_command / _run_command_sync / _run_command_async (subprocess pm_core.wrapper spawn + spinner)`
    - *Spawning `python -m pm_core.wrapper <subcommand>` from the TUI to execute pm CLI commands becomes obsolete: in v2 the TUI is in-process with Mind and invokes streams/supervisors directly. The spinner UX (working_message animation) is still useful and should be lifted to a small generic helper in pm_core/tui/_shell.py or pm_core/tui/spinner.py (already exists as _shell helpers).*
- **DELETES**: `PR_ACTION_PREFIXES constant`
    - *Tied to the subprocess-string command surface; with in-process Stream dispatch the prefix set is encoded as command-bar grammar branches.*

  *Not in plan:*
  - Spinner UX during long-running command-bar actions (update_spinner / itertools.cycle frames): Keep a small TUI-only spinner helper (pm_core/tui/spinner.py or fold into _shell.py). Not a refactor concern — purely cosmetic.
  - Command-bar grammar (review-loop, edit, autostart, pr qa fresh/loop, plan add): Document explicitly that pm_core/tui/pr_view.py remains the command-bar grammar dispatcher and that each branch maps to a Mind.stream(...) call. Possibly mention in plan-mind's 'TUI integration shim pattern' section.
  - app._inflight_pr_action / app._write_queue (app-level state that this file mutates): Spec that ProjectYamlArtifact.propose_edit subsumes the write-coalescing queue (debounced batch writes inside the Artifact). The _inflight_pr_action mutex becomes a query on the relevant ChampionSlotKey lease via sensorium/leases.py.

  *Cross-cutting:* Imports that block migration of other files: imports pm_core.pr_cleanup (deleted — must migrate to PRStreamSupervisor first), pm_core.loop_shared.get_pm_session (deleted — must migrate to CallbackRegistry), pm_core.tui.auto_start (becomes thin delegator to streams/watchers/auto_start.py), pm_core.tui.review_loop_ui (thin delegator to ReviewStream), pm_core.tui.qa_loop_ui (thin delegator to Qa*Streams). The `_run_command_*` functions exec `python -m pm_core.wrapper` (now bootstrap.py) — once TUI is in-process with Mind, these subprocess calls disappear, breaking the only remaining caller of the wrapper-as-CLI-entry pattern from the TUI. tech_tree.py is read/written extensively (tree._hidden_plans, _hide_merged, _sort_field, _status_filter, selected_pr_id) — pr_view's migration is coupled to tech_tree's view-state representation; tech_tree.py is listed as STAYS so this is fine.

#### `pm_core/tui/qa_pane.py`
*Textual Widget rendering a 3-section scrollable list (QA Instructions / Regression Tests / Artifact Recipes) with keyboard navigation (j/k/up/down/enter) and action shortcuts (a=add, e=edit, d=debug). Emits QAItemSelected, QAItemActivated, and QAAction messages consumed by the parent TUI app. Pure UI; reads no data itself — data is pushed via update_items().*

- **STAYS**: `QAPane Widget (rendering + key handling)`
    - *Pure Textual UI widget; v2 keeps pm_core/tui/ (most) intact. No primitive moves required.*
- **STAYS**: `QAItemSelected / QAItemActivated messages (via item_message factory)`
    - *TUI-internal message types; stay with the widget.*
- **STAYS**: `QAAction message (a=add, e=edit, d=debug shortcuts)`
    - *TUI-internal message; consumed by app.py-level handlers.*
- **STAYS**: `update_items(all_items) data ingestion`
    - *Call-site update only: caller will now read from QaLibraryArtifact subclasses (sensorium/artifact/qa_library/{instructions,mocks,regression,artifacts}.py) instead of pm/qa/* directly. The widget signature itself is unchanged.*
- **STAYS**: `Scroll-into-view geometry helper (_scroll_selected_into_view, _entry_lines)`
    - *Pure UI math.*
- **STAYS**: `Truncation helper (_truncate)`

  *Not in plan:*
  - QAAction(action='debug') handler semantics: Either (a) clarify in plan-mind that 'debug' maps to an existing QaVerificationStream/QaScenarioStream invocation, or (b) document as an app.py-level call-site concern (launches an ad-hoc QA shell pane) — likely the latter; no new file needed.

  *Cross-cutting:* Depends on pm_core.tui.item_message factory (stays). The caller (likely app.py) currently reads pm/qa/{instructions,regression,artifacts}/ directly via qa_instructions.py — once qa_instructions.py is replaced by QaLibraryArtifact subclasses under sensorium/artifact/qa_library/, this widget's call-site (the dict it receives) will be assembled from those Artifacts. Widget itself is unblocked. The QAAction(action='debug') variant is referenced here but not in the plan summary — the app-level handler for it must continue to exist (likely launches a debugger Stream, but no stream role is named for it in v2).

#### `pm_core/tui/tech_tree.py`
*Textual Widget rendering a PR dependency graph (tech tree) for the TUI. Contains: EdgeCanvas (drawing routed edges between PR nodes), PRNode (per-PR widget with status/loop indicators), PlanLabel + PlanGroup (plan-band grouping/labels), TechTree (top-level widget: layout/recompute, viewport culling, plan-band navigation, key handling, scroll-into-view, active-PR animation). Helpers include qa_pane_state(), compute_neighbors(), and grid-to-text rendering. Pure UI rendering layer over the dependency graph + PR status data.*

- **STAYS**: `EdgeCanvas widget (routed edge rendering)`
    - *Pure UI; v2 'Stays' list explicitly keeps pm_core/tui/ rendering.*
- **STAYS**: `PRNode widget (status glyphs, loop markers)`
    - *May need call-site updates: loop/QA/review status now sourced from LifecycleState + Stream.status (lifecycle.py) and watchdog/tui.py rather than runtime_state/qa_status.*
- **DELETES**: `STATUS_ICONS (L27-36)`, `STATUS_STYLES (L86-95)`, `STATUS_BG (L98-107)`, `STATUS_FILTER_CYCLE (L110)` — four parallel dicts collapse into reads from `PR_STATUS_DISPLAY` + `STATUS_FILTER_CYCLE` on `pm_core/mind/lifecycle.py`. Renaming/adding a PRStatus member now updates one table instead of four.
- **STAYS**: `PlanLabel + PlanGroup widgets (plan-band grouping/labels)`
- **STAYS**: `TechTree widget (layout, recompute, signatures, culling, key handling, plan navigation, scroll-into-view)`
    - *Core UI widget; v2 keeps pm_core/tui/ mostly intact.*
- **STAYS**: `qa_pane_state(tracker, pr_id) helper`
    - *Currently reads from qa tracker; will need to read from watchdog/tui.py state surface once qa_status.py is deleted. Minor call-site update.*
- **STAYS**: `compute_neighbors() graph adjacency helper`
    - *Pure graph utility over PR list; complements pm_core/graph.py which stays.*
- **STAYS**: `_grid_to_text() rendering helper`
- **STAYS**: `Active-PR animation / refresh_active_nodes`
    - *Driven by 'is this PR active' which under v2 maps to Stream.status==RUNNING for the PR's streams via PRStreamSupervisor; minor data-source change.*
- **STAYS**: `Auto-start signature tracking (_auto_start_sig)`
    - *Will sample from WatcherSupervisor / auto_start watcher Stream state instead of current watcher_manager; minor adapter change.*

  *Cross-cutting:* tech_tree.py consumes: (a) PR status / loop state currently from runtime_state.py + qa_status.py + watcher_manager.py — all three are DELETED in v2. Migration of tech_tree is blocked until shim adapters exist for: LifecycleState/Stream.status (lifecycle.py), watchdog/tui.py QA state surface, and WatcherSupervisor auto-start state. The widget itself stays, but its data-fetching helpers (qa_pane_state, _auto_start_sig, _is_active_pr) need rewiring. Also consumes pm_core/graph.py (stays) and PR dicts from store.py (stays / now via ProjectYamlArtifact). No outbound dependencies that block other files.</cross_cutting_notes> <parameter name="not_in_plan">[]

### MIXED (11)

#### `pm_core/cli/cluster.py`
*Click CLI group `pm cluster` with two subcommands: `auto` (runs the clustering pipeline from pm_core/cluster, writes text/json/plan output, optionally creating a plan file + entry in project.yaml) and `explore` (runs clustering, writes summary to a temp file, builds a prompt, and launches Claude via claude_launcher.launch_claude or launch_bridge_in_tmux). Shared helper `_run_clustering` orchestrates extract_chunks → pre_partition → compute_edges → agglomerative_cluster.*

- **STAYS**: `pm cluster CLI group registration`
    - *pm_core/cli/ is listed as stays in v2; the CLI surface remains here as Click commands.*
- **STAYS**: ``pm cluster auto` subcommand (run pipeline, emit text/json/plan)`
    - *Stays in pm_core/cli/cluster.py; underlying pm_core/cluster/ also stays per v2.*
- **STAYS**: `_run_clustering helper (extract → partition → edges → agglomerative)`
    - *Thin orchestration over pm_core/cluster which v2 marks as Stays.*
- **STAYS**: `Plan file generation + project.yaml plans[] append (cluster-explore plan)`
    - *Uses store.locked_update + trigger_tui_refresh; both substrate (store.py) and CLI stay. Eventually could be re-encoded via ProjectYamlArtifact/PlanArtifact apply, but v2 keeps the CLI path.*
- **MOVES**: ``pm cluster explore` subcommand — launch Claude with cluster summary prompt` → `pm_core/streams/cluster_exploration.py`
    - *v2 explicitly lists `cluster_exploration.py` under streams/. The interactive explore-with-Claude behavior is the canonical cluster-exploration Stream. CLI command would remain as a thin shim that creates the ClusterExplorationStream via Mind.*
- **MOVES**: `Cluster-explore prompt construction (goal + tmp file + tui_section)` → `pm_core/streams/_shared_prompts.py`
    - *The prompt body is an InputType for ClusterExplorationStream; tui_section becomes _shared.tui_section per v2. Currently imports from pm_core.prompt_gen which v2 deletes (prompt_gen.py is in the Deleted list).*
- **DELETES**: `Bridged launch path (launch_bridge_in_tmux + socket wait)`
    - *bridge.py / bridge_client.py are deleted in v2; replaced by RawApiRuntime + Mailbox + AttentionRequest. The --bridged flag's mechanism is re-encoded as a runtime choice on the ClusterExplorationStream (e.g., RawApiRuntime instead of TmuxHostRuntime). The CLI flag may stay but its implementation becomes runtime selection.*
- **MOVES**: `Direct launch path (find_claude + launch_claude + clear_session)` → `pm_core/runtime/tmux_host.py`
    - *claude_launcher.py stays per v2 and is consumed by TmuxHostRuntime; the explore command should request a Stream which uses TmuxHostRuntime instead of calling launch_claude directly.*
- **MOVES**: `session_key / fresh-session semantics (`cluster:explore`)` → `pm_core/streams/cluster_exploration.py`
    - *Becomes a Stream instance_key under Mind.stream(role=ClusterExplorationStream, instance_key='explore'); LoopMode handles fresh vs resume.*
- **STAYS**: `_get_pm_session / state_root / _resolve_repo_dir helpers`
    - *CLI helpers remain in pm_core/cli/helpers.py.*

  *Not in plan:*
  - Two-flavor Claude launch (tmux-pane vs bridge-socket) selected by --bridged flag from a CLI command: Add a convention (likely in pm_core/streams/base.py or Mind.stream docs) for CLI-driven runtime selection, or document on streams/cluster_exploration.py that callers pass runtime= explicitly.
  - Writing a cluster summary to a tempfile and passing the path into the prompt: Either keep as-is inside the cluster_exploration Stream's input preparation, or model as a CaptureBundle in sensorium/captures.py if the pattern recurs.

  *Cross-cutting:* Imports `pm_core.prompt_gen.tui_section` — prompt_gen.py is in v2 Deleted list, so this import must migrate to `pm_core/prompts/_shared.py::tui_section` before/with prompt_gen removal. Imports `pm_core.claude_launcher.launch_claude / launch_bridge_in_tmux / clear_session / find_claude`: claude_launcher.py stays but `launch_bridge_in_tmux` belongs to the bridge.py world that is deleted — confirm whether launch_bridge_in_tmux survives or is replaced by RawApiRuntime. `pm_core.cluster` package stays (explicitly in Stays list), so the pipeline helper is safe. Plan-creation path (store.locked_update + generate_plan_id + make_plan_entry) couples CLI to store.py; if PlanArtifact/ProjectYamlArtifact eventually own writes, this call site updates but file stays.

#### `pm_core/cli/container.py`
*Click CLI command group `pm container` exposing user-facing commands to configure and operate container isolation: status, enable, disable, set, build-base, build (launches a Claude session via tmux to author Dockerfile.pm-project), and cleanup. Delegates to pm_core/container.py (which v2 absorbs into TmuxContainerRuntime) and to claude_launcher/tmux for the `build` subcommand. Also contains an inline _build_container_build_prompt helper string.*

- **STAYS**: `container_group (pm container CLI group)` → `pm_core/cli/container.py`
    - *v2 'Stays' list explicitly keeps pm_core/cli/ surface; commands re-target to the runtime layer rather than pm_core/container.py*
- **STAYS**: `container status command` → `pm_core/cli/container.py`
    - *Call sites change: query TmuxContainerRuntime capability/config from pm_core/runtime/tmux_container.py instead of pm_core.container*
- **STAYS**: `container enable/disable commands` → `pm_core/cli/container.py`
    - *Still writes global settings via pm_core/paths.py. Runtime availability check delegates to pm_core/runtime/tmux_container.py*
- **STAYS**: `container set command (image/memory/cpu/runtime)` → `pm_core/cli/container.py`
    - *Configuration values now consumed by TmuxContainerRuntime*
- **MOVES**: `container build-base command (build pm-dev:latest base image)` → `pm_core/runtime/tmux_container.py`
    - *build_image absorbed into TmuxContainerRuntime; CLI wrapper stays as thin entrypoint that delegates*
- **MOVES**: `container build command (launches Claude session to author Dockerfile.pm-project)` → `pm_core/streams/container_build.py`
    - *v2 lists streams/container_build.py — this command becomes Mind.stream(role=ContainerBuildStream, ...). CLI wrapper in cli/container.py stays as thin entrypoint.*
- **MISSING_FROM_PLAN**: `_build_container_build_prompt (system prompt template for container-build session)` → `pm_core/streams/container_build.py`
    - *v2 prompts/ enumeration omits a container_build.py module despite streams/container_build.py existing; every other Stream pairs with a prompts/ file*
- **MOVES**: `container cleanup command (remove stale pm containers; --pr filter)` → `pm_core/runtime/tmux_container.py`
    - *Container lifecycle/teardown is a TmuxContainerRuntime concern; pm_core/container.py is deleted in v2 and pr_cleanup.py fans out into Supervisor teardown + runtime cleanup hooks. CLI wrapper stays.*
- **MOVES**: `Imports from pm_core/container.py (is_container_mode_enabled, load_container_config, _runtime_available, _get_runtime, build_image, DEFAULT_IMAGE, _run_runtime, remove_container, CONTAINER_PREFIX)` → `pm_core/runtime/tmux_container.py`
    - *v2 explicitly deletes pm_core/container.py — all these symbols migrate to TmuxContainerRuntime. cli/container.py needs updated import surface.*
- **MOVES**: `Direct tmux window launching for container-build session` → `pm_core/streams/container_build.py`
    - *tmux_mod calls + claude_launcher.build_claude_shell_cmd / launch_claude become Stream instantiation; window-role dedup handled by stream's tui_window_role*

  *Not in plan:*
  - Prompt template for the container-build Claude session (_build_container_build_prompt): Add pm_core/prompts/container_build.py (typed InputType holding project_name/project_dir/base_image/image_tag/runtime) paired with streams/container_build.py.
  - Persisted container config schema (ContainerConfig dataclass + load/save against global settings): Co-locate ContainerConfig + load/save inside pm_core/runtime/tmux_container.py. If it grows, extract pm_core/runtime/tmux_container_config.py. No new plan needed.
  - Ad-hoc `pm container cleanup --pr` enumerating/removing orphan containers independent of Supervisor lifecycle: Expose as TmuxContainerRuntime.cleanup_stale(pr_filter=...) classmethod in pm_core/runtime/tmux_container.py; cli/container.py delegates to it.

  *Cross-cutting:* cli/container.py blocks deletion of pm_core/container.py: every import in this file targets pm_core.container, so the symbols (is_container_mode_enabled, load_container_config, _runtime_available, _get_runtime, build_image, DEFAULT_IMAGE, _run_runtime, remove_container, CONTAINER_PREFIX) must be re-exposed by pm_core/runtime/tmux_container.py before this file can migrate. Also imports pm_core/claude_launcher (stays), pm_core/tmux (stays), pm_core/store (stays), pm_core/paths (stays), and pm_core/cli/helpers (_get_pm_session, state_root). The `container build` command's tmux window-launching pattern duplicates infrastructure that will be standardized by Stream/runtime — migration of this command should happen alongside introduction of streams/container_build.py.

#### `pm_core/cli/guide.py`
*Registers two Click CLI commands: `pm guide` (detects project state, runs non-interactive setup steps, then dispatches to either an "assist" or "setup" Claude session — with tmux-aware resume/save session handling and fresh-start support) and `pm notes` (opens a multi-section notes editor with a welcome splash screen and per-repo splash disable marker).*

- **STAYS**: `pm guide CLI command registration` → `pm_core/cli/guide.py`
    - *v2 keeps pm_core/cli/ as the CLI command surface; the Click registration remains, but the body becomes a thin delegator that spawns a guide Stream via Mind.*
- **MOVES**: `guide state detection + non-interactive step loop` → `pm_core/streams/guide/setup.py`
    - *guide_mod.detect_state + run_non_interactive_step loop becomes part of GuideSetupStream's startup logic (with corresponding GuideAssistStream branch).*
- **MOVES**: `assist-mode prompt construction + launch` → `pm_core/streams/guide/assist.py`
    - *build_assist_prompt becomes the InputType for GuideAssistStream (pm_core/prompts/guide/assist.py); launch becomes Mind.stream(role=GuideAssistStream, runtime=TmuxHostRuntime).*
- **MOVES**: `setup-mode prompt construction + launch (with session save/resume)` → `pm_core/streams/guide/setup.py`
    - *build_setup_prompt → pm_core/prompts/guide/setup.py InputType; load_session/save_session/clear_session resume semantics are absorbed by Stream lifecycle + CallbackRegistry / TmuxHostRuntime session handling.*
- **MOVES**: `tmux-aware exec branching (_in_pm_tmux_session + os.execvp vs launch_claude)` → `pm_core/runtime/tmux_host.py`
    - *Tmux detection + in-pane vs new-pane launch is a runtime concern owned by TmuxHostRuntime; the CLI no longer chooses between os.execvp and launch_claude.*
- **STAYS**: `Claude-CLI-missing fallback (echo prompt to stdout)` → `pm_core/cli/guide.py`
    - *Falls naturally out of RuntimePlugin capability check (no interactive_tty / find_claude None) — but the user-facing echo remains a CLI-layer concern.*
- **STAYS**: `pm notes CLI command registration` → `pm_core/cli/guide.py`
    - *Click command stays; body delegates to NotesSectionArtifact.edit_interactively().*
- **MOVES**: `notes file ensure + section template build/parse + save` → `pm_core/sensorium/artifact/notes.py`
    - *build_edit_template/parse_edit_template/save_sections/ensure_notes_file become NotesSectionArtifact methods (read, propose_edit, apply); the on_save callback collapses into Artifact.apply.*
- **MOVES**: `watched-editor invocation (run_watched_editor + on_save callback)` → `pm_core/sensorium/artifact/base.py`
    - *Becomes Artifact.edit_interactively + watch_for_save on the base — explicitly listed in v2 'Added' changes; pm_core/editor.py is deleted.*
- **MISSING_FROM_PLAN**: `welcome splash screen (NOTES_WELCOME echo + raw-mode keypress wait)`
    - *First-run UX splash with single-keypress dismiss and per-repo .no-notes-splash opt-out marker has no clear home in v2. Could be a NotesSectionArtifact pre-edit hook, but the splash + persistent dismiss-marker pattern is unspecified.*
- **MISSING_FROM_PLAN**: `--disable-splash flag + .no-notes-splash marker file`
    - *Per-repo dismissal state for the splash has no defined home. Recommend either storing under sensorium HostCodeOverride-style per-repo preferences, or simply keeping the marker check in the CLI command itself.*

  *Not in plan:*
  - Welcome splash screen + dismissable per-repo marker for pm notes: Either (a) keep the splash + .no-notes-splash check inline in pm_core/cli/guide.py (CLI-layer UX concern, harmless to stay), or (b) add a small 'first-run hint' hook to Artifact.edit_interactively in pm_core/sensorium/artifact/base.py that accepts a (splash_text, dismiss_marker_path) pair.
  - Session save/resume keyed by 'guide:setup' with crash-on-failure clear semantics: Add explicit guidance in pm_core/runtime/tmux_host.py or pm_core/streams/base.py for how Claude-CLI --resume session IDs are persisted per (root, stream-role, instance_key) and cleared on abnormal exit.

  *Cross-cutting:* Depends on pm_core.guide module (detect_state, run_non_interactive_step, build_assist_prompt, build_setup_prompt) — that module is not itemized in v2 and presumably MOVES with this file into pm_core/streams/guide/ + pm_core/prompts/guide/. Depends on claude_launcher (stays), tmux (stays), notes (consumed by NotesSectionArtifact), editor (deleted — folds into Artifact base). Migration of this file is blocked until (a) GuideSetupStream / GuideAssistStream exist, (b) NotesSectionArtifact.edit_interactively is implemented, and (c) TmuxHostRuntime owns the in-pane vs new-pane launch decision.

#### `pm_core/cli/helpers.py`
*Shared CLI helpers: terminal-width-aware record wrapping, HelpGroup Click subclass, project-root resolution, PR/plan resolution + display formatting, PR entry construction + status-timestamp recording, tmux PR-window kill, TUI reload/command/restart/merge-lock signaling, workdir provisioning (clone+lock), session-name resolution, TUI pane finder. Largely stays as CLI surface, but several pieces map to v2 sensorium/streams/runtime concepts.*

- **STAYS**: `_cell_aware_fill / _wrap_record_to_width / echo_record / emit_paged`
    - *Pure CLI presentation. Stays under pm_core/cli/ (helpers.py or split into a cli/output.py); no v2 home needed.*
- **STAYS**: `HelpGroup + CONTEXT_SETTINGS`
    - *Click integration; lives in cli/. Not relevant to v2 substrate.*
- **STAYS**: `_project_override / set_project_override / state_root / _normalize_repo_url / _verify_pm_repo_matches_cwd`
    - *CLI bootstrap-ish; project root resolution stays via store.find_project_root. Note pm_core/bootstrap.py handles the wrapper-level pm_root walk but this is the cli-time override.*
- **STAYS**: `_pr_id_sort_key / _pr_display_id / format_pr_line`
    - *Display layer for PRs. Now consumes `PRStatus` + `PR_STATUS_DISPLAY` from `pm_core/mind/lifecycle.py` for icons/styles/priority.*
- **DELETES**: `PR_STATUS_ICONS` (lines 262-271) — replaced by reads from `PR_STATUS_DISPLAY[status].emoji` on `pm_core/mind/lifecycle.py`. The `blocked` entry it uniquely had becomes a first-class `PRStatus.blocked` enum member.
- **MOVES**: `kill_pr_windows` → `pm_core/runtime/tmux_host.py`
    - *Tmux PR window teardown — currently fans out across home_window park + tmux kill. v2 says pr_cleanup.py 'fans out across Supervisor teardown + runtime cleanup hooks'. The actual tmux kill belongs in TmuxHostRuntime cleanup; Supervisor in pm_core/supervisors/pr_stream.py invokes it. The hardcoded prefix list at L326-327 (`"signoff-"`, `"review-"`, `"merge-"`, `"qa-"`) DELETES; the rewritten function enumerates `PRActionTUIType.__subclasses__()` and reads each `window_role`, so adding a new PR-action role doesn't require touching this function.*
- **STAYS**: `_resolve_pr_id / _require_pr / _require_plan / _auto_select_plan`
    - *CLI argument resolution; consumes store. Stays under cli/.*
- **STAYS**: `_make_pr_entry`
    - *Constructs PR dict for project.yaml. Will consume PRStatus from pm_core/agent/lifecycle.py but creation logic stays at cli/ + store layer (eventually via ProjectYamlArtifact).*
- **MOVES**: `_record_status_timestamp` → `pm_core/sensorium/artifact/project_yaml.py`
    - *PR lifecycle-state timestamp side-effects belong with ProjectYamlArtifact mutation semantics in v2 (or in pm_core/supervisors/pr_stream.py when transitioning states). Currently CLI-side; in v2 the lifecycle transitions are driven by Stream/Supervisor and the artifact apply() records timestamps.*
- **STAYS**: `_canonical_session / _tui_pidfile_for_session / _tui_command_queue_for_session`
    - *tmux/TUI plumbing — paths/conventions. Could move to pm_core/tui/ but v2 lists tui as 'most stays'. Keep here or under cli/.*
- **STAYS** (revised per "locking story" consolidation): `trigger_tui_reload / trigger_tui_refresh / trigger_tui_command / trigger_tui_restart` STAY as cross-process IPC signal files in `cli/helpers.py`. Earlier wording routed these to `sensorium/artifact/base.py`'s on_change subscribers — but those triggers aren't Artifact mutations; they're runtime IPC between external pm CLI invocations and the in-process TUI subprocess (neither side is a stream). Per the mind/runtime boundary principle, runtime-internal IPC stays as plumbing. The pidfile/SIGUSR2 command-queue file machinery remains as today.
- **MOVES**: `trigger_tui_merge_lock / trigger_tui_merge_unlock (specifically)` → `pm_core/sensorium/leases.py`
    - *The merge lock IS a coordinated pm resource (a per-PR mutex preventing concurrent merges) — that fits `ResourceLease` with a `BranchRefKey` or per-PR `MergeSlotKey`. This one graduates; the other triggers don't.*
- **STAYS**: `_resolve_repo_dir / _gh_state_to_status`
    - *_resolve_repo_dir stays at cli/ helper level. _gh_state_to_status arguably moves to pm_core/pr_sync.py (stays per v2) — minor.*
- **MOVES**: `_workdirs_dir / _ensure_workdir / _clone_workdir / _resolve_repo_id` → `pm_core/sensorium/workdirs.py`
    - *v2 'Added: WorkdirRegistry+Workdir' — these workdir provisioning + per-PR lock + clone-and-checkout primitives are exactly the WorkdirRegistry/Workdir surface. The per-PR file-lock semantics belong on Workdir.ensure(). repo_id caching on project.yaml moves with it (or to ProjectYamlArtifact).*
- **STAYS**: `_infer_pr_id`
    - *CLI-side cwd/active-pr inference. Stays at cli/. Could consume Workdir registry once that exists.*
- **STAYS**: `_set_share_mode_env / _get_session_name_for_cwd / _get_current_pm_session / _get_pm_session`
    - *tmux session-naming convention. v2 lists pm_core/tmux.py as foundational substrate that stays; these session-tag helpers belong alongside it or stay at cli/. Could move to pm_core/tmux.py.*
- **MOVES**: `_find_tui_pane` → `pm_core/tui/pane_registry.py`
    - *Searches pane_registry for the TUI pane. v2 keeps pane_registry as foundational substrate; this finder logically belongs there (or on TmuxHostRuntime). Currently in helpers for circularity reasons.*

  *Not in plan:*
  - PM-repo-vs-cwd-repo mismatch warning (_verify_pm_repo_matches_cwd + _normalize_repo_url): Stays at cli/helpers.py (or new cli/safety.py). Safe to keep as-is; not a refactor target.
  - TUI command queue file + SIGUSR2 IPC (trigger_tui_command): Either (a) keep as a TUI-internal IPC primitive under pm_core/tui/, or (b) reframe as a Mailbox subscription on a TUI-local Channel (pm_core/agent/channels.py — a new TUICommandChannel). Recommend adding TUICommandChannel to channels.py so cross-process command submission rides on the unified Mailbox/Emission substrate.
  - Workdir per-PR fcntl provisioning lock: Document Workdir.ensure() as an explicit guarantee in pm_core/sensorium/workdirs.py: serialized via per-PR exclusive lock with double-checked load. This should be called out in plan-sensorium for the Workdir API.
  - configure_dual_remote + repo_id resolution side effect on project.yaml during clone: Move to ProjectYamlArtifact.ensure_repo_id() or Workdir.ensure() side-effect. Add as a ProjectYamlArtifact method in pm_core/sensorium/artifact/project_yaml.py.

  *Cross-cutting:* helpers.py is imported by nearly every cli/*.py submodule, so its migration is high-leverage: kill_pr_windows callers (pr_cleanup, signoff, merge commands) must rewire to Supervisor teardown; trigger_tui_* callers (every command that mutates project.yaml — edit, status, signoff, etc.) must rewire to Artifact.on_change once that lands. The workdir helpers are imported by pr_signoff, pr_start, qa flows and gate the WorkdirRegistry migration. pane_registry import here means cli/helpers carries a dependency on tui/ — moving _find_tui_pane to pane_registry resolves that circularity. _record_status_timestamp is invoked anywhere PR.status mutates; moving it to ProjectYamlArtifact.apply() means all 'set status' call sites become artifact.propose_edit instead of dict-mutation + save.

#### `pm_core/cli/plan.py`
*Registers the `pm plan` Click group with subcommands: add, list, breakdown, review, deps, load, fixes, fix, import. Each "agentic" subcommand (add, breakdown, review, deps, fix, import) builds a large prompt string, calls find_claude/launch_claude to start a Claude session keyed by plan id, then kicks off a background review via plans.review module. Non-agentic subcommands (list, load, fixes) read/write project.yaml directly via store: load parses the plan markdown's PRs section and creates PR entries; list/fixes just emit summaries. Helpers: _build_pr_description (compose PR description from plan fields), _import_github_prs (during init, pulls open GH PRs into yaml), _run_plan_import / _run_fix_command (shared helpers).*

- **STAYS**: `plan group registration (Click @cli.group)` → `pm_core/cli/plan.py`
    - *pm_core/cli/ stays per v2; CLI surface remains. Subcommand bodies delegate to Streams/Supervisors.*
- **MOVES**: `plan_add — builds prompt + launches Claude + background review` → `pm_core/streams/plan/add.py`
    - *Becomes PlanAddStream; prompt body moves to pm_core/prompts/plan/add.py. CLI handler shrinks to mind.stream(role=PlanAddStream, ...) invocation.*
- **MOVES**: `plan_breakdown — prompt + Claude launch + background review` → `pm_core/streams/plan/breakdown.py`
    - *Prompt body moves to pm_core/prompts/plan/breakdown.py.*
- **MOVES**: `plan_review — prompt + Claude launch` → `pm_core/streams/plan/review.py`
    - *Prompt body moves to pm_core/prompts/plan/review.py.*
- **MOVES**: `plan_deps — prompt + Claude launch + background review` → `pm_core/streams/plan/deps.py`
    - *Prompt body moves to pm_core/prompts/plan/deps.py.*
- **MOVES**: `plan_fix + _run_fix_command — build fix prompt from review file, launch Claude` → `pm_core/streams/plan/fix.py`
    - *Prompt scaffolding moves to pm_core/prompts/plan/fix.py.*
- **MOVES**: `plan_import + _run_plan_import — full import flow with Claude` → `pm_core/streams/plan/import_.py`
    - *Prompt body to pm_core/prompts/plan/import_.py.*
- **STAYS**: `plan_list — read plans from project.yaml and emit` → `pm_core/cli/plan.py`
    - *Pure read; reads via store (which still exists) and ProjectYamlArtifact in v2. CLI handler stays.*
- **STAYS**: `plan_load — parse PRs section, create PR entries in yaml` → `pm_core/cli/plan.py`
    - *Non-agentic; uses store + parse_plan_prs (both stay). May read via PlanArtifact / write via ProjectYamlArtifact in v2 but stays in CLI.*
- **STAYS**: `plan_fixes — list pending reviews` → `pm_core/cli/plan.py`
    - *Delegates to plans.review module; CLI surface stays.*
- **STAYS**: `_build_pr_description helper` → `pm_core/cli/plan.py`
    - *Or moves with plan_load if extracted; trivial pure helper.*
- **STAYS**: `_import_github_prs helper (used by init)` → `pm_core/cli/plan.py`
    - *Pure gh_ops + store glue used by `pm init`; gh_ops + store both stay per v2. Could also live in pm_core/cli/init.py since only init imports it.*
- **MOVES**: `_MANUAL_TESTING_GUIDANCE shared prompt fragment` → `pm_core/streams/_shared_prompts.py`
    - *v2 explicitly lists prompts/_shared.py for cross-prompt fragments.*
- **MOVES**: `_PROMPT_ARG_LIMIT (E2BIG safety constant for execve argv)` → `pm_core/runtime/tmux_host.py`
    - *argv-size limit is a TmuxHostRuntime concern (Claude CLI invocation). Could also belong in claude_launcher.py which stays. Currently unused-looking constant — verify before move.*
- **MOVES**: `tui_section import from prompt_gen` → `pm_core/streams/_shared_prompts.py`
    - *v2 lists tui_section explicitly as a _shared fragment; prompt_gen.py is deleted.*
- **MOVES**: `background review kickoff (review_mod.review_step calls)` → `pm_core/supervisors/plan_stream.py`
    - *Per-stream auto-review becomes PlanStreamSupervisor responsibility; each PlanXStream emits completion, supervisor spawns ReviewStream. Reduces duplicated review_step boilerplate across handlers.*

  *Not in plan:*
  - _PROMPT_ARG_LIMIT — Linux MAX_ARG_STRLEN safety guard on prompt size passed via argv to claude CLI: Add to pm_core/runtime/tmux_host.py (or keep in pm_core/claude_launcher.py which stays). The RuntimePlugin Protocol's max_inline_input_bytes capability field is the natural home — TmuxHostRuntime advertises this limit and callers respect it.
  - plan_load's title->id resolution for depends_on across PRs being created in same batch: Keep in CLI (stays). If duplication appears, extract to pm_core/plans/parser.py (which stays) as a `resolve_dependencies` helper.
  - review file parsing (review_mod.parse_review_file used by plan_fix to determine step): Confirm pm_core/plans/review.py stays alongside plans/parser.py, or fold its review-file read/write into sensorium ReviewFileArtifact and keep parse helpers there.

  *Cross-cutting:* Imports from this file that constrain ordering: (1) prompt_gen.tui_section — prompt_gen.py is DELETED in v2, so tui_section must land in pm_core/prompts/_shared.py before this file can be edited. (2) plans.review module — used heavily for background-review kickoff and review-file parsing; v2 doesn't enumerate it but it's implicitly a stay (parallel to plans/parser.py). (3) claude_launcher.find_claude/launch_claude/clear_session — stays per v2 (TmuxHostRuntime consumes it). (4) pm_core/cli/init.py imports _import_github_prs and _run_plan_import from this file — init.py migration is coupled to whether those helpers stay here or move into streams/plan/import_.py. (5) cli/helpers (_auto_select_plan, _require_plan, _make_pr_entry, etc.) — these helpers need a home in v2; if they stay in cli/helpers.py, this file's STAYS portions are fine. Each agentic subcommand follows the same pattern (build prompt → launch_claude → review_step) — this strongly motivates the v2 PlanStreamSupervisor pattern to eliminate ~6 copies of the boilerplate.

#### `pm_core/cli/pr.py`
*3260 LOC of Click CLI commands for the PR lifecycle: add/edit/list/select/cd/graph/ready/spec/spec-approve/start/review/qa/signoff/merge/cleanup/close/sync/sync-github/import-github/auto-sequence/note (group), plus helpers for launching tmux windows (impl, review, signoff, merge, companion), parsing/applying pr edit blobs, stash/unstash around merges, finalizing merges, pulling after merge, polling for verdicts (review, signoff, qa, impl-idle), and detached qa runs. The CLI shell stays; most business logic delegates into Streams/Supervisors/Runtimes.*

- **STAYS**: `pr add command` → `pm_core/cli/pr.py`
    - *Body becomes a thin delegate to ProjectYamlArtifact + PRStreamSupervisor.create*
- **STAYS**: `pr edit + _parse_pr_edit_raw + _apply_pr_edit + _restore_unicode` → `pm_core/cli/pr.py`
    - *Edit-blob parsing is CLI-shaped; writes delegate to pm_core/sensorium/artifact/project_yaml.py*
    - *Inline `click.Choice([...])` PR-status list at L315-316 DELETES; replaced by `click.Choice([s.value for s in PRStatus])` reading from `pm_core/mind/lifecycle.py`. Removes the fifth+ parallel copy of the status enum.*
- **STAYS**: `pr select / pr cd / pr list / pr graph / pr ready` → `pm_core/cli/pr.py`
    - *Listing/navigation against store + graph.py; minor call-site updates*
- **MOVES**: `pr spec / pr spec-path / pr spec-approve` → `pm_core/sensorium/artifact/spec.py`
    - *Generator moves to pm_core/prompts/spec_gen.py; SpecArtifact owns persistence; CLI stays as delegator*
- **MOVES**: `pr start + _launch_review_window + _add_companion_pane (impl-window launch)` → `pm_core/streams/impl.py`
    - *Tmux launch + claude session resumption become ImplStream.start via pm_core/runtime/tmux_host.py*
- **MOVES**: `pr review (loop + plain)` → `pm_core/streams/review.py`
    - *ReviewStream owns launch; LoopMode.kill_restart on review.requested*
- **MOVES**: `pr signoff` → `pm_core/streams/signoff.py`
    - *SignoffStream + SignoffSystemPrompt own this*
- **MOVES**: `pr signoff-record (hidden)` → `pm_core/streams/signoff.py`
    - *Verdict recording becomes Emission append into StreamTranscript + EmissionLog*
- **MOVES**: `pr qa` → `pm_core/streams/qa_planning.py`
    - *Entry into Qa* stream chain; CLI stays as delegator*
- **MOVES**: `pr merge + _finalize_merge + _launch_merge_window + _pull_after_merge + _pull_from_workdir + _resolve_window_default` → `pm_core/streams/merge.py`
    - *MergeStream + MergeConflictResolverStream own merge flow; launch via TmuxHostRuntime; git pulls via git_ops*
- **MOVES**: `_stash_for_merge / _unstash_after_merge / _is_dirty_overlap_error / _dirty_file_paths / _workdir_is_dirty` → `pm_core/sensorium/workdirs.py`
    - *Cross-workdir stash coordination explicitly listed in v2 under WorkdirRegistry+Workdir*
- **MOVES**: `pr cleanup + _cleanup_pr + _clear_workdir` → `pm_core/supervisors/pr_stream.py`
    - *pr_cleanup.py is deleted in v2; fans out to PRStreamSupervisor.teardown + ResourceLease release + WorkdirRegistry*
- **MOVES**: `pr close` → `pm_core/supervisors/pr_stream.py`
    - *Becomes PRStreamSupervisor.close (state transition + gh_ops + branch cleanup)*
- **STAYS**: `pr sync / pr sync-github / pr import-github` → `pm_core/cli/pr.py`
    - *Delegates to pr_sync.py and gh_ops.py which stay*
- **MOVES**: `pr note group (add/edit/list/delete)` → `pm_core/sensorium/artifact/notes.py`
    - *Notes storage is NotesSectionArtifact; CLI stays as delegator*
- **MOVES**: `pr auto-sequence + _impl_window_pane + _review_window_pane + _signoff_window_pane + _check_review_verdict + _check_signoff_verdict + _check_impl_idle + _qa_status_for + _retire_signoff_window + _auto_seq_transcript_dir` → `pm_core/supervisors/pr_stream.py`
    - *Auto-sequencing impl->review->qa->signoff->merge is PRStreamSupervisor's job; verdict polling becomes CallbackRegistry.wait_for at pm_core/agent/callbacks.py; idle detection becomes runtime capability; transcript paths become StreamTranscript at pm_core/agent/transcript.py*
- **MOVES**: `pr qa-run-bg (hidden) + _launch_qa_detached` → `pm_core/runtime/tmux_host.py`
    - *Detached background launch is a runtime capability; orchestration in QaSupervisor / PRStreamSupervisor*
- **DELETES**: `Verdict checking by scanning transcript files`
    - *verdict_transcript.py is deleted in v2; replaced by EmissionLog queries + CallbackRegistry.wait_for(predicate=...) at pm_core/agent/callbacks.py*

  *Not in plan:*
  - pr cd emits a path for shell-wrapper chdir: Keep pr_cd in pm_core/cli/pr.py calling PathService.workdir_for(pr_id); document shell-eval contract in pm_core/cli/__init__.py or bootstrap.py
  - pr import-github bulk-import reconciliation: Leave in pm_core/cli/pr.py as a delegator; ensure pr_sync.py owns reconciliation
  - Spec generation phase enumeration + regenerate semantics: Add SpecPhase StrEnum + regenerate policy on pm_core/sensorium/artifact/spec.py
  - Companion pane (secondary shell pane attached to a PR window): Add CompanionPane to pm_core/tui/pane_registry.py
  - Background re-entry contract via hidden --background/--transcript/--origin/--propagation-only flags: Fold pm-self-reentry into pm_core/runtime/hook_entry.py as a pm-reentry mode, or add pm_core/runtime/reentry.py; flag for plan-mind

  *Cross-cutting:* cli/pr.py depends on: pr_cleanup.py (DELETED), pane_idle.py (DELETED), verdict_transcript.py (DELETED), signoff.py (DELETED->Stream), qa_loop.py (DELETED->Stream), review_loop.py (DELETED->Stream), claude_launcher.py (STAYS, via TmuxHostRuntime), container.py (DELETED->TmuxContainerRuntime), prompt_gen/spec_gen (DELETED->prompts/). Migration order: (1) build pm_core/streams/* and pm_core/runtime/tmux_host.py, (2) move workdir stash helpers to sensorium/workdirs.py, (3) move auto-sequence into PRStreamSupervisor, (4) thin pr.py to delegators. Memory note 'CLI pr start OK' must be preserved by the delegator. Hidden re-entry flags (--background, --transcript, --origin, --propagation-only) form an implicit protocol that the new runtime/supervisor layer must preserve or replace explicitly.

#### `pm_core/cli/qa.py`
*Click CLI group `pm qa` exposing the QA instruction library: list/show/edit instructions and regressions, add (template-create), author (Claude-driven authoring), captures-path, docs, regression (run regression test by id), run (run a QA instruction against a PR), debug (debug an instruction in a Claude session), launch (open in tmux window), standalone, and a nested `mocks` subgroup (list/show/add/edit/prompt). Mixes thin file-system reads with stream-launching (Claude sessions / tmux panes).*

- **STAYS**: `qa group + _resolve_qa_item (id/category resolution)` → `pm_core/cli/qa.py`
    - *Per v2: pm_core/cli/ stays as command surface; the qa group remains but its action commands become thin delegators.*
- **MOVES**: `qa list / qa show / qa docs (read QA library entries)` → `pm_core/sensorium/artifact/qa_library/instructions.py`
    - *Reads of the QA instruction library become QaLibraryArtifact / QaInstructionsArtifact reads; CLI delegates.*
- **MOVES**: `qa add-instruction / add-regression / add-artifact (template scaffolding via _qa_add/_category_dir)` → `pm_core/sensorium/artifact/qa_library/instructions.py`
    - *Template creation becomes an Artifact constructor / factory method on QaLibraryArtifact subclasses (instructions.py, regression.py, artifacts.py).*
- **MOVES**: `qa captures-path (resolves capture bundle path for a PR)` → `pm_core/sensorium/captures.py`
    - *CaptureService/CaptureBundle owns capture-path resolution; CLI thin-wraps.*
- **MOVES**: `qa author-instruction / author-regression / author-artifact (Claude-driven authoring stream)` → `pm_core/streams/qa_author.py`
    - *QaAuthorStream — qa_authoring.py is explicitly listed as folding into QaAuthorStream. CLI delegates to Mind.stream(role=QaAuthorStream, ...).*
- **MOVES**: `qa edit (open file in editor)` → `pm_core/sensorium/artifact/base.py`
    - *Becomes Artifact.open_in_editor — editor.py is listed as deleted/absorbed into Artifact.open_in_editor.*
- **MOVES**: `qa regression (run regression test by id, file_prs flag)` → `pm_core/streams/qa_regression.py`
    - *QaRegressionStream launched via Mind.stream(role=QaRegressionStream, ...). qa_loop.py is listed as rewritten into Qa*Streams + QaSupervisor.*
- **MOVES**: `qa run (run instruction against a PR)` → `pm_core/streams/qa_verification.py`
    - *Running an instruction against a PR maps to a verification stream under the per-PR Supervisor.*
- **MOVES**: `qa debug (Claude session against instruction, foreground/branch options)` → `pm_core/streams/qa_author.py`
    - *Debug-an-instruction is an authoring/iteration session on the instruction Artifact; reuses QaAuthorStream with a debug-flavored InputType.*
- **MOVES**: `qa launch (open instruction in a tmux window with target_window option)` → `pm_core/runtime/tmux_host.py`
    - *Tmux-window opening is a runtime concern; CLI thin-wraps Mind.stream(... runtime=TmuxHostRuntime) with the proper Stream role.*
- **MOVES**: `qa standalone (run instruction outside PR context)` → `pm_core/streams/qa_verification.py`
    - *Same Stream as `qa run` with no PR-binding; or a QaStandalone variant — fits under qa_verification.py.*
- **MOVES**: `qa mocks list / show (read mocks library)` → `pm_core/sensorium/artifact/qa_library/mocks.py`
    - *Direct mapping to qa_library/mocks.py Artifact subclass.*
- **MOVES**: `qa mocks add (scaffold mock file)` → `pm_core/sensorium/artifact/qa_library/mocks.py`
    - *Mock Artifact factory.*
- **MOVES**: `qa mocks edit (open mock in editor)` → `pm_core/sensorium/artifact/base.py`
    - *Artifact.open_in_editor on a MockArtifact instance.*
- **MOVES**: `qa mocks prompt (emit prompt fragment about mocks)` → `pm_core/streams/_shared_prompts.py`
    - *Mocks-related prompt fragment belongs in cross-prompt shared fragments.*

  *Cross-cutting:* qa.py imports from pm_core.qa_instructions, pm_core.qa_authoring, pm_core.qa_loop, pm_core.editor, pm_core.captures (likely), and from the tmux/claude_launcher stack — all of which are listed as deleted/absorbed. Migration of this CLI is gated by: (1) QaLibraryArtifact subclasses in sensorium/artifact/qa_library/, (2) QaAuthorStream + QaVerificationStream + QaRegressionStream under streams/, (3) CaptureService in sensorium/captures.py, (4) Artifact.open_in_editor in sensorium/artifact/base.py. The CLI file itself stays as the command-surface entry point; only its bodies change to delegators. tui/qa_loop_ui.py (a "thin delegator" per the v2 notes) and pm_core/qa_status.py (deleted → watchdog/tui.py) both share the same QA-library reads, so coordinating these migrations together is wise.

#### `pm_core/paths.py`
*A grab-bag of path/config helpers: ~/.pm/ directory roots, session-tag derivation from git repo, per-session config files (debug, skip-permissions, fake-claude, fake-github, override, pm_root), captures dir resolution (host + container bind-mount), QA status lookup, command logging + logger configuration, global settings, shared tmux socket paths + permissions for multi-user mode, and bench cache dir. Explicitly called out as "mostly stays" in v2 plan but several pieces clearly belong elsewhere.*

- **STAYS**: `pm_home / pane_registry_dir / debug_dir / workdirs_base / sessions_dir / pm_core_path`
    - *Core ~/.pm/ root directory helpers. v2 plan explicitly says paths.py stays for most. Consumed by sensorium/paths.py PathService and WorkdirRegistry.*
- **STAYS**: `get_session_tag / session_dir / set_session_pm_root / get_session_pm_root`
    - *Session-tag derivation from git repo. Consumed by bootstrap.py (pm_root persistence) and many call sites. Stays as foundational substrate.*
- **MOVES**: `captures_dir + CONTAINER_CAPTURES_MOUNT` → `pm_core/sensorium/captures.py`
    - *Capture-bundle path resolution belongs with CaptureBundle/CaptureService. Container bind-mount constant moves with it (or to runtime/tmux_container.py if it's runtime-owned).*
- **DELETES**: `latest_qa_status_path`
    - *QA status is being rewritten as QaSupervisor/Qa*Stream + watchdog/tui.py. qa_status.json file-scanning is replaced by EmissionLog queries on QA streams.*
- **STAYS**: `debug_enabled / set_debug`
    - *Per-session debug flag. Consumed by configure_logger. Foundational.*
- **MOVES**: `skip_permissions_enabled / set_skip_permissions` → `pm_core/runtime/tmux_host.py`
    - *Claude-launch permission flag — runtime concern (TmuxHostRuntime / claude_launcher consumes it). Could alternately stay since claude_launcher stays.*
- **MOVES**: `fake_claude_config / fake_claude_config_for_type / set_fake_claude_config / clear_fake_claude` → `pm_core/sensorium/artifact/fake_claude_config.py` (`FakeClaudeConfigArtifact`) — *revised per locking-story consolidation; the raw file getters/setters become a typed Artifact with schema validation + change-notify. `FakeClaudeRuntime` consumes the Artifact rather than the bare path helpers. Filename constants (`fake-claude`, `fake-claude.state`) live in `pm_core/_path_constants.py`.*
- **STAYS**: `fake_github_dir / fake_github_active / clear_fake_github`
    - *Consumed by pm_core/fake_github.py which v2 says stays. Tightly coupled — moves with fake_github.py if anything.*
- **STAYS**: `configure_logger / command_log_file / log_shell_command / run_shell_logged`
    - *Cross-cutting shell logging — consumed by gh_ops/git_ops (which stay). Stays as part of foundational substrate.*
- **MOVES**: `get_override_path / set_override_path` → `pm_core/sensorium/artifact/host_override.py` (`HostOverrideArtifact`) for the per-session workdir/branch override file — *revised per locking-story consolidation; typed Artifact with schema validation replaces raw file getters/setters*. The bootstrap-time *path resolution* (`OVERRIDE_FILENAME` literal, session-dir derivation) lives in `pm_core/_path_constants.py` so `bootstrap.py` can read the override before `pm_core` is importable; the Artifact's higher-level read/write/edit-interactively/change-notify lands in sensorium.
- **MOVES**: `get_global_setting / has_global_setting / set_global_setting / get_global_setting_value / set_global_setting_value` → `pm_core/sensorium/artifact/global_settings.py` (`GlobalSettingsArtifact`) — *resolves the previous MISSING_FROM_PLAN flag per locking-story consolidation. The free-form `dict[str, Any]` KV store becomes a typed Artifact with `GlobalSettings` schema (one field per known key: `provider`, `default_model`, `effort`, capture flags, observability flags, etc.). Paired with `model_config.py` which becomes the typed schema definition + resolver; the persistence + change-notify lives on the Artifact.*
- **STAYS**: `clear_session`
    - *Session teardown; foundational.*
- **STAYS**: `bench_cache_dir`
    - *v2 says pm_core/bench/ is out-of-refactor; this helper stays with it.*
- **MOVES**: `SHARED_SOCKET_DIR / shared_socket_path / ensure_shared_socket_dir / set_shared_socket_permissions / get_share_users` → `pm_core/collaboration/transport/tmux_socket.py`
    - *Multi-user shared tmux socket primitives — exactly the substrate the tmux_socket transport needs (same-host shared tmux socket per v2).*

  *Not in plan:*
  - Global pm settings registry (~/.pm/settings/*): Either leave the 5 get/set/has_global_setting* helpers in paths.py (lowest churn — consistent with v2's 'paths.py mostly stays'), or add a small pm_core/settings.py module owned by pm_core/mind.py for global preferences. Safe to defer.
  - Container bind-mount path constant CONTAINER_CAPTURES_MOUNT: Co-locate with sensorium/captures.py as the canonical mount constant; TmuxContainerRuntime imports it when wiring the bind-mount.

  *Cross-cutting:* paths.py is imported by virtually every module in pm_core (gh_ops/git_ops via run_shell_logged, claude_launcher via fake_claude_config, container.py via CONTAINER_CAPTURES_MOUNT, cli/helpers via _get_pm_session, tui via configure_logger). Migration is highly call-site-sensitive: any split should preserve back-compat re-exports from paths.py to avoid touching dozens of importers in one shot. The fake_claude_config split blocks runtime/fake.py until done; SHARED_SOCKET_DIR split blocks collaboration/transport/tmux_socket.py; captures_dir split blocks sensorium/captures.py. Also: imports pm_core.git_ops, pm_core.fake_claude (SESSION_TYPE_VERDICTS, validate_session_verdicts), pm_core.cli.helpers — these coupling points need to survive the move.

#### `pm_core/tui/pane_ops.py`
*Collection of TUI helper functions that take the Textual app instance as first arg, wrapping tmux pane launch/kill/rebalance, plus role-specific launchers (Claude, discuss, watcher-review, QA item, plan edit/breakdown/deps/review, notes, log, meta, guide, plan-add), plus registry healing, plans-window routing, connect/quit/restart. All are TUI orchestration glue around pm_core.tmux + pane_registry + pane_layout + claude_launcher + prompt_gen.*

- **STAYS**: `heal_registry`
    - *Pure pane_registry healing — foundational TUI/tmux substrate. Stays in tui/pane_ops.py.*
- **STAYS**: `get_session_and_window`
    - *Thin tmux helper; TUI-only.*
- **STAYS**: `launch_pane (core)` → `pm_core/tui/pane_ops.py`
    - *Core pane lifecycle — wraps trap, registers, rebalances, dedups by role. This IS the implementation TmuxHostRuntime will consume (per v2: 'TmuxHostRuntime — wraps today's launch_pane + claude_launcher'). Stays; runtime/tmux_host.py imports it.*
- **STAYS**: `rebalance`
    - *TUI keybinding handler; tmux substrate.*
- **MOVES**: `find_editor` → `pm_core/sensorium/artifact/base.py`
    - *Editor resolution belongs to Artifact.open_in_editor / edit_interactively; small helper inlined there. Could also stay as TUI util — either way is minor.*
- **MOVES**: `edit_plan (PR-edit launcher)` → `pm_core/streams/pr_action.py`
    - *TUI keybinding 'e' on a PR → becomes a PRActionStream invocation; the shim here delegates to Stream.start via app dispatch. The launch_pane call moves into TmuxHostRuntime.*
- **MOVES**: `view_plan (open plan-for-PR)` → `pm_core/sensorium/artifact/plan.py`
    - *Becomes PlanArtifact.open_in_editor() / .resolve_link() invoked from a TUI shim.*
- **MOVES**: `launch_notes` → `pm_core/sensorium/artifact/notes.py`
    - *NotesSectionArtifact.edit_interactively() — TUI shim calls into the Artifact.*
- **STAYS**: `view_log`
    - *Generic tail-f on command log — TUI debug util. Stays.*
- **MOVES**: `launch_meta` → `pm_core/streams/meta_development.py`
    - *Becomes MetaDevelopmentStream invocation; the load_watcher_plan_prs side-effect should move to WatcherSupervisor reconcile.*
- **MOVES**: `launch_guide` → `pm_core/streams/guide/setup.py`
    - *Routed to guide/setup.py or guide/assist.py depending on project state (per v2 streams/guide/{setup,assist}.py). TUI shim dispatches.*
- **MOVES**: `launch_claude (interactive Claude session)` → `pm_core/streams/discuss.py`
    - *Free-form Claude session with pm context belongs alongside discuss.py (or a sibling 'shell' Stream). The embedded prompt string moves to pm_core/prompts/_shared.py or a new prompts/shell_system.py.*
- **MOVES**: `launch_discuss` → `pm_core/streams/discuss.py`
    - *DiscussStream. Embedded prompt moves to pm_core/prompts/ (new discuss_system.py) — currently inlined here.*
- **MOVES**: `launch_watcher_review` → `pm_core/streams/watchers/watcher_review.py`
    - *Maps to WatcherReviewStream; uses prompts/watcher/watcher_review.py for the prompt (currently generate_watcher_review_prompt in prompt_gen.py which is slated for deletion).*
- **MOVES**: `launch_qa_item` → `pm_core/streams/qa_author.py`
    - *QaAuthorStream for category==instructions; for category==regression delegates to QaRegressionStream (streams/qa_regression.py). Prompt assembly moves to prompts/qa_authoring.py + prompts/regression/bug_reproduce.py.*
- **STAYS**: `_plans_window_name / _focus_plans_window / _wrap_pane_cmd / _launch_in_plans_window`
    - *tmux-window routing infrastructure for per-plan windows — TUI substrate consumed by plan stream launches. Stays in pane_ops.py (or moves to tui/pane_layout.py as a helper).*
- **MOVES**: `handle_plan_action (edit/breakdown/deps/load/review)` → `pm_core/streams/plan/breakdown.py`
    - *Each branch maps to a different PlanStream (plan/breakdown.py, plan/deps.py, plan/review.py, plan/import_.py for 'load'); 'edit' maps to PlanArtifact.edit_interactively. TUI shim becomes a 3-line dispatch table keyed on action.*
- **MOVES**: `handle_plan_add` → `pm_core/streams/plan/add.py`
    - *PlanAddStream; plan-id pre-computation stays inline as TUI shim or moves into PlanStreamSupervisor.create_plan.*
- **MOVES**: `launch_plan_activated (open plan file)` → `pm_core/sensorium/artifact/plan.py`
    - *PlanArtifact.open_in_editor (or read-only view variant).*
- **STAYS**: `show_connect (tmux shared-session connect-string screen)`
    - *TUI screen helper; tmux session metadata. Stays.*
- **STAYS**: `quit_app / restart_app`
    - *Textual app lifecycle + os.execvp — TUI-only. Stays in pane_ops.py or moves to tui/app.py.*

  *Not in plan:*
  - TUI shim dispatch layer — the pattern where a keybinding in app.py calls a pane_ops function, which assembles a prompt + cmd and calls launch_pane: Keep pane_ops.py as the canonical TUI shim file; after migration, its per-role functions become 3-5 line delegators that build the Stream's input artifact and call mind.stream(role=XStream, runtime=TmuxHostRuntime, ...). No new file needed — name this pattern explicitly in plan-mind or plan-sensorium so reviewers know pane_ops.py is intentionally the shim landing pad.
  - **Non-PR `action_*` delegate boilerplate** in `pm_core/tui/app.py:849-874` (`action_edit_plan`, `action_view_plan`, `action_launch_notes`, `action_view_log`, `action_launch_meta`, `action_rebalance`, `action_launch_claude`, `action_launch_guide`, `action_show_connect` — ~9 methods total): These are NOT PR-action delegates and intentionally do NOT get a `PRActionTUIType` binding. They stay as thin app.py methods calling pane_ops helpers — the typed-binding completeness check excludes them by construction (`PRActionTUIType` is the PR-action family, not the general TUI-action family). The audit (P9) considered a sibling `TUIPaneActionType` family but the cost (9 new tiny classes for 9 stable handlers) exceeds the drift risk (these handlers don't share state machinery with PR actions and rarely change). Flagged here so reviewers don't expect them under `pm_core/tui/pr_actions/`. If a future refactor adds a non-PR action that DOES share state (e.g., a typed pane lifecycle), revisit then.
  - Per-plan tmux window routing (_launch_in_plans_window family): Either (a) push this into TmuxHostRuntime as a 'window grouping policy' parameter that PlanStreamSupervisor sets, or (b) keep it in tui/pane_layout.py as a 'plans grouping helper'. Recommend (a) so non-TUI runtimes (raw_api, managed_agent) can ignore it cleanly. Worth a one-line note in plan-mind under runtime/tmux_host.py.
  - launch_claude (generic 'discuss pm' session) vs launch_discuss — two near-duplicate Claude-with-pm-context launchers: Merge into a single DiscussStream with a 'mode' enum (work | learn) or split into discuss.py + onboarding.py. Either is fine; just call it out so a reviewer doesn't lose one of the two prompt bodies during migration.
  - load_watcher_plan_prs side effect inside launch_meta: Belongs in WatcherSupervisor reconcile loop (pm_core/supervisors/watcher.py) or as an ArtifactChangeChannel subscriber on bugs.md/improvements.md. Add to plan-mind.

  *Cross-cutting:* Imports pm_core.prompt_gen (tui_section, generate_watcher_review_prompt) and pm_core.regression_prompts and pm_core.qa_instructions — all three are slated for DELETION/refactor into pm_core/prompts/_shared.py, pm_core/prompts/watcher/watcher_review.py, pm_core/prompts/regression/, and pm_core/sensorium/artifact/qa_library/*. Call sites here must be rewritten when those modules move. Also tightly coupled to pm_core.tmux + tui/pane_layout + tui/pane_registry (all STAY per plan — "foundational substrate consumed by all Tmux* runtimes"). The launch_* functions are the primary call sites the new TmuxHostRuntime needs to absorb; until streams/PRActionStream wires up tui_keybinding + tui_window_role, the TUI app.py still needs to call these as the keybinding-dispatch shim. This is the canonical "TUI integration shim" location.

#### `pm_core/tui/sync.py`
*TUI background and startup sync routines: reload project.yaml, run pr_sync.sync_prs / sync_from_github in an executor on a deep-copied data dict, apply merged-PR status updates under store lock, tear down merged PRs' tmux windows/containers/sockets via pr_cleanup, refresh status bar, and trigger auto-start for newly ready PRs. Also handles guide-mode state detection and capture-config reload.*

- **STAYS**: `background_sync entry (reload project.yaml + dispatch to guide or normal sync)` → `pm_core/tui/sync.py`
    - *TUI-side periodic tick. v2 keeps pm_core/tui/ mostly unchanged; this stays as a thin orchestration layer but now its data-load step is conceptually backed by ProjectYamlArtifact (sensorium/artifact/project_yaml.py). Call sites update to read through the artifact when that lands.*
- **STAYS**: `capture-config reload on tick` → `pm_core/tui/frame_capture.py`
    - *frame_capture.py explicitly stays per v2.*
- **MOVES**: `guide-mode state detection branch (guide.detect_state, _show_guide_view/_show_normal_view)` → `pm_core/streams/guide/setup.py`
    - *Guide workflow becomes guide/{setup,assist}.py streams; the tick-driven 'has-the-user-progressed?' check belongs to GuideSetupStream's watcher logic. The TUI keeps a thin delegator per the 'TUI integration shim pattern' note.*
- **MOVES**: `do_normal_sync: PR sync orchestration (deep-copy data, run pr_sync.sync_prs in executor, apply merged statuses under store.locked_update)` → `pm_core/supervisors/pr_stream.py`
    - *Per-PR lifecycle (detect merged, mark merged, record timestamp) is PRStreamSupervisor's job. pr_sync.py itself STAYS per v2; the orchestration around it (lock, status timestamp, race avoidance) moves to the supervisor. TUI calls become 'observe a lifecycle Emission'.*
- **MOVES**: `store.locked_update wrapping for atomic project.yaml writes` → `pm_core/sensorium/artifact/project_yaml.py`
    - *Atomic edits to project.yaml are the ProjectYamlArtifact.apply / propose_edit responsibility; callers stop using store.locked_update directly.*
- **MOVES**: `_record_status_timestamp PR status bookkeeping` → `pm_core/streams/pr_action.py`
    - *PR lifecycle state transitions are now driven by PRActionStream / lifecycle.py PRStatus; the timestamp recording lives alongside PRStatus transitions. Currently imported from pm_core.cli.helpers; that helper itself stays but the call site moves.*
- **MOVES**: `_kill_merged_pr_windows: tear down windows/containers/sockets/registry for merged PRs (via pr_cleanup.cleanup_pr_resources)` → `pm_core/supervisors/pr_stream.py`
    - *pr_cleanup.py is DELETED in v2 ('fans out across Supervisor teardown + runtime cleanup hooks'). Window/container/socket teardown becomes PRStreamSupervisor.shutdown() composed with the runtime's cleanup hook (TmuxHostRuntime tears tmux windows; TmuxContainerRuntime tears containers + push_proxy sockets). The hardcoded window-name pattern at `sync.py:22` (today's `(?:review-|merge-|qa-)?` prefix string) DELETES; the rewritten teardown enumerates `PRActionTUIType.__subclasses__()` and reads each `window_role` for the pattern set.*
- **MOVES**: `auto-start-on-newly-merged dispatch (check_and_start)` → `pm_core/streams/watchers/auto_start.py`
    - *Auto-start watcher is its own Stream subclass under streams/watchers/. The 'PR merged -> consider starting next ready PR' edge is a subscription on the per-PR LifecycleGlobalChannel rather than an inline call from sync.*
- **STAYS**: `status-bar update routing (mode_owns_status guard, sync_state propagation)` → `pm_core/tui/sync.py`
    - *Pure UI concern; remains in tui/ as a thin delegator that reacts to sync Emissions from PRStreamSupervisor.*
- **MOVES**: `startup_github_sync: one-shot GitHub PR-state pull on launch (sync_from_github + atomic status apply + merged cleanup + auto-start)` → `pm_core/supervisors/pr_stream.py`
    - *Same as do_normal_sync but with a different sync source. The GitHub-specific dispatch (backend == 'github') is a backend capability check; pr_sync.sync_from_github STAYS, but the orchestration moves to PRStreamSupervisor (perhaps a startup hook on MindSupervisor).*
- **MOVES**: `ProjectYamlParseError / StoreLockTimeout error surfacing to user` → `pm_core/sensorium/artifact/project_yaml.py`
    - *Becomes Artifact.apply error semantics; UI subscribes via Artifact.on_change / failure Emission rather than catching store exceptions.*
- **UNCLEAR**: `SystemExit suppression around sync (defensive against pr_sync calling sys.exit)`
    - *Defensive guard against legacy code paths; should disappear once orchestration moves to supervisors, but may need an explicit note in supervisors/pr_stream.py.*

  *Not in plan:*
  - Cross-source merge reconciliation: detecting merges that happened outside the in-process sync (e.g. `pm pr merge` for vanilla backend writing to disk, then the TUI re-reading and noticing the status delta via old_statuses snapshot).: Add a 'project.yaml change-detection' responsibility to pm_core/sensorium/artifact/project_yaml.py (use Artifact._on_external_change hook, already listed in v2) and have PRStreamSupervisor subscribe to it so it can synthesize a lifecycle.merged Emission when an external writer flips status. Worth calling out explicitly in plan-sensorium.
  - Distinction between manual-refresh (is_manual=True, shorter min_interval, transient 'Refreshed' toast) and periodic background sync.: Stays in pm_core/tui/sync.py as a thin delegator that calls into PRStreamSupervisor with a 'force' flag plus its own toast timer. No new file needed.

  *Cross-cutting:* Imports pm_core.pr_sync (STAYS), pm_core.store (STAYS), pm_core.guide, pm_core.pr_cleanup (DELETED in v2 — its consumers all need migration before pr_cleanup can be removed; this file is one of two main call sites alongside the manual Y/y keybinding handler in app.py). Imports pm_core.tui.frame_capture (STAYS) and pm_core.tui.auto_start (becomes a thin delegator to streams/watchers/auto_start.py). pm_core.cli.helpers._record_status_timestamp is consumed here and in CLI commands; safe to leave as a shared helper but the call edge moves into PRStreamSupervisor. Migration of this file is blocked on: (1) ProjectYamlArtifact existing (sensorium/artifact/project_yaml.py), (2) PRStreamSupervisor existing, (3) auto_start watcher Stream existing. Until then, this file is the natural integration shim.

#### `pm_core/tui/watcher_ui.py`
*TUI integration shim for watchers: defines WATCHER_PLANS (bugs.md / improvements.md) meta-workdir plan bootstrapping, loading PRs parsed from those plans into project.yaml, start/stop/is_running wrappers over WatcherManager, poll-timer notification logic, transcript finalization on completion, and a verdict-icon table for log lines.*

- **MOVES**: `WATCHER_PLANS constant (bugs/improvements plan metadata)` → `pm_core/streams/watchers/__init__.py`
    - *Belongs alongside WATCHER_REGISTRY as static config consumed by WatcherSupervisor/discovery streams.*
- **MOVES**: `ensure_watcher_plans (create bugs.md/improvements.md + register as plans in meta workdir)` → `pm_core/supervisors/watcher.py`
    - *Bootstrapping side-effect that WatcherSupervisor should perform on startup; touches ProjectYamlArtifact + PlanArtifact in the meta workdir (sensorium/workdirs.py provides the meta workdir).*
- **MOVES**: `load_watcher_plan_prs (parse bugs.md/improvements.md and append PR entries to project.yaml)` → `pm_core/supervisors/watcher.py`
    - *Same flow as ensure_watcher_plans; consumes plan_parser + ProjectYamlArtifact via supervisor.*
- **STAYS**: `WATCHER_VERDICT_ICONS (rich-markup verdict glyphs)` → `pm_core/tui/watcher_ui.py`
    - *TUI-rendering concern; per v2 'watcher_ui becomes thin delegator' pattern this stays in tui/ as part of the rendering shim.*
- **MOVES**: `start_watcher (resolve watcher class, register with WatcherManager, kick off iteration callbacks)` → `pm_core/supervisors/watcher.py`
    - *Replaced by WatcherSupervisor.start(role=..., instance_key=...) which constructs a watcher Stream under pm_core/streams/watchers/. TUI keybinding handler becomes a thin delegator calling Mind.supervisor('watcher').start(...).*
- **MOVES**: `stop_watcher (graceful stop request)` → `pm_core/supervisors/watcher.py`
    - *Becomes WatcherSupervisor.stop(stream_id) / Stream.request_stop; TUI shim only forwards the keypress.*
- **MOVES**: `is_running (check watcher liveness)` → `pm_core/supervisors/protocol.py`
    - *Subsumed by Stream.status (LifecycleState) and Supervisor.streams(role=, alive_only=True) on the StreamRecord dataclass.*
- **DELETES**: `_on_iteration_from_thread / _on_complete_from_thread (background thread callbacks logging iteration/verdict)`
    - *Replaced by Emission envelopes streamed through EmissionLog + Mailbox; LifecycleState transitions emit completion events that watchdog/tui.py consumes.*
- **MOVES**: `Transcript finalization on watcher completion (finalize_transcript over symlinked .jsonl in transcript_dir)` → `pm_core/runtime/tmux_host.py`
    - *Runtime-internal teardown; transcript handling is now pm-owned via StreamTranscript (agent/transcript.py) and the TmuxHostRuntime cleanup hook.*
- **MOVES**: `poll_watcher_state (1Hz poll over WatcherManager state, push notifications on INPUT_REQUIRED / completion / ERROR)` → `pm_core/watchdog/tui.py`
    - *This is exactly the TUI watchdog policy responsibility; consumes Manager/Supervisor events (or AttentionRequest from agent/attention.py for INPUT_REQUIRED) instead of polling.*
- **MOVES**: `_ui_notified_input / _ui_notified_done dedup flags on watcher state` → `pm_core/mind/emissions.py`
    - *Folds into Emission.dedup_key on the notification channel so watchdog/tui.py doesn't have to stash flags on state objects.*

  *Cross-cutting:* Imports pm_core.cli.meta.ensure_meta_workdir — the meta workdir concept needs a home in sensorium/workdirs.py (WorkdirRegistry) and a dedicated MetaWorkdir or named entry; otherwise ensure_watcher_plans/load_watcher_plan_prs have no clean substrate to land on. Also reaches into pm_core.tui.review_loop_ui._ensure_poll_timer — once polling moves to watchdog/tui.py the shared poll-timer plumbing should move with it (review_loop_ui is similarly slated to become a thin delegator). pm_core.watchers.get_watcher_class is replaced by WATCHER_REGISTRY in pm_core/streams/watchers/__init__.py — call sites in tui/app.py keybinding handlers will need updating in lockstep.

### MOSTLY_MOVES (30)

#### `pm_core/cli/meta.py`
*Click command `pm meta` for meta-development sessions on pm itself: ensures a meta workdir (clones the pm repo if needed), determines/creates a feature branch from master or a tag, detects how pm is installed, sets a per-session pm_core override, builds a Claude prompt with architecture/debugging guidance, and launches Claude either in the pm tmux session as a new window or as a fallback subprocess. Also exposes `pm meta cd` to drop into a shell inside the meta workdir.*

- **STAYS**: `meta_cmd Click entry point (CLI surface)` → `pm_core/cli/meta.py`
    - *CLI surface stays per v2 ('pm_core/cli/ — CLI command surface — most stays'); body is reduced to a thin delegator that constructs a MetaDevelopmentStream via Mind.*
- **MOVES**: `ensure_meta_workdir / _meta_workdir (clone pm repo into ~/.pm/workdirs/meta-<tag>, manage workdir lifecycle)` → `pm_core/sensorium/workdirs.py`
    - *Maps onto WorkdirRegistry + Workdir; the meta workdir becomes a typed Workdir owned by the sensorium.*
- **MOVES**: `Branch/tag/checkout logic (fresh clone vs resume, fetch+pull, checkout_branch)` → `pm_core/streams/meta_development.py`
    - *MetaDevelopmentStream setup phase; consumes git_ops + Workdir.*
- **MOVES**: `Session-override write (set_override_path) tying workdir's pm_core to running session` → `pm_core/sensorium/host_overrides.py`
    - *Maps directly onto HostCodeOverride in sensorium/host_overrides.py.*
- **MOVES**: `_build_meta_prompt (large templated prompt with architecture/debugging/override docs)` → `pm_core/streams/meta_development.py`
    - *Becomes a typed InputType under pm_core/prompts/. Not currently enumerated in the v2 prompts/ list, but follows the same pattern as other *_system prompts; sibling to streams/meta_development.py.*
- **MOVES**: `tmux window dedup + new_window launch + fallback subprocess.run` → `pm_core/runtime/tmux_host.py`
    - *Window create/find/select and Claude launch are TmuxHostRuntime responsibilities; MetaDevelopmentStream declares required_capabilities and the runtime handles the actual pane.*
- **MOVES**: `claude_launcher invocation (find_claude, build_claude_shell_cmd) + cleanup rm of session dir` → `pm_core/runtime/tmux_host.py`
    - *claude_launcher stays per v2 'Stays' list; TmuxHostRuntime consumes it. Session-dir cleanup becomes part of runtime teardown / HostCodeOverride lifecycle.*
- **MISSING_FROM_PLAN**: `_detect_pm_install (introspects pm_core install path, editable vs pip)`
    - *No clear home — it's a host-environment probe used only for prompt context. Recommend folding into pm_core/sensorium/host_overrides.py (as a static helper alongside HostCodeOverride) or deleting if the prompt no longer needs it once override semantics are handled by HostCodeOverride.*
- **STAYS**: `'pm meta cd' subcommand (chdir + execvp shell)` → `pm_core/cli/meta.py`
    - *Pure CLI affordance over a Workdir path; stays in the CLI layer but switches to calling WorkdirRegistry to resolve the path.*
- **MOVES**: `_get_session_name_for_cwd / _get_pm_session helpers usage (session-tag derivation)` → `pm_core/sensorium/workdirs.py`
    - *Session-tag derivation is part of identifying the active Workdir/Mind; cli helpers remain but the canonical lookup moves into sensorium.*

  *Not in plan:*
  - _detect_pm_install — host-side introspection of how pm itself is installed (editable vs site-packages, install command synthesis): Add a small helper in pm_core/sensorium/host_overrides.py (e.g. detect_host_install()) returning install metadata; the meta prompt consumes it. Alternatively, drop it — once HostCodeOverride is the canonical mechanism, the prompt doesn't need to explain pip vs editable installs.
  - pm_core/prompts/meta_development.py — typed InputType for the meta-development prompt: Add pm_core/prompts/meta_development.py to the v2 prompts/ tree as the paired InputType for MetaDevelopmentStream.

  *Cross-cutting:* Depends on pm_core.paths.set_override_path / workdirs_base and pm_core.cli.helpers._get_pm_session/_get_session_name_for_cwd; migration of meta.py is blocked until (a) sensorium/host_overrides.py exists to absorb the override write, (b) sensorium/workdirs.py exists to absorb meta workdir resolution, and (c) streams/meta_development.py + prompts/meta_development.py exist. Also consumes claude_launcher and tmux modules which v2 keeps as substrate for TmuxHostRuntime — so this file's migration should happen after TmuxHostRuntime lands.

#### `pm_core/container.py`
*Container isolation layer (Docker/Podman) for Claude sessions: image build, runtime detection (rootless podman/docker, nested-podman, AppArmor/SELinux), container lifecycle (create/exec/remove), resource limits, git identity setup, container-side git wrapper that forwards push to a host-side Unix-socket push proxy, QA-scenario and PR-scoped container naming/cleanup utilities, and wrap_claude_cmd to launch Claude inside a container.*

- **MOVES**: `ContainerError + ContainerConfig dataclass` → `pm_core/runtime/tmux_container.py`
    - Error type and resource-limit config consumed only by the container runtime
- **MOVES**: `Runtime detection (_detect_default_runtime, _get_runtime, _nested_podman_enabled, _apparmor_enforcing, _selinux_enabled, _nested_podman_run_args, _runtime_available)` → `pm_core/runtime/tmux_container.py`
    - Docker vs Podman selection + host security posture detection — runtime-internal
- **MOVES**: `Image build / existence cache (build_image, image_exists, _invalidate_image_exists_cache, _get_dockerfile_path)` → `pm_core/runtime/tmux_container.py`
    - Builds the container image consumed by TmuxContainerRuntime
- **MOVES**: `Config loader (load_container_config, is_container_mode_enabled)` → `pm_core/runtime/tmux_container.py`
    - *Could alternatively be exposed via RuntimePlugin capabilities; load remains runtime-local*
- **MOVES**: `_run_runtime / container_is_running helpers` → `pm_core/runtime/tmux_container.py`
    - Thin wrappers over docker/podman CLI
- **MOVES**: `_build_git_setup_script + _host_git_identity + git-wrapper proxy-client shell script (lines ~382-528)` → `pm_core/runtime/tmux_container.py`
    - *Imports from pm_core/runtime/push_proxy.py (the _CONTAINER_SOCKET_PATH constant) — coupling explicitly anticipated in v2*
- **MOVES**: `_resolve_claude_binary` → `pm_core/runtime/tmux_container.py`
    - Locates the claude CLI to bind-mount into container
- **MOVES**: `Container naming (_make_container_name, qa_container_name)` → `pm_core/runtime/tmux_container.py`
    - *Naming scheme is runtime-internal; the role/PR/QA-scenario identity that DRIVES the name is owned upstream by Supervisors/leases (ContainerKey in sensorium/leases.py)*
- **MOVES**: `create_container (main lifecycle, ~380 LOC)` → `pm_core/runtime/tmux_container.py`
    - Core container creation logic — becomes part of TmuxContainerRuntime.start/launch
- **MOVES**: `build_exec_cmd / remove_container / wrap_claude_cmd` → `pm_core/runtime/tmux_container.py`
    - Exec-into-container + Claude command wrapping — runtime-internal seam
- **MOVES**: `create_qa_container (QA-scenario container variant)` → `pm_core/runtime/tmux_container.py`
    - *Called by QaScenarioStream via runtime; the QA-specific tagging stays runtime-side, the orchestration moves to streams/qa_scenario.py*
- **MIXED**: `cleanup_qa_containers / cleanup_pr_containers / cleanup_orphaned_qa_containers / cleanup_session_containers / cleanup_all_containers` → `pm_core/runtime/tmux_container.py`
    - *Mechanism (docker rm by label) MOVES to tmux_container.py. The decisions of WHEN to clean up move to supervisors/pr_stream.py teardown and ResourceLease release in pm_core/sensorium/leases.py (ContainerKey lease release should call into the runtime). Also some session-wide cleanup currently triggered from pr_cleanup.py — v2 plan says pr_cleanup.py fans out across Supervisor teardown + runtime cleanup hooks; that holds here.*
    - *During the move, consolidate the inline `{CONTAINER_PREFIX}[{session_tag}-]qa-{pr_id}-{loop_id}-` prefix-list reconstruction (today duplicated across `container.py:1169, 1203, 1252` in the three `cleanup_*` functions) into a single helper — either `_qa_prefixes(pr_id, loop_id=None, session_tag=None) -> list[str]` on `TmuxContainerRuntime` or `ContainerKey.name_prefixes()` on the lease key. All three cleanup functions consume the helper; no inline prefix concatenation survives the move. Audit round-3 clarity nit.*
- **MOVES**: `Container snapshot/labels for identification by PR/QA/session` → `pm_core/sensorium/leases.py`
    - *ContainerKey in the lease hierarchy is the typed handle; the docker-label conventions used to find/cleanup containers should be co-located with ContainerKey or kept runtime-internal with ContainerKey holding the opaque container_name string*

  *Not in plan:*
  - Host security-posture detection (AppArmor enforcing, SELinux enabled, nested podman detection) — affects how the runtime configures itself, not strictly a runtime impl detail; could be reused by sandbox/host runtimes: Acceptable to keep inside tmux_container.py for now; if tmux_sandbox.py / tmux_host.py grow similar checks, extract to pm_core/runtime/host_probe.py in a follow-up
  - ContainerSnapshot artifact (mentioned in v2 artifacts/container_snapshot.py as 'references a sensorium-side container snapshot id, NOT a wrapper-internal snapshot'): No migration owed by container.py; clarify in plan that ContainerSnapshot is greenfield.
  - Container image build invalidation/caching beyond a simple in-process bool cache (image_exists cache): Stay inside tmux_container.py

  *Cross-cutting:* container.py imports from pm_core/push_proxy.py (specifically _CONTAINER_SOCKET_PATH) — v2 places both under pm_core/runtime/ (tmux_container.py + push_proxy.py), so the import path moves with them and the coupling is anticipated. Current callers of container.py include qa_loop.py, signoff.py, pr_cleanup.py, and likely claude_launcher.py / bridge.py — all of those are slated for deletion or rewrite (Streams + Supervisors), so call-site updates land naturally when those migrations happen. Cleanup entry points (cleanup_session_containers, cleanup_all_containers) are likely also invoked from CLI commands (pm cleanup or similar) under pm_core/cli/ which stays — those CLI handlers need updated import paths to pm_core/runtime/tmux_container.py. The QA container naming scheme (qa_container_name with pr_id/loop_id/scenario_index) encodes orchestration identity that conceptually belongs to ContainerKey in pm_core/sensorium/leases.py; recommend ContainerKey owns the canonical name() method and tmux_container.py consumes it, to avoid drift between lease-bookkeeping and runtime-side label filters.</cross_cutting_notes> </invoke>

#### `pm_core/fake_claude.py`
*Fake Claude session for integration testing: writes realistic preamble/body output, emits scriptable single-line or START/END-block verdicts on stdout, writes a Claude-format JSONL transcript, emits idle_prompt hook events, and holds the pane open to mimic a real interactive session. Also defines the catalog of valid verdicts per session type and validates fake-session configs.*

- **MOVES**: `run_fake_claude entrypoint + output sequencing (preamble, body batches, delays, hold-open, streaming, _write helper)` → `pm_core/runtime/fake.py`
    - *Becomes FakeClaudeRuntime's execute loop. v2 explicitly lists fake.py as 'FakeClaudeRuntime — test impl from FakeClaudeSession.'*
- **MOVES**: `Verdict catalog: SINGLE_LINE_VERDICTS, BLOCK_VERDICTS, ALL_VERDICTS, NO_VERDICT, ALL_VERDICT_CHOICES` → `pm_core/runtime/fake.py`
    - *These are the test-fixture vocabulary the fake emits. They mirror the ALLOWED_VERDICTS classvars on per-prompt InputType classes (prompts/protocol.py) — could be derived from those at test time instead of a duplicated catalog.*
- **MOVES**: `SESSION_TYPE_VERDICTS mapping (per session-type allowed verdicts) + validate_session_verdicts` → `pm_core/runtime/fake.py`
    - *In v2 each Stream subclass declares its own fake_runtime_script and the InputType declares ALLOWED_VERDICTS. This mapping becomes redundant — it could be replaced by aggregating ALLOWED_VERDICTS from each Stream's InputType. Keep a thin validate_session_verdicts helper in runtime/fake.py for tests until streams are migrated.*
- **MOVES**: `Scripted-sequence support (_scripted_sequence, _scripted_entry_verdict, _scripted_wrap)` → `pm_core/runtime/fake.py`
    - *Directly maps to Stream.fake_runtime_script declared on subclasses (streams/base.py mentions fake_runtime_script). The scripted-list/dict shape is the runtime-side interpretation.*
- **MOVES**: `_write_fake_transcript + _claude_transcript_path (writes Claude-format JSONL transcript)` → `pm_core/runtime/fake.py`
    - *Production verdict detection reads Claude's native JSONL. In v2, FakeClaudeRuntime emits Emissions and pm-owned StreamTranscript (agent/transcript.py) captures them. The fake's job to mimic a Claude-format on-disk JSONL likely goes away — but while TmuxHostRuntime + hook_entry.py still read native transcripts, the fake must produce them. Lives inside runtime/fake.py.*
- **MOVES**: `_emit_idle_hook (writes idle_prompt hook event the poller waits on)` → `pm_core/runtime/fake.py`
    - *Pairs with runtime/hook_entry.py. FakeClaudeRuntime fabricates the hook events that hook_entry.py would receive from real Claude Code. Tight coupling to hook_entry.py's event schema.*
- **MOVES**: `_hold_open (stay-open-with-periodic-hook-refresh loop, stdin select for graceful exit)` → `pm_core/runtime/fake.py`
    - *FakeClaudeRuntime lifecycle: mimics interactive Claude staying open. Maps to RuntimePlugin's interactive_tty capability behavior.*
- **MOVES**: `_resolve_block_name (verdict alias resolution: 'FLAGGED' or 'FLAGGED_END' both accepted)` → `pm_core/runtime/fake.py`
    - *Internal helper, moves with the catalog.*
- **MOVES**: `Preamble / body filler text constants (_PREAMBLE_LINES, _BODY_LINES, _DEFAULT_BODIES — referenced but defined elsewhere in file)` → `pm_core/runtime/fake.py`
    - *Test-fixture text content. Moves wholesale.*

  *Not in plan:*
  - Coordination between fake verdict emission and the on-disk Claude JSONL transcript format: Consider extracting a small pm_core/runtime/_claude_jsonl.py shared between TmuxHostRuntime (reading) and FakeClaudeRuntime (writing). Otherwise both runtimes duplicate the format. Could also live as a private helper in runtime/hook_entry.py.
  - SESSION_TYPE_VERDICTS as a single source of truth for which verdicts each session emits: Add a small helper in pm_core/streams/base.py (or prompts/protocol.py) that aggregates ALLOWED_VERDICTS across all registered Stream subclasses, so test infra can replace the SESSION_TYPE_VERDICTS table. Safe to leave the table in runtime/fake.py as a transitional shim.

  *Cross-cutting:* Imported/invoked by: claude_launcher.py (real launch path, picks fake binary when fake-claude config present), CLI entry (pm fake-claude or similar), and a console_scripts shim. Migration of fake_claude.py to runtime/fake.py is blocked on / coupled with: (1) runtime/hook_entry.py existing (shares idle_prompt event schema and Claude JSONL format); (2) streams/base.py declaring fake_runtime_script so scripted-sequence semantics have a typed home; (3) prompts/protocol.py exposing ALLOWED_VERDICTS so SESSION_TYPE_VERDICTS can be derived instead of duplicated; (4) TmuxHostRuntime + claude_launcher.py needing to know how to substitute FakeClaudeRuntime for tests. The v2 plan explicitly names fake.py as 'test impl from FakeClaudeSession' — this is a near-1:1 file move with internal renames.

#### `pm_core/guide.py`
*Implements `pm guide`: detects project setup state from project.yaml + plan files, runs non-interactive load step when applicable, and composes two large prompts — a setup prompt (walks user through init/plan/breakdown/load) and an assist prompt (helps user decide what to do next given the project lifecycle). Also exposes needs_guide() used by session startup / TUI.*

- **MOVES**: `STEP_ORDER / STEP_DESCRIPTIONS / SETUP_STATES / is_setup_state` → `pm_core/streams/guide/setup.py`
    - Setup-state enum/constants describing the guide's step machine.
    - *Lives with the GuideSetupStream that consumes them.*
- **MOVES**: `needs_guide()` → `pm_core/streams/guide/setup.py`
    - Predicate used by session startup + TUI to decide whether to auto-launch the guide stream.
    - *Becomes a classmethod / module helper on GuideSetupStream; callers (session startup, TUI) update to import from there.*
- **MOVES**: `detect_state()` → `pm_core/streams/guide/setup.py`
    - Reads project.yaml + first plan file, classifies project into a setup state, returns context dict.
    - *Becomes GuideSetupStream's state-detection hook. Consumes store (stays) + plan_parser (stays) + graph (stays); migration is straightforward.*
- **MOVES**: `run_non_interactive_step()` → `pm_core/streams/guide/setup.py`
    - Shells out to `pm plan load` when state==has_plan_prs.
    - *In v2, the stream's non-interactive branch should call into PlanStreamSupervisor / the equivalent Stream rather than subprocess'ing the CLI. Worth flagging as a small cleanup during migration.*
- **MOVES**: `_beginner_mode_guide_section()` → `pm_core/streams/guide/setup.py`
    - Renders a beginner-mode fragment based on global setting state.
    - *Lives in the GuideSetupSystemPrompt InputType. Reads global settings via paths.py (stays).*
- **MOVES**: `build_setup_prompt()` → `pm_core/streams/guide/setup.py`
    - Large multi-section prompt builder for the setup workflow.
    - *Becomes the typed InputType class for GuideSetupStream. Imports of prompt_gen.tui_section get replaced by pm_core/prompts/_shared.tui_section per v2.*
- **MOVES**: `build_assist_prompt()` → `pm_core/streams/guide/assist.py`
    - Builds the 'help user decide next step' prompt with lifecycle overview, plan summary, and assessment task.
    - *Becomes the typed InputType class for GuideAssistStream (pm_core/streams/guide/assist.py). Same tui_section import migration applies.*
- **STAYS**: `notes_block / notes.notes_section integration` → `pm_core/notes.py`
    - Both prompts append a notes block via notes.notes_section(root).
    - *Per v2 'Stays' list, pm_core/notes.py stays; prompt builders just consume it. In v2 this could alternatively be sourced through NotesSectionArtifact under sensorium/artifact/notes.py.*
- **MOVES**: `tui_section import from pm_core.prompt_gen` → `pm_core/streams/_shared_prompts.py`
    - Both prompts inline-import tui_section to render the TUI keybinding block.
    - *prompt_gen.py is on the 'Deleted' list; tui_section is explicitly named as a fragment in prompts/_shared.py. Both call sites update.*

  *Cross-cutting:* guide.py is imported by session startup and TUI (needs_guide). Their migration to import from pm_core/streams/guide/setup.py is blocked until guide.py moves. Also depends on pm_core.prompt_gen.tui_section — guide.py's migration is coupled with the prompt_gen.py deletion / _shared.py extraction. The `run_non_interactive_step` subprocess call to `pm plan load` becomes awkward in the new Stream/Supervisor model — worth replacing with a direct PlanStreamSupervisor invocation during migration.

#### `pm_core/hook_install.py`
*Installs pm's Claude Code hooks into ~/.claude/settings.json (Notification[idle_prompt], Notification[permission_prompt], Stop), copies a standalone hook_receiver.py to ~/.pm/hook_receiver.py, handles host/container path translation via PM_HOST_HOME, detects foreign hook conflicts, sweeps stale event files, and is idempotent. Provides HookConflictError, hooks_already_installed(), ensure_hooks_installed().*

- **MOVES**: `Install/merge Claude Code hook entries into ~/.claude/settings.json (ensure_hooks_installed, _desired_hooks, hooks_already_installed)` → `pm_core/sensorium/artifact/claude_hooks.py` (`ClaudeHooksArtifact`) for the **settings.json mutation itself** + `pm_core/runtime/tmux_host.py` for the **hook-config policy** (`_desired_hooks` — which entries pm wants installed, the command string pointing at hook_entry.py).
    - *Revised per locking-story consolidation. Writing to `~/.claude/settings.json` is an out-of-repo file mutation that pm performs on the user's behalf — exactly the sensorium HostCodeOverride pattern. `ClaudeHooksArtifact.apply(merge_pm_entries(...))` gives schema validation + change-notify so a `RuntimePlugin` can re-register if the user externally edits their hooks. The decision of WHICH hooks pm wants stays in `TmuxHostRuntime` (it knows about hook_entry.py and the commands it emits); the file write goes through the Artifact.*
- **MOVES**: `Standalone hook receiver script that Claude Code's hook command invokes (the command string and the on-disk receiver file)` → `pm_core/runtime/hook_entry.py`
    - *v2 explicitly names runtime/hook_entry.py as the shippable CLI invoked by Claude Code hooks; _hook_command_for() and _install_receiver() collapse into hook_entry.py being the installed target (and TmuxHostRuntime emitting the command string that points at it).*
- **MOVES**: `Detect foreign / pre-existing non-pm hooks and raise HookConflictError (_detect_foreign_hooks, _entry_is_pm, HookConflictError)` → `pm_core/runtime/tmux_host.py`
    - *Conflict detection is part of TmuxHostRuntime's host-side setup; HookConflictError lives alongside it (no dedicated v2 home, but it's a runtime-internal concern).*
- **MOVES**: `Host/container home-path translation via PM_HOST_HOME (_host_home, _settings_path, _hooks_base, _receiver_path)` → `pm_core/runtime/tmux_container.py`
    - *PM_HOST_HOME is exported by container.py (which v2 folds into TmuxContainerRuntime). The host-path translation helpers split: path-resolution helpers consumed by both TmuxHostRuntime and TmuxContainerRuntime; could plausibly live in a tiny shared helper but v2 doesn't name one — internal to the two runtime modules.*
- **MOVES**: `Sweep stale ~/.pm/hooks/*.json event files (_sweep_stale_events, _STALE_SECONDS)` → `pm_core/runtime/hook_entry.py`
    - *Stale-event cleanup is part of the hook-receiver lifecycle; belongs with hook_entry.py (or invoked by TmuxHostRuntime startup). Could also be argued as a Supervisor teardown concern but it's keyed to the on-disk hook protocol, so hook_entry.py is the natural home.*
- **DELETES**: `Module-level back-compat constants (_SETTINGS_PATH, _HOOKS_BASE, RECEIVER_PATH)`
    - *These are explicitly back-compat shims for importers/tests; with hook_install.py deleted, callers migrate to the new runtime APIs and the constants vanish.*

  *Not in plan:*
  - HookConflictError surfacing to the user (currently raised at install time and presumably caught by a top-level CLI handler): Keep HookConflictError defined inside pm_core/runtime/tmux_host.py and document that TmuxHostRuntime.__init__ (or a setup() capability call) may raise it; the CLI/bootstrap entry that constructs the runtime handles the user message. No new plan file required.
  - Foreign-hook detection acting as a safety boundary between pm and user-managed Claude Code settings: now modeled by `ClaudeHooksArtifact` (sensorium/artifact/claude_hooks.py — added per locking-story consolidation). The Artifact's apply() performs the merge + conflict detection; `HookConflictError` raises from the Artifact when external (non-pm) hook entries are present. `TmuxHostRuntime` consumes the Artifact rather than touching settings.json directly.

  *Cross-cutting:* hook_install.py is currently invoked at pm startup (likely from bootstrap/wrapper or CLI entry); the call site needs to move to TmuxHostRuntime.__init__ / setup (or a one-shot host-bootstrap step) before this file can be deleted. It also depends on pm_core.hook_receiver (which v2 also deletes — folded into runtime/hook_entry.py), so the two must be migrated together. Container.py (→ TmuxContainerRuntime) sets PM_HOST_HOME and bind-mounts ~/.claude + the receiver path; that contract must be preserved across the runtime/tmux_host.py ↔ runtime/tmux_container.py split.

#### `pm_core/hook_receiver.py`
*Tiny CLI script invoked by Claude Code hooks. Reads stdin JSON + event-type argv, writes an atomic per-session event record to ~/.pm/hooks/{session_id}.json so the host pm process can observe turn boundaries (idle_prompt, permission_prompt, Stop) without polling.*

- **MOVES**: `CLI entrypoint invoked by Claude Code hooks (main + __main__)` → `pm_core/runtime/hook_entry.py`
    - *v2 explicitly names runtime/hook_entry.py as 'shippable CLI invoked by Claude Code hooks; forwards events to RuntimePlugin'. Direct replacement.*
- **MOVES**: `Stdin JSON payload parsing + event_type dispatch (idle_prompt/permission_prompt/Stop)` → `pm_core/runtime/hook_entry.py`
    - *Parsing logic moves with the entry point; semantics get re-expressed as Emissions forwarded into the owning RuntimePlugin (TmuxHostRuntime/TmuxContainerRuntime).*
- **DELETES**: `Atomic per-session-id file write to ~/.pm/hooks/{session_id}.json`
    - *Flat-dir signaling is replaced by EmissionLog (pm_core/agent/log.py) + StreamTranscript. The hook entry forwards events directly to the RuntimePlugin/EmissionLog rather than writing a separate sidecar file. Listed in v2 deletes ('hook_receiver.py → runtime/hook_entry.py + TmuxHostRuntime internals').*
- **MOVES**: `Container-vs-host path agreement via flat ~/.pm/hooks/ dir` → `pm_core/runtime/tmux_container.py`
    - *Cross-boundary delivery from inside a container becomes a TmuxContainerRuntime concern (and/or push_proxy.py); hook_entry.py running inside the container forwards via the runtime's transport rather than a shared host dir.*
- **MOVES**: `Never-block-Claude error swallowing` → `pm_core/runtime/hook_entry.py`
    - *Defensive top-level try/except stays as a property of the hook CLI.*

  *Cross-cutting:* Readers of ~/.pm/hooks/{session_id}.json (pane_idle.py and any TUI/loop code that polls turn boundaries) must migrate at the same time. v2 deletes pane_idle.py ('runtime-internal detail moves into TmuxHostRuntime'), so TmuxHostRuntime must consume hook_entry.py events directly (in-process callback or local socket) rather than via the on-disk sidecar. hook_install.py (also listed as deleted) installs the settings.json entry pointing at this script; its replacement must point at the new hook_entry.py console script (likely via bootstrap.py). Container case: TmuxContainerRuntime + push_proxy.py need a forwarding path from in-container hook_entry.py back to the host Mind.

#### `pm_core/plans/review.py`
*Post-step review logic for `pm plan` commands. Holds (a) per-step review prompt templates (plan-add/breakdown/deps/load/import/review), (b) a background `claude -p` launcher that parses PASS/NEEDS_FIX verdicts and writes a review file, (c) tmux background-pane reporting of the verdict, (d) reviews-directory I/O (`reviews/*.txt` write/list/parse), and (e) a fix-prompt builder for the `-fix` variant invocation.*

- **MOVES**: `REVIEW_PROMPTS templates per plan step` → `pm_core/streams/plan/review.py`
    - *The plan-add/breakdown/deps/load/import/review check prompts become typed InputType prompt classes; each step's prompt lives in the corresponding pm_core/prompts/plan/{add,breakdown,deps,import_,fix,review}.py file. The dict itself dissolves.*
- **MOVES**: `build_fix_prompt — fix-variant prompt builder` → `pm_core/streams/plan/fix.py`
    - *Becomes the InputType prompt for streams/plan/fix.py.*
- **MOVES**: `review_step — launches background claude review, parses verdict, writes file, reports via tmux` → `pm_core/streams/plan/review.py`
    - *Becomes a PlanReviewStream (or post-step ReviewStream variant). The claude_launcher.launch_claude_print_background call is replaced by stream.run on a RuntimePlugin (likely TmuxHostRuntime or RawApiRuntime). Verdict parsing becomes an Emission with ALLOWED_VERDICTS classvar on the InputType.*
- **MOVES**: `_parse_verdict — extract PASS/NEEDS_FIX from claude output` → `pm_core/streams/plan/review.py`
    - *Folds into ReviewStream verdict handling; pattern aligns with ALLOWED_VERDICTS classvar in pm_core/prompts/protocol.py.*
- **MOVES**: `tmux background-pane PASS/NEEDS_FIX summary rendering` → `pm_core/runtime/tmux_host.py`
    - *Background-pane verdict notification is runtime-internal; could alternatively land in pm_core/tui/ as a transient notification widget. The split_pane_background call is TmuxHostRuntime territory.*
- **MOVES**: `_write_review_file + _reviews_dir — reviews/*.txt file write` → `pm_core/sensorium/artifact/review_file.py`
    - *Becomes ReviewFileArtifact (already listed in v2 sensorium tree). Write/read/parse all go on the artifact class.*
- **MOVES**: `list_pending_reviews — scan reviews dir for NEEDS_FIX` → `pm_core/sensorium/artifact/review_file.py`
    - *Class-level / registry method on ReviewFileArtifact (e.g. ReviewFileArtifact.list_pending(root)).*
- **MOVES**: `parse_review_file — parse Step/Status/findings/fix_cmd sections` → `pm_core/sensorium/artifact/review_file.py`
    - *Becomes ReviewFileArtifact.read() / structured parse on the artifact.*

  *Cross-cutting:* Imports pm_core.tmux, pm_core.claude_launcher, pm_core.shell — all three are in the STAYS list, so dependencies are stable. Callers (likely pm_core/cli/ plan command group and pm_core/plans/* siblings — plan-add/breakdown/import/deps/load/review/fix) currently call review_step(step_name, ..., REVIEW_PROMPTS[step]) at the tail of each plan subcommand; their migration is gated on this file's migration into streams/plan/*.py + ReviewFileArtifact. The `reviews/` directory under pm_root is a sensorium-owned location; ReviewFileArtifact needs a path resolution policy (PathView / PathService). The `pm plan fix --review <path>` CLI surface is referenced in the written file content — must remain in the CLI surface (cli/ stays) and route to streams/plan/fix.py.

#### `pm_core/pr_utils.py`
*Defines the PRStatus Literal type, a VALID_PR_STATES set, and two helpers (is_valid_pr_status, normalize_pr_status) for validating/normalizing PR status strings.*

- **MOVES**: `PRStatus Literal type definition` → `pm_core/mind/lifecycle.py`
    - The PRStatus Literal (pending|in_progress|in_review|qa|sign_off|merged|closed) defining the valid PR lifecycle states.
    - *v2 plan explicitly calls out: 'pr_utils.py (PRStatus moves to lifecycle.py)'. Likely promoted to a StrEnum alongside LifecycleState.*
- **MOVES**: `VALID_PR_STATES set` → `pm_core/mind/lifecycle.py`
- **NEW (co-located with PRStatus)**: `TERMINAL_PR_STATUSES: frozenset[PRStatus]` + `PRStatus.is_terminal()` classmethod. Replaces `cli/session.py:953 _TERMINAL_STATUSES` plus all inline `{"merged","closed"}` checks in `qa_loop.py`, `home_window/pr_list.py`. Adds `blocked` enum member (today only present in `cli/helpers.py:262-271 PR_STATUS_ICONS`).
- **NEW (co-located with PRStatus)**: `PR_STATUS_DISPLAY: dict[PRStatus, PRStatusDisplay]` table with per-status `glyph` (terminal-safe unicode), `emoji` (rich CLI), `fg` / `bg` (Textual styles), `sort_priority` (tree ordering). One canonical source consumed by `cli/__init__.py` (pm status emoji), `cli/helpers.py` (PR_STATUS_ICONS), `graph.py` (status emoji), `tech_tree.py` (STATUS_ICONS / STATUS_STYLES / STATUS_BG), `tree_layout.py` (status_priority). Module-load assert: `set(PR_STATUS_DISPLAY) == set(PRStatus)`.
- **NEW (co-located with PRStatus)**: `STATUS_FILTER_CYCLE = (None, *PRStatus)` — derived from enum order. Replaces `tech_tree.py:110` hardcoded list and `cli/__init__.py:411` iteration. Invariant test asserts the TUI's effective filter cycle matches.
    - Set of valid PR status strings used for membership checks.
    - *Becomes implicit via StrEnum membership / __members__ on the lifecycle enum; the explicit set constant goes away.*
- **MOVES**: `is_valid_pr_status() helper` → `pm_core/mind/lifecycle.py`
    - Boolean check whether a string is a valid PR status.
    - *Becomes a classmethod on the lifecycle/PRStatus enum (e.g. PRStatus.is_valid(s)) or callers switch to enum membership check.*
- **MOVES**: `normalize_pr_status() helper` → `pm_core/mind/lifecycle.py`
    - Validate and coerce string to PRStatus, raising ValueError on invalid input with a sorted list of valid states.
    - *Becomes PRStatus(value) constructor (StrEnum) or a classmethod that wraps it with the friendlier error message.*

  *Cross-cutting:* Any module that currently imports PRStatus / is_valid_pr_status / normalize_pr_status from pm_core.pr_utils (likely store.py, backend.py, CLI, TUI panels) will need its import updated to pm_core.agent.lifecycle. Migration of pr_utils.py itself is trivial but is a blocker for cleanly removing the legacy module; recommend an import re-export shim during transition. The lifecycle.py file already plans to host LifecycleState (StrEnum) and ControlOwner, so collocating PRStatus there fits naturally.

#### `pm_core/prompt_gen.py`
*Monolithic prompt generator producing Claude system/user prompts for all PR work session roles (impl, review, signoff, merge, watcher, discovery supervisor, bug-fix, improvement-fix, review-loop, QA planner/interactive/child/standalone, watcher-review). Also contains many shared text fragments (TUI section, PR-notes handoff, beginner addendum, remote/base-branch sync tips, auto-cleanup addendum, signoff QA scenarios block, review-loop addendum).*

- **MOVES**: `tui_section` → `pm_core/streams/_shared_prompts.py`
    - Shared fragment describing TUI session keybindings
- **MOVES**: `_pr_notes_handoff_block / _format_pr_notes` → `pm_core/streams/_shared_prompts.py`
    - Shared fragment rendering PR notes handoff context
- **MOVES**: `_beginner_addendum` → `pm_core/streams/_shared_prompts.py`
    - Shared beginner-friendly addendum text
- **MOVES**: `_remote_sync_tip / _base_branch_sync_tip` → `pm_core/streams/_shared_prompts.py`
    - Shared git-sync tips fragments
- **MOVES**: `_auto_cleanup_addendum` → `pm_core/streams/_shared_prompts.py`
    - Shared cleanup-on-exit text fragment
- **MOVES**: `_review_loop_addendum` → `pm_core/streams/_shared_prompts.py`
    - Iteration-aware addendum for review-loop prompts
- **MOVES**: `_signoff_qa_scenarios_block` → `pm_core/streams/_shared_prompts.py`
    - Block listing QA scenarios for signoff context
    - *Explicitly enumerated in v2 _shared.py contents*
- **MOVES**: `generate_prompt (impl)` → `pm_core/streams/impl_system.py`
    - Implementation work session prompt builder
- **MOVES**: `generate_review_prompt` → `pm_core/streams/review_system.py`
    - Review session prompt builder
- **MOVES**: `generate_review_loop_prompt` → `pm_core/streams/review_system.py`
    - Thin wrapper composing review prompt + loop addendum
- **MOVES**: `generate_signoff_prompt` → `pm_core/streams/signoff.py`
    - Signoff session prompt builder
- **MISSING_FROM_PLAN**: `generate_merge_prompt`
    - Merge / merge-conflict resolution prompt builder
    - *v2 lists streams/merge.py (MergeStream + MergeConflictResolverStream) but no pm_core/prompts/merge.py is enumerated. Propose adding pm_core/prompts/merge.py (or merge_system.py).*
- **MOVES**: `generate_watcher_prompt` → `pm_core/streams/watcher/auto_start.py`
    - Watcher session prompt (general auto-start watcher)
- **MISSING_FROM_PLAN**: `generate_discovery_supervisor_prompt`
    - Discovery supervisor (project-discovery watcher) prompt
    - *streams/watchers/discovery_supervisor.py exists but no matching prompts/watcher/discovery_supervisor.py. Propose adding pm_core/prompts/watcher/discovery_supervisor.py.*
- **MOVES**: `generate_bug_fix_impl_prompt` → `pm_core/streams/watcher/bug_fix.py`
    - Bug-fix impl prompt builder
- **MOVES**: `generate_improvement_fix_impl_prompt` → `pm_core/streams/watcher/improvement_fix.py`
    - Improvement-fix impl prompt builder
- **MOVES**: `generate_qa_planner_prompt` → `pm_core/streams/qa_planning.py`
    - QA planner session prompt
- **MOVES**: `generate_qa_interactive_prompt` → `pm_core/streams/qa_scenario.py`
    - QA interactive (scenario concretize/run) prompt
    - *Could also split between qa_scenario.py and qa_concretize.py depending on intent*
- **MOVES**: `generate_qa_child_prompt` → `pm_core/streams/qa_verification.py`
    - QA child (verification) session prompt
- **MOVES**: `generate_standalone_qa_prompt` → `pm_core/streams/qa_authoring.py`
    - Standalone QA prompt (library-driven QA authoring/run)
- **MOVES**: `generate_watcher_review_prompt` → `pm_core/streams/watcher/watcher_review.py`
    - Watcher-review prompt builder

  *Not in plan:*
  - Merge prompt generation (generate_merge_prompt, ~175 LOC): Add pm_core/prompts/merge.py (or merge_system.py) holding the MergeInputType for both MergeStream and MergeConflictResolverStream.
  - Discovery supervisor prompt (generate_discovery_supervisor_prompt, ~140 LOC): Add pm_core/prompts/watcher/discovery_supervisor.py.

  *Cross-cutting:* prompt_gen.py is consumed by virtually every legacy session-launch path (review_loop.py, qa_loop.py, watcher_*.py, signoff.py, container.py, bridge.py, claude_launcher.py call sites). Its removal must be sequenced with the Stream subclass migration that wires each Stream to its typed InputType in pm_core/prompts/. The _shared.py fragments are reused across at least 8 prompt builders, so _shared.py needs to land first (or simultaneously) with the per-role prompt files. Also note: prompt_gen.py reads PR data dicts from project.yaml (via store) and PR notes (via notes.py) — those reads should be re-expressed as ProjectYamlArtifact + NotesSectionArtifact reads when the InputType classes are constructed.

#### `pm_core/qa_authoring.py`
*Small (73 LOC) helper module that loads a packaged docs/qa_library.md reference and builds a Claude prompt to interview the user for authoring a new QA library file (instructions / regression / artifacts).*

- **MOVES**: `build_authoring_prompt — Claude prompt assembly for QA library authoring (per category: instructions/regression/artifacts), including category blurbs and label dispatch` → `pm_core/streams/qa_authoring.py`
    - *v2 explicitly lists prompts/qa_authoring.py; the per-category blurb/label tables and the prompt template string belong here as a typed InputType class (likely with category as a field). Also explicitly named in the Deleted note: 'qa_authoring.py folds into QaAuthorStream' — the prompt half lands in prompts/qa_authoring.py and the orchestration half in streams/qa_author.py.*
- **MOVES**: `qa_library_doc() — load packaged pm_core/docs/qa_library.md reference text` → `pm_core/sensorium/artifact/qa_library/instructions.py`
    - *Reading the packaged qa_library.md reference doc is a sensorium concern (it documents the QaLibraryArtifact schema). Most natural home is alongside the QaLibraryArtifact subclass tree under sensorium/artifact/qa_library/ — could equally live as a module-level helper in any of the four qa_library/*.py files, or be inlined into prompts/qa_authoring.py if the prompt is the only consumer. Slightly UNCLEAR which qa_library/*.py file owns it.*
- **MOVES**: `Category dispatch (instructions/regression/artifacts → label + blurb) and ValueError on unknown category` → `pm_core/streams/qa_authoring.py`
    - *Moves with build_authoring_prompt; likely encoded as an enum/Literal field on the QaAuthoringInput InputType.*
- **MOVES**: `Driving the authoring session (writing the target file, interviewing the user) — implied caller responsibility` → `pm_core/streams/qa_author.py`
    - *v2 lists streams/qa_author.py and the deletion note 'qa_authoring.py folds into QaAuthorStream'. The Stream subclass owns the session lifecycle; this file only built the prompt, but the surrounding orchestration (CLI command currently calling build_authoring_prompt) moves into QaAuthorStream.*

  *Not in plan:*
  - Location of the packaged qa_library.md reference doc loader: Add a small qa_library_doc() helper in pm_core/sensorium/artifact/qa_library/__init__.py (or instructions.py) so all four QaLibrary artifact subclasses can reference one schema doc; have prompts/qa_authoring.py import from there.

  *Cross-cutting:* Depends on pm_core/docs/qa_library.md being packaged with pm_core — that doc is not in the v2 inventory but presumably stays as a static resource. Callers (likely under pm_core/cli/ — a `pm qa author` command) will need to switch from calling build_authoring_prompt to instantiating a QaAuthorStream with a QaAuthoringInput; CLI migration is blocked on streams/qa_author.py + prompts/qa_authoring.py landing.

#### `pm_core/qa_finalize_prompt.py`
*Single-function prompt builder (build_qa_finalize_prompt) that generates the Claude prompt for the post-QA finalize pane. It formats scenario worktree status, PR context, and instructions for a finalize agent that pushes scenario captures and fast-forwards the PR workdir to origin, emitting FINALIZE_DONE or FINALIZE_BLOCKED.*

- **MOVES**: `build_qa_finalize_prompt` → `pm_core/streams/qa_finalize.py`
    - Builds the QA finalize Claude prompt with scenario list, push/pull goals, and FINALIZE_DONE/FINALIZE_BLOCKED verdict protocol.
    - *Becomes a typed InputType class under pm_core/prompts/qa_finalize.py per v2's 'qa_finalize_prompt.py extracted into typed InputType classes' rule. ALLOWED_VERDICTS = {FINALIZE_DONE, FINALIZE_BLOCKED}.*
- **MOVES**: `Scenario worktree formatting helper (inline)` → `pm_core/streams/qa_finalize.py`
    - Inline rendering of (scenario_index, verdict, worktree_path) tuples into bullet lines.
    - *Stays inside the InputType class; may share patterns with prompts/_shared.py if other QA prompts render scenario lists similarly.*
- **MOVES**: `Finalize verdict protocol (FINALIZE_DONE / FINALIZE_BLOCKED)` → `pm_core/streams/qa_finalize.py`
    - Defines the two terminal tokens the finalize agent must emit.
    - *Encoded as ALLOWED_VERDICTS classvar on the QaFinalizePrompt InputType, consumed by QaFinalizeStream (streams/qa_finalize.py).*

  *Cross-cutting:* Consumed today by qa_loop.py (which spawns the finalize pane). qa_loop.py is slated for deletion / rewrite into Qa*Stream + QaSupervisor; the finalize prompt's new home (prompts/qa_finalize.py) is paired with streams/qa_finalize.py. Migration of qa_loop.py's finalize-pane spawning into QaFinalizeStream must land alongside this move. The prompt also implicitly relies on the push-proxy (runtime/push_proxy.py) being healthy and on the PR workdir being a WorkdirRegistry entry (sensorium/workdirs.py).

#### `pm_core/qa_instructions.py`
*Manages the four-category QA library under pm/qa/ (instructions, regression, mocks, artifacts): directory helpers, YAML-frontmatter parsing, listing/single-item access, fuzzy ref resolution for planner output, and two prompt-rendering helpers (instruction summary + mocks section).*

- **MOVES**: `qa_dir/instructions_dir/regression_dir/mocks_dir/artifacts_dir directory helpers` → `pm_core/sensorium/artifact/qa_library/instructions.py (and siblings mocks.py/regression.py/artifacts.py)`
    - *Each path becomes the on-disk root of the corresponding QaLibraryArtifact subclass; the mkdir-on-access semantics move into the Artifact's __init__ / resolve_link.*
- **MOVES**: `_parse_frontmatter (YAML frontmatter splitter)` → `pm_core/sensorium/artifact/qa_library/instructions.py`
    - *Shared utility — should live on a small base in pm_core/sensorium/artifact/qa_library/__init__ or be reused from a generic frontmatter helper. Plan doesn't name a shared frontmatter module — see MISSING.*
- **MOVES**: `_list_dir + list_instructions/list_regression_tests/list_mocks/list_artifacts/list_all` → `pm_core/sensorium/artifact/qa_library/instructions.py`
    - *Become .list() / .items() methods on each QaLibraryArtifact subclass; list_all becomes a small aggregator either on the package __init__ or a parent QaLibraryArtifact.*
- **MOVES**: `resolve_instruction_ref (fuzzy planner-output -> filename resolution)` → `pm_core/sensorium/artifact/qa_library/instructions.py`
    - *Lives as classmethod on QaInstructionsArtifact (cross-searches regression + artifacts siblings).*
- **MOVES**: `get_instruction / get_mock (single-item load with body)` → `pm_core/sensorium/artifact/qa_library/instructions.py`
    - *Become .read(id) / .get(id) on the corresponding QaLibraryArtifact subclass.*
- **MOVES**: `instruction_summary_for_prompt (planner prompt fragment)` → `pm_core/streams/_shared_prompts.py`
    - *Cross-prompt fragment consumed by prompts/qa_planning.py and prompts/qa_concretize.py; v2 explicitly lists _shared.py as the home for cross-prompt fragments. May call into QaLibraryArtifact for data.*
- **MOVES**: `mocks_for_prompt (QA scenario prompt fragment)` → `pm_core/streams/_shared_prompts.py`
    - *Cross-prompt fragment; v2 names signoff_qa_scenarios_block in _shared.py, this is the same shape. Reads QaMocksArtifact bodies.*

  *Not in plan:*
  - Shared YAML-frontmatter parser (_parse_frontmatter): Add pm_core/sensorium/artifact/_frontmatter.py (small helper) or put the splitter as a static method on the Artifact base in pm_core/sensorium/artifact/base.py. Safer to add as a tiny shared module so non-Artifact callers (CLI) can use it too.
  - Convention that artifact captures land at ~/.pm/sessions/<tag>/captures/<pr-id>/ resolved via `pm qa captures-path <pr-id>`: Confirm `pm qa captures-path` CLI is covered by sensorium/captures.py + pm_core/cli/ stays; document that QaArtifactsArtifact recipes resolve capture paths via CaptureService. No new file needed if pm_core/cli/ retains the qa command group as v2 indicates.

  *Cross-cutting:* Consumed by qa_loop.py (planning/concretize/finalize prompts) and qa_authoring.py — those become Qa*Stream + prompts/qa_*.py, which will read these artifacts via the new QaLibraryArtifact subclasses. The fuzzy resolve_instruction_ref is used during planner-output validation (qa_planning verdict parsing) — its new home is on the QaInstructionsArtifact (or a small resolver helper alongside it). The two *_for_prompt helpers are prompt-fragment producers; they should live with prompts/_shared.py or as methods on the QaLibraryArtifact so prompts/qa_planning.py and prompts/qa_scenario.py can call them. CLI surface `pm qa list/show/captures-path` (under pm_core/cli/) currently imports these functions — those CLI commands will need to be updated to go through the new Artifact API.

#### `pm_core/qa_loop.py`
*A 3588-LOC monolith implementing the entire QA loop for a PR: planning (asking Claude to generate QA scenarios), parsing scenarios, generating mock fixtures, concretizing scenarios into runnable instructions, launching scenarios in parallel via either tmux panes or Docker containers, polling for verdicts, running verification passes, running finalization, persisting resume state, and writing status files. Roughly equal mix of (a) prompt construction, (b) plan/output parsing, (c) workdir / clone / tmux window / container orchestration, (d) verdict polling state machine, (e) resume-state serialization, (f) artifact/instruction file installation. v2 explicitly says "qa_loop.py (rewritten as Qa*Stream + QaSupervisor)" — so the file as a unit is deleted; its responsibilities scatter.*

- **MOVES**: `Config knobs: _get_max_scenarios, _get_verification_max_retries, _get_verdict_reminder_timeout, _is_verification_enabled` → `pm_core/mind/policy.py`
    - *These are policy thresholds (max_iterations, consecutive_pass_threshold analogue) — fold into StreamPolicy/BudgetPolicy or a QaPolicy subclass declared on QaSupervisor.*
- **MOVES**: `_tail_has_marker_on_own_line (verdict marker detection on transcript tail)` → `pm_core/mind/transcript.py`
    - *Generic transcript-tail predicate belongs on StreamTranscript as a utility (or a small helper consumed by the verdict-polling Stream).*
- **MOVES**: `QAScenario dataclass` → `pm_core/payloads/qa_scenario_ref.py`
    - *v2 already lists qa_scenario_ref.py as the typed artifact.*
- **MOVES**: `NewMockRequest dataclass` → `pm_core/payloads/mock_spec.py`
    - *v2 lists mock_spec.py.*
- **DELETES**: `QALoopState (in-memory orchestration state across scenarios)`
    - *Replaced by QaSupervisor + per-scenario Stream instances tracked via StreamRecord (supervisors/protocol.py) + EmissionLog. No single 'loop state' object survives.*
- **MOVES**: `create_qa_workdir / create_scenario_workdir / _setup_clone_override` → `pm_core/sensorium/workdirs.py`
    - *Workdir creation + clone setup is exactly what WorkdirRegistry+Workdir is for. Per-scenario workdir becomes a child Workdir leased by ScenarioStream.*
- **MOVES**: `_scenario_transcript_path / _next_scenario_offset` → `pm_core/mind/transcript.py`
    - *StreamTranscript owns per-stream file naming; offset computation becomes part of how QaSupervisor names its child scenario streams.*
- **MOVES**: `_compute_qa_window_name / _scenario_window_name / _cleanup_stale_scenario_windows` → `pm_core/runtime/tmux_host.py`
    - *tmux-window naming + stale-window cleanup is internal to TmuxHostRuntime (v2 says pane_idle/window mgmt folds into TmuxHostRuntime). Window-key resource ownership shows up as TmuxWindowKey leases in sensorium/leases.py.*
- **MOVES**: `_run_qa_finalize_pane (launching the finalize Claude session)` → `pm_core/streams/qa_finalize.py`
    - *Becomes QaFinalizeStream.run with prompt built from prompts/qa_finalize.py.*
- **DELETES**: `_write_status_file (legacy qa_status.json writer)`
    - *v2 explicitly: 'qa_status.py becomes watchdog/tui.py + TmuxHostRuntime internals'. Status is derived from EmissionLog now; the status file goes away.*
- **DELETES**: `Resume state: _resume_file_path, _scenario_to_resume_dict, _scenario_from_resume_dict, _write_resume_file, _load_resume_file, clear_resume_file, build_resume_state, resume_qa_sync, resume_qa_background`
    - *v2 dropped snapshot/snapshot_resume from RuntimePlugin and Stream. Resume is replaced by EmissionLog idempotent replay + LoopMode.continue_existing on QaSupervisor restart. The bespoke JSON resume file is gone.*
- **MOVES**: `parse_qa_plan (parses Claude's QA plan markdown into QAScenario list)` → `pm_core/streams/qa_planning.py`
    - *Parsing the output of the planning prompt belongs in QaPlanningStream (postprocessing of its Emission to produce QaScenarioRef artifacts). Could alternately live next to the prompt in prompts/qa_planning.py if symmetric — but parsing is Stream-side.*
- **MOVES**: `parse_new_mocks_from_plan` → `pm_core/streams/qa_planning.py`
    - *Same as parse_qa_plan — output of planning Stream is QaScenarioRef + MockSpec artifacts.*
- **MOVES**: `_generate_new_mock / generate_new_mocks (run Claude to author each mock fixture)` → `pm_core/streams/qa_author.py`
    - *v2 lists qa_author.py / QaAuthorStream — and 'qa_authoring.py folds into QaAuthorStream'. Mock generation is an authoring task.*
- **MOVES**: `_resolve_qa_model (model selection for QA Claude sessions)` → `pm_core/model_config.py`
    - *model_config.py is listed as Stays — this is the natural home for per-role model resolution. The QA-specific dispatch becomes a helper there or a method on the QaSupervisor that consults model_config.*
- **MOVES**: `_build_concretization_prompt` → `pm_core/streams/qa_concretize.py`
    - *Already listed in v2.*
- **MOVES**: `_build_concretize_cmd / _concretize_scenario / _launch_scenario_0` → `pm_core/streams/qa_concretize.py`
    - *Concretization-as-a-Stream. The 'launch scenario 0' first-scenario distinction goes away — every scenario is just a QaConcretizeStream child.*
- **MOVES**: `_install_instruction_file / _install_artifact_files` → `pm_core/sensorium/artifact/qa_library/instructions.py`
    - *Writing instruction files into the QA library is exactly QaLibraryArtifact.apply(). v2 lists qa_library/{instructions.py, mocks.py, regression.py, artifacts.py}.*
- **MOVES**: `_write_scenario_capture_file` → `pm_core/sensorium/captures.py`
    - *CaptureBundle/CaptureService is the new home for capture-file writing (CaptureChannel on the emission side).*
- **MOVES**: `_persist_scenario_verdicts (writes verdicts back onto PR/branch)` → `pm_core/supervisors/pr_stream.py`
    - *Cross-scenario aggregation that updates PR state belongs to the PRStreamSupervisor (it owns QA streams under a PR). Alternative: project_yaml.py artifact if persistence is just yaml writes.*
- **MOVES**: `_launch_scenarios_in_tmux` → `pm_core/streams/qa_scenario.py`
    - *Becomes 'QaSupervisor spawns N QaScenarioStream instances with TmuxHostRuntime'. The launch mechanics belong in runtime/tmux_host.py; the orchestration of N parallel children belongs to the supervisor/QaSupervisor (no dedicated file in v2 — likely pr_stream.py owns this).*
- **MOVES**: `_launch_scenarios_in_containers` → `pm_core/runtime/tmux_container.py`
    - *Container-runtime variant of the launch — TmuxContainerRuntime absorbs container.py + per-PR Docker glue. Supervisor stays runtime-agnostic; it just picks the runtime.*
- **MOVES**: `_build_scenario_run_cmd` → `pm_core/runtime/tmux_host.py`
    - *Command construction for launching a Claude session in a tmux window is a TmuxHostRuntime / TmuxContainerRuntime internal.*
- **MOVES**: `_relaunch_scenario_window` → `pm_core/runtime/tmux_host.py`
    - *Window relaunch is runtime-internal — also overlaps with Stream.deliver_message + LoopMode.kill_restart semantics from agent/tags.py.*
- **MOVES**: `_poll_tmux_verdicts (long polling state machine reading transcripts, deciding pass/fail/retry/verify)` → `pm_core/streams/qa_verification.py`
    - *The verdict polling loop is the meat of the QA flow. Becomes (a) QaScenarioStream emitting verdict Emissions via tagged output detection inside TmuxHostRuntime, and (b) QaVerificationStream/QaSupervisor reacting via CallbackRegistry.wait_for. Split across qa_scenario.py + qa_verification.py + the supervisor.*
- **MOVES**: `_build_verification_prompt` → `pm_core/streams/qa_verification.py`
    - *Already in v2.*
- **MOVES**: `_extract_flagged_reason` → `pm_core/payloads/failure_reason.py`
    - *Parsing a flagged-reason string out of a transcript produces a FailureReason artifact payload.*
- **MOVES**: `_verify_single_scenario` → `pm_core/streams/qa_verification.py`
    - *One QaVerificationStream invocation per flagged scenario.*
- **MOVES**: `run_qa_sync (top-level orchestration: plan -> mocks -> launch -> poll -> verify -> finalize)` → `pm_core/supervisors/pr_stream.py`
    - *The whole sequence is a Supervisor's run() — PRStreamSupervisor coordinates QaPlanningStream, QaAuthorStream (mocks), QaConcretizeStream*, QaScenarioStream*, QaVerificationStream*, QaFinalizeStream. There is no QaSupervisor file in v2; it lives inside pr_stream.py.*
- **MOVES**: `_execute_and_finalize` → `pm_core/supervisors/pr_stream.py`
    - *Same — Supervisor-level sequencing.*
- **MOVES**: `start_qa_background / resume_qa_background (spawn QA loop in background process)` → `pm_core/cli/`
    - *Background spawn is a CLI concern (pm qa start). v2 says 'pm qa command groups change to delegate to Streams/Supervisors' — these CLI handlers stay in cli/ but become thin Supervisor.start() calls. Resume disappears (see Resume state row above).*

  *Not in plan:*
  - Per-scenario CLONE / git-worktree setup with a separate working clone (_setup_clone_override + create_scenario_workdir): Either (a) add pm_core/sensorium/workdirs.py:ScenarioWorkdir as a Workdir subclass that owns the clone-override file write, or (b) clarify in plan-sensorium that WorkdirRegistry.create_child(parent, key) handles this. Slight preference for explicit ScenarioWorkdir since the clone-override file is QA-specific.
  - Verdict-retry / verdict-reminder timeout loop (verdict_reminder_timeout sends a nudge into the pane if no verdict has been emitted within N seconds): Add a RemindOnGrace policy field to StreamPolicy (agent/policy.py): on grace expiry, deliver a templated reminder message via Stream.deliver_message and reset the timer. Document in plan-mind.
  - Stale tmux window cleanup across loop_ids (_cleanup_stale_scenario_windows scans existing windows from previous QA runs for the same PR and kills them): Either (a) make this a TmuxHostRuntime startup invariant ('on instantiate, reclaim windows matching attach_hint pattern owned by my mind_id'), or (b) add a sweep responsibility to PRStreamSupervisor.startup. Document in plan-mind under runtime/tmux_host.py.
  - Background daemonization of the whole QA loop (start_qa_background spawns a detached child process running run_qa_sync): Already partly addressed by 'pm qa command groups change to delegate to Streams/Supervisors' but plan should make explicit that CLI background spawn = 'start Mind daemon if not running, then call mind.stream(role=QaPlanningStream, ...)'. Tie to bootstrap.py.

  *Cross-cutting:* qa_loop.py is imported by: cli/qa commands, tui/qa_loop_ui.py (delegator per v2), watcher_manager.py (which invokes QA), and signoff.py (which gates on QA verdicts). Migration ordering: (1) sensorium/workdirs.py + qa_library artifacts must land first because the artifact-mediated writes replace _install_*; (2) prompts/qa_* files are easy first moves (pure string-builders) and unblock the Stream rewrites; (3) TmuxHostRuntime + TmuxContainerRuntime must absorb _launch_scenarios_in_* and _build_scenario_run_cmd before QaScenarioStream can be implemented; (4) PRStreamSupervisor sequencing is the last step. Also: _persist_scenario_verdicts writes into project.yaml — coordination needed with ProjectYamlArtifact migration. fake_claude.py (becoming FakeClaudeRuntime) is used by qa_loop tests; FakeClaudeRuntime must support the verdict-emission pattern before qa_loop tests can be ported.

#### `pm_core/qa_status.py`
*Standalone tmux-pane script that polls a qa_status.json file and renders a live ANSI dashboard of scenario verdicts. Supports interactive TTY mode (j/k navigation, Enter to switch tmux windows, q to quit) via raw termios input, plus a passive mode that just refreshes until overall verdict is set. Includes ANSI rendering helpers, terminal-size detection, escape-sequence key parsing, and a grouped-tmux-session resolver for window switching.*

- **MOVES**: `Live QA dashboard rendering (verdict table, spinner, progress, error block)` → `pm_core/watchdog/tui.py`
    - *v2 explicitly maps qa_status.py -> watchdog/tui.py + TmuxHostRuntime internals. The rendering loop becomes a TUI WatchdogPolicy that subscribes to ScenarioChannel/PRChannel emissions instead of polling JSON.*
- **DELETES**: `qa_status.json file polling / _load_status`
    - *Source of truth shifts from a JSON file on disk to EmissionLog + ScenarioChannel subscriptions. The JSON-file shape is replaced by streaming Emissions consumed by the watchdog.*
- **MOVES**: `Tmux window switching (_switch_to_window, _find_attached_session)` → `pm_core/tmux.py`
    - *Grouped-session resolution and select-window are foundational tmux substrate; v2 lists pm_core/tmux.py as staying. If not already there, this logic belongs alongside current_or_base_session. Invocation seam shifts to TmuxHostRuntime / pane_registry.*
- **MOVES**: `Raw termios keyboard input loop (_read_key, _run_interactive)` → `pm_core/watchdog/tui.py`
    - *Interactive navigation belongs in the TUI watchdog; alternatively absorbed by TmuxHostRuntime internals per v2 deletion note.*
- **DELETES**: `Passive refresh-until-done mode (_run_passive)`
    - *Replaced by Emission-driven updates; no need for a polling passive mode once watchdog consumes ScenarioChannel/lifecycle events.*
- **MOVES**: `ANSI helpers (_truncate, _pad_line, color constants, spinner frames)` → `pm_core/watchdog/tui.py`
    - *Could also live in a shared pm_core/tui helper, but v2 routes qa_status specifically to watchdog/tui.py.*
- **MOVES**: `Terminal size detection (_get_terminal_size)` → `pm_core/watchdog/tui.py`
    - *Trivial helper; folds into watchdog TUI module.*
- **DELETES**: `CLI entry point (__main__ + main(status_path, session))`
    - *The standalone-script invocation pattern is replaced: TmuxHostRuntime launches the watchdog pane, and the watchdog talks to Mind via Channels rather than via JSON-file + sys.argv.*

  *Cross-cutting:* qa_status.json is written by qa_loop.py / signoff.py today; both are slated for deletion / rewrite as Qa*Stream + SignoffStream. The watchdog/tui.py target depends on ScenarioChannel + lifecycle emissions being defined first (pm_core/agent/channels.py, lifecycle.py). Anything that currently spawns this script via subprocess (likely qa_loop.py and possibly app.py / pane launcher) is blocked until TmuxHostRuntime owns the pane-launch seam. _find_attached_session duplicates pm_core.tmux.current_or_base_session — consolidation into tmux.py is a prerequisite.

#### `pm_core/regression_prompts.py`
*Assembles the prompt handed to Claude by `pm qa regression`: session context (tmux session/pane), captures path guidance, the free-form test body, and an optional filing-findings addendum directing Claude to file bugs/improvements as PRs rather than fix in-place.*

- **MOVES**: `build_regression_test_prompt — top-level assembly` → `pm_core/streams/regression/bug_reproduce.py`
    - *Becomes a typed InputType class (per v2 prompts/ pattern) producing the regression-test prompt; explicit listing under prompts/regression/{bug_reproduce.py, impl_fix.py}.*
- **MOVES**: `_FILING_ADDENDUM (file bugs/improvements as PRs, not in-place fixes)` → `pm_core/streams/_shared_prompts.py`
    - *v2 explicitly lists 'filing_addendum' as a cross-prompt fragment in prompts/_shared.py.*
- **MOVES**: `Session Context block (tmux session/pane, pm tui view/send tips)` → `pm_core/streams/_shared_prompts.py`
    - *Matches v2's 'tui_section' shared fragment; reused by signoff/QA prompts likely.*
- **MOVES**: `Captures block (paths under ~/.pm/sessions/<tag>/captures/regression/, not git-tracked)` → `pm_core/streams/regression/bug_reproduce.py`
    - *Regression-specific captures guidance; could partially share with CaptureService/captures.py docs but the prose lives with the prompt. CaptureBundle/CaptureService in sensorium/captures.py is the runtime counterpart.*

  *Cross-cutting:* Called from pm_core/cli/tui.py (per module docstring) — that call site needs to switch to instantiating the new InputType under prompts/regression/. The QaRegressionStream in streams/qa_regression.py will own invocation. Captures path conventions duplicate knowledge held by sensorium/captures.py (CaptureBundle/CaptureService) and `pm qa captures-path` — keep the prose in sync when CaptureService formalizes path layout.

#### `pm_core/review/__init__.py`
*Package init for adversarial-review walker's markdown format primitives — re-exports md_parser and md_writer submodules that handle parsing/writing of response blocks, interaction logs, audit docs, response docs, STATE.md, UI_FOCUS.md, and NOTES.md surfaces.*

- **MOVES**: `Package marker / docstring for review walker markdown layer` → `pm_core/sensorium/artifact/walker_ui.py`
    - *The walker's markdown surfaces (STATE.md, UI_FOCUS.md, per-cycle response/audit docs) become ReviewStateArtifact, UiFocusArtifact, ReviewCycleArtifact, CitationAuditCycleArtifact, ReviewResponseCycleArtifact per the plan.*
- **MOVES**: `Re-export of md_parser submodule` → `pm_core/sensorium/artifact/walker_ui.py`
    - *Parser logic folds into the Artifact subclasses' read() implementations (parsing the on-disk markdown into structured payloads).*
- **MOVES**: `Re-export of md_writer submodule` → `pm_core/sensorium/artifact/walker_ui.py`
    - *Writer logic folds into the Artifact subclasses' apply()/propose_edit() implementations.*

  *Cross-cutting:* The init file itself is trivial; its disposition is entirely dictated by where pm_core/review/md_parser.py and pm_core/review/md_writer.py land (and any consumers that currently do `from pm_core.review import ...`). The v2 plan explicitly lists walker_ui.py artifacts as the new home for plan-3119574 walker surfaces, so this whole package collapses into pm_core/sensorium/artifact/walker_ui.py (plus possibly NotesSectionArtifact for NOTES.md). Migration is blocked until md_parser/md_writer are themselves classified and walker driver code (review_walker, review supervisor) is rewritten to use Artifact.read/apply seams.

#### `pm_core/review/md_parser.py`
*Markdown surface parsers for the walker UI (plan-3119574): parses proposed-change response blocks (YAML inside HTML comments), interaction logs, canonical citation-audit docs, response docs (preamble + blocks), STATE.md, and UI_FOCUS.md. Returns typed dataclasses (ResponseBlock, ResponseDoc, AuditEntry, AuditDoc, StateFile, FocusFile). Includes a custom YAML loader that keeps ISO timestamps as strings for round-tripping.*

- **MOVES**: `ResponseBlock + parse_response_blocks + parse_interaction_log + parse_response_doc + ResponseDoc` → `pm_core/sensorium/artifact/walker_ui.py`
    - *These are the on-disk reader half of ReviewResponseCycleArtifact (per-cycle REVIEW_RESPONSE_CYCLE_N.md). The Artifact's read() should delegate to these parsers; the dataclasses become the typed payload returned by .read().*
- **MOVES**: `AuditEntry + AuditDoc + parse_audit_doc + _extract_section + _extract_surfaced + tier/verdict/flag regexes` → `pm_core/sensorium/artifact/walker_ui.py`
    - *Reader half of CitationAuditCycleArtifact (CITATION_AUDIT_CYCLE_N.md). The mid-write entry-completeness gating logic must move with it since it's a real durability concern.*
- **MOVES**: `StateFile + parse_state` → `pm_core/sensorium/artifact/walker_ui.py`
    - *Reader half of ReviewStateArtifact (STATE.md).*
- **MOVES**: `FocusFile + parse_focus` → `pm_core/sensorium/artifact/walker_ui.py`
    - *Reader half of UiFocusArtifact (UI_FOCUS.md).*
- **MOVES**: `_StringTimestampLoader + _yaml_load (timestamp-as-string YAML loader)` → `pm_core/sensorium/artifact/walker_ui.py`
    - *Small shared utility used by parse_response_blocks/parse_state/parse_focus — colocate as a private helper inside walker_ui.py since all consumers move there. If a second sensorium Artifact ever needs the same loader, hoist it to pm_core/sensorium/artifact/base.py.*
- **MOVES**: `BLOCK_OPEN_RE / BLOCK_CLOSE_RE proposed-change fence parsing` → `pm_core/sensorium/artifact/walker_ui.py`
    - *Belongs with ReviewResponseCycleArtifact; the apply()/propose_edit() side on that Artifact will need to write the same fences, so consider extracting a small ResponseBlockCodec section within walker_ui.py.*

  *Not in plan:*
  - Symmetric writer/round-trip side of these surfaces (propose_edit/apply for response blocks and audit entries): When walker_ui.py is built, factor a single _codec section (fences + canonical heading order + YAML loader) so the audit/response writer Streams import the same constants rather than duplicating regex/format knowledge.

  *Cross-cutting:* pm_core/review/ is a sibling directory not enumerated in v2 — the whole walker UI subsystem (plan-3119574) is being consolidated under sensorium/artifact/walker_ui.py for the typed-Artifact half. Other files under pm_core/review/ (state machine, audit driver, response driver, SSE/HTTP server) will move to streams/ and sensorium/artifact/ as well; this parser is the cleanest piece to move first because it has no upstream dependencies beyond stdlib + pyyaml. Consumers of md_parser inside pm_core/review/ (likely the SSE server and state driver) need their imports redirected to walker_ui.py — those migrations are blocked until walker_ui.py exists.

#### `pm_core/review/md_writer.py`
*Atomic + flock-locked writers for the walker UI's three markdown surfaces: response-block files (proposed-change blocks with id/interactions), STATE.md, UI_FOCUS.md, and NOTES.md. Provides _atomic_write_text (temp file + os.replace + fsync), _locked (sibling .lock flock context), a custom YAML dumper that renders multi-line strings as literal | blocks, _rewrite_block (locked RMW of a single response block by id), update_response_block, append_interaction, update_state, update_focus, append_note.*

- **MOVES**: `Atomic write primitive (_atomic_write_text)` → `pm_core/sensorium/artifact/base.py`
    - *Becomes a shared helper on Artifact base used by apply(); same pattern as pane_registry.locked_read_modify_write. Could also be a small util module — but Artifact.apply is the natural seam.*
- **MOVES**: `flock-based locking context (_locked)` → `pm_core/sensorium/artifact/base.py`
    - *Artifact.apply needs RMW locking; this is the canonical impl.*
- **MOVES**: `YAML block-style dumper (_BlockDumper, _represent_str/_none, _dump_block_body, _render_block)` → `pm_core/sensorium/artifact/walker_ui.py`
    - *Specific to the proposed-change block serialization format of ReviewResponseCycleArtifact; lives next to the response-block parser.*
- **MOVES**: `_rewrite_block + update_response_block + append_interaction (response-block RMW)` → `pm_core/sensorium/artifact/walker_ui.py`
    - *Becomes methods on ReviewResponseCycleArtifact (apply/propose_edit semantics) — operates on a per-cycle response-block file.*
- **MOVES**: `update_state (STATE.md writer)` → `pm_core/sensorium/artifact/walker_ui.py`
    - *Becomes ReviewStateArtifact.apply — stamps last-transition, atomic write.*
- **MOVES**: `update_focus (UI_FOCUS.md writer)` → `pm_core/sensorium/artifact/walker_ui.py`
    - *Becomes UiFocusArtifact.apply — stamps timestamp last, atomic write.*
- **MOVES**: `append_note (NOTES.md section-aware appender)` → `pm_core/sensorium/artifact/notes.py`
    - *Matches NotesSectionArtifact responsibility (section-keyed timestamped append). Walker NOTES.md is a NotesSectionArtifact instance — share code with project-level NotesSectionArtifact.*
- **MOVES**: `_utc_now timestamp helper` → `pm_core/sensorium/artifact/base.py`
    - *Trivial helper; lives wherever Artifact base lives.*

  *Cross-cutting:* Paired with pm_core/review/md_parser.py (imported here: parse_response_blocks, BLOCK_CLOSE) — md_parser must move alongside to walker_ui.py to keep the response-block serializer/parser colocated. Callers in pm_core/review/* (walker controller, response renderer) will need to migrate to Artifact.apply / propose_edit on ReviewResponseCycleArtifact + ReviewStateArtifact + UiFocusArtifact instead of importing these free functions. The atomic-write + flock pattern is the third instance in the repo (pane_registry, plan-walker, here) — v2's Artifact.apply should canonicalize it once.

#### `pm_core/runtime_state.py`
*Persists per-PR action lifecycle state (queued/launching/running/idle/waiting/done/failed) to ~/.pm/runtime/{pr_id}.json with flock-protected read-modify-write so the TUI and external CLI/popup processes share a view of in-flight PR actions. Also handles stale-state sweeping on TUI restart, a suppress-switch flag for cancelled window-focus steals, hook-event cross-referencing to derive fresh idle/waiting, and QA pane aggregation. Kicks the home window on real transitions.*

- **MOVES**: `Action state schema + VALID_STATES enum` → `pm_core/mind/lifecycle.py`
    - Maps directly onto LifecycleState StrEnum; queued/launching/running/idle/waiting/done/failed become canonical LifecycleState values.
- **MOVES**: `Persisted action transitions (set_action_state read-modify-write under flock)` → `pm_core/mind/log.py`
    - EmissionLog (SQLite, idempotent append on (stream_id, tag, correlation_id)) replaces JSON-per-PR file write; each transition becomes an Emission with a lifecycle tag. Plan spec lists runtime_state as 'folds into EmissionLog + lifecycle.py'.
- **MOVES**: `get_pr_actions / get_action_state readers` → `pm_core/mind/log.py`
    - Becomes EmissionLog queries scoped by stream_id; PR-action lookup becomes 'latest lifecycle emission per Stream owned by PRStreamSupervisor'.
- **MOVES**: `sweep_stale_states (TUI-restart reset of in-flight entries)` → `pm_core/supervisors/pr_stream.py`
    - PRStreamSupervisor (and/or MindSupervisor) owns liveness reconciliation on Mind startup: Stream.status (LifecycleState) becomes authoritative; orphaned in-flight Streams are terminated by the supervisor rather than swept from a sidecar JSON file.
- **MOVES**: `suppress_switch flag (request_suppress_switch / consume_suppress_switch)` → `pm_core/mind/attention.py`
    - This is an attention/focus-steal cancellation signal; fits AttentionService + AttentionRequest semantics (user-dismissed popup => suppress subsequent focus grab). Could alternatively live as a TUI-local artifact in sensorium/artifact/walker_ui.py-style UiFocusArtifact.
- **MOVES**: `derive_action_status (cross-reference hook_events for fresh idle/waiting)` → `pm_core/runtime/tmux_host.py`
    - Hook-event reading is a runtime-internal detail. TmuxHostRuntime owns Claude Code hook ingestion and reports idle/waiting via Emissions; callers no longer need a derive step.
- **MOVES**: `QA pane worst-state aggregation across scenario panes` → `pm_core/supervisors/pr_stream.py`
    - Becomes PRStreamSupervisor (or a dedicated QaSupervisor under supervisors/) aggregating LifecycleState across child QaScenarioStream instances; replaces the entry['panes'] dict in JSON.
- **MOVES**: `refresh_home() kick on transitions` → `pm_core/watchdog/tui.py`
    - Home-window refresh is a TUI watchdog reaction to lifecycle emissions; subscribing to LifecycleGlobalChannel replaces the inline import+call from inside set_action_state.
- **DELETES**: `runtime_path / _runtime_dir on-disk JSON layout`
    - JSON-per-PR sidecar files are obsoleted by EmissionLog SQLite; no analogue needed.
- **MOVES**: `session_id field on action entry (pane-backed cross-ref key)` → `pm_core/runtime/tmux_host.py`
    - Session-id<->pane mapping is runtime-internal to TmuxHostRuntime; surfaces externally only as Emission metadata.
- **MOVES**: `verdict field surfacing (done VERDICT badge survival)` → `pm_core/payloads/failure_reason.py`
    - Terminal-state verdict belongs on a typed artifact attached to the terminal Emission (FailureReason for failed; analogous payload for done); the picker reads from EmissionLog terminal entry.

  *Not in plan:*
  - Cross-process write-visibility ordering (flush-before-unlock so LOCK_SH readers see new bytes): Safe to delete — subsumed by SQLite semantics in pm_core/agent/log.py.
  - 'Drop action entry when only updated_at/started_at remain' cleanup heuristic: Safe to delete — n/a under append-only EmissionLog.
  - Popup-spinner / queued-tui-command status surface (what get_action_state currently powers for external CLI/popup processes): Add a thin pm_core/cli/ helper (or document in supervisors/pr_stream.py) that exposes EmissionLog-derived action status to CLI popup callers; ensure cli command group migration covers this.

  *Cross-cutting:* Importers blocking migration: pm_core/home_window (refresh_home call inside set_action_state), pm_core/hook_events (read_event used by derive_action_status), pm_core/paths (pm_home, configure_logger), and any TUI code calling set_action_state/sweep_stale_states/request_suppress_switch/consume_suppress_switch. TUI restart sweep is currently triggered from the Textual App on mount — pr_stream.py supervisor needs an explicit startup-reconciliation hook before runtime_state.py can be removed. The 'home window kick' coupling means watchdog/tui.py must subscribe to LifecycleGlobalChannel before set_action_state's inline refresh_home call can be deleted. hook_events.py is not mentioned in the v2 structure — its absorption likely belongs in runtime/hook_entry.py + tmux_host.py and should be verified.

#### `pm_core/signoff.py`
*Sign-off lifecycle stage: defines the five routing verdicts (MERGE/REQA/REVIEW/IMPL/BLOCKED) plus display icons/styles, records and reads verdicts on the PR, launches the tmux sign-off window (evidence pane + Claude router pane, with container-mode handling, per-PR launch lock, pane registry registration, layout rebalance), and provides the pure decide_signoff_hop + side-effect apply_signoff_hop pair for auto-sequence-only state transitions.*

- **MOVES**: `SIGNOFF_* verdict constants + ALLOWED_VERDICTS list` → `pm_core/streams/signoff.py`
    - *Per v2 InputType Protocol's ALLOWED_VERDICTS classvar pattern; the prompt class owns the verdict vocabulary it instructs Claude to emit.*
- **MOVES**: `SIGNOFF_VERDICT_ICONS / SIGNOFF_VERDICT_STYLES / signoff_verdict_icon()` → `pm_core/streams/signoff.py`
    - *Display markers used by TUI tech tree + pm pr list; live with SignoffStream as the canonical rendering metadata. Could alternately live in tui/ but kept core per the original comment.*
- **MOVES**: `signoff_window_name() + window-name convention` → `pm_core/streams/signoff.py`
    - *PRActionStream subclasses declare tui_window_role; window-name derivation belongs on SignoffStream.*
- **DELETES**: `head_sha() git HEAD helper`
    - *Thin wrapper over git_ops.run_git; callers can use git_ops directly. If kept, belongs in pm_core/git_ops.py (Stays bucket).*
- **MOVES**: `record_signoff_verdict() — durable pr['signoff'] = {verdict, sha, ts, origin}` → `pm_core/sensorium/artifact/project_yaml.py`
    - *Writes structured data into project.yaml under the PR entry; this is a ProjectYamlArtifact mutation. The verdict-emission itself is a SignoffStream Emission (pm_core/agent/emissions.py via EmissionLog), and the PR-record update is the Artifact-side projection. Supervisor (pm_core/supervisors/pr_stream.py) wires the two.*
- **MOVES**: `fresh_recorded_verdict() / latest_signoff_verdict() readers` → `pm_core/streams/signoff.py`
    - *Read helpers used by auto-sequence adoption logic and TUI display; live with SignoffStream alongside the icon helpers.*
- **MOVES**: `_evidence_pane_cmd() — shell script that prints captures tree + qa_status.json + diff` → `pm_core/streams/signoff.py`
    - *Stream-specific pane construction; the captures-tree portion will eventually consume CaptureService/CaptureBundle from sensorium/captures.py and the QaStatusArtifact rather than shelling out to `pm qa captures-path` + globbing ~/.pm/workdirs/qa/*.*
- **MOVES**: `launch_signoff_window() — full tmux window launch (evidence pane + Claude pane, fresh/background/origin params, container wrap, pane_registry registration, layout rebalance, per-PR fcntl lock)` → `pm_core/streams/signoff.py`
    - *This is exactly what SignoffStream.start() does. The pane-launching mechanics decompose: prompt generation -> pm_core/prompts/signoff.py; Claude pane spawn -> TmuxHostRuntime / TmuxContainerRuntime (pm_core/runtime/tmux_host.py + tmux_container.py); the fcntl per-PR launch lock -> sensorium/leases.py ResourceLease on a TmuxWindowKey; the prompt build call -> the prompts/signoff.py InputType.*
- **MOVES**: `Per-PR fcntl launch lock (.signoff-launch-<session>-<pr>.lock)` → `pm_core/sensorium/leases.py`
    - *Exactly the use case for ResourceLease+TmuxWindowKey — serialize concurrent claimants of one tmux window.*
- **MOVES**: `Container-mode integration (wrap_claude_cmd, _CONTAINER_WORKDIR, remove_container)` → `pm_core/runtime/tmux_container.py`
    - *Container-vs-host cwd/write_dir branching is exactly the runtime selection seam — SignoffStream just declares required_capabilities and the runtime handles the difference.*
- **STAYS**: `Pane registry registration (signoff-evidence / signoff-claude roles) + user_modified reset + rebalance` → `pm_core/tui/pane_registry.py`
    - *pane_registry + pane_layout are in the Stays list; SignoffStream calls into them. The specific role strings move with SignoffStream.*
- **MOVES**: `_BOUNCE_HOP_STATUS map + decide_signoff_hop() (pure verdict->hop)` → `pm_core/supervisors/pr_stream.py`
    - *Revised destination: lives with `apply_signoff_hop` in `PRStreamSupervisor`'s verdict-routing layer keyed on `PRStatus` enum values rather than the existing `"review"` (hop-token) vs `"in_review"` (status-token) string drift. Per the duplication audit (P2), keeping `decide_signoff_hop` next to its side-effect partner removes the dual-token vocabulary.*
    - *Routing policy of the SignoffStream. Could alternately live on the SignoffSystemPrompt's ALLOWED_VERDICTS metadata, but the mapping to PR lifecycle states is stream-side.*
- **MOVES**: `apply_signoff_hop() — auto-sequence-only side-effect that transitions sign_off -> qa/in_review/in_progress and clears pr['signoff']` → `pm_core/supervisors/pr_stream.py`
    - *PR-level lifecycle transition driven by a child stream's verdict — this is the PRStreamSupervisor's job. The state write itself ultimately goes through ProjectYamlArtifact.propose_edit.*
- **MOVES**: `Module docstring: gate-at-merge invariant + audit-trail-via-pm-pr-note philosophy` → `pm_core/streams/signoff.py`
    - *Behavioral contract for the Claude pane — belongs in the system prompt / InputType docstring.*

  *Not in plan:*
  - QA status surfacing via globbing ~/.pm/workdirs/qa/<pr>-*/qa_status.json from a shell pane: Add pm_core/sensorium/artifact/qa_library/status.py (QaStatusArtifact) so SignoffStream's evidence surface reads the artifact rather than globbing workdirs. Alternatively the evidence pane reads it through CaptureService.
  - Cross-stage 'evidence surface' (captures tree + qa status + full diff) as a first-class concept rendered into a pane: Either (a) make _evidence_pane_cmd a SignoffStream-internal helper that consumes CaptureBundle (preferred — keeps it stream-local), or (b) add sensorium/artifact/evidence_view.py if the surface is reused by review/qa/merge streams. Plan-sensorium should clarify.
  - PR-level structured record pr['signoff'] = {verdict, sha, ts, origin} as a durable, sha-keyed adoption cache: Document on SignoffStream (pm_core/streams/signoff.py) that the latest fresh verdict emission for the current HEAD is adopted by the PRStreamSupervisor; ProjectYamlArtifact stores a denormalized projection for fast cross-process reads. No new file needed — but add this to plan-mind's Stream/Supervisor contract.

  *Cross-cutting:* Importers of this module include: pm_core/cli/pr.py (pm pr signoff command), the auto-sequence driver (likely pm_core/watcher_*), TUI tech tree + pm pr list (icon helpers), and qa_status / transcript verdict-extraction code. Migration is bidirectional with: pm_core/prompt_gen.py (generate_signoff_prompt — moves to prompts/signoff.py and must move first or together), pm_core/container.py (TmuxContainerRuntime extracts container_mode handling), pm_core/claude_launcher.py (stays; consumed by TmuxHostRuntime), pm_core/pane_layout + pane_registry + tmux + home_window (stays), pm_core/store.locked_update + get_pr (stays; consumed by ProjectYamlArtifact). The auto-sequence driver's reliance on decide_signoff_hop/apply_signoff_hop means PRStreamSupervisor must land before signoff.py can be removed. The verdict-string vocabulary is shared with qa-finalize-style transcript polling (extract_verdict_from_transcript) — moving ALLOWED_VERDICTS into prompts/signoff.py requires updating that polling site accordingly.

#### `pm_core/spec_gen.py`
*Spec generation subsystem for PR phases (impl, qa). Mixes (a) prompt construction for spec generation, (b) on-disk spec file I/O at pm/specs/<pr-id>/<phase>.md, (c) project.yaml state mutation for spec_pending review-queue, (d) a synchronous launch_claude_print invocation to actually generate the spec, (e) preamble/format helpers that get inlined into downstream impl/qa session prompts, and (f) a QA mocks-section extractor.*

- **MOVES**: `get_spec_mode / pr_spec_mode (global+per-PR spec mode resolution)` → `pm_core/sensorium/artifact/spec.py`
    - *Becomes a property/method on SpecArtifact (or on its policy); per-PR review_spec flag continues to live in ProjectYamlArtifact. The mode enum (auto|review|prompt) belongs with the SpecArtifact.*
- **MOVES**: `spec_dir / spec_file_path (on-disk path layout under pm/specs/<pr_id>/<phase>.md)` → `pm_core/sensorium/artifact/spec.py`
    - *SpecArtifact owns the file path; PathService (sensorium/paths.py) may help with workdir-vs-canonical resolution.*
- **MOVES**: `get_spec / set_spec (read with workdir-first fallback, write + log)` → `pm_core/sensorium/artifact/spec.py`
    - *Becomes SpecArtifact.read() / apply()/propose_edit() with Artifact base semantics; workdir-vs-merged lookup uses PathView/WorkdirRegistry.*
- **MOVES**: `_build_spec_prompt (Claude prompt for generating a phase spec)` → `pm_core/streams/spec_gen.py`
    - *Listed explicitly in v2 under prompts/. Becomes the InputType class for spec generation.*
    - *Inline `phase_labels = {"impl": "implementation", "qa": "QA"}` dict at L507-508 DELETES; replaced by `Phase(phase).prose` reading from `pm_core/streams/_shared_prompts.py`. Audit round-3 found this dict duplicated against another phase-labels dict at L692-696 in `format_spec_for_prompt`, with different casings — splitting the two helpers across files (this PR moves them to different destinations) would make the duplication harder to spot post-refactor. The `Phase` StrEnum on `_shared_prompts.py` collapses both.*
- *(Cross-cutting with `format_spec_for_prompt` move)* the second `phase_labels = {"impl": "Implementation Spec", "qa": "QA Spec"}` dict at L692-696 also DELETES; the relocated `format_spec_for_prompt` in `pm_core/streams/_shared_prompts.py` reads `Phase(phase).heading` from the same enum.
- **MOVES**: `generate_spec (orchestrates: existing-check, prompt build, launch_claude_print, write file, set spec_pending state)` → `pm_core/streams/impl.py`
    - *Spec generation as a separately-driven Stream step. Effectively the 'Step 0' invocation — could be its own SpecGenStream, but v2 doesn't list one. Closest fit is folding it into ImplStream/QaPlanningStream (each phase gens its own spec). Flag: a dedicated SpecGenStream is arguably missing — see MISSING. The launch_claude_print call gets replaced by RuntimePlugin invocation.*
- **MOVES**: `spec_pending state in project.yaml (write/read of the review queue)` → `pm_core/sensorium/artifact/project_yaml.py`
    - *spec_pending is a PR-record field; ProjectYamlArtifact.apply() handles the locked_update. The queue semantics (oldest_pending_spec_pr) become a query method on ProjectYamlArtifact or on SpecArtifact.*
- **MOVES**: `has_pending_spec / get_pending_spec_phase / oldest_pending_spec_pr (queue queries for review UI)` → `pm_core/sensorium/artifact/spec.py`
    - *Become SpecArtifact query methods or a SpecReviewQueue helper alongside it.*
- **MOVES**: `approve_spec (clear spec_pending, optionally write edited text)` → `pm_core/sensorium/artifact/spec.py`
    - *SpecArtifact.approve(edited_text=None) — uses Artifact.apply for the write and ProjectYamlArtifact.apply for clearing spec_pending.*
- **MOVES**: `reject_spec (regenerate with feedback appended to description)` → `pm_core/sensorium/artifact/spec.py`
    - *SpecArtifact.reject(feedback) triggers a re-run of the spec-generation Stream. The 'temporarily mutate description then restore' dance should be replaced by passing feedback as a separate Stream input.*
- **MOVES**: `spec_generation_preamble (inline 'Step 0' prompt block injected into impl/qa sessions)` → `pm_core/streams/_shared_prompts.py`
    - *Cross-prompt fragment shared by impl_system, qa_planning, etc. The QA-specific 'commit and push the spec' branch is conceptually a Workdir/git operation, but the prompt fragment itself belongs in _shared.py. Could alternatively live in prompts/spec_gen.py as a public helper imported by the system prompts.*
- **MOVES**: `format_spec_for_prompt (renders an existing spec + staleness/review note for downstream session prompts)` → `pm_core/streams/_shared_prompts.py`
    - *Same rationale — used by impl_system.py and qa_*.py prompts; lives as a shared fragment.*
- **MOVES**: `get_spec_mocks_section (extract Mocks block from QA spec or fall back to qa_instructions library)` → `pm_core/sensorium/artifact/qa_library/mocks.py`
    - *v2 has qa_library/mocks.py (the authoritative library). The 'extract from QA spec' fallback is legacy and should be retired (or moved alongside as a one-shot migration helper). The 'mocks block for prompt' renderer belongs as a method on the QaMocksArtifact.*
- **MOVES**: `PHASES constant ('impl','qa') and phase validation` → `pm_core/sensorium/artifact/spec.py`
    - *Becomes an enum on SpecArtifact or a literal type. Phase identity also overlaps with PRStatus / lifecycle states (lifecycle.py).*
- **DELETES**: `Synchronous launch_claude_print spec generation (today's transport)`
    - *Replaced by RuntimePlugin invocation from the Stream that orchestrates spec gen. The 'click.echo Generating...' user-feedback line becomes an Emission.*

  *Not in plan:*
  - A dedicated SpecGenStream (or equivalent) that owns the Claude invocation, ambiguity detection (AMBIGUITY_FLAG / [UNRESOLVED] sentinels), and toggling of spec_pending: Add pm_core/streams/spec_gen.py (a small Stream subclass) under plan-mind, with its own input type pm_core/prompts/spec_gen.py (already listed). Alternatively fold the gating semantics into the PR Supervisor (pm_core/supervisors/pr_stream.py) as a precondition step before launching ImplStream/QaPlanningStream.
  - Ambiguity-flag review loop (mode=prompt detects AMBIGUITY_FLAG / [UNRESOLVED] tokens in generated text and triggers human review): Detection logic lives in SpecGenStream (above) or as a WatchdogPolicy under pm_core/watchdog/. The actual user-review request becomes an AttentionRequest emitted on AttentionGlobalChannel.
  - QA-spec git commit+push step (so scenario clones can read the spec): Move the 'commit+push spec before QA planner runs' responsibility to pm_core/sensorium/workdirs.py (Workdir.publish_artifact) or to QaPlanningStream's setup phase, so it isn't done by Claude inside a prompt.

  *Cross-cutting:* spec_gen.py is imported by impl/qa session prompt builders (prompts/impl_system.py, prompts/qa_*.py via format_spec_for_prompt and spec_generation_preamble) and by CLI surfaces for spec approve/reject (likely pm_core/cli/). Migration order: (1) introduce SpecArtifact + qa_library/mocks.py; (2) extract _build_spec_prompt into prompts/spec_gen.py; (3) move preamble/format helpers into prompts/_shared.py; (4) decide on SpecGenStream vs folding into ImplStream/QaPlanningStream — this decision blocks PR Supervisor design. The 'launch_claude_print' call here is one of the last sync-Claude call sites outside bridge.py and must migrate to RuntimePlugin in lockstep with bridge.py's removal. spec_pending field in project.yaml is read by TUI status panes — those readers migrate via ProjectYamlArtifact.

#### `pm_core/tui/auto_start.py`
*TUI module implementing "auto-start" mode: when enabled with a target PR, automatically starts ready PRs in the target's transitive dependency tree, auto-starts review loops for in_review PRs, auto-starts QA loops for qa-status PRs, and manages a stop-before-merge set. Also handles breadcrumb persistence across TUI restarts (for merge-restart flow), per-run transcript directory allocation, and a quiet `pm pr start --background` subprocess invocation.*

- **MOVES**: `Auto-start orchestration policy (check_and_start, toggle, auto_sequence_for_pr, set_target, _disable, is_enabled, get_target)` → `pm_core/streams/watchers/auto_start.py`
    - *Becomes an AutoStartWatcherStream + WatcherSupervisor. The 'target + transitive deps + start ready' policy is the watcher's core loop.*
- **MOVES**: `Transitive dependency computation (_transitive_deps)` → `pm_core/streams/watchers/auto_start.py`
    - *Internal helper for the watcher; could also call into pm_core/graph.py which stays.*
- **MOVES**: `Auto-start review-loop fan-out (_auto_start_review_loops)` → `pm_core/supervisors/pr_stream.py`
    - *Per-PR stream supervisor decides when to spawn a ReviewStream; the watcher signals 'target dep-tree relevance' via a Channel.*
- **MOVES**: `Auto-start QA fan-out (_auto_start_qa_loops, skip_qa policy)` → `pm_core/supervisors/pr_stream.py`
    - *PRStreamSupervisor handles QA stream lifecycle; skip_qa becomes a StreamPolicy field.*
- **DELETES**: `Quiet PR start subprocess (_start_pr_quiet using `pm pr start --background`)`
    - *Replaced by Mind.stream(role=ImplStream, ...) — the watcher creates streams directly via the Mind instead of shelling out to a CLI.*
- **MOVES**: `stop_before_merge set management (in save_breadcrumb, consume_breadcrumb, check_and_start, auto_sequence_for_pr)` → `pm_core/mind/policy.py`
    - *Becomes StreamPolicy.stop_before_merge (already explicitly listed in policy.py in v2).*
- **MOVES**: `Transcript directory allocation (get_transcript_dir, run_id generation, _finalize_all_transcripts)` → `pm_core/mind/transcript.py`
    - *StreamTranscript is pm-owned per-stream files; per-run dir collection becomes a transcript service concern. finalize_transcript is in claude_launcher (stays) and gets called by TmuxHostRuntime cleanup.*
- **MOVES**: `Breadcrumb persistence across TUI restart (save_breadcrumb, consume_breadcrumb, _MERGE_RESTART_MARKER, has_merge_restart_marker)` → `pm_core/supervisors/mind.py`
    - *Mind-level resume-after-restart: persist watcher set, running streams, stop_before_merge. EmissionLog already gives durable per-stream state, so breadcrumb shrinks to 'which watchers were running + their config'. Marker file flow itself fits MindSupervisor restart hook.*
- **DELETES**: `Review-loop state serialization in breadcrumb (review_loops dict with ReviewLoopState reconstruction)`
    - *ReviewLoopState/ReviewIteration go away with review_loop.py; replaced by EmissionLog replay + ReviewStream lifecycle. No bespoke serialization needed.*
- **MOVES**: `Watcher resume from breadcrumb (watchers_data loop calling watcher_ui.start_watcher)` → `pm_core/supervisors/mind.py`
    - *WatcherSupervisor + MindSupervisor own watcher recreation from persisted config.*
- **MOVES**: `TUI keypress entry points (toggle, auto_sequence_for_pr, set_target) — UI-facing callable surface` → `pm_core/tui/auto_start.py`
    - *Per v2 'TUI integration shim pattern' — this file STAYS as a thin delegator: keybinding handler calls Mind.supervisor('watcher').start(AutoStartWatcher, target=...). The 575 LOC shrinks to ~30 LOC.*
- **MOVES**: `manual-<token> transcript run_id fallback (manual review loops without auto-start)` → `pm_core/mind/transcript.py`
    - *Cross-cutting transcript dir convention; not auto-start specific. Belongs with StreamTranscript service.*

  *Not in plan:*
  - merge-restart marker file (_MERGE_RESTART_MARKER) — a TUI-process-restart signaling mechanism written by the merge step and consumed at TUI startup: Add a small RestartCoordinator concept in pm_core/supervisors/mind.py or note it as a host-loop responsibility under pm_core/tui/ that survives the refactor. Likely safe to keep as a TUI-process detail since other runtimes don't have an equivalent.
  - Auto-sequence 'arm one PR to flow through impl→review→qa but stop before merge' as a named user-facing mode distinct from auto-start: Add as a method on WatcherSupervisor or as a documented AutoStartWatcherStream input mode (target=pr_id, stop_before_merge=True).

  *Cross-cutting:* Imports/uses: pm_core.review_loop (deleted; replaced by ReviewStream), pm_core.tui.review_loop_ui._start_loop (becomes thin delegator), pm_core.tui.watcher_ui (becomes thin delegator), pm_core.tui.qa_loop_ui (becomes thin delegator), pm_core.claude_launcher.finalize_transcript (stays; called by TmuxHostRuntime), pm_core.wrapper (renamed bootstrap.py; subprocess call deleted), pm_core.store.get_pr (stays via ProjectYamlArtifact), pm_core.graph.ready_prs (stays), pm_core.paths (mostly stays). app object fields _auto_start, _auto_start_target, _auto_start_run_id, _review_loops, _qa_loops, _stop_before_merge, _watcher_manager are all migration touchpoints — the TUI App's state model needs to be refactored to call into Mind/Supervisor instead of holding these directly. Migration of auto_start.py is blocked until: AutoStartWatcherStream exists, WatcherSupervisor exists, StreamPolicy.stop_before_merge wired through, and review_loop.py / qa_loop.py replacements are in place.

#### `pm_core/tui/qa_loop_ui.py`
*TUI integration for QA loops: handles keybinding actions (t / z t / zz t) to start/focus/restart/stop QA runs, polls QA state and animates panes, recovers orphaned QA runs from disk after TUI restart, processes QA completion (verdict-driven lifecycle transitions, auto-merge, self-driving review restart, PR note recording), and exposes stop_qa for the command bar.*

- **MOVES**: `Keybinding action: focus_or_start_qa (t)` → `pm_core/streams/qa_planning.py (or thin shim retained in pm_core/tui/qa_loop_ui.py delegating to Mind.stream(QaPlanningStream, instance_key=pr_id))`
    - Focus existing QA window or kick off a new QA run. Becomes a thin TUI shim invoking Mind.stream() for QA role.
- **MOVES**: `Keybinding action: start_qa` → `pm_core/supervisors/pr_stream.py`
    - Create QALoopState, transition status in_review→qa, spawn background. Becomes PRStreamSupervisor.start_qa() spawning Qa* Streams; status transition becomes lifecycle.PRStatus update via ProjectYamlArtifact.
- **MOVES**: `Keybinding action: fresh_start_qa (z t)` → `pm_core/supervisors/pr_stream.py`
    - Stop running QA and restart. Maps to PRStreamSupervisor kill_restart of QA streams using LoopMode.kill_restart.
- **MOVES**: `Keybinding action: start_or_stop_qa_loop (zz t)` → `pm_core/supervisors/pr_stream.py`
    - Toggle self-driving QA loop with required-pass counting. PRStreamSupervisor owns consecutive_pass_threshold via StreamPolicy.
- **MOVES**: `stop_qa public API` → `pm_core/supervisors/pr_stream.py`
    - Graceful stop request → Stream.shutdown / supervisor stop.
- **MOVES**: `poll_qa_state (TUI tick) — spinner/pane idle tracking + completion drain` → `pm_core/watchdog/tui.py`
    - Spinner animation wiring against pane idle tracker and consuming completion events becomes a typed WatchdogPolicy reacting to Stream lifecycle emissions.
- **DELETES**: `_resume_incomplete_qa — disk-scan recovery of orphaned runs`
    - *Replaced by EmissionLog + StreamTranscript persistence + Supervisor reconstitution on Mind startup. Resume snapshot files become unnecessary because Stream state is reconstructable from the log.*
- **MOVES**: `_on_qa_update (TUI log line)` → `pm_core/watchdog/tui.py`
    - Subscriber on QA stream Emissions writing to TUI log.
- **MOVES**: `_on_qa_complete — verdict dispatch + self-driving counting + auto-merge / review restart` → `pm_core/supervisors/pr_stream.py`
    - Verdict-driven lifecycle dispatch (PASS→merge or restart, NEEDS_WORK→ReviewStream restart, INPUT_REQUIRED→pause) is core PRStreamSupervisor logic; consecutive-pass counting consumes StreamPolicy.consecutive_pass_threshold.
- **MOVES**: `_start_self_driving_review` → `pm_core/supervisors/pr_stream.py`
    - PRStreamSupervisor spawns ReviewStream directly when QA returns NEEDS_WORK in self-driving mode.
- **MOVES**: `_trigger_auto_merge` → `pm_core/supervisors/pr_stream.py`
    - Merge gating becomes supervisor responsibility (stop_before_merge policy + MergeStream spawn).
- **MOVES**: `_transition_pr_status (locked status update)` → `pm_core/sensorium/artifact/project_yaml.py`
    - Status transitions become ProjectYamlArtifact.propose_edit/apply operations using lifecycle.PRStatus.
- **MOVES**: `_record_qa_note (append PR note)` → `pm_core/sensorium/artifact/notes.py`
    - PR note recording becomes NotesSectionArtifact.apply (still consumes pm_core/notes.py + store).
- **MOVES**: `_get_qa_pass_count (global settings read)` → `pm_core/mind/policy.py`
    - Becomes a field/derivation in StreamPolicy.consecutive_pass_threshold sourced from global settings.
- **STAYS**: `_get_selected_pr (TUI helper)` → `pm_core/tui/qa_loop_ui.py`
    - Pure TUI selection helper — stays in TUI as part of the thin integration shim.
- **STAYS**: `Module top-level: thin TUI integration shim` → `pm_core/tui/qa_loop_ui.py`
    - Per v2 'TUI integration shim pattern', qa_loop_ui survives as a thin delegator translating keybindings into Mind.stream()/Supervisor calls.

  *Not in plan:*
  - Suppress-switch flag handshake (runtime_state.consume_suppress_switch) to prevent focus stealing after popup picker dismissal: Model as a short-lived AttentionRequest in pm_core/agent/attention.py (ControlOwner=tui_user with TTL), or as a transient flag on AttentionService — add an explicit note in plan-mind that attention handshake covers popup→window focus suppression.
  - runtime_state.set_action_state mirror so the popup picker can show [done VERDICT] across invocations: Goes into pm_core/sensorium/artifact/walker_ui.py-style artifact OR a new PRActionStateArtifact under pm_core/sensorium/artifact/ — flag for plan-sensorium.
  - qa_resume.json on-disk snapshot for orphan recovery: Document in plan-mind that Supervisor reconstitution on Mind boot + EmissionLog replay replaces resume snapshots; safe to delete the json artifact.

  *Cross-cutting:* Imports pm_core.qa_loop (slated for deletion → Qa*Stream + QaSupervisor), pm_core.loop_shared (deleted → CallbackRegistry), pm_core.runtime_state (deleted → EmissionLog/lifecycle/attention), pm_core.tui.review_loop_ui (sibling shim under same TUI shim pattern), pm_core.tui.auto_start (becomes AutoStartWatcher stream). Migration of qa_loop_ui is gated on PRStreamSupervisor + Qa*Stream + ReviewStream existing, and on the attention/sensorium replacements for runtime_state's suppress_switch + action_state mirror. Conversely, app.py (which calls focus_or_start_qa, start_qa, fresh_start_qa, start_or_stop_qa_loop, stop_qa, poll_qa_state) must keep these entry points (or migrate to Mind.stream / supervisor calls) atomically with this file.

#### `pm_core/tui/review_loop_ui.py`
*TUI integration shim for review loops: handles z d / zz d keybindings (stop-and-fresh vs supersede-and-restart loop), starts/stops review loop background threads, manages the shared 1Hz poll timer, mirrors loop state into runtime_state, polls implementation panes for idle detection to trigger auto-review, polls merge windows for MERGED/INPUT_REQUIRED verdicts, performs auto-QA on review PASS and auto-merge with two-step propagation logic for conflict resolution.*

- **MOVES**: `Verdict icon table (VERDICT_ICONS)` → `pm_core/tui/review_loop_ui.py`
    - *Pure presentation; review_loop_ui stays as 'thin delegator' per plan's TUI integration shim pattern. Constants like VERDICT_ICONS remain here for log_message rendering.*
- **MOVES**: `z d handler — stop loop or fresh review` → `pm_core/streams/review.py`
    - *Keybinding handler becomes a thin call into ReviewStream lifecycle: takeover/restart via ControlOwner + LoopMode.kill_restart. The kill-window side effect moves into TmuxHostRuntime cleanup.*
- **MOVES**: `zz d handler — start or supersede loop` → `pm_core/streams/review.py`
    - *Becomes ReviewStream.start() with LoopMode.kill_restart on review.requested per plan: 'ReviewStream — uses LoopMode.kill_restart on review.requested'.*
- **MOVES**: `_start_loop — launch background review loop with transcript dir, resume state, runtime_state mirror` → `pm_core/streams/review.py`
    - *Stream lifecycle owns this; transcript_dir handling moves to StreamTranscript (pm_core/agent/transcript.py); runtime_state mirror replaced by EmissionLog.*
- **MOVES**: `_stop_loop / stop_loop_for_pr — graceful stop request` → `pm_core/streams/review.py`
    - *Stream.shutdown / LifecycleState transition.*
- **MOVES**: `_on_iteration_from_thread / _on_complete_from_thread — background-thread callbacks mirroring state` → `pm_core/mind/emissions.py`
    - *Replaced by Emission envelope writes from RuntimePlugin; supersede detection (loop_id check) becomes correlation_id + dedup_key on Emission.*
- **DELETES**: `_is_active_loop — supersede detection via runtime_state loop_id comparison`
    - *runtime_state.py is folded into EmissionLog + lifecycle.py per plan; correlation_id on Emission supersedes loop_id comparison.*
- **MOVES**: `finalize_transcript symlink finalization on loop complete` → `pm_core/mind/transcript.py`
    - *Transcript finalization is now pm-owned StreamTranscript responsibility.*
- **MOVES**: `_ensure_poll_timer / ensure_animation_timer — shared 1Hz timer management` → `pm_core/tui/review_loop_ui.py`
    - *Per plan TUI shim pattern this thin timer logic stays in the TUI integration file; but coverage of QA/watcher/impl loops should be unified — flagged as cross-cutting.*
- **MOVES**: `_poll_loop_state / _poll_loop_state_inner — multi-loop tick: review, QA, watcher, impl idle, tree refresh, completion announcements` → `pm_core/watchdog/tui.py`
    - *Becomes a WatchdogPolicy that consumes Manager/Supervisor events instead of polling state objects. The completion announcement / sticky log_message side effect stays in the TUI shim.*
- **STAYS**: `_refresh_tech_tree — advance animation + refresh active nodes` → `pm_core/tui/review_loop_ui.py`
    - *Pure TUI rendering; tech_tree.py stays per plan.*
- **MOVES**: `_maybe_start_qa — auto-transition in_review → qa and start QA on review PASS (with skip_qa branch)` → `pm_core/supervisors/pr_stream.py`
    - *PRStreamSupervisor owns the cross-stream transition (review.passed → start QaPlanningStream). skip_qa policy belongs in StreamPolicy. Self-driving QA flag moves to Supervisor state.*
- **MOVES**: `_maybe_auto_merge — auto-merge on PASS gated by auto-start + stop_before_merge` → `pm_core/supervisors/pr_stream.py`
    - *PRStreamSupervisor orchestrates review.passed → MergeStream; stop_before_merge becomes StreamPolicy.stop_before_merge per plan.*
- **MOVES**: `_attempt_merge — run pm pr merge subprocess with resolve_window / propagation_only flags` → `pm_core/streams/merge.py`
    - *MergeStream encapsulates the two-step merge command invocation.*
- **MOVES**: `_on_merge_success — cleanup tracker + kick dependents` → `pm_core/supervisors/pr_stream.py`
    - *Supervisor teardown hook; check_and_start becomes a Supervisor event.*
- **MOVES**: `_kill_merge_window — find and kill tmux merge window` → `pm_core/runtime/tmux_host.py`
    - *Tmux window cleanup is RuntimePlugin internal. Lease release in pm_core/sensorium/leases.py (TmuxWindowKey).*
- **MOVES**: `_finalize_detected_merge — two-step MERGED verdict finalization with propagation phase tracking` → `pm_core/streams/merge.py`
    - *Becomes MergeStream + MergeConflictResolverStream state machine per plan ('merge.py (MergeStream + MergeConflictResolverStream)'). _merge_propagation_phase set replaced by Stream.status / LifecycleState.*
- **MOVES**: `_handle_merge_input_required — INPUT_REQUIRED merge verdict handling` → `pm_core/mind/attention.py`
    - *AttentionRequest with ControlOwner per plan; _merge_input_required_prs tracking subsumed by AttentionService.*
- **MOVES**: `_find_impl_pane — tmux pane lookup helper` → `pm_core/runtime/tmux_host.py`
    - *Tmux pane resolution is runtime-internal.*
- **MOVES**: `_poll_impl_idle — poll impl panes for idle, register/unregister with tracker, detect newly-idle for auto-review` → `pm_core/runtime/tmux_host.py`
    - *Pane idle detection moves into TmuxHostRuntime per plan ('pane_idle.py — runtime-internal detail moves into TmuxHostRuntime'). Newly-idle detection emits a stream Emission consumed by WatcherSupervisor.*
- **MOVES**: `Merge verdict polling (extract_verdict_from_transcript on merge transcript)` → `pm_core/streams/merge.py`
    - *verdict_transcript.py is deleted; replaced by pm-owned StreamTranscript capture inside MergeStream.*
- **MOVES**: `Review verdict mirror for non-loop review windows (extract_verdict_from_transcript)` → `pm_core/streams/review.py`
    - *Same — StreamTranscript-based verdict extraction inside ReviewStream.*
- **MOVES**: `Tracker stale key cleanup (merge:/review:/impl)` → `pm_core/runtime/tmux_host.py`
    - *Tracker lifecycle moves into TmuxHostRuntime.*
- **MOVES**: `_auto_review_idle_prs — transition in_progress → in_review and run pm pr review --background, start ReviewLoop` → `pm_core/streams/watchers/auto_start.py`
    - *Per plan 'streams/watchers/{auto_start.py}'; AutoStartWatcher reacts to impl.idle emission, transitions PR, and instantiates ReviewStream.*
- **STAYS**: `_get_selected_pr / log_message UI plumbing` → `pm_core/tui/review_loop_ui.py`
    - *Selection state and message rendering remain TUI-local.*
- **MOVES**: `spec_pending re-arm on idle (mark_active when pr.spec_pending)` → `pm_core/streams/watchers/auto_start.py`
    - *Policy lives with the auto-start watcher.*

  *Cross-cutting:* This file is a major integration hub: it imports pm_core.review_loop (deleted in plan), pm_core.runtime_state (deleted), pm_core.verdict_transcript (deleted), pm_core.tui.auto_start, pm_core.tui.qa_loop_ui, pm_core.tui.watcher_ui, pm_core.tui.pr_view, pm_core.tmux, pm_core.home_window, pm_core.claude_launcher.finalize_transcript, pm_core.cli.helpers._pr_display_id. Migration cannot land until: (1) ReviewStream + MergeStream + QaPlanningStream + AutoStartWatcher exist, (2) PRStreamSupervisor wires review→qa→merge transitions, (3) TmuxHostRuntime absorbs pane_idle + tracker + window kill, (4) EmissionLog replaces runtime_state mirror semantics, (5) AttentionService replaces _merge_input_required_prs. app._review_loops / app._qa_loops / app._pending_merge_prs / app._merge_propagation_phase / app._merge_input_required_prs / app._stop_before_merge / app._self_driving_qa / app._pane_idle_tracker / app._impl_poll_counter / app._review_loop_timer / app._watcher_manager — all of these App-level attributes need successor homes (mostly Supervisor state, some StreamPolicy, AttentionService). The two-step merge propagation_only logic is subtle and should be preserved as MergeConflictResolverStream state machine. Auto-QA's skip_qa project-level branch needs to live in StreamPolicy or project config, not duplicated in PRStreamSupervisor.</cross_cutting_notes> <parameter name="not_in_plan">[   {"responsibility": "Self-driving QA mode (app._self_driving_qa dict — transitions review→qa even when auto-start disabled)", "why_not_covered": "Plan covers auto-start watchers but doesn't explicitly call out a 'self-driving' per-PR override mode that bypasses auto-start gating.", "recommendation": "Add to pm_core/supervisors/pr_stream.py as a per-PR Supervisor flag (self_driving: bool) that overrides auto-start scope checks. Document in plan-mind alongside ControlOwner / takeover semantics."},   {"responsibility": "stop_before_merge per-PR set armed by auto-sequence keypress", "why_not_covered": "Plan mentions StreamPolicy.stop_before_merge but that's policy-level; this is a per-instance armable flag triggered by a TUI keybinding.", "recommendation": "Add to PRStreamSupervisor as a per-PR armable flag, or as a StreamPolicy override on a specific MergeStream instance. Likely belongs as a TUI-level gesture that sets a policy override on the merge stream."},   {"responsibility": "Two-phase merge propagation (_merge_propagation_phase set — step 1 workdir merge, step 2 propagation to repo dir, distinct INPUT_REQUIRED resolution per phase)", "why_not_covered": "Plan mentions MergeStream + MergeConflictResolverStream but doesn't detail the two-step (workdir-merge → propagation-only) state machine with --propagation-only flag.", "recommendation": "Make the two-step explicit in pm_core/streams/merge.py: MergeStream owns step 1, transitions to MergePropagationStream (or a sub-state) for step 2. Each step gets its own Emission stream and AttentionRequest on conflict."},   {"responsibility": "Sticky log_message with N-second timeout (sticky=3/10/30)", "why_not_covered": "Plan covers Emission visibility tiers but doesn't address ephemeral TUI banner duration.", "recommendation": "Stays in TUI shim — log_message sticky duration is presentation policy not core. Document in TUI integration shim pattern."} ]

#### `pm_core/watchers/__init__.py`
*Package init for built-in watchers: imports four watcher classes (AutoStart, BugFixImpl, DiscoverySupervisor, ImprovementFixImpl), exposes WATCHER_REGISTRY mapping WATCHER_TYPE strings to classes, and provides get_watcher_class() lookup and list_watcher_types() metadata helper.*

- **MOVES**: `Import of AutoStartWatcher` → `pm_core/streams/watchers/auto_start.py`
    - Re-export of AutoStartWatcher; in v2 becomes import of the AutoStart watcher Stream class.
- **MOVES**: `Import of BugFixImplWatcher` → `pm_core/streams/watchers/bug_fix_impl.py`
    - Re-export of bug-fix impl watcher; moves to streams/watchers/bug_fix_impl.py.
- **MOVES**: `Import of DiscoverySupervisorWatcher` → `pm_core/streams/watchers/discovery_supervisor.py`
    - Re-export of discovery supervisor watcher; moves to streams/watchers/discovery_supervisor.py.
- **MOVES**: `Import of ImprovementFixImplWatcher` → `pm_core/streams/watchers/improvement_fix_impl.py`
    - Re-export of improvement-fix impl watcher; v2 plan lists improvement_fix_impl.py under streams/watchers/ (filename inferred; plan shows 'improvement_fix_impl.py' implicitly — explicit watcher_review.py also listed).
- **MOVES**: `WATCHER_REGISTRY dict` → `pm_core/streams/watchers/__init__.py`
    - Explicitly called out in v2: 'streams/watchers/__init__.py with WATCHER_REGISTRY'. Registry now maps to Stream subclasses; lookup consumed by WatcherSupervisor instead of WatcherManager.
- **MOVES**: `get_watcher_class() lookup helper` → `pm_core/streams/watchers/__init__.py`
    - Lives next to the registry in the new watchers package; same semantics, consumed by WatcherSupervisor and CLI delegators.
- **MOVES**: `list_watcher_types() metadata helper` → `pm_core/streams/watchers/__init__.py`
    - Display/window/interval metadata; in v2 the Stream base declares tui_keybinding/tui_glyph/tui_window_role classvars, so this helper either reads those or is folded into a Stream.__init_subclass__-registered descriptor. Lives in streams/watchers/__init__.py.
    - *WATCHER_TYPE/DISPLAY_NAME/WINDOW_NAME/DEFAULT_INTERVAL classvars need to be reconciled with PRActionStream's declared classvars (tui_window_role, tui_glyph) — may need a small adapter.*

  *Cross-cutting:* CLI (pm watcher) and WatcherManager both import from pm_core.watchers; their migration to WatcherSupervisor + streams/watchers/ must happen together. The per-watcher modules (auto_start_watcher.py, bug_fix_impl_watcher.py, discovery_supervisor.py, improvement_fix_impl_watcher.py) are siblings that must move in the same step — this __init__ is just an aggregator and cannot move ahead of them.

#### `pm_core/watchers/auto_start_watcher.py`
*Concrete BaseWatcher subclass for the auto-start mode: declares watcher metadata (type, display name, window, interval, verdicts), generates the watcher prompt via prompt_gen, builds the `pm watcher --iteration` launch command, and parses READY/INPUT_REQUIRED verdicts from Claude output.*

- **MOVES**: `AutoStartWatcher class (concrete watcher role)` → `pm_core/streams/watchers/auto_start.py`
    - Subclass of BaseWatcher becomes a Stream subclass under streams/watchers/, registered in WATCHER_REGISTRY in __init__.py.
    - *WATCHER_TYPE/DISPLAY_NAME/WINDOW_NAME/DEFAULT_INTERVAL/VERDICTS classvars become Stream-declared metadata (tui_window_role, tag declarations, policy).*
- **MOVES**: `generate_prompt() — auto-start watcher prompt` → `pm_core/streams/watcher/auto_start.py`
    - Prompt construction (currently a thin wrapper around prompt_gen.generate_watcher_prompt) becomes a typed InputType class under prompts/watcher/auto_start.py.
    - *Consumes project.yaml data (now via ProjectYamlArtifact) and iteration/loop_id/auto_start_target/meta_pm_root inputs.*
- **DELETES**: `build_launch_cmd() — `pm watcher --iteration` CLI command builder`
    - Subprocess-invocation of `python -m pm_core.wrapper watcher` goes away; stream execution is driven by a RuntimePlugin (TmuxHostRuntime), not by re-entering the wrapper CLI.
    - *wrapper.py is renamed to bootstrap.py and the watcher CLI subcommand in pm_core/cli/ delegates to Streams/Supervisors per the plan.*
- **MOVES**: `parse_verdict() — extract READY/INPUT_REQUIRED from output` → `pm_core/streams/watchers/auto_start.py`
    - Verdict parsing (currently uses loop_shared.match_verdict) becomes part of the AutoStartStream's emission-classification logic, emitting typed Emissions (e.g. verdict tag) rather than returning a string.
    - *loop_shared.py is deleted (CallbackRegistry replaces it); a shared verdict-matching helper, if still needed, would live alongside watcher Streams or in agent/tags.py.*
- **MOVES**: `auto_start_target / meta_pm_root parameters (auto-start target wiring)` → `pm_core/streams/watchers/auto_start.py`
    - Constructor-injected parameters carrying which project/meta-PM root is being auto-started become Stream instance_key/inputs.
    - *Meta-PM linkage (meta_pm_root) is a cross-mind concern; if it implies cross-project supervision, it touches collaboration/identity.py — flag for review.*
- **DELETES**: `WatcherState plumbing (loop_id propagation)`
    - WatcherState comes from watcher_base.py which is being rewritten as Stream base + WatcherSupervisor; loop_id is replaced by stream_id / correlation_id on Emissions.
    - *Per plan: 'watcher_base.py + watcher_manager.py (rewritten as Stream base + WatcherSupervisor)'.*
- **STAYS**: `module-level logger configuration via configure_logger` → `pm_core/paths.py`
    - configure_logger continues to live in pm_core/paths.py (most stays); the new streams/watchers/auto_start.py will still import it.

  *Not in plan:*
  - meta_pm_root parameter — pointer from a watched project to its supervising 'meta' PM project: Verify whether meta_pm_root is just a path used to file notes into another project (handled by collaboration/published_artifact.py + transport/) or whether it implies a dedicated meta-PM Supervisor role; if the latter, add a brief note to plan-collaboration tying meta_pm_root to ProjectIdentity/PartyRelationship.

  *Cross-cutting:* Imports from watcher_base (deleted, becomes streams/base.py + supervisors/watcher.py), loop_shared (deleted, replaced by CallbackRegistry), and prompt_gen (extracted into prompts/watcher/auto_start.py). Re-launch command embeds `pm_core.wrapper` — that module is being renamed to bootstrap.py and the watcher CLI surface is changing to delegate to Streams, so this command builder is fully obsoleted. meta_pm_root suggests cross-project (meta-PM) coupling worth verifying against collaboration/identity.py.

#### `pm_core/watchers/bug_fix_impl_watcher.py`
*BugFixImplWatcher: a BaseWatcher subclass that picks bug PRs from plan=bugs, generates a bug-fix impl prompt, launches a Claude session via pm_core.wrapper CLI, parses READY/INPUT_REQUIRED verdicts, and auto-merges on PASS (auto-merge being the distinguishing behavior).*

- **MOVES**: `Watcher class definition + lifecycle (BaseWatcher subclass)` → `pm_core/streams/watchers/bug_fix_impl.py`
    - *Becomes a Stream subclass under streams/watchers/, registered in WATCHER_REGISTRY in streams/watchers/__init__.py. BaseWatcher itself is deleted (replaced by Stream base + WatcherSupervisor).*
- **MOVES**: `Prompt generation (generate_bug_fix_impl_prompt)` → `pm_core/streams/watcher/bug_fix.py`
    - *Typed InputType class replaces prompt_gen.generate_bug_fix_impl_prompt; pm_core/prompt_gen.py is deleted per plan.*
- **DELETES**: `Launch command construction (build_launch_cmd → python -m pm_core.wrapper watcher ...)`
    - *Subprocess-style launch is replaced by RuntimePlugin invocation (likely TmuxHostRuntime) driven by WatcherSupervisor; wrapper.py is renamed to bootstrap.py and the watcher CLI entry path goes away in favor of Stream.required_capabilities + runtime.start().*
- **MOVES**: `Verdict parsing (parse_verdict scanning trailing lines for READY/INPUT_REQUIRED)` → `pm_core/streams/watchers/bug_fix_impl.py`
    - *Verdict extraction becomes part of the Stream's output_emissions handling (Emission/tag matching via TagRegistry); loop_shared.match_verdict is deleted along with loop_shared.py.*
- **MOVES**: `Auto-merge on PASS distinguishing behavior` → `pm_core/streams/watchers/bug_fix_impl.py`
    - *Auto-merge policy lives on the BugFixImplStream (likely as a StreamPolicy flag or supervisor hand-off to MergeStream). Not visible in this file's body but documented in module docstring.*
- **UNCLEAR**: `meta_pm_root plumbing (cross-project pm root pointer)`
    - *meta_pm_root is a cross-mind/meta-development concept; may belong on streams/meta_development.py inputs or on collaboration/identity.py ProjectIdentity. Not explicitly addressed in v2 plan for watchers.*
- **STAYS**: `Logger configuration via pm_core.paths.configure_logger` → `pm_core/paths.py`
    - *paths.py is in the Stays list; call sites updated to new module path.*

  *Not in plan:*
  - meta_pm_root parameter threading (cross-project bug-fix watcher pointing at a meta-PM repo): Add an explicit meta_pm_root (or ProjectIdentity ref) field on BugFixImplStream inputs in pm_core/streams/watchers/bug_fix_impl.py, or model it via collaboration/identity.py ProjectIdentity reference resolved through PathService.

  *Cross-cutting:* Imports pm_core.watcher_base (deleted), pm_core.loop_shared (deleted), pm_core.prompt_gen (deleted), and shells out to pm_core.wrapper (renamed bootstrap.py with different CLI semantics). Migration of this file is blocked until: (1) Stream base + WatcherSupervisor exist, (2) pm_core/prompts/watcher/bug_fix.py exists, (3) TagRegistry/Emission verdict matching replaces loop_shared.match_verdict, (4) RuntimePlugin invocation replaces the `python -m pm_core.wrapper watcher` subprocess pattern. Sibling improvement_fix_impl_watcher and discovery_supervisor watchers migrate in lockstep.

#### `pm_core/watchers/discovery_supervisor.py`
*DiscoverySupervisorWatcher subclasses BaseWatcher to run the regression test suite on a schedule (30-min default), generate a discovery-supervisor prompt, build a launch command via pm_core.wrapper, and parse READY/INPUT_REQUIRED verdicts. Customizes only prompt generation, launch cmd, and verdict parsing; inherits loop engine from BaseWatcher.*

- **MOVES**: `DiscoverySupervisorWatcher class (watcher role registration: type/display/window/interval/verdicts)` → `pm_core/streams/watchers/discovery_supervisor.py`
    - *Becomes a Stream subclass under streams/watchers/, registered in WATCHER_REGISTRY in streams/watchers/__init__.py. Loop engine inherited from BaseWatcher is supplanted by Stream base + WatcherSupervisor (watcher_base.py + watcher_manager.py are deleted).*
- **MOVES**: `generate_prompt() — builds discovery supervisor prompt via prompt_gen.generate_discovery_supervisor_prompt` → `pm_core/streams/watcher/auto_start.py`
    - *No dedicated discovery_supervisor prompt file is listed in v2 under prompts/watcher/ (only auto_start, bug_fix, improvement_fix, watcher_review). MISSING/UNCLEAR: appears to need its own prompts/watcher/discovery_supervisor.py — flagged below.*
- **DELETES**: `build_launch_cmd() — constructs `python -m pm_core.wrapper watcher ...` invocation`
    - *Launch-cmd construction is absorbed by RuntimePlugin (TmuxHostRuntime) + bootstrap.py (renamed wrapper.py). Stream subclass declares input_type/required_capabilities; the runtime decides how to launch.*
- **DELETES**: `parse_verdict() — scans output lines reverse for READY/INPUT_REQUIRED via match_verdict`
    - *Verdict matching from loop_shared.match_verdict is deleted; replaced by Emission-based verdict extraction declared via output_emissions on the Stream subclass.*
- **MOVES**: `meta_pm_root forwarding (passes meta_pm_root through to prompt + launch cmd)` → `pm_core/streams/watchers/discovery_supervisor.py`
    - *Becomes Stream input/policy field; meta_pm_root represents the supervised project root and would be declared via the Stream's typed InputType.*
- **DELETES**: `WatcherState injection / pm_root construction`
    - *WatcherState is replaced by Stream.status (LifecycleState) + EmissionLog runtime_state.py fold-in. Construction handled by Mind.stream(role=..., instance_key=..., inputs=...).*
- **STAYS**: `configure_logger usage`
    - *pm_core.paths.configure_logger stays (paths.py mostly stays); call-site update only.*

  *Not in plan:*
  - Discovery-supervisor prompt generation: Add pm_core/prompts/watcher/discovery_supervisor.py as a typed InputType class wrapping the current generate_discovery_supervisor_prompt content (currently in pm_core/prompt_gen.py, which is slated for deletion).

  *Cross-cutting:* Depends on pm_core.watcher_base.BaseWatcher (deleted — becomes Stream base + WatcherSupervisor), pm_core.loop_shared.match_verdict (deleted — replaced by CallbackRegistry + Emission verdicts), pm_core.prompt_gen.generate_discovery_supervisor_prompt (deleted — must be re-encoded as a typed InputType under prompts/watcher/), and pm_core.wrapper (renamed to bootstrap.py; CLI entry point changes). Migration of this file is blocked on: (1) Stream base + WatcherSupervisor landing, (2) prompts/watcher/discovery_supervisor.py being added to the plan, (3) RuntimePlugin (TmuxHostRuntime) absorbing launch_cmd construction. Sibling watcher files (auto_start_watcher, bug_fix_impl, improvement_fix, watcher_review) share the same migration shape and should move together.

#### `pm_core/watchers/improvement_fix_impl_watcher.py`
*Watcher subclass for UX/improvement-fix PRs. Inherits BaseWatcher's loop engine; customizes prompt generation (via prompt_gen.generate_improvement_fix_impl_prompt), launch command (re-invokes via pm_core.wrapper), and verdict parsing. Unlike bug-fix watcher, does not auto-merge after QA PASS (held for human taste check).*

- **MOVES**: `ImprovementFixImplWatcher class (Stream subclass, no auto-merge)` → `pm_core/streams/watchers/improvement_fix_impl.py`
    - *Becomes a Stream subclass; loop_engine replaced by Stream base + WatcherSupervisor; verdict-as-emission via Emission/Mailbox; stop_before_merge encoded in StreamPolicy*
- **MOVES**: `generate_prompt (delegates to prompt_gen.generate_improvement_fix_impl_prompt)` → `pm_core/streams/watcher/improvement_fix.py`
    - *Becomes a typed InputType class; consumes project data via ProjectYamlArtifact*
- **DELETES**: `build_launch_cmd (re-invokes pm_core.wrapper)`
    - *Subsumed by RuntimePlugin (TmuxHostRuntime) launch path + bootstrap.py entry; per-watcher launch_cmd no longer hand-rolled*
- **MOVES**: `parse_verdict (READY/INPUT_REQUIRED via match_verdict)` → `pm_core/streams/watchers/improvement_fix_impl.py`
    - *VERDICTS classvar / ALLOWED_VERDICTS pattern from prompts/protocol.py; loop_shared.match_verdict deleted, predicate inlined into stream or shared helper inside streams/watchers/__init__*
- **MOVES**: `WATCHER_TYPE / DISPLAY_NAME / WINDOW_NAME / DEFAULT_INTERVAL metadata` → `pm_core/streams/watchers/improvement_fix_impl.py`
    - *tui_window_role / DEFAULT_INTERVAL become Stream classvars or schedule() args; registered in streams/watchers/__init__.py WATCHER_REGISTRY*
- **DELETES**: `WatcherState parameter / loop_id plumbing`
    - *WatcherState/loop_shared deleted; lifecycle/state encoded by EmissionLog + LifecycleState; loop_id replaced by correlation_id on Emission*
- **MOVES**: `meta_pm_root parameter (cross-project meta-PM context)` → `pm_core/streams/watchers/improvement_fix_impl.py`
    - *Becomes a Stream input or instance_key dim; cross-project handle should likely resolve via collaboration/identity.py ProjectIdentity*
- **MOVES**: `Hold-at-QA-PASS (no auto-merge) policy` → `pm_core/mind/policy.py`
    - *Encoded as StreamPolicy.stop_before_merge=True on the spawned PR action stream (or on the watcher's downstream PRStreamSupervisor policy)*

  *Not in plan:*
  - meta_pm_root cross-project context (a watcher running in project A but referencing meta-pm project B): Add a pm_root/project_id resolution helper to collaboration/identity.py (or sensorium/paths.py PathService) so watchers can take a target_project parameter and resolve artifacts from a sibling project

  *Cross-cutting:* Imports pm_core.watcher_base (deleted -> Stream base + WatcherSupervisor), pm_core.loop_shared (deleted -> CallbackRegistry), pm_core.prompt_gen (deleted -> prompts/watcher/improvement_fix.py), pm_core.wrapper (renamed -> bootstrap.py). Migration blocked until streams/base.py + watchers/__init__.py registry + prompts/watcher/improvement_fix.py exist. Sibling bug_fix_impl_watcher.py has parallel structure; both should migrate together. Referenced by pm watcher CLI group + TUI watcher_ui — those call-sites must update.

#### `pm_core/wrapper.py`
*Entry point shim that runs before pm_core is importable. Resolves which pm_core source dir to use via priority chain: (1) session override file at ~/.pm/sessions/<tag>/override, (2) session-persisted pm_root, (3) cwd-walk to find local pm_core, (4) installed pm_core. Also marks PM_IN_TMUX_SESSION env var, handles IPC command session-tag extraction from argv, and manipulates sys.path / sys.modules to swap pm_core before delegating to pm_core.cli.main.*

- **MOVES**: `main() entry point with sys.path manipulation and dispatch to pm_core.cli` → `pm_core/bootstrap.py`
    - *v2 explicitly says wrapper.py is RENAMED to bootstrap.py; this is the core function.*
- **MOVES**: `_get_session_tag — derive session tag from git repo (repo_name + md5 hash of git root path)` → `pm_core/bootstrap.py`
    - *Used by bootstrap-time session resolution before pm_core is importable; must stay in the shim. Audit gap G5: today this duplicates `paths.get_session_tag` independently and the on-disk contract drifts silently. The mind-class PR introduces `pm_core/_path_constants.py` (stdlib-only, no pm_core imports) defining `PM_HOME`, `SESSIONS_SUBDIR`, `PM_ROOT_FILENAME`, `PM_SHARE_MODE_ENV`. Both `bootstrap.py._get_session_tag` and `paths.get_session_tag` derive from those constants, and the parity test `tests/test_bootstrap_session_tag_matches_paths.py` covers PM_SHARE_MODE hashing + `use_github_name=True` branches.*
- **MOVES**: `_find_active_override — read ~/.pm/sessions/<tag>/override file` → `pm_core/bootstrap.py`
    - *Bootstrap-time concern (used to pick installed-vs-source pm_core).*
- **MOVES**: `find_local_pm_core — walk cwd up to 3 parents looking for pm_core/cli` → `pm_core/bootstrap.py`
    - *Explicitly listed in v2 bootstrap.py description as 'cwd-walk to find local pm_core'.*
- **MOVES**: `_mark_tmux_session — sets PM_IN_TMUX_SESSION env var when under tmux` → `pm_core/bootstrap.py`
    - *Trivial env marker that needs to happen before subcommand import; stays in shim.*
- **MOVES**: `_is_session_ipc_command — detect hidden IPC commands (_popup/_pane/_window/_tui/rebalance) from argv` → `pm_core/bootstrap.py`
    - *Needed before pm_core importable to choose IPC vs cwd-walk path.*
- **MOVES**: `_ipc_session_tag — extract session tag from tmux session positional argv for IPC commands` → `pm_core/bootstrap.py`
    - *Bootstrap concern — pairs with _is_session_ipc_command.*
- **MOVES**: `_session_tag — unified resolver (argv for IPC, cwd-derived otherwise)` → `pm_core/bootstrap.py`
    - *Bootstrap concern.*
- **MOVES**: `_pm_core_from_pm_root — resolve pm_core source dir from persisted pm_root file` → `pm_core/bootstrap.py`
    - *v2 bootstrap.py description names 'pm_root persistence' explicitly.*
- **MOVES**: `Logger configuration call (configure_logger('pm.wrapper') diagnostic logging)` → `pm_core/bootstrap.py`
    - *Logger name should likely be renamed to 'pm.bootstrap'; minor.*

  *Cross-cutting:* This file is the console_scripts entry point — setup.cfg / pyproject.toml [project.scripts] very likely references pm_core.wrapper:main and must be updated to pm_core.bootstrap:main as part of the rename. Imports pm_core.git_ops (STAYS) and pm_core.paths.configure_logger (paths.py STAYS per v2). Imports pm_core.cli.main (STAYS). The ~/.pm/sessions/<tag>/{override,pm_root} on-disk contract is shared with whatever writes those files (pm meta sessions / QA loops); renaming the module does not change the file format, but any other code that hardcodes the 'pm.wrapper' logger name needs updating. v2 'Deleted' section lists wrapper.py with the parenthetical 'RENAMED to bootstrap.py, stays' — confirming this is a pure rename + minor cleanup, not a functional redesign.

### DELETES_ENTIRELY (13)

#### `pm_core/claude_launcher.py`
*Multi-purpose Claude CLI launcher: builds Claude shell commands, manages session-id registry (load/save/clear), launches Claude in foreground/tmux/background/print modes, parses session ids from stderr, locates transcript files in ~/.claude/projects/, finalizes transcripts, resolves provider (claude/fake), and contains the fake-claude scripted-verdict subsystem.*

**Decision:** the file deletes; content distributes across the runtime tree. Previously listed under MOSTLY_STAYS; revised because the workflow audit found content widely absorbed and the user decided the file is at most a collection of shared helpers under `runtime/`.

- **MOVES**: `build_claude_shell_cmd / launch_claude / launch_claude_in_tmux / launch_claude_print / launch_claude_print_background / find_claude / find_editor / _skip_permissions / _resolve_provider` → `pm_core/runtime/tmux_host.py`
    - *Claude CLI invocation, flag construction, and binary discovery are TmuxHostRuntime's responsibility per the runtime-protocol-tmux PR scope.*
- **MANDATED CONSOLIDATION** (audit NG-2): the Claude CLI flag construction (`--dangerously-skip-permissions`, `--model`, `--effort`, `--allowedTools`, `--resume` / `--session-id`, `--input-format stream-json`) appears today in 5 sites with subtly different list-vs-string builders (`claude_launcher.py:442-453, 473-480, 527-539, 673-688, 832-837` + `bridge.py:184-190`). After this PR the flag-assembly lives in exactly one file: `pm_core/runtime/_claude_cli_flags.py` (a private helper module, sibling to `_claude_jsonl.py`). It exposes a single function — `build_claude_argv(*, claude_bin: str, system_prompt: str | None, model: str | None, effort: str | None, allowed_tools: list[str] | None, skip_permissions: bool, resume: ResumeSpec | None, input_format: Literal['stream-json', 'text'] | None = None, extra: list[str] = ()) -> list[str]` — used by both `TmuxHostRuntime` (foreground/tmux/print launchers) and `RawApiRuntime` (`_invoke_claude` body). No other module spells out the flag names. Invariant test: `tests/test_claude_cli_flags.py` snapshots the argv shape for each (skip_permissions, effort, resume, input_format) combination; renaming a flag updates one place.
- **MOVES**: `load_session / save_session / clear_session / _registry_path / _parse_session_id` → `pm_core/runtime/tmux_host.py`
    - *Session-id registry is runtime-internal state. TmuxHostRuntime owns it; the file path on disk stays the same.*
- **MOVES**: `session_id_from_transcript / transcript_path_for / _claude_project_dir / finalize_transcript` → `pm_core/runtime/_claude_jsonl.py`
    - *Claude's on-disk JSONL transcript layout (the ~/.claude/projects/ path conventions, symlink/finalize, session-id extraction from JSONL) consolidates into the private `_claude_jsonl.py` codec shared between TmuxHostRuntime (reads) and FakeClaudeRuntime (writes).*
- **DELETES**: `launch_bridge_in_tmux`
    - *Bridge subsystem deletes outright (see bridge.py below). Only consumer was `cli/cluster.py --bridged` flag which also deletes; cluster_exploration uses RawApiRuntime when programmatic control is wanted.*
- **MOVES**: `_fake_claude_config_for_type / _pick_fake_verdict / _clamp_cursor / _advance_scripted_cursor / _resolve_fake_verdict / _fake_claude_args / peek_fake_verdicts` → `pm_core/runtime/fake.py`
    - *Scripted-verdict + cursor + args machinery is FakeClaudeRuntime's behavior.*

If multiple Tmux* runtimes end up genuinely sharing a helper, the implementer may consolidate it into a private `pm_core/runtime/_claude_helpers.py`. Otherwise everything folds into the runtime impl that needs it.

  *Cross-cutting:* `find_editor()` is consumed by `Artifact.open_in_editor` in `sensorium/artifact/base.py` — that call site retargets to `runtime.tmux_host.find_editor` (or to a sensorium-local equivalent if sensorium can't import from runtime). `_resolve_provider` callers update to select runtime at `Mind.stream(runtime=...)` time. Test files (`tests/test_claude_launcher.py`) refactor against the new runtime split.

#### `pm_core/bridge.py`
*A standalone Python entrypoint (python -m pm_core.bridge) that hosts a Claude sub-agent inside a tmux pane. The Bridge class: (1) opens a Unix-domain socket server accepting JSON commands (status, take_control, release_control, send) from an orchestrating "Session A"; (2) reads stdin in HUMAN/AGENT modes so a human in the pane can toggle control with Enter; (3) invokes `claude -p --resume <session_id> --input-format stream-json` as a subprocess and streams assistant text + tool_use events to the pane; (4) maintains a single session_id across turns for resume continuity. The module also includes the argparse main() and signal handlers for SIGINT/SIGTERM shutdown.*

- **MOVES**: `Subprocess invocation of `claude -p --resume` with stream-json I/O and session_id continuity (_invoke_claude)` → `pm_core/runtime/raw_api.py`
    - *v2 explicitly says RawApiRuntime 'absorbs bridge.py's _invoke_claude semantics'. The session_id resume continuity becomes the RuntimePlugin's per-Stream session state. The argv-construction body (lines 184-190 today, which independently spells `--dangerously-skip-permissions` / `--resume` / `--input-format stream-json`) DELETES; RawApiRuntime calls `runtime/_claude_cli_flags.build_claude_argv(...)` shared with TmuxHostRuntime. See the NG-2 consolidation note under claude_launcher.py.*
- **MOVES**: `Streaming of assistant text and tool_use events back to a visible surface` → `pm_core/runtime/raw_api.py`
    - *Per-turn streaming output becomes Emission emission on the Stream; visible-pane rendering is handled by whichever Tmux* runtime composes with it (HybridRuntime) or by Stream transcript replay.*
- **DELETES**: `Unix-socket JSON command surface (status / take_control / release_control / send) for cross-process orchestration`
    - *The socket protocol deletes outright — pm has no external-process control plane after this PR. Today's only consumer (`cli/cluster.py --bridged` flag via `launch_bridge_in_tmux`) also deletes. Mailbox delivery (in-process) covers stream-to-stream messaging; AttentionService + ControlOwner cover human takeover via the TUI. There is no replacement for "external program drives a Claude session via socket."*
- **MOVES**: `AGENT/HUMAN mode toggle and ControlOwner state machine` → `pm_core/mind/attention.py`
    - *Becomes AttentionService + ControlOwner enum (HUMAN/AGENT) + AttentionRequest. v2 explicitly calls out 'AttentionRequest' as a split-target for bridge.py.*
- **MOVES**: `Stdin reader loop with Enter-to-toggle UX in a tmux pane` → `pm_core/runtime/tmux_host.py`
    - *Pane-side human input + control-toggle keybinding becomes a TmuxHostRuntime concern (paired with HybridRuntime when composed with RawApiRuntime). The Enter-toggle itself is a TUI keybinding configured by the Stream subclass.*
- **MOVES**: `Busy flag preventing concurrent turns / ack protocol on send` → `pm_core/mind/mailbox.py`
    - *Mailbox's preempt/next-checkpoint delivery semantics + Stream's LifecycleState replace the ad-hoc busy flag and JSON ack.*
- **DELETES**: `Unix-socket lifecycle (bind, unlink on shutdown) + signal handlers + argparse main()`
    - *There is no longer a standalone bridge process; sub-agent invocation happens via Mind.stream(...) + RuntimePlugin. main() and its socket plumbing have no replacement and need none.*
- **MOVES**: `skip_permissions_enabled() lookup for --dangerously-skip-permissions flag` → `pm_core/runtime/raw_api.py`
    - *Flag selection moves with _invoke_claude into RawApiRuntime; pm_core/paths.py (the source of skip_permissions_enabled) is listed under Stays.*
- **MOVES**: `Session-id persistence across turns for `claude --resume`` → `pm_core/runtime/raw_api.py`
    - *Per-Stream session_id is RuntimePlugin internal state. Optional: could also be surfaced via EmissionLog stream_id correlation but the resume token itself is runtime-internal.*

  *Cross-cutting:* bridge.py is invoked by bridge_client.py (the orchestrator side) — both are listed together in v2's Deleted section, so they must be migrated as a pair. The split target is explicit: RawApiRuntime + Mailbox + AttentionRequest. Dependency on pm_core/paths.skip_permissions_enabled() is preserved (paths.py stays). The `claude -p` CLI invocation pattern here overlaps semantically with pm_core/claude_launcher.py (which TmuxHostRuntime wraps) — RawApiRuntime and TmuxHostRuntime should share a small helper for skip-permissions/--resume flag assembly to avoid drift, or be composed via HybridRuntime when both human-visible pane and direct-API turns are wanted. The HUMAN/AGENT toggle UX (Enter-to-takeover) is the concrete UX shape that AttentionService + ControlOwner must support; the AttentionService design should preserve the property that takeover is preempt-at-turn-boundary, not mid-turn (the busy flag currently enforces this).

#### `pm_core/bridge_client.py`
*A thin synchronous Unix-socket JSON client for the Agent Bridge daemon. Wraps four operations: send_message (write a message, wait for ack + turn_end response), take_control / release_control (AGENT vs HUMAN mode switching), and get_status (mode + busy state). Pure transport — no policy, no schema beyond {cmd, message}.*

- **DELETES**: `Unix socket JSON line protocol (connect, _send, close)`
    - *Transport detail of the old bridge daemon. The v2 RuntimePlugin seam replaces the bridge-as-out-of-process model. RawApiRuntime invokes Claude directly via SDK; TmuxHostRuntime drives the live session. No client-side socket transport is needed.*
- **MOVES**: `send_message (synchronous request/response with Claude)` → `pm_core/runtime/raw_api.py`
    - *v2 plan explicitly says bridge.py's _invoke_claude semantics get absorbed into RawApiRuntime. The send-and-wait-for-turn-end behavior becomes a RuntimePlugin invocation; the result surfaces as an Emission on the StreamTranscript / EmissionLog.*
- **MOVES**: `take_control / release_control (AGENT vs HUMAN mode toggle)` → `pm_core/mind/attention.py`
    - *Per the deletion note 'bridge.py + bridge_client.py (split: RawApiRuntime + Mailbox + AttentionRequest)'. Control ownership becomes ControlOwner enum + AttentionService/AttentionRequest. The mode-toggle API surface is replaced by the attention/control-owner model.*
- **MOVES**: `get_status (mode + busy)` → `pm_core/streams/base.py`
    - *Busy/idle and control owner are now first-class on Stream (Stream.status: LifecycleState) and ControlOwner (in lifecycle.py / attention.py). No separate status RPC needed; consumers read Stream.status and AttentionService state.*
- **DELETES**: `Error mapping (event=='error' → RuntimeError; closed connection → ConnectionError)`
    - *No longer applicable: errors surface as Emissions on the EmissionLog with tag/visibility, not as RPC error envelopes. Closed-connection semantics are runtime-internal to each RuntimePlugin.*

  *Cross-cutting:* bridge_client.py is the consumer-facing half of the bridge.py daemon pair — they must be deleted together. Any caller that imports BridgeClient (likely CLI subcommands that drive an existing bridge session, and possibly meta-development / discuss flows) is blocked on the RawApiRuntime + AttentionService migration landing first. Worth grepping for `BridgeClient` and `bridge_client` to enumerate callers and route each to either (a) a Stream + RuntimePlugin invocation, or (b) AttentionService.request_control / release calls. The take_control/release_control surface in particular implies an existing interactive (likely tmux) Claude session whose control the user wants to seize — i.e., the migration target is plausibly TmuxHostRuntime + AttentionService, not RawApiRuntime, for those two methods.

#### `pm_core/bug_fix_prompts.py`
*Three helpers for bug-fix flow: _is_bug_pr (detects bug PRs), _bug_fix_flow_block (impl-prompt block with captures dir + 5-step flow), _bug_fix_review_block (review checklist for bug fixes). Currently imported and re-exported by prompt_gen.py.*

- **MOVES**: `_is_bug_pr — detect bug-fix PRs via plan==bugs or type==bug` → `pm_core/streams/_shared_prompts.py`
    - *Detection helper shared by impl_system, review_system, and qa prompts so they stay in sync. Fits the _shared.py 'cross-prompt fragments' bucket.*
- **MOVES**: `_bug_fix_flow_block — impl-side bug-fix flow (captures dir + 5-step manual repro/test/fix/verify)` → `pm_core/streams/impl_system.py`
    - *Conditionally appended to ImplSystemPrompt when _is_bug_pr(pr). Alternative target: pm_core/prompts/_shared.py if reused by regression/impl_fix.py as well.*
- **MOVES**: `_bug_fix_review_block — review-side bug-fix checklist (pre/post captures, failing test, scope)` → `pm_core/streams/review_system.py`
    - *Conditionally appended to ReviewSystemPrompt when _is_bug_pr(pr).*

  *Cross-cutting:* prompt_gen.py imports and re-exports these three symbols for backward compat; prompt_gen.py is itself slated for deletion (extracted into typed InputType classes under pm_core/prompts/). Migration of bug_fix_prompts.py is coupled with the prompt_gen.py extraction — both must move together. The blocks reference `pm qa captures-path <pr-id>` CLI and `~/.pm/sessions/<session-tag>/captures/...` paths; those CLI/path semantics need to remain stable (CaptureBundle / CaptureService in sensorium/captures.py) or the prompt text must be updated when captures move.

#### `pm_core/editor.py`
*Provides run_watched_editor: writes a template to a temp file, launches $EDITOR via find_editor(), and runs a daemon thread that polls the temp file's mtime; on each detected save it reads the file and invokes an on_save callback. Cleans up the temp file and runs a final poll after the editor exits. Returns (exit_code, was_modified).*

- **MOVES**: `temp-file template seed + launch $EDITOR` → `pm_core/sensorium/artifact/base.py`
    - *Per v2 'Deleted' section: 'editor.py becomes Artifact.open_in_editor + watch_for_save on the base'. The 'write template -> launch editor' half maps to Artifact.open_in_editor / Artifact.edit_interactively on the base Artifact class.*
- **MOVES**: `mtime-polling save detection + on_save callback dispatch (daemon thread + final post-exit poll)` → `pm_core/sensorium/artifact/base.py`
    - *Maps to Artifact.watch_for_save (and the related _on_external_change hook listed for the Artifact base). The polling+callback mechanic is the implementation behind watch_for_save.*
- **MOVES**: `temp file cleanup (os.unlink in finally)` → `pm_core/sensorium/artifact/base.py`
    - *Becomes an internal detail of Artifact.edit_interactively / open_in_editor lifecycle.*
- **MOVES**: `find_editor() resolution` → `pm_core/runtime/tmux_host.py`
    - *find_editor was in claude_launcher.py; under the revised decision, claude_launcher.py deletes and find_editor moves into runtime/tmux_host.py with the other binary-discovery helpers. `Artifact.open_in_editor` calls `runtime.tmux_host.find_editor` (or, if sensorium can't import from runtime, a sensorium-local re-export pattern). Implementer decides per import-graph constraints.*

  *Cross-cutting:* Callers of run_watched_editor (likely CLI commands that edit plans/notes/specs interactively, e.g. pm plan edit / pm note edit) will need to be migrated to obtain the relevant Artifact (PlanArtifact, NotesSectionArtifact, SpecArtifact, etc.) and call artifact.edit_interactively() instead. Migration of editor.py is blocked until Artifact base + at least PlanArtifact/NotesSectionArtifact exist, and conversely the sensorium Artifact base cannot claim 'editor support' as done until those callers are switched over.

#### `pm_core/hook_events.py`
*Reader-side API for Claude Code hook events: locates per-session JSON event files under ~/.pm/hooks/, exposes read/clear primitives, checks ~/.claude/settings.json for hook installation, and provides wait_for_event polling for idle/stop signals matching given event_types newer than a watermark.*

- **DELETES**: `hooks_dir / event_path / read_event / clear_event (per-session JSON file I/O)` → `pm_core/runtime/hook_entry.py`
    - *Hook event delivery is re-encoded as Emissions flowing through RuntimePlugin → EmissionLog. The on-disk ~/.pm/hooks/{session_id}.json transport is an internal detail of the TmuxHostRuntime + runtime/hook_entry.py pair; readers no longer touch files directly. Absorbed by pm_core/runtime/tmux_host.py and pm_core/runtime/hook_entry.py.*
- **DELETES**: `hooks_available() — settings.json installation probe` → `pm_core/runtime/tmux_host.py`
    - *v2 plan deletes hook_install.py + hook_receiver.py and folds hook installation/detection into runtime/hook_entry.py + TmuxHostRuntime internals. Capability surfaces via RuntimePlugin.supports_hooks instead of a global filesystem probe.*
- **DELETES**: `wait_for_event() — poll for idle/stop event matching event_types newer than watermark` → `pm_core/mind/callbacks.py`
    - *Replaced by CallbackRegistry.wait_for(not_before=, predicate=, grace_period=) over Emissions on the stream's EmissionLog/Mailbox. The session_id-keyed file polling is superseded by stream-id keyed log reads.*
- **MOVES**: `Event schema (event_type, timestamp fields)` → `pm_core/mind/emissions.py`
    - *The idle/stop/permission event categories become typed Emissions / VisibilityTier-tagged log entries. Schema versioning per emissions.py Emission.schema_version.*

  *Cross-cutting:* Anything currently importing hook_events (pane_idle, qa_status, watcher loops, signoff loops) will need migration to CallbackRegistry.wait_for over Emissions. The ~/.pm/hooks/{session_id}.json flat-dir contract is shared with hook_receiver.py (also slated for deletion) and the container variant of the writer — both writer and reader collapse into pm_core/runtime/hook_entry.py + TmuxHostRuntime/TmuxContainerRuntime. Migration of this file is blocked until RuntimePlugin emits idle/stop Emissions and CallbackRegistry.wait_for(predicate=) is available, since every current caller needs a substitute.

#### `pm_core/loop_shared.py`
*Shared helpers for review/qa/watcher loops: tmux session/pane discovery, verdict-line matching, marker-bracket text extraction, and two hook-driven polling functions (poll_for_verdict, wait_for_follow_up_verdict) that wait for Claude idle_prompt events and extract a verdict from the JSONL transcript.*

- **DELETES**: `get_pm_session`
    - *Wrapper around _get_current_pm_session; folds into TmuxHostRuntime internals + sensorium/leases TmuxWindowKey resolution. Plan explicitly lists loop_shared.py under Deleted.*
- **DELETES**: `find_claude_pane` → `pm_core/runtime/tmux_host.py`
    - *Pane lookup by window name becomes a runtime-internal detail of TmuxHostRuntime (tmux.py stays as substrate).*
- **MOVES**: `match_verdict` → `pm_core/streams/protocol.py`
    - *Verdict-keyword matching against ALLOWED_VERDICTS classvar belongs with the InputType Protocol pattern (ALLOWED_VERDICTS). Could also live as a small helper in prompts/_shared.py.*
- **MOVES**: `extract_between_markers` → `pm_core/streams/_shared_prompts.py`
    - *Marker-bracket extraction is a cross-prompt parsing fragment shared by review/qa/watcher prompt output — fits the _shared.py 'cross-prompt fragments' bucket. Alternatively lives next to InputType.parse_output on protocol.py.*
- **DELETES**: `poll_for_verdict` → `pm_core/mind/callbacks.py`
    - *Plan explicitly says 'loop_shared.py (replaced by CallbackRegistry)'. The idle-prompt + verdict-extraction polling loop is re-encoded as CallbackRegistry.wait_for with not_before/predicate/grace_period. Hook event source moves to runtime/hook_entry.py; transcript reads move to pm-owned StreamTranscript.*
- **DELETES**: `wait_for_follow_up_verdict` → `pm_core/mind/callbacks.py`
    - *Same — second wait variant collapses into CallbackRegistry.wait_for parameterized by predicate over emissions from StreamTranscript / EmissionLog.*
- **DELETES**: `VERDICT_TAIL_LINES constant`
    - *Pane-tail scanning no longer needed; pm-owned StreamTranscript replaces verdict_transcript scanning, and verdicts are typed Emissions, not regex over scrollback.*
- **DELETES**: `session_id recovery from transcript symlink` → `pm_core/runtime/tmux_host.py`
    - *session_id_from_transcript dependency disappears once Stream id is the canonical identifier; TmuxHostRuntime maps Stream id <-> tmux session_id internally.*

  *Cross-cutting:* Imported by review_loop, qa_loop, watcher_loop (all listed as Deleted/rewritten — those rewrites must land first or simultaneously, since they consume match_verdict / extract_between_markers / poll_for_verdict). Depends on pm_core.hook_events (not mentioned in plan — likely folds into runtime/hook_entry.py + RuntimePlugin event seam; worth confirming), pm_core.verdict_transcript (explicitly Deleted, replaced by pm-owned StreamTranscript), pm_core.claude_launcher (Stays, consumed by TmuxHostRuntime), pm_core.tmux (Stays as substrate). The extract_between_markers helper is also likely used outside the loops (e.g., spec_gen / qa_finalize prompt parsers) — grep before deleting to make sure all parse-output sites get migrated to prompts/_shared.py.

#### `pm_core/pane_idle.py`
*Thread-safe tracker of per-pane Claude session idle/waiting-for-input/gone state, driven entirely by Claude Code hook events (read via hook_events.read_event(session_id)) plus tmux.pane_exists liveness checks. Also mirrors pane/session bookkeeping into runtime_state under per-action keys (start/qa/merge/review) so the popup picker and status spinner can resolve idle/working state, with special handling for QA scenarios (per-scenario subkey aggregation) and preservation of terminal verdicts on unregister.*

- **MOVES**: `PaneIdleState dataclass (per-pane idle/waiting/gone/timestamp/notified flags)` → `pm_core/runtime/tmux_host.py`
    - *Per-pane lifecycle bookkeeping is a TmuxHostRuntime-internal detail; collapses into runtime's stream state. Lifecycle bits (idle/working/gone) project onto LifecycleState in pm_core/agent/lifecycle.py.*
- **MOVES**: `PaneIdleTracker.register / unregister (start tracking a pane keyed by pr_id/qa:.../merge:.../review:...)` → `pm_core/runtime/tmux_host.py`
    - *Registration becomes implicit when TmuxHostRuntime.attach()/start() opens a stream; the key/role mapping is replaced by Stream id + role.*
- **MOVES**: `PaneIdleTracker.poll (read hook event, update flags, check tmux.pane_exists)` → `pm_core/runtime/tmux_host.py`
    - *Hook event consumption moves into runtime/hook_entry.py which forwards into TmuxHostRuntime; pane_exists liveness probe stays runtime-internal. Idle/working transitions get emitted as Emissions on the stream's lifecycle channel.*
- **MOVES**: `is_idle / is_waiting_for_input / is_gone / became_idle / mark_active / tracked_keys / get_transcript_path (pure read accessors)` → `pm_core/runtime/tmux_host.py`
    - *Callers (TUI/picker) should query Stream.status (LifecycleState) and lifecycle Emissions on AttentionGlobalChannel/LifecycleGlobalChannel rather than poking a tracker. waiting_for_input becomes an AttentionRequest via AttentionService (pm_core/agent/attention.py). became_idle becomes a one-shot subscription via CallbackRegistry (pm_core/agent/callbacks.py). get_transcript_path is replaced by Mind.transcript_of(stream_id) on pm_core/agent/transcript.py.*
- **DELETES**: `_runtime_target / _qa_scenario_subkey key-parsing helpers (pr_id, action) extraction from tracker keys`
    - *String-keyed pr_id/action routing is obsolete once Streams have typed instance_keys and roles; PRStreamSupervisor (pm_core/supervisors/pr_stream.py) owns the mapping explicitly.*
- **DELETES**: `_runtime_mirror_register / _runtime_mirror_clear (write to runtime_state with per-action panes[]/verdict preservation; QA scenario aggregation)`
    - *runtime_state.py is explicitly deleted in v2 (folds into EmissionLog + lifecycle.py). The mirror's purpose — letting the picker derive [idle]/[working]/[done VERDICT] per (pr_id, action) — is reconstituted from EmissionLog queries against the PR's streams, with verdicts represented as terminal-state Emissions on the stream (PRStreamSupervisor aggregates per-PR action status). QA scenario aggregation moves into PRStreamSupervisor's view over multiple QaScenarioStream instances.*
- **MOVES**: `Thread-safety (RLock around dict mutations across TUI main thread + review loop background thread)` → `pm_core/runtime/tmux_host.py`
    - *Concurrency contract migrates with the runtime; EmissionLog (pm_core/agent/log.py) is already specified as SQLite + idempotent append, which subsumes most cross-thread state coordination.*

  *Not in plan:*
  - QA scenario aggregation semantics: 'show [idle] only when ALL live scenarios are idle, not when any one goes idle' — currently implemented via panes[subkey] dict in runtime_state mirror.: Add to pm_core/supervisors/pr_stream.py spec an explicit 'action_status(pr_id, role) -> Status' method documenting the aggregation rule (idle iff all member streams idle; working if any working; done+verdict preserved across teardown). Worth a one-line callout in plan-mind or in PRStreamSupervisor's docstring section.
  - Terminal-verdict preservation on stream/pane teardown ('keep [done LGTM] visible after the review pane closes'): Document on Stream.status / LifecycleState in pm_core/agent/lifecycle.py that terminal-state Emissions remain queryable after lifecycle ends; or note in PRStreamSupervisor that action_status falls back to the last terminal Emission. No new file needed — just a contract clarification.
  - Permission-prompt (Claude Code tool-approval dialog) as a first-class state distinct from plain idle: In pm_core/runtime/hook_entry.py spec, list permission_prompt -> AttentionRequest(owner=ControlOwner.USER, reason='tool_approval') as one of the standard hook->emission translations.

  *Cross-cutting:* Consumers of PaneIdleTracker that block its deletion until they migrate: TUI poll timer (pm_core/tui/), review_loop.py (background-thread caller), qa_loop.py (sets qa:<pr_id>:s<N> keys), watcher_base.py/watcher_manager.py, picker/status spinner code. All of these are themselves slated for rewrite (review_loop->ReviewStream, qa_loop->Qa*Stream, watcher_*->Stream+WatcherSupervisor, runtime_state->EmissionLog), so pane_idle.py's deletion is gated on completing TmuxHostRuntime + EmissionLog + the Stream rewrites — it cannot move independently. Also depends on pm_core/hook_events.py (read_event) and pm_core/claude_launcher.py (session_id_from_transcript); hook_events folds into runtime/hook_entry.py per the plan, claude_launcher stays.

#### `pm_core/pr_cleanup.py`
*Best-effort teardown of every live resource attached to a PR: tmux windows (impl/review/merge/qa/qa-scenario), QA containers, push-proxy sockets, pane-registry entries, and the per-PR runtime_state json. Provides a summary dict and a human-readable formatter.*

- **DELETES**: `_candidate_window_names — enumerate tmux + registry windows belonging to a PR (impl/review/merge/qa + qa-scenario prefix)`
    - *In v2, each Stream owns its own tmux window via ResourceLease(TmuxWindowKey). Enumeration becomes 'iterate streams owned by PRStreamSupervisor' rather than name-prefix scanning.*
- **MOVES**: `kill PR tmux windows (via kill_pr_windows)` → `pm_core/supervisors/pr_stream.py`
    - *PRStreamSupervisor.shutdown() iterates owned streams; each Stream's TmuxHostRuntime/TmuxContainerRuntime releases its TmuxWindowKey lease, which kills the window.*
- **MOVES**: `cleanup PR containers (container_mod.cleanup_pr_containers)` → `pm_core/runtime/tmux_container.py`
    - *Container teardown becomes TmuxContainerRuntime.shutdown(); ContainerKey lease release in sensorium/leases.py drives it.*
- **MOVES**: `stop push-proxy sockets for lingering containers` → `pm_core/runtime/push_proxy.py`
    - *push_proxy daemon owns its own socket lifecycle; TmuxContainerRuntime.shutdown calls into it. Standalone 'lingering socket' sweep becomes push_proxy internal reconcile.*
- **MOVES**: `unregister pane-registry entries for PR windows` → `pm_core/sensorium/leases.py`
    - *Pane registry is subsumed by ResourceLease (TmuxWindowKey); releasing the lease unregisters. Foundational pane_registry.py stays per v2, but cleanup path moves into lease release.*
- **DELETES**: `delete per-PR runtime_state JSON (~/.pm/runtime/{pr_id}.json)`
    - *runtime_state.py is explicitly deleted in v2 ('folds into EmissionLog + lifecycle.py'). No file to unlink; lifecycle terminal state in EmissionLog supersedes.*
- **MOVES**: `cleanup_pr_resources orchestration entry point (callable from CLI/TUI)` → `pm_core/supervisors/pr_stream.py`
    - *Becomes PRStreamSupervisor.shutdown(pr) — fans out across owned streams' runtime.shutdown() and lease releases.*
- **MOVES**: `format_summary — human-readable cleanup result string` → `pm_core/supervisors/pr_stream.py`
    - *Either a method on PRStreamSupervisor or a small helper there; consumed by CLI 'pm pr cleanup' surface. Could alternately stay in pm_core/cli/ as a presentation helper.*
- **UNCLEAR**: `summary dict schema {windows, containers, registry_windows, sockets, runtime_state}`
    - *v2 doesn't specify a typed teardown-summary artifact. If CLI/TUI still surface a count, PRStreamSupervisor.shutdown should return a typed dataclass; otherwise emissions on LifecycleGlobalChannel suffice.*

  *Cross-cutting:* Callers: pm_core/cli/helpers and likely pm pr cleanup CLI + TUI 'd' keybinding paths import cleanup_pr_resources/format_summary — those call sites must migrate to PRStreamSupervisor.shutdown(). Imports container, pane_registry, push_proxy, runtime_state, tmux, cli.helpers — three of those (container.py, runtime_state.py, kill_pr_windows in cli helpers) are themselves deleted/relocated in v2, so pr_cleanup's removal is coupled to those migrations and should land in the same wave as TmuxContainerRuntime + PRStreamSupervisor + leases.py landing. The qa-scenario window prefix scanning is a workaround for windows outliving registry entries — v2 ResourceLease should make this reconciliation unnecessary; flag for verification when implementing TmuxWindowKey lease release semantics.</cross_cutting_notes> <parameter name="not_in_plan">[   {"responsibility": "Reconciliation sweep for orphaned tmux windows / sockets whose owning Stream/runtime crashed without releasing leases", "why_not_covered": "v2 assumes lease release on Stream shutdown is reliable, but pr_cleanup today exists precisely because that assumption fails (qa-scenario windows outliving registry; sockets outliving containers).", "recommendation": "Add a reconcile() method to sensorium/leases.py (or a small pm_core/sensorium/reconcile.py) that PRStreamSupervisor.shutdown invokes after best-effort stream shutdown to sweep stale leases by ResourceKey prefix. Mention in plan-sensorium under leases."},   {"responsibility": "CLI/TUI-visible cleanup summary (counts of windows/containers/registry entries cleaned)", "why_not_covered": "v2 supervisor shutdown is described in terms of lifecycle emissions, not a returned summary structure consumed by user-facing surfaces.", "recommendation": "Define PRStreamSupervisor.shutdown() -> TeardownReport dataclass; small addition to pm_core/supervisors/pr_stream.py or protocol.py. Safe to inline without a separate plan."} ]

#### `pm_core/review_loop.py`
*Synchronous and threaded review loop: launches a tmux review window via `pm pr review --fresh --review-loop`, polls a JSONL transcript for verdict via Claude Code hooks, classifies PASS/NEEDS_WORK/INPUT_REQUIRED/KILLED, handles INPUT_REQUIRED follow-up polling against the existing pane, tracks per-iteration history, and exposes a background-thread runner with on_iteration/on_complete callbacks.*

- **MOVES**: `Verdict constants and ALL_VERDICTS` → `pm_core/streams/review_system.py`
    - *Becomes ALLOWED_VERDICTS classvar per prompts/protocol.py*
- **MOVES**: `parse_review_verdict and _match_verdict` → `pm_core/streams/review.py`
    - *Verdict parsing on ReviewStream; loop_shared.match_verdict is deleted*
- **MOVES**: `ReviewIteration dataclass` → `pm_core/mind/emissions.py`
    - *Per-iteration history becomes Emissions in EmissionLog*
- **MOVES**: `ReviewLoopState` → `pm_core/streams/review.py`
    - *Replaced by ReviewStream instance state plus LifecycleState*
- **MOVES**: `_generate_loop_id` → `pm_core/streams/review.py`
    - *Becomes instance_key/correlation_id via Mind.stream()*
- **MOVES**: `_compute_review_window_name` → `pm_core/runtime/tmux_host.py`
    - *Window naming is TmuxHostRuntime; role declared on PRActionStream.tui_window_role*
- **MOVES**: `_launch_review_window subprocess` → `pm_core/runtime/tmux_host.py`
    - *Launch is RuntimePlugin job, uses claude_launcher*
- **DELETES**: `_find_claude_pane and _get_pm_session wrappers`
    - *Thin wrappers over deleted loop_shared; tmux helpers stay in pm_core/tmux.py*
- **MOVES**: `_poll_for_verdict` → `pm_core/mind/callbacks.py`
    - *CallbackRegistry.wait_for(not_before/predicate/grace_period); transcript via StreamTranscript*
- **MOVES**: `PaneKilledError` → `pm_core/lifecycle.py`
    - *Becomes a TerminationReason*
- **MOVES**: `_run_claude_review (single iteration orchestration)` → `pm_core/streams/review.py`
    - *ReviewStream advance under LoopMode.kill_restart*
- **MOVES**: `_wait_for_follow_up_verdict (INPUT_REQUIRED handling)` → `pm_core/mind/attention.py`
    - *AttentionRequest with ControlOwner handoff to human; resume via callback*
- **MOVES**: `should_stop (PASS-only stop predicate)` → `pm_core/policy.py`
    - *StreamPolicy.consecutive_pass_threshold*
- **MOVES**: `run_review_loop_sync (loop body plus history plus on_iteration)` → `pm_core/streams/review.py`
    - *Becomes ReviewStream driven by LoopMode.kill_restart, bounded by StreamPolicy.max_iterations*
- **MOVES**: `start_review_loop_background (thread wrapper plus on_complete)` → `pm_core/supervisors/pr_stream.py`
    - *Background lifecycle owned by PRStreamSupervisor*
- **MOVES**: `max_iterations safety cap` → `pm_core/policy.py`
    - *StreamPolicy.max_iterations*
- **MOVES**: `_VERDICT_GRACE_PERIOD constant` → `pm_core/mind/callbacks.py`
    - *grace_period parameter on CallbackRegistry.wait_for*

  *Not in plan:*
  - Repeated-INPUT_REQUIRED demotion to NEEDS_WORK (anti-loop heuristic): Add max_consecutive_attention_requests (or repeated_attention_action) to StreamPolicy in pm_core/policy.py
  - UI notification de-dup flags (_ui_notified_done, _ui_notified_input): Use Emission.dedup_key on lifecycle-tier emissions consumed by pm_core/watchdog/tui.py; no new structure needed

  *Cross-cutting:* Imports pm_core.loop_shared (slated for deletion, replaced by CallbackRegistry) and pm_core.paths.configure_logger (paths.py mostly stays). The companion pm_core/tui/review_loop_ui.py becomes a thin delegator per the TUI-shim pattern; its migration is gated on ReviewStream existing. The CLI 'pm pr review --review-loop' entrypoint (pm_core/cli/) and the self-respawning subprocess collapse once ReviewStream runs in-process under PRStreamSupervisor. verdict_transcript.py (deleted in v2) and loop_shared.py (deleted) are tightly entangled with this file and should be removed in the same refactor wave.

#### `pm_core/verdict_transcript.py`
*Reads Claude Code JSONL session transcripts and extracts (a) the latest assistant-turn verdict keyword via boundary-aware regex and (b) the concatenated text content of the latest assistant turn. Includes a symlink/session-id glob recovery fallback for mismatched transcript paths.*

- **DELETES**: `extract_verdict_from_transcript (boundary-aware verdict regex over latest assistant turn)` → `pm_core/mind/transcript.py + pm_core/runtime/hook_entry.py`
    - *v2 plan explicitly lists verdict_transcript.py under Deleted: 'replaced by pm-owned StreamTranscript capture'. Verdicts will be extracted/emitted by RuntimePlugin impls (raw_api.py/tmux_host.py/hook_entry.py) writing structured Emissions tagged with the verdict into EmissionLog/StreamTranscript, eliminating the need to scrape Claude-owned JSONL post-hoc.*
- **DELETES**: `read_latest_assistant_text (parse JSONL records, collect message.content[].type==text from latest turn)` → `pm_core/mind/transcript.py`
    - *Same rationale — pm-owned StreamTranscript captures assistant text as Emissions directly; callers in loop_shared (which is itself deleted) and elsewhere will read from StreamTranscript/EmissionLog instead of scraping Claude's JSONL.*
- **DELETES**: `_read_transcript_text (symlink/session-id glob fallback for build_claude_shell_cmd path mismatch — pr-488b748 band-aid)` → `pm_core/mind/transcript.py (replaced concept)`
    - *Band-aid for Claude Code's transcript-symlink behavior. With pm-owned StreamTranscript writing to flat per-stream files under pm's control (not ~/.claude/projects), the slug-mismatch problem disappears. The recovery logic has no analog in v2.*
- **DELETES**: `_ASSISTANT_RE/_USER_RE schema-light JSONL record-type detection`
    - *Coupling to Claude Code's JSONL shape goes away once pm owns the transcript format. Record-type discrimination becomes Emission.kind / role on the pm side.*

  *Not in plan:*
  - Boundary-aware verdict-keyword matching (rejecting 'PASS this file' while accepting '**PASS**' alone, with markdown-bold/code tolerance and longest-match-first): Add a small verdict-parser utility either in pm_core/prompts/protocol.py (alongside ALLOWED_VERDICTS) or in pm_core/agent/transcript.py (as StreamTranscript.latest_verdict(allowed: set[str]) -> str | None). The latter is cleaner because StreamTranscript is the read seam for emitted assistant text.
  - Robustness fallback when the transport layer (Claude Code) writes to a different path than expected: When implementing runtime/hook_entry.py, ensure it resolves the Stream id from the hook event rather than relying on cwd-derived paths — codify the lesson from pr-488b748 as a docstring/test there. No new file needed.

  *Cross-cutting:* Direct callers that block this file's deletion: (1) loop_shared.py uses read_latest_assistant_text for REFINED_STEPS_START/END marker extraction — loop_shared is itself slated for deletion (replaced by CallbackRegistry), and the marker-extraction pattern needs to be re-encoded as a typed Emission or an InputType/Artifact in pm_core/prompts or pm_core/artifacts. (2) qa_loop.py / review_loop.py / signoff.py / qa_status.py / pane_idle.py likely consume extract_verdict_from_transcript for verdict detection — all are slated for deletion and the verdict signal becomes a structured Emission carried via StreamTranscript/EmissionLog. (3) Any RuntimePlugin that wraps Claude Code (TmuxHostRuntime, TmuxContainerRuntime, TmuxSandboxRuntime) must, before this file is removed, learn to emit verdict Emissions itself — likely through runtime/hook_entry.py, which is the Claude-Code-hook shim that forwards events to RuntimePlugin. The "verdict keyword on its own boundary-bounded line" semantics need to survive somewhere — probably as a small utility inside hook_entry.py or as a parser on the InputType/prompt side declaring ALLOWED_VERDICTS (the prompts/protocol.py ALLOWED_VERDICTS classvar pattern suggests verdict matching moves to prompts/).

#### `pm_core/watcher_base.py`
*Base watcher framework: abstract BaseWatcher class with shared polling loop, tmux pane management, state persistence (WatcherState/WatcherIteration), INPUT_REQUIRED escalation handling, verdict parsing hooks, background-thread orchestration. Concrete watchers (auto_start, bug_fix, etc.) subclass and implement generate_prompt/build_launch_cmd/parse_verdict/on_verdict.*

- **DELETES**: `BaseWatcher abstract class + run_sync polling loop`
    - *Re-encoded as pm_core/streams/base.py Stream base + pm_core/supervisors/watcher.py WatcherSupervisor. The loop engine becomes Stream lifecycle + CallbackRegistry.wait_for + LoopMode.continue_existing.*
- **DELETES**: `WatcherState dataclass (iteration, latest_verdict, history, loop_id, input_required)`
    - *Replaced by StreamRecord (pm_core/supervisors/protocol.py) + LifecycleState (pm_core/agent/lifecycle.py) + EmissionLog (pm_core/agent/log.py) for history persistence.*
- **DELETES**: `WatcherIteration dataclass (per-iteration verdict snapshot)`
    - *Replaced by Emission entries in EmissionLog (pm_core/agent/emissions.py + log.py).*
- **DELETES**: `generate_loop_id()`
    - *Stream/instance ids generated by Mind.stream() in pm_core/mind.py.*
- **MOVES**: `VERDICTS/KEYWORDS class config + parse_verdict abstract method` → `pm_core/streams/base.py`
    - *Becomes Stream.output_emissions classvar; verdict parsing moves into runtime/hook_entry.py emission decoding. Per-watcher prompt logic moves to pm_core/prompts/watcher/{auto_start,bug_fix,improvement_fix,watcher_review}.py.*
- **DELETES**: `_launch_window via subprocess (tmux window creation)`
    - *Subsumed by RuntimePlugin (pm_core/runtime/tmux_host.py) — launch is a runtime capability, not watcher logic.*
- **DELETES**: `_poll_for_verdict / _wait_for_follow_up (hook-driven verdict polling)`
    - *Replaced by CallbackRegistry.wait_for (pm_core/agent/callbacks.py) with grace_period + predicate. Underlying hook ingestion moves to pm_core/runtime/hook_entry.py.*
- **DELETES**: `_handle_input_required (INPUT_REQUIRED escalation)`
    - *Replaced by AttentionService + AttentionRequest (pm_core/agent/attention.py) with ControlOwner enum.*
- **DELETES**: `PaneKilledError`
    - *Termination signaled via TerminationReason in pm_core/agent/lifecycle.py; runtime translates pane-killed into a TerminationReason.*
- **MOVES**: `should_continue() loop continuation hook` → `pm_core/mind/policy.py`
    - *Becomes StreamPolicy.loop_mode + consecutive_pass_threshold; per-watcher overrides via loop_mode_overrides.*
- **DELETES**: `start_background (threading.Thread harness)`
    - *Replaced by Mind.stream() instantiation + WatcherSupervisor (pm_core/supervisors/watcher.py) managing lifecycle. Threading is a Mind-internal detail.*
- **DELETES**: `transcript_dir / iter_transcript symlink wiring`
    - *Replaced by StreamTranscript (pm_core/agent/transcript.py) — pm-owned per-stream transcripts.*
- **DELETES**: `on_iteration / on_complete callback wiring`
    - *Replaced by EmissionLog subscribers + Mailbox subscriptions on LifecycleGlobalChannel (pm_core/agent/channels.py).*
- **MOVES**: `WATCHER_TYPE/DISPLAY_NAME/WINDOW_NAME class config` → `pm_core/streams/watchers/__init__.py`
    - *Becomes Stream subclass class attributes + WATCHER_REGISTRY; tmux window role moves to PRActionStream.tui_window_role (n/a for watchers — likely a separate base attribute).*
- **MOVES**: `history list cap (_MAX_HISTORY = 50)` → `pm_core/mind/policy.py`
    - *Becomes RetentionPolicy on StreamPolicy.*

  *Not in plan:*
  - Pane-disappeared-mid-INPUT_REQUIRED detection (currently surfaces as KILLED verdict with summary 'Pane disappeared during INPUT_REQUIRED wait'): Add to plan-mind: AttentionService should define cancellation semantics when stream terminates with an open AttentionRequest (auto-cancel + emit AttentionAbandoned emission). Probably a small addition to pm_core/agent/attention.py spec.
  - 'Treat repeated INPUT_REQUIRED as READY' fallback (prevents infinite escalation loop): Either fold into StreamPolicy as a max_consecutive_attention_requests field (pm_core/agent/policy.py), or accept as deletion if the new model treats every AttentionRequest as a hard stop (no auto-resume).

  *Cross-cutting:* Heavy dependency on pm_core/loop_shared.py (deleted in v2 — replaced by CallbackRegistry) and pm_core/paths.configure_logger. All concrete watcher subclasses (auto_start, bug_fix_impl, improvement_fix_impl, discovery_supervisor, watcher_review) inherit from BaseWatcher; their migration to streams/watchers/*.py is blocked until Stream base + WatcherSupervisor + CallbackRegistry land. The TUI watcher_ui consumes WatcherState directly — migration must update TUI to consume StreamRecord/LifecycleState instead. The watcher_manager.py orchestrator (also deleted in v2) drives BaseWatcher instances; both must migrate together.

#### `pm_core/watcher_manager.py`
*WatcherManager: thread-safe orchestrator that registers, starts, stops, and queries lifecycle/status of BaseWatcher instances; backs the TUI's watcher list view and aggregate input-required/running checks.*

- **MOVES**: `register/unregister watcher instances` → `pm_core/supervisors/watcher.py`
    - *WatcherSupervisor takes over registration/tracking of watcher Streams; StreamRecord dataclass in supervisors/protocol.py replaces the dict-of-watchers.*
- **MOVES**: `start watcher in background thread (with on_iteration/on_complete callbacks, transcript_dir)` → `pm_core/supervisors/watcher.py`
    - *Stream lifecycle (start) is now driven by Mind.stream(role=...) + Supervisor; threading + callback wiring is replaced by the RuntimePlugin seam plus CallbackRegistry (pm_core/agent/callbacks.py). transcript_dir handled by pm_core/agent/transcript.py (StreamTranscript).*
- **MOVES**: `stop / stop_all (graceful stop via stop_requested flag)` → `pm_core/supervisors/watcher.py`
    - *Stream.status / LifecycleState + Supervisor teardown replaces stop_requested flag mutation; termination reasons live in pm_core/agent/lifecycle.py.*
- **MOVES**: `get_watcher / get_state / find_by_type / find_state_by_type` → `pm_core/supervisors/protocol.py`
    - *Supervisor.streams(role=, alive_only=) plus StreamRecord supplant these lookups; per-stream state replaced by Stream.status (LifecycleState) and EmissionLog queries.*
- **MOVES**: `list_watchers (status dicts: verdict, iteration, input_required, window_name, display_name)` → `pm_core/watchdog/tui.py`
    - *Aggregating per-watcher display state for the TUI is the watchdog/TUI policy's job; underlying data comes from StreamRecord + EmissionLog tags (verdict, iteration) and AttentionRequest (input_required). Glyph/window_name/display_name move to PRActionStream classvars on streams/watchers/*.*
- **MOVES**: `is_any_running / any_input_required (aggregate predicates)` → `pm_core/watchdog/tui.py`
    - *Aggregate predicates over streams; input_required corresponds to outstanding AttentionRequest (pm_core/agent/attention.py).*
- **DELETES**: `thread-safety lock around watcher dicts`
    - *Background-thread coordination disappears: streams run behind RuntimePlugin (own threads/processes), and shared state lives in EmissionLog (SQLite, idempotent) instead of in-process dicts.*
- **MOVES**: `duplicate-start guard (running flag set eagerly)` → `pm_core/supervisors/watcher.py`
    - *Idempotent stream(role=, instance_key=) on Mind/Supervisor replaces the eager-set-running guard.*
- **MOVES**: `deduplicating user notifications (mentioned in module docstring)` → `pm_core/mind/emissions.py`
    - *Emission.dedup_key + EmissionLog idempotent append on (stream_id, tag, correlation_id) cover dedup; surfacing to user goes through AttentionService.*

  *Cross-cutting:* Listed under "Deleted" in v2 (watcher_base.py + watcher_manager.py "rewritten as Stream base + WatcherSupervisor"). Callers: TUI app.py and tui/watcher_ui.py poll list_watchers / any_input_required — these become thin delegators over WatcherSupervisor + watchdog/tui.py. CLI `pm watcher` group (per v2 notes under pm_core/cli/) needs to be re-pointed to Mind.stream(role=...) + WatcherSupervisor. Migration is gated on: pm_core/agent/{emissions.py,callbacks.py,attention.py,transcript.py}, pm_core/streams/base.py + streams/watchers/*, and pm_core/supervisors/{protocol.py,watcher.py} all existing first. transcript_dir parameter callers must migrate to StreamTranscript naming conventions.

## By-target consolidation

Every NEW file in the proposed structure, with the existing code that contributes to it. New files with no listed source are net-new (need fresh implementation).

### `pm_core/payloads/failure_reason.py`

- from `pm_core/qa_loop.py` — **_extract_flagged_reason**
    - *Parsing a flagged-reason string out of a transcript produces a FailureReason artifact payload.*
- from `pm_core/runtime_state.py` — **verdict field surfacing (done VERDICT badge survival)**: Terminal-state verdict belongs on a typed artifact attached to the terminal Emission (FailureReason for failed; analogou

### `pm_core/payloads/mock_spec.py`

- from `pm_core/qa_loop.py` — **NewMockRequest dataclass**
    - *v2 lists mock_spec.py.*

### `pm_core/payloads/qa_scenario_ref.py`

- from `pm_core/qa_loop.py` — **QAScenario dataclass**
    - *v2 already lists qa_scenario_ref.py as the typed artifact.*

### `pm_core/bootstrap.py`

- from `pm_core/paths.py` — **get_override_path / set_override_path**
    - *Installation-override resolution is exactly what bootstrap.py owns (session-override resolution per v2 plan).*
- from `pm_core/wrapper.py` — **main() entry point with sys.path manipulation and dispatch to pm_core.cli**
    - *v2 explicitly says wrapper.py is RENAMED to bootstrap.py; this is the core function.*
- from `pm_core/wrapper.py` — **_get_session_tag — derive session tag from git repo (repo_name + md5 hash of git root path)**
    - *Used by bootstrap-time session resolution before pm_core is importable; must stay in the shim.*
- from `pm_core/wrapper.py` — **_find_active_override — read ~/.pm/sessions/<tag>/override file**
    - *Bootstrap-time concern (used to pick installed-vs-source pm_core).*
- from `pm_core/wrapper.py` — **find_local_pm_core — walk cwd up to 3 parents looking for pm_core/cli**
    - *Explicitly listed in v2 bootstrap.py description as 'cwd-walk to find local pm_core'.*
- from `pm_core/wrapper.py` — **_mark_tmux_session — sets PM_IN_TMUX_SESSION env var when under tmux**
    - *Trivial env marker that needs to happen before subcommand import; stays in shim.*
- from `pm_core/wrapper.py` — **_is_session_ipc_command — detect hidden IPC commands (_popup/_pane/_window/_tui/rebalance) from argv**
    - *Needed before pm_core importable to choose IPC vs cwd-walk path.*
- from `pm_core/wrapper.py` — **_ipc_session_tag — extract session tag from tmux session positional argv for IPC commands**
    - *Bootstrap concern — pairs with _is_session_ipc_command.*
- from `pm_core/wrapper.py` — **_session_tag — unified resolver (argv for IPC, cwd-derived otherwise)**
    - *Bootstrap concern.*
- from `pm_core/wrapper.py` — **_pm_core_from_pm_root — resolve pm_core source dir from persisted pm_root file**
    - *v2 bootstrap.py description names 'pm_root persistence' explicitly.*
- from `pm_core/wrapper.py` — **Logger configuration call (configure_logger('pm.wrapper') diagnostic logging)**
    - *Logger name should likely be renamed to 'pm.bootstrap'; minor.*

### `pm_core/cli/`

- from `pm_core/qa_loop.py` — **start_qa_background / resume_qa_background (spawn QA loop in background process)**
    - *Background spawn is a CLI concern (pm qa start). v2 says 'pm qa command groups change to delegate to Streams/Supervisors' — these CLI handlers stay in cli/ but become thin Supervisor.start() calls. Re*

### `pm_core/collaboration/transport/tmux_socket.py`

- from `pm_core/paths.py` — **SHARED_SOCKET_DIR / shared_socket_path / ensure_shared_socket_dir / set_shared_socket_permissions / get_share_users**
    - *Multi-user shared tmux socket primitives — exactly the substrate the tmux_socket transport needs (same-host shared tmux socket per v2).*

### `pm_core/lifecycle.py`

- from `pm_core/review_loop.py` — **PaneKilledError**
    - *Becomes a TerminationReason*

### `pm_core/mind/attention.py`

- from `pm_core/bridge.py` — **AGENT/HUMAN mode toggle and ControlOwner state machine**
    - *Becomes AttentionService + ControlOwner enum (HUMAN/AGENT) + AttentionRequest. v2 explicitly calls out 'AttentionRequest' as a split-target for bridge.py.*
- from `pm_core/bridge_client.py` — **take_control / release_control (AGENT vs HUMAN mode toggle)**
    - *Per the deletion note 'bridge.py + bridge_client.py (split: RawApiRuntime + Mailbox + AttentionRequest)'. Control ownership becomes ControlOwner enum + AttentionService/AttentionRequest. The mode-togg*
- from `pm_core/review_loop.py` — **_wait_for_follow_up_verdict (INPUT_REQUIRED handling)**
    - *AttentionRequest with ControlOwner handoff to human; resume via callback*
- from `pm_core/runtime_state.py` — **suppress_switch flag (request_suppress_switch / consume_suppress_switch)**: This is an attention/focus-steal cancellation signal; fits AttentionService + AttentionRequest semantics (user-dismissed
- from `pm_core/tui/review_loop_ui.py` — **_handle_merge_input_required — INPUT_REQUIRED merge verdict handling**
    - *AttentionRequest with ControlOwner per plan; _merge_input_required_prs tracking subsumed by AttentionService.*

### `pm_core/mind/callbacks.py`

- from `pm_core/review_loop.py` — **_poll_for_verdict**
    - *CallbackRegistry.wait_for(not_before/predicate/grace_period); transcript via StreamTranscript*
- from `pm_core/review_loop.py` — **_VERDICT_GRACE_PERIOD constant**
    - *grace_period parameter on CallbackRegistry.wait_for*

### `pm_core/mind/emissions.py`

- from `pm_core/hook_events.py` — **Event schema (event_type, timestamp fields)**
    - *The idle/stop/permission event categories become typed Emissions / VisibilityTier-tagged log entries. Schema versioning per emissions.py Emission.schema_version.*
- from `pm_core/review_loop.py` — **ReviewIteration dataclass**
    - *Per-iteration history becomes Emissions in EmissionLog*
- from `pm_core/watcher_manager.py` — **deduplicating user notifications (mentioned in module docstring)**
    - *Emission.dedup_key + EmissionLog idempotent append on (stream_id, tag, correlation_id) cover dedup; surfacing to user goes through AttentionService.*
- from `pm_core/tui/review_loop_ui.py` — **_on_iteration_from_thread / _on_complete_from_thread — background-thread callbacks mirroring state**
    - *Replaced by Emission envelope writes from RuntimePlugin; supersede detection (loop_id check) becomes correlation_id + dedup_key on Emission.*
- from `pm_core/tui/watcher_ui.py` — **_ui_notified_input / _ui_notified_done dedup flags on watcher state**
    - *Folds into Emission.dedup_key on the notification channel so watchdog/tui.py doesn't have to stash flags on state objects.*

### `pm_core/mind/lifecycle.py`

- from `pm_core/pr_utils.py` — **PRStatus Literal type definition**: The PRStatus Literal (pending|in_progress|in_review|qa|sign_off|merged|closed) defining the valid PR lifecycle states.
    - *v2 plan explicitly calls out: 'pr_utils.py (PRStatus moves to lifecycle.py)'. Likely promoted to a StrEnum alongside LifecycleState.*
- from `pm_core/pr_utils.py` — **VALID_PR_STATES set**: Set of valid PR status strings used for membership checks.
    - *Becomes implicit via StrEnum membership / __members__ on the lifecycle enum; the explicit set constant goes away.*
- from `pm_core/pr_utils.py` — **is_valid_pr_status() helper**: Boolean check whether a string is a valid PR status.
    - *Becomes a classmethod on the lifecycle/PRStatus enum (e.g. PRStatus.is_valid(s)) or callers switch to enum membership check.*
- from `pm_core/pr_utils.py` — **normalize_pr_status() helper**: Validate and coerce string to PRStatus, raising ValueError on invalid input with a sorted list of valid states.
    - *Becomes PRStatus(value) constructor (StrEnum) or a classmethod that wraps it with the friendlier error message.*
- from `pm_core/runtime_state.py` — **Action state schema + VALID_STATES enum**: Maps directly onto LifecycleState StrEnum; queued/launching/running/idle/waiting/done/failed become canonical LifecycleS

### `pm_core/mind/log.py`

- from `pm_core/runtime_state.py` — **Persisted action transitions (set_action_state read-modify-write under flock)**: EmissionLog (SQLite, idempotent append on (stream_id, tag, correlation_id)) replaces JSON-per-PR file write; each transi
- from `pm_core/runtime_state.py` — **get_pr_actions / get_action_state readers**: Becomes EmissionLog queries scoped by stream_id; PR-action lookup becomes 'latest lifecycle emission per Stream owned by

### `pm_core/mind/mailbox.py`

- from `pm_core/bridge.py` — **Busy flag preventing concurrent turns / ack protocol on send**
    - *Mailbox's preempt/next-checkpoint delivery semantics + Stream's LifecycleState replace the ad-hoc busy flag and JSON ack.*

### `pm_core/mind/policy.py`

- from `pm_core/qa_loop.py` — **Config knobs: _get_max_scenarios, _get_verification_max_retries, _get_verdict_reminder_timeout, _is_verification_enabled**
    - *These are policy thresholds (max_iterations, consecutive_pass_threshold analogue) — fold into StreamPolicy/BudgetPolicy or a QaPolicy subclass declared on QaSupervisor.*
- from `pm_core/watcher_base.py` — **should_continue() loop continuation hook**
    - *Becomes StreamPolicy.loop_mode + consecutive_pass_threshold; per-watcher overrides via loop_mode_overrides.*
- from `pm_core/watcher_base.py` — **history list cap (_MAX_HISTORY = 50)**
    - *Becomes RetentionPolicy on StreamPolicy.*
- from `pm_core/tui/app.py` — **_stop_before_merge set**
    - *Per v2 changes: StreamPolicy has stop_before_merge field.*
- from `pm_core/tui/auto_start.py` — **stop_before_merge set management (in save_breadcrumb, consume_breadcrumb, check_and_start, auto_sequence_for_pr)**
    - *Becomes StreamPolicy.stop_before_merge (already explicitly listed in policy.py in v2).*
- from `pm_core/tui/qa_loop_ui.py` — **_get_qa_pass_count (global settings read)**: Becomes a field/derivation in StreamPolicy.consecutive_pass_threshold sourced from global settings.
- from `pm_core/watchers/improvement_fix_impl_watcher.py` — **Hold-at-QA-PASS (no auto-merge) policy**
    - *Encoded as StreamPolicy.stop_before_merge=True on the spawned PR action stream (or on the watcher's downstream PRStreamSupervisor policy)*

### `pm_core/mind/transcript.py`

- from `pm_core/qa_loop.py` — **_tail_has_marker_on_own_line (verdict marker detection on transcript tail)**
    - *Generic transcript-tail predicate belongs on StreamTranscript as a utility (or a small helper consumed by the verdict-polling Stream).*
- from `pm_core/qa_loop.py` — **_scenario_transcript_path / _next_scenario_offset**
    - *StreamTranscript owns per-stream file naming; offset computation becomes part of how QaSupervisor names its child scenario streams.*
- from `pm_core/cli/watcher.py` — **Transcript directory creation + finalize_transcript symlink cleanup**
    - *Per-stream transcript handling moves to StreamTranscript (pm-owned, not Claude-owned). CLI no longer pokes the transcript dir directly.*
- from `pm_core/tui/auto_start.py` — **Transcript directory allocation (get_transcript_dir, run_id generation, _finalize_all_transcripts)**
    - *StreamTranscript is pm-owned per-stream files; per-run dir collection becomes a transcript service concern. finalize_transcript is in claude_launcher (stays) and gets called by TmuxHostRuntime cleanup*
- from `pm_core/tui/auto_start.py` — **manual-<token> transcript run_id fallback (manual review loops without auto-start)**
    - *Cross-cutting transcript dir convention; not auto-start specific. Belongs with StreamTranscript service.*
- from `pm_core/tui/review_loop_ui.py` — **finalize_transcript symlink finalization on loop complete**
    - *Transcript finalization is now pm-owned StreamTranscript responsibility.*

### `pm_core/model_config.py`

- from `pm_core/qa_loop.py` — **_resolve_qa_model (model selection for QA Claude sessions)**
    - *model_config.py is listed as Stays — this is the natural home for per-role model resolution. The QA-specific dispatch becomes a helper there or a method on the QaSupervisor that consults model_config.*

### `pm_core/policy.py`

- from `pm_core/review_loop.py` — **should_stop (PASS-only stop predicate)**
    - *StreamPolicy.consecutive_pass_threshold*
- from `pm_core/review_loop.py` — **max_iterations safety cap**
    - *StreamPolicy.max_iterations*

### `pm_core/runtime/fake.py`

- from `pm_core/claude_launcher.py` — **_resolve_provider (provider switch: claude vs fake)**
    - *The provider-switching logic is the seam between real-Claude and FakeClaude runtimes. Under v2 the runtime is selected at Mind.stream(runtime=...) time, so this dispatch belongs near FakeClaudeRuntime*
- from `pm_core/claude_launcher.py` — **_fake_claude_config_for_type / _pick_fake_verdict / _clamp_cursor / _advance_scripted_cursor / _resolve_fake_verdict / _fake_claude_args / peek_fake_verdicts (entire fake-claude scripted verdict subsystem)**
    - *v2 lists fake_claude.py as 'becomes FakeClaudeRuntime' under runtime/fake.py. This scripted-verdict + cursor + args machinery is the FakeClaude provider's behavior and belongs inside FakeClaudeRuntime*
- from `pm_core/fake_claude.py` — **run_fake_claude entrypoint + output sequencing (preamble, body batches, delays, hold-open, streaming, _write helper)**
    - *Becomes FakeClaudeRuntime's execute loop. v2 explicitly lists fake.py as 'FakeClaudeRuntime — test impl from FakeClaudeSession.'*
- from `pm_core/fake_claude.py` — **Verdict catalog: SINGLE_LINE_VERDICTS, BLOCK_VERDICTS, ALL_VERDICTS, NO_VERDICT, ALL_VERDICT_CHOICES**
    - *These are the test-fixture vocabulary the fake emits. They mirror the ALLOWED_VERDICTS classvars on per-prompt InputType classes (prompts/protocol.py) — could be derived from those at test time instea*
- from `pm_core/fake_claude.py` — **SESSION_TYPE_VERDICTS mapping (per session-type allowed verdicts) + validate_session_verdicts**
    - *In v2 each Stream subclass declares its own fake_runtime_script and the InputType declares ALLOWED_VERDICTS. This mapping becomes redundant — it could be replaced by aggregating ALLOWED_VERDICTS from *
- from `pm_core/fake_claude.py` — **Scripted-sequence support (_scripted_sequence, _scripted_entry_verdict, _scripted_wrap)**
    - *Directly maps to Stream.fake_runtime_script declared on subclasses (streams/base.py mentions fake_runtime_script). The scripted-list/dict shape is the runtime-side interpretation.*
- from `pm_core/fake_claude.py` — **_write_fake_transcript + _claude_transcript_path (writes Claude-format JSONL transcript)**
    - *Production verdict detection reads Claude's native JSONL. In v2, FakeClaudeRuntime emits Emissions and pm-owned StreamTranscript (agent/transcript.py) captures them. The fake's job to mimic a Claude-f*
- from `pm_core/fake_claude.py` — **_emit_idle_hook (writes idle_prompt hook event the poller waits on)**
    - *Pairs with runtime/hook_entry.py. FakeClaudeRuntime fabricates the hook events that hook_entry.py would receive from real Claude Code. Tight coupling to hook_entry.py's event schema.*
- from `pm_core/fake_claude.py` — **_hold_open (stay-open-with-periodic-hook-refresh loop, stdin select for graceful exit)**
    - *FakeClaudeRuntime lifecycle: mimics interactive Claude staying open. Maps to RuntimePlugin's interactive_tty capability behavior.*
- from `pm_core/fake_claude.py` — **_resolve_block_name (verdict alias resolution: 'FLAGGED' or 'FLAGGED_END' both accepted)**
    - *Internal helper, moves with the catalog.*
- from `pm_core/fake_claude.py` — **Preamble / body filler text constants (_PREAMBLE_LINES, _BODY_LINES, _DEFAULT_BODIES — referenced but defined elsewhere in file)**
    - *Test-fixture text content. Moves wholesale.*
- from `pm_core/paths.py` — **fake_claude_config / fake_claude_config_for_type / set_fake_claude_config / clear_fake_claude**
    - *Per-session fake-claude config drives FakeClaudeRuntime. Logically belongs with the FakeClaudeRuntime impl.*

### `pm_core/runtime/hook_entry.py`

- from `pm_core/hook_install.py` — **Standalone hook receiver script that Claude Code's hook command invokes (the command string and the on-disk receiver file)**
    - *v2 explicitly names runtime/hook_entry.py as the shippable CLI invoked by Claude Code hooks; _hook_command_for() and _install_receiver() collapse into hook_entry.py being the installed target (and Tmu*
- from `pm_core/hook_install.py` — **Sweep stale ~/.pm/hooks/*.json event files (_sweep_stale_events, _STALE_SECONDS)**
    - *Stale-event cleanup is part of the hook-receiver lifecycle; belongs with hook_entry.py (or invoked by TmuxHostRuntime startup). Could also be argued as a Supervisor teardown concern but it's keyed to *
- from `pm_core/hook_receiver.py` — **CLI entrypoint invoked by Claude Code hooks (main + __main__)**
    - *v2 explicitly names runtime/hook_entry.py as 'shippable CLI invoked by Claude Code hooks; forwards events to RuntimePlugin'. Direct replacement.*
- from `pm_core/hook_receiver.py` — **Stdin JSON payload parsing + event_type dispatch (idle_prompt/permission_prompt/Stop)**
    - *Parsing logic moves with the entry point; semantics get re-expressed as Emissions forwarded into the owning RuntimePlugin (TmuxHostRuntime/TmuxContainerRuntime).*
- from `pm_core/hook_receiver.py` — **Never-block-Claude error swallowing**
    - *Defensive top-level try/except stays as a property of the hook CLI.*
- from `pm_core/cli/session.py` — **Claude Code hook installation at session start (ensure_hooks_installed import from pm_core.hook_install)**
    - *hook_install.py is in the Deleted list ('runtime/hook_entry.py + TmuxHostRuntime internals'). The call from _session_start needs to be retargeted; the session entry path should ask the active TmuxHost*
- from `pm_core/cli/tui.py` — **Claude Code hook installation at TUI launch (ensure_hooks_installed)**
    - *v2 deletes hook_install.py and routes hook plumbing through runtime/hook_entry.py + TmuxHostRuntime internals. The call here needs to be replaced with whatever TmuxHostRuntime's setup invokes.*

### `pm_core/runtime/push_proxy.py`

- from `pm_core/pr_cleanup.py` — **stop push-proxy sockets for lingering containers**
    - *push_proxy daemon owns its own socket lifecycle; TmuxContainerRuntime.shutdown calls into it. Standalone 'lingering socket' sweep becomes push_proxy internal reconcile.*
- from `pm_core/push_proxy.py` — **PushProxy daemon (class PushProxy, lines 112-502)**
    - *v2 explicitly lists runtime/push_proxy.py as ~870 LOC consumed by TmuxContainerRuntime; this is the primary relocation target.*
- from `pm_core/push_proxy.py` — **_resolve_local_remote_url / resolve_real_origin (origin URL resolution for bind-mounted workdirs)**
    - *Tightly coupled helpers for the proxy; move together. Could alternatively land in git_ops.py, but they exist solely to serve the proxy.*
- from `pm_core/push_proxy.py` — **Shared socket directory / key derivation (_shared_proxy_key, _shared_sock_dir_path, _shared_sock_dir)**
    - *Internal to proxy lifecycle.*
- from `pm_core/push_proxy.py` — **Proxy subprocess lifecycle (_start_proxy_subprocess, start_push_proxy, _kill_proxy_socket, stop_push_proxy)**
    - *Called by TmuxContainerRuntime per v2.*
- from `pm_core/push_proxy.py` — **Bulk teardown (stop_all_proxies, stop_session_proxies)**
    - *Likely invoked from Supervisor teardown or runtime cleanup hooks — but the implementations stay co-located with the daemon.*
- from `pm_core/push_proxy.py` — **Liveness/introspection (proxy_is_alive, get_proxy_socket_path, container_socket_path)**
    - *Used by container runtime to wire socket into the container.*

### `pm_core/runtime/raw_api.py`

- from `pm_core/bridge.py` — **Subprocess invocation of `claude -p --resume` with stream-json I/O and session_id continuity (_invoke_claude)**
    - *v2 explicitly says RawApiRuntime 'absorbs bridge.py's _invoke_claude semantics'. The session_id resume continuity becomes the RuntimePlugin's per-Stream session state.*
- from `pm_core/bridge.py` — **Streaming of assistant text and tool_use events back to a visible surface**
    - *Per-turn streaming output becomes Emission emission on the Stream; visible-pane rendering is handled by whichever Tmux* runtime composes with it (HybridRuntime) or by Stream transcript replay.*
- from `pm_core/bridge.py` — **skip_permissions_enabled() lookup for --dangerously-skip-permissions flag**
    - *Flag selection moves with _invoke_claude into RawApiRuntime; pm_core/paths.py (the source of skip_permissions_enabled) is listed under Stays.*
- from `pm_core/bridge.py` — **Session-id persistence across turns for `claude --resume`**
    - *Per-Stream session_id is RuntimePlugin internal state. Optional: could also be surfaced via EmissionLog stream_id correlation but the resume token itself is runtime-internal.*
- from `pm_core/bridge_client.py` — **send_message (synchronous request/response with Claude)**
    - *v2 plan explicitly says bridge.py's _invoke_claude semantics get absorbed into RawApiRuntime. The send-and-wait-for-turn-end behavior becomes a RuntimePlugin invocation; the result surfaces as an Emis*

### `pm_core/runtime/tmux_container.py`

- from `pm_core/container.py` — **ContainerError + ContainerConfig dataclass**: Error type and resource-limit config consumed only by the container runtime
- from `pm_core/container.py` — **Runtime detection (_detect_default_runtime, _get_runtime, _nested_podman_enabled, _apparmor_enforcing, _selinux_enabled, _nested_podman_run_args, _runtime_available)**: Docker vs Podman selection + host security posture detection — runtime-internal
- from `pm_core/container.py` — **Image build / existence cache (build_image, image_exists, _invalidate_image_exists_cache, _get_dockerfile_path)**: Builds the container image consumed by TmuxContainerRuntime
- from `pm_core/container.py` — **Config loader (load_container_config, is_container_mode_enabled)**
    - *Could alternatively be exposed via RuntimePlugin capabilities; load remains runtime-local*
- from `pm_core/container.py` — **_run_runtime / container_is_running helpers**: Thin wrappers over docker/podman CLI
- from `pm_core/container.py` — **_build_git_setup_script + _host_git_identity + git-wrapper proxy-client shell script (lines ~382-528)**
    - *Imports from pm_core/runtime/push_proxy.py (the _CONTAINER_SOCKET_PATH constant) — coupling explicitly anticipated in v2*
- from `pm_core/container.py` — **_resolve_claude_binary**: Locates the claude CLI to bind-mount into container
- from `pm_core/container.py` — **Container naming (_make_container_name, qa_container_name)**
    - *Naming scheme is runtime-internal; the role/PR/QA-scenario identity that DRIVES the name is owned upstream by Supervisors/leases (ContainerKey in sensorium/leases.py)*
- from `pm_core/container.py` — **create_container (main lifecycle, ~380 LOC)**: Core container creation logic — becomes part of TmuxContainerRuntime.start/launch
- from `pm_core/container.py` — **build_exec_cmd / remove_container / wrap_claude_cmd**: Exec-into-container + Claude command wrapping — runtime-internal seam
- from `pm_core/container.py` — **create_qa_container (QA-scenario container variant)**
    - *Called by QaScenarioStream via runtime; the QA-specific tagging stays runtime-side, the orchestration moves to streams/qa_scenario.py*
- from `pm_core/hook_install.py` — **Host/container home-path translation via PM_HOST_HOME (_host_home, _settings_path, _hooks_base, _receiver_path)**
    - *PM_HOST_HOME is exported by container.py (which v2 folds into TmuxContainerRuntime). The host-path translation helpers split: path-resolution helpers consumed by both TmuxHostRuntime and TmuxContainer*
- from `pm_core/hook_receiver.py` — **Container-vs-host path agreement via flat ~/.pm/hooks/ dir**
    - *Cross-boundary delivery from inside a container becomes a TmuxContainerRuntime concern (and/or push_proxy.py); hook_entry.py running inside the container forwards via the runtime's transport rather th*
- from `pm_core/pr_cleanup.py` — **cleanup PR containers (container_mod.cleanup_pr_containers)**
    - *Container teardown becomes TmuxContainerRuntime.shutdown(); ContainerKey lease release in sensorium/leases.py drives it.*
- from `pm_core/qa_loop.py` — **_launch_scenarios_in_containers**
    - *Container-runtime variant of the launch — TmuxContainerRuntime absorbs container.py + per-PR Docker glue. Supervisor stays runtime-agnostic; it just picks the runtime.*
- from `pm_core/signoff.py` — **Container-mode integration (wrap_claude_cmd, _CONTAINER_WORKDIR, remove_container)**
    - *Container-vs-host cwd/write_dir branching is exactly the runtime selection seam — SignoffStream just declares required_capabilities and the runtime handles the difference.*
- from `pm_core/cli/container.py` — **container build-base command (build pm-dev:latest base image)**
    - *build_image absorbed into TmuxContainerRuntime; CLI wrapper stays as thin entrypoint that delegates*
- from `pm_core/cli/container.py` — **container cleanup command (remove stale pm containers; --pr filter)**
    - *Container lifecycle/teardown is a TmuxContainerRuntime concern; pm_core/container.py is deleted in v2 and pr_cleanup.py fans out into Supervisor teardown + runtime cleanup hooks. CLI wrapper stays.*
- from `pm_core/cli/container.py` — **Imports from pm_core/container.py (is_container_mode_enabled, load_container_config, _runtime_available, _get_runtime, build_image, DEFAULT_IMAGE, _run_runtime, remove_container, CONTAINER_PREFIX)**
    - *v2 explicitly deletes pm_core/container.py — all these symbols migrate to TmuxContainerRuntime. cli/container.py needs updated import surface.*

### `pm_core/runtime/tmux_host.py`

- from `pm_core/bridge.py` — **Stdin reader loop with Enter-to-toggle UX in a tmux pane**
    - *Pane-side human input + control-toggle keybinding becomes a TmuxHostRuntime concern (paired with HybridRuntime when composed with RawApiRuntime). The Enter-toggle itself is a TUI keybinding configured*
- from `pm_core/hook_install.py` — **Install/merge Claude Code hook entries into ~/.claude/settings.json (ensure_hooks_installed, _desired_hooks, hooks_already_installed)**
    - *Per v2 plan, hook_install.py is deleted; settings.json hook installation is an internal detail of TmuxHostRuntime (the runtime that talks to a host Claude Code via hooks). The desired-hooks config bec*
- from `pm_core/hook_install.py` — **Detect foreign / pre-existing non-pm hooks and raise HookConflictError (_detect_foreign_hooks, _entry_is_pm, HookConflictError)**
    - *Conflict detection is part of TmuxHostRuntime's host-side setup; HookConflictError lives alongside it (no dedicated v2 home, but it's a runtime-internal concern).*
- from `pm_core/pane_idle.py` — **PaneIdleState dataclass (per-pane idle/waiting/gone/timestamp/notified flags)**
    - *Per-pane lifecycle bookkeeping is a TmuxHostRuntime-internal detail; collapses into runtime's stream state. Lifecycle bits (idle/working/gone) project onto LifecycleState in pm_core/agent/lifecycle.py*
- from `pm_core/pane_idle.py` — **PaneIdleTracker.register / unregister (start tracking a pane keyed by pr_id/qa:.../merge:.../review:...)**
    - *Registration becomes implicit when TmuxHostRuntime.attach()/start() opens a stream; the key/role mapping is replaced by Stream id + role.*
- from `pm_core/pane_idle.py` — **PaneIdleTracker.poll (read hook event, update flags, check tmux.pane_exists)**
    - *Hook event consumption moves into runtime/hook_entry.py which forwards into TmuxHostRuntime; pane_exists liveness probe stays runtime-internal. Idle/working transitions get emitted as Emissions on the*
- from `pm_core/pane_idle.py` — **is_idle / is_waiting_for_input / is_gone / became_idle / mark_active / tracked_keys / get_transcript_path (pure read accessors)**
    - *Callers (TUI/picker) should query Stream.status (LifecycleState) and lifecycle Emissions on AttentionGlobalChannel/LifecycleGlobalChannel rather than poking a tracker. waiting_for_input becomes an Att*
- from `pm_core/pane_idle.py` — **Thread-safety (RLock around dict mutations across TUI main thread + review loop background thread)**
    - *Concurrency contract migrates with the runtime; EmissionLog (pm_core/agent/log.py) is already specified as SQLite + idempotent append, which subsumes most cross-thread state coordination.*
- from `pm_core/paths.py` — **skip_permissions_enabled / set_skip_permissions**
    - *Claude-launch permission flag — runtime concern (TmuxHostRuntime / claude_launcher consumes it). Could alternately stay since claude_launcher stays.*
- from `pm_core/qa_loop.py` — **_compute_qa_window_name / _scenario_window_name / _cleanup_stale_scenario_windows**
    - *tmux-window naming + stale-window cleanup is internal to TmuxHostRuntime (v2 says pane_idle/window mgmt folds into TmuxHostRuntime). Window-key resource ownership shows up as TmuxWindowKey leases in s*
- from `pm_core/qa_loop.py` — **_build_scenario_run_cmd**
    - *Command construction for launching a Claude session in a tmux window is a TmuxHostRuntime / TmuxContainerRuntime internal.*
- from `pm_core/qa_loop.py` — **_relaunch_scenario_window**
    - *Window relaunch is runtime-internal — also overlaps with Stream.deliver_message + LoopMode.kill_restart semantics from agent/tags.py.*
- from `pm_core/review_loop.py` — **_compute_review_window_name**
    - *Window naming is TmuxHostRuntime; role declared on PRActionStream.tui_window_role*
- from `pm_core/review_loop.py` — **_launch_review_window subprocess**
    - *Launch is RuntimePlugin job, uses claude_launcher*
- from `pm_core/runtime_state.py` — **derive_action_status (cross-reference hook_events for fresh idle/waiting)**: Hook-event reading is a runtime-internal detail. TmuxHostRuntime owns Claude Code hook ingestion and reports idle/waitin
- from `pm_core/runtime_state.py` — **session_id field on action entry (pane-backed cross-ref key)**: Session-id<->pane mapping is runtime-internal to TmuxHostRuntime; surfaces externally only as Emission metadata.
- from `pm_core/cli/cluster.py` — **Direct launch path (find_claude + launch_claude + clear_session)**
    - *claude_launcher.py stays per v2 and is consumed by TmuxHostRuntime; the explore command should request a Stream which uses TmuxHostRuntime instead of calling launch_claude directly.*
- from `pm_core/cli/guide.py` — **tmux-aware exec branching (_in_pm_tmux_session + os.execvp vs launch_claude)**
    - *Tmux detection + in-pane vs new-pane launch is a runtime concern owned by TmuxHostRuntime; the CLI no longer chooses between os.execvp and launch_claude.*
- from `pm_core/cli/helpers.py` — **kill_pr_windows**
    - *Tmux PR window teardown — currently fans out across home_window park + tmux kill. v2 says pr_cleanup.py 'fans out across Supervisor teardown + runtime cleanup hooks'. The actual tmux kill belongs in T*
- from `pm_core/cli/meta.py` — **tmux window dedup + new_window launch + fallback subprocess.run**
    - *Window create/find/select and Claude launch are TmuxHostRuntime responsibilities; MetaDevelopmentStream declares required_capabilities and the runtime handles the actual pane.*
- from `pm_core/cli/meta.py` — **claude_launcher invocation (find_claude, build_claude_shell_cmd) + cleanup rm of session dir**
    - *claude_launcher stays per v2 'Stays' list; TmuxHostRuntime consumes it. Session-dir cleanup becomes part of runtime teardown / HostCodeOverride lifecycle.*
- from `pm_core/cli/plan.py` — **_PROMPT_ARG_LIMIT (E2BIG safety constant for execve argv)**
    - *argv-size limit is a TmuxHostRuntime concern (Claude CLI invocation). Could also belong in claude_launcher.py which stays. Currently unused-looking constant — verify before move.*
- from `pm_core/cli/pr.py` — **pr qa-run-bg (hidden) + _launch_qa_detached**
    - *Detached background launch is a runtime capability; orchestration in QaSupervisor / PRStreamSupervisor*
- from `pm_core/cli/qa.py` — **qa launch (open instruction in a tmux window with target_window option)**
    - *Tmux-window opening is a runtime concern; CLI thin-wraps Mind.stream(... runtime=TmuxHostRuntime) with the proper Stream role.*
- from `pm_core/cli/watcher.py` — **Internal --iteration mode: build per-iteration tmux watcher window (_create_watcher_window)**
    - *Tmux window creation, kill+recreate-per-iteration semantics, home_window parking, session switching are all TmuxHostRuntime concerns. Watcher Stream declares loop_mode=kill_restart and TmuxHostRuntime*
- from `pm_core/cli/watcher.py` — **tmux precondition checks (has_tmux + in_tmux + session_exists)**
    - *These become capability/precondition checks inside TmuxHostRuntime (declared via required_capabilities on the watcher Stream and validated by the runtime).*
- from `pm_core/plans/review.py` — **tmux background-pane PASS/NEEDS_FIX summary rendering**
    - *Background-pane verdict notification is runtime-internal; could alternatively land in pm_core/tui/ as a transient notification widget. The split_pane_background call is TmuxHostRuntime territory.*
- from `pm_core/tui/review_loop_ui.py` — **_kill_merge_window — find and kill tmux merge window**
    - *Tmux window cleanup is RuntimePlugin internal. Lease release in pm_core/sensorium/leases.py (TmuxWindowKey).*
- from `pm_core/tui/review_loop_ui.py` — **_find_impl_pane — tmux pane lookup helper**
    - *Tmux pane resolution is runtime-internal.*
- from `pm_core/tui/review_loop_ui.py` — **_poll_impl_idle — poll impl panes for idle, register/unregister with tracker, detect newly-idle for auto-review**
    - *Pane idle detection moves into TmuxHostRuntime per plan ('pane_idle.py — runtime-internal detail moves into TmuxHostRuntime'). Newly-idle detection emits a stream Emission consumed by WatcherSuperviso*
- from `pm_core/tui/review_loop_ui.py` — **Tracker stale key cleanup (merge:/review:/impl)**
    - *Tracker lifecycle moves into TmuxHostRuntime.*
- from `pm_core/tui/watcher_ui.py` — **Transcript finalization on watcher completion (finalize_transcript over symlinked .jsonl in transcript_dir)**
    - *Runtime-internal teardown; transcript handling is now pm-owned via StreamTranscript (agent/transcript.py) and the TmuxHostRuntime cleanup hook.*

### `pm_core/sensorium/artifact/base.py`

- from `pm_core/editor.py` — **temp-file template seed + launch $EDITOR**
    - *Per v2 'Deleted' section: 'editor.py becomes Artifact.open_in_editor + watch_for_save on the base'. The 'write template -> launch editor' half maps to Artifact.open_in_editor / Artifact.edit_interacti*
- from `pm_core/editor.py` — **mtime-polling save detection + on_save callback dispatch (daemon thread + final post-exit poll)**
    - *Maps to Artifact.watch_for_save (and the related _on_external_change hook listed for the Artifact base). The polling+callback mechanic is the implementation behind watch_for_save.*
- from `pm_core/editor.py` — **temp file cleanup (os.unlink in finally)**
    - *Becomes an internal detail of Artifact.edit_interactively / open_in_editor lifecycle.*
- from `pm_core/cli/guide.py` — **watched-editor invocation (run_watched_editor + on_save callback)**
    - *Becomes Artifact.edit_interactively + watch_for_save on the base — explicitly listed in v2 'Added' changes; pm_core/editor.py is deleted.*
- from `pm_core/cli/helpers.py` — **trigger_tui_reload / trigger_tui_refresh / trigger_tui_command / trigger_tui_restart / trigger_tui_merge_lock / trigger_tui_merge_unlock**
    - *These are the IPC backend for external mutations notifying the TUI. In v2 this concern is replaced by Artifact._on_external_change + on_change subscribers — the TUI listens to artifact change events r*
- from `pm_core/cli/qa.py` — **qa edit (open file in editor)**
    - *Becomes Artifact.open_in_editor — editor.py is listed as deleted/absorbed into Artifact.open_in_editor.*
- from `pm_core/cli/qa.py` — **qa mocks edit (open mock in editor)**
    - *Artifact.open_in_editor on a MockArtifact instance.*
- from `pm_core/review/md_writer.py` — **Atomic write primitive (_atomic_write_text)**
    - *Becomes a shared helper on Artifact base used by apply(); same pattern as pane_registry.locked_read_modify_write. Could also be a small util module — but Artifact.apply is the natural seam.*
- from `pm_core/review/md_writer.py` — **flock-based locking context (_locked)**
    - *Artifact.apply needs RMW locking; this is the canonical impl.*
- from `pm_core/review/md_writer.py` — **_utc_now timestamp helper**
    - *Trivial helper; lives wherever Artifact base lives.*
- from `pm_core/tui/pane_ops.py` — **find_editor**
    - *Editor resolution belongs to Artifact.open_in_editor / edit_interactively; small helper inlined there. Could also stay as TUI util — either way is minor.*

### `pm_core/sensorium/artifact/notes.py`

- from `pm_core/notes.py` — **Edit template build/parse (build_edit_template, parse_edit_template)**
    - *These are the editor round-trip — NotesSectionArtifact's edit_interactively / watch_for_save / propose_edit semantics live on Artifact base. Composite-view editing is artifact-layer concern, though cu*
- from `pm_core/notes.py` — **Constants: NOTES_HEADER, NOTES_WELCOME, _SECTION_DESCS**
    - *UI/edit-template chrome — belongs with NotesSectionArtifact's interactive-edit surface.*
- from `pm_core/cli/guide.py` — **notes file ensure + section template build/parse + save**
    - *build_edit_template/parse_edit_template/save_sections/ensure_notes_file become NotesSectionArtifact methods (read, propose_edit, apply); the on_save callback collapses into Artifact.apply.*
- from `pm_core/cli/pr.py` — **pr note group (add/edit/list/delete)**
    - *Notes storage is NotesSectionArtifact; CLI stays as delegator*
- from `pm_core/review/md_writer.py` — **append_note (NOTES.md section-aware appender)**
    - *Matches NotesSectionArtifact responsibility (section-keyed timestamped append). Walker NOTES.md is a NotesSectionArtifact instance — share code with project-level NotesSectionArtifact.*
- from `pm_core/tui/pane_ops.py` — **launch_notes**
    - *NotesSectionArtifact.edit_interactively() — TUI shim calls into the Artifact.*
- from `pm_core/tui/qa_loop_ui.py` — **_record_qa_note (append PR note)**: PR note recording becomes NotesSectionArtifact.apply (still consumes pm_core/notes.py + store).

### `pm_core/sensorium/artifact/plan.py`

- from `pm_core/tui/pane_ops.py` — **view_plan (open plan-for-PR)**
    - *Becomes PlanArtifact.open_in_editor() / .resolve_link() invoked from a TUI shim.*
- from `pm_core/tui/pane_ops.py` — **launch_plan_activated (open plan file)**
    - *PlanArtifact.open_in_editor (or read-only view variant).*

### `pm_core/sensorium/artifact/project_yaml.py`

- from `pm_core/pr_sync.py` — **_trigger_tui_refresh (signals TUI app to redraw after sync)**
    - *External-write notification — fits Artifact._on_change / _on_external_change pattern on ProjectYamlArtifact. TUI should subscribe to artifact change events rather than pr_sync poking it directly. Unti*
- from `pm_core/signoff.py` — **record_signoff_verdict() — durable pr['signoff'] = {verdict, sha, ts, origin}**
    - *Writes structured data into project.yaml under the PR entry; this is a ProjectYamlArtifact mutation. The verdict-emission itself is a SignoffStream Emission (pm_core/agent/emissions.py via EmissionLog*
- from `pm_core/spec_gen.py` — **spec_pending state in project.yaml (write/read of the review queue)**
    - *spec_pending is a PR-record field; ProjectYamlArtifact.apply() handles the locked_update. The queue semantics (oldest_pending_spec_pr) become a query method on ProjectYamlArtifact or on SpecArtifact.*
- from `pm_core/store.py` — **locked_edit (open $EDITOR under lock, re-read + re-save)**
    - *v2 introduces Artifact.open_in_editor + watch_for_save + edit_interactively on the Artifact base — locked_edit becomes ProjectYamlArtifact.edit_interactively. The lock acquisition + reload logic stays*
- from `pm_core/cli/helpers.py` — **_record_status_timestamp**
    - *PR lifecycle-state timestamp side-effects belong with ProjectYamlArtifact mutation semantics in v2 (or in pm_core/supervisors/pr_stream.py when transitioning states). Currently CLI-side; in v2 the lif*
- from `pm_core/tui/app.py` — **WriteQueue ownership for project.yaml mutations**
    - *ProjectYamlArtifact owns project.yaml writes per v2; debounced WriteQueue semantics fold into Artifact.apply + on_change mechanism.*
- from `pm_core/tui/qa_loop_ui.py` — **_transition_pr_status (locked status update)**: Status transitions become ProjectYamlArtifact.propose_edit/apply operations using lifecycle.PRStatus.
- from `pm_core/tui/sync.py` — **store.locked_update wrapping for atomic project.yaml writes**
    - *Atomic edits to project.yaml are the ProjectYamlArtifact.apply / propose_edit responsibility; callers stop using store.locked_update directly.*
- from `pm_core/tui/sync.py` — **ProjectYamlParseError / StoreLockTimeout error surfacing to user**
    - *Becomes Artifact.apply error semantics; UI subscribes via Artifact.on_change / failure Emission rather than catching store exceptions.*

### `pm_core/sensorium/artifact/qa_library/instructions.py`

- from `pm_core/qa_authoring.py` — **qa_library_doc() — load packaged pm_core/docs/qa_library.md reference text**
    - *Reading the packaged qa_library.md reference doc is a sensorium concern (it documents the QaLibraryArtifact schema). Most natural home is alongside the QaLibraryArtifact subclass tree under sensorium/*
- from `pm_core/qa_instructions.py` — **_parse_frontmatter (YAML frontmatter splitter)**
    - *Shared utility — should live on a small base in pm_core/sensorium/artifact/qa_library/__init__ or be reused from a generic frontmatter helper. Plan doesn't name a shared frontmatter module — see MISSI*
- from `pm_core/qa_instructions.py` — **_list_dir + list_instructions/list_regression_tests/list_mocks/list_artifacts/list_all**
    - *Become .list() / .items() methods on each QaLibraryArtifact subclass; list_all becomes a small aggregator either on the package __init__ or a parent QaLibraryArtifact.*
- from `pm_core/qa_instructions.py` — **resolve_instruction_ref (fuzzy planner-output -> filename resolution)**
    - *Lives as classmethod on QaInstructionsArtifact (cross-searches regression + artifacts siblings).*
- from `pm_core/qa_instructions.py` — **get_instruction / get_mock (single-item load with body)**
    - *Become .read(id) / .get(id) on the corresponding QaLibraryArtifact subclass.*
- from `pm_core/qa_loop.py` — **_install_instruction_file / _install_artifact_files**
    - *Writing instruction files into the QA library is exactly QaLibraryArtifact.apply(). v2 lists qa_library/{instructions.py, mocks.py, regression.py, artifacts.py}.*
- from `pm_core/cli/qa.py` — **qa list / qa show / qa docs (read QA library entries)**
    - *Reads of the QA instruction library become QaLibraryArtifact / QaInstructionsArtifact reads; CLI delegates.*
- from `pm_core/cli/qa.py` — **qa add-instruction / add-regression / add-artifact (template scaffolding via _qa_add/_category_dir)**
    - *Template creation becomes an Artifact constructor / factory method on QaLibraryArtifact subclasses (instructions.py, regression.py, artifacts.py).*
- from `pm_core/tui/app.py` — **QA pane refresh (qa_instructions.list_all)**
    - *qa_instructions.py deleted → QaLibraryArtifact subclasses. _refresh_qa_pane + _update_qa_status_bar call sites switch to QaLibraryArtifact.read().*

### `pm_core/sensorium/artifact/qa_library/instructions.py (and siblings mocks.py/regression.py/artifacts.py)`

- from `pm_core/qa_instructions.py` — **qa_dir/instructions_dir/regression_dir/mocks_dir/artifacts_dir directory helpers**
    - *Each path becomes the on-disk root of the corresponding QaLibraryArtifact subclass; the mkdir-on-access semantics move into the Artifact's __init__ / resolve_link.*

### `pm_core/sensorium/artifact/qa_library/mocks.py`

- from `pm_core/spec_gen.py` — **get_spec_mocks_section (extract Mocks block from QA spec or fall back to qa_instructions library)**
    - *v2 has qa_library/mocks.py (the authoritative library). The 'extract from QA spec' fallback is legacy and should be retired (or moved alongside as a one-shot migration helper). The 'mocks block for pr*
- from `pm_core/cli/qa.py` — **qa mocks list / show (read mocks library)**
    - *Direct mapping to qa_library/mocks.py Artifact subclass.*
- from `pm_core/cli/qa.py` — **qa mocks add (scaffold mock file)**
    - *Mock Artifact factory.*

### `pm_core/sensorium/artifact/review_file.py`

- from `pm_core/plans/review.py` — **_write_review_file + _reviews_dir — reviews/*.txt file write**
    - *Becomes ReviewFileArtifact (already listed in v2 sensorium tree). Write/read/parse all go on the artifact class.*
- from `pm_core/plans/review.py` — **list_pending_reviews — scan reviews dir for NEEDS_FIX**
    - *Class-level / registry method on ReviewFileArtifact (e.g. ReviewFileArtifact.list_pending(root)).*
- from `pm_core/plans/review.py` — **parse_review_file — parse Step/Status/findings/fix_cmd sections**
    - *Becomes ReviewFileArtifact.read() / structured parse on the artifact.*

### `pm_core/sensorium/artifact/spec.py`

- from `pm_core/spec_gen.py` — **get_spec_mode / pr_spec_mode (global+per-PR spec mode resolution)**
    - *Becomes a property/method on SpecArtifact (or on its policy); per-PR review_spec flag continues to live in ProjectYamlArtifact. The mode enum (auto|review|prompt) belongs with the SpecArtifact.*
- from `pm_core/spec_gen.py` — **spec_dir / spec_file_path (on-disk path layout under pm/specs/<pr_id>/<phase>.md)**
    - *SpecArtifact owns the file path; PathService (sensorium/paths.py) may help with workdir-vs-canonical resolution.*
- from `pm_core/spec_gen.py` — **get_spec / set_spec (read with workdir-first fallback, write + log)**
    - *Becomes SpecArtifact.read() / apply()/propose_edit() with Artifact base semantics; workdir-vs-merged lookup uses PathView/WorkdirRegistry.*
- from `pm_core/spec_gen.py` — **has_pending_spec / get_pending_spec_phase / oldest_pending_spec_pr (queue queries for review UI)**
    - *Become SpecArtifact query methods or a SpecReviewQueue helper alongside it.*
- from `pm_core/spec_gen.py` — **approve_spec (clear spec_pending, optionally write edited text)**
    - *SpecArtifact.approve(edited_text=None) — uses Artifact.apply for the write and ProjectYamlArtifact.apply for clearing spec_pending.*
- from `pm_core/spec_gen.py` — **reject_spec (regenerate with feedback appended to description)**
    - *SpecArtifact.reject(feedback) triggers a re-run of the spec-generation Stream. The 'temporarily mutate description then restore' dance should be replaced by passing feedback as a separate Stream input*
- from `pm_core/spec_gen.py` — **PHASES constant ('impl','qa') and phase validation**
    - *Becomes an enum on SpecArtifact or a literal type. Phase identity also overlaps with PRStatus / lifecycle states (lifecycle.py).*
- from `pm_core/cli/pr.py` — **pr spec / pr spec-path / pr spec-approve**
    - *Generator moves to pm_core/prompts/spec_gen.py; SpecArtifact owns persistence; CLI stays as delegator*
- from `pm_core/tui/app.py` — **action_review_spec (spec_gen.oldest_pending_spec_pr)**
    - *spec_gen.py deleted; SpecArtifact + prompts/spec_gen.py replace it. Action stays in app.py but call site moves.*

### `pm_core/sensorium/artifact/walker_ui.py`

- from `pm_core/review/__init__.py` — **Package marker / docstring for review walker markdown layer**
    - *The walker's markdown surfaces (STATE.md, UI_FOCUS.md, per-cycle response/audit docs) become ReviewStateArtifact, UiFocusArtifact, ReviewCycleArtifact, CitationAuditCycleArtifact, ReviewResponseCycleA*
- from `pm_core/review/__init__.py` — **Re-export of md_parser submodule**
    - *Parser logic folds into the Artifact subclasses' read() implementations (parsing the on-disk markdown into structured payloads).*
- from `pm_core/review/__init__.py` — **Re-export of md_writer submodule**
    - *Writer logic folds into the Artifact subclasses' apply()/propose_edit() implementations.*
- from `pm_core/review/md_parser.py` — **ResponseBlock + parse_response_blocks + parse_interaction_log + parse_response_doc + ResponseDoc**
    - *These are the on-disk reader half of ReviewResponseCycleArtifact (per-cycle REVIEW_RESPONSE_CYCLE_N.md). The Artifact's read() should delegate to these parsers; the dataclasses become the typed payloa*
- from `pm_core/review/md_parser.py` — **AuditEntry + AuditDoc + parse_audit_doc + _extract_section + _extract_surfaced + tier/verdict/flag regexes**
    - *Reader half of CitationAuditCycleArtifact (CITATION_AUDIT_CYCLE_N.md). The mid-write entry-completeness gating logic must move with it since it's a real durability concern.*
- from `pm_core/review/md_parser.py` — **StateFile + parse_state**
    - *Reader half of ReviewStateArtifact (STATE.md).*
- from `pm_core/review/md_parser.py` — **FocusFile + parse_focus**
    - *Reader half of UiFocusArtifact (UI_FOCUS.md).*
- from `pm_core/review/md_parser.py` — **_StringTimestampLoader + _yaml_load (timestamp-as-string YAML loader)**
    - *Small shared utility used by parse_response_blocks/parse_state/parse_focus — colocate as a private helper inside walker_ui.py since all consumers move there. If a second sensorium Artifact ever needs *
- from `pm_core/review/md_parser.py` — **BLOCK_OPEN_RE / BLOCK_CLOSE_RE proposed-change fence parsing**
    - *Belongs with ReviewResponseCycleArtifact; the apply()/propose_edit() side on that Artifact will need to write the same fences, so consider extracting a small ResponseBlockCodec section within walker_u*
- from `pm_core/review/md_writer.py` — **YAML block-style dumper (_BlockDumper, _represent_str/_none, _dump_block_body, _render_block)**
    - *Specific to the proposed-change block serialization format of ReviewResponseCycleArtifact; lives next to the response-block parser.*
- from `pm_core/review/md_writer.py` — **_rewrite_block + update_response_block + append_interaction (response-block RMW)**
    - *Becomes methods on ReviewResponseCycleArtifact (apply/propose_edit semantics) — operates on a per-cycle response-block file.*
- from `pm_core/review/md_writer.py` — **update_state (STATE.md writer)**
    - *Becomes ReviewStateArtifact.apply — stamps last-transition, atomic write.*
- from `pm_core/review/md_writer.py` — **update_focus (UI_FOCUS.md writer)**
    - *Becomes UiFocusArtifact.apply — stamps timestamp last, atomic write.*

### `pm_core/sensorium/captures.py`

- from `pm_core/paths.py` — **captures_dir + CONTAINER_CAPTURES_MOUNT**
    - *Capture-bundle path resolution belongs with CaptureBundle/CaptureService. Container bind-mount constant moves with it (or to runtime/tmux_container.py if it's runtime-owned).*
- from `pm_core/qa_loop.py` — **_write_scenario_capture_file**
    - *CaptureBundle/CaptureService is the new home for capture-file writing (CaptureChannel on the emission side).*
- from `pm_core/cli/qa.py` — **qa captures-path (resolves capture bundle path for a PR)**
    - *CaptureService/CaptureBundle owns capture-path resolution; CLI thin-wraps.*

### `pm_core/sensorium/host_overrides.py`

- from `pm_core/cli/meta.py` — **Session-override write (set_override_path) tying workdir's pm_core to running session**
    - *Maps directly onto HostCodeOverride in sensorium/host_overrides.py.*

### `pm_core/sensorium/leases.py`

- from `pm_core/container.py` — **Container snapshot/labels for identification by PR/QA/session**
    - *ContainerKey in the lease hierarchy is the typed handle; the docker-label conventions used to find/cleanup containers should be co-located with ContainerKey or kept runtime-internal with ContainerKey *
- from `pm_core/pr_cleanup.py` — **unregister pane-registry entries for PR windows**
    - *Pane registry is subsumed by ResourceLease (TmuxWindowKey); releasing the lease unregisters. Foundational pane_registry.py stays per v2, but cleanup path moves into lease release.*
- from `pm_core/signoff.py` — **Per-PR fcntl launch lock (.signoff-launch-<session>-<pr>.lock)**
    - *Exactly the use case for ResourceLease+TmuxWindowKey — serialize concurrent claimants of one tmux window.*
- from `pm_core/cli/helpers.py` — **trigger_tui_merge_lock / trigger_tui_merge_unlock (specifically)**
    - *Merge lock is a per-PR resource lease in v2 (ChampionSlotKey / BranchRefKey). Lock acquisition/release replaces marker file.*

### `pm_core/sensorium/workdirs.py`

- from `pm_core/qa_loop.py` — **create_qa_workdir / create_scenario_workdir / _setup_clone_override**
    - *Workdir creation + clone setup is exactly what WorkdirRegistry+Workdir is for. Per-scenario workdir becomes a child Workdir leased by ScenarioStream.*
- from `pm_core/cli/helpers.py` — **_workdirs_dir / _ensure_workdir / _clone_workdir / _resolve_repo_id**
    - *v2 'Added: WorkdirRegistry+Workdir' — these workdir provisioning + per-PR lock + clone-and-checkout primitives are exactly the WorkdirRegistry/Workdir surface. The per-PR file-lock semantics belong on*
- from `pm_core/cli/meta.py` — **ensure_meta_workdir / _meta_workdir (clone pm repo into ~/.pm/workdirs/meta-<tag>, manage workdir lifecycle)**
    - *Maps onto WorkdirRegistry + Workdir; the meta workdir becomes a typed Workdir owned by the sensorium.*
- from `pm_core/cli/meta.py` — **_get_session_name_for_cwd / _get_pm_session helpers usage (session-tag derivation)**
    - *Session-tag derivation is part of identifying the active Workdir/Mind; cli helpers remain but the canonical lookup moves into sensorium.*
- from `pm_core/cli/pr.py` — **_stash_for_merge / _unstash_after_merge / _is_dirty_overlap_error / _dirty_file_paths / _workdir_is_dirty**
    - *Cross-workdir stash coordination explicitly listed in v2 under WorkdirRegistry+Workdir*

### `pm_core/streams/_shared_prompts.py`

- from `pm_core/bug_fix_prompts.py` — **_is_bug_pr — detect bug-fix PRs via plan==bugs or type==bug**
    - *Detection helper shared by impl_system, review_system, and qa prompts so they stay in sync. Fits the _shared.py 'cross-prompt fragments' bucket.*
- from `pm_core/guide.py` — **tui_section import from pm_core.prompt_gen**: Both prompts inline-import tui_section to render the TUI keybinding block.
    - *prompt_gen.py is on the 'Deleted' list; tui_section is explicitly named as a fragment in prompts/_shared.py. Both call sites update.*
- from `pm_core/loop_shared.py` — **extract_between_markers**
    - *Marker-bracket extraction is a cross-prompt parsing fragment shared by review/qa/watcher prompt output — fits the _shared.py 'cross-prompt fragments' bucket. Alternatively lives next to InputType.pars*
- from `pm_core/notes.py` — **Prompt integration: notes_section / notes_for_prompt / load_notes**
    - *These produce formatted prompt blocks ('## Session Notes', '## Additional X Instructions') for impl/review/qa/merge/watcher. v2 has prompts/_shared.py for cross-prompt fragments — notes injection is e*
- from `pm_core/notes.py` — **PROMPT_SECTIONS mapping (impl/review/qa/merge/watcher → sections)**
    - *Couples notes to prompt taxonomy; belongs alongside the prompt-side consumers.*
- from `pm_core/prompt_gen.py` — **tui_section**: Shared fragment describing TUI session keybindings
- from `pm_core/prompt_gen.py` — **_pr_notes_handoff_block / _format_pr_notes**: Shared fragment rendering PR notes handoff context
- from `pm_core/prompt_gen.py` — **_beginner_addendum**: Shared beginner-friendly addendum text
- from `pm_core/prompt_gen.py` — **_remote_sync_tip / _base_branch_sync_tip**: Shared git-sync tips fragments
- from `pm_core/prompt_gen.py` — **_auto_cleanup_addendum**: Shared cleanup-on-exit text fragment
- from `pm_core/prompt_gen.py` — **_review_loop_addendum**: Iteration-aware addendum for review-loop prompts
- from `pm_core/prompt_gen.py` — **_signoff_qa_scenarios_block**: Block listing QA scenarios for signoff context
    - *Explicitly enumerated in v2 _shared.py contents*
- from `pm_core/qa_instructions.py` — **instruction_summary_for_prompt (planner prompt fragment)**
    - *Cross-prompt fragment consumed by prompts/qa_planning.py and prompts/qa_concretize.py; v2 explicitly lists _shared.py as the home for cross-prompt fragments. May call into QaLibraryArtifact for data.*
- from `pm_core/qa_instructions.py` — **mocks_for_prompt (QA scenario prompt fragment)**
    - *Cross-prompt fragment; v2 names signoff_qa_scenarios_block in _shared.py, this is the same shape. Reads QaMocksArtifact bodies.*
- from `pm_core/regression_prompts.py` — **_FILING_ADDENDUM (file bugs/improvements as PRs, not in-place fixes)**
    - *v2 explicitly lists 'filing_addendum' as a cross-prompt fragment in prompts/_shared.py.*
- from `pm_core/regression_prompts.py` — **Session Context block (tmux session/pane, pm tui view/send tips)**
    - *Matches v2's 'tui_section' shared fragment; reused by signoff/QA prompts likely.*
- from `pm_core/spec_gen.py` — **spec_generation_preamble (inline 'Step 0' prompt block injected into impl/qa sessions)**
    - *Cross-prompt fragment shared by impl_system, qa_planning, etc. The QA-specific 'commit and push the spec' branch is conceptually a Workdir/git operation, but the prompt fragment itself belongs in _sha*
- from `pm_core/spec_gen.py` — **format_spec_for_prompt (renders an existing spec + staleness/review note for downstream session prompts)**
    - *Same rationale — used by impl_system.py and qa_*.py prompts; lives as a shared fragment.*
- from `pm_core/cli/cluster.py` — **Cluster-explore prompt construction (goal + tmp file + tui_section)**
    - *The prompt body is an InputType for ClusterExplorationStream; tui_section becomes _shared.tui_section per v2. Currently imports from pm_core.prompt_gen which v2 deletes (prompt_gen.py is in the Delete*
- from `pm_core/cli/plan.py` — **_MANUAL_TESTING_GUIDANCE shared prompt fragment**
    - *v2 explicitly lists prompts/_shared.py for cross-prompt fragments.*
- from `pm_core/cli/plan.py` — **tui_section import from prompt_gen**
    - *v2 lists tui_section explicitly as a _shared fragment; prompt_gen.py is deleted.*
- from `pm_core/cli/qa.py` — **qa mocks prompt (emit prompt fragment about mocks)**
    - *Mocks-related prompt fragment belongs in cross-prompt shared fragments.*

### `pm_core/streams/base.py`

- from `pm_core/bridge_client.py` — **get_status (mode + busy)**
    - *Busy/idle and control owner are now first-class on Stream (Stream.status: LifecycleState) and ControlOwner (in lifecycle.py / attention.py). No separate status RPC needed; consumers read Stream.status*
- from `pm_core/watcher_base.py` — **VERDICTS/KEYWORDS class config + parse_verdict abstract method**
    - *Becomes Stream.output_emissions classvar; verdict parsing moves into runtime/hook_entry.py emission decoding. Per-watcher prompt logic moves to pm_core/prompts/watcher/{auto_start,bug_fix,improvement_*

### `pm_core/streams/cluster_exploration.py`

- from `pm_core/cli/cluster.py` — **`pm cluster explore` subcommand — launch Claude with cluster summary prompt**
    - *v2 explicitly lists `cluster_exploration.py` under streams/. The interactive explore-with-Claude behavior is the canonical cluster-exploration Stream. CLI command would remain as a thin shim that crea*
- from `pm_core/cli/cluster.py` — **session_key / fresh-session semantics (`cluster:explore`)**
    - *Becomes a Stream instance_key under Mind.stream(role=ClusterExplorationStream, instance_key='explore'); LoopMode handles fresh vs resume.*

### `pm_core/streams/container_build.py`

- from `pm_core/cli/container.py` — **container build command (launches Claude session to author Dockerfile.pm-project)**
    - *v2 lists streams/container_build.py — this command becomes Mind.stream(role=ContainerBuildStream, ...). CLI wrapper in cli/container.py stays as thin entrypoint.*
- from `pm_core/cli/container.py` — **Direct tmux window launching for container-build session**
    - *tmux_mod calls + claude_launcher.build_claude_shell_cmd / launch_claude become Stream instantiation; window-role dedup handled by stream's tui_window_role*

### `pm_core/streams/discuss.py`

- from `pm_core/tui/pane_ops.py` — **launch_claude (interactive Claude session)**
    - *Free-form Claude session with pm context belongs alongside discuss.py (or a sibling 'shell' Stream). The embedded prompt string moves to pm_core/prompts/_shared.py or a new prompts/shell_system.py.*
- from `pm_core/tui/pane_ops.py` — **launch_discuss**
    - *DiscussStream. Embedded prompt moves to pm_core/prompts/ (new discuss_system.py) — currently inlined here.*

### `pm_core/streams/guide/assist.py`

- from `pm_core/guide.py` — **build_assist_prompt()**: Builds the 'help user decide next step' prompt with lifecycle overview, plan summary, and assessment task.
    - *Becomes the typed InputType class for GuideAssistStream (pm_core/streams/guide/assist.py). Same tui_section import migration applies.*
- from `pm_core/cli/guide.py` — **assist-mode prompt construction + launch**
    - *build_assist_prompt becomes the InputType for GuideAssistStream (pm_core/prompts/guide/assist.py); launch becomes Mind.stream(role=GuideAssistStream, runtime=TmuxHostRuntime).*

### `pm_core/streams/guide/setup.py`

- from `pm_core/guide.py` — **STEP_ORDER / STEP_DESCRIPTIONS / SETUP_STATES / is_setup_state**: Setup-state enum/constants describing the guide's step machine.
    - *Lives with the GuideSetupStream that consumes them.*
- from `pm_core/guide.py` — **needs_guide()**: Predicate used by session startup + TUI to decide whether to auto-launch the guide stream.
    - *Becomes a classmethod / module helper on GuideSetupStream; callers (session startup, TUI) update to import from there.*
- from `pm_core/guide.py` — **detect_state()**: Reads project.yaml + first plan file, classifies project into a setup state, returns context dict.
    - *Becomes GuideSetupStream's state-detection hook. Consumes store (stays) + plan_parser (stays) + graph (stays); migration is straightforward.*
- from `pm_core/guide.py` — **run_non_interactive_step()**: Shells out to `pm plan load` when state==has_plan_prs.
    - *In v2, the stream's non-interactive branch should call into PlanStreamSupervisor / the equivalent Stream rather than subprocess'ing the CLI. Worth flagging as a small cleanup during migration.*
- from `pm_core/cli/guide.py` — **guide state detection + non-interactive step loop**
    - *guide_mod.detect_state + run_non_interactive_step loop becomes part of GuideSetupStream's startup logic (with corresponding GuideAssistStream branch).*
- from `pm_core/cli/guide.py` — **setup-mode prompt construction + launch (with session save/resume)**
    - *build_setup_prompt → pm_core/prompts/guide/setup.py InputType; load_session/save_session/clear_session resume semantics are absorbed by Stream lifecycle + CallbackRegistry / TmuxHostRuntime session ha*
- from `pm_core/tui/pane_ops.py` — **launch_guide**
    - *Routed to guide/setup.py or guide/assist.py depending on project state (per v2 streams/guide/{setup,assist}.py). TUI shim dispatches.*
- from `pm_core/tui/sync.py` — **guide-mode state detection branch (guide.detect_state, _show_guide_view/_show_normal_view)**
    - *Guide workflow becomes guide/{setup,assist}.py streams; the tick-driven 'has-the-user-progressed?' check belongs to GuideSetupStream's watcher logic. The TUI keeps a thin delegator per the 'TUI integr*
- from `pm_core/guide.py` — **_beginner_mode_guide_section()**: Renders a beginner-mode fragment based on global setting state.
    - *Lives in the GuideSetupSystemPrompt InputType. Reads global settings via paths.py (stays).*
- from `pm_core/guide.py` — **build_setup_prompt()**: Large multi-section prompt builder for the setup workflow.
    - *Becomes the typed InputType class for GuideSetupStream. Imports of prompt_gen.tui_section get replaced by pm_core/prompts/_shared.tui_section per v2.*

### `pm_core/streams/impl.py`

- from `pm_core/spec_gen.py` — **generate_spec (orchestrates: existing-check, prompt build, launch_claude_print, write file, set spec_pending state)**
    - *Spec generation as a separately-driven Stream step. Effectively the 'Step 0' invocation — could be its own SpecGenStream, but v2 doesn't list one. Closest fit is folding it into ImplStream/QaPlanningS*
- from `pm_core/cli/pr.py` — **pr start + _launch_review_window + _add_companion_pane (impl-window launch)**
    - *Tmux launch + claude session resumption become ImplStream.start via pm_core/runtime/tmux_host.py*

### `pm_core/streams/impl_system.py`

- from `pm_core/bug_fix_prompts.py` — **_bug_fix_flow_block — impl-side bug-fix flow (captures dir + 5-step manual repro/test/fix/verify)**
    - *Conditionally appended to ImplSystemPrompt when _is_bug_pr(pr). Alternative target: pm_core/prompts/_shared.py if reused by regression/impl_fix.py as well.*
- from `pm_core/prompt_gen.py` — **generate_prompt (impl)**: Implementation work session prompt builder
- from `pm_core/cli/__init__.py` — **pm prompt**
    - *prompt_gen.py is deleted in v2; body must be rewritten to use a typed InputType from pm_core/prompts/. Click shell stays in cli/__init__.py.*

### `pm_core/streams/merge.py`

- from `pm_core/cli/pr.py` — **pr merge + _finalize_merge + _launch_merge_window + _pull_after_merge + _pull_from_workdir + _resolve_window_default**
    - *MergeStream + MergeConflictResolverStream own merge flow; launch via TmuxHostRuntime; git pulls via git_ops*
- from `pm_core/tui/app.py` — **_pending_merge_prs / _merge_input_required_prs / _merge_propagation_phase tracking**
    - *Merge phase state belongs in MergeStream lifecycle + MergeConflictResolverStream.*
- from `pm_core/tui/app.py` — **MergeLockScreen overlay on action_reload**
    - *Merge-lock is a MergeStream-owned ResourceLease per v2 (sensorium/leases.py); overlay trigger remains in app.py but lock state queried from ResourceLease.*
- from `pm_core/tui/review_loop_ui.py` — **_attempt_merge — run pm pr merge subprocess with resolve_window / propagation_only flags**
    - *MergeStream encapsulates the two-step merge command invocation.*
- from `pm_core/tui/review_loop_ui.py` — **_finalize_detected_merge — two-step MERGED verdict finalization with propagation phase tracking**
    - *Becomes MergeStream + MergeConflictResolverStream state machine per plan ('merge.py (MergeStream + MergeConflictResolverStream)'). _merge_propagation_phase set replaced by Stream.status / LifecycleSta*
- from `pm_core/tui/review_loop_ui.py` — **Merge verdict polling (extract_verdict_from_transcript on merge transcript)**
    - *verdict_transcript.py is deleted; replaced by pm-owned StreamTranscript capture inside MergeStream.*

### `pm_core/streams/meta_development.py`

- from `pm_core/cli/meta.py` — **Branch/tag/checkout logic (fresh clone vs resume, fetch+pull, checkout_branch)**
    - *MetaDevelopmentStream setup phase; consumes git_ops + Workdir.*
- from `pm_core/tui/pane_ops.py` — **launch_meta**
    - *Becomes MetaDevelopmentStream invocation; the load_watcher_plan_prs side-effect should move to WatcherSupervisor reconcile.*
- from `pm_core/cli/meta.py` — **_build_meta_prompt (large templated prompt with architecture/debugging/override docs)**
    - *Becomes a typed InputType under pm_core/prompts/. Not currently enumerated in the v2 prompts/ list, but follows the same pattern as other *_system prompts; sibling to streams/meta_development.py.*

### `pm_core/streams/plan/add.py`

- from `pm_core/cli/plan.py` — **plan_add — builds prompt + launches Claude + background review**
    - *Becomes PlanAddStream; prompt body moves to pm_core/prompts/plan/add.py. CLI handler shrinks to mind.stream(role=PlanAddStream, ...) invocation.*
- from `pm_core/tui/pane_ops.py` — **handle_plan_add**
    - *PlanAddStream; plan-id pre-computation stays inline as TUI shim or moves into PlanStreamSupervisor.create_plan.*

### `pm_core/streams/plan/breakdown.py`

- from `pm_core/cli/plan.py` — **plan_breakdown — prompt + Claude launch + background review**
    - *Prompt body moves to pm_core/prompts/plan/breakdown.py.*
- from `pm_core/tui/pane_ops.py` — **handle_plan_action (edit/breakdown/deps/load/review)**
    - *Each branch maps to a different PlanStream (plan/breakdown.py, plan/deps.py, plan/review.py, plan/import_.py for 'load'); 'edit' maps to PlanArtifact.edit_interactively. TUI shim becomes a 3-line disp*

### `pm_core/streams/plan/deps.py`

- from `pm_core/cli/plan.py` — **plan_deps — prompt + Claude launch + background review**
    - *Prompt body moves to pm_core/prompts/plan/deps.py.*

### `pm_core/streams/plan/fix.py`

- from `pm_core/cli/plan.py` — **plan_fix + _run_fix_command — build fix prompt from review file, launch Claude**
    - *Prompt scaffolding moves to pm_core/prompts/plan/fix.py.*
- from `pm_core/plans/review.py` — **build_fix_prompt — fix-variant prompt builder**
    - *Becomes the InputType prompt for streams/plan/fix.py.*

### `pm_core/streams/plan/import_.py`

- from `pm_core/cli/plan.py` — **plan_import + _run_plan_import — full import flow with Claude**
    - *Prompt body to pm_core/prompts/plan/import_.py.*

### `pm_core/streams/plan/review.py`

- from `pm_core/cli/plan.py` — **plan_review — prompt + Claude launch**
    - *Prompt body moves to pm_core/prompts/plan/review.py.*
- from `pm_core/plans/review.py` — **review_step — launches background claude review, parses verdict, writes file, reports via tmux**
    - *Becomes a PlanReviewStream (or post-step ReviewStream variant). The claude_launcher.launch_claude_print_background call is replaced by stream.run on a RuntimePlugin (likely TmuxHostRuntime or RawApiRu*
- from `pm_core/plans/review.py` — **_parse_verdict — extract PASS/NEEDS_FIX from claude output**
    - *Folds into ReviewStream verdict handling; pattern aligns with ALLOWED_VERDICTS classvar in pm_core/prompts/protocol.py.*
- from `pm_core/plans/review.py` — **REVIEW_PROMPTS templates per plan step**
    - *The plan-add/breakdown/deps/load/import/review check prompts become typed InputType prompt classes; each step's prompt lives in the corresponding pm_core/prompts/plan/{add,breakdown,deps,import_,fix,r*

### `pm_core/streams/pr_action.py`

- from `pm_core/tui/pane_ops.py` — **edit_plan (PR-edit launcher)**
    - *TUI keybinding 'e' on a PR → becomes a PRActionStream invocation; the shim here delegates to Stream.start via app dispatch. The launch_pane call moves into TmuxHostRuntime.*
- from `pm_core/tui/sync.py` — **_record_status_timestamp PR status bookkeeping**
    - *PR lifecycle state transitions are now driven by PRActionStream / lifecycle.py PRStatus; the timestamp recording lives alongside PRStatus transitions. Currently imported from pm_core.cli.helpers; that*

### `pm_core/streams/protocol.py`

- from `pm_core/loop_shared.py` — **match_verdict**
    - *Verdict-keyword matching against ALLOWED_VERDICTS classvar belongs with the InputType Protocol pattern (ALLOWED_VERDICTS). Could also live as a small helper in prompts/_shared.py.*
- from `pm_core/cli/fake_claude.py` — **ALL_VERDICT_CHOICES import (verdict catalogue)**
    - *The verdict catalogue currently in pm_core/fake_claude.py corresponds to the ALLOWED_VERDICTS classvar pattern noted in prompts/protocol.py. The CLI's click.Choice will need to be re-sourced from the *

### `pm_core/streams/qa_author.py`

- from `pm_core/qa_authoring.py` — **Driving the authoring session (writing the target file, interviewing the user) — implied caller responsibility**
    - *v2 lists streams/qa_author.py and the deletion note 'qa_authoring.py folds into QaAuthorStream'. The Stream subclass owns the session lifecycle; this file only built the prompt, but the surrounding or*
- from `pm_core/qa_loop.py` — **_generate_new_mock / generate_new_mocks (run Claude to author each mock fixture)**
    - *v2 lists qa_author.py / QaAuthorStream — and 'qa_authoring.py folds into QaAuthorStream'. Mock generation is an authoring task.*
- from `pm_core/cli/qa.py` — **qa author-instruction / author-regression / author-artifact (Claude-driven authoring stream)**
    - *QaAuthorStream — qa_authoring.py is explicitly listed as folding into QaAuthorStream. CLI delegates to Mind.stream(role=QaAuthorStream, ...).*
- from `pm_core/cli/qa.py` — **qa debug (Claude session against instruction, foreground/branch options)**
    - *Debug-an-instruction is an authoring/iteration session on the instruction Artifact; reuses QaAuthorStream with a debug-flavored InputType.*
- from `pm_core/tui/pane_ops.py` — **launch_qa_item**
    - *QaAuthorStream for category==instructions; for category==regression delegates to QaRegressionStream (streams/qa_regression.py). Prompt assembly moves to prompts/qa_authoring.py + prompts/regression/bu*

### `pm_core/streams/qa_authoring.py`

- from `pm_core/prompt_gen.py` — **generate_standalone_qa_prompt**: Standalone QA prompt (library-driven QA authoring/run)
- from `pm_core/qa_authoring.py` — **build_authoring_prompt — Claude prompt assembly for QA library authoring (per category: instructions/regression/artifacts), including category blurbs and label dispatch**
    - *v2 explicitly lists prompts/qa_authoring.py; the per-category blurb/label tables and the prompt template string belong here as a typed InputType class (likely with category as a field). Also explicitl*
- from `pm_core/qa_authoring.py` — **Category dispatch (instructions/regression/artifacts → label + blurb) and ValueError on unknown category**
    - *Moves with build_authoring_prompt; likely encoded as an enum/Literal field on the QaAuthoringInput InputType.*

### `pm_core/streams/qa_concretize.py`

- from `pm_core/qa_loop.py` — **_build_concretization_prompt**
    - *Already listed in v2.*
- from `pm_core/qa_loop.py` — **_build_concretize_cmd / _concretize_scenario / _launch_scenario_0**
    - *Concretization-as-a-Stream. The 'launch scenario 0' first-scenario distinction goes away — every scenario is just a QaConcretizeStream child.*

### `pm_core/streams/qa_finalize.py`

- from `pm_core/qa_finalize_prompt.py` — **build_qa_finalize_prompt**: Builds the QA finalize Claude prompt with scenario list, push/pull goals, and FINALIZE_DONE/FINALIZE_BLOCKED verdict pro
    - *Becomes a typed InputType class under pm_core/prompts/qa_finalize.py per v2's 'qa_finalize_prompt.py extracted into typed InputType classes' rule. ALLOWED_VERDICTS = {FINALIZE_DONE, FINALIZE_BLOCKED}.*
- from `pm_core/qa_finalize_prompt.py` — **Scenario worktree formatting helper (inline)**: Inline rendering of (scenario_index, verdict, worktree_path) tuples into bullet lines.
    - *Stays inside the InputType class; may share patterns with prompts/_shared.py if other QA prompts render scenario lists similarly.*
- from `pm_core/qa_finalize_prompt.py` — **Finalize verdict protocol (FINALIZE_DONE / FINALIZE_BLOCKED)**: Defines the two terminal tokens the finalize agent must emit.
    - *Encoded as ALLOWED_VERDICTS classvar on the QaFinalizePrompt InputType, consumed by QaFinalizeStream (streams/qa_finalize.py).*
- from `pm_core/qa_loop.py` — **_run_qa_finalize_pane (launching the finalize Claude session)**
    - *Becomes QaFinalizeStream.run with prompt built from prompts/qa_finalize.py.*

### `pm_core/streams/qa_planning.py`

- from `pm_core/prompt_gen.py` — **generate_qa_planner_prompt**: QA planner session prompt
- from `pm_core/qa_loop.py` — **parse_qa_plan (parses Claude's QA plan markdown into QAScenario list)**
    - *Parsing the output of the planning prompt belongs in QaPlanningStream (postprocessing of its Emission to produce QaScenarioRef artifacts). Could alternately live next to the prompt in prompts/qa_plann*
- from `pm_core/qa_loop.py` — **parse_new_mocks_from_plan**
    - *Same as parse_qa_plan — output of planning Stream is QaScenarioRef + MockSpec artifacts.*
- from `pm_core/cli/pr.py` — **pr qa**
    - *Entry into Qa* stream chain; CLI stays as delegator*

### `pm_core/streams/qa_planning.py (or thin shim retained in pm_core/tui/qa_loop_ui.py delegating to Mind.stream(QaPlanningStream, instance_key=pr_id))`

- from `pm_core/tui/qa_loop_ui.py` — **Keybinding action: focus_or_start_qa (t)**: Focus existing QA window or kick off a new QA run. Becomes a thin TUI shim invoking Mind.stream() for QA role.

### `pm_core/streams/qa_regression.py`

- from `pm_core/cli/qa.py` — **qa regression (run regression test by id, file_prs flag)**
    - *QaRegressionStream launched via Mind.stream(role=QaRegressionStream, ...). qa_loop.py is listed as rewritten into Qa*Streams + QaSupervisor.*

### `pm_core/streams/qa_scenario.py`

- from `pm_core/prompt_gen.py` — **generate_qa_interactive_prompt**: QA interactive (scenario concretize/run) prompt
    - *Could also split between qa_scenario.py and qa_concretize.py depending on intent*
- from `pm_core/qa_loop.py` — **_launch_scenarios_in_tmux**
    - *Becomes 'QaSupervisor spawns N QaScenarioStream instances with TmuxHostRuntime'. The launch mechanics belong in runtime/tmux_host.py; the orchestration of N parallel children belongs to the supervisor*

### `pm_core/streams/qa_verification.py`

- from `pm_core/prompt_gen.py` — **generate_qa_child_prompt**: QA child (verification) session prompt
- from `pm_core/qa_loop.py` — **_build_verification_prompt**
    - *Already in v2.*
- from `pm_core/qa_loop.py` — **_poll_tmux_verdicts (long polling state machine reading transcripts, deciding pass/fail/retry/verify)**
    - *The verdict polling loop is the meat of the QA flow. Becomes (a) QaScenarioStream emitting verdict Emissions via tagged output detection inside TmuxHostRuntime, and (b) QaVerificationStream/QaSupervis*
- from `pm_core/qa_loop.py` — **_verify_single_scenario**
    - *One QaVerificationStream invocation per flagged scenario.*
- from `pm_core/cli/qa.py` — **qa run (run instruction against a PR)**
    - *Running an instruction against a PR maps to a verification stream under the per-PR Supervisor.*
- from `pm_core/cli/qa.py` — **qa standalone (run instruction outside PR context)**
    - *Same Stream as `qa run` with no PR-binding; or a QaStandalone variant — fits under qa_verification.py.*

### `pm_core/streams/regression/bug_reproduce.py`

- from `pm_core/regression_prompts.py` — **build_regression_test_prompt — top-level assembly**
    - *Becomes a typed InputType class (per v2 prompts/ pattern) producing the regression-test prompt; explicit listing under prompts/regression/{bug_reproduce.py, impl_fix.py}.*
- from `pm_core/regression_prompts.py` — **Captures block (paths under ~/.pm/sessions/<tag>/captures/regression/, not git-tracked)**
    - *Regression-specific captures guidance; could partially share with CaptureService/captures.py docs but the prose lives with the prompt. CaptureBundle/CaptureService in sensorium/captures.py is the runt*

### `pm_core/streams/review.py`

- from `pm_core/review_loop.py` — **parse_review_verdict and _match_verdict**
    - *Verdict parsing on ReviewStream; loop_shared.match_verdict is deleted*
- from `pm_core/review_loop.py` — **ReviewLoopState**
    - *Replaced by ReviewStream instance state plus LifecycleState*
- from `pm_core/review_loop.py` — **_generate_loop_id**
    - *Becomes instance_key/correlation_id via Mind.stream()*
- from `pm_core/review_loop.py` — **_run_claude_review (single iteration orchestration)**
    - *ReviewStream advance under LoopMode.kill_restart*
- from `pm_core/review_loop.py` — **run_review_loop_sync (loop body plus history plus on_iteration)**
    - *Becomes ReviewStream driven by LoopMode.kill_restart, bounded by StreamPolicy.max_iterations*
- from `pm_core/cli/pr.py` — **pr review (loop + plain)**
    - *ReviewStream owns launch; LoopMode.kill_restart on review.requested*
- from `pm_core/tui/review_loop_ui.py` — **z d handler — stop loop or fresh review**
    - *Keybinding handler becomes a thin call into ReviewStream lifecycle: takeover/restart via ControlOwner + LoopMode.kill_restart. The kill-window side effect moves into TmuxHostRuntime cleanup.*
- from `pm_core/tui/review_loop_ui.py` — **zz d handler — start or supersede loop**
    - *Becomes ReviewStream.start() with LoopMode.kill_restart on review.requested per plan: 'ReviewStream — uses LoopMode.kill_restart on review.requested'.*
- from `pm_core/tui/review_loop_ui.py` — **_start_loop — launch background review loop with transcript dir, resume state, runtime_state mirror**
    - *Stream lifecycle owns this; transcript_dir handling moves to StreamTranscript (pm_core/agent/transcript.py); runtime_state mirror replaced by EmissionLog.*
- from `pm_core/tui/review_loop_ui.py` — **_stop_loop / stop_loop_for_pr — graceful stop request**
    - *Stream.shutdown / LifecycleState transition.*
- from `pm_core/tui/review_loop_ui.py` — **Review verdict mirror for non-loop review windows (extract_verdict_from_transcript)**
    - *Same — StreamTranscript-based verdict extraction inside ReviewStream.*

### `pm_core/streams/review_system.py`

- from `pm_core/bug_fix_prompts.py` — **_bug_fix_review_block — review-side bug-fix checklist (pre/post captures, failing test, scope)**
    - *Conditionally appended to ReviewSystemPrompt when _is_bug_pr(pr).*
- from `pm_core/prompt_gen.py` — **generate_review_prompt**: Review session prompt builder
- from `pm_core/prompt_gen.py` — **generate_review_loop_prompt**: Thin wrapper composing review prompt + loop addendum
- from `pm_core/review_loop.py` — **Verdict constants and ALL_VERDICTS**
    - *Becomes ALLOWED_VERDICTS classvar per prompts/protocol.py*

### `pm_core/streams/signoff.py`

- from `pm_core/prompt_gen.py` — **generate_signoff_prompt**: Signoff session prompt builder
- from `pm_core/signoff.py` — **SIGNOFF_* verdict constants + ALLOWED_VERDICTS list**
    - *Per v2 InputType Protocol's ALLOWED_VERDICTS classvar pattern; the prompt class owns the verdict vocabulary it instructs Claude to emit.*
- from `pm_core/signoff.py` — **Module docstring: gate-at-merge invariant + audit-trail-via-pm-pr-note philosophy**
    - *Behavioral contract for the Claude pane — belongs in the system prompt / InputType docstring.*
- from `pm_core/signoff.py` — **SIGNOFF_VERDICT_ICONS / SIGNOFF_VERDICT_STYLES / signoff_verdict_icon()**
    - *Display markers used by TUI tech tree + pm pr list; live with SignoffStream as the canonical rendering metadata. Could alternately live in tui/ but kept core per the original comment.*
- from `pm_core/signoff.py` — **signoff_window_name() + window-name convention**
    - *PRActionStream subclasses declare tui_window_role; window-name derivation belongs on SignoffStream.*
- from `pm_core/signoff.py` — **fresh_recorded_verdict() / latest_signoff_verdict() readers**
    - *Read helpers used by auto-sequence adoption logic and TUI display; live with SignoffStream alongside the icon helpers.*
- from `pm_core/signoff.py` — **_evidence_pane_cmd() — shell script that prints captures tree + qa_status.json + diff**
    - *Stream-specific pane construction; the captures-tree portion will eventually consume CaptureService/CaptureBundle from sensorium/captures.py and the QaStatusArtifact rather than shelling out to `pm qa*
- from `pm_core/signoff.py` — **launch_signoff_window() — full tmux window launch (evidence pane + Claude pane, fresh/background/origin params, container wrap, pane_registry registration, layout rebalance, per-PR fcntl lock)**
    - *This is exactly what SignoffStream.start() does. The pane-launching mechanics decompose: prompt generation -> pm_core/prompts/signoff.py; Claude pane spawn -> TmuxHostRuntime / TmuxContainerRuntime (p*
- from `pm_core/signoff.py` — **_BOUNCE_HOP_STATUS map + decide_signoff_hop() (pure verdict->hop)**
    - *Routing policy of the SignoffStream. Could alternately live on the SignoffSystemPrompt's ALLOWED_VERDICTS metadata, but the mapping to PR lifecycle states is stream-side.*
- from `pm_core/cli/pr.py` — **pr signoff**
    - *SignoffStream + SignoffSystemPrompt own this*
- from `pm_core/cli/pr.py` — **pr signoff-record (hidden)**
    - *Verdict recording becomes Emission append into StreamTranscript + EmissionLog*

### `pm_core/streams/spec_gen.py`

- from `pm_core/spec_gen.py` — **_build_spec_prompt (Claude prompt for generating a phase spec)**
    - *Listed explicitly in v2 under prompts/. Becomes the InputType class for spec generation.*

### `pm_core/streams/watcher/auto_start.py`

- from `pm_core/prompt_gen.py` — **generate_watcher_prompt**: Watcher session prompt (general auto-start watcher)
- from `pm_core/cli/watcher.py` — **Per-watcher-type prompt selection (discovery / bug-fix-impl / improvement-fix-impl / auto-start)**
    - *Dispatch goes away — each watcher Stream subclass (streams/watchers/{auto_start,bug_fix_impl,improvement_fix_impl,discovery_supervisor}.py) declares its own InputType from prompts/watcher/{auto_start,*
- from `pm_core/watchers/auto_start_watcher.py` — **generate_prompt() — auto-start watcher prompt**: Prompt construction (currently a thin wrapper around prompt_gen.generate_watcher_prompt) becomes a typed InputType class
    - *Consumes project.yaml data (now via ProjectYamlArtifact) and iteration/loop_id/auto_start_target/meta_pm_root inputs.*
- from `pm_core/watchers/discovery_supervisor.py` — **generate_prompt() — builds discovery supervisor prompt via prompt_gen.generate_discovery_supervisor_prompt**
    - *No dedicated discovery_supervisor prompt file is listed in v2 under prompts/watcher/ (only auto_start, bug_fix, improvement_fix, watcher_review). MISSING/UNCLEAR: appears to need its own prompts/watch*

### `pm_core/streams/watcher/bug_fix.py`

- from `pm_core/prompt_gen.py` — **generate_bug_fix_impl_prompt**: Bug-fix impl prompt builder
- from `pm_core/watchers/bug_fix_impl_watcher.py` — **Prompt generation (generate_bug_fix_impl_prompt)**
    - *Typed InputType class replaces prompt_gen.generate_bug_fix_impl_prompt; pm_core/prompt_gen.py is deleted per plan.*

### `pm_core/streams/watcher/improvement_fix.py`

- from `pm_core/prompt_gen.py` — **generate_improvement_fix_impl_prompt**: Improvement-fix impl prompt builder
- from `pm_core/watchers/improvement_fix_impl_watcher.py` — **generate_prompt (delegates to prompt_gen.generate_improvement_fix_impl_prompt)**
    - *Becomes a typed InputType class; consumes project data via ProjectYamlArtifact*

### `pm_core/streams/watcher/watcher_review.py`

- from `pm_core/prompt_gen.py` — **generate_watcher_review_prompt**: Watcher-review prompt builder

### `pm_core/streams/watchers/__init__.py`

- from `pm_core/watcher_base.py` — **WATCHER_TYPE/DISPLAY_NAME/WINDOW_NAME class config**
    - *Becomes Stream subclass class attributes + WATCHER_REGISTRY; tmux window role moves to PRActionStream.tui_window_role (n/a for watchers — likely a separate base attribute).*
- from `pm_core/cli/watcher.py` — **Watcher type registry lookup (get_watcher_class / list_watcher_types)**
    - *v2 names this explicitly: 'streams/watchers/__init__.py with WATCHER_REGISTRY'. The CLI keeps calling a registry; only the module path and class shape change.*
- from `pm_core/tui/watcher_ui.py` — **WATCHER_PLANS constant (bugs/improvements plan metadata)**
    - *Belongs alongside WATCHER_REGISTRY as static config consumed by WatcherSupervisor/discovery streams.*
- from `pm_core/watchers/__init__.py` — **WATCHER_REGISTRY dict**: Explicitly called out in v2: 'streams/watchers/__init__.py with WATCHER_REGISTRY'. Registry now maps to Stream subclasse
- from `pm_core/watchers/__init__.py` — **get_watcher_class() lookup helper**: Lives next to the registry in the new watchers package; same semantics, consumed by WatcherSupervisor and CLI delegators
- from `pm_core/watchers/__init__.py` — **list_watcher_types() metadata helper**: Display/window/interval metadata; in v2 the Stream base declares tui_keybinding/tui_glyph/tui_window_role classvars, so 
    - *WATCHER_TYPE/DISPLAY_NAME/WINDOW_NAME/DEFAULT_INTERVAL classvars need to be reconciled with PRActionStream's declared classvars (tui_window_role, tui_glyph) — may need a small adapter.*

### `pm_core/streams/watchers/auto_start.py`

- from `pm_core/tui/auto_start.py` — **Auto-start orchestration policy (check_and_start, toggle, auto_sequence_for_pr, set_target, _disable, is_enabled, get_target)**
    - *Becomes an AutoStartWatcherStream + WatcherSupervisor. The 'target + transitive deps + start ready' policy is the watcher's core loop.*
- from `pm_core/tui/auto_start.py` — **Transitive dependency computation (_transitive_deps)**
    - *Internal helper for the watcher; could also call into pm_core/graph.py which stays.*
- from `pm_core/tui/review_loop_ui.py` — **_auto_review_idle_prs — transition in_progress → in_review and run pm pr review --background, start ReviewLoop**
    - *Per plan 'streams/watchers/{auto_start.py}'; AutoStartWatcher reacts to impl.idle emission, transitions PR, and instantiates ReviewStream.*
- from `pm_core/tui/review_loop_ui.py` — **spec_pending re-arm on idle (mark_active when pr.spec_pending)**
    - *Policy lives with the auto-start watcher.*
- from `pm_core/tui/sync.py` — **auto-start-on-newly-merged dispatch (check_and_start)**
    - *Auto-start watcher is its own Stream subclass under streams/watchers/. The 'PR merged -> consider starting next ready PR' edge is a subscription on the per-PR LifecycleGlobalChannel rather than an inl*
- from `pm_core/watchers/__init__.py` — **Import of AutoStartWatcher**: Re-export of AutoStartWatcher; in v2 becomes import of the AutoStart watcher Stream class.
- from `pm_core/watchers/auto_start_watcher.py` — **AutoStartWatcher class (concrete watcher role)**: Subclass of BaseWatcher becomes a Stream subclass under streams/watchers/, registered in WATCHER_REGISTRY in __init__.py
    - *WATCHER_TYPE/DISPLAY_NAME/WINDOW_NAME/DEFAULT_INTERVAL/VERDICTS classvars become Stream-declared metadata (tui_window_role, tag declarations, policy).*
- from `pm_core/watchers/auto_start_watcher.py` — **parse_verdict() — extract READY/INPUT_REQUIRED from output**: Verdict parsing (currently uses loop_shared.match_verdict) becomes part of the AutoStartStream's emission-classification
    - *loop_shared.py is deleted (CallbackRegistry replaces it); a shared verdict-matching helper, if still needed, would live alongside watcher Streams or in agent/tags.py.*
- from `pm_core/watchers/auto_start_watcher.py` — **auto_start_target / meta_pm_root parameters (auto-start target wiring)**: Constructor-injected parameters carrying which project/meta-PM root is being auto-started become Stream instance_key/inp
    - *Meta-PM linkage (meta_pm_root) is a cross-mind concern; if it implies cross-project supervision, it touches collaboration/identity.py — flag for review.*

### `pm_core/streams/watchers/bug_fix_impl.py`

- from `pm_core/watchers/__init__.py` — **Import of BugFixImplWatcher**: Re-export of bug-fix impl watcher; moves to streams/watchers/bug_fix_impl.py.
- from `pm_core/watchers/bug_fix_impl_watcher.py` — **Watcher class definition + lifecycle (BaseWatcher subclass)**
    - *Becomes a Stream subclass under streams/watchers/, registered in WATCHER_REGISTRY in streams/watchers/__init__.py. BaseWatcher itself is deleted (replaced by Stream base + WatcherSupervisor).*
- from `pm_core/watchers/bug_fix_impl_watcher.py` — **Verdict parsing (parse_verdict scanning trailing lines for READY/INPUT_REQUIRED)**
    - *Verdict extraction becomes part of the Stream's output_emissions handling (Emission/tag matching via TagRegistry); loop_shared.match_verdict is deleted along with loop_shared.py.*
- from `pm_core/watchers/bug_fix_impl_watcher.py` — **Auto-merge on PASS distinguishing behavior**
    - *Auto-merge policy lives on the BugFixImplStream (likely as a StreamPolicy flag or supervisor hand-off to MergeStream). Not visible in this file's body but documented in module docstring.*

### `pm_core/streams/watchers/discovery_supervisor.py`

- from `pm_core/watchers/__init__.py` — **Import of DiscoverySupervisorWatcher**: Re-export of discovery supervisor watcher; moves to streams/watchers/discovery_supervisor.py.
- from `pm_core/watchers/discovery_supervisor.py` — **DiscoverySupervisorWatcher class (watcher role registration: type/display/window/interval/verdicts)**
    - *Becomes a Stream subclass under streams/watchers/, registered in WATCHER_REGISTRY in streams/watchers/__init__.py. Loop engine inherited from BaseWatcher is supplanted by Stream base + WatcherSupervis*
- from `pm_core/watchers/discovery_supervisor.py` — **meta_pm_root forwarding (passes meta_pm_root through to prompt + launch cmd)**
    - *Becomes Stream input/policy field; meta_pm_root represents the supervised project root and would be declared via the Stream's typed InputType.*

### `pm_core/streams/watchers/improvement_fix_impl.py`

- from `pm_core/watchers/__init__.py` — **Import of ImprovementFixImplWatcher**: Re-export of improvement-fix impl watcher; v2 plan lists improvement_fix_impl.py under streams/watchers/ (filename infer
- from `pm_core/watchers/improvement_fix_impl_watcher.py` — **ImprovementFixImplWatcher class (Stream subclass, no auto-merge)**
    - *Becomes a Stream subclass; loop_engine replaced by Stream base + WatcherSupervisor; verdict-as-emission via Emission/Mailbox; stop_before_merge encoded in StreamPolicy*
- from `pm_core/watchers/improvement_fix_impl_watcher.py` — **parse_verdict (READY/INPUT_REQUIRED via match_verdict)**
    - *VERDICTS classvar / ALLOWED_VERDICTS pattern from prompts/protocol.py; loop_shared.match_verdict deleted, predicate inlined into stream or shared helper inside streams/watchers/__init__*
- from `pm_core/watchers/improvement_fix_impl_watcher.py` — **WATCHER_TYPE / DISPLAY_NAME / WINDOW_NAME / DEFAULT_INTERVAL metadata**
    - *tui_window_role / DEFAULT_INTERVAL become Stream classvars or schedule() args; registered in streams/watchers/__init__.py WATCHER_REGISTRY*
- from `pm_core/watchers/improvement_fix_impl_watcher.py` — **meta_pm_root parameter (cross-project meta-PM context)**
    - *Becomes a Stream input or instance_key dim; cross-project handle should likely resolve via collaboration/identity.py ProjectIdentity*

### `pm_core/streams/watchers/watcher_review.py`

- from `pm_core/tui/pane_ops.py` — **launch_watcher_review**
    - *Maps to WatcherReviewStream; uses prompts/watcher/watcher_review.py for the prompt (currently generate_watcher_review_prompt in prompt_gen.py which is slated for deletion).*

### `pm_core/supervisors/mind.py`

- from `pm_core/tui/auto_start.py` — **Breadcrumb persistence across TUI restart (save_breadcrumb, consume_breadcrumb, _MERGE_RESTART_MARKER, has_merge_restart_marker)**
    - *Mind-level resume-after-restart: persist watcher set, running streams, stop_before_merge. EmissionLog already gives durable per-stream state, so breadcrumb shrinks to 'which watchers were running + th*
- from `pm_core/tui/auto_start.py` — **Watcher resume from breadcrumb (watchers_data loop calling watcher_ui.start_watcher)**
    - *WatcherSupervisor + MindSupervisor own watcher recreation from persisted config.*

### `pm_core/supervisors/plan_stream.py`

- from `pm_core/cli/plan.py` — **background review kickoff (review_mod.review_step calls)**
    - *Per-stream auto-review becomes PlanStreamSupervisor responsibility; each PlanXStream emits completion, supervisor spawns ReviewStream. Reduces duplicated review_step boilerplate across handlers.*

### `pm_core/supervisors/pr_stream.py`

- from `pm_core/pr_cleanup.py` — **kill PR tmux windows (via kill_pr_windows)**
    - *PRStreamSupervisor.shutdown() iterates owned streams; each Stream's TmuxHostRuntime/TmuxContainerRuntime releases its TmuxWindowKey lease, which kills the window.*
- from `pm_core/pr_cleanup.py` — **cleanup_pr_resources orchestration entry point (callable from CLI/TUI)**
    - *Becomes PRStreamSupervisor.shutdown(pr) — fans out across owned streams' runtime.shutdown() and lease releases.*
- from `pm_core/pr_cleanup.py` — **format_summary — human-readable cleanup result string**
    - *Either a method on PRStreamSupervisor or a small helper there; consumed by CLI 'pm pr cleanup' surface. Could alternately stay in pm_core/cli/ as a presentation helper.*
- from `pm_core/qa_loop.py` — **_persist_scenario_verdicts (writes verdicts back onto PR/branch)**
    - *Cross-scenario aggregation that updates PR state belongs to the PRStreamSupervisor (it owns QA streams under a PR). Alternative: project_yaml.py artifact if persistence is just yaml writes.*
- from `pm_core/qa_loop.py` — **run_qa_sync (top-level orchestration: plan -> mocks -> launch -> poll -> verify -> finalize)**
    - *The whole sequence is a Supervisor's run() — PRStreamSupervisor coordinates QaPlanningStream, QaAuthorStream (mocks), QaConcretizeStream*, QaScenarioStream*, QaVerificationStream*, QaFinalizeStream. T*
- from `pm_core/qa_loop.py` — **_execute_and_finalize**
    - *Same — Supervisor-level sequencing.*
- from `pm_core/review_loop.py` — **start_review_loop_background (thread wrapper plus on_complete)**
    - *Background lifecycle owned by PRStreamSupervisor*
- from `pm_core/runtime_state.py` — **sweep_stale_states (TUI-restart reset of in-flight entries)**: PRStreamSupervisor (and/or MindSupervisor) owns liveness reconciliation on Mind startup: Stream.status (LifecycleState) 
- from `pm_core/runtime_state.py` — **QA pane worst-state aggregation across scenario panes**: Becomes PRStreamSupervisor (or a dedicated QaSupervisor under supervisors/) aggregating LifecycleState across child QaSc
- from `pm_core/signoff.py` — **apply_signoff_hop() — auto-sequence-only side-effect that transitions sign_off -> qa/in_review/in_progress and clears pr['signoff']**
    - *PR-level lifecycle transition driven by a child stream's verdict — this is the PRStreamSupervisor's job. The state write itself ultimately goes through ProjectYamlArtifact.propose_edit.*
- from `pm_core/cli/pr.py` — **pr cleanup + _cleanup_pr + _clear_workdir**
    - *pr_cleanup.py is deleted in v2; fans out to PRStreamSupervisor.teardown + ResourceLease release + WorkdirRegistry*
- from `pm_core/cli/pr.py` — **pr close**
    - *Becomes PRStreamSupervisor.close (state transition + gh_ops + branch cleanup)*
- from `pm_core/cli/pr.py` — **pr auto-sequence + _impl_window_pane + _review_window_pane + _signoff_window_pane + _check_review_verdict + _check_signoff_verdict + _check_impl_idle + _qa_status_for + _retire_signoff_window + _auto_seq_transcript_dir**
    - *Auto-sequencing impl->review->qa->signoff->merge is PRStreamSupervisor's job; verdict polling becomes CallbackRegistry.wait_for at pm_core/agent/callbacks.py; idle detection becomes runtime capability*
- from `pm_core/tui/app.py` — **Stale merge-lock cleanup on startup**
    - *Merge-lock lifecycle belongs to PRStreamSupervisor/MergeStream teardown.*
- from `pm_core/tui/auto_start.py` — **Auto-start review-loop fan-out (_auto_start_review_loops)**
    - *Per-PR stream supervisor decides when to spawn a ReviewStream; the watcher signals 'target dep-tree relevance' via a Channel.*
- from `pm_core/tui/auto_start.py` — **Auto-start QA fan-out (_auto_start_qa_loops, skip_qa policy)**
    - *PRStreamSupervisor handles QA stream lifecycle; skip_qa becomes a StreamPolicy field.*
- from `pm_core/tui/pr_view.py` — **_do_cleanup / _cleanup_worker / cleanup_pr / cleanup_then_action**
    - *pr_cleanup.py is deleted; cleanup logic fans out into PRStreamSupervisor teardown + runtime cleanup hooks + ResourceLease release. The TUI keybinding entry (cleanup_pr) stays but delegates to supervis*
- from `pm_core/tui/qa_loop_ui.py` — **Keybinding action: start_qa**: Create QALoopState, transition status in_review→qa, spawn background. Becomes PRStreamSupervisor.start_qa() spawning Qa*
- from `pm_core/tui/qa_loop_ui.py` — **Keybinding action: fresh_start_qa (z t)**: Stop running QA and restart. Maps to PRStreamSupervisor kill_restart of QA streams using LoopMode.kill_restart.
- from `pm_core/tui/qa_loop_ui.py` — **Keybinding action: start_or_stop_qa_loop (zz t)**: Toggle self-driving QA loop with required-pass counting. PRStreamSupervisor owns consecutive_pass_threshold via StreamPo
- from `pm_core/tui/qa_loop_ui.py` — **stop_qa public API**: Graceful stop request → Stream.shutdown / supervisor stop.
- from `pm_core/tui/qa_loop_ui.py` — **_on_qa_complete — verdict dispatch + self-driving counting + auto-merge / review restart**: Verdict-driven lifecycle dispatch (PASS→merge or restart, NEEDS_WORK→ReviewStream restart, INPUT_REQUIRED→pause) is core
- from `pm_core/tui/qa_loop_ui.py` — **_start_self_driving_review**: PRStreamSupervisor spawns ReviewStream directly when QA returns NEEDS_WORK in self-driving mode.
- from `pm_core/tui/qa_loop_ui.py` — **_trigger_auto_merge**: Merge gating becomes supervisor responsibility (stop_before_merge policy + MergeStream spawn).
- from `pm_core/tui/review_loop_ui.py` — **_maybe_start_qa — auto-transition in_review → qa and start QA on review PASS (with skip_qa branch)**
    - *PRStreamSupervisor owns the cross-stream transition (review.passed → start QaPlanningStream). skip_qa policy belongs in StreamPolicy. Self-driving QA flag moves to Supervisor state.*
- from `pm_core/tui/review_loop_ui.py` — **_maybe_auto_merge — auto-merge on PASS gated by auto-start + stop_before_merge**
    - *PRStreamSupervisor orchestrates review.passed → MergeStream; stop_before_merge becomes StreamPolicy.stop_before_merge per plan.*
- from `pm_core/tui/review_loop_ui.py` — **_on_merge_success — cleanup tracker + kick dependents**
    - *Supervisor teardown hook; check_and_start becomes a Supervisor event.*
- from `pm_core/tui/sync.py` — **do_normal_sync: PR sync orchestration (deep-copy data, run pr_sync.sync_prs in executor, apply merged statuses under store.locked_update)**
    - *Per-PR lifecycle (detect merged, mark merged, record timestamp) is PRStreamSupervisor's job. pr_sync.py itself STAYS per v2; the orchestration around it (lock, status timestamp, race avoidance) moves *
- from `pm_core/tui/sync.py` — **_kill_merged_pr_windows: tear down windows/containers/sockets/registry for merged PRs (via pr_cleanup.cleanup_pr_resources)**
    - *pr_cleanup.py is DELETED in v2 ('fans out across Supervisor teardown + runtime cleanup hooks'). Window/container/socket teardown becomes PRStreamSupervisor.shutdown() composed with the runtime's clean*
- from `pm_core/tui/sync.py` — **startup_github_sync: one-shot GitHub PR-state pull on launch (sync_from_github + atomic status apply + merged cleanup + auto-start)**
    - *Same as do_normal_sync but with a different sync source. The GitHub-specific dispatch (backend == 'github') is a backend capability check; pr_sync.sync_from_github STAYS, but the orchestration moves t*

### `pm_core/supervisors/protocol.py`

- from `pm_core/watcher_manager.py` — **get_watcher / get_state / find_by_type / find_state_by_type**
    - *Supervisor.streams(role=, alive_only=) plus StreamRecord supplant these lookups; per-stream state replaced by Stream.status (LifecycleState) and EmissionLog queries.*
- from `pm_core/tui/watcher_ui.py` — **is_running (check watcher liveness)**
    - *Subsumed by Stream.status (LifecycleState) and Supervisor.streams(role=, alive_only=True) on the StreamRecord dataclass.*

### `pm_core/supervisors/watcher.py`

- from `pm_core/watcher_manager.py` — **register/unregister watcher instances**
    - *WatcherSupervisor takes over registration/tracking of watcher Streams; StreamRecord dataclass in supervisors/protocol.py replaces the dict-of-watchers.*
- from `pm_core/watcher_manager.py` — **start watcher in background thread (with on_iteration/on_complete callbacks, transcript_dir)**
    - *Stream lifecycle (start) is now driven by Mind.stream(role=...) + Supervisor; threading + callback wiring is replaced by the RuntimePlugin seam plus CallbackRegistry (pm_core/agent/callbacks.py). tran*
- from `pm_core/watcher_manager.py` — **stop / stop_all (graceful stop via stop_requested flag)**
    - *Stream.status / LifecycleState + Supervisor teardown replaces stop_requested flag mutation; termination reasons live in pm_core/agent/lifecycle.py.*
- from `pm_core/watcher_manager.py` — **duplicate-start guard (running flag set eagerly)**
    - *Idempotent stream(role=, instance_key=) on Mind/Supervisor replaces the eager-set-running guard.*
- from `pm_core/cli/watcher.py` — **Blocking user watcher loop (_run_user_watcher_loop)**
    - *Loop semantics move into WatcherSupervisor; the CLI becomes a thin delegator that asks Mind.supervisor('watcher') to run a chosen watcher Stream.*
- from `pm_core/cli/watcher.py` — **Regression-loop meta (_run_regression_loop) — fan-out of discovery + bug-fix-impl + improvement-fix-impl**
    - *WatcherManager is being deleted (watcher_manager.py -> 'rewritten as Stream base + WatcherSupervisor'). Multi-watcher orchestration becomes WatcherSupervisor spawning multiple watcher Streams.*
- from `pm_core/tui/watcher_ui.py` — **ensure_watcher_plans (create bugs.md/improvements.md + register as plans in meta workdir)**
    - *Bootstrapping side-effect that WatcherSupervisor should perform on startup; touches ProjectYamlArtifact + PlanArtifact in the meta workdir (sensorium/workdirs.py provides the meta workdir).*
- from `pm_core/tui/watcher_ui.py` — **load_watcher_plan_prs (parse bugs.md/improvements.md and append PR entries to project.yaml)**
    - *Same flow as ensure_watcher_plans; consumes plan_parser + ProjectYamlArtifact via supervisor.*
- from `pm_core/tui/watcher_ui.py` — **start_watcher (resolve watcher class, register with WatcherManager, kick off iteration callbacks)**
    - *Replaced by WatcherSupervisor.start(role=..., instance_key=...) which constructs a watcher Stream under pm_core/streams/watchers/. TUI keybinding handler becomes a thin delegator calling Mind.supervis*
- from `pm_core/tui/watcher_ui.py` — **stop_watcher (graceful stop request)**
    - *Becomes WatcherSupervisor.stop(stream_id) / Stream.request_stop; TUI shim only forwards the keypress.*

### `pm_core/tmux.py`

- from `pm_core/qa_status.py` — **Tmux window switching (_switch_to_window, _find_attached_session)**
    - *Grouped-session resolution and select-window are foundational tmux substrate; v2 lists pm_core/tmux.py as staying. If not already there, this logic belongs alongside current_or_base_session. Invocatio*

### `pm_core/tui/auto_start.py`

- from `pm_core/tui/auto_start.py` — **TUI keypress entry points (toggle, auto_sequence_for_pr, set_target) — UI-facing callable surface**
    - *Per v2 'TUI integration shim pattern' — this file STAYS as a thin delegator: keybinding handler calls Mind.supervisor('watcher').start(AutoStartWatcher, target=...). The 575 LOC shrinks to ~30 LOC.*

### `pm_core/tui/pane_registry.py`

- from `pm_core/cli/helpers.py` — **_find_tui_pane**
    - *Searches pane_registry for the TUI pane. v2 keeps pane_registry as foundational substrate; this finder logically belongs there (or on TmuxHostRuntime). Currently in helpers for circularity reasons.*

### `pm_core/tui/pr_view.py`

- from `pm_core/tui/pr_view.py` — **start_pr / review_pr / signoff_pr / merge_pr**
    - *Function names stay in TUI as keybinding entry points (thin delegators per 'TUI integration shim pattern'), but bodies move to Mind.stream(role=ImplStream|ReviewStream|SignoffStream|MergeStream, insta*

### `pm_core/tui/review_loop_ui.py`

- from `pm_core/tui/review_loop_ui.py` — **Verdict icon table (VERDICT_ICONS)**
    - *Pure presentation; review_loop_ui stays as 'thin delegator' per plan's TUI integration shim pattern. Constants like VERDICT_ICONS remain here for log_message rendering.*
- from `pm_core/tui/review_loop_ui.py` — **_ensure_poll_timer / ensure_animation_timer — shared 1Hz timer management**
    - *Per plan TUI shim pattern this thin timer logic stays in the TUI integration file; but coverage of QA/watcher/impl loops should be unified — flagged as cross-cutting.*

### `pm_core/watchdog/tui.py`

- from `pm_core/qa_status.py` — **Live QA dashboard rendering (verdict table, spinner, progress, error block)**
    - *v2 explicitly maps qa_status.py -> watchdog/tui.py + TmuxHostRuntime internals. The rendering loop becomes a TUI WatchdogPolicy that subscribes to ScenarioChannel/PRChannel emissions instead of pollin*
- from `pm_core/qa_status.py` — **Raw termios keyboard input loop (_read_key, _run_interactive)**
    - *Interactive navigation belongs in the TUI watchdog; alternatively absorbed by TmuxHostRuntime internals per v2 deletion note.*
- from `pm_core/qa_status.py` — **ANSI helpers (_truncate, _pad_line, color constants, spinner frames)**
    - *Could also live in a shared pm_core/tui helper, but v2 routes qa_status specifically to watchdog/tui.py.*
- from `pm_core/qa_status.py` — **Terminal size detection (_get_terminal_size)**
    - *Trivial helper; folds into watchdog TUI module.*
- from `pm_core/runtime_state.py` — **refresh_home() kick on transitions**: Home-window refresh is a TUI watchdog reaction to lifecycle emissions; subscribing to LifecycleGlobalChannel replaces th
- from `pm_core/watcher_manager.py` — **list_watchers (status dicts: verdict, iteration, input_required, window_name, display_name)**
    - *Aggregating per-watcher display state for the TUI is the watchdog/TUI policy's job; underlying data comes from StreamRecord + EmissionLog tags (verdict, iteration) and AttentionRequest (input_required*
- from `pm_core/watcher_manager.py` — **is_any_running / any_input_required (aggregate predicates)**
    - *Aggregate predicates over streams; input_required corresponds to outstanding AttentionRequest (pm_core/agent/attention.py).*
- from `pm_core/tui/qa_loop_ui.py` — **poll_qa_state (TUI tick) — spinner/pane idle tracking + completion drain**: Spinner animation wiring against pane idle tracker and consuming completion events becomes a typed WatchdogPolicy reacti
- from `pm_core/tui/qa_loop_ui.py` — **_on_qa_update (TUI log line)**: Subscriber on QA stream Emissions writing to TUI log.
- from `pm_core/tui/review_loop_ui.py` — **_poll_loop_state / _poll_loop_state_inner — multi-loop tick: review, QA, watcher, impl idle, tree refresh, completion announcements**
    - *Becomes a WatchdogPolicy that consumes Manager/Supervisor events instead of polling state objects. The completion announcement / sticky log_message side effect stays in the TUI shim.*
- from `pm_core/tui/watcher_ui.py` — **poll_watcher_state (1Hz poll over WatcherManager state, push notifications on INPUT_REQUIRED / completion / ERROR)**
    - *This is exactly the TUI watchdog policy responsibility; consumes Manager/Supervisor events (or AttentionRequest from agent/attention.py for INPUT_REQUIRED) instead of polling.*

## Stays bucket summary

Files unchanged or with minor call-site updates only:

- pm_core/__init__.py
- pm_core/__main__.py
- pm_core/backend.py
- pm_core/bench/ (entire package)
- pm_core/cli/__init__.py (mostly; pm prompt body updates)
- pm_core/cli/bench.py
- pm_core/cli/fake_github.py
- pm_core/cli/log.py
- pm_core/cli/model.py
- pm_core/cli/project.py
- pm_core/cli/provider.py
- pm_core/cluster/ (entire package)
- pm_core/fake_github.py
- pm_core/gh_ops.py
- pm_core/git_ops.py
- pm_core/graph.py
- pm_core/home_window/__init__.py
- pm_core/home_window/pr_list.py
- pm_core/model_config.py
- pm_core/notes.py (load/save core; some pieces consumed by NotesSectionArtifact + prompts/_shared)
- pm_core/pane_layout.py (path move to tui/pane_layout.py)
- pm_core/pane_registry.py (path move to tui/pane_registry.py)
- pm_core/paths.py (most; pieces move to runtime/fake.py, sensorium/captures.py, collaboration/transport/tmux_socket.py, bootstrap.py)
- pm_core/plans/__init__.py
- pm_core/plans/parser.py
- pm_core/pr_sync.py
- pm_core/providers.py
- pm_core/shell.py
- pm_core/store.py (mostly; locked_edit consumed by ProjectYamlArtifact.edit_interactively)
- pm_core/tmux.py
- pm_core/tui/__init__.py
- pm_core/tui/_shell.py
- pm_core/tui/command_bar.py
- pm_core/tui/frame_capture.py
- pm_core/tui/guide_progress.py (STEP_ORDER import needs update)
- pm_core/tui/perf.py
- pm_core/tui/plans_pane.py
- pm_core/tui/qa_pane.py
- pm_core/tui/screens.py
- pm_core/tui/tech_tree.py (data-source helpers retarget)
- pm_core/tui/tree_layout.py
- pm_core/tui/widgets.py

## Deletes bucket summary

Files removed in the refactor (functionality re-encoded in new structure):

- `pm_core/wrapper.py` — Renamed to pm_core/bootstrap.py (no behavioral change)
    - → pm_core/bootstrap.py
- `pm_core/claude_launcher.py` — Split: launch/CLI-flag/session-registry/binary-discovery → runtime/tmux_host.py; transcript path/session-id helpers → runtime/_claude_jsonl.py; fake-claude pieces → runtime/fake.py; launch_bridge_in_tmux deletes outright
    - → pm_core/runtime/tmux_host.py + pm_core/runtime/_claude_jsonl.py + pm_core/runtime/fake.py
- `pm_core/bridge.py` — Socket protocol deletes outright (no external-process control plane); _invoke_claude semantics absorb into RawApiRuntime; mode-toggle → AttentionService + ControlOwner
    - → RawApiRuntime + Mailbox + AttentionService
- `pm_core/bridge_client.py` — Companion to bridge.py; same split
    - → Mailbox.post + AttentionService
- `pm_core/bug_fix_prompts.py` — Fragments fold into prompts/_shared.py + prompts/impl_system.py + prompts/review_system.py
    - → pm_core/streams/_shared_prompts.py + impl_system.py + review_system.py
- `pm_core/editor.py` — Becomes Artifact.open_in_editor + watch_for_save on Artifact base
    - → pm_core/sensorium/artifact/base.py
- `pm_core/hook_events.py` — Reader-side hook API replaced by EmissionLog + CallbackRegistry
    - → runtime/hook_entry.py + agent/callbacks.py + agent/log.py
- `pm_core/hook_install.py` — Hook installation becomes runtime-internal
    - → runtime/tmux_host.py + runtime/hook_entry.py
- `pm_core/hook_receiver.py` — Replaced by shippable runtime/hook_entry.py CLI
    - → runtime/hook_entry.py
- `pm_core/loop_shared.py` — Replaced by CallbackRegistry + StreamTranscript + Emission tags
    - → agent/callbacks.py + agent/transcript.py + prompts/_shared.py
- `pm_core/pane_idle.py` — Runtime-internal detail folds into TmuxHostRuntime
    - → runtime/tmux_host.py + agent/lifecycle.py
- `pm_core/pr_cleanup.py` — Fans out into Supervisor teardown + runtime cleanup hooks
    - → supervisors/pr_stream.py + runtime/tmux_host.py + runtime/tmux_container.py + sensorium/leases.py
- `pm_core/pr_utils.py` — PRStatus moves to lifecycle.py
    - → pm_core/mind/lifecycle.py
- `pm_core/prompt_gen.py` — Extracted into typed InputType classes per role
    - → pm_core/streams/{impl_system,review_system,signoff,merge,qa_*,watcher/*,plan/*,_shared}.py
- `pm_core/qa_finalize_prompt.py` — Becomes a typed InputType
    - → pm_core/streams/qa_finalize.py
- `pm_core/qa_authoring.py` — Folds into QaAuthorStream
    - → streams/qa_author.py + prompts/qa_authoring.py
- `pm_core/qa_instructions.py` — Replaced by QaLibraryArtifact subclasses
    - → sensorium/artifact/qa_library/{instructions,mocks,regression,artifacts}.py + prompts/_shared.py
- `pm_core/qa_loop.py` — Rewritten as Qa* streams + QaSupervisor (folded into PRStreamSupervisor)
    - → streams/qa_*.py + supervisors/pr_stream.py + sensorium/workdirs.py + sensorium/captures.py
- `pm_core/qa_status.py` — Becomes watchdog/tui.py + TmuxHostRuntime internals
    - → watchdog/tui.py
- `pm_core/regression_prompts.py` — Becomes a typed InputType + shared fragments
    - → prompts/regression/bug_reproduce.py + prompts/_shared.py
- `pm_core/review_loop.py` — Replaced by ReviewStream + LoopMode.kill_restart + StreamPolicy
    - → streams/review.py + agent/{callbacks,emissions,policy,lifecycle}.py
- `pm_core/runtime_state.py` — Folds into EmissionLog + lifecycle.py
    - → agent/log.py + agent/lifecycle.py + supervisors/pr_stream.py + agent/attention.py
- `pm_core/signoff.py` — Becomes SignoffStream + ProjectYamlArtifact verdict record + PRStreamSupervisor auto-sequence
    - → streams/signoff.py + sensorium/artifact/project_yaml.py + supervisors/pr_stream.py
- `pm_core/spec_gen.py` — Splits into SpecArtifact + prompts/spec_gen.py + (proposed) streams/spec_gen.py
    - → sensorium/artifact/spec.py + prompts/spec_gen.py + streams/spec_gen.py
- `pm_core/verdict_transcript.py` — Replaced by pm-owned StreamTranscript + Emission tags
    - → agent/transcript.py + agent/emissions.py
- `pm_core/watcher_base.py` — Replaced by Stream base + WatcherSupervisor
    - → streams/base.py + supervisors/watcher.py + agent/policy.py
- `pm_core/watcher_manager.py` — Replaced by WatcherSupervisor
    - → supervisors/watcher.py + supervisors/protocol.py + watchdog/tui.py
- `pm_core/container.py` — Becomes TmuxContainerRuntime
    - → runtime/tmux_container.py + sensorium/leases.py
- `pm_core/push_proxy.py` — Moves to runtime/ as a sibling daemon
    - → runtime/push_proxy.py
- `pm_core/fake_claude.py` — Becomes FakeClaudeRuntime
    - → runtime/fake.py
- `pm_core/review/__init__.py` — Walker UI primitives become sensorium Artifacts
    - → sensorium/artifact/walker_ui.py
- `pm_core/review/md_parser.py` — Folds into walker_ui artifact reads
    - → sensorium/artifact/walker_ui.py
- `pm_core/review/md_writer.py` — Folds into walker_ui artifact applies
    - → sensorium/artifact/walker_ui.py + sensorium/artifact/base.py + sensorium/artifact/notes.py
- `pm_core/watchers/__init__.py` — Replaced by streams/watchers/__init__.py WATCHER_REGISTRY
    - → streams/watchers/__init__.py
- `pm_core/watchers/auto_start_watcher.py` — Rewritten as AutoStartWatcherStream
    - → streams/watchers/auto_start.py
- `pm_core/watchers/bug_fix_impl_watcher.py` — Rewritten as BugFixImplWatcherStream
    - → streams/watchers/bug_fix_impl.py
- `pm_core/watchers/discovery_supervisor.py` — Rewritten as DiscoverySupervisorStream
    - → streams/watchers/discovery_supervisor.py
- `pm_core/watchers/improvement_fix_impl_watcher.py` — Rewritten as ImprovementFixImplWatcherStream
    - → streams/watchers/improvement_fix_impl.py

## Gaps and proposed additions

Items the workflow surfaced as missing from the proposed structure. All BLOCKING + RECOMMENDED + NICE-TO-HAVE have been incorporated into the plans (see plan-mind, plan-sensorium for details).

- **[RECOMMENDED]** GAP-1: STEP_ORDER home for guide subsystem
    - pm_core/guide.py exports STEP_ORDER/STEP_DESCRIPTIONS/SETUP_STATES consumed by pm_core/tui/guide_progress.py. v2 lists streams/guide/{setup,assist}.py and prompts/guide/ but doesn't say where the step-ordering enum lives.
    - *Rec:* Add STEP_ORDER as a StrEnum classvar on streams/guide/setup.py (GuideSetupStream); re-export from there. Update tui/guide_progress.py to import from the new path.
    - Sources: pm_core/guide.py, pm_core/tui/guide_progress.py
- **[BLOCKING]** GAP-2: Missing prompts/ siblings for three named Streams
    - streams/container_build.py, streams/watchers/discovery_supervisor.py, and streams/merge.py are listed but no paired prompts/{container_build.py, watcher/discovery_supervisor.py, merge.py} are enumerated. prompt_gen.py contains generate_discovery_supervisor_prompt and generate_merge_prompt today, wit
    - *Rec:* Add the three prompt files explicitly to plan-mind under pm_core/prompts/ — they should be implicit but absence creates migration ambiguity.
    - Sources: pm_core/prompt_gen.py, pm_core/cli/container.py
- **[RECOMMENDED]** GAP-3: SpecGenStream missing as a typed Stream subclass
    - prompts/spec_gen.py is listed but no streams/spec_gen.py. spec_gen is a real lifecycle step with its own gen→pending→approve/reject loop and ambiguity-flag detection. It doesn't fit cleanly inside ImplStream or QaPlanningStream — it precedes and gates them.
    - *Rec:* Add pm_core/streams/spec_gen.py (small Stream subclass) under plan-mind, paired with prompts/spec_gen.py. PRStreamSupervisor sequences it as a precondition.
    - Sources: pm_core/spec_gen.py, pm_core/tui/app.py
- **[RECOMMENDED]** GAP-4: External-process TUI IPC has no Mind primitive
    - SIGUSR1 state-reload + SIGUSR2 command-queue file IPC drive cross-process orchestration (popup picker, CLI helpers writing commands to a running TUI). Mailbox/AttentionService are intra-Mind. pm_core/tui/app.py and pm_core/cli/session.py popup-cmd flows depend on this.
    - *Rec:* Either document as a TUI-process-local concern (stays in pm_core/tui/app.py), or add a TUICommandChannel to pm_core/agent/channels.py that rides on the unified Mailbox/Emission substrate via a file-backed Channel sibling.
    - Sources: pm_core/tui/app.py, pm_core/cli/session.py, pm_core/cli/helpers.py
- **[RECOMMENDED]** GAP-5: Verdict-reminder timeout (RemindOnGrace) not in StreamPolicy
    - qa_loop's verdict_reminder_timeout sends a nudge into a pane if no verdict has been emitted within N seconds, then continues waiting. CallbackRegistry.wait_for grace_period only times out; it doesn't auto-remind + reset.
    - *Rec:* Add a RemindOnGrace policy field to StreamPolicy in pm_core/agent/policy.py: on grace expiry, deliver a templated reminder via Stream.deliver_message and reset the timer.
    - Sources: pm_core/qa_loop.py
- **[RECOMMENDED]** GAP-6: Two-phase merge propagation state machine
    - MergeStream + MergeConflictResolverStream are named but the workdir-merge → propagation-only (--propagation-only flag) two-step with distinct INPUT_REQUIRED resolution per phase is not explicit.
    - *Rec:* Document on pm_core/streams/merge.py that MergeStream owns step 1, transitions to a MergePropagationStream (or sub-state) for step 2. Each phase emits its own AttentionRequest on conflict.
    - Sources: pm_core/tui/review_loop_ui.py, pm_core/cli/pr.py
- **[RECOMMENDED]** GAP-7: AttentionRequest cancellation semantics when holding stream dies
    - AttentionService is defined but doesn't specify what happens to an outstanding AttentionRequest when the attending Stream terminates. Watcher_base's 'pane disappeared during INPUT_REQUIRED' becomes orphaned.
    - *Rec:* Add to pm_core/agent/attention.py: AttentionService auto-cancels outstanding requests when the holder's Stream transitions to terminal LifecycleState, emitting an AttentionAbandoned emission.
    - Sources: pm_core/watcher_base.py, pm_core/review_loop.py
- **[RECOMMENDED]** GAP-8: Repeated INPUT_REQUIRED demotion / anti-escalation policy
    - review_loop and watcher_base both have a 'treat repeated INPUT_REQUIRED as READY/NEEDS_WORK' fallback to prevent infinite escalation. Not covered by consecutive_pass_threshold or AttentionService.
    - *Rec:* Add max_consecutive_attention_requests (or repeated_attention_action) field to StreamPolicy in pm_core/agent/policy.py.
    - Sources: pm_core/review_loop.py, pm_core/watcher_base.py
- **[RECOMMENDED]** GAP-9: Per-scenario clone-override workdir (ScenarioWorkdir)
    - WorkdirRegistry + Workdir are named, but qa_loop's per-scenario isolated clone with override file (create_scenario_workdir + _setup_clone_override) is not first-class.
    - *Rec:* Add ScenarioWorkdir as a Workdir subclass in pm_core/sensorium/workdirs.py, or document WorkdirRegistry.create_child(parent, key) as the entry point. Slight preference for explicit ScenarioWorkdir since the clone-override file is QA-specific.
    - Sources: pm_core/qa_loop.py
- **[RECOMMENDED]** GAP-10: Suppress-switch / focus-steal cancellation primitive
    - runtime_state's request_suppress_switch/consume_suppress_switch (popup-picker→window-focus handoff cancellation) has no AttentionService equivalent. The user-dismissed-popup-then-no-focus-steal handshake is unspecified.
    - *Rec:* Model as a short-lived AttentionRequest with ControlOwner=tui_user and TTL in pm_core/agent/attention.py, or as a transient TUI-local artifact. Document in plan-mind.
    - Sources: pm_core/runtime_state.py, pm_core/pane_idle.py, pm_core/tui/qa_loop_ui.py
- **[RECOMMENDED]** GAP-11: Self-driving QA per-PR override flag
    - tui/qa_loop_ui.py uses app._self_driving_qa to drive review→qa transitions even when auto-start is off. Not a policy-level concept; it's a per-PR armable flag set by a TUI gesture.
    - *Rec:* Add per-PR override fields on PRStreamSupervisor (self_driving: bool, stop_before_merge_for_pr: set[int]) that override StreamPolicy on instance.
    - Sources: pm_core/tui/qa_loop_ui.py, pm_core/tui/auto_start.py
- **[NICE-TO-HAVE]** GAP-12: Shared YAML-frontmatter parser
    - QaLibraryArtifact subclasses, PlanArtifact, SpecArtifact, RadarItemArtifact, walker_ui artifacts all need YAML-frontmatter parsing. No shared helper named.
    - *Rec:* Add pm_core/sensorium/artifact/_frontmatter.py (small helper) or put a static method on the Artifact base. Mention in plan-sensorium.
    - Sources: pm_core/qa_instructions.py, pm_core/review/md_parser.py
- **[RECOMMENDED]** GAP-13: Stale tmux window / lease reconciliation on Supervisor startup
    - qa_loop's _cleanup_stale_scenario_windows scans existing windows from a prior loop_id where the Supervisor crashed mid-flight. v2 assumes lease release on Stream shutdown is reliable, but pr_cleanup exists precisely because it fails today.
    - *Rec:* Add a reconcile() method to pm_core/sensorium/leases.py that PRStreamSupervisor.startup invokes to sweep stale leases by ResourceKey prefix matching the supervisor's mind_id. Mention in plan-sensorium.
    - Sources: pm_core/qa_loop.py, pm_core/pr_cleanup.py, pm_core/runtime/tmux_host.py
- **[RECOMMENDED]** GAP-14: Pm-self-reentry contract (hidden CLI flags) survival
    - cli/pr.py uses hidden --background/--transcript/--origin/--propagation-only flags for pm subprocesses re-entering itself. Used by detached launches, supervisor re-invocations. hook_entry.py is for Claude Code hooks specifically.
    - *Rec:* Either fold pm-self-reentry into pm_core/runtime/hook_entry.py as a pm-reentry mode, or add pm_core/runtime/reentry.py. Document explicitly that the bootstrap.py entry handles these modes.
    - Sources: pm_core/cli/pr.py, pm_core/cli/watcher.py
- **[NICE-TO-HAVE]** GAP-15: QaStatusArtifact for signoff evidence pane
    - signoff.py's _evidence_pane_cmd shell-globs ~/.pm/workdirs/qa/<pr>-*/qa_status.json to surface QA status. qa_status.py is deleted (becomes watchdog/tui.py); the cross-stage evidence read has no Artifact-mediated equivalent.
    - *Rec:* Add pm_core/sensorium/artifact/qa_library/status.py (QaStatusArtifact) so SignoffStream's evidence surface reads the artifact rather than globbing workdirs.
    - Sources: pm_core/signoff.py, pm_core/qa_status.py
- **[NICE-TO-HAVE]** GAP-16: EmissionLog inspection CLI surface
    - v2 introduces SQLite EmissionLog with rich structured fields but no CLI surface is named to inspect it. pm log only knows the legacy flat text log.
    - *Rec:* Extend pm_core/cli/log.py with subcommands like `pm log emissions --stream <id> --tag <t>` that query EmissionLog. Mention in plan-mind.
    - Sources: pm_core/cli/log.py
- **[NICE-TO-HAVE]** GAP-17: Merge-restart breadcrumb marker for TUI restart resume
    - auto_start.py + tui/sync.py use a merge-restart marker file to handle 'TUI process needs to restart itself after merge then resume watchers'. No named home in MindSupervisor.
    - *Rec:* Either model as a small RestartCoordinator concept in pm_core/supervisors/mind.py, or delete and rely on EmissionLog replay + WatcherSupervisor reconstitution. Document either way in plan-mind.
    - Sources: pm_core/tui/auto_start.py, pm_core/tui/app.py, pm_core/cli/tui.py
- **[NICE-TO-HAVE]** GAP-18: Discovery prompt for fake-claude / shared claude-JSONL codec
    - FakeClaudeRuntime writes Claude-format JSONL transcripts so hook_entry/TmuxHostRuntime can read them. Pm-owned StreamTranscript is separate. No shared parser/writer for the Claude JSONL format is named — both TmuxHostRuntime (reading) and FakeClaudeRuntime (writing) will duplicate format knowledge.
    - *Rec:* Extract a small pm_core/runtime/_claude_jsonl.py shared between the two runtimes (or as a private helper inside hook_entry.py). Mention in plan-mind.
    - Sources: pm_core/fake_claude.py, pm_core/verdict_transcript.py
- **[NICE-TO-HAVE]** GAP-19: Companion pane as a typed window role
    - cli/pr.py's _add_companion_pane creates a secondary shell pane attached to a PR window. pane_layout/pane_registry stay but companion isn't enumerated as a first-class tui_window_role.
    - *Rec:* Add CompanionPane as a typed role declared by ImplStream (or as a sibling PRActionStream subclass) in pm_core/streams/impl.py, or document as pane_registry-internal.
    - Sources: pm_core/cli/pr.py
- **[RECOMMENDED]** GAP-20: Verdict parser shared utility (loop_shared.match_verdict survival)
    - Boundary-aware verdict-keyword matching (rejecting 'PASS this file' but accepting '**PASS**' alone, with markdown/code tolerance and longest-match-first) is non-trivial parser logic. ALLOWED_VERDICTS on InputType is named but not the matching utility.
    - *Rec:* Add as a method on StreamTranscript (StreamTranscript.latest_verdict(allowed: set[str])) in pm_core/agent/transcript.py, OR as a small helper on InputType base in pm_core/prompts/protocol.py.
    - Sources: pm_core/verdict_transcript.py, pm_core/loop_shared.py
