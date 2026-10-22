# Evaluating planning through execution

The objective is to improve task results over direct prompting by generating an intermediate plan. This stage follows the [document-only bootstrap](../plans/plan-doc-eval.md), which develops the evaluator and prompt-improvement loop and adopts measured improvements in PM's existing prompts. Execution evaluation then starts with existing benchmark tasks and their supplied prompts/materials. A golden human plan is optional for this stage.

## Starting point

Use the ProgramBench task inputs already targeted by [plan-regression](../plans/plan-regression.md)'s single-prompt capstone (`pr-e2b7fdf`) and exact benchmark adapter (`pr-0cf3626`). [ProgramBench](https://programbench.com/) supplies documentation and a reference executable, with behavioral tests for the submitted implementation. Preserve the benchmark's input and access rules; report the internet-enabled realistic variant separately.

Both PM adapters are still pending. After the document-only bootstrap, the planning comparison can run outside the full PM flow, reusing the benchmark's task inputs and evaluator, then use the same cases to evaluate PM as its adapter lands. The implemented `pm_core/bench` runners and plan-002 datasets can provide inexpensive smoke tests; they do not replace the larger task evaluation.

## Required comparisons

| Arm | Execution |
|---|---|
| Direct | Original task prompt and materials go directly to the coding agent. No separate plan-generation stage; normal reasoning and tools remain available. |
| Current planning | The current planning prompt generates a plan; the coding agent receives the original task plus that plan. |
| Improved planning | A candidate planning prompt generates the plan; the same coding agent executes it. |
| Full PM, later | Run the same tasks through PM's planning, watcher, review and acceptance flow. Compare with direct execution and planning alone to measure the additional effect of orchestration. |

Hold the executor model, task inputs, tools and environment fixed for the planning comparison. Count planning and revision overhead in the total budget and give direct execution the same overall resource allowance. Report actual tokens, cost, wall time and retries alongside quality. Planner and executor backends remain independently configurable, including open/local models; compare each configuration against its own direct baseline.

## Improvement loop

Split tasks by originating project into development, validation and untouched final evaluation sets before optimizing. Generate prompt edits from development outcomes, select on validation, and use the final set only after selection. Reference source code and withheld tests stay outside worker workspaces; task-provided reference executables remain available under the benchmark's rules. The optimizer receives only the feedback allowed for its split.

Score actual task completion with the external evaluator. Also retain per-task partial test success, regressions, failures and resource use; include every launched attempt in the accounting. Repeat paired runs to distinguish prompt effects from sampling variation. Promote on reproducible downstream improvement within the agreed budget; unchanged or worse results remain valid experimental outcomes.

LLM panels and general-purpose classifiers such as Gev and GLiClass can propose edits or predict useful plans. Measure their predictions against execution results before relying on them to save evaluation compute. They do not replace the external evaluator.

The collected public documents retain their known-good label without manual quality curation. They remain useful for writing examples, evaluator diagnostics and human readability, but agreement with a golden plan is neither the training objective nor a prerequisite. Their role can shrink as reliable execution feedback becomes available; code scores alone do not establish readability for human users.

## Additional tasks with implementations and tests

These supplement the existing execution benchmark. Source and test connections have been checked; runnable replay environments have not yet been validated. Pin compatible proposal, implementation and test revisions when packaging each task.

| Source | Code and tests | Useful scope |
|---|---|---|
| [PEP 616](https://peps.python.org/pep-0616/) | [Merged implementation and regression tests](https://github.com/python/cpython/pull/18939/files) | Small string API change; smoke test for the loop. |
| [PEP 680](https://peps.python.org/pep-0680/) | [tomllib implementation](https://github.com/python/cpython/tree/3.11/Lib/tomllib) and [tests and fixtures](https://github.com/python/cpython/tree/3.11/Lib/test/test_tomllib) | Parser integration and API behavior. The original task adopts an existing parser. |
| [Go error inspection](https://github.com/golang/proposal/blob/master/design/29934-error-values.md) | [Implementation](https://github.com/golang/go/blob/master/src/errors/wrap.go) and [tests and benchmarks](https://github.com/golang/go/blob/master/src/errors/wrap_test.go) | Accepted `Is`/`As` functionality; the full original proposal and today's API differ. |
| [Linux Maple Tree proposal](https://lkml.iu.edu/hypermail/linux/kernel/2110.0/03137.html) | [Implementation](https://github.com/torvalds/linux/blob/master/lib/maple_tree.c), [regressions](https://github.com/torvalds/linux/blob/master/lib/test_maple_tree.c), [userspace harness](https://github.com/torvalds/linux/blob/master/tools/testing/radix-tree/maple.c) | Larger data-structure work with a userspace test entry point. |
| [OpenTitan UART design](https://opentitan.org/book/hw/ip/uart/doc/theory_of_operation.html) | [RTL](https://github.com/lowRISC/opentitan/tree/master/hw/ip/uart/rtl), [verification suite](https://opentitan.org/book/hw/ip/uart/dv/index.html), [test plan](https://github.com/lowRISC/opentitan/blob/master/hw/ip/uart/data/uart_testplan.hjson) | Hardware correctness and coverage; verify simulator support first. |
| [OpenROAD documentation](https://openroad.readthedocs.io/en/latest/) | [Implementation and tests](https://github.com/The-OpenROAD-Project/OpenROAD), [test-running guide](https://openroad.readthedocs.io/en/latest/contrib/DeveloperGuide.html) | Tool changes and physical-design outcomes under fixed constraints; design/flow docs rather than historical proposals. |

## Connection to PM evaluation

This extends the document-only experiment within [plan-self-improve](../plans/plan-self-improve.md) to execution outcomes, before the recursive tournament or full PM capstone is required. Reuse the resulting task inputs, prompt versions, execution artifacts and outcome accounting for [plan-delivery](../plans/plan-delivery.md)'s D9 comparisons as the runtime becomes available. The delivery plan's auto-fix, cosmic_ac, Omerta and living-document demonstrations remain separate required evidence of PM's usefulness.
