"""Tests for container isolation of Claude sessions."""

import shlex
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from pm_core.container import (
    ContainerConfig,
    ContainerError,
    qa_container_name,
    load_container_config,
    is_container_mode_enabled,
    create_container,
    create_qa_container,
    build_exec_cmd,
    build_image,
    image_exists,
    remove_container,
    cleanup_qa_containers,
    cleanup_session_containers,
    cleanup_all_containers,
    wrap_claude_cmd,
    container_is_running,
    _runtime_available,
    _build_git_setup_script,
    _get_dockerfile_path,
    _get_runtime,
    _make_container_name,
    _resolve_claude_binary,
    DEFAULT_IMAGE,
    DEFAULT_MEMORY_LIMIT,
    DEFAULT_CPU_LIMIT,
    DEFAULT_RUNTIME,
    CONTAINER_PREFIX,
    _CONTAINER_WORKDIR,
    _CONTAINER_SCRATCH,
    _CONTAINER_USER,
    _CONTAINER_HOME,
)


class TestDefaultImage:
    def test_default_is_pm_dev(self):
        assert DEFAULT_IMAGE == "pm-dev:latest"

    def test_dockerfile_exists(self):
        assert _get_dockerfile_path().exists()


class TestBuildImage:
    @patch("subprocess.run")
    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_builds_with_tag(self, mock_runtime, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        build_image(tag="pm-dev:test", quiet=True)
        args = mock_run.call_args[0][0]
        assert args[0] == "docker"
        assert args[1] == "build"
        assert "-t" in args
        assert "pm-dev:test" in args

    @patch("subprocess.run")
    def test_raises_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="fail")
        with pytest.raises(RuntimeError, match="Image build failed"):
            build_image(quiet=True)


