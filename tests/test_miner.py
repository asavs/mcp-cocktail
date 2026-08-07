"""Tests for mcp_cocktail.miner module."""

from mcp_cocktail.miner import detect_patterns


def test_detect_patterns():
    hits1 = detect_patterns(10, "uv not found in PATH; restart process")
    assert any(h.pattern_id == "P1" for h in hits1)

    hits2 = detect_patterns(20, "isReachable: false with isRunning: true; invented row")
    assert any(h.pattern_id == "P2" for h in hits2)

    hits3 = detect_patterns(30, "process never exits and command timed out")
    assert any(h.pattern_id == "P3" for h in hits3)

    hits4 = detect_patterns(40, "connected to server but exposed 0 tools")
    assert any(h.pattern_id == "P4" for h in hits4)

    hits5 = detect_patterns(50, "accepted component_properties but ignored write; left at default")
    assert any(h.pattern_id == "P5" for h in hits5)
