"""Tests for mcp_cocktail.sync module."""

from pathlib import Path
from mcp_cocktail.sync import merge_traps_config, push_domain_contributions
from mcp_cocktail.inbox import append_note


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