class TestImageExists:
    def setup_method(self):
        # image_exists caches results across calls; clear between tests.
        from pm_core.container import _invalidate_image_exists_cache
        _invalidate_image_exists_cache()

    @patch("subprocess.run")
    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_exists(self, mock_runtime, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert image_exists("pm-dev:latest") is True

    @patch("subprocess.run")
    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_not_exists(self, mock_runtime, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert image_exists("pm-dev:latest") is False

    @patch("subprocess.run")
    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_runtime_not_installed(self, mock_runtime, mock_run):
        mock_run.side_effect = FileNotFoundError
        assert image_exists("pm-dev:latest") is False

    @patch("subprocess.run")
    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_result_is_cached_across_calls(self, mock_runtime, mock_run):
        """Concurrent callers coalesce onto one ``podman image inspect``."""
        mock_run.return_value = MagicMock(returncode=0)
        for _ in range(5):
            assert image_exists("pm-dev:latest") is True
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_cache_invalidated_on_build(self, mock_runtime, mock_run):
        from pm_core.container import _invalidate_image_exists_cache
        # Cache a False result
        mock_run.return_value = MagicMock(returncode=1)
        assert image_exists("pm-dev:latest") is False
        # Simulate a successful build clearing the cache
        _invalidate_image_exists_cache("pm-dev:latest")
        mock_run.return_value = MagicMock(returncode=0)
        assert image_exists("pm-dev:latest") is True
        assert mock_run.call_count == 2


class TestContainerConfig:
    def test_defaults(self):
        cfg = ContainerConfig()
        assert cfg.image == DEFAULT_IMAGE
        assert cfg.memory_limit == DEFAULT_MEMORY_LIMIT
        assert cfg.cpu_limit == DEFAULT_CPU_LIMIT
        assert cfg.env == {}
        assert cfg.extra_mounts == []

    def test_custom(self):
        cfg = ContainerConfig(
            image="my-image:latest",
            memory_limit="8g",
            cpu_limit="4.0",
            env={"FOO": "bar"},
            extra_mounts=["/host:/container:ro"],
        )
        assert cfg.image == "my-image:latest"
        assert cfg.memory_limit == "8g"
        assert cfg.env == {"FOO": "bar"}


class TestContainerName:
    def test_qa_format(self):
        name = qa_container_name("pr-abc123", "loop456", 3)
        assert name == f"{CONTAINER_PREFIX}qa-pr-abc123-loop456-s3"

    def test_qa_with_session_tag(self):
        name = qa_container_name("pr-abc123", "loop456", 3,
                                 session_tag="myrepo-c5a1006b")
        assert name == f"{CONTAINER_PREFIX}myrepo-c5a1006b-qa-pr-abc123-loop456-s3"

    def test_qa_different_indices(self):
        n1 = qa_container_name("pr-x", "loop", 1)
        n2 = qa_container_name("pr-x", "loop", 2)
        assert n1 != n2
        assert n1.endswith("-s1")
        assert n2.endswith("-s2")

    def test_make_container_name_deterministic(self):
        """Container names are deterministic (no random suffix)."""
        name = _make_container_name("impl")
        assert name == f"{CONTAINER_PREFIX}impl"

    def test_make_container_name_with_session_tag(self):
        name = _make_container_name("impl", session_tag="myrepo-c5a1006b")
        assert name == f"{CONTAINER_PREFIX}myrepo-c5a1006b-impl"

    def test_make_container_name_same_label_same_name(self):
        """Same label produces the same name (deterministic)."""
        n1 = _make_container_name("test")
        n2 = _make_container_name("test")
        assert n1 == n2


class TestLoadContainerConfig:
    @patch("pm_core.paths.get_global_setting_value")
    def test_loads_from_settings(self, mock_get):
        mock_get.side_effect = lambda name, default="": {
            "container-image": "custom:v2",
            "container-memory-limit": "16g",
            "container-cpu-limit": "8.0",
            "container-runtime": "podman",
        }.get(name, default)

        cfg = load_container_config()
        assert cfg.image == "custom:v2"
        assert cfg.memory_limit == "16g"
        assert cfg.cpu_limit == "8.0"
        assert cfg.runtime == "podman"

    @patch("pm_core.paths.get_global_setting_value")
    def test_falls_back_to_defaults(self, mock_get):
        mock_get.side_effect = lambda name, default="": default
        cfg = load_container_config()
        assert cfg.image == DEFAULT_IMAGE
        assert cfg.memory_limit == DEFAULT_MEMORY_LIMIT
        assert cfg.cpu_limit == DEFAULT_CPU_LIMIT
        assert cfg.runtime == DEFAULT_RUNTIME


class TestIsContainerModeEnabled:
    @patch("pm_core.paths.get_global_setting")
    def test_enabled(self, mock_get):
        mock_get.return_value = True
        assert is_container_mode_enabled() is True
        mock_get.assert_called_with("container-enabled")

    @patch("pm_core.paths.get_global_setting")
    def test_disabled(self, mock_get):
        mock_get.return_value = False
        assert is_container_mode_enabled() is False


class TestRuntimeAvailable:
    @patch("subprocess.run")
    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_available(self, mock_runtime, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert _runtime_available() is True

    @patch("subprocess.run")
    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_not_available(self, mock_runtime, mock_run):
        mock_run.side_effect = FileNotFoundError
        assert _runtime_available() is False

    @patch("subprocess.run")
    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_daemon_not_running(self, mock_runtime, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert _runtime_available() is False

    @patch("subprocess.run")
    @patch("pm_core.container._get_runtime", return_value="podman")
    def test_podman_runtime(self, mock_runtime, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert _runtime_available() is True
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][0] == "podman"


class TestGetRuntime:
    @patch("pm_core.paths.get_global_setting_value", return_value="podman")
    def test_explicit_setting_wins(self, mock_get):
        assert _get_runtime() == "podman"

    @patch("pm_core.paths.get_global_setting_value")
    def test_defaults_to_docker(self, mock_get):
        mock_get.side_effect = lambda name, default: default
        assert _get_runtime() == "docker"


@patch("pm_core.container.container_is_running", return_value=False)
class TestCreateContainerPodman:
    """Podman-specific create_container tests."""

    @patch("pm_core.container._get_runtime", return_value="podman")
    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_userns_keep_id_added_for_podman(self, mock_runtime_cmd, mock_rm,
                                              mock_exists, mock_get_runtime,
                                              _mock_running):
        """Podman runtime adds --userns=keep-id to run commands."""
        mock_runtime_cmd.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"))

        run_call = mock_runtime_cmd.call_args_list[0]
        args = run_call[0]
        assert "--userns=keep-id" in args

    @patch("pm_core.container._get_runtime", return_value="podman")
    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_podman_skips_useradd(self, mock_runtime_cmd, mock_rm,
                                   mock_exists, mock_get_runtime,
                                   _mock_running):
        """Podman setup script does NOT run groupadd/useradd."""
        mock_runtime_cmd.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"))

        run_call = mock_runtime_cmd.call_args_list[0]
        setup_script = run_call[0][-1]  # last arg is the bash -c script
        assert "groupadd" not in setup_script
        assert "useradd" not in setup_script
        assert "mkdir -p /home/pm" in setup_script

    @patch("pm_core.container._get_runtime", return_value="podman")
    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_podman_no_su_in_git_config(self, mock_runtime_cmd, mock_rm,
                                         mock_exists, mock_get_runtime,
                                         _mock_running):
        """Podman setup script does NOT use su for git config."""
        mock_runtime_cmd.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"))

        run_call = mock_runtime_cmd.call_args_list[0]
        setup_script = run_call[0][-1]
        assert "su -" not in setup_script
        assert "su -c" not in setup_script

    @patch("pm_core.container._get_runtime", return_value="docker")
    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_userns_keep_id_not_added_for_docker(self, mock_runtime_cmd, mock_rm,
                                                  mock_exists, mock_get_runtime,
                                                  _mock_running):
        """Docker runtime does NOT add --userns=keep-id."""
        mock_runtime_cmd.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"))

        run_call = mock_runtime_cmd.call_args_list[0]
        args = run_call[0]
        assert "--userns=keep-id" not in args

    @patch("pm_core.container._get_runtime", return_value="docker")
    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_docker_uses_useradd(self, mock_runtime_cmd, mock_rm,
                                  mock_exists, mock_get_runtime,
                                  _mock_running):
        """Docker setup script runs groupadd/useradd."""
        mock_runtime_cmd.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"))

        run_call = mock_runtime_cmd.call_args_list[0]
        setup_script = run_call[0][-1]
        assert "groupadd" in setup_script
        assert "useradd" in setup_script


@patch("pm_core.container._get_runtime", return_value="docker")
@patch("pm_core.container.container_is_running", return_value=False)
class TestCreateContainer:
    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_creates_with_workdir(self, mock_docker, mock_rm, mock_exists, _mock_running, _mock_runtime):
        mock_docker.return_value = MagicMock(stdout="abc123\n", returncode=0)

        config = ContainerConfig(image="test:v1", memory_limit="2g", cpu_limit="1.0")
        cid = create_container(
            name="pm-test",
            config=config,
            workdir=Path("/my/workdir"),
        )

        assert cid == "abc123"
        mock_rm.assert_called_once_with("pm-test")

        # First call is `docker run`, subsequent calls are readiness checks
        run_call = mock_docker.call_args_list[0]
        args = run_call[0]
        assert args[0] == "run"
        assert "-d" in args
        assert f"/my/workdir:{_CONTAINER_WORKDIR}" in " ".join(args)
        # Entrypoint creates pm user then execs sleep infinity
        assert args[-3] == "bash"
        assert args[-2] == "-c"
        assert "useradd" in args[-1]
        assert "sleep infinity" in args[-1]

    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_extra_ro_mounts(self, mock_docker, mock_rm, mock_exists, _mock_running, _mock_runtime):
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        create_container(
            name="test",
            config=config,
            workdir=Path("/w"),
            extra_ro_mounts={Path("/repo"): "/repo"},
        )

        args_str = " ".join(mock_docker.call_args_list[0][0])
        assert "/repo:/repo:ro" in args_str

    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_extra_rw_mounts(self, mock_docker, mock_rm, mock_exists, _mock_running, _mock_runtime):
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        create_container(
            name="test",
            config=config,
            workdir=Path("/w"),
            extra_rw_mounts={Path("/scratch"): "/scratch"},
        )

        args_str = " ".join(mock_docker.call_args_list[0][0])
        assert "/scratch:/scratch" in args_str
        # Should NOT have :ro suffix
        assert "/scratch:/scratch:ro" not in args_str

    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_passes_env_vars(self, mock_docker, mock_rm, mock_exists, _mock_running, _mock_runtime):
        mock_docker.return_value = MagicMock(stdout="id123\n", returncode=0)

        config = ContainerConfig(env={"CUSTOM_VAR": "custom_val"})
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            create_container(
                name="test",
                config=config,
                workdir=Path("/w"),
            )

        args_str = " ".join(mock_docker.call_args_list[0][0])
        assert "ANTHROPIC_API_KEY=sk-test" in args_str
        assert "CUSTOM_VAR=custom_val" in args_str

    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container._resolve_claude_binary", return_value=None)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_mounts_claude_config_rw(self, mock_docker, mock_rm, mock_bin, mock_exists, _mock_running, _mock_runtime):
        """~/.claude is mounted read-write so Claude can write session state."""
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch("pm_core.container.Path.home", return_value=Path("/home/user")), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "exists", return_value=True):
            create_container(name="test", config=config, workdir=Path("/w"))

        args_str = " ".join(mock_docker.call_args_list[0][0])
        assert f"/home/user/.claude:{_CONTAINER_HOME}/.claude" in args_str
        # Should NOT be read-only
        assert f"/home/user/.claude:{_CONTAINER_HOME}/.claude:ro" not in args_str

    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container._resolve_claude_binary", return_value=None)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_copies_claude_json(self, mock_docker, mock_rm, mock_bin, mock_exists, _mock_running, _mock_runtime):
        """.claude.json is copied (not bind-mounted) into the container."""
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch("pm_core.container.Path.home", return_value=Path("/home/user")), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "exists", return_value=True):
            create_container(name="test", config=config, workdir=Path("/w"))

        # .claude.json should NOT be in the docker run args (no bind mount)
        args_str = " ".join(mock_docker.call_args_list[0][0])
        assert f"/home/user/.claude.json:{_CONTAINER_HOME}/.claude.json" not in args_str
        # Instead it should be copied via docker cp (second call after run)
        all_calls = mock_docker.call_args_list
        cp_calls = [c for c in all_calls if len(c[0]) > 0 and c[0][0] == "cp"]
        assert len(cp_calls) >= 1, "docker cp should be called for .claude.json"

    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container._resolve_claude_binary")
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_mounts_claude_binary(self, mock_docker, mock_rm, mock_resolve, mock_exists, _mock_running, _mock_runtime):
        """Host claude binary is bind-mounted at /usr/local/bin/claude."""
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        # Simulate a resolved binary that exists
        fake_bin = Path("/home/user/.local/share/claude/versions/1.0.0")
        mock_resolve.return_value = fake_bin

        config = ContainerConfig()
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"))

        args_str = " ".join(mock_docker.call_args_list[0][0])
        assert f"{fake_bin}:/usr/local/bin/claude:ro" in args_str

    @patch("pm_core.container.build_image")
    @patch("pm_core.container.image_exists", return_value=False)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_auto_builds_default_image(self, mock_docker, mock_rm, mock_exists, mock_build, _mock_running, _mock_runtime):
        """Default image is auto-built if it doesn't exist locally."""
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()  # uses DEFAULT_IMAGE

        with patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"))

        mock_build.assert_called_once_with(tag=DEFAULT_IMAGE, quiet=True)

    @patch("pm_core.container.build_image")
    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_skips_build_if_image_exists(self, mock_docker, mock_rm, mock_exists, mock_build, _mock_running, _mock_runtime):
        """Skips auto-build when the default image already exists."""
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"))

        mock_build.assert_not_called()

    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_no_auto_build_for_custom_image(self, mock_docker, mock_rm, mock_exists, _mock_running, _mock_runtime):
        """Custom images are not auto-built, but existence is checked."""
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig(image="custom:v1")

        with patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"))

        # image_exists is called to verify the custom image exists,
        # but build_image should NOT be called
        mock_exists.assert_called_once_with("custom:v1")

    @patch("pm_core.container.image_exists", return_value=False)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_missing_custom_image_raises(self, mock_docker, mock_rm, mock_exists, _mock_running, _mock_runtime):
        """Missing custom image raises a clear error."""
        config = ContainerConfig(image="custom:v1")

        with pytest.raises(ContainerError, match="not found in docker"):
            create_container(name="test", config=config, workdir=Path("/w"))

    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container._resolve_claude_binary", return_value=None)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_no_binary_still_creates_container(self, mock_docker, mock_rm, mock_resolve, mock_exists, _mock_running, _mock_runtime):
        """Container creation succeeds even if claude binary is not found."""
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch.object(Path, "is_dir", return_value=False):
            cid = create_container(name="test", config=config, workdir=Path("/w"))

        assert cid == "id"
        # Should not contain /usr/local/bin/claude mount
        args_str = " ".join(mock_docker.call_args_list[0][0])
        assert "/usr/local/bin/claude" not in args_str


@patch("pm_core.container._get_runtime", return_value="docker")
class TestContainerReuse:
    @patch("pm_core.container.container_is_running", return_value=True)
    @patch("pm_core.container._run_runtime")
    def test_reuses_running_container(self, mock_docker, mock_running, _mock_runtime):
        """An existing running container is reused instead of recreated."""
        mock_docker.return_value = MagicMock(
            returncode=0, stdout="abc123deadbeef\n")

        config = ContainerConfig()
        cid = create_container(name="pm-test", config=config,
                               workdir=Path("/w"))
        assert cid == "abc123deadbeef"
        # Should only call inspect, not run
        calls = [c[0][0] for c in mock_docker.call_args_list]
        assert "inspect" in calls
        assert "run" not in calls

    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container.container_is_running", return_value=False)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_creates_new_when_not_running(self, mock_docker, mock_rm,
                                          mock_running, mock_exists, _mock_runtime):
        """A new container is created when none exists."""
        mock_docker.return_value = MagicMock(stdout="newid\n", returncode=0)
        config = ContainerConfig()
        cid = create_container(name="pm-test", config=config,
                               workdir=Path("/w"))
        assert cid == "newid"
        mock_rm.assert_called_once_with("pm-test")
        # First docker call should be "run"
        assert mock_docker.call_args_list[0][0][0] == "run"


class TestResolveClaudeBinary:
    @patch("shutil.which", return_value="/usr/local/bin/claude")
    def test_resolves_symlink(self, mock_which):
        result = _resolve_claude_binary()
        assert result is not None
        # Path.resolve() is called on the result
        mock_which.assert_called_once_with("claude")

    @patch("shutil.which", return_value=None)
    def test_returns_none_when_not_found(self, mock_which):
        result = _resolve_claude_binary()
        assert result is None


class TestCreateQAContainer:
    @patch("pm_core.container.create_container")
    def test_delegates_with_qa_mounts(self, mock_create):
        mock_create.return_value = "qa-id"

        config = ContainerConfig()
        cid = create_qa_container(
            name="pm-qa-test-s1",
            config=config,
            workdir=Path("/clones/c1"),
            scratch_path=Path("/scratch/s1"),
        )

        assert cid == "qa-id"
        mock_create.assert_called_once_with(
            name="pm-qa-test-s1",
            config=config,
            workdir=Path("/clones/c1"),
            extra_rw_mounts={Path("/scratch/s1"): _CONTAINER_SCRATCH},
            allowed_push_branch=None,
            session_tag=None,
            pr_id=None,
        )

    @patch("pm_core.container.create_container")
    def test_passes_push_branch(self, mock_create):
        mock_create.return_value = "qa-id"
        config = ContainerConfig()
        create_qa_container(
            name="pm-qa-test-s1",
            config=config,
            workdir=Path("/clones/c1"),
            scratch_path=Path("/scratch/s1"),
            allowed_push_branch="pm/pr-123-feature",
        )
        mock_create.assert_called_once_with(
            name="pm-qa-test-s1",
            config=config,
            workdir=Path("/clones/c1"),
            extra_rw_mounts={Path("/scratch/s1"): _CONTAINER_SCRATCH},
            allowed_push_branch="pm/pr-123-feature",
            session_tag=None,
            pr_id=None,
        )

    @patch("pm_core.container.create_container")
    def test_passes_session_tag_and_pr_id(self, mock_create):
        mock_create.return_value = "qa-id"
        config = ContainerConfig()
        create_qa_container(
            name="pm-repo-abc-qa-test-s1",
            config=config,
            workdir=Path("/clones/c1"),
            scratch_path=Path("/scratch/s1"),
            allowed_push_branch="pm/pr-123-feature",
            session_tag="repo-abc",
            pr_id="pr-123",
        )
        mock_create.assert_called_once_with(
            name="pm-repo-abc-qa-test-s1",
            config=config,
            workdir=Path("/clones/c1"),
            extra_rw_mounts={Path("/scratch/s1"): _CONTAINER_SCRATCH},
            allowed_push_branch="pm/pr-123-feature",
            session_tag="repo-abc",
            pr_id="pr-123",
        )


class TestBuildExecCmd:
    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_basic(self, mock_runtime):
        cmd = build_exec_cmd("my-container", "claude 'hello world'")
        assert "docker exec -it" in cmd
        assert f"-u {_CONTAINER_USER}" in cmd
        assert "my-container" in cmd
        assert "claude" in cmd
        assert "hello world" in cmd

    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_includes_cleanup_by_default(self, mock_runtime):
        cmd = build_exec_cmd("my-container", "claude 'hi'")
        assert "docker rm -f" in cmd
        # Cleanup is wrapped in a bash trap for robustness against kill-pane
        assert cmd.startswith("bash -c ")
        assert "trap " in cmd
        assert "EXIT" in cmd

    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_cleanup_removes_proxy_socket(self, mock_runtime):
        cmd = build_exec_cmd("my-container", "claude 'hi'",
                             proxy_socket_path="/tmp/pm-push-proxy-x/push.sock")
        assert "rm -f" in cmd
        assert "/tmp/pm-push-proxy-x/push.sock" in cmd
        assert "rmdir" in cmd
        assert "/tmp/pm-push-proxy-x" in cmd
        # Socket removal should come before container rm
        rm_pos = cmd.index("rm -f")
        runtime_rm_pos = cmd.index("docker rm")
        assert rm_pos < runtime_rm_pos

    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_no_cleanup_when_disabled(self, mock_runtime):
        cmd = build_exec_cmd("my-container", "claude 'hi'", cleanup=False)
        assert "docker rm -f" not in cmd

    @patch("pm_core.container._get_runtime", return_value="docker")
    def test_shell_safety(self, mock_runtime):
        cmd = build_exec_cmd("name-with-special", "claude 'prompt with $vars'")
        # The command is wrapped in bash -c with a trap, so parse the outer layer
        outer = shlex.split(cmd)
        assert outer[0] == "bash"
        assert outer[1] == "-c"
        # The inner script should contain a proper docker exec invocation
        inner = outer[2]
        assert "docker exec -it" in inner
        assert f"-u {_CONTAINER_USER}" in inner
        assert "name-with-special" in inner

    @patch("pm_core.container._get_runtime", return_value="podman")
    def test_uses_configured_runtime(self, mock_runtime):
        cmd = build_exec_cmd("my-container", "claude 'hi'")
        assert "podman exec -it" in cmd
        assert "podman rm -f" in cmd
        # Podman should NOT use -u pm (user is already mapped via --userns=keep-id)
        assert f"-u {_CONTAINER_USER}" not in cmd


class TestWrapClaudeCmd:
    @patch("pm_core.container.is_container_mode_enabled", return_value=False)
    def test_passthrough_when_disabled(self, mock_enabled):
        cmd, cname = wrap_claude_cmd("claude 'hello'", "/workdir")
        assert cmd == "claude 'hello'"
        assert cname == ""

    @patch("pm_core.container.build_exec_cmd", return_value="docker exec ...")
    @patch("pm_core.container.create_container", return_value="cid123")
    @patch("pm_core.container.load_container_config",
           return_value=ContainerConfig())
    @patch("pm_core.container.is_container_mode_enabled", return_value=True)
    def test_wraps_when_enabled(self, mock_enabled, mock_config,
                                 mock_create, mock_exec):
        cmd, cname = wrap_claude_cmd("claude 'hi'", "/workdir", label="impl")
        assert cmd == "docker exec ..."
        assert cname == f"{CONTAINER_PREFIX}impl"
        mock_create.assert_called_once()
        mock_exec.assert_called_once()

    @patch("pm_core.container.build_exec_cmd", return_value="docker exec ...")
    @patch("pm_core.container.create_container", return_value="cid123")
    @patch("pm_core.container.load_container_config",
           return_value=ContainerConfig())
    @patch("pm_core.container.is_container_mode_enabled", return_value=True)
    def test_wraps_with_session_tag(self, mock_enabled, mock_config,
                                     mock_create, mock_exec):
        cmd, cname = wrap_claude_cmd("claude 'hi'", "/workdir", label="impl",
                                     session_tag="repo-abc12345", pr_id="pr-1")
        assert cname == f"{CONTAINER_PREFIX}repo-abc12345-impl"
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["session_tag"] == "repo-abc12345"
        assert call_kwargs["pr_id"] == "pr-1"

    @patch("pm_core.container.build_exec_cmd", return_value="docker exec ...")
    @patch("pm_core.container.create_container", return_value="cid")
    @patch("pm_core.container.load_container_config",
           return_value=ContainerConfig())
    @patch("pm_core.container.is_container_mode_enabled", return_value=True)
    def test_passes_extra_mounts(self, mock_enabled, mock_config,
                                  mock_create, mock_exec):
        ro = {Path("/repo"): "/repo"}
        rw = {Path("/scratch"): "/scratch"}
        wrap_claude_cmd("claude", "/w", extra_ro_mounts=ro, extra_rw_mounts=rw)

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["extra_ro_mounts"] == ro
        assert call_kwargs["extra_rw_mounts"] == rw


class TestRemoveContainer:
    @patch("pm_core.container._run_runtime")
    def test_removes_container(self, mock_docker):
        # After rm, remove_container polls with inspect until the container is gone.
        # Simulate inspect returning non-zero (container gone) on first poll.
        mock_docker.return_value.returncode = 1
        remove_container("test-container")
        # First call is rm -f, second is inspect (wait loop)
        mock_docker.assert_any_call(
            "rm", "-f", "test-container", check=False, timeout=30)
        mock_docker.assert_any_call(
            "inspect", "test-container", check=False, timeout=5)


class TestCleanupContainers:
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_cleans_up_qa_containers(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(
            returncode=0,
            stdout="pm-qa-pr1-loop1-s1\npm-qa-pr1-loop1-s2\n",
        )

        count = cleanup_qa_containers("pr1", "loop1")
        assert count == 2
        assert mock_rm.call_count == 2
        mock_rm.assert_any_call("pm-qa-pr1-loop1-s1")
        mock_rm.assert_any_call("pm-qa-pr1-loop1-s2")

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_cleans_up_session_tagged_qa_containers(self, mock_docker, mock_rm):
        """Cleanup finds session-tagged containers."""
        mock_docker.side_effect = [
            MagicMock(returncode=0,
                      stdout="pm-repo-abc-qa-pr1-loop1-s1\npm-repo-abc-qa-pr1-loop1-s2\n"),
            MagicMock(returncode=0, stdout=""),
        ]
        count = cleanup_qa_containers("pr1", "loop1", session_tag="repo-abc")
        assert count == 2

    @patch("pm_core.container._run_runtime")
    def test_no_containers(self, mock_docker):
        mock_docker.return_value = MagicMock(returncode=0, stdout="")
        count = cleanup_qa_containers("pr1", "loop1")
        assert count == 0

    @patch("pm_core.container._run_runtime")
    def test_docker_failure(self, mock_docker):
        mock_docker.return_value = MagicMock(returncode=1, stdout="")
        count = cleanup_qa_containers("pr1", "loop1")
        assert count == 0

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_cleanup_session(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(
            returncode=0,
            stdout="pm-repo-abc-impl-pr1\npm-repo-abc-qa-pr1-loop1-s1\n",
        )
        count = cleanup_session_containers("repo-abc")
        assert count == 2
        mock_rm.assert_any_call("pm-repo-abc-impl-pr1")

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_cleanup_all(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(
            returncode=0,
            stdout="pm-impl-abc\npm-review-def\npm-qa-pr1-x-s1\n",
        )

        count = cleanup_all_containers()
        assert count == 3
        assert mock_rm.call_count == 3


class TestIntegration:
    """Test that session launchers integrate with container wrapping."""

    def test_container_mode_branches_exist(self):
        """Verify that the container launcher function is importable."""
        from pm_core.qa_loop import _launch_scenarios_in_containers
        from pm_core.qa_loop import _launch_scenarios_in_tmux
        assert callable(_launch_scenarios_in_containers)
        assert callable(_launch_scenarios_in_tmux)

    @patch("pm_core.container.is_container_mode_enabled", return_value=False)
    def test_disabled_by_default(self, mock_enabled):
        from pm_core.container import is_container_mode_enabled
        assert is_container_mode_enabled() is False

    def test_wrap_claude_cmd_importable_from_expected_sites(self):
        """Verify wrap_claude_cmd is accessible where it's used."""
        from pm_core.container import wrap_claude_cmd
        assert callable(wrap_claude_cmd)



class TestBuildGitSetupScript:
    def test_safe_directory_always_set(self):
        script = _build_git_setup_script()
        assert "safe.directory" in script

    def test_push_proxy_installs_wrapper(self):
        script = _build_git_setup_script(has_push_proxy=True)
        assert "/home/pm/.local/bin/git" in script
        assert "push-proxy" in script
        assert "REAL_GIT=/usr/bin/git" in script

    def test_no_proxy_no_wrapper(self):
        script = _build_git_setup_script(has_push_proxy=False)
        assert ".local/bin/git" not in script

    def test_no_credentials_in_script(self):
        """Push proxy approach should never embed credentials."""
        script = _build_git_setup_script(has_push_proxy=True)
        assert "token" not in script.lower()
        assert "password" not in script.lower()
        assert "credential" not in script.lower()

    def test_shebang_at_start_of_wrapper(self):
        """Wrapper script shebang must be at column 0 for kernel to recognise it."""
        script = _build_git_setup_script(has_push_proxy=True)
        # The heredoc content must have #!/bin/sh at column 0 (after the
        # newline following the WRAPEOF marker)
        assert "\n#!/bin/sh\n" in script

    def test_host_workdir_baked_into_wrapper(self):
        """host_workdir is baked as HOST_WORKDIR and included in request JSON."""
        script = _build_git_setup_script(has_push_proxy=True,
                                         host_workdir="/home/user/repo")
        assert 'HOST_WORKDIR="/home/user/repo"' in script
        assert '"workdir"' in script

    def test_host_workdir_produces_valid_json_in_request(self):
        """The request= line must assemble valid JSON — no stray quote after args_json.

        The shell fragment looks like:
            request='{"cmd": "'$escaped_cmd'", "args": '$args_json', "workdir": "...'
        After $args_json (an array like ["origin"]), the next shell literal must
        start with ', "workdir"' NOT '", "workdir"' — the latter would produce
        ["origin"]", "workdir" which is invalid JSON.
        """
        script = _build_git_setup_script(has_push_proxy=True,
                                         host_workdir="/some/clone")
        # Bad pattern: stray " after $args_json (produces invalid JSON)
        bad = "$args_json'\", \"workdir\""
        # Good pattern: no stray " (produces valid JSON)
        good = "$args_json', \"workdir\""
        assert bad not in script, "Stray '\"' after $args_json produces invalid JSON"
        assert good in script, "Expected '$args_json', \"workdir\"' pattern"

    def test_no_host_workdir_omits_workdir_field(self):
        """Without host_workdir, no HOST_WORKDIR or workdir field in request."""
        script = _build_git_setup_script(has_push_proxy=True)
        assert "HOST_WORKDIR" not in script
        assert '"workdir"' not in script


@patch("pm_core.container._get_runtime", return_value="docker")
@patch("pm_core.container.container_is_running", return_value=False)
class TestCreateContainerPushProxy:
    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.push_proxy.start_push_proxy",
           return_value="/tmp/pm-push-proxy-test/push.sock")
    @patch("pm_core.container._resolve_claude_binary", return_value=None)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_starts_proxy_and_mounts_socket(self, mock_docker, mock_rm,
                                             mock_bin, mock_proxy,
                                             mock_exists, _mock_running, _mock_runtime):
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"),
                             allowed_push_branch="pm/pr-123")

        mock_proxy.assert_called_once_with(
            "test", "/w", "pm/pr-123",
            session_tag=None, pr_id=None,
        )
        args_str = " ".join(mock_docker.call_args_list[0][0])
        assert "/tmp/pm-push-proxy-test:/run/pm-push-proxy" in args_str

    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.container._resolve_claude_binary", return_value=None)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_no_proxy_without_branch(self, mock_docker, mock_rm,
                                      mock_bin, mock_exists, _mock_running, _mock_runtime):
        """No push proxy started if no allowed_push_branch specified."""
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"))

        args_str = " ".join(mock_docker.call_args_list[0][0])
        assert "push-proxy" not in args_str

    @patch("pm_core.container.image_exists", return_value=True)
    @patch("pm_core.push_proxy.start_push_proxy",
           return_value="/tmp/pm-push-proxy-test/push.sock")
    @patch("pm_core.container._resolve_claude_binary", return_value=None)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_entrypoint_has_wrapper(self, mock_docker, mock_rm,
                                     mock_bin, mock_proxy,
                                     mock_exists, _mock_running, _mock_runtime):
        """Container entrypoint installs the git push proxy wrapper."""
        mock_docker.return_value = MagicMock(stdout="id\n", returncode=0)
        config = ContainerConfig()

        with patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"),
                             allowed_push_branch="pm/pr-123")

        args = mock_docker.call_args_list[0][0]
        setup_script = args[-1]
        assert "/home/pm/.local/bin/git" in setup_script
        assert "REAL_GIT=/usr/bin/git" in setup_script

    @patch("pm_core.container.build_exec_cmd", return_value="docker exec ...")
    @patch("pm_core.container.create_container", return_value="cid")
    @patch("pm_core.container.load_container_config",
           return_value=ContainerConfig())
    @patch("pm_core.container.is_container_mode_enabled", return_value=True)
    def test_wrap_passes_branch(self, mock_enabled, mock_config,
                                 mock_create, mock_exec, _mock_running, _mock_runtime):
        wrap_claude_cmd("claude", "/w", label="impl",
                        allowed_push_branch="pm/pr-123")
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["allowed_push_branch"] == "pm/pr-123"

    @patch("pm_core.push_proxy.get_proxy_socket_path",
           return_value="/tmp/pm-push-proxy-x/push.sock")
    @patch("pm_core.container.build_exec_cmd", return_value="docker exec ...")
    @patch("pm_core.container.create_container", return_value="cid")
    @patch("pm_core.container.load_container_config",
           return_value=ContainerConfig())
    @patch("pm_core.container.is_container_mode_enabled", return_value=True)
    def test_wrap_passes_proxy_socket_to_exec(self, mock_enabled, mock_config,
                                               mock_create, mock_exec,
                                               mock_sock, _mock_running, _mock_runtime):
        wrap_claude_cmd("claude", "/w", label="impl",
                        allowed_push_branch="pm/pr-123")
        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs["proxy_socket_path"] == "/tmp/pm-push-proxy-x/push.sock"

    @patch("pm_core.push_proxy.get_proxy_socket_path",
           return_value="/tmp/pm-push-proxy-repo-abc-pr-1/push.sock")
    @patch("pm_core.container.build_exec_cmd", return_value="docker exec ...")
    @patch("pm_core.container.create_container", return_value="cid")
    @patch("pm_core.container.load_container_config",
           return_value=ContainerConfig())
    @patch("pm_core.container.is_container_mode_enabled", return_value=True)
    def test_shared_proxy_not_cleaned_inline(self, mock_enabled, mock_config,
                                              mock_create, mock_exec,
                                              mock_sock, _mock_running, _mock_runtime):
        """Shared proxies should NOT have their socket deleted by inline cleanup."""
        wrap_claude_cmd("claude", "/w", label="impl",
                        allowed_push_branch="pm/pr-123",
                        session_tag="repo-abc", pr_id="pr-1")
        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs["proxy_socket_path"] is None
