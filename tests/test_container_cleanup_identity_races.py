"""Final cleanup rechecks preserve release authority across runtime renames."""

from unittest.mock import Mock

import pytest

from pm_core import container as cm, container_reaper as reaper


@pytest.mark.parametrize("identity", ["captured-id", None, ""])
def test_disappeared_name_does_not_retire_renamed_owner_release(monkeypatch, identity):
    name, cid = "pm-impl-pr-abcdef0", "captured-id"
    reaper._record_release(name, cid, "epoch", "test")
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)
    monkeypatch.setattr(reaper, "allocation_generation", lambda *a: "epoch")
    monkeypatch.setattr(cm, "current_container_id", lambda target: "" if target == name else identity)
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    decision = reaper.Decision(
        reaper.ContainerInfo(name=name, id=cid), "remove", "released",
        released=True, release_generation="epoch", release_name=name)

    removed, error = reaper._remove_checked(decision, reaper.Scope())
    outcome = reaper.Outcome(decisions=[decision], removed=[name] if removed else [])
    reaper._prune_releases(outcome, reaper.Scope(), float("inf"))
    if identity == "":
        assert removed
        assert not reaper._release_records()
    else:
        assert not removed
        assert error.startswith("error:" if identity is None else "skipped:")
        remove.assert_not_called()
        assert len(reaper._release_records()) == 1
