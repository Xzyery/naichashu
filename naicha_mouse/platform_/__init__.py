"""Platform abstraction layer — auto-selects the correct backend."""

from __future__ import annotations

import platform as _platform

from naicha_mouse.platform_.base import CursorPos, PlatformBackend, WindowRect

_backend: PlatformBackend | None = None


def get_backend() -> PlatformBackend:
    """Return the cached platform backend, creating it on first call."""
    global _backend
    if _backend is None:
        system = _platform.system()
        if system == "Windows":
            from naicha_mouse.platform_.windows import WindowsBackend

            _backend = WindowsBackend()
        elif system == "Darwin":
            from naicha_mouse.platform_.macos import MacOSBackend

            _backend = MacOSBackend()
        else:
            raise RuntimeError(f"Unsupported platform: {system}")
    return _backend


__all__ = ["PlatformBackend", "WindowRect", "CursorPos", "get_backend"]
