"""Tests for mcp_cocktail.installer module."""

import json
import os
from pathlib import Path
import re

import pytest

import mcp_cocktail
from mcp_cocktail.config import CocktailConfig, TrapsConfig
from mcp_cocktail.installer import (
    DEFAULT_HOOK_MATCHER,
    PRESETS_DIR,
    available_presets,
    install_hook,
    preset_dir,
    provision_tree,
    uninstall_hook,
    load_json_file,
    detect_current_active_harness,
)


def _harness_would_invoke(matcher: str, tool_name: str) -> bool:
    """Model the harness-level tool-name filter applied before the hook runs."""
    if matcher in ("*", ""):
        return True
    return bool(re.match(f"(?:{matcher})$", tool_name))


def test_installed_matcher_reaches_every_shipped_rule(tmp_path: Path):
    """Every tool a rule declares must survive the harness matcher.

    Regression: the old default 'Bash|PowerShell|mcp__.*' stranded the P1
    manifest-while-running rule, whose tool_matcher declares Edit and Write.
    """
    settings_file = tmp_path / ".claude" / "settings.json"
    install_hook(harness="claude", target_path=str(settings_file))
    matcher = load_json_file(settings_file)["hooks"]["PreToolUse"][0]["matcher"]

    traps = TrapsConfig.load(PRESETS_DIR / "unity" / "traps.json")
    assert traps.rules, "expected the Unity preset to ship rules"

    for tool in ("Bash", "PowerShell", "Edit", "Write", "mcp__UnityMCP__manage_gameobject"):
        assert _harness_would_invoke(matcher, tool), f"{matcher!r} strands rules targeting {tool}"


def test_default_matcher_subscribes_to_all_tools():
    assert DEFAULT_HOOK_MATCHER == "*"


