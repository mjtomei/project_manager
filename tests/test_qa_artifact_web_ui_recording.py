"""Tests for the web-ui-recording QA artifact recipe.

Validates the shipped recipe at pm/qa/artifacts/web-ui-recording.md:
- valid frontmatter and discoverability via the QA artifact-library loader;
- documented commands are well-formed (shell blocks parse with `bash -n`,
  the Node Playwright driver parses with `node --check`);
- the Playwright driver-script skeleton records both video and trace and
  launches Chromium with container-safe flags;
- the recipe captures the HTTP/SSE protocol layer;
- the manifest/files section lists the required artifacts.
"""

import re
import shutil
import subprocess
import tempfile
import os
from pathlib import Path

import pytest

from pm_core.qa_instructions import (
    _parse_frontmatter,
    list_artifacts,
    get_instruction,
    resolve_instruction_ref,
)

# Repo layout: <repo>/tests/this_file and <repo>/pm/qa/artifacts/...
REPO_ROOT = Path(__file__).resolve().parents[1]
PM_ROOT = REPO_ROOT / "pm"
RECIPE_ID = "web-ui-recording"
RECIPE_PATH = PM_ROOT / "qa" / "artifacts" / f"{RECIPE_ID}.md"


@pytest.fixture(scope="module")
def recipe_text() -> str:
    assert RECIPE_PATH.is_file(), f"recipe missing at {RECIPE_PATH}"
    return RECIPE_PATH.read_text()


def _fenced_blocks(text: str) -> list[tuple[str, str]]:
    """Return (lang, code) for every ```-fenced block in *text*.

    The recipe avoids nested triple-backtick fences (inner examples use
    indentation), so a flat fence-toggle scan pairs them correctly.
    """
    blocks: list[tuple[str, str]] = []
    cur: list | None = None
    for line in text.split("\n"):
        m = re.match(r"^```(\w*)\s*$", line)
        if m:
            if cur is None:
                cur = [m.group(1), []]
            else:
                blocks.append((cur[0], "\n".join(cur[1])))
                cur = None
        elif cur is not None:
            cur[1].append(line)
    assert cur is None, "unterminated fenced code block in recipe"
    return blocks


def _driver_block(text: str) -> str:
    js = [code for lang, code in _fenced_blocks(text) if lang in ("javascript", "js")]
    assert len(js) == 1, f"expected exactly one JS driver block, found {len(js)}"
    return js[0]


# ---------------------------------------------------------------------------
# Frontmatter + discoverability
# ---------------------------------------------------------------------------

class TestFrontmatter:
    def test_valid_frontmatter(self, recipe_text):
        meta, body = _parse_frontmatter(recipe_text)
        assert meta.get("title"), "recipe needs a non-empty title"
        assert meta.get("description"), "recipe needs a non-empty description"
        assert body.strip(), "recipe body is empty"


class TestDiscoverability:
    def test_listed_by_loader(self):
        items = list_artifacts(PM_ROOT)
        ids = {it["id"] for it in items}
        assert RECIPE_ID in ids
        entry = next(it for it in items if it["id"] == RECIPE_ID)
        assert entry["title"]
        assert entry["description"]

    def test_get_instruction_artifacts_category(self):
        item = get_instruction(PM_ROOT, RECIPE_ID, category="artifacts")
        assert item is not None
        assert item["body"].strip()

    def test_resolve_ref_bare_stem(self):
        assert resolve_instruction_ref(PM_ROOT, RECIPE_ID) == (
            "artifacts", f"{RECIPE_ID}.md")

    def test_resolve_ref_filename(self):
        assert resolve_instruction_ref(PM_ROOT, f"{RECIPE_ID}.md") == (
            "artifacts", f"{RECIPE_ID}.md")


# ---------------------------------------------------------------------------
# Command well-formedness
# ---------------------------------------------------------------------------

class TestCommandsParse:
    def test_shell_blocks_parse(self, recipe_text):
        if shutil.which("bash") is None:
            pytest.skip("bash not available")
        shell = [c for lang, c in _fenced_blocks(recipe_text)
                 if lang in ("bash", "sh")]
        assert shell, "recipe has no shell blocks"
        for code in shell:
            r = subprocess.run(["bash", "-n"], input=code,
                               capture_output=True, text=True)
            assert r.returncode == 0, f"bash -n failed:\n{r.stderr}\n---\n{code}"

    def test_driver_block_parses(self, recipe_text):
        if shutil.which("node") is None:
            pytest.skip("node not available")
        code = _driver_block(recipe_text)
        # .mjs so `import` is valid (the driver is ESM).
        fd, name = tempfile.mkstemp(suffix=".mjs")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(code)
            r = subprocess.run(["node", "--check", name],
                               capture_output=True, text=True)
            assert r.returncode == 0, f"node --check failed:\n{r.stderr}"
        finally:
            os.unlink(name)


# ---------------------------------------------------------------------------
# Driver-script contract
# ---------------------------------------------------------------------------

class TestDriverContract:
    def test_records_video(self, recipe_text):
        code = _driver_block(recipe_text)
        assert "recordVideo" in code
        assert "recording.webm" in recipe_text

    def test_records_trace(self, recipe_text):
        code = _driver_block(recipe_text)
        assert "tracing.start" in code
        assert "trace.zip" in code

    def test_container_safe_chromium_flags(self, recipe_text):
        code = _driver_block(recipe_text)
        assert "chromium.launch" in code
        assert "--no-sandbox" in code
        assert "--disable-dev-shm-usage" in code

    def test_navigates_and_interacts(self, recipe_text):
        code = _driver_block(recipe_text)
        assert "page.goto" in code
        assert "page.screenshot" in code or "shot(page" in code
        assert "page.keyboard" in code or "click" in code

    def test_dumps_dom(self, recipe_text):
        code = _driver_block(recipe_text)
        assert "page.content()" in code


class TestProtocolCapture:
    def test_captures_http_and_sse(self, recipe_text):
        # Layer 2: curl HTTP snapshots + an SSE (-N) stream transcript.
        assert "http.log" in recipe_text
        assert "sse.log" in recipe_text
        assert "curl" in recipe_text
        assert "-N" in recipe_text  # SSE streaming flag


# ---------------------------------------------------------------------------
# Manifest / files
# ---------------------------------------------------------------------------

class TestManifestArtifacts:
    @pytest.mark.parametrize("artifact", [
        "recording.webm",
        "trace.zip",
        "dom.html",
        "http.log",
        "sse.log",
    ])
    def test_files_section_lists_artifact(self, recipe_text, artifact):
        # The Files section lives after the "## Files" heading.
        files_section = recipe_text.split("## Files", 1)[-1]
        assert artifact in files_section, f"{artifact} missing from Files section"

    def test_mentions_screenshots(self, recipe_text):
        files_section = recipe_text.split("## Files", 1)[-1]
        assert ".png" in files_section
