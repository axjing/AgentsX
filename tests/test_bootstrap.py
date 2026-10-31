"""Tests for Windows console UTF-8 encoding bootstrap."""

import sys
from unittest.mock import MagicMock, patch

from agentsx.bootstrap import _bootstrap


def test_bootstrap_current_platform() -> None:
    """Test bootstrap executes without errors on the running platform."""
    _bootstrap()


def test_bootstrap_non_windows() -> None:
    """Test bootstrap exits early on non-Windows platforms."""
    with patch.object(sys, "platform", "linux"):
        _bootstrap()


def test_bootstrap_windows_simulation() -> None:
    """Test bootstrap configuration when platform is win32."""
    fake_stream = MagicMock()
    fake_stream.encoding = "cp1252"

    with patch.object(sys, "platform", "win32"):
        with patch.object(sys, "stdout", fake_stream):
            _bootstrap()
            fake_stream.reconfigure.assert_called_with(
                encoding="utf-8",
                errors="replace",
            )
