"""Auto-start disable must not freeze a running review loop's transcript.

Turning auto-start off (``pm autostart remove`` of the last target, or a
target completing) finalizes the run directory's transcript symlinks so
the transcripts are self-contained.  A review loop that is *still running*
polls its own symlink for the follow-up verdict, so finalizing it strands
the loop: the frozen copy has no verdict turn, the loop reads the next
idle as a new prose question and re-arms the INPUT_REQUIRED wait for a
question nobody was asked (observed in QA scenario 17 story 4 — the
answer's PASS never landed).  The loop finalizes its own transcripts when
it completes, so a running loop's symlink must be left alone.
"""

from unittest.mock import MagicMock

from pm_core.review_loop import ReviewLoopState
from pm_core.tui.auto_start import _finalize_all_transcripts


def _make_app(tmp_path, review_loops):
    app = MagicMock()
    app._root = tmp_path
    app._auto_start_run_id = "run1"
    app._review_loops = review_loops
    return app


def _make_run_dir(tmp_path):
    tdir = tmp_path / "transcripts" / "run1"
    tdir.mkdir(parents=True)
    return tdir


def test_disable_keeps_a_running_review_loops_transcript_live(tmp_path):
    tdir = _make_run_dir(tmp_path)
    live = tmp_path / "live-session.jsonl"
    live.write_text('{"type": "user", "message": {"role": "user", '
                    '"content": "use option A"}}\n')
    link = tdir / "review-pr-001-i1.jsonl"
    link.symlink_to(live)

    app = _make_app(tmp_path, {"pr-001": ReviewLoopState(pr_id="pr-001",
                                                         running=True)})
    _finalize_all_transcripts(app)

    assert link.is_symlink(), "a running loop's transcript was frozen"
    # The loop keeps seeing turns written after the disable.
    with live.open("a") as f:
        f.write('{"type": "assistant", "message": {"role": "assistant", '
                '"content": [{"type": "text", "text": "**PASS**"}]}}\n')
    assert "**PASS**" in link.read_text()


def test_disable_finalizes_a_finished_loops_transcript(tmp_path):
    tdir = _make_run_dir(tmp_path)
    live = tmp_path / "live-session.jsonl"
    live.write_text('{"type": "user", "message": {"role": "user", '
                    '"content": "use option A"}}\n')
    link = tdir / "review-pr-002-i1.jsonl"
    link.symlink_to(live)

    app = _make_app(tmp_path, {"pr-002": ReviewLoopState(pr_id="pr-002",
                                                         running=False)})
    _finalize_all_transcripts(app)

    assert not link.is_symlink(), "a finished loop's transcript was not finalized"
    assert "use option A" in link.read_text()


def test_disable_finalizes_every_transcript_with_no_review_loops(tmp_path):
    tdir = _make_run_dir(tmp_path)
    live = tmp_path / "live-session.jsonl"
    live.write_text("{}\n")
    link = tdir / "review-pr-003-i1.jsonl"
    link.symlink_to(live)

    app = _make_app(tmp_path, {})
    _finalize_all_transcripts(app)

    assert not link.is_symlink()
