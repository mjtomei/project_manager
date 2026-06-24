"""Tests for the all-PR behavior dashboard + the sign-off prompt extension
(pr-8e693f6).

Per-PR ``report.html`` is agent-written. The dashboard is served by a small
localhost HTTP server (``pm pr dashboard``) that rebuilds the index from
``project.yaml`` + the captures dir on every ``/`` request, so liveness is
dynamic and no on-disk index.html exists.
"""

import http.server
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pm_core.behavior_report as br
from pm_core import dashboard_server, signoff


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _data():
    return {
        "prs": [
            {"id": "pr-aaa", "title": "Add thing", "status": "sign_off",
             "gh_pr_number": 42, "description": "desc"},
            {"id": "pr-bbb", "title": "No report PR", "status": "pending"},
            {"id": "pr-ccc", "title": "Merged one", "status": "merged",
             "merged_at": "2026-01-01T00:00:00Z"},
        ],
    }


def _write_report(root: Path, pr_id: str, verdict: str | None) -> Path:
    """Write a minimal report.html with optional verdict meta tag."""
    head_meta = (f'<meta name="pm-signoff-verdict" content="{verdict}">'
                 if verdict else "")
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta charset="utf-8">'
        f'{head_meta}'
        '<title>report</title>'
        '</head><body><h1>report</h1></body></html>'
    )
    pdir = root / pr_id
    pdir.mkdir(parents=True, exist_ok=True)
    out = pdir / "report.html"
    out.write_text(html, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Row gathering
# ---------------------------------------------------------------------------

def test_report_drives_row_with_verdict_from_meta(tmp_path):
    _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.has_report
    assert aaa.report_html_rel == "pr-aaa/report.html"
    assert aaa.verdict == signoff.SIGNOFF_MERGE
    assert aaa.title == "Add thing"
    assert aaa.gh_label == "#42"


def test_missing_report_row_still_appears(tmp_path):
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    bbb = next(r for r in rows if r.pr_id == "pr-bbb")
    assert bbb.has_report is False
    assert bbb.report_html_rel is None
    assert bbb.verdict == ""
    assert bbb.gh_label == ""  # no gh_pr_number


def test_report_without_meta_yields_empty_verdict(tmp_path):
    _write_report(tmp_path, "pr-aaa", verdict=None)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.has_report
    assert aaa.verdict == ""


def test_meta_tag_in_body_ignored(tmp_path):
    """A verbatim verdict keyword (or even a meta) in <body> must NOT match —
    only the <head> meta tag is canonical."""
    pdir = tmp_path / "pr-aaa"
    pdir.mkdir(parents=True)
    (pdir / "report.html").write_text(
        '<!DOCTYPE html><html><head><title>x</title></head>'
        '<body>SIGNOFF_MERGE appears in body text\n'
        '<meta name="pm-signoff-verdict" content="SIGNOFF_MERGE">'
        '</body></html>',
        encoding="utf-8")
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.verdict == ""


def test_verdict_meta_attribute_order_independent(tmp_path):
    """The agent writes report.html, so the verdict meta tag must parse
    regardless of whether ``content`` precedes ``name``."""
    pdir = tmp_path / "pr-aaa"
    pdir.mkdir(parents=True)
    (pdir / "report.html").write_text(
        '<!DOCTYPE html><html><head>'
        '<meta content="SIGNOFF_MERGE" name="pm-signoff-verdict">'
        '<title>x</title></head><body>x</body></html>',
        encoding="utf-8")
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.verdict == signoff.SIGNOFF_MERGE


def test_verdict_found_with_large_inline_body(tmp_path):
    """Reports embed the full diff inline and can run to many MB; the verdict
    tag still lives in <head>. The bounded head read must find it without
    depending on the (huge) body."""
    pdir = tmp_path / "pr-aaa"
    pdir.mkdir(parents=True)
    big_body = "x" * (2 * 1024 * 1024)  # 2 MB, larger than the head read cap
    (pdir / "report.html").write_text(
        '<!DOCTYPE html><html><head>'
        '<meta name="pm-signoff-verdict" content="SIGNOFF_MERGE">'
        f'<title>x</title></head><body>{big_body}</body></html>',
        encoding="utf-8")
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.verdict == signoff.SIGNOFF_MERGE


def test_pr_state_read_from_project_yaml(tmp_path):
    """Title comes from project.yaml — not from anything in the report."""
    _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    data = _data()
    rows = br.gather_dashboard_rows(data, tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.title == "Add thing"


def test_row_carries_report_mtime(tmp_path):
    """The dashboard row picks up the report.html mtime for the last-modified
    column and for default sorting."""
    p = _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    expected = p.stat().st_mtime
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.mtime is not None
    assert abs(aaa.mtime - expected) < 0.001
    # PRs without a report have no mtime.
    bbb = next(r for r in rows if r.pr_id == "pr-bbb")
    assert bbb.mtime is None


def test_rows_default_sort_by_mtime_desc(tmp_path):
    """Default sort: most-recently-modified report first, then by pr_id for
    stable ordering of empty-state rows."""
    import os
    older = _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    newer = _write_report(tmp_path, "pr-ccc", signoff.SIGNOFF_REQA)
    # Force a measurable mtime gap so we don't depend on filesystem granularity.
    os.utime(older, (older.stat().st_atime, newer.stat().st_mtime - 10))
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    # Newer report comes first; then older; then empty-state pr-bbb at the end.
    assert [r.pr_id for r in rows] == ["pr-ccc", "pr-aaa", "pr-bbb"]


# ---------------------------------------------------------------------------
# Dashboard rendering
# ---------------------------------------------------------------------------

def test_dashboard_links_to_agent_written_report(tmp_path):
    _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(rows)
    assert 'href="pr-aaa/report.html"' in h


def test_dashboard_missing_state_shows_no_report_yet(tmp_path):
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(rows)
    assert "no report yet" in h
    # The cell intentionally carries no regenerate command / copy button —
    # the dashboard is read-only chrome, not a launcher.
    assert "pm pr signoff" not in h
    assert "pmCopy" not in h


def test_dashboard_renders_verdict_icon(tmp_path):
    _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(rows)
    assert signoff.SIGNOFF_VERDICT_ICONS[signoff.SIGNOFF_MERGE] in h
    assert "SIGNOFF_MERGE" in h


def test_dashboard_shows_verdict_unknown_when_no_meta(tmp_path):
    _write_report(tmp_path, "pr-aaa", verdict=None)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(rows)
    assert "verdict unknown" in h


def test_dashboard_shows_gh_id_when_present(tmp_path):
    _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(rows)
    assert "pr-aaa" in h
    assert "#42" in h


def test_dashboard_has_last_modified_column(tmp_path):
    """The Last modified column shows a relative time and carries the unix
    mtime as the sort key."""
    p = _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(rows)
    assert "Last modified" in h
    # Relative-time renderings ("Xs/m/h/d ago") for a just-written file.
    assert " ago" in h
    # The cell carries the raw mtime as data-sort so the JS sorter has a
    # numeric key independent of the displayed relative text.
    assert f'data-sort="{round(p.stat().st_mtime)}"' in h


def test_dashboard_filter_input_present(tmp_path):
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(rows)
    assert 'id="q"' in h
    assert "pmFilter()" in h


def test_dashboard_sortable_headers_present(tmp_path):
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(rows)
    # Every header is click-to-sort and the Last modified column starts
    # marked as descending (the default sort).
    assert 'onclick="pmSort(0)"' in h
    assert 'onclick="pmSort(3)"' in h
    assert 'class="sort-desc" onclick="pmSort(3)"' in h
    assert 'data-sort="3-desc"' in h
    # Last modified opts into a DESC default too, so returning to this column
    # after sorting another one still puts the most-recent report first
    # (matches the initial load) rather than oldest-first.
    assert 'data-col="3" data-default-dir="desc"' in h


def test_dashboard_has_status_column(tmp_path):
    """The Status column reuses PR_STATUS_ICONS (single source) and uses a
    lifecycle rank as the sort key so the column sorts in phase order; the
    header carries data-default-dir='desc' so the first click puts sign_off
    at the top."""
    from pm_core.cli.helpers import PR_STATUS_ICONS
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(rows)
    assert ">Status</th>" in h
    # The header opts into a DESC-default so first click surfaces sign_off
    # at the top of the column.
    assert 'data-default-dir="desc" onclick="pmSort(2)">Status' in h
    # _data() seeds sign_off, pending, merged — the icons appear.
    for status in ("sign_off", "pending", "merged"):
        assert PR_STATUS_ICONS[status] in h
    # The cell's data-sort is the rank, not the raw string. sign_off is
    # the highest rank (6) so it lands first under DESC.
    assert f'data-sort="{br._STATUS_RANK["sign_off"]}"' in h
    assert f'data-sort="{br._STATUS_RANK["pending"]}"' in h
    assert f'data-sort="{br._STATUS_RANK["merged"]}"' in h


def test_status_rank_orders_lifecycle():
    """Lifecycle order from terminal to active. First click sorts DESC so
    sign_off is at the top; subsequent click goes ASC for the standard
    closed→merged→…→sign_off reading order."""
    r = br._STATUS_RANK
    assert (r["closed"] < r["merged"] < r["pending"] < r["in_progress"]
            < r["in_review"] < r["qa"] < r["sign_off"])


def test_dashboard_escapes_html_in_title(tmp_path):
    """A PR title with HTML special chars must be escaped so a hostile or
    accidental ``<script>`` in project.yaml can't inject into the page."""
    data = {"prs": [
        {"id": "pr-xss", "title": "<script>alert(1)</script> & <b>bold</b>",
         "status": "pending"},
    ]}
    rows = br.gather_dashboard_rows(data, tmp_path)
    h = br.render_dashboard_html(rows)
    assert "<script>alert(1)</script>" not in h
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in h
    assert "&amp;" in h


# ---------------------------------------------------------------------------
# Sign-off prompt extension
# ---------------------------------------------------------------------------

def test_signoff_prompt_includes_report_deliverable():
    from pm_core import prompt_gen
    p = prompt_gen.generate_signoff_prompt(
        _data(), "pr-aaa", session_name="pm-test")
    # report.html is the deliverable; no JSON sidecar.
    assert "report.html" in p
    assert "report.json" not in p
    # The verdict meta tag is the dashboard's only machine-readable contract.
    assert "pm-signoff-verdict" in p
    # The goal of the report is framed for the agent — external technical
    # reviewer invested in the project but not necessarily familiar with the
    # PR details / surrounding code. Bug + ambiguity sections are framed as
    # entry points for that reviewer.
    assert "external technical reviewer" in p.lower()
    assert "not necessarily familiar" in p.lower()
    assert "entry point" in p.lower()
    assert "implications" in p.lower()
    # Icon/style single source still pointed at so the verdict marker matches
    # the TUI / pm pr list.
    assert "SIGNOFF_VERDICT_ICONS" in p


def test_signoff_prompt_keeps_route_step_numbered_last():
    from pm_core import prompt_gen
    p = prompt_gen.generate_signoff_prompt(
        _data(), "pr-aaa", session_name="pm-test")
    assert "3. **Write the sign-off report" in p
    assert "4. **Route" in p


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _spin_up(pm_root: Path, caps: Path):
    """Start the dashboard server on a free port; return (httpd, base_url)."""
    handler = dashboard_server._make_handler(pm_root, caps)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    # Wait briefly until the listener is actually accepting.
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.02)
    return httpd, f"http://127.0.0.1:{port}"


def _seed_project(tmp_path: Path) -> tuple[Path, Path]:
    pm_root = tmp_path / "pm"
    pm_root.mkdir()
    caps = tmp_path / "captures"
    caps.mkdir()
    from pm_core import store
    store.save(_data(), pm_root)
    return pm_root, caps


def test_server_root_renders_dashboard_dynamically(tmp_path):
    pm_root, caps = _seed_project(tmp_path)
    _write_report(caps, "pr-aaa", signoff.SIGNOFF_MERGE)
    httpd, base = _spin_up(pm_root, caps)
    try:
        body = urllib.request.urlopen(f"{base}/").read().decode()
        assert 'href="pr-aaa/report.html"' in body
        assert signoff.SIGNOFF_VERDICT_ICONS[signoff.SIGNOFF_MERGE] in body
        assert "no report yet" in body  # empty-state cell for pr-bbb
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_server_serves_report_html_from_captures(tmp_path):
    pm_root, caps = _seed_project(tmp_path)
    _write_report(caps, "pr-aaa", signoff.SIGNOFF_MERGE)
    httpd, base = _spin_up(pm_root, caps)
    try:
        body = urllib.request.urlopen(
            f"{base}/pr-aaa/report.html").read().decode()
        assert "pm-signoff-verdict" in body
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_server_picks_up_new_report_without_restart(tmp_path):
    """A report written after the server starts must show up on the next
    request — liveness must be per-request, not cached at startup."""
    pm_root, caps = _seed_project(tmp_path)
    httpd, base = _spin_up(pm_root, caps)
    try:
        body_before = urllib.request.urlopen(f"{base}/").read().decode()
        assert "no report yet" in body_before
        assert 'href="pr-aaa/report.html"' not in body_before
        _write_report(caps, "pr-aaa", signoff.SIGNOFF_MERGE)
        body_after = urllib.request.urlopen(f"{base}/").read().decode()
        assert 'href="pr-aaa/report.html"' in body_after
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_server_404_on_unknown_path(tmp_path):
    pm_root, caps = _seed_project(tmp_path)
    httpd, base = _spin_up(pm_root, caps)
    try:
        try:
            urllib.request.urlopen(f"{base}/does-not-exist")
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_pr_report_command_is_removed():
    import pm_core.cli.pr as pr_cli
    assert not hasattr(pr_cli, "pr_report")


def test_generate_dashboard_static_writer_is_removed():
    """The static-file writer was replaced by the local HTTP server."""
    assert not hasattr(br, "generate_dashboard")


# ---------------------------------------------------------------------------
# Captures-root resolution (paths.captures_root — the dashboard's doc root)
# ---------------------------------------------------------------------------

def test_captures_root_with_explicit_tag(tmp_path, monkeypatch):
    """An explicit session_tag yields ``<sessions>/<tag>/captures`` and
    creates it — this is the doc root ``pm pr dashboard`` serves from."""
    from pm_core import paths
    monkeypatch.setattr(paths, "sessions_dir", lambda: tmp_path)
    root = paths.captures_root(session_tag="mytag")
    assert root == tmp_path / "mytag" / "captures"
    assert root.is_dir()


def test_captures_root_none_when_no_tag(tmp_path, monkeypatch):
    """When no tag can be derived (not in a git repo / no pm session), the
    function returns None rather than synthesising a bogus dir — the CLI
    relies on this to fail clearly."""
    from pm_core import paths
    monkeypatch.setattr(paths, "_resolve_session_tag", lambda *a, **k: None)
    assert paths.captures_root() is None


def test_resolve_session_tag_prefers_pm_session(monkeypatch):
    """Inside a pm tmux session the pm-session tag wins (``pm-`` stripped)
    over the cwd-derived fallback."""
    from pm_core import paths, tmux as tmux_mod
    from pm_core.cli import helpers
    monkeypatch.setattr(tmux_mod, "in_tmux", lambda: True)
    monkeypatch.setattr(helpers, "_get_pm_session", lambda: "pm-proj-abcd1234")
    assert paths._resolve_session_tag() == "proj-abcd1234"
