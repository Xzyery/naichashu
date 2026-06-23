"""Cross-platform key-code mapping for typing detection."""

from __future__ import annotations

import platform as _platform


def typing_key_codes() -> tuple[int, ...]:
    """Return key codes that count as 'typing' for the current platform."""
    system = _platform.system()
    if system == "Windows":
        # Windows virtual key codes (original TYPING_KEYS)
        return tuple(
            list(range(0x30, 0x3A))   # 0-9
            + list(range(0x41, 0x5B))  # A-Z
            + list(range(0x60, 0x6A))  # Numpad 0-9
            + [
                0x08, 0x09, 0x0D, 0x10, 0x20, 0x2E,
                0xE5, 0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF,
                0xC0, 0xE2, 0xDB, 0xDC, 0xDD, 0xDE,
            ]
        )
    if system == "Darwin":
        # macOS Carbon virtual key codes
        return tuple(
            list(range(0x00, 0x1E))   # ANSI keys (A-Z layout)
            + [0x24, 0x30, 0x31]       # Return, Tab, Space
            + list(range(0x52, 0x5C))  # Numpad 0-9
            + [0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F]  # Punctuation keys
        )
    raise RuntimeError(f"Unsupported platform: {system}")


def modifier_key_codes() -> tuple[int, ...]:
    """Return key codes for shortcut modifiers on the current platform."""
    system = _platform.system()
    if system == "Windows":
        return (0x11, 0x12, 0x5B, 0x5C)  # VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN
    if system == "Darwin":
        return (0x3A, 0x3B, 0x3D, 0x3E)  # VK_Option, VK_Control, VK_RightCmd, VK_Function
    raise RuntimeError(f"Unsupported platform: {system}")