def test_provision_tree_merges_into_an_existing_directory(tmp_path: Path):
    """Field log V1: setup guarded its copytree on `not dst.exists()`, so a
    workspace that already had a tools/ directory -- any real game repo --
    silently received nothing, leaving the declared setup_script undelivered
    and coplay-mcp unstartable."""
    src = tmp_path / "preset" / "tools"
    (src / "git").mkdir(parents=True)
    (src / "three-way-setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (src / "git" / "setup.sh").write_text("preset version\n", encoding="utf-8")

    dst = tmp_path / "workspace" / "tools"
    dst.mkdir(parents=True)
    (dst / "the-users-own-script.sh").write_text("do not touch\n", encoding="utf-8")
    (dst / "git").mkdir()
    (dst / "git" / "setup.sh").write_text("the user's version\n", encoding="utf-8")

    copied, skipped = provision_tree(src, dst)

    assert "three-way-setup.sh" in copied
    assert (dst / "three-way-setup.sh").exists()
    # Never clobber, and say which files were left alone.
    assert skipped == ["git/setup.sh"]
    assert (dst / "git" / "setup.sh").read_text(encoding="utf-8") == "the user's version\n"
    assert (dst / "the-users-own-script.sh").read_text(encoding="utf-8") == "do not touch\n"


def test_provision_tree_handles_a_missing_source(tmp_path: Path):
    assert provision_tree(tmp_path / "nope", tmp_path / "dst") == ([], [])


def test_provisioning_delivers_every_declared_setup_script(tmp_path: Path):
    """The end state V1 is really about: after provisioning, every arm that
    names a setup_script must actually have one on disk."""
    preset_root = PRESETS_DIR / "unity"
    workspace = tmp_path / "workspace"
    (workspace / "tools").mkdir(parents=True)  # pre-existing, as in a real repo

    provision_tree(preset_root / "tools", workspace / "tools")

    for arm in CocktailConfig.load(preset_root / "manifest.json").arms:
        if arm.setup_script:
            assert (workspace / arm.setup_script).exists(), (
                f"{arm.id}: setup_script '{arm.setup_script}' not provisioned"
            )


def test_presets_resolve_relative_to_the_package_not_the_repo():
    """Regression: presets resolved as `Path(__file__).parents[2] / "examples"`,
    which is the repo root only under an editable install. Under a real
    `pip install` that path lands beside site-packages and `setup --preset`
    could never find a preset. Anchoring inside the package is the fix, so
    assert the anchor rather than the happy path -- the happy path passes in
    this checkout either way."""
    package_root = Path(mcp_cocktail.__file__).resolve().parent
    assert package_root in PRESETS_DIR.parents or PRESETS_DIR.parent == package_root


def test_every_shipped_preset_carries_a_manifest():
    presets = available_presets()
    assert presets, "expected at least one shipped preset"
    for name in presets:
        assert (PRESETS_DIR / name / "manifest.json").exists(), f"preset '{name}' ships no manifest"


def test_preset_dir_resolves_only_a_shipped_name():
    assert preset_dir("unity") == PRESETS_DIR / "unity"
    assert preset_dir("no-such-domain") is None
    # A preset id names one directory. Anything that walks is not an id.
    assert preset_dir("../presets/unity") is None
    assert preset_dir("unity/tools") is None


def test_pyproject_packages_every_preset_file():
    """The bug this guards is silent: a preset file that no package-data glob
    matches is simply absent from the wheel, and only shows up as a broken
    `setup --preset` on a user's machine. Match the shipped tree against the
    declared globs here, where adding an unpackaged file fails immediately."""
    tomllib = pytest.importorskip("tomllib")

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with open(pyproject, "rb") as fh:
        patterns = tomllib.load(fh)["tool"]["setuptools"]["package-data"]["mcp_cocktail"]

    package_root = PRESETS_DIR.parent
    packaged = {p for pattern in patterns for p in package_root.glob(pattern) if p.is_file()}

    for shipped in PRESETS_DIR.rglob("*"):
        if not shipped.is_file() or "__pycache__" in shipped.parts:
            continue
        assert shipped in packaged, (
            f"{shipped.relative_to(package_root).as_posix()} matches no package-data glob "
            f"-- it will be missing from the wheel"
        )


def _cocktail_hooks(settings_file: Path) -> list[dict]:
    return [
        hook
        for entry in load_json_file(settings_file)["hooks"]["PreToolUse"]
        for hook in entry.get("hooks", [])
        if "cocktail check" in hook.get("command", "")
    ]


def test_install_replaces_a_hook_carried_by_a_different_matcher(tmp_path: Path):
    """Field log Finding 6: setup appended a second PreToolUse entry instead of
    repairing the first, and every tool call produced two identical reminders."""
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash|PowerShell|Edit|Write|mcp__unity-editor-mcp__.*",
                            "hooks": [{"type": "command", "command": "python -m mcp_cocktail check"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    ok, msg = install_hook(harness="claude", target_path=str(settings_file))
    assert ok
    assert "Replaced 1 existing" in msg
    assert len(_cocktail_hooks(settings_file)) == 1, "duplicate hook -> duplicate context injection"


def test_install_preserves_unrelated_hooks(tmp_path: Path):
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "Bash", "hooks": [{"type": "command", "command": "some-other-linter"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    install_hook(harness="claude", target_path=str(settings_file))
    commands = [
        h.get("command")
        for entry in load_json_file(settings_file)["hooks"]["PreToolUse"]
        for h in entry.get("hooks", [])
    ]
    assert "some-other-linter" in commands
    assert len(_cocktail_hooks(settings_file)) == 1


def test_traps_path_is_portable(tmp_path: Path, monkeypatch):
    """An absolute path bakes one machine's drive layout into the file the
    README tells teams to commit."""
    monkeypatch.chdir(tmp_path)
    traps = tmp_path / ".agents" / "traps.json"
    traps.parent.mkdir(parents=True)
    traps.write_text("{}", encoding="utf-8")

    settings_file = tmp_path / ".claude" / "settings.json"
    install_hook(harness="claude", target_path=str(settings_file), custom_traps=str(traps))

    command = _cocktail_hooks(settings_file)[0]["command"]
    assert command == 'mcp-cocktail check --traps "$CLAUDE_PROJECT_DIR/.agents/traps.json"'
    assert str(tmp_path) not in command


def test_traps_path_outside_project_stays_absolute(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "shared" / "traps.json"
    external.parent.mkdir(parents=True)
    external.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(project)

    settings_file = project / ".claude" / "settings.json"
    install_hook(harness="claude", target_path=str(settings_file), custom_traps=str(external))
    assert str(external) in _cocktail_hooks(settings_file)[0]["command"]


def test_install_and_uninstall_hook(tmp_path: Path):
    settings_file = tmp_path / ".claude" / "settings.json"

    ok, msg = install_hook(harness="claude", target_path=str(settings_file))
    assert ok
    assert settings_file.exists()

    data = load_json_file(settings_file)
    assert "hooks" in data
    assert "PreToolUse" in data["hooks"]
    pre = data["hooks"]["PreToolUse"]
    assert len(pre) == 1
    assert pre[0]["hooks"][0]["command"] == "mcp-cocktail check"

    # Second install - idempotent update
    ok2, msg2 = install_hook(harness="claude", target_path=str(settings_file))
    assert ok2
    data2 = load_json_file(settings_file)
    assert len(data2["hooks"]["PreToolUse"][0]["hooks"]) == 1

    # Uninstall
    ok3, msg3 = uninstall_hook(harness="claude", target_path=str(settings_file))
    assert ok3
    data3 = load_json_file(settings_file)
    assert len(data3["hooks"]["PreToolUse"]) == 0


def _clear_harness_env(monkeypatch):
    """Drop every harness signal so a test asserts on what it sets, not on the
    machine it runs on."""
    for name in list(os.environ):
        if name.startswith("CODEX_") or name in ("OMP_SESSION_ID", "OMP_DIR", "CLAUDE_SESSION_ID"):
            monkeypatch.delenv(name, raising=False)


def test_detect_current_active_harness(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OMP_SESSION_ID", "sess_123")
    assert detect_current_active_harness(tmp_path) == "omp"

    monkeypatch.delenv("OMP_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess_456")
    assert detect_current_active_harness(tmp_path) == "claude"


def test_codex_session_is_not_detected_as_claude(tmp_path: Path, monkeypatch):
    """Field report: `setup` run inside a Codex session auto-selected Claude
    and wrote .claude/settings.json -- a guardrail the running harness will
    never invoke, reported as installed."""
    _clear_harness_env(monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    assert detect_current_active_harness(tmp_path) == "codex"


def test_a_live_claude_session_outranks_codex_config_on_the_machine(tmp_path: Path, monkeypatch):
    """A machine that has run several harnesses keeps all their config
    forever; only one of them is executing. The session id is the fact about
    now, so it has to win."""
    _clear_harness_env(monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess_456")
    assert detect_current_active_harness(tmp_path) == "claude"


def test_codex_workspace_directory_is_detected(tmp_path: Path, monkeypatch):
    _clear_harness_env(monkeypatch)
    (tmp_path / ".codex").mkdir()
    assert detect_current_active_harness(tmp_path) == "codex"

    # ...but a Claude workspace in the same tree still wins, matching the
    # existing .omp/.claude precedence.
    (tmp_path / ".claude").mkdir()
    assert detect_current_active_harness(tmp_path) == "claude"


def test_installing_for_codex_writes_nothing_and_says_why(tmp_path: Path, monkeypatch):
    """Refusing loudly beats a silent fallback. The failure mode being closed
    is the one the field log named twice: a configured hook, a passing
    selftest, and zero protection."""
    _clear_harness_env(monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.chdir(tmp_path)

    ok, msg = install_hook(harness="auto")

    assert ok is False
    assert not (tmp_path / ".claude").exists(), "wrote a Claude hook during a Codex session"
    assert "Nothing was written" in msg
    assert "mcp_servers" in msg, "the message must name the route that does work"
    assert "--harness claude" in msg


def test_uninstalling_for_codex_does_not_strip_another_harness(tmp_path: Path, monkeypatch):
    """get_harness_settings_path falls through to .claude for unknown names,
    so an unguarded codex uninstall would remove a Claude hook and report it
    as Codex's."""
    _clear_harness_env(monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.chdir(tmp_path)

    settings = tmp_path / ".claude" / "settings.json"
    install_hook(harness="claude", target_path=str(settings))
    before = settings.read_text(encoding="utf-8")

    ok, msg = uninstall_hook(harness="auto")

    assert ok is False
    assert settings.read_text(encoding="utf-8") == before
    assert "Nothing was removed" in msg


def test_explicit_settings_path_still_overrides_the_codex_refusal(tmp_path: Path, monkeypatch):
    """--settings names a destination outright; the refusal exists to stop a
    silent *guess*, not to override an instruction."""
    _clear_harness_env(monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.chdir(tmp_path)

    target = tmp_path / "explicit" / "settings.json"
    ok, _ = install_hook(harness="auto", target_path=str(target))

    assert ok is True
    assert target.exists()
