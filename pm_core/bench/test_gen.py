"""Test generation from problem descriptions.

Given an exercise's problem description and starter code (but NOT the reference
tests), generate test cases using a local model.  The core insight from plan-002:
verification is easier than generation — a model that scores poorly on single-pass
coding can generate useful tests that filter better solutions from multiple
candidates.

Pipeline:
    1. Build prompts (multiple variants for diversity)
    2. Generate at multiple temperatures
    3. Extract code blocks from LLM responses
    4. Validate syntax per language
    5. Deduplicate equivalent tests
    6. Merge into a single test file
"""

from __future__ import annotations

import ast
import hashlib
import re
import textwrap
from dataclasses import dataclass, field
from typing import Callable

from pm_core.bench.runner import GenerationResult

# ---------------------------------------------------------------------------
# Language descriptors
# ---------------------------------------------------------------------------

LANG_TEST_FRAMEWORKS: dict[str, dict] = {
    "python": {
        "framework": "pytest",
        "file_ext": ".py",
        "test_pattern": r"def\s+test_\w+",
        "import_hint": "",
    },
    "javascript": {
        "framework": "Jest",
        "file_ext": ".test.js",
        "test_pattern": r"(?:test|it)\s*\(",
        "import_hint": "const {{ {funcs} }} = require('./{module}');",
    },
    "go": {
        "framework": "testing",
        "file_ext": "_test.go",
        "test_pattern": r"func\s+Test\w+\s*\(",
        "import_hint": 'import "testing"',
    },
    "rust": {
        "framework": "built-in",
        "file_ext": ".rs",
        "test_pattern": r"#\[test\]",
        "import_hint": "",
    },
    "java": {
        "framework": "JUnit",
        "file_ext": ".java",
        "test_pattern": r"@Test",
        "import_hint": "import org.junit.jupiter.api.Test;\nimport static org.junit.jupiter.api.Assertions.*;",
    },
    "cpp": {
        "framework": "Catch2",
        "file_ext": ".cpp",
        "test_pattern": r"TEST_CASE\s*\(",
        "import_hint": '#include "catch2/catch_test_macros.hpp"',
    },
}

SUPPORTED_LANGUAGES = list(LANG_TEST_FRAMEWORKS.keys())

# ---------------------------------------------------------------------------
# Prompt variants
# ---------------------------------------------------------------------------

PROMPT_VARIANTS = {
    "direct": textwrap.dedent("""\
        You are a test engineer. Write comprehensive {framework} tests for the
        following problem.

        ## Problem description
        {description}

        ## Starter code ({language})
        ```{language}
        {starter_code}
        ```

        Write tests that verify correctness. Include tests for:
        - Basic/example cases from the description
        - Edge cases and boundary conditions
        - Error handling if applicable

        Output ONLY the test code in a single ```{language} code block.
        Do not include any explanation outside the code block.
    """),

    "edge_cases": textwrap.dedent("""\
        You are a QA specialist focused on edge cases. Given the problem below,
        write {framework} tests that specifically target:
        - Boundary values (empty inputs, zero, negative, very large)
        - Type edge cases (if applicable)
        - Corner cases mentioned or implied by the description

        ## Problem description
        {description}

        ## Starter code ({language})
        ```{language}
        {starter_code}
        ```

        Output ONLY the test code in a single ```{language} code block.
        Do not include any explanation outside the code block.
    """),

    "examples": textwrap.dedent("""\
        You are a test engineer. The problem description below contains examples.
        Convert each example into a test case, then add a few more tests for
        cases the examples don't cover.

        ## Problem description
        {description}

        ## Starter code ({language})
        ```{language}
        {starter_code}
        ```

        Write {framework} tests. Output ONLY the test code in a single
        ```{language} code block. Do not include any explanation outside the
        code block.
    """),
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class TestBlock:
    """A single generated test block before merging."""
    __test__ = False  # prevent pytest collection
    code: str
    variant: str
    temperature: float
    language: str
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def fingerprint(self) -> str:
        """Content hash for deduplication (ignoring whitespace differences)."""
        normalized = re.sub(r"\s+", " ", self.code.strip())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]


@dataclass
class TestGenResult:
    """Result of test generation for one exercise."""
    __test__ = False  # prevent pytest collection
    merged_tests: str
    language: str
    num_generated: int
    num_valid: int
    num_after_dedup: int
    blocks: list[TestBlock] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_prompt(
    description: str,
    starter_code: str,
    language: str,
    variant: str = "direct",
) -> str:
    """Build a test-generation prompt for the given variant."""
    if variant not in PROMPT_VARIANTS:
        raise ValueError(f"Unknown prompt variant: {variant!r}. Choose from {list(PROMPT_VARIANTS)}")
    if language not in LANG_TEST_FRAMEWORKS:
        raise ValueError(f"Unsupported language: {language!r}. Choose from {SUPPORTED_LANGUAGES}")

    framework = LANG_TEST_FRAMEWORKS[language]["framework"]
    return PROMPT_VARIANTS[variant].format(
        description=description,
        starter_code=starter_code,
        language=language,
        framework=framework,
    )


