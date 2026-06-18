"""Windows platform backend — wraps ctypes windll.user32 calls."""

from __future__ import annotations

from ctypes import POINTER, Structure, byref, windll, wintypes

from naicha_mouse.platform_.base import CursorPos, PlatformBackend, WindowRect
from naicha_mouse.platform_.keys import modifier_key_codes, typing_key_codes


class _WinRect(Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _WinPoint(Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class WindowsBackend(PlatformBackend):
    """Windows implementation using ctypes / user32."""

    def __init__(self) -> None:
        self._user32 = windll.user32
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowRect.argtypes = [wintypes.HWND, POINTER(_WinRect)]
        self._user32.GetWindowRect.restype = wintypes.BOOL
        self._user32.GetCursorPos.argtypes = [POINTER(_WinPoint)]
        self._user32.GetCursorPos.restype = wintypes.BOOL
        self._user32.GetAsyncKeyState.argtypes = [wintypes.INT]
        self._user32.GetAsyncKeyState.restype = wintypes.SHORT

    # ── keyboard ───────────────────────────────────────────
    def is_key_pressed(self, key_code: int) -> bool:
        return bool(self._user32.GetAsyncKeyState(key_code) & 0x8000)

    def is_key_tapped(self, key_code: int) -> bool:
        return bool(self._user32.GetAsyncKeyState(key_code) & 0x0001)

    def get_typing_key_codes(self) -> tuple[int, ...]:
        return typing_key_codes()

    def get_modifier_key_codes(self) -> tuple[int, ...]:
        return modifier_key_codes()

    def is_modifier_down(self) -> bool:
        return any(
            self._user32.GetAsyncKeyState(code) & 0x8000
            for code in self.get_modifier_key_codes()
        )

    # ── window / cursor ────────────────────────────────────
    def get_foreground_window_rect(self, own_window_id: int) -> WindowRect | None:
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd or hwnd == own_window_id:
            return None
        rect = _WinRect()
        if not self._user32.GetWindowRect(hwnd, byref(rect)):
            return None
        return WindowRect(left=rect.left, top=rect.top, right=rect.right, bottom=rect.bottom)

    def get_cursor_position(self) -> CursorPos | None:
        point = _WinPoint()
        if not self._user32.GetCursorPos(byref(point)):
            return None
        return CursorPos(x=point.x, y=point.y)
