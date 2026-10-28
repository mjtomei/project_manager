"""A container removed while another actor is releasing it is not a failure.

S53: `pm pr cleanup --resources` kills the worker window, so the pane's EXIT
trap release runs while the cleanup removes the container. The release's
proxy sweep listed the container, then its inspect hit "no such object" and
the whole inventory failed closed; status then reported the proxy as
"runtime inventory unavailable; proxy preserved" although the cleanup had
stopped it, and still listed the removed container as released while retained.
"""
import subprocess

import click
from click.testing import CliRunner

from pm_core import container, container_reaper as reaper
from pm_core.cli import container as cli_container

GONE = "pm-tag-impl-pr-a"
LIVE = "pm-tag-impl-pr-b"
LABELS = '{"pm.managed":"1"}'


def _runtime(monkeypatch, listings, inspect_results):
    """ps answers from *listings* (one per inventory attempt); inspect from *inspect_results*."""
    calls = []

    def run(*args, **_kw):
        calls.append(args)
        if args[0] == "ps":
            names = listings[min(sum(a[0] == "inspect" for a in calls), len(listings) - 1)]
            return subprocess.CompletedProcess(args, 0, "\n".join(names) + "\n", "")
        rc, out, err = inspect_results.pop(0)
        return subprocess.CompletedProcess(args, rc, out, err)

    monkeypatch.setattr(container, "_run_runtime", run)
    return calls


def _row(name, cid):
    return f"{name}\t{cid}\ttrue\trunning\t{LABELS}\n"


def test_vanished_container_retakes_inventory(monkeypatch):
    calls = _runtime(monkeypatch, [[GONE, LIVE], [LIVE]], [
        (125, _row(LIVE, "id-b"), f'Error: error inspecting object: no such object: "{GONE}"'),
        (0, _row(LIVE, "id-b"), ""),
    ])
    inv = reaper.list_containers()
    assert [i.name for i in inv] == [LIVE]
    assert sum(a[0] == "inspect" for a in calls) == 2


def test_other_inspect_failure_still_fails_closed(monkeypatch):
    calls = _runtime(monkeypatch, [[GONE, LIVE]], [
        (125, "", "Error: cannot connect to the runtime socket"),
    ])
    assert reaper.list_containers() is None
    assert sum(a[0] == "inspect" for a in calls) == 1


def test_retry_is_bounded(monkeypatch):
    absent = (125, "", f'Error: no such object: "{GONE}"')
    calls = _runtime(monkeypatch, [[GONE]], [absent, absent])
    assert reaper.list_containers() is None
    assert sum(a[0] == "inspect" for a in calls) == 2


def test_proxy_of_removed_container_is_released_not_failed(monkeypatch):
    from pm_core import push_proxy
    _runtime(monkeypatch, [[GONE], []], [
        (125, "", f'Error: error inspecting object: no such object: "{GONE}"'),
    ])
    monkeypatch.setattr(push_proxy, "_owner_domain_matches", lambda *_: True)
    monkeypatch.setattr(push_proxy, "_kill_proxy_socket", lambda *_: None)
    assert push_proxy.release_proxy_decision("tag", "pr-a") == push_proxy.PROXY_RELEASED


def _status(monkeypatch, inventory):
    monkeypatch.setattr(reaper, "last_state", lambda: {})
    monkeypatch.setattr(reaper, "unavailable_runtime_diagnostics", lambda: [])
    monkeypatch.setattr(reaper, "local_retained_names", lambda *_: [])
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    monkeypatch.setattr(reaper, "pending_failures", lambda: {
        GONE: {"id": "id-a", "owner_release": True, "error": "owner release pending"},
        LIVE: {"id": "id-b", "owner_release": True, "error": "owner release pending"},
    })
    monkeypatch.setattr(reaper, "is_retained", lambda name, cid="": True)
    cmd = click.Command("s", callback=lambda: cli_container._echo_reaper_state(True, inventory))
    return CliRunner().invoke(cmd, []).output


def test_removed_retained_allocation_not_listed_as_released_while_retained(monkeypatch):
    live = [reaper.ContainerInfo(name=LIVE, id="id-b", running=True)]
    out = _status(monkeypatch, live)
    section = out.split("Released while retained", 1)[1]
    assert LIVE in section and GONE not in out
    assert "Cleanup failures" not in out


def test_unknown_inventory_keeps_listing_deferred_releases(monkeypatch):
    out = _status(monkeypatch, None)
    section = out.split("Released while retained", 1)[1]
    assert GONE in section and LIVE in section


