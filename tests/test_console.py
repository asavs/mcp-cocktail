"""Tests for mcp_cocktail.console and the entrypoints that depend on it."""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_cocktail.console import ensure_utf8_streams

# Every non-ASCII string the package can print to a console.
EM_DASH = "—"

ENTRYPOINT_ENCODINGS = ["cp437", "cp1252", "ascii"]


def test_ensure_utf8_streams_survives_streams_without_reconfigure():
    """Must never take down the command it is protecting."""
    ensure_utf8_streams(io.StringIO())  # no reconfigure attribute
    ensure_utf8_streams()  # real streams, possibly already captured


@pytest.mark.parametrize("encoding", ENTRYPOINT_ENCODINGS)
def test_selftest_warning_survives_a_non_utf8_console(tmp_path: Path, encoding: str):
    """Field log V3: on cp437 the em dash raised UnicodeEncodeError and the
    WARNING line was lost entirely while the exit code still said 1 --
    reproducing the exact silent inertness Finding 5 exists to eliminate."""
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_cocktail", "check", "--selftest"],
        cwd=tmp_path,
        capture_output=True,
        env={**dict(__import__("os").environ), "PYTHONIOENCODING": encoding},
    )

    assert proc.returncode == 1
    stdout = proc.stdout.decode("utf-8")  # must not raise: bare cp1252 \x97 would
    assert "nothing is protected" in stdout
    assert EM_DASH in stdout
    assert b"UnicodeEncodeError" not in proc.stderr


@pytest.mark.parametrize("encoding", ENTRYPOINT_ENCODINGS)
def test_doctor_unconfigured_message_survives_a_non_utf8_console(tmp_path: Path, encoding: str):
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_cocktail", "doctor"],
        cwd=tmp_path,
        capture_output=True,
        env={**dict(__import__("os").environ), "PYTHONIOENCODING": encoding},
    )

    assert proc.returncode == 2
    stdout = proc.stdout.decode("utf-8")
    assert "nothing was probed" in stdout
    assert b"UnicodeEncodeError" not in proc.stderr


def test_every_printing_module_imports_the_helper():
    """A new entrypoint that prints non-ASCII without calling the helper
    reintroduces V3. Catch it at the module level rather than per-string."""
    src = Path(__file__).resolve().parents[1] / "src" / "mcp_cocktail"

    for module in sorted(src.glob("*.py")):
        text = module.read_text(encoding="utf-8")
        prints_non_ascii = any(
            ord(char) > 127
            for line in text.splitlines()
            if "print(" in line
            for char in line
        )
        if prints_non_ascii:
            assert "ensure_utf8_streams" in text, (
                f"{module.name} prints non-ASCII but never calls ensure_utf8_streams()"
            )
