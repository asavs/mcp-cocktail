"""Shared console encoding setup for mcp-cocktail entrypoints.

Every command that prints non-ASCII must call `ensure_utf8_streams()` before
its first write. Windows consoles default to cp1252 (and CI runners sometimes
to cp437 or ascii), where an em dash either raises UnicodeEncodeError or is
written as a lone \\x97 byte that is not valid UTF-8 -- silently corrupting
captured logs. File I/O is unaffected; those paths already pass
encoding="utf-8" explicitly.

This lives in its own module so a new entrypoint has one obvious thing to
call, rather than a four-line idiom to remember to copy.
"""

from __future__ import annotations

import sys
from typing import IO, Any


def ensure_utf8_streams(*streams: IO[Any]) -> None:
    """Reconfigure the given streams (default: stdout, stderr, stdin) to UTF-8.

    Never raises: a stream that cannot be reconfigured -- already detached, or
    replaced by a test harness with something that has no reconfigure() -- is
    skipped. Failing to set an encoding must not take down the command.
    """
    targets = streams or (sys.stdout, sys.stderr, sys.stdin)

    for stream in targets:
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass
