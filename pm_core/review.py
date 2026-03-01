"""Post-step review logic for pm plan commands."""

import os
import sys
from datetime import datetime
from pathlib import Path

from pm_core import tmux as tmux_mod
from pm_core.claude_launcher import launch_claude_print_background, find_claude


# --- Review prompt templates ---

REVIEW_PROMPTS = {
    "plan-add": (
        'Read the plan file at {path}. Does it have a substantive plan description AND '
        'a "## PRs" section with at least one "### PR:" entry that has description, tests, '
        'files fields? Output PASS if yes, NEEDS_FIX if no, followed by what\'s missing.'
    ),
    "plan-deps": (
        'Run `pm pr list` and `pm pr graph`. Check for: circular dependencies, '
        'PRs with missing deps (B clearly needs A but doesn\'t list it), unnecessary deps. '
        'Output PASS if the graph looks correct, NEEDS_FIX if not, with specifics.'
    ),
    "plan-load": (
        'Run `pm pr list`. Were PRs successfully created? Do they match the ## PRs section '
        'in the plan file at {path}? Output PASS if yes, NEEDS_FIX if not, with specifics.'
    ),
    "plan-import": (
        'Read the plan file at {path}. Does it have a "## PRs" section with at least one '
        '"### PR:" entry that has description, tests, files fields? '
        'Output PASS if yes, NEEDS_FIX if no, followed by what\'s missing.'
    ),
    "plan-review": (
        'Read the plan file at {path} and run `pm pr list`. For each PR linked to this plan, '
        'check: (1) does the PR description contain enough context to work independently, '
        '(2) does the plan mention anything not covered by any PR, '
        '(3) do the file paths in each PR exist or make sense as new files. '
        'Output PASS if consistent, NEEDS_FIX if not, with specifics.'
    ),
}


def _reviews_dir(root: Path) -> Path:
    d = root / "reviews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_verdict(output: str) -> str:
    """Extract PASS or NEEDS_FIX from claude output."""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("PASS"):
            return "PASS"
        if stripped.startswith("NEEDS_FIX"):
            return "NEEDS_FIX"
    # If no clear verdict, assume needs fix if there's output
    return "NEEDS_FIX" if output.strip() else "PASS"


def build_fix_prompt(step_name: str, original_context: str, review_findings: str) -> str:
    """Build a prompt for the -fix variant of a command."""
    return f"""\
Fixing issues from the "{step_name}" review.

This session is managed by `pm`. Run `pm help` to see available commands.

Original context:
{original_context}

Issues found:
{review_findings}

Read the relevant files, fix the issues, and verify. Use `pm` commands for any
state changes (PRs, plans)."""


def _write_review_file(root: Path, step_name: str, status: str, findings: str) -> Path:
    """Write a review file and return its path."""
    reviews = _reviews_dir(root)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    slug = step_name.replace(" ", "-")
    filename = f"{slug}-{ts}.txt"
    path = reviews / filename

    fix_cmd = f"pm plan fix --review {path}"

    content = f"""\
Step: {step_name}
Status: {status}
Timestamp: {datetime.now().isoformat()}

## Review Findings
{findings}

## Fix Command
{fix_cmd}
"""
    path.write_text(content)
    return path


def review_step(step_name: str, goal_description: str, check_prompt: str, root: Path, cwd: str | None = None) -> None:
    """Launch a background review of a completed step.

    Runs claude -p with the check_prompt. If the review finds issues,
    writes a review file. If in tmux, shows result in a background pane.
    """
    claude = find_claude()
    if not claude:
        return

    def _on_complete(stdout: str, stderr: str, returncode: int):
        output = stdout.strip()
        if not output:
            return

        verdict = _parse_verdict(output)
        if verdict == "PASS":
            if tmux_mod.in_tmux():
                try:
                    import subprocess
                    session_name = subprocess.run(
                        tmux_mod._tmux_cmd("display-message", "-p", "#{session_name}"),
                        capture_output=True, text=True,
                    ).stdout.strip()
                    tmux_mod.split_pane_background(
                        session_name, "v",
                        f"echo 'pm review: {step_name} — PASS' && sleep 5"
                    )
                except Exception:
                    pass
            return

        # NEEDS_FIX
        review_path = _write_review_file(root, step_name, "NEEDS_FIX", output)

        if tmux_mod.in_tmux():
            try:
                import subprocess
                session_name = subprocess.run(
                    tmux_mod._tmux_cmd("display-message", "-p", "#{session_name}"),
                    capture_output=True, text=True,
                ).stdout.strip()
                # Show a summary in a background pane
                summary = output[:200].replace("'", "'\\''").replace("\n", " ")
                fix_cmd = f"pm plan fix --review {review_path}"
                pane_cmd = (
                    f"echo 'pm review: {step_name} — NEEDS_FIX' && "
                    f"echo '{summary}' && "
                    f"echo 'Run: {fix_cmd}' && "
                    f"sleep 30"
                )
                tmux_mod.split_pane_background(session_name, "v", pane_cmd)
            except Exception:
                # Fall back to stderr
                print(f"\npm review: {step_name} — NEEDS_FIX", file=sys.stderr)
                print(f"Review file: {review_path}", file=sys.stderr)
        else:
            print(f"\npm review: {step_name} — NEEDS_FIX", file=sys.stderr)
            print(f"Review file: {review_path}", file=sys.stderr)

    launch_claude_print_background(check_prompt, cwd=cwd or str(root), callback=_on_complete)


def list_pending_reviews(root: Path) -> list[dict]:
    """List review files with Status: NEEDS_FIX."""
    reviews_dir = root / "reviews"
    if not reviews_dir.exists():
        return []

    results = []
    for f in sorted(reviews_dir.iterdir()):
        if not f.suffix == ".txt":
            continue
        content = f.read_text()
        if "Status: NEEDS_FIX" in content:
            # Extract fix command
            fix_cmd = ""
            for line in content.splitlines():
                if line.startswith("pm plan"):
                    fix_cmd = line.strip()
                    break
            results.append({
                "path": str(f),
                "filename": f.name,
                "fix_cmd": fix_cmd,
                "content": content,
            })
    return results


def parse_review_file(path: Path) -> dict:
    """Parse a review file into its components."""
    content = path.read_text()
    result = {"step": "", "status": "", "findings": "", "fix_cmd": "", "raw": content}

    for line in content.splitlines():
        if line.startswith("Step: "):
            result["step"] = line[6:].strip()
        elif line.startswith("Status: "):
            result["status"] = line[8:].strip()

    # Extract findings section
    if "## Review Findings" in content:
        parts = content.split("## Review Findings", 1)
        if len(parts) > 1:
            findings_part = parts[1]
            if "## Fix Command" in findings_part:
                findings_part = findings_part.split("## Fix Command")[0]
            result["findings"] = findings_part.strip()

    # Extract fix command
    if "## Fix Command" in content:
        cmd_part = content.split("## Fix Command", 1)[1].strip()
        result["fix_cmd"] = cmd_part.splitlines()[0].strip() if cmd_part else ""

    return result
