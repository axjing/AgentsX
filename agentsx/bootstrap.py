"""Windows console UTF-8 encoding bootstrap.

Import this module early (before any I/O) to ensure the standard streams
use UTF-8 on Windows, where the default console code page is often a
legacy MBCS codec (cp949, cp1252, …) that raises ``UnicodeEncodeError``
for common characters like em-dashes (U+2014) or code symbols.

This is a no-op on POSIX systems.

Usage::

    try:
        import agentsx.bootstrap  # noqa: F401
    except ModuleNotFoundError:
        pass  # Graceful fallback during partial installs.

Why this matters:
    - Python 3.12+ has ``sys.stdlib_encoding`` but it does not affect
      existing stream wrappers.
    - ``PYTHONIOENCODING=utf-8`` must be set before the process starts.
    - On Windows, ``sys.stdout.reconfigure(encoding="utf-8")`` works but
      must be called explicitly — the interpreter does not do it.
    - The Windows console requires ``SetConsoleOutputCP(65001)`` for
      subprocess heredocs to render correctly.

See https://github.com/NousResearch/hermes-agent/issues/44873 for the
original problem report that inspired this approach.
"""

import sys


def _bootstrap() -> None:
    if sys.platform != "win32":
        return

    import ctypes  # noqa: PLC0415
    import os  # noqa: PLC0415

    # Set the Windows console code page to UTF-8 (CP 65001).
    # This ensures that subprocess heredocs and direct console writes
    # render Unicode correctly.  Must be called before any console I/O.
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except (OSError, AttributeError):
        # kernel32 may be unavailable in some Windows environments
        # (e.g., Windows Nano Server, some container runtimes).
        pass

    # Reconfigure standard streams to use UTF-8 with error replacement.
    # ``errors='replace'`` ensures that un-encodable characters produce
    # ``?`` rather than crashing the process with UnicodeEncodeError.
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        # Skip if already UTF-8 or surrogate-aware.
        encoding = getattr(stream, "encoding", None) or "utf-8"
        normalized = encoding.lower().replace("-", "")
        if normalized in ("utf8", "utf8surrogateescape"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, AttributeError, ValueError):
            # Stream may be non-interactive (redirected to file, pipe)
            # or already wrapped by a test harness.
            pass

    # Set environment hint for subprocesses spawned via os.system or
    # subprocess without explicit encoding configuration.
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")


_bootstrap()
