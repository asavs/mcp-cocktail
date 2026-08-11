"""Tests for mcp_cocktail.sync module."""

import json
from pathlib import Path

from mcp_cocktail.config import TrapsConfig, resolve_traps_path
from mcp_cocktail.sync import merge_traps_config, pull_domain_rules, push_domain_contributions
from mcp_cocktail.inbox import append_note


REMOTE = {
    "version": "1.0",
    "domain": "unity",
    "rules": [{"id": "remote-rule", "message": "TRAP from registry"}],
}


def _pulled_rule_ids(root: Path) -> list[str]:
    return [r.id for r in TrapsConfig.load(root).rules]


def test_pull_writes_where_the_loader_reads(tmp_path: Path, monkeypatch):
    """Regression: sync wrote root/traps.json while the loader preferred
    .agents/traps.json, so pulled rules were silently never evaluated."""
    monkeypatch.setattr("mcp_cocktail.sync.fetch_remote_domain_traps", lambda domain: REMOTE)

    agents_traps = tmp_path / ".agents" / "traps.json"
    agents_traps.parent.mkdir(parents=True)
    agents_traps.write_text(
        json.dumps({"version": "1.0", "domain": "unity", "rules": [{"id": "local-rule", "message": "local"}]}),
        encoding="utf-8",
    )

    ok, _ = pull_domain_rules("unity", root_dir=tmp_path)
    assert ok
    assert not (tmp_path / "traps.json").exists(), "pull resurrected the pre-.agents path"
    assert _pulled_rule_ids(tmp_path) == ["local-rule", "remote-rule"]


def test_pull_honours_legacy_layout(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mcp_cocktail.sync.fetch_remote_domain_traps", lambda domain: REMOTE)

    legacy = tmp_path / "traps.json"
    legacy.write_text(json.dumps({"version": "1.0", "domain": "unity", "rules": []}), encoding="utf-8")

    ok, _ = pull_domain_rules("unity", root_dir=tmp_path)
    assert ok
    assert not (tmp_path / ".agents").exists(), "pull migrated a legacy workspace unasked"
    assert _pulled_rule_ids(tmp_path) == ["remote-rule"]


def test_pull_into_empty_workspace_uses_canonical_path(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mcp_cocktail.sync.fetch_remote_domain_traps", lambda domain: REMOTE)

    ok, _ = pull_domain_rules("unity", root_dir=tmp_path)
    assert ok
    assert resolve_traps_path(tmp_path) == tmp_path / ".agents" / "traps.json"
    assert _pulled_rule_ids(tmp_path) == ["remote-rule"]


def test_merge_traps_config():
    local = {
        "version": "1.0",
        "domain": "test",
        "rules": [{"id": "r1", "message": "Rule 1"}]
    }
    remote = {
        "version": "1.0",
        "domain": "test",
        "rules": [
            {"id": "r1", "message": "Rule 1 Duplicate"},
            {"id": "r2", "message": "Rule 2 Remote"}
        ]
    }

    merged = merge_traps_config(local, remote)
    assert len(merged["rules"]) == 2
    rule_ids = [r["id"] for r in merged["rules"]]
    assert "r1" in rule_ids
    assert "r2" in rule_ids


def test_push_domain_contributions(tmp_path: Path):
    inbox = tmp_path / "docs" / "findings-inbox.md"
    append_note("unity command silently rejects name=X argument", cost_mins=20, inbox_path=inbox)

    ok, msg = push_domain_contributions("unity", root_dir=tmp_path)
    assert ok
    bundle_path = tmp_path / "docs" / "sync-contribution-bundle-unity.json"
    assert bundle_path.exists()
