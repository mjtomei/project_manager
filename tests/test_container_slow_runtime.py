"""A slow runtime is not a failed launch.

Under concurrent QA launches the nested Podman runtime serialises on its
storage lock: ``run`` calls took 28-44 s while sibling probes were given
10 s.  Treating an unanswered probe as a definitive answer aborted real
scenarios ("image not found", "identity unavailable").  These tests pin
the unknown-vs-absent distinction for the image and identity probes;
readiness polling is covered by test_container_setup_safety.py.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_core import container as cm


@pytest.fixture(autouse=True)
def _fresh_image_cache():
    cm._invalidate_image_exists_cache()
    yield
    cm._invalidate_image_exists_cache()


def test_image_check_timeout_is_unknown_not_missing(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

    monkeypatch.setattr(cm, "_get_runtime", lambda: "podman")
    monkeypatch.setattr(cm.subprocess, "run", run)
    assert cm.image_exists("custom:v1") is None
    # Queued callers reuse the unknown result instead of waiting again.
    assert cm.image_exists("custom:v1") is None
    assert len(calls) == 1


@patch("pm_core.container._get_runtime", return_value="podman")
@patch("pm_core.container.container_is_running", return_value=False)
class TestUnknownImagePresence:
    @pytest.fixture(autouse=True)
    def unowned(self, monkeypatch):
        monkeypatch.setattr("pm_core.container_reaper.live_owner_panes", lambda *a: [])

    @patch("pm_core.container.image_exists", return_value=None)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_custom_image_lets_run_decide(self, mock_runtime, mock_rm, mock_exists,
                                          _mock_running, _mock_get_runtime):
        mock_runtime.return_value = MagicMock(stdout="id\n", returncode=0)
        with patch.object(Path, "is_dir", return_value=False):
            cm.create_container(name="test", config=cm.ContainerConfig(image="custom:v1"),
                                workdir=Path("/w"))
        assert any(c.args[0] == "run" for c in mock_runtime.call_args_list)

    @patch("pm_core.container.build_image")
    @patch("pm_core.container.image_exists", return_value=None)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_default_image_is_not_rebuilt(self, mock_runtime, mock_rm, mock_exists,
                                          mock_build, _mock_running, _mock_get_runtime):
        mock_runtime.return_value = MagicMock(stdout="id\n", returncode=0)
        with patch.object(Path, "is_dir", return_value=False):
            cm.create_container(name="test", config=cm.ContainerConfig(), workdir=Path("/w"))
        mock_build.assert_not_called()
        assert any(c.args[0] == "run" for c in mock_runtime.call_args_list)


def test_identity_check_timeout_is_unknown_not_absent(monkeypatch):
    def runtime(*args, **kwargs):
        raise subprocess.TimeoutExpired(["podman", *args], kwargs.get("timeout"))

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    assert cm.current_container_id("pm-x") is None


def test_reuse_preflight_retries_an_unanswered_inspect(monkeypatch):
    """The launch proceeds once the busy runtime answers."""
    monkeypatch.setattr(cm, "_IDENTITY_PROBE_BUDGET", 5.0)
    monkeypatch.setattr(cm, "_IDENTITY_PROBE_INTERVAL", 0)
    answers = iter([None, None, ""])  # unknown, unknown, then explicitly absent

    monkeypatch.setattr(cm, "current_container_id", lambda _: next(answers, ""))
    assert cm._ensure_reusable("pm-x", Path("/w"), None,
                               session_tag=None, pr_id=None) is None


def test_reuse_preflight_still_fails_closed_when_never_answered(monkeypatch):
    monkeypatch.setattr(cm, "_IDENTITY_PROBE_BUDGET", 0.05)
    monkeypatch.setattr(cm, "_IDENTITY_PROBE_INTERVAL", 0)
    monkeypatch.setattr(cm, "current_container_id", lambda _: None)
    monkeypatch.setattr(cm, "container_is_running",
                        MagicMock(side_effect=subprocess.TimeoutExpired(["podman"], 10)))
    with pytest.raises(cm.ContainerLaunchError) as ei:
        cm._ensure_reusable("pm-x", Path("/w"), None, session_tag=None, pr_id=None)
    assert ei.value.kind == "runtime"
    assert "identity unavailable" in str(ei.value)