# ---------------------------------------------------------------------------
# Code extraction from LLM output
# ---------------------------------------------------------------------------

def extract_code(response: str, language: str) -> str:
    """Extract code from a fenced code block in the LLM response.

    Tries language-specific fences first, then generic fences, then falls back
    to the raw response.
    """
    # Try ```language ... ``` first
    lang_aliases = {
        "python": ["python", "py", "python3"],
        "javascript": ["javascript", "js"],
        "go": ["go", "golang"],
        "rust": ["rust", "rs"],
        "java": ["java"],
        "cpp": ["cpp", "c++", "cxx"],
    }
    aliases = lang_aliases.get(language, [language])

    for alias in aliases:
        pattern = rf"```{re.escape(alias)}\s*\n(.*?)```"
        m = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # Try generic ``` ... ```
    pattern = r"```\s*\n(.*?)```"
    m = re.search(pattern, response, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Fall back to raw text (strip any leading prose)
    return response.strip()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _extract_function_names(starter_code: str, language: str) -> list[str]:
    """Extract function/method names from starter code."""
    patterns = {
        "python": r"def\s+(\w+)\s*\(",
        "javascript": r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=)",
        "go": r"func\s+(\w+)\s*\(",
        "rust": r"(?:pub\s+)?fn\s+(\w+)\s*[(<]",
        "java": r"(?:public|private|protected|static|\s)+\w+\s+(\w+)\s*\(",
        "cpp": r"(?:\w+\s+)+(\w+)\s*\(",
    }
    pattern = patterns.get(language)
    if not pattern:
        return []

    matches = re.findall(pattern, starter_code)
    # Some patterns have multiple groups (javascript)
    names = []
    for m in matches:
        if isinstance(m, tuple):
            names.extend(n for n in m if n)
        else:
            names.append(m)

    # Filter out common non-function names
    skip = {"main", "new", "if", "for", "while", "return", "class", "struct", "impl"}
    return [n for n in names if n not in skip]


def validate_tests(code: str, language: str, starter_code: str = "") -> list[str]:
    """Validate generated test code.

    Returns a list of error strings (empty = valid).

    Checks:
    - Not empty
    - Contains at least one test pattern for the language
    - Syntax is valid (for Python, uses ast.parse; others use heuristics)
    - References at least one function from starter code (if provided)
    """
    errors = []

    if not code or not code.strip():
        return ["Empty test code"]

    # Check for test patterns
    lang_info = LANG_TEST_FRAMEWORKS.get(language)
    if lang_info:
        if not re.search(lang_info["test_pattern"], code):
            errors.append(f"No test patterns found (expected {lang_info['framework']} conventions)")

    # Syntax check (Python only — other languages need a compiler)
    if language == "python":
        try:
            ast.parse(code)
        except SyntaxError as e:
            errors.append(f"Python syntax error: {e.msg} (line {e.lineno})")

    # Check function references
    if starter_code:
        func_names = _extract_function_names(starter_code, language)
        if func_names:
            referenced = [name for name in func_names if name in code]
            if not referenced:
                errors.append(
                    f"Tests don't reference any functions from starter code: "
                    f"{func_names}"
                )

    return errors


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _extract_test_names(code: str, language: str) -> list[str]:
    """Extract individual test function/case names from test code."""
    patterns = {
        "python": r"def\s+(test_\w+)",
        "javascript": r"(?:test|it)\s*\(\s*['\"]([^'\"]+)['\"]",
        "go": r"func\s+(Test\w+)",
        "rust": r"fn\s+(test_\w+|it_\w+|\w*test\w*)",
        "java": r"(?:public\s+)?void\s+(\w+Test\w*|\w*test\w+)\s*\(",
        "cpp": r'TEST_CASE\s*\(\s*"([^"]+)"',
    }
    pattern = patterns.get(language)
    if not pattern:
        return []
    return re.findall(pattern, code)


