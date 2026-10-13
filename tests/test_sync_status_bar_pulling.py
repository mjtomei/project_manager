"""The "pulling..." status bar keeps the AUTO ×N / WCH / filter segments.

``do_normal_sync`` used to paint "pulling..." with a bare
``StatusBar.update_status(name, repo, "pulling")``, which dropped every
other indicator for the length of each pull (every ``r`` and background
sync): armed auto-start targets lost their ``AUTO ×N`` segment and the
filter segment vanished until the sync finished.
"""

import asyncio
from unittest import mock

from pm_core import pr_sync
from pm_core.tui import sync


class _FakeApp:
    _qa_visible = False
    _plans_visible = False

    def __init__(self, root):
        self._root = root
        self._data = {"project": {"name": "p", "repo": "/r"}, "prs": []}
        self.status_calls = []
        self.messages = []

    def _update_status_bar(self, sync_state="synced"):
        self.status_calls.append(sync_state)

    def query_one(self, *a, **k):  # the bare update_status() path
        raise AssertionError("pulling must go through _update_status_bar")

    def log_message(self, msg, **k):
        self.messages.append(msg)


def test_pulling_state_goes_through_full_status_bar(tmp_path):
    app = _FakeApp(tmp_path)
    seen_during_sync = []

    def fake_sync_prs(*a, **k):
        seen_during_sync.extend(app.status_calls)
        raise RuntimeError("stop after the pulling paint")

    with mock.patch.object(pr_sync, "sync_prs", fake_sync_prs):
        asyncio.run(sync.do_normal_sync(app, is_manual=True))

    assert seen_during_sync == ["pulling"]
    assert not any("pulling must go" in m for m in app.messages)


def test_mode_owned_status_bar_not_clobbered(tmp_path):
    app = _FakeApp(tmp_path)
    app._qa_visible = True

    def fake_sync_prs(*a, **k):
        raise RuntimeError("stop")

    with mock.patch.object(pr_sync, "sync_prs", fake_sync_prs):
        asyncio.run(sync.do_normal_sync(app, is_manual=True))

    assert app.status_calls == []
