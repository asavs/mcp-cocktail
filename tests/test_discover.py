"""Tests for mcp_cocktail.discover module."""

from mcp_cocktail.discover import (
    discover_domain_arms,
    build_discovered_manifest,
    generate_agentic_discover_task,
)


def test_discover_domain_arms():
    candidates = discover_domain_arms("unity")
    assert len(candidates) >= 1
    ids = [c.id for c in candidates]
    assert "unity-cli" in ids


def test_build_discovered_manifest():
    candidates = discover_domain_arms("postgres")
    manifest = build_discovered_manifest("postgres", candidates)
    assert manifest["name"] == "postgres-ecosystem"
    assert len(manifest["arms"]) >= 1
    assert manifest["arms"][0]["id"] == "postgres-cli"


def test_generate_agentic_discover_task():
    task_spec = generate_agentic_discover_task("docker")
    assert task_spec["agent"] == "scout"
    assert "Discover_Ecosystem_docker" in task_spec["name"]
    assert "docker" in task_spec["task"]
