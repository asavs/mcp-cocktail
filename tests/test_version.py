import re
from pathlib import Path

from mcp_cocktail import __version__


def test_release_version_is_pep440_and_sourced_dynamically():
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:a\d+|b\d+|rc\d+)?", __version__)
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert 'version = {attr = "mcp_cocktail.__version__"}' in pyproject
    assert re.search(r'^version\s*=\s*"', pyproject, re.MULTILINE) is None
