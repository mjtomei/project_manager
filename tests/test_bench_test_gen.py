"""Tests for pm_core.bench.test_gen — test generation from problem descriptions."""

from unittest import mock

import pytest

from pm_core.bench.runner import GenerationResult
from pm_core.bench.test_gen import (
    PROMPT_VARIANTS,
    SUPPORTED_LANGUAGES,
    TestBlock,
    build_prompt,
    deduplicate_tests,
    extract_code,
    generate_tests,
    merge_tests,
    validate_tests,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DESCRIPTION = """\
Write a function that checks if a number is prime.

A prime number is a natural number greater than 1 that has no positive divisors
other than 1 and itself.

Examples:
- is_prime(2) -> True
- is_prime(4) -> False
- is_prime(17) -> True
- is_prime(1) -> False
"""

SAMPLE_PYTHON_STARTER = """\
def is_prime(n: int) -> bool:
    pass
"""

SAMPLE_JS_STARTER = """\
function isPrime(n) {
  // your code here
}
module.exports = { isPrime };
"""

SAMPLE_GO_STARTER = """\
package prime

func IsPrime(n int) bool {
    return false
}
"""

SAMPLE_RUST_STARTER = """\
pub fn is_prime(n: u64) -> bool {
    todo!()
}
"""


def _make_result(text: str, temp: float = 0.5) -> GenerationResult:
    """Helper to create a GenerationResult with given text."""
    return GenerationResult(
        text=text,
        model="test-model",
        temperature=temp,
        prompt_tokens=100,
        completion_tokens=200,
        elapsed_s=1.0,
    )


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_direct_variant(self):
        prompt = build_prompt(SAMPLE_DESCRIPTION, SAMPLE_PYTHON_STARTER, "python", "direct")
        assert "is_prime" in prompt
        assert "pytest" in prompt
        assert "Problem description" in prompt

    def test_edge_cases_variant(self):
        prompt = build_prompt(SAMPLE_DESCRIPTION, SAMPLE_PYTHON_STARTER, "python", "edge_cases")
        assert "boundary" in prompt.lower() or "edge" in prompt.lower()

    def test_examples_variant(self):
        prompt = build_prompt(SAMPLE_DESCRIPTION, SAMPLE_PYTHON_STARTER, "python", "examples")
        assert "example" in prompt.lower()

    def test_all_variants_include_description(self):
        for variant in PROMPT_VARIANTS:
            prompt = build_prompt(SAMPLE_DESCRIPTION, SAMPLE_PYTHON_STARTER, "python", variant)
            assert "prime" in prompt

    def test_all_languages_supported(self):
        for lang in SUPPORTED_LANGUAGES:
            prompt = build_prompt("desc", "code", lang, "direct")
            assert len(prompt) > 0

    def test_unknown_variant_raises(self):
        with pytest.raises(ValueError, match="Unknown prompt variant"):
            build_prompt("desc", "code", "python", "nonexistent")

    def test_unknown_language_raises(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            build_prompt("desc", "code", "brainfuck", "direct")

    def test_javascript_uses_jest(self):
        prompt = build_prompt(SAMPLE_DESCRIPTION, SAMPLE_JS_STARTER, "javascript", "direct")
        assert "Jest" in prompt

    def test_go_uses_testing(self):
        prompt = build_prompt(SAMPLE_DESCRIPTION, SAMPLE_GO_STARTER, "go", "direct")
        assert "testing" in prompt


# ---------------------------------------------------------------------------
# extract_code
# ---------------------------------------------------------------------------

class TestExtractCode:
    def test_python_fenced_block(self):
        response = "Here are the tests:\n```python\ndef test_foo():\n    assert True\n```\nDone."
        assert extract_code(response, "python") == "def test_foo():\n    assert True"

    def test_py_alias(self):
        response = "```py\ndef test_foo():\n    pass\n```"
        assert "test_foo" in extract_code(response, "python")

    def test_generic_fence(self):
        response = "```\ndef test_foo():\n    pass\n```"
        assert "test_foo" in extract_code(response, "python")

    def test_no_fence_returns_raw(self):
        response = "def test_foo():\n    assert 1 + 1 == 2"
        assert "test_foo" in extract_code(response, "python")

    def test_javascript_fence(self):
        response = "```javascript\ntest('works', () => { expect(1).toBe(1); });\n```"
        assert "test(" in extract_code(response, "javascript")

    def test_js_alias(self):
        response = "```js\ntest('works', () => {});\n```"
        assert "test(" in extract_code(response, "javascript")

    def test_go_fence(self):
        response = '```go\nfunc TestFoo(t *testing.T) {\n\tt.Log("ok")\n}\n```'
        assert "TestFoo" in extract_code(response, "go")

    def test_rust_fence(self):
        response = "```rust\n#[test]\nfn test_it() { assert!(true); }\n```"
        assert "#[test]" in extract_code(response, "rust")

    def test_picks_first_matching_fence(self):
        response = (
            "Some text\n```python\nfirst_block\n```\nMore text\n"
            "```python\nsecond_block\n```"
        )
        assert extract_code(response, "python") == "first_block"


# ---------------------------------------------------------------------------
# validate_tests
# ---------------------------------------------------------------------------

class TestValidateTests:
    def test_valid_python_tests(self):
        code = "def test_is_prime():\n    assert is_prime(2) is True"
        errors = validate_tests(code, "python", SAMPLE_PYTHON_STARTER)
        assert errors == []

    def test_empty_code(self):
        errors = validate_tests("", "python")
        assert len(errors) == 1
        assert "Empty" in errors[0]

    def test_python_syntax_error(self):
        code = "def test_bad(:\n    pass"
        errors = validate_tests(code, "python")
        assert any("syntax" in e.lower() for e in errors)

    def test_no_test_patterns(self):
        code = "x = 1\ny = 2"
        errors = validate_tests(code, "python")
        assert any("No test patterns" in e for e in errors)

    def test_missing_function_reference(self):
        code = "def test_something():\n    assert True"
        errors = validate_tests(code, "python", SAMPLE_PYTHON_STARTER)
        assert any("don't reference" in e for e in errors)

    def test_function_reference_present(self):
        code = "def test_it():\n    assert is_prime(7)"
        errors = validate_tests(code, "python", SAMPLE_PYTHON_STARTER)
        assert not any("don't reference" in e for e in errors)

    def test_javascript_valid(self):
        code = "test('isPrime returns true for 2', () => { expect(isPrime(2)).toBe(true); });"
        errors = validate_tests(code, "javascript", SAMPLE_JS_STARTER)
        assert errors == []

    def test_go_valid(self):
        code = 'func TestIsPrime(t *testing.T) {\n\tif !IsPrime(2) {\n\t\tt.Error("fail")\n\t}\n}'
        errors = validate_tests(code, "go", SAMPLE_GO_STARTER)
        assert errors == []

    def test_rust_valid(self):
        code = "#[test]\nfn test_is_prime() {\n    assert!(is_prime(2));\n}"
        errors = validate_tests(code, "rust", SAMPLE_RUST_STARTER)
        assert errors == []

    def test_no_starter_code_skips_reference_check(self):
        code = "def test_something():\n    assert True"
        errors = validate_tests(code, "python")
        assert not any("don't reference" in e for e in errors)


# ---------------------------------------------------------------------------
# deduplicate_tests
# ---------------------------------------------------------------------------

class TestDeduplicateTests:
    def test_identical_blocks_deduplicated(self):
        block = TestBlock(code="def test_a():\n    assert True", variant="direct",
                         temperature=0.5, language="python")
        block2 = TestBlock(code="def test_a():\n    assert True", variant="direct",
                          temperature=0.8, language="python")
        result = deduplicate_tests([block, block2])
        assert len(result) == 1

    def test_whitespace_difference_deduplicated(self):
        block1 = TestBlock(code="def test_a():\n    assert True", variant="direct",
                          temperature=0.5, language="python")
        block2 = TestBlock(code="def test_a():\n    assert  True", variant="direct",
                          temperature=0.8, language="python")
        # Whitespace is normalized in fingerprint
        result = deduplicate_tests([block1, block2])
        assert len(result) == 1

    def test_different_blocks_kept(self):
        block1 = TestBlock(code="def test_a():\n    assert True", variant="direct",
                          temperature=0.5, language="python")
        block2 = TestBlock(code="def test_b():\n    assert False", variant="edge_cases",
                          temperature=0.8, language="python")
        result = deduplicate_tests([block1, block2])
        assert len(result) == 2

    def test_same_test_names_deduplicated(self):
        block1 = TestBlock(
            code="def test_prime_2():\n    assert is_prime(2)\n\ndef test_prime_4():\n    assert not is_prime(4)",
            variant="direct", temperature=0.5, language="python",
        )
        block2 = TestBlock(
            code="def test_prime_2():\n    result = is_prime(2)\n    assert result\n\ndef test_prime_4():\n    assert is_prime(4) == False",
            variant="examples", temperature=0.8, language="python",
        )
        result = deduplicate_tests([block1, block2])
        assert len(result) == 1

    def test_invalid_blocks_filtered(self):
        valid = TestBlock(code="def test_a():\n    assert True", variant="direct",
                         temperature=0.5, language="python")
        invalid = TestBlock(code="def test_b():\n    assert True", variant="direct",
                           temperature=0.5, language="python",
                           errors=["syntax error"])
        result = deduplicate_tests([valid, invalid])
        assert len(result) == 1
        assert result[0] is valid

    def test_empty_input(self):
        assert deduplicate_tests([]) == []


# ---------------------------------------------------------------------------
# merge_tests
# ---------------------------------------------------------------------------

class TestMergeTests:
    def test_merge_python_deduplicates_functions(self):
        block1 = TestBlock(
            code="import pytest\n\ndef test_a():\n    assert True",
            variant="direct", temperature=0.5, language="python",
        )
        block2 = TestBlock(
            code="import pytest\n\ndef test_b():\n    assert False",
            variant="edge_cases", temperature=0.8, language="python",
        )
        merged = merge_tests([block1, block2], "python")
        assert "test_a" in merged
        assert "test_b" in merged
        # Import should appear only once
        assert merged.count("import pytest") == 1

    def test_merge_python_same_name_keeps_first(self):
        block1 = TestBlock(
            code="def test_a():\n    assert True",
            variant="direct", temperature=0.5, language="python",
        )
        block2 = TestBlock(
            code="def test_a():\n    assert False",
            variant="edge_cases", temperature=0.8, language="python",
        )
        merged = merge_tests([block1, block2], "python")
        assert "assert True" in merged
        assert "assert False" not in merged

    def test_merge_other_languages_concatenates(self):
        block1 = TestBlock(
            code="test('a', () => { expect(1).toBe(1); });",
            variant="direct", temperature=0.5, language="javascript",
        )
        block2 = TestBlock(
            code="test('b', () => { expect(2).toBe(2); });",
            variant="edge_cases", temperature=0.8, language="javascript",
        )
        merged = merge_tests([block1, block2], "javascript")
        assert "test('a'" in merged
        assert "test('b'" in merged

    def test_merge_empty_returns_empty(self):
        assert merge_tests([], "python") == ""


# ---------------------------------------------------------------------------
# generate_tests (integration with mock runner)
# ---------------------------------------------------------------------------

MOCK_PYTHON_TESTS_DIRECT = """\
Here are the tests:
```python
import pytest


def test_is_prime_basic():
    assert is_prime(2) is True
    assert is_prime(3) is True


def test_is_prime_not_prime():
    assert is_prime(4) is False
    assert is_prime(1) is False
```
"""

MOCK_PYTHON_TESTS_EDGE = """\
```python
def test_is_prime_zero():
    assert is_prime(0) is False


def test_is_prime_negative():
    assert is_prime(-1) is False


def test_is_prime_large():
    assert is_prime(97) is True
```
"""

MOCK_PYTHON_TESTS_EXAMPLES = """\
```python
def test_example_2():
    assert is_prime(2) is True


def test_example_4():
    assert is_prime(4) is False


def test_example_17():
    assert is_prime(17) is True


def test_example_1():
    assert is_prime(1) is False
```
"""


class TestGenerateTests:
    def _mock_generate(self, responses: dict[str, str]):
        """Create a mock generate function that returns different responses
        based on prompt content."""
        call_count = {"n": 0}

        def gen_fn(prompt, model, temperature, base_url):
            call_count["n"] += 1
            # Match by variant keywords in prompt
            for key, text in responses.items():
                if key in prompt.lower():
                    return _make_result(text, temperature)
            # Default
            return _make_result(list(responses.values())[0], temperature)

        return gen_fn

    def test_generates_for_all_variant_temperature_combos(self):
        gen_fn = self._mock_generate({
            "comprehensive": MOCK_PYTHON_TESTS_DIRECT,
            "edge": MOCK_PYTHON_TESTS_EDGE,
            "convert each example": MOCK_PYTHON_TESTS_EXAMPLES,
        })

        result = generate_tests(
            description=SAMPLE_DESCRIPTION,
            starter_code=SAMPLE_PYTHON_STARTER,
            language="python",
            generate_fn=gen_fn,
            temperatures=[0.2, 0.8],
            variants=["direct", "edge_cases"],
        )
        # 2 variants x 2 temperatures = 4 blocks
        assert result.num_generated == 4

    def test_merged_output_is_valid_python(self):
        gen_fn = self._mock_generate({
            "comprehensive": MOCK_PYTHON_TESTS_DIRECT,
            "edge": MOCK_PYTHON_TESTS_EDGE,
            "convert each example": MOCK_PYTHON_TESTS_EXAMPLES,
        })

        result = generate_tests(
            description=SAMPLE_DESCRIPTION,
            starter_code=SAMPLE_PYTHON_STARTER,
            language="python",
            generate_fn=gen_fn,
        )
        # Merged output should be valid Python
        import ast
        ast.parse(result.merged_tests)

    def test_merged_output_contains_tests_from_multiple_variants(self):
        gen_fn = self._mock_generate({
            "comprehensive": MOCK_PYTHON_TESTS_DIRECT,
            "edge": MOCK_PYTHON_TESTS_EDGE,
            "convert each example": MOCK_PYTHON_TESTS_EXAMPLES,
        })

        result = generate_tests(
            description=SAMPLE_DESCRIPTION,
            starter_code=SAMPLE_PYTHON_STARTER,
            language="python",
            generate_fn=gen_fn,
        )
        merged = result.merged_tests
        # Should have tests from direct variant
        assert "test_is_prime_basic" in merged
        # Should have tests from edge_cases variant
        assert "test_is_prime_zero" in merged
        # Should have tests from examples variant
        assert "test_example_17" in merged

    def test_deduplication_reduces_count(self):
        # Same response for all calls → lots of duplicates
        gen_fn = self._mock_generate({"": MOCK_PYTHON_TESTS_DIRECT})

        result = generate_tests(
            description=SAMPLE_DESCRIPTION,
            starter_code=SAMPLE_PYTHON_STARTER,
            language="python",
            generate_fn=gen_fn,
            temperatures=[0.2, 0.5, 0.8],
            variants=["direct", "edge_cases", "examples"],
        )
        # 9 generated, but all identical → deduplicated to 1
        assert result.num_generated == 9
        assert result.num_after_dedup == 1

    def test_invalid_responses_excluded(self):
        def gen_fn(prompt, model, temperature, base_url):
            # Return invalid Python (syntax error)
            return _make_result("```python\ndef test_bad(:\n    pass\n```", temperature)

        result = generate_tests(
            description=SAMPLE_DESCRIPTION,
            starter_code=SAMPLE_PYTHON_STARTER,
            language="python",
            generate_fn=gen_fn,
            temperatures=[0.5],
            variants=["direct"],
        )
        assert result.num_generated == 1
        assert result.num_valid == 0
        assert result.merged_tests == ""

    def test_unsupported_language_raises(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            generate_tests(
                description="desc",
                starter_code="code",
                language="brainfuck",
                generate_fn=lambda **kw: _make_result(""),
            )

    def test_result_metadata(self):
        gen_fn = self._mock_generate({
            "comprehensive": MOCK_PYTHON_TESTS_DIRECT,
            "edge": MOCK_PYTHON_TESTS_EDGE,
            "convert each example": MOCK_PYTHON_TESTS_EXAMPLES,
        })

        result = generate_tests(
            description=SAMPLE_DESCRIPTION,
            starter_code=SAMPLE_PYTHON_STARTER,
            language="python",
            generate_fn=gen_fn,
            temperatures=[0.5],
            variants=["direct"],
        )
        assert result.language == "python"
        assert result.num_generated == 1
        assert len(result.blocks) == 1
        assert result.blocks[0].variant == "direct"
        assert result.blocks[0].temperature == 0.5


# ---------------------------------------------------------------------------
# TestBlock
# ---------------------------------------------------------------------------

class TestTestBlock:
    def test_valid_when_no_errors(self):
        block = TestBlock(code="test", variant="direct", temperature=0.5, language="python")
        assert block.valid is True

    def test_invalid_when_errors(self):
        block = TestBlock(code="test", variant="direct", temperature=0.5,
                         language="python", errors=["bad"])
        assert block.valid is False

    def test_fingerprint_stable(self):
        block = TestBlock(code="def test_a():\n    pass", variant="direct",
                         temperature=0.5, language="python")
        assert block.fingerprint == block.fingerprint

    def test_fingerprint_ignores_whitespace(self):
        block1 = TestBlock(code="def test_a():\n    pass", variant="direct",
                          temperature=0.5, language="python")
        block2 = TestBlock(code="def  test_a():\n    pass", variant="direct",
                          temperature=0.5, language="python")
        assert block1.fingerprint == block2.fingerprint
