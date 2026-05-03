"""Tests for ``pm rc`` server, CLI guard, and registry behaviors."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from pm_core.rc.server import create_app  # noqa: E402


# ---------------------------------------------------------------------------
# Server endpoint tests (using TestClient)
# ---------------------------------------------------------------------------

@pytest.fixture
def doc(tmp_path: Path) -> Path:
    p = tmp_path / "doc.md"
    p.write_text("alpha\nbravo\ncharlie\ndelta\necho\nfoxtrot\n")
    return p


@pytest.fixture
def client(doc: Path) -> TestClient:
    # watch_interval=0 disables the polling thread; tests that exercise
    # the watcher drive State.check_disk() directly.
    return TestClient(create_app(doc, watch_interval=0))


def test_doc_initial_snapshot(client: TestClient, doc: Path):
    r = client.get("/api/doc")
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == str(doc.resolve())
    assert data["text"] == doc.read_text()
    assert data["version"] == 0
    assert data["selection"] is None
    assert data["proposal"] is None


def test_select_sets_selection_and_autofocus(client: TestClient):
    r = client.post("/api/select", json={"start": 4, "end": 5})
    assert r.status_code == 200
    s = client.get("/api/doc").json()
    assert s["selection"] == {"start": 4, "end": 5}
    # auto-focus: top = max(1, start - 3) = 1
    assert s["viewport"]["top"] == 1


def test_select_autofocus_clamps_to_one(client: TestClient):
    client.post("/api/select", json={"start": 1, "end": 2})
    s = client.get("/api/doc").json()
    assert s["viewport"]["top"] == 1


def test_select_out_of_range_400(client: TestClient):
    r = client.post("/api/select", json={"start": 0, "end": 1})
    assert r.status_code == 400
    r = client.post("/api/select", json={"start": 3, "end": 2})
    assert r.status_code == 400
    r = client.post("/api/select", json={"start": 1, "end": 999})
    assert r.status_code == 400


def test_focus_sets_top_without_changing_selection(client: TestClient):
    client.post("/api/select", json={"start": 4, "end": 5})
    r = client.post("/api/focus", json={"top_line": 2})
    assert r.status_code == 200
    assert r.json()["viewport"]["top"] == 2
    s = client.get("/api/doc").json()
    assert s["selection"] == {"start": 4, "end": 5}
    assert s["viewport"]["top"] == 2


def test_propose_requires_selection(client: TestClient):
    r = client.post("/api/propose", json={"text": "x"})
    assert r.status_code == 400


def test_propose_then_status(client: TestClient):
    client.post("/api/select", json={"start": 2, "end": 2})
    r = client.post("/api/propose", json={"text": "BRAVO"})
    assert r.status_code == 200
    s = client.get("/api/doc").json()
    assert s["proposal"] == {"text": "BRAVO"}


def test_accept_writes_file_and_clears_state(client: TestClient, doc: Path):
    client.post("/api/select", json={"start": 2, "end": 3})
    client.post("/api/propose", json={"text": "BRAVO\nCHARLIE"})
    r = client.post("/api/accept")
    assert r.status_code == 200
    assert r.json()["version"] == 1
    text = doc.read_text()
    assert text == "alpha\nBRAVO\nCHARLIE\ndelta\necho\nfoxtrot\n"
    s = client.get("/api/doc").json()
    assert s["selection"] is None
    assert s["proposal"] is None
    assert s["version"] == 1


def test_accept_handles_single_line_replacement(client: TestClient, doc: Path):
    client.post("/api/select", json={"start": 1, "end": 1})
    client.post("/api/propose", json={"text": "ALPHA"})
    client.post("/api/accept")
    assert doc.read_text().splitlines()[0] == "ALPHA"


def test_accept_proposal_with_trailing_newline(client: TestClient, doc: Path):
    client.post("/api/select", json={"start": 2, "end": 2})
    client.post("/api/propose", json={"text": "BRAVO\n"})
    client.post("/api/accept")
    assert doc.read_text() == "alpha\nBRAVO\ncharlie\ndelta\necho\nfoxtrot\n"


def test_reject_clears_proposal_preserves_selection(client: TestClient):
    client.post("/api/select", json={"start": 2, "end": 2})
    client.post("/api/propose", json={"text": "X"})
    r = client.post("/api/reject")
    assert r.status_code == 200
    s = client.get("/api/doc").json()
    assert s["proposal"] is None
    assert s["selection"] == {"start": 2, "end": 2}


def test_viewport_post_updates_state(client: TestClient):
    r = client.post("/api/viewport", json={"top": 4, "bottom": 12})
    assert r.status_code == 200
    s = client.get("/api/doc").json()
    assert s["viewport"] == {"top": 4, "bottom": 12}


def test_root_returns_html(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower()


# ---------------------------------------------------------------------------
# SSE delivery
# ---------------------------------------------------------------------------

def _parse_first_event(body: bytes) -> dict:
    """Parse the first complete SSE event out of a partial stream."""
    text = body.decode()
    # Skip initial state frame, find next event terminator
    blocks = text.split("\n\n")
    parsed = []
    for block in blocks:
        if not block.strip():
            continue
        ev = "message"
        data_lines = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        if data_lines:
            parsed.append({"event": ev, "data": json.loads("\n".join(data_lines))})
    return parsed


def test_sse_broadcasts_state_on_mutation(doc: Path):
    """Direct unit test of the broadcast plumbing (avoids HTTP streaming
    in TestClient, which doesn't return until the response body is fully
    consumed)."""
    from pm_core.rc.server import State
    state = State(path=doc)
    import queue
    q = queue.Queue(maxsize=10)
    state.subscribers.append(q)
    state.broadcast("state", {"hello": "world"})
    ev, payload = q.get_nowait()
    assert ev == "state"
    assert payload == {"hello": "world"}


def test_sse_drops_slow_subscribers(doc: Path):
    from pm_core.rc.server import State
    import queue
    state = State(path=doc)
    q = queue.Queue(maxsize=1)
    state.subscribers.append(q)
    state.broadcast("state", {"a": 1})  # fills queue
    state.broadcast("state", {"a": 2})  # would block — should drop
    assert q not in state.subscribers


def test_external_modification_bumps_version_and_broadcasts(doc: Path):
    """File touched externally should bump version and emit state+doc."""
    from pm_core.rc.server import State
    import queue
    state = State(path=doc.resolve())
    state.remember_disk_state()
    initial_version = state.version

    q: queue.Queue = queue.Queue(maxsize=10)
    state.subscribers.append(q)

    # Simulate an external editor save with new content + bumped mtime.
    new_text = "alpha\nbravo\nCHARLIE-EDITED\ndelta\necho\nfoxtrot\n"
    doc.write_text(new_text)
    # write_text may produce same mtime_ns on fast filesystems; force.
    import os
    st = doc.stat()
    os.utime(doc, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    changed, snap, docsnap = state.check_disk()
    assert changed
    assert snap["version"] == initial_version + 1
    assert snap["missing"] is False
    assert docsnap is not None
    assert docsnap["text"] == new_text


def test_external_deletion_emits_missing_state(doc: Path):
    from pm_core.rc.server import State
    state = State(path=doc.resolve())
    state.remember_disk_state()

    doc.unlink()
    changed, snap, docsnap = state.check_disk()
    assert changed
    assert snap["missing"] is True
    assert docsnap is None

    # Subsequent check with no further change is a no-op
    changed2, _, _ = state.check_disk()
    assert not changed2


def test_doc_endpoint_when_missing_does_not_500(doc: Path):
    from fastapi.testclient import TestClient
    from pm_core.rc.server import create_app, State

    app = create_app(doc, watch_interval=0)
    state: State = app.state.rc
    doc.unlink()
    state.check_disk()

    c = TestClient(app)
    r = c.get("/api/doc")
    assert r.status_code == 200
    body = r.json()
    assert body["missing"] is True
    assert body["text"] == ""


def test_accept_does_not_trigger_watcher(doc: Path):
    """Our own writes via /api/accept should not be re-broadcast as
    external modifications — remember_disk_state must capture the new
    signature inside the accept handler."""
    from fastapi.testclient import TestClient
    from pm_core.rc.server import create_app, State

    app = create_app(doc, watch_interval=0)
    state: State = app.state.rc
    c = TestClient(app)

    c.post("/api/select", json={"start": 2, "end": 2})
    c.post("/api/propose", json={"text": "BRAVO"})
    c.post("/api/accept")

    # Now polling the disk should report no further change.
    changed, _, _ = state.check_disk()
    assert changed is False


def test_viewport_last_write_wins(client: TestClient):
    client.post("/api/viewport", json={"top": 1, "bottom": 5})
    client.post("/api/viewport", json={"top": 10, "bottom": 20})
    s = client.get("/api/doc").json()
    assert s["viewport"] == {"top": 10, "bottom": 20}


# ---------------------------------------------------------------------------
# CLI guard tests
# ---------------------------------------------------------------------------

def test_pm_rc_start_outside_pm_session_errors(tmp_path: Path):
    from click.testing import CliRunner
    from pm_core.cli import cli

    f = tmp_path / "foo.md"
    f.write_text("hi\n")
    runner = CliRunner()
    with mock.patch("pm_core.cli.rc._get_current_pm_session", return_value=None):
        result = runner.invoke(cli, ["rc", "start", str(f)])
    assert result.exit_code == 1
    assert "pm session" in result.output


def test_pm_rc_start_port_in_use_errors(tmp_path: Path):
    from click.testing import CliRunner
    from pm_core.cli import cli

    f = tmp_path / "foo.md"
    f.write_text("hi\n")

    # Bind a real socket to occupy a port
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    busy_port = s.getsockname()[1]

    runner = CliRunner()
    try:
        with mock.patch("pm_core.cli.rc._get_current_pm_session",
                        return_value="pm-test"):
            result = runner.invoke(
                cli, ["rc", "start", str(f), "--port", str(busy_port)]
            )
    finally:
        s.close()
    assert result.exit_code == 1
    assert "in use" in result.output


def test_pm_rc_subcommand_outside_session_errors(tmp_path: Path):
    from click.testing import CliRunner
    from pm_core.cli import cli

    runner = CliRunner()
    with mock.patch("pm_core.cli.rc._get_current_pm_session", return_value=None):
        result = runner.invoke(cli, ["rc", "select", "1"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def test_save_and_load_rc_server(tmp_path: Path, monkeypatch):
    from pm_core import pane_registry as reg
    from pm_core.cli import rc as rc_mod

    monkeypatch.setattr(reg, "registry_dir", lambda: tmp_path)

    info = {"pid": 4242, "port": 9000, "host": "0.0.0.0",
            "lan_ip": "10.0.0.1", "path": "/tmp/x", "log": "/tmp/x.log"}
    rc_mod._save_rc_server("pm-test", "@7", info)

    loaded = rc_mod._load_rc_server("pm-test", "@7")
    assert loaded == info


def test_drop_rc_server(tmp_path: Path, monkeypatch):
    from pm_core import pane_registry as reg
    from pm_core.cli import rc as rc_mod

    monkeypatch.setattr(reg, "registry_dir", lambda: tmp_path)

    rc_mod._save_rc_server("pm-test", "@7", {"pid": 1, "port": 9000})
    out = rc_mod._drop_rc_server("pm-test", "@7")
    assert out == {"pid": 1, "port": 9000}
    assert rc_mod._load_rc_server("pm-test", "@7") is None


def test_cleanup_kills_server_when_no_driver(tmp_path: Path, monkeypatch):
    from pm_core import pane_registry as reg
    from pm_core.rc import cleanup

    monkeypatch.setattr(reg, "registry_dir", lambda: tmp_path)

    # No driver registered, but server entry exists
    def _save(raw):
        data = reg._prepare_registry_data(raw, "pm-test")
        data.setdefault("rc_servers", {})["@7"] = {"pid": 999999, "port": 9000}
        return data
    reg.locked_read_modify_write(reg.registry_path("pm-test"), _save)

    killed = []
    monkeypatch.setattr("pm_core.rc.cleanup.os.kill",
                        lambda pid, sig: killed.append((pid, sig)))

    cleanup.maybe_kill_server("pm-test", "@7")
    assert killed == [(999999, cleanup.signal.SIGTERM)]
    # Entry was dropped
    data = reg.load_registry("pm-test")
    assert "@7" not in (data.get("rc_servers") or {})


def test_cleanup_skips_when_driver_alive(tmp_path: Path, monkeypatch):
    from pm_core import pane_registry as reg
    from pm_core.rc import cleanup

    monkeypatch.setattr(reg, "registry_dir", lambda: tmp_path)

    def _save(raw):
        data = reg._prepare_registry_data(raw, "pm-test")
        data.setdefault("rc_servers", {})["@7"] = {"pid": 999999, "port": 9000}
        wdata = reg.get_window_data(data, "@7")
        wdata["panes"].append({"id": "%1", "role": "rc-driver", "order": 0,
                                "cmd": "claude"})
        return data
    reg.locked_read_modify_write(reg.registry_path("pm-test"), _save)

    killed = []
    monkeypatch.setattr("pm_core.rc.cleanup.os.kill",
                        lambda pid, sig: killed.append((pid, sig)))

    cleanup.maybe_kill_server("pm-test", "@7")
    assert killed == []
    data = reg.load_registry("pm-test")
    assert "@7" in (data.get("rc_servers") or {})
