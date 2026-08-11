"""Tests for mcp_cocktail.cli module."""

import json
from pathlib import Path
from unittest.mock import patch
from mcp_cocktail.cli import main
from mcp_cocktail.doctor import ArmHealthResult
from mcp_cocktail.installer import PRESETS_DIR


def test_cli_init(tmp_path: Path):
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        res = main(["init", "--name", "my-benchmark"])
        assert res == 0
        assert (tmp_path / ".agents" / "manifest.json").exists()
        assert (tmp_path / ".agents" / "traps.json").exists()


def _health(*statuses):
    """Doctor results with the given statuses, for grading setup's exit code."""
    return [
        ArmHealthResult(f"arm{i}", f"Arm {i}", status, "canned", {})
        for i, status in enumerate(statuses)
    ]


def test_cli_setup_preset(tmp_path: Path):
    settings_file = tmp_path / ".claude" / "settings.json"
    with patch("pathlib.Path.cwd", return_value=tmp_path), \
            patch("mcp_cocktail.cli.run_doctor", return_value=_health("READY", "OFFLINE")):
        res = main(["setup", "--preset", "unity", "--settings", str(settings_file)])
        assert res == 0
        assert (tmp_path / ".agents" / "manifest.json").exists()
        assert (tmp_path / ".agents" / "traps.json").exists()
        assert settings_file.exists()


def test_cli_setup_does_not_report_ok_when_no_arm_is_ready(tmp_path: Path, capsys):
    """The green light cocktail exists to catch, in cocktail's own output.

    Every visible step succeeded -- files copied, hook installed -- over a
    doctor table reading 0/11 READY, and setup still printed [OK] and exited
    0. Copying files is not the outcome anyone ran setup for.
    """
    settings_file = tmp_path / ".claude" / "settings.json"
    with patch("pathlib.Path.cwd", return_value=tmp_path), \
            patch("mcp_cocktail.cli.run_doctor", return_value=_health("OFFLINE", "NOT_RUNNING")):
        assert main(["setup", "--preset", "unity", "--settings", str(settings_file)]) == 1

    out = capsys.readouterr().out
    assert "[OK]" not in out
    assert "0/2 arms are READY" in out
    # The provisioning that did land must not read as a total failure.
    assert (tmp_path / ".agents" / "manifest.json").exists()


def test_cli_setup_counts_assumed_ready_as_ready(tmp_path: Path):
    """ASSUMED_READY is in READY_STATUSES for --require; setup must agree."""
    settings_file = tmp_path / ".claude" / "settings.json"
    with patch("pathlib.Path.cwd", return_value=tmp_path), \
            patch("mcp_cocktail.cli.run_doctor", return_value=_health("ASSUMED_READY")):
        assert main(["setup", "--preset", "unity", "--settings", str(settings_file)]) == 0


def test_cli_setup_names_the_shipped_presets_when_one_is_unknown(tmp_path: Path, capsys):
    """A typo and an install that shipped no presets fail the same way from the
    user's side, so the message has to say which presets this install has."""
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        assert main(["setup", "--preset", "postgres"]) == 1

    out = capsys.readouterr().out
    assert "postgres" in out
    assert "unity" in out
    assert not (tmp_path / ".agents").exists(), "a failed setup left a partial workspace"


def test_cli_check_selftest():
    preset = PRESETS_DIR / "unity" / "traps.json"
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


def test_install_plan_prints_steps_for_a_named_arm(tmp_path: Path, capsys):
    with patch("pathlib.Path.cwd", return_value=tmp_path), \
            patch("mcp_cocktail.cli.run_doctor", return_value=_health("READY")):
        main(["setup", "--preset", "unity", "--settings", str(tmp_path / "s.json")])
        capsys.readouterr()
        assert main(["install", "hatayama-loop"]) == 0

    out = capsys.readouterr().out
    assert "npm install -g uloop-cli" in out
    assert "unity-cli-loop.git" in out, "the Unity-side package is half the install"
    assert "never executed" in out, "the plan must not read as something that ran"


def test_install_plan_rejects_an_unknown_arm(tmp_path: Path, capsys):
    with patch("pathlib.Path.cwd", return_value=tmp_path), \
            patch("mcp_cocktail.cli.run_doctor", return_value=_health("READY")):
        main(["setup", "--preset", "unity", "--settings", str(tmp_path / "s.json")])
        capsys.readouterr()
        assert main(["install", "not-an-arm"]) == 2

    assert "no such arm" in capsys.readouterr().out


def test_setup_does_not_offer_a_route_for_an_unresolved_arm(tmp_path: Path, capsys):
    """smithery-toolkit-mcp carries an `install` block that exists only to say
    the project could not be found. Listing it as obtainable would send someone
    to fetch a thing nobody could locate."""
    from mcp_cocktail.config import CocktailConfig

    preset = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    all_offline = [ArmHealthResult(a.id, a.name, "OFFLINE", "canned", {}) for a in preset.arms]

    with patch("pathlib.Path.cwd", return_value=tmp_path), \
            patch("mcp_cocktail.cli.run_doctor", return_value=all_offline):
        main(["setup", "--preset", "unity", "--settings", str(tmp_path / "s.json")])

    out = capsys.readouterr().out
    handoff = [ln for ln in out.splitlines() if "mcp-cocktail install " in ln]
    assert handoff, "expected an install handoff line"
    assert "smithery-toolkit-mcp" not in " ".join(handoff)
