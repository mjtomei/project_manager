"""Tests for pm_core.cli.container — container CLI commands."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from pm_core.cli.container import (
    container_build,
    container_set,
    _build_container_build_prompt,
)


class TestBuildContainerBuildPrompt:
    """Tests for the prompt generation function."""

    def test_includes_project_name(self):
        prompt = _build_container_build_prompt(
            project_name="my-app",
            project_dir="/home/user/my-app",
            base_image="pm-dev:latest",
            image_tag="pm-project-my-app:latest",
        )
        assert '"my-app"' in prompt

    def test_includes_project_dir(self):
        prompt = _build_container_build_prompt(
            project_name="proj",
            project_dir="/home/user/proj",
            base_image="pm-dev:latest",
            image_tag="pm-project-proj:latest",
        )
        assert "/home/user/proj" in prompt

    def test_includes_base_image(self):
        prompt = _build_container_build_prompt(
            project_name="proj",
            project_dir="/w",
            base_image="custom:v2",
            image_tag="pm-project-proj:latest",
        )
        assert "custom:v2" in prompt
        assert "FROM custom:v2" in prompt

    def test_includes_image_tag(self):
        prompt = _build_container_build_prompt(
            project_name="proj",
            project_dir="/w",
            base_image="pm-dev:latest",
            image_tag="my-tag:v1",
        )
        assert "my-tag:v1" in prompt
        assert "docker build -t my-tag:v1" in prompt

    def test_includes_dockerfile_path(self):
        prompt = _build_container_build_prompt(
            project_name="proj",
            project_dir="/app",
            base_image="pm-dev:latest",
            image_tag="img:latest",
        )
        assert "Dockerfile.pm-project" in prompt

    def test_includes_pm_container_set(self):
        prompt = _build_container_build_prompt(
            project_name="proj",
            project_dir="/app",
            base_image="pm-dev:latest",
            image_tag="img:latest",
        )
        assert "pm container set image img:latest" in prompt

    def test_includes_dependency_file_types(self):
        prompt = _build_container_build_prompt(
            project_name="proj",
            project_dir="/app",
            base_image="pm-dev:latest",
            image_tag="img:latest",
        )
        assert "requirements.txt" in prompt
        assert "package.json" in prompt
        assert "Cargo.toml" in prompt
        assert "go.mod" in prompt
        assert "Gemfile" in prompt


class TestContainerBuildCommand:
    """Tests for the pm container build CLI command."""

    @patch("pm_core.cli.container._get_pm_session", return_value=None)
    @patch("pm_core.cli.container.state_root")
    @patch("pm_core.cli.container._build_container_build_prompt", return_value="test prompt")
    def test_exits_when_claude_not_found(self, mock_prompt, mock_root, mock_session):
        mock_root.return_value = Path("/fake/pm")

        with patch("pm_core.store.load", return_value={"project": {"name": "test"}}), \
             patch("pm_core.store.is_internal_pm_dir", return_value=True), \
             patch("pm_core.container.load_container_config",
                   return_value=MagicMock(image="pm-dev:latest")), \
             patch("pm_core.claude_launcher.find_claude", return_value=None):
            runner = CliRunner()
            result = runner.invoke(container_build, [])

        assert result.exit_code != 0
        assert "Claude CLI not found" in result.output

    @patch("pm_core.cli.container._get_pm_session", return_value=None)
    @patch("pm_core.cli.container.state_root")
    def test_uses_custom_tag(self, mock_root, mock_session):
        mock_root.return_value = Path("/fake/pm")

        with patch("pm_core.store.load", return_value={"project": {"name": "test"}}), \
             patch("pm_core.store.is_internal_pm_dir", return_value=True), \
             patch("pm_core.container.load_container_config",
                   return_value=MagicMock(image="pm-dev:latest")), \
             patch("pm_core.claude_launcher.find_claude", return_value=None):
            runner = CliRunner()
            result = runner.invoke(container_build, ["--tag", "custom:v1"])

        # Should show the prompt with our custom tag since claude isn't found
        assert "custom:v1" in result.output

    @patch("pm_core.cli.container._get_pm_session", return_value=None)
    @patch("pm_core.cli.container.state_root")
    def test_uses_custom_base(self, mock_root, mock_session):
        mock_root.return_value = Path("/fake/pm")

        with patch("pm_core.store.load", return_value={"project": {"name": "test"}}), \
             patch("pm_core.store.is_internal_pm_dir", return_value=True), \
             patch("pm_core.container.load_container_config",
                   return_value=MagicMock(image="pm-dev:latest")), \
             patch("pm_core.claude_launcher.find_claude", return_value=None):
            runner = CliRunner()
            result = runner.invoke(container_build, ["--base", "ubuntu:22.04"])

        assert "ubuntu:22.04" in result.output

    @patch("pm_core.cli.container._get_pm_session", return_value="pm-test-session")
    @patch("pm_core.cli.container.state_root")
    def test_launches_in_tmux_window(self, mock_root, mock_session):
        mock_root.return_value = Path("/fake/pm")

        with patch("pm_core.store.load", return_value={"project": {"name": "myproj"}}), \
             patch("pm_core.store.is_internal_pm_dir", return_value=True), \
             patch("pm_core.container.load_container_config",
                   return_value=MagicMock(image="pm-dev:latest")), \
             patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude"), \
             patch("pm_core.claude_launcher.build_claude_shell_cmd", return_value="claude --prompt test"), \
             patch("pm_core.tmux.session_exists", return_value=True), \
             patch("pm_core.tmux.find_window_by_name", return_value=None), \
             patch("pm_core.tmux.new_window") as mock_new_window, \
             patch("pm_core.tmux.set_shared_window_size"):
            runner = CliRunner()
            result = runner.invoke(container_build, [])

        assert result.exit_code == 0
        assert "Launched container build session" in result.output
        mock_new_window.assert_called_once()
        # Window name should be "container-build"
        assert mock_new_window.call_args[0][1] == "container-build"

    @patch("pm_core.cli.container._get_pm_session", return_value="pm-test-session")
    @patch("pm_core.cli.container.state_root")
    def test_switches_to_existing_window(self, mock_root, mock_session):
        mock_root.return_value = Path("/fake/pm")

        existing_win = {"index": 3, "name": "container-build", "id": "@5"}
        with patch("pm_core.store.load", return_value={"project": {"name": "myproj"}}), \
             patch("pm_core.store.is_internal_pm_dir", return_value=True), \
             patch("pm_core.container.load_container_config",
                   return_value=MagicMock(image="pm-dev:latest")), \
             patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude"), \
             patch("pm_core.claude_launcher.build_claude_shell_cmd", return_value="claude"), \
             patch("pm_core.tmux.session_exists", return_value=True), \
             patch("pm_core.tmux.find_window_by_name", return_value=existing_win), \
             patch("pm_core.tmux.select_window") as mock_select:
            runner = CliRunner()
            result = runner.invoke(container_build, [])

        assert result.exit_code == 0
        assert "Switched to existing window" in result.output
        mock_select.assert_called_once_with("pm-test-session", 3)

    @patch("pm_core.cli.container._get_pm_session", return_value=None)
    @patch("pm_core.cli.container.state_root")
    def test_default_tag_uses_project_name(self, mock_root, mock_session):
        mock_root.return_value = Path("/fake/pm")

        with patch("pm_core.store.load", return_value={"project": {"name": "cool-app"}}), \
             patch("pm_core.store.is_internal_pm_dir", return_value=True), \
             patch("pm_core.container.load_container_config",
                   return_value=MagicMock(image="pm-dev:latest")), \
             patch("pm_core.claude_launcher.find_claude", return_value=None):
            runner = CliRunner()
            result = runner.invoke(container_build, [])

        assert "pm-project-cool-app:latest" in result.output

    @patch("pm_core.cli.container._get_pm_session", return_value=None)
    @patch("pm_core.cli.container.state_root")
    def test_fallback_interactive_launch(self, mock_root, mock_session):
        mock_root.return_value = Path("/fake/pm")

        with patch("pm_core.store.load", return_value={"project": {"name": "proj"}}), \
             patch("pm_core.store.is_internal_pm_dir", return_value=True), \
             patch("pm_core.container.load_container_config",
                   return_value=MagicMock(image="pm-dev:latest")), \
             patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude"), \
             patch("pm_core.claude_launcher.build_claude_shell_cmd", return_value="claude"), \
             patch("pm_core.claude_launcher.launch_claude") as mock_launch:
            runner = CliRunner()
            result = runner.invoke(container_build, [])

        assert result.exit_code == 0
        assert "Launching Claude..." in result.output
        mock_launch.assert_called_once()
        call_kwargs = mock_launch.call_args
        assert call_kwargs[1]["session_key"] == "container:build"


class TestContainerSetRuntime:
    """Tests for runtime validation in pm container set."""

    def test_invalid_runtime_rejected(self):
        runner = CliRunner()
        result = runner.invoke(container_set, ["runtime", "nerdctl"])
        assert result.exit_code != 0
        assert "Error" in result.output

    @patch("pm_core.paths.set_global_setting_value")
    def test_valid_runtime_accepted(self, mock_set):
        runner = CliRunner()
        result = runner.invoke(container_set, ["runtime", "podman"])
        assert result.exit_code == 0
        assert "Set runtime = podman" in result.output
