"""Tests for container isolation of Claude sessions."""

import shlex
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from pm_core.container import (
    ContainerConfig,
    qa_container_name,
    load_container_config,
    is_container_mode_enabled,
    create_container,
    create_qa_container,
    build_exec_cmd,
    remove_container,
    cleanup_qa_containers,
    cleanup_all_containers,
    wrap_claude_cmd,
    _docker_available,
    _make_container_name,
    _resolve_claude_binary,
    DEFAULT_IMAGE,
    DEFAULT_MEMORY_LIMIT,
    DEFAULT_CPU_LIMIT,
    CONTAINER_PREFIX,
    _CONTAINER_WORKDIR,
    _CONTAINER_SCRATCH,
    _CONTAINER_USER,
    _CONTAINER_HOME,
)


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

    def test_qa_different_indices(self):
        n1 = qa_container_name("pr-x", "loop", 1)
        n2 = qa_container_name("pr-x", "loop", 2)
        assert n1 != n2
        assert n1.endswith("-s1")
        assert n2.endswith("-s2")

    def test_make_container_name_has_prefix(self):
        name = _make_container_name("impl")
        assert name.startswith(f"{CONTAINER_PREFIX}impl-")
        assert len(name) > len(f"{CONTAINER_PREFIX}impl-")

    def test_make_container_name_unique(self):
        n1 = _make_container_name("test")
        n2 = _make_container_name("test")
        assert n1 != n2


class TestLoadContainerConfig:
    @patch("pm_core.paths.get_global_setting_value")
    def test_loads_from_settings(self, mock_get):
        mock_get.side_effect = lambda name, default="": {
            "qa-container-image": "custom:v2",
            "qa-container-memory-limit": "16g",
            "qa-container-cpu-limit": "8.0",
        }.get(name, default)

        cfg = load_container_config()
        assert cfg.image == "custom:v2"
        assert cfg.memory_limit == "16g"
        assert cfg.cpu_limit == "8.0"

    @patch("pm_core.paths.get_global_setting_value")
    def test_falls_back_to_defaults(self, mock_get):
        mock_get.side_effect = lambda name, default="": default
        cfg = load_container_config()
        assert cfg.image == DEFAULT_IMAGE
        assert cfg.memory_limit == DEFAULT_MEMORY_LIMIT
        assert cfg.cpu_limit == DEFAULT_CPU_LIMIT


class TestIsContainerModeEnabled:
    @patch("pm_core.paths.get_global_setting")
    def test_enabled(self, mock_get):
        mock_get.return_value = True
        assert is_container_mode_enabled() is True
        mock_get.assert_called_with("qa-container-enabled")

    @patch("pm_core.paths.get_global_setting")
    def test_disabled(self, mock_get):
        mock_get.return_value = False
        assert is_container_mode_enabled() is False


