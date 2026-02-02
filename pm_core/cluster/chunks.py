"""Code chunk extraction from repository files."""

import ast
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Chunk:
    id: str                        # "src/auth.py::LoginHandler" or "src/auth.py"
    kind: str                      # "function" | "class" | "file" | "directory"
    path: Path                     # relative to repo root
    name: str
    start_line: int | None = None
    end_line: int | None = None
    tokens: set[str] = field(default_factory=set)
    imports: set[str] = field(default_factory=set)
    calls: set[str] = field(default_factory=set)
    children: list[str] = field(default_factory=list)


_TOKEN_RE = re.compile(r'[a-zA-Z_]\w{2,}')
_MAX_FILE_SIZE = 500 * 1024  # 500KB


def _git_ls_files(repo_root: Path) -> list[str]:
    """Get tracked files via git ls-files, falling back to walk."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root, capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().split('\n') if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    # Fallback: walk directory
    files = []
    for p in repo_root.rglob('*'):
        if p.is_file() and '.git' not in p.parts:
            files.append(str(p.relative_to(repo_root)))
    return files


def _is_binary(path: Path) -> bool:
    """Quick binary check via null bytes in first 8KB."""
    try:
        with open(path, 'rb') as f:
            return b'\x00' in f.read(8192)
    except OSError:
        return True


def _extract_python_chunks(rel_path: str, full_path: Path) -> list[Chunk]:
    """Parse a Python file into function/class/file chunks."""
    try:
        source = full_path.read_text(errors='replace')
        tree = ast.parse(source, filename=str(rel_path))
    except (SyntaxError, ValueError):
        return _extract_generic_chunk(rel_path, full_path)

    file_tokens: set[str] = set()
    file_imports: set[str] = set()
    file_calls: set[str] = set()
    children: list[str] = []
    chunks: list[Chunk] = []

    # Collect file-level imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                file_imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                file_imports.add(node.module)
            for alias in node.names:
                file_imports.add(alias.name)

    # Extract top-level functions and classes
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            chunk_id = f"{rel_path}::{node.name}"
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            tokens = set()
            calls = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    tokens.add(child.id)
                elif isinstance(child, ast.Constant) and isinstance(child.value, str) and len(child.value) >= 3:
                    tokens.add(child.value)
                elif isinstance(child, ast.Call):
                    call_name = _extract_call_name(child)
                    if call_name:
                        calls.add(call_name)

            end_line = getattr(node, 'end_lineno', None) or node.lineno
            chunk = Chunk(
                id=chunk_id, kind=kind, path=Path(rel_path), name=node.name,
                start_line=node.lineno, end_line=end_line,
                tokens=tokens, imports=file_imports.copy(), calls=calls,
            )
            chunks.append(chunk)
            children.append(chunk_id)
            file_tokens.update(tokens)
            file_calls.update(calls)

    # File-level tokens from top-level code
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    file_tokens.add(child.id)

    file_chunk = Chunk(
        id=rel_path, kind="file", path=Path(rel_path), name=Path(rel_path).name,
        tokens=file_tokens, imports=file_imports, calls=file_calls,
        children=children,
    )
    chunks.insert(0, file_chunk)
    return chunks


def _extract_call_name(node: ast.Call) -> str | None:
    """Extract the function/method name from a Call node."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _extract_generic_chunk(rel_path: str, full_path: Path) -> list[Chunk]:
    """Regex tokenization for non-Python files."""
    try:
        text = full_path.read_text(errors='replace')
    except OSError:
        return []
    tokens = set(_TOKEN_RE.findall(text))
    return [Chunk(
        id=rel_path, kind="file", path=Path(rel_path), name=Path(rel_path).name,
        tokens=tokens,
    )]


def _matches_patterns(path: str, patterns: list[str] | None) -> bool:
    """Check if path matches any of the glob-style patterns."""
    if patterns is None:
        return True
    from fnmatch import fnmatch
    return any(fnmatch(path, p) for p in patterns)


def extract_chunks(repo_root: Path,
                   include: list[str] | None = None,
                   exclude: list[str] | None = None) -> list[Chunk]:
    """Extract code chunks from a repository.

    Args:
        repo_root: Path to the repository root.
        include: Optional glob patterns to include (e.g. ["*.py", "src/**"]).
        exclude: Optional glob patterns to exclude.

    Returns:
        List of Chunk objects representing code units.
    """
    files = _git_ls_files(repo_root)
    chunks: list[Chunk] = []
    dir_children: dict[str, list[str]] = {}

    for rel_path in files:
        if include and not _matches_patterns(rel_path, include):
            continue
        if exclude and _matches_patterns(rel_path, exclude):
            continue

        full_path = repo_root / rel_path
        if not full_path.is_file():
            continue
        if full_path.stat().st_size > _MAX_FILE_SIZE:
            continue
        if _is_binary(full_path):
            continue

        if rel_path.endswith('.py'):
            file_chunks = _extract_python_chunks(rel_path, full_path)
        else:
            file_chunks = _extract_generic_chunk(rel_path, full_path)

        chunks.extend(file_chunks)

        # Track directory membership
        dir_path = str(Path(rel_path).parent)
        if dir_path == '.':
            dir_path = ''
        if dir_path not in dir_children:
            dir_children[dir_path] = []
        dir_children[dir_path].append(rel_path)

    # Create directory-level chunks
    for dir_path, child_files in dir_children.items():
        if not dir_path:
            continue
        dir_tokens: set[str] = set()
        for c in chunks:
            if c.kind == "file" and str(c.path.parent) == dir_path:
                dir_tokens.update(c.tokens)
        chunks.append(Chunk(
            id=dir_path + "/",
            kind="directory",
            path=Path(dir_path),
            name=Path(dir_path).name,
            tokens=dir_tokens,
            children=child_files,
        ))

    return chunks
