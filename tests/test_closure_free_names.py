"""Static audit: catch closures that reference names unbound in any enclosing scope.

Regression for a bug where ``_launch_scenarios_in_containers._concretize_and_launch``
referenced ``scenario_cwd`` (only defined in the tmux-path twin closure), causing
every container-mode scenario to die with ``NameError`` before its session_id was
recorded — so ``_poll_tmux_verdicts`` marked every scenario ``INPUT_REQUIRED``.

pyflakes does not flag this because it treats a name as valid if it exists
*anywhere* at module scope. This audit checks scope resolution per-function
(module globals + lexically enclosing function locals + params + builtins).
"""
from __future__ import annotations

import ast
import builtins
from pathlib import Path

_BUILTINS = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__all__",
    "__builtins__", "__class__", "__package__", "__spec__", "__loader__",
}

# Files this PR rewrote substantially on the hook/session-id path. Scoping the
# audit to these keeps the test fast and focused on the code at risk.
_TARGET_FILES = [
    "pm_core/qa_loop.py",
    "pm_core/review_loop.py",
    "pm_core/watcher_base.py",
    "pm_core/loop_shared.py",
    "pm_core/pane_idle.py",
    "pm_core/hook_install.py",
    "pm_core/hook_events.py",
    "pm_core/hook_receiver.py",
    "pm_core/verdict_transcript.py",
    "pm_core/spec_gen.py",
    "pm_core/claude_launcher.py",
    "pm_core/container.py",
    "pm_core/tui/app.py",
    "pm_core/tui/review_loop_ui.py",
    "pm_core/tui/qa_loop_ui.py",
    "pm_core/tui/tech_tree.py",
    "pm_core/tui/auto_start.py",
]


def _bindings(node: ast.AST) -> set[str]:
    """Names bound in *node*'s own scope, not descending into nested scopes."""
    names: set[str] = set()

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = node.args
        for arg in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
            names.add(arg.arg)
        if a.vararg:
            names.add(a.vararg.arg)
        if a.kwarg:
            names.add(a.kwarg.arg)

    def collect_target(t: ast.AST) -> None:
        if isinstance(t, ast.Name):
            names.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for el in t.elts:
                collect_target(el)
        elif isinstance(t, ast.Starred):
            collect_target(t.value)

    def walk(n: ast.AST) -> None:
        # Nested scopes: record the name but do not descend
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
            return
        if isinstance(n, ast.Lambda):
            return
        if isinstance(n, ast.Assign):
            for t in n.targets:
                collect_target(t)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            collect_target(n.target)
        elif isinstance(n, (ast.For, ast.AsyncFor)):
            collect_target(n.target)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                if item.optional_vars:
                    collect_target(item.optional_vars)
        elif isinstance(n, ast.Import):
            for alias in n.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for alias in n.names:
                names.add(alias.asname or alias.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            for nm in n.names:
                names.add(nm)
        elif isinstance(n, ast.Try):
            for h in n.handlers:
                if h.name:
                    names.add(h.name)
        elif isinstance(n, ast.NamedExpr):
            collect_target(n.target)
        elif isinstance(n, ast.comprehension):
            collect_target(n.target)
        for c in ast.iter_child_nodes(n):
            walk(c)

    body = node.body if hasattr(node, "body") else []
    if isinstance(body, list):
        for s in body:
            walk(s)
    return names


def _check_func(fn: str, fnode: ast.AST, enclosing: set[str],
                problems: list[tuple[str, int, str, str]]) -> None:
    local = _bindings(fnode)
    scope = enclosing | local

    def walk(n: ast.AST) -> None:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            _check_func(fn, n, scope, problems)
            return
        if isinstance(n, ast.ClassDef):
            cscope = scope | {
                m.name for m in n.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _check_func(fn, m, cscope, problems)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if n.id not in scope:
                problems.append((fn, n.lineno, getattr(fnode, "name", "<lambda>"), n.id))
        for c in ast.iter_child_nodes(n):
            walk(c)

    body = fnode.body if isinstance(fnode.body, list) else [fnode.body]
    for s in body:
        walk(s)


def _scan(path: Path) -> list[tuple[str, int, str, str]]:
    src = path.read_text()
    tree = ast.parse(src, str(path))
    module_scope = _bindings(tree) | _BUILTINS
    problems: list[tuple[str, int, str, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_func(str(path), node, module_scope, problems)
        elif isinstance(node, ast.ClassDef):
            cscope = module_scope | {
                m.name for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _check_func(str(path), m, cscope, problems)
    # self/cls are implicitly bound by method descriptors; ignore
    return [(f, ln, fn, nm) for (f, ln, fn, nm) in problems if nm not in ("self", "cls")]


def test_no_unresolved_free_names_in_modified_modules() -> None:
    """Every Name load in the hook/session-id code paths must resolve to a
    binding in its own scope, an enclosing function scope, module globals,
    or builtins. A failure here usually means a nested closure references a
    variable defined only in a *sibling* closure — the exact pattern that
    made container-mode QA silently mark every scenario INPUT_REQUIRED.
    """
    repo_root = Path(__file__).resolve().parent.parent
    all_problems: list[tuple[str, int, str, str]] = []
    for rel in _TARGET_FILES:
        p = repo_root / rel
        if not p.is_file():
            continue
        all_problems.extend(_scan(p))

    assert not all_problems, (
        "Unresolved free names detected (likely a closure using a variable "
        "that is not defined in any enclosing scope):\n"
        + "\n".join(f"  {f}:{ln}  in {fn!r} -> name {nm!r}"
                    for (f, ln, fn, nm) in sorted(all_problems))
    )


def test_container_concretize_uses_container_workdir() -> None:
    """Direct regression for the original bug: the container-path
    ``_concretize_and_launch`` must pass ``container_workdir`` (a local of
    ``_launch_scenarios_in_containers``) into ``_concretize_scenario``, not
    the ``scenario_cwd`` name that only exists in the tmux-path twin.
    """
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "pm_core" / "qa_loop.py").read_text()
    tree = ast.parse(src, "pm_core/qa_loop.py")

    container_fn: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef)
                and node.name == "_launch_scenarios_in_containers"):
            container_fn = node
            break
    assert container_fn is not None, (
        "_launch_scenarios_in_containers not found — test needs updating"
    )

    # Find the nested _concretize_and_launch and confirm its
    # _concretize_scenario call site passes scenario_cwd=container_workdir.
    inner: ast.FunctionDef | None = None
    for node in ast.walk(container_fn):
        if (isinstance(node, ast.FunctionDef)
                and node.name == "_concretize_and_launch"):
            inner = node
            break
    assert inner is not None, (
        "_concretize_and_launch not found inside "
        "_launch_scenarios_in_containers — test needs updating"
    )

    found = False
    for call in ast.walk(inner):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if isinstance(func, ast.Name) and func.id == "_concretize_scenario":
            for kw in call.keywords:
                if kw.arg == "scenario_cwd":
                    assert isinstance(kw.value, ast.Name), (
                        f"scenario_cwd must be a plain Name, got "
                        f"{ast.dump(kw.value)}"
                    )
                    assert kw.value.id == "container_workdir", (
                        f"container-mode _concretize_scenario must receive "
                        f"scenario_cwd=container_workdir; got "
                        f"scenario_cwd={kw.value.id!r} — this is the NameError "
                        f"regression."
                    )
                    found = True
    assert found, (
        "Could not locate _concretize_scenario(scenario_cwd=...) call inside "
        "the container-mode _concretize_and_launch closure"
    )