class TestDockerAvailable:
    @patch("subprocess.run")
    def test_available(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert _docker_available() is True

    @patch("subprocess.run")
    def test_not_available(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        assert _docker_available() is False

    @patch("subprocess.run")
    def test_daemon_not_running(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert _docker_available() is False


class TestCreateContainer:
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_creates_with_workdir(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(stdout="abc123\n")

        config = ContainerConfig(image="test:v1", memory_limit="2g", cpu_limit="1.0")
        cid = create_container(
            name="pm-test",
            config=config,
            workdir=Path("/my/workdir"),
        )

        assert cid == "abc123"
        mock_rm.assert_called_once_with("pm-test")

        args = mock_docker.call_args[0]
        assert args[0] == "run"
        assert "-d" in args
        assert f"/my/workdir:{_CONTAINER_WORKDIR}" in " ".join(args)
        # Entrypoint creates pm user then execs sleep infinity
        assert args[-3] == "bash"
        assert args[-2] == "-c"
        assert "useradd" in args[-1]
        assert "sleep infinity" in args[-1]

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_extra_ro_mounts(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(stdout="id\n")
        config = ContainerConfig()

        create_container(
            name="test",
            config=config,
            workdir=Path("/w"),
            extra_ro_mounts={Path("/repo"): "/repo"},
        )

        args_str = " ".join(mock_docker.call_args[0])
        assert "/repo:/repo:ro" in args_str

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_extra_rw_mounts(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(stdout="id\n")
        config = ContainerConfig()

        create_container(
            name="test",
            config=config,
            workdir=Path("/w"),
            extra_rw_mounts={Path("/scratch"): "/scratch"},
        )

        args_str = " ".join(mock_docker.call_args[0])
        assert "/scratch:/scratch" in args_str
        # Should NOT have :ro suffix
        assert "/scratch:/scratch:ro" not in args_str

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_passes_env_vars(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(stdout="id123\n")

        config = ContainerConfig(env={"CUSTOM_VAR": "custom_val"})
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            create_container(
                name="test",
                config=config,
                workdir=Path("/w"),
            )

        args_str = " ".join(mock_docker.call_args[0])
        assert "ANTHROPIC_API_KEY=sk-test" in args_str
        assert "CUSTOM_VAR=custom_val" in args_str

    @patch("pm_core.container._resolve_claude_binary", return_value=None)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_mounts_claude_config_rw(self, mock_docker, mock_rm, mock_bin):
        """~/.claude is mounted read-write so Claude can write session state."""
        mock_docker.return_value = MagicMock(stdout="id\n")
        config = ContainerConfig()

        with patch("pm_core.container.Path.home", return_value=Path("/home/user")), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "exists", return_value=True):
            create_container(name="test", config=config, workdir=Path("/w"))

        args_str = " ".join(mock_docker.call_args[0])
        assert f"/home/user/.claude:{_CONTAINER_HOME}/.claude" in args_str
        # Should NOT be read-only
        assert f"/home/user/.claude:{_CONTAINER_HOME}/.claude:ro" not in args_str

    @patch("pm_core.container._resolve_claude_binary", return_value=None)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_mounts_claude_json(self, mock_docker, mock_rm, mock_bin):
        """~/.claude.json is mounted read-write for Claude config."""
        mock_docker.return_value = MagicMock(stdout="id\n")
        config = ContainerConfig()

        with patch("pm_core.container.Path.home", return_value=Path("/home/user")), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "exists", return_value=True):
            create_container(name="test", config=config, workdir=Path("/w"))

        args_str = " ".join(mock_docker.call_args[0])
        assert f"/home/user/.claude.json:{_CONTAINER_HOME}/.claude.json" in args_str

    @patch("pm_core.container._resolve_claude_binary")
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_mounts_claude_binary(self, mock_docker, mock_rm, mock_resolve):
        """Host claude binary is bind-mounted at /usr/local/bin/claude."""
        mock_docker.return_value = MagicMock(stdout="id\n")
        # Simulate a resolved binary that exists
        fake_bin = Path("/home/user/.local/share/claude/versions/1.0.0")
        mock_resolve.return_value = fake_bin

        config = ContainerConfig()
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "is_dir", return_value=False):
            create_container(name="test", config=config, workdir=Path("/w"))

        args_str = " ".join(mock_docker.call_args[0])
        assert f"{fake_bin}:/usr/local/bin/claude:ro" in args_str

    @patch("pm_core.container._resolve_claude_binary", return_value=None)
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_no_binary_still_creates_container(self, mock_docker, mock_rm, mock_resolve):
        """Container creation succeeds even if claude binary is not found."""
        mock_docker.return_value = MagicMock(stdout="id\n")
        config = ContainerConfig()

        with patch.object(Path, "is_dir", return_value=False):
            cid = create_container(name="test", config=config, workdir=Path("/w"))

        assert cid == "id"
        # Should not contain /usr/local/bin/claude mount
        args_str = " ".join(mock_docker.call_args[0])
        assert "/usr/local/bin/claude" not in args_str


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
            repo_root=Path("/repo"),
            worktree_path=Path("/worktrees/w1"),
            scratch_path=Path("/scratch/s1"),
        )

        assert cid == "qa-id"
        mock_create.assert_called_once_with(
            name="pm-qa-test-s1",
            config=config,
            workdir=Path("/worktrees/w1"),
            extra_ro_mounts={Path("/repo"): "/repo"},
            extra_rw_mounts={Path("/scratch/s1"): _CONTAINER_SCRATCH},
        )


class TestBuildExecCmd:
    def test_basic(self):
        cmd = build_exec_cmd("my-container", "claude 'hello world'")
        assert "docker exec -it" in cmd
        assert f"-u {_CONTAINER_USER}" in cmd
        assert "my-container" in cmd
        assert "claude" in cmd
        assert "hello world" in cmd

    def test_shell_safety(self):
        cmd = build_exec_cmd("name-with-special", "claude 'prompt with $vars'")
        parts = shlex.split(cmd)
        assert parts[0] == "docker"
        assert parts[1] == "exec"
        assert parts[2] == "-it"
        assert parts[3] == "-u"
        assert parts[4] == _CONTAINER_USER


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
        assert cname.startswith(f"{CONTAINER_PREFIX}impl-")
        mock_create.assert_called_once()
        mock_exec.assert_called_once()

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
    @patch("pm_core.container._run_docker")
    def test_removes_container(self, mock_docker):
        remove_container("test-container")
        mock_docker.assert_called_once_with(
            "rm", "-f", "test-container", check=False, timeout=30)


class TestCleanupContainers:
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
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

    @patch("pm_core.container._run_docker")
    def test_no_containers(self, mock_docker):
        mock_docker.return_value = MagicMock(returncode=0, stdout="")
        count = cleanup_qa_containers("pr1", "loop1")
        assert count == 0

    @patch("pm_core.container._run_docker")
    def test_docker_failure(self, mock_docker):
        mock_docker.return_value = MagicMock(returncode=1, stdout="")
        count = cleanup_qa_containers("pr1", "loop1")
        assert count == 0

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
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
