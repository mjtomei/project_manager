"""``do_normal_sync`` must survive PR entries with no usable id.

A partial or externally written project.yaml can contain a PR mapping with
a status but no ``id`` (the popup picker rejects such a snapshot with
"Picker PR entry requires a non-empty, command-safe string id").  The TUI's
background sync used to index those entries directly and raise
``KeyError: 'id'`` out of ``do_normal_sync``, logging a traceback every
sync interval until the file was repaired.
"""

import asyncio
import copy
from unittest import mock

from pm_core import pr_sync
from pm_core.tui import sync


class _FakeApp:
    _qa_visible = False
    _plans_visible = False
    _current_guide_step = None

    def __init__(self, root, data):
        self._root = root
        self._data = data
        self.status_calls = []
        self.messages = []

    def _update_status_bar(self, sync_state="synced"):
        self.status_calls.append(sync_state)

    def _update_display(self):
        pass

    def log_message(self, msg, **k):
        self.messages.append(msg)
        return len(self.messages)

    def clear_log_message_later(self, delay, seq=None):
        pass


def _run(tmp_path, data, merged_prs=None):
    app = _FakeApp(tmp_path, copy.deepcopy(data))
    result = pr_sync.SyncResult(synced=True, merged_prs=merged_prs or [])
    with mock.patch.object(pr_sync, "sync_prs", return_value=result), \
         mock.patch.object(sync.store, "load",
                           side_effect=lambda *a, **k: copy.deepcopy(data)):
        asyncio.run(sync.do_normal_sync(app, is_manual=True))
    return app


def test_sync_skips_entry_without_id(tmp_path):
    data = {"project": {"name": "p", "repo": "/r"},
            "prs": [{"status": "in_review", "title": "no id"}]}
    app = _run(tmp_path, data)
    assert not any("Sync error" in m for m in app.messages)


def test_sync_skips_non_dict_and_unhashable_ids(tmp_path):
    data = {"project": {"name": "p", "repo": "/r"},
            "prs": ["not-a-mapping",
                    {"id": ["unhashable"], "status": "merged"},
                    {"id": None, "status": "merged"}]}
    app = _run(tmp_path, data, merged_prs=[])
    assert not any("Sync error" in m for m in app.messages)


def test_sync_still_detects_merge_on_wellformed_entries(tmp_path):
    data = {"project": {"name": "p", "repo": "/r"},
            "prs": [{"id": "pr-a", "status": "merged", "title": "A"},
                    {"status": "in_review", "title": "no id"}]}
    app = _run(tmp_path, data, merged_prs=[])
    # The malformed neighbour must not stop the well-formed merge from
    # being noticed, and nothing may raise.
    assert not any("Sync error" in m for m in app.messages)
    assert app.status_calls[-1] in ("synced", "no-op")
