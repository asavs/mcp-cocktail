"""Tests for mcp_cocktail.inbox module."""

from pathlib import Path
from mcp_cocktail.inbox import append_note, show_inbox


def test_append_and_show_note(tmp_path: Path):
    inbox_file = tmp_path / "docs" / "findings-inbox.md"

    p = append_note("Evaluated top-level using directives", cost_mins=15, inbox_path=inbox_file)
    assert p.exists()

    content = show_inbox(inbox_file)
    assert "(cost: 15m)" in content
    assert "Evaluated top-level using directives" in content

    append_note("Second finding without cost", inbox_path=inbox_file)
    content2 = show_inbox(inbox_file)
    assert "Second finding without cost" in content2
