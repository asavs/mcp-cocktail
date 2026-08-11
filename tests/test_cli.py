"""Tests for mcp_cocktail.cli module."""

import json
from pathlib import Path
from unittest.mock import patch
from mcp_cocktail.cli import main


def test_cli_init(tmp_path: Path):
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        res = main(["init", "--name", "my-benchmark"])
        assert res == 0
        assert (tmp_path / ".agents" / "manifest.json").exists()
        assert (tmp_path / ".agents" / "traps.json").exists()


def test_cli_setup_preset(tmp_path: Path):
    settings_file = tmp_path / ".claude" / "settings.json"
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        res = main(["setup", "--preset", "unity", "--settings", str(settings_file)])
        assert res == 0
        assert (tmp_path / ".agents" / "manifest.json").exists()
        assert (tmp_path / ".agents" / "traps.json").exists()
        assert settings_file.exists()


def test_cli_check_selftest():
    preset = Path(__file__).resolve().parents[1] / "examples" / "unity" / ".agents" / "traps.json"
    assert main(["check", "--selftest", "--traps", str(preset)]) == 0


def test_cli_check_selftest_fails_when_nothing_is_deployed(tmp_path: Path):
    """The engine passing is not evidence that any rules are loaded."""
    assert main(["check", "--selftest", "--traps", str(tmp_path)]) == 1


def _write_manifest(root: Path, arms: list[dict]) -> None:
    (root / ".agents").mkdir(parents=True, exist_ok=True)
    (root / ".agents" / "manifest.json").write_text(
        json.dumps({"name": "t", "description": "", "arms": arms}), encoding="utf-8"
    )


def test_cli_doctor_reports_without_asserting_by_default(tmp_path: Path, monkeypatch):
    """A manifest is a survey of competing arms -- the Unity preset lists 11
    and nobody has all 11 -- so a bare `doctor` must not fail because some arm
    is down. A check that always fails gets tuned out."""
    monkeypatch.chdir(tmp_path)
    _write_manifest(tmp_path, [
        {"id": "absent", "name": "Absent", "type": "cli", "command": "nonexistent_binary_xyz_123"}
    ])

    assert main(["doctor"]) == 0


def test_cli_doctor_require_fails_on_a_down_arm(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _write_manifest(tmp_path, [
        {"id": "up", "name": "Up", "type": "cli", "command": "python"},
        {"id": "absent", "name": "Absent", "type": "cli", "command": "nonexistent_binary_xyz_123"},
    ])

    assert main(["doctor", "--require", "up"]) == 0
    assert main(["doctor", "--require", "up", "--require", "absent"]) == 1
    assert "--require absent" in capsys.readouterr().out


def test_cli_doctor_require_unknown_arm_cannot_be_evaluated(tmp_path: Path, monkeypatch, capsys):
    """A typo must not read as a satisfied requirement."""
    monkeypatch.chdir(tmp_path)
    _write_manifest(tmp_path, [{"id": "up", "name": "Up", "type": "cli", "command": "python"}])

    assert main(["doctor", "--require", "uup"]) == 2
    out = capsys.readouterr().out
    assert "no such arm" in out and "Known arms: up" in out


def test_cli_doctor_rejects_an_unconfigured_workspace(tmp_path: Path, monkeypatch):
    """Field log Finding 4: no manifest reported '0/0 arms READY' and exit 0,
    so `doctor && proceed` sailed through a workspace with nothing set up."""
    monkeypatch.chdir(tmp_path)
    assert main(["doctor"]) == 2


def test_cli_note(tmp_path: Path):
    inbox_file = tmp_path / "docs" / "findings-inbox.md"
    res = main(["note", "Testing CLI note", "--cost", "5", "--inbox", str(inbox_file)])
    assert res == 0
    assert inbox_file.exists()


def test_cli_run(tmp_path: Path):
    manifest = {
        "name": "cli-test",
        "description": "test",
        "arms": [{"id": "a1", "name": "Arm 1", "type": "cli"}],
    }
    (tmp_path / ".agents").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".agents" / "manifest.json").write_text(str(manifest).replace("'", '"'), encoding="utf-8")

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        res = main(["run", "T-100", "Execute test task"])
        assert res == 0
        assert (tmp_path / "docs" / "trials" / "T-100" / "brief-a1.md").exists()
