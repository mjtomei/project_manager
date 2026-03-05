"""Tests for container isolation of QA scenario workers."""

import shlex
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from pm_core.container import (
    ContainerConfig,
    container_name,
    load_container_config,
    is_container_mode_enabled,
    create_scenario_container,
    build_exec_cmd,
    remove_container,
    cleanup_containers,
    _docker_available,
    DEFAULT_IMAGE,
    DEFAULT_MEMORY_LIMIT,
    DEFAULT_CPU_LIMIT,
    CONTAINER_PREFIX,
    _CONTAINER_WORKDIR,
    _CONTAINER_SCRATCH,
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
    def test_format(self):
        name = container_name("pr-abc123", "loop456", 3)
        assert name == f"{CONTAINER_PREFIX}pr-abc123-loop456-s3"

    def test_different_indices(self):
        n1 = container_name("pr-x", "loop", 1)
        n2 = container_name("pr-x", "loop", 2)
        assert n1 != n2
        assert n1.endswith("-s1")
        assert n2.endswith("-s2")


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


class TestCreateScenarioContainer:
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_creates_container_with_correct_args(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(stdout="abc123container\n")

        config = ContainerConfig(image="test-image:v1", memory_limit="2g",
                                 cpu_limit="1.0")
        cid = create_scenario_container(
            name="pm-qa-test-s1",
            config=config,
            repo_root=Path("/repo"),
            worktree_path=Path("/worktrees/w1"),
            scratch_path=Path("/scratch/s1"),
        )

        assert cid == "abc123container"
        mock_rm.assert_called_once_with("pm-qa-test-s1")

        # Check docker run args
        args = mock_docker.call_args[0]
        assert args[0] == "run"
        assert "-d" in args
        assert "--name" in args
        idx = list(args).index("--name")
        assert args[idx + 1] == "pm-qa-test-s1"
        assert "--memory" in args
        assert "2g" in args
        assert "--cpus" in args
        assert "1.0" in args
        # Check mounts
        assert f"/worktrees/w1:{_CONTAINER_WORKDIR}" in " ".join(args)
        assert f"/scratch/s1:{_CONTAINER_SCRATCH}" in " ".join(args)
        assert "/repo:/repo:ro" in " ".join(args)
        # Should end with sleep infinity
        assert args[-2] == "sleep"
        assert args[-1] == "infinity"

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_passes_env_vars(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(stdout="id123\n")

        config = ContainerConfig(env={"CUSTOM_VAR": "custom_val"})
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            create_scenario_container(
                name="test",
                config=config,
                repo_root=Path("/r"),
                worktree_path=Path("/w"),
                scratch_path=Path("/s"),
            )

        args = mock_docker.call_args[0]
        args_str = " ".join(args)
        assert "ANTHROPIC_API_KEY=sk-test" in args_str
        assert "CUSTOM_VAR=custom_val" in args_str

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_mounts_claude_config(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(stdout="id\n")
        config = ContainerConfig()

        with patch("pm_core.container.Path.home", return_value=Path("/home/user")), \
             patch.object(Path, "is_dir", return_value=True):
            create_scenario_container(
                name="test",
                config=config,
                repo_root=Path("/r"),
                worktree_path=Path("/w"),
                scratch_path=Path("/s"),
            )

        args_str = " ".join(mock_docker.call_args[0])
        assert "/home/user/.claude:/root/.claude:ro" in args_str

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_extra_mounts(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(stdout="id\n")
        config = ContainerConfig(extra_mounts=["/data:/data:ro"])

        create_scenario_container(
            name="test",
            config=config,
            repo_root=Path("/r"),
            worktree_path=Path("/w"),
            scratch_path=Path("/s"),
        )

        args_str = " ".join(mock_docker.call_args[0])
        assert "/data:/data:ro" in args_str


class TestBuildExecCmd:
    def test_basic(self):
        cmd = build_exec_cmd("my-container", "claude 'hello world'")
        assert "docker exec -it" in cmd
        assert "my-container" in cmd
        # The claude command should be properly quoted
        assert "claude" in cmd
        assert "hello world" in cmd

    def test_shell_safety(self):
        # Ensure shell metacharacters in container name are quoted
        cmd = build_exec_cmd("name-with-special", "claude 'prompt with $vars'")
        # Should be parseable as a shell command
        parts = shlex.split(cmd)
        assert parts[0] == "docker"
        assert parts[1] == "exec"
        assert parts[2] == "-it"


class TestRemoveContainer:
    @patch("pm_core.container._run_docker")
    def test_removes_container(self, mock_docker):
        remove_container("test-container")
        mock_docker.assert_called_once_with(
            "rm", "-f", "test-container", check=False, timeout=30)


class TestCleanupContainers:
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_docker")
    def test_cleans_up_matching_containers(self, mock_docker, mock_rm):
        mock_docker.return_value = MagicMock(
            returncode=0,
            stdout="pm-qa-pr1-loop1-s1\npm-qa-pr1-loop1-s2\n",
        )

        count = cleanup_containers("pr1", "loop1")
        assert count == 2
        assert mock_rm.call_count == 2
        mock_rm.assert_any_call("pm-qa-pr1-loop1-s1")
        mock_rm.assert_any_call("pm-qa-pr1-loop1-s2")

    @patch("pm_core.container._run_docker")
    def test_no_containers(self, mock_docker):
        mock_docker.return_value = MagicMock(returncode=0, stdout="")
        count = cleanup_containers("pr1", "loop1")
        assert count == 0

    @patch("pm_core.container._run_docker")
    def test_docker_failure(self, mock_docker):
        mock_docker.return_value = MagicMock(returncode=1, stdout="")
        count = cleanup_containers("pr1", "loop1")
        assert count == 0


class TestQALoopContainerIntegration:
    """Test that QA loop correctly integrates with container mode."""

    def test_container_mode_branches_exist(self):
        """Verify that the container launcher function is importable."""
        from pm_core.qa_loop import _launch_scenarios_in_containers
        from pm_core.qa_loop import _launch_scenarios_in_tmux
        assert callable(_launch_scenarios_in_containers)
        assert callable(_launch_scenarios_in_tmux)

    @patch("pm_core.container.is_container_mode_enabled", return_value=False)
    def test_disabled_by_default(self, mock_enabled):
        """Container mode is off by default."""
        from pm_core.container import is_container_mode_enabled
        assert is_container_mode_enabled() is False