def _ps_runtime(monkeypatch, ps_results):
    calls = []

    def run(*args, **_kw):
        calls.append(args)
        if args[0] == "ps":
            rc, out, err = ps_results.pop(0)
            return subprocess.CompletedProcess(args, rc, out, err)
        return subprocess.CompletedProcess(args, 0, _row(LIVE, "id-b"), "")

    monkeypatch.setattr(container, "_run_runtime", run)
    return calls


def test_ps_racing_a_removal_retakes_inventory(monkeypatch):
    # S52: Podman 3.4 ps fails outright when a container is removed mid-listing
    # (review/sign-off --fresh removes the old allocation while its pane's
    # exit release lists containers).
    race = (125, "", "Error: container 69905ace does not exist in database: no such container")
    calls = _ps_runtime(monkeypatch, [race, (0, f"{LIVE}\n", ""), (0, f"{LIVE}\n", "")])
    assert [i.name for i in reaper.list_containers()] == [LIVE]
    assert sum(a[0] == "ps" for a in calls) == 3


def test_consecutive_removals_racing_ps_retake_inventory(monkeypatch):
    # S62: pm pr cleanup --resources removed two containers 15 ms apart while
    # a pane's exit release listed them; each removal failed one ps listing.
    first = (125, "", "Error: container fccbe80f does not exist in database: no such container")
    second = (125, "", "Error: container c82d89ea does not exist in database: no such container")
    ok = (0, f"{LIVE}\n", "")
    calls = _ps_runtime(monkeypatch, [first, second, ok, ok])
    assert [i.name for i in reaper.list_containers()] == [LIVE]
    assert sum(a[0] == "ps" for a in calls) == 4


def test_same_vanished_container_twice_fails_closed(monkeypatch):
    race = (125, "", "Error: container 69905ace does not exist in database: no such container")
    calls = _ps_runtime(monkeypatch, [race, race, (0, f"{LIVE}\n", "")])
    assert reaper.list_containers() is None
    assert sum(a[0] == "ps" for a in calls) == 2


def test_other_ps_failure_still_fails_closed(monkeypatch):
    calls = _ps_runtime(monkeypatch, [(125, "", "Error: cannot connect to the runtime socket")])
    assert reaper.list_containers() is None
    assert sum(a[0] == "ps" for a in calls) == 1


def _pending_status(monkeypatch, inventory):
    # S62: review/sign-off --fresh removed the old allocation before the old
    # pane's exit release recorded itself; status listed the removed name as
    # "owner release pending; retry with pm container reap" until the
    # release's own deferred pass finished.
    monkeypatch.setattr(reaper, "last_state", lambda: {})
    monkeypatch.setattr(reaper, "unavailable_runtime_diagnostics", lambda: [])
    monkeypatch.setattr(reaper, "local_retained_names", lambda *_: [])
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    pending = "owner release pending; retry with pm container reap"
    domain = {"runtime": "podman", "graph_root": "/g"}
    monkeypatch.setattr(reaper, "pending_failures", lambda: {
        GONE: {"id": "id-a", "owner_release": True, "runtime_domain": domain, "error": pending},
        LIVE: {"id": "id-b", "owner_release": True, "runtime_domain": domain, "error": pending},
    })
    monkeypatch.setattr(reaper, "is_retained", lambda name, cid="": False)
    cmd = click.Command("s", callback=lambda: cli_container._echo_reaper_state(True, inventory))
    return CliRunner().invoke(cmd, []).output


def test_owner_release_of_removed_allocation_not_listed_as_failure(monkeypatch):
    out = _pending_status(monkeypatch, [reaper.ContainerInfo(name=LIVE, id="id-b", running=True)])
    assert "Cleanup failures (1)" in out and LIVE in out and GONE not in out


def test_same_name_replacement_keeps_old_release_hidden(monkeypatch):
    # The replacing launch reuses the name with a new ID: the old ID is gone.
    out = _pending_status(monkeypatch, [reaper.ContainerInfo(name=GONE, id="id-new", running=True),
                                        reaper.ContainerInfo(name=LIVE, id="id-b", running=True)])
    assert f"{GONE}:" not in out and f"{LIVE}:" in out


def test_unknown_inventory_keeps_listing_pending_releases(monkeypatch):
    out = _pending_status(monkeypatch, None)
    assert "Cleanup failures (2)" in out and GONE in out and LIVE in out
