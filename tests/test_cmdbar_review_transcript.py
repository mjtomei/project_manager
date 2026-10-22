"""A ``pr review`` typed in the command bar gets ``--transcript`` like ``d``.

QA repro (pr-8020495 s35): ``/pr review M`` launched a review pane with no hook
transcript, so the TUI never tracked it and the PR's action history stayed
empty although a review ran.
"""

from types import SimpleNamespace

from pm_core.tui import pr_view


def _app(tmp_path):
    data = {"prs": [{"id": "pr-0000abc", "gh_pr_number": 42}]}
    return SimpleNamespace(_data=data, _root=tmp_path, _auto_start_run_id="run-1")


def _rewrite(app, cmd):
    return pr_view._with_review_transcript(app, cmd, cmd.split())


def test_adds_transcript_for_pr_id(tmp_path):
    out = _rewrite(_app(tmp_path), "pr review pr-0000abc")
    assert out == (f"pr review --transcript {tmp_path}/transcripts/run-1/"
                   "review-pr-0000abc.jsonl pr-0000abc")


def test_display_id_names_transcript_by_canonical_id(tmp_path):
    out = _rewrite(_app(tmp_path), "pr review --fresh 42")
    assert out == (f"pr review --fresh --transcript {tmp_path}/transcripts/"
                   "run-1/review-pr-0000abc.jsonl 42")


def test_leaves_other_forms_alone(tmp_path):
    app = _app(tmp_path)
    for cmd in ("pr review", "pr review pr-nope000",
                "pr review --transcript /x/t.jsonl pr-0000abc",
                "pr review --no-window pr-0000abc"):
        assert _rewrite(app, cmd) == cmd
