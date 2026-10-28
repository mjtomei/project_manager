"""``pm set list`` must show what pm actually uses for an unset boolean."""

from click.testing import CliRunner

from pm_core.cli import cli


def _listed(name):
    out = CliRunner().invoke(cli, ["set", "list"]).output
    return next(line.split() for line in out.splitlines()
                if line.split() and line.split()[0] == name)


def test_unset_qa_verify_pass_lists_as_its_default_on(tmp_path, monkeypatch):
    """Unset qa-verify-pass verifies PASSes, so it must not list as off."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from pm_core.qa_loop import _is_verification_enabled
    assert _is_verification_enabled()
    assert _listed("qa-verify-pass") == ["qa-verify-pass", "on", "(default)"]
    assert _listed("hide-assist") == ["hide-assist", "off", "(default)"]


def test_set_booleans_list_their_stored_value(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    assert runner.invoke(cli, ["set", "qa-verify-pass", "off"]).exit_code == 0
    assert runner.invoke(cli, ["set", "hide-assist", "on"]).exit_code == 0
    assert _listed("qa-verify-pass") == ["qa-verify-pass", "off"]
    assert _listed("hide-assist") == ["hide-assist", "on"]
    assert runner.invoke(cli, ["set", "qa-verify-pass", "on"]).exit_code == 0
    assert _listed("qa-verify-pass") == ["qa-verify-pass", "on", "(default)"]
