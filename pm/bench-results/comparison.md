# Benchmark Comparison: Tournament Selection vs Published pass@1

Cross-source integration verified: all three benchmark loaders (EvalPlus,
LiveCodeBench, BigCodeBench) load without conflict, share the `--source` flag,
and produce identical `Exercise` objects through the orchestrator.

## Published Reference Scores (pass@1 %)

All published scores from Table 16 of the Qwen2.5-Coder Technical Report
(arXiv:2409.12186v3) unless noted.

| Benchmark | Qwen2.5-Coder-7B | Qwen2.5-Coder-32B | DS-Coder-V2-Lite (16B) | GPT-4o |
|---|---|---|---|---|
| HumanEval+ | 84.1 | 87.2 | 75.6 | 86.0 |
| MBPP+ | 71.7 | 75.1 | 70.4 | 72.5 |
| LiveCodeBench (Jul–Nov 2024) | 18.2 | 31.4 | 16.3 | 34.6 |
| BigCodeBench-Instruct Full | 40.4 | 49.6 | 36.8 | 50.1 |
| BigCodeBench-Instruct Hard | 18.2 | 27.0 | 16.2 | 25.0 |

## Local Tournament Results

Results from `pm bench run` with N=8 candidates, tournament selection against
AI-generated tests. "Baseline" is single-pass N=1; "Tournament" is best-of-N
selected by generated-test scoring.

### EvalPlus (HumanEval+ / MBPP+ combined, 542 exercises)

| Config | Baseline pass@1 | Tournament pass@1 | Δ |
|---|---|---|---|
| ~20B local | — | — | — |
| ~120B local | — | — | — |

### LiveCodeBench (1055 exercises, stdin/stdout)

| Config | Baseline pass@1 | Tournament pass@1 | Δ |
|---|---|---|---|
| ~20B local | — | — | — |
| ~120B local | — | — | — |

### BigCodeBench-Instruct Hard (148 exercises)

| Config | Baseline pass@1 | Tournament pass@1 | Δ |
|---|---|---|---|
| ~20B local | — | — | — |
| ~120B local | — | — | — |

## Benchmark Inventory

| Source | Exercises | Language | Difficulty levels | Notes |
|---|---|---|---|---|
| EvalPlus | 542 | Python | — | 164 HumanEval+ and 378 MBPP+ |
| LiveCodeBench | 1055 | Python | easy/medium/hard | AtCoder, LeetCode, Codeforces; stdin/stdout eval |
| BigCodeBench Full | 1140 | Python | — | Instruct and complete prompt modes |
| BigCodeBench Hard | 148 | Python | — | Curated hard subset of the above |

## How to Run

```bash
# Sync exercise caches (first time only)
pm bench exercises --source evalplus
pm bench exercises --source livecodebench
pm bench exercises --source bigcodebench

# Run benchmarks (requires local inference server)
pm bench run <model> -n 8 --source evalplus -o pm/bench-results/evalplus-<model>.json
pm bench run <model> -n 8 --source livecodebench -o pm/bench-results/lcb-<model>.json
pm bench run <model> -n 8 --source bigcodebench --hard -o pm/bench-results/bcb-hard-<model>.json
```

## Key Questions This Answers

**How close does local+tournament get to frontier?** The tournament selection
approach (best-of-N with AI-generated test scoring) aims to close the gap
between small local models (~7B–32B) and frontier models like GPT-4o. The
tables above will be filled in as actual benchmark runs complete, allowing
direct comparison of `~20B tournament` and `~120B tournament` scores against
the published pass@1 numbers.

## Sources

- [Qwen2.5-Coder Technical Report](https://arxiv.org/abs/2409.12186) — Table 16
- [EvalPlus Leaderboard](https://evalplus.github.io/leaderboard.html)
- [LiveCodeBench Leaderboard](https://livecodebench.github.io/leaderboard.html)
- [BigCodeBench Leaderboard](https://bigcode-bench.github.io/)