def deduplicate_tests(blocks: list[TestBlock]) -> list[TestBlock]:
    """Remove duplicate test blocks.

    Two blocks are duplicates if:
    - They have the same content fingerprint, OR
    - They have identical sets of test function names
    """
    seen_fingerprints: set[str] = set()
    seen_test_sets: set[frozenset[str]] = set()
    unique: list[TestBlock] = []

    for block in blocks:
        if not block.valid:
            continue

        fp = block.fingerprint
        if fp in seen_fingerprints:
            continue

        test_names = frozenset(_extract_test_names(block.code, block.language))
        if test_names and test_names in seen_test_sets:
            continue

        seen_fingerprints.add(fp)
        if test_names:
            seen_test_sets.add(test_names)
        unique.append(block)

    return unique


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------

def _extract_individual_tests_python(code: str) -> list[str]:
    """Extract individual test functions from Python test code."""
    tree = ast.parse(code)
    tests = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            # Get the source lines for this function
            start = node.lineno - 1
            end = node.end_lineno
            lines = code.splitlines()
            tests.append("\n".join(lines[start:end]))
    return tests


def _collect_imports_python(code: str) -> list[str]:
    """Collect import statements from Python code."""
    tree = ast.parse(code)
    imports = []
    lines = code.splitlines()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            start = node.lineno - 1
            end = node.end_lineno
            imports.append("\n".join(lines[start:end]))
    return imports


def merge_tests(blocks: list[TestBlock], language: str) -> str:
    """Merge multiple test blocks into a single test file.

    For Python: combines imports and individual test functions, deduplicating
    by function name.
    For other languages: concatenates blocks with comment separators.
    """
    if not blocks:
        return ""

    if language == "python":
        return _merge_python_tests(blocks)

    # Generic merge for other languages: concatenate with separators
    parts = []
    for i, block in enumerate(blocks):
        if i > 0:
            parts.append(f"\n// --- generated block {i + 1} ---\n")
        parts.append(block.code)
    return "\n".join(parts)


def _merge_python_tests(blocks: list[TestBlock]) -> str:
    """Merge Python test blocks, deduplicating by test function name."""
    all_imports: list[str] = []
    all_tests: dict[str, str] = {}  # name -> source

    for block in blocks:
        try:
            imports = _collect_imports_python(block.code)
            tests = _extract_individual_tests_python(block.code)
        except SyntaxError:
            # If parsing fails, include the whole block as-is
            all_tests[f"_block_{id(block)}"] = block.code
            continue

        for imp in imports:
            if imp not in all_imports:
                all_imports.append(imp)

        for test_src in tests:
            # Extract function name
            m = re.match(r"def\s+(test_\w+)", test_src)
            if m:
                name = m.group(1)
                if name not in all_tests:
                    all_tests[name] = test_src

    parts = []
    if all_imports:
        parts.append("\n".join(all_imports))
        parts.append("")
    if all_tests:
        parts.append("\n\n".join(all_tests.values()))
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

# Type alias for the generation function (allows mocking in tests)
GenerateFn = Callable[..., GenerationResult]


def generate_tests(
    description: str,
    starter_code: str,
    language: str,
    generate_fn: GenerateFn,
    *,
    model: str = "qwen3:32b",
    temperatures: list[float] | None = None,
    variants: list[str] | None = None,
    base_url: str = "http://localhost:11434",
) -> TestGenResult:
    """Generate a test suite from a problem description.

    Args:
        description: Exercise problem description text.
        starter_code: Starter/template code with function signatures.
        language: Programming language (python, javascript, go, rust, java, cpp).
        generate_fn: Callable matching runner.generate() signature.
        model: Ollama model name.
        temperatures: List of temperatures for diversity (default: [0.2, 0.5, 0.8]).
        variants: Prompt variants to use (default: all three).
        base_url: Ollama API base URL.

    Returns:
        TestGenResult with the merged test suite and metadata.
    """
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language!r}")

    if temperatures is None:
        temperatures = [0.2, 0.5, 0.8]
    if variants is None:
        variants = list(PROMPT_VARIANTS.keys())

    # Generate test blocks: one per (variant, temperature) combination
    blocks: list[TestBlock] = []
    for variant in variants:
        prompt = build_prompt(description, starter_code, language, variant)
        for temp in temperatures:
            result = generate_fn(
                prompt=prompt,
                model=model,
                temperature=temp,
                base_url=base_url,
            )
            code = extract_code(result.text, language)
            errors = validate_tests(code, language, starter_code)
            blocks.append(TestBlock(
                code=code,
                variant=variant,
                temperature=temp,
                language=language,
                errors=errors,
            ))

    valid_blocks = [b for b in blocks if b.valid]
    deduped = deduplicate_tests(valid_blocks)
    merged = merge_tests(deduped, language)

    return TestGenResult(
        merged_tests=merged,
        language=language,
        num_generated=len(blocks),
        num_valid=len(valid_blocks),
        num_after_dedup=len(deduped),
        blocks=blocks,
    )
