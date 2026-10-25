"""Preflight cleanup and proxy inventory share allocation ownership rules."""

import json
import subprocess
from unittest.mock import MagicMock

import pytest

from pm_core import container as cm, container_reaper as reaper, push_proxy

NAME = "pm-tag-review-pr-aaaa"


@pytest.mark.parametrize("captured", [False, True])
def test_preflight_preserves_other_launch_attachment_lease(monkeypatch, captured):
    cm._renew_launch(NAME)
    monkeypatch.setattr(cm, "current_container_id", lambda name: "cid")
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a, **k: [])
    remove = MagicMock()
    monkeypatch.setattr(cm, "remove_container", remove)
    monkeypatch.setattr(push_proxy, "stop_push_proxy", MagicMock())
    kwargs = {"container_id": "cid", "generation": cm.cleanup_generation(NAME)} if captured else {}
    assert cm.discard_unowned_container(NAME, **kwargs) is captured
    assert remove.called is captured


@pytest.mark.parametrize("labelled", [True, False])
def test_proxy_inventory_respects_labels_then_legacy_names(monkeypatch, labelled):
    name = "pm-renamed" if labelled else NAME
    labels = {cm.LABEL_MANAGED: "1", cm.LABEL_SESSION: "tag", cm.LABEL_PR: "pr-aaaa"} if labelled else {}

    def runtime(*args, **kwargs):
        if args[0] == "ps":
            output = name + "\n"
        elif args[0] == "inspect":
            output = f"/{name}\tcid\ttrue\trunning\t{json.dumps(labels)}\n"
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    assert cm.containers_for_pr("tag", "pr-aaaa") == {name}
    assert cm.containers_for_pr("other", "pr-aaaa") == set()


def test_proxy_inventory_unknown_labels_preserves_proxy(monkeypatch):
    def runtime(*args, **kwargs):
        if args[0] == "ps":
            return subprocess.CompletedProcess(args, 0, "pm-renamed\n", "")
        return subprocess.CompletedProcess(args, 125, "", "runtime unavailable")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    assert cm.containers_for_pr("tag", "pr-aaaa") is None
