"""Tests for mcp_cocktail.cli module."""

from pathlib import Path
from unittest.mock import patch
from mcp_cocktail.cli import main


def test_cli_init(tmp_path: Path):
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        res = main(["init", "--name", "my-benchmark"])
        assert res == 0
        assert (tmp_path / "mcp-cocktail.json").exists()
        assert (tmp_path / "traps.json").exists()


def test_cli_setup_preset(tmp_path: Path):
    settings_file = tmp_path / ".claude" / "settings.json"
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        res = main(["setup", "--preset", "unity", "--settings", str(settings_file)])
        assert res == 0
        assert (tmp_path / "mcp-cocktail.json").exists()
        assert (tmp_path / "traps.json").exists()
        assert settings_file.exists()


def test_cli_check_selftest():
    res = main(["check", "--selftest"])
    assert res == 0


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
    (tmp_path / "mcp-cocktail.json").write_text(str(manifest).replace("'", '"'), encoding="utf-8")

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        res = main(["run", "T-100", "Execute test task"])
        assert res == 0
        assert (tmp_path / "docs" / "trials" / "T-100" / "brief-arm-a1.md").exists()
