"""Tests for mcp_cocktail.weakness module (Bennett, 2023)."""

from mcp_cocktail.weakness import (
    compute_weakness_score,
    generalize_pattern,
    derive_weakest_rule,
)


def test_generalize_pattern():
    pat1 = generalize_pattern("- [2026-08-07] (cost: 15m) unity command ignores positional name=X")
    assert pat1 == r"\bunity\s+command\b"

    pat2 = generalize_pattern("eval top-level using directive CS1001")
    assert pat2 == r"\beval\s+top\b" or "eval" in pat2


def test_compute_weakness_score():
    sample_space = ["unity command --foo", "git status", "rm -rf /"]
    score = compute_weakness_score("Bash", r"\bunity\s+command\b", sample_space)
    assert score == 1 / 3


def test_derive_weakest_rule():
    rule = derive_weakest_rule("unity command silently drops positional parameters")
    assert rule.id.startswith("weakness-rule-")
    assert "TRAP (Weakness Optimized):" in rule.message
    assert "rsi-derived" in rule.tags
    assert "weakness-maximized" in rule.tags
