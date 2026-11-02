"""Tests for store.WriteQueue — the coalescing write queue behind the TUI.

Covers the acceptance criteria for pr-b4b68f3:
- rapid same-key enqueues coalesce to a single disk write of the final value
- the worker drains off the event loop and re-reads under the lock so
  concurrent external edits are respected (not clobbered)
- flush_sync drains synchronously for shutdown paths
- handle_pr_selected no longer writes to disk synchronously per selection
"""

import asyncio
import types

import pytest
import yaml

from pm_core import store


@pytest.fixture
def project_dir(tmp_path):
    data = {
        "project": {"name": "test", "repo": "/tmp/repo", "base_branch": "main"},
        "plans": [],
        "prs": [
            {"id": f"pr-{i:03d}", "title": f"PR {i}", "status": "pending"}
            for i in range(1, 13)
        ],
    }
    path = tmp_path / "project.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f)
    return tmp_path


def _read(project_dir):
    return store.load(project_dir)


class TestWriteQueueCoalescing:
    def test_rapid_enqueue_coalesces_to_one_write(self, project_dir, monkeypatch):
        """12 rapid same-key enqueues collapse to a single disk write of the final value."""
        saves = []
        real_save = store.save
        monkeypatch.setattr(store, "save",
                            lambda data, root=None: (saves.append(1), real_save(data, root)))

        async def scenario():
            wq = store.WriteQueue(project_dir, debounce=0.05)
            worker = asyncio.create_task(wq.run())
            for i in range(1, 13):
                wq.enqueue(
                    ("set", "active_pr"),
                    lambda d, pid=f"pr-{i:03d}": d["project"].__setitem__("active_pr", pid),
                )
            # Wait past the debounce window for the worker to drain.
            await asyncio.sleep(0.3)
            wq.stop()
            await worker

        asyncio.run(scenario())

        assert len(saves) == 1, f"expected one coalesced write, got {len(saves)}"
        assert _read(project_dir)["project"]["active_pr"] == "pr-012"

    def test_distinct_keys_both_applied_in_one_write(self, project_dir):
        """Different keys queued together are all applied in a single drain."""
        async def scenario():
            wq = store.WriteQueue(project_dir, debounce=0.05)
            worker = asyncio.create_task(wq.run())
            wq.enqueue(("set", "active_pr"),
                       lambda d: d["project"].__setitem__("active_pr", "pr-005"))
            wq.enqueue(("set", "hide_merged"),
                       lambda d: d["project"].__setitem__("hide_merged", True))
            await asyncio.sleep(0.3)
            wq.stop()
            await worker

        asyncio.run(scenario())
        proj = _read(project_dir)["project"]
        assert proj["active_pr"] == "pr-005"
        assert proj["hide_merged"] is True


class TestWriteQueueFlush:
    def test_flush_sync_drains_pending(self, project_dir):
        """flush_sync writes pending ops without the worker running."""
        wq = store.WriteQueue(project_dir)
        wq.enqueue(("set", "active_pr"),
                   lambda d: d["project"].__setitem__("active_pr", "pr-007"))
        wq.flush_sync()
        assert _read(project_dir)["project"]["active_pr"] == "pr-007"

    def test_flush_sync_noop_when_empty(self, project_dir, monkeypatch):
        """flush_sync is a no-op (no disk write) when nothing is pending."""
        saves = []
        monkeypatch.setattr(store, "save", lambda *a, **k: saves.append(1))
        store.WriteQueue(project_dir).flush_sync()
        assert saves == []


class TestWriteQueueConflictResolution:
    def test_external_edit_not_clobbered(self, project_dir):
        """An external write between enqueue and drain survives the drain."""
        wq = store.WriteQueue(project_dir)
        wq.enqueue(("set", "active_pr"),
                   lambda d: d["project"].__setitem__("active_pr", "pr-009"))
        # Simulate another pm process editing project.yaml.
        ext = store.load(project_dir)
        ext["prs"].append({"id": "pr-ext", "title": "External", "status": "pending"})
        store.save(ext, project_dir)
        # Drain re-reads fresh disk state under the lock and layers ops on top.
        wq.flush_sync()
        on_disk = _read(project_dir)
        assert on_disk["project"]["active_pr"] == "pr-009"
        assert any(p["id"] == "pr-ext" for p in on_disk["prs"])


class TestWriteQueueErrorContainment:
    def test_failing_op_does_not_block_later_drain(self, project_dir, caplog):
        """A queued op that raises is contained; a later drain still works."""
        wq = store.WriteQueue(project_dir)

        def boom(d):
            raise ValueError("bad op")

        wq.enqueue(("set", "active_pr"), boom)
        wq.flush_sync()  # swallows the error
        # Queue recovers for the next op.
        wq.enqueue(("set", "active_pr"),
                   lambda d: d["project"].__setitem__("active_pr", "pr-003"))
        wq.flush_sync()
        assert _read(project_dir)["project"]["active_pr"] == "pr-003"


class TestHandlePrSelectedRouting:
    """Codified bug repro: selection must not write to disk synchronously."""

    def _stub_app(self, project_dir, write_queue):
        app = types.SimpleNamespace()
        app._root = project_dir
        app._data = store.load(project_dir)
        app._write_queue = write_queue
        app.log_message = lambda *a, **k: None
        app.call_after_refresh = lambda *a, **k: None
        app._capture_frame = lambda *a, **k: None
        return app

    def test_rapid_selection_defers_disk_writes(self, project_dir, monkeypatch):
        """Selecting N PRs performs zero synchronous saves; flush yields one final write."""
        from pm_core.tui import pr_view

        saves = []
        real_save = store.save
        monkeypatch.setattr(store, "save",
                            lambda data, root=None: (saves.append(1), real_save(data, root)))

        wq = store.WriteQueue(project_dir)
        app = self._stub_app(project_dir, wq)

        for i in range(1, 13):
            pr_view.handle_pr_selected(app, f"pr-{i:03d}")

        # Pre-fix this is N synchronous saves; post-fix it must be zero.
        assert saves == [], "selection wrote to disk synchronously"
        assert app._data["project"]["active_pr"] == "pr-012"

        wq.flush_sync()
        assert len(saves) == 1
        assert _read(project_dir)["project"]["active_pr"] == "pr-012"

    def test_fallback_writes_when_no_queue(self, project_dir):
        """Without a write queue (early events/tests), selection persists synchronously."""
        from pm_core.tui import pr_view

        app = self._stub_app(project_dir, None)
        pr_view.handle_pr_selected(app, "pr-004")
        assert _read(project_dir)["project"]["active_pr"] == "pr-004"
