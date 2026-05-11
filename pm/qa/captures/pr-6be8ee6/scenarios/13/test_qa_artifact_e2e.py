"""End-to-end QA tests for artifact recipe planner block, ARTIFACT parsing,
and _install_artifact_files (scenario 13)."""

import logging
from pathlib import Path
from unittest.mock import patch

from pm_core.prompt_gen import (
    generate_qa_planner_prompt,
    generate_qa_child_prompt,
)
from pm_core.qa_loop import (
    QAScenario,
    parse_qa_plan,
    _install_artifact_files,
)


def _make_data():
    pr = {
        "id": "pr-001",
        "plan": None,
        "title": "Test PR",
        "branch": "pm/pr-001-test",
        "status": "in_progress",
        "depends_on": [],
        "description": "A test PR",
        "agent_machine": None,
        "gh_pr": None,
        "gh_pr_number": None,
        "workdir": None,
    }
    return {
        "project": {"name": "test", "repo": "/tmp/fake", "base_branch": "master"},
        "plans": [],
        "prs": [pr],
    }


def test_planner_prompt_has_artifact_block():
    data = _make_data()
    with patch("pm_core.prompt_gen.store.find_project_root",
               return_value=Path("/workspace/pm")):
        prompt = generate_qa_planner_prompt(data, "pr-001")
    assert "Artifact Recipes" in prompt
    assert "ARTIFACT:" in prompt


def test_planner_prompt_omits_artifact_block_when_empty(tmp_path):
    # Make a fake pm root with only instructions/, no artifacts/.
    pm_root = tmp_path / "pm"
    instr_dir = pm_root / "qa" / "instructions"
    instr_dir.mkdir(parents=True)
    (instr_dir / "dummy.md").write_text(
        "---\ntitle: dummy\ndescription: a dummy\n---\nhi\n"
    )

    data = _make_data()
    with patch("pm_core.prompt_gen.store.find_project_root",
               return_value=pm_root):
        prompt = generate_qa_planner_prompt(data, "pr-001")
    assert "Artifact Recipes" not in prompt
    # The SCENARIO-template ARTIFACT line should be omitted too.
    assert "ARTIFACT:" not in prompt


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_parse_qa_plan_artifact_field():
    plan_text = """\
QA_PLAN_START

SCENARIO 1: Real combo
FOCUS: f1
ARTIFACT: tmux-screen-recording.md, cli-recording.md
STEPS:
do stuff

SCENARIO 2: With bogus
FOCUS: f2
ARTIFACT: tmux-screen-recording.md, bogus-recipe.md
STEPS:
do stuff

SCENARIO 3: Cross-category
FOCUS: f3
ARTIFACT: tui-manual-test.md
STEPS:
do stuff

SCENARIO 4: None case
FOCUS: f4
ARTIFACT: none
STEPS:
do stuff

QA_PLAN_END
"""
    handler = _ListHandler()
    handler.setLevel(logging.WARNING)
    qa_logger = logging.getLogger("pm.qa_loop")
    qa_logger.addHandler(handler)
    try:
        scenarios = parse_qa_plan(plan_text, pm_root=Path("/workspace/pm"))
    finally:
        qa_logger.removeHandler(handler)

    assert len(scenarios) == 4
    assert scenarios[0].artifact_paths == [
        "artifacts/tmux-screen-recording.md",
        "artifacts/cli-recording.md",
    ]
    assert scenarios[1].artifact_paths == ["artifacts/tmux-screen-recording.md"]
    assert scenarios[2].artifact_paths == []
    assert scenarios[3].artifact_paths == []

    all_warnings = " ".join(r.getMessage() for r in handler.records)
    assert "bogus-recipe.md" in all_warnings
    assert "tui-manual-test.md" in all_warnings


def test_install_artifact_files_copies_and_rewrites(tmp_path):
    scenario = QAScenario(
        index=1,
        title="t",
        focus="f",
        artifact_paths=[
            "artifacts/tmux-screen-recording.md",
            "artifacts/cli-recording.md",
        ],
    )
    _install_artifact_files(
        Path("/workspace/pm"), scenario,
        scratch_path=tmp_path, scratch_dir="/agent-scratch",
    )
    assert (tmp_path / "qa-artifacts" / "tmux-screen-recording.md").is_file()
    assert (tmp_path / "qa-artifacts" / "cli-recording.md").is_file()
    assert scenario.artifact_paths == [
        "/agent-scratch/qa-artifacts/tmux-screen-recording.md",
        "/agent-scratch/qa-artifacts/cli-recording.md",
    ]


def test_child_prompt_renders_artifact_section(tmp_path):
    scenario = QAScenario(
        index=1,
        title="t",
        focus="f",
        artifact_paths=[
            "artifacts/tmux-screen-recording.md",
            "artifacts/cli-recording.md",
        ],
        steps="do stuff",
    )
    _install_artifact_files(
        Path("/workspace/pm"), scenario,
        scratch_path=tmp_path, scratch_dir="/agent-scratch",
    )
    data = _make_data()
    prompt = generate_qa_child_prompt(
        data, "pr-001", scenario,
        workdir="/tmp/workdir", scratch_dir="/agent-scratch",
    )
    assert "## Artifact Capture Recipes" in prompt
    assert "- `/agent-scratch/qa-artifacts/tmux-screen-recording.md`" in prompt
    assert "- `/agent-scratch/qa-artifacts/cli-recording.md`" in prompt
    assert "pm/qa/captures/pr-001/scenarios/1/" in prompt
    assert "git add pm/qa/captures/pr-001/scenarios/1/" in prompt
    assert 'git commit -m "qa: capture for scenario 1"' in prompt
    assert "git push origin pm/pr-001-test" in prompt
    assert "git pull --rebase" in prompt
    assert "git push origin pm/pr-001-test" in prompt
    # The rebase-on-conflict line wraps a newline between --rebase and origin.
    assert "git pull --rebase\norigin pm/pr-001-test" in prompt
