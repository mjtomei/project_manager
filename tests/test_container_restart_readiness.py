"""Restart must recover the captured allocation and observe this boot's setup."""

import json
import subprocess
from unittest.mock import MagicMock

import pytest

from pm_core import container as cm


@pytest.mark.parametrize("fresh_marker", [True, False])
@pytest.mark.parametrize("boot_time", ["2026-10-26T00:00:00.123456789Z",
                                      "2026-10-26T01:00:00.123456789+01:00"])
def test_restart_waits_for_current_boot_and_pins_id(tmp_path, monkeypatch, fresh_marker, boot_time):
    name, cid = "pm-t-review-pr-aaaa", "original-id"
    sentinel = tmp_path / "ready"
    sentinel.touch()
    import os
    # Only one nanosecond before this boot; second/microsecond rounding fails.
    os.utime(sentinel, ns=(1792972800123456788, 1792972800123456788))
    monkeypatch.setattr(cm, "_READY_SENTINEL", str(sentinel))
    monkeypatch.setattr(cm, "current_container_id", lambda _: cid)
    monkeypatch.setattr(cm, "_SETUP_TIMEOUT", 0.2)
    monkeypatch.setattr(cm, "_SETUP_POLL_INTERVAL", 0)
    calls = []
    probes = 0

    def runtime(*args, **kwargs):
        nonlocal probes
        calls.append(args)
        if args[0] == "inspect":
            return subprocess.CompletedProcess(args, 0, json.dumps(boot_time), "")
        if args[0] == "exec":
            probes += 1
            if fresh_marker and probes == 2:
                os.utime(sentinel, ns=(1792972800123456789, 1792972800123456789))
            # Execute the real readiness predicate against a host-local fixture.
            return subprocess.run(args[2:], capture_output=True, text=True)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    complete = MagicMock(return_value=True)
    monkeypatch.setattr(cm, "_setup_complete", complete)
    if fresh_marker:
        cm.restart_container(name)
        assert probes >= 2  # the previous boot's ready marker was rejected
        complete.assert_called_once_with(cid)
    else:
        with pytest.raises(cm.ContainerLaunchError, match="come back up after restart"):
            cm.restart_container(name)
        complete.assert_not_called()
    assert ("restart", "-t", "5", cid) in calls
    assert all(args[1] == cid for args in calls if args[0] == "exec")


@pytest.mark.parametrize("timestamp", ["", "garbage", "0001-01-01T00:00:00Z"])
def test_restart_refuses_unknown_boot_time(monkeypatch, timestamp):
    monkeypatch.setattr(cm, "current_container_id", lambda _: "original-id")
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, json.dumps(timestamp), ""))
    complete = MagicMock(return_value=True)
    monkeypatch.setattr(cm, "_setup_complete", complete)
    with pytest.raises(cm.ContainerError, match="start time"):
        cm.restart_container("pm-t-review-pr-aaaa")
    complete.assert_not_called()


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_fresh_publication_cancellation_discards_allocation(tmp_path, monkeypatch, error):
    monkeypatch.setattr(cm, "recent_launch", lambda *a: False)
    monkeypatch.setattr(cm, "_ensure_reusable", lambda *a, **k: None)
    monkeypatch.setattr(cm, "_create_fresh", lambda *a, **k: "fresh-id")
    monkeypatch.setattr(cm, "_renew_launch", MagicMock(side_effect=error))
    discard = MagicMock()
    monkeypatch.setattr(cm, "discard_container", discard)
    with pytest.raises(error):
        cm.create_container("pm-t-review-pr-aaaa", cm.ContainerConfig(), tmp_path)
    discard.assert_called_once_with("pm-t-review-pr-aaaa")
