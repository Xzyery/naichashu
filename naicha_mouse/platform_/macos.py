"""macOS platform backend — uses Quartz and AppKit."""

from __future__ import annotations

from typing import Any

from naicha_mouse.platform_.base import CursorPos, PlatformBackend, WindowRect
from naicha_mouse.platform_.keys import modifier_key_codes, typing_key_codes


def _import_quartz() -> Any:
    """Lazily import Quartz; raise a helpful error if pyobjc is not installed."""
    try:
        import Quartz  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "pyobjc-framework-Quartz is required on macOS. "
            "Install it with:  pip install pyobjc-framework-Quartz"
        ) from exc
    return Quartz


def _import_appkit() -> Any:
    """Lazily import AppKit (NSEvent, NSWorkspace)."""
    try:
        from AppKit import NSEvent, NSWorkspace  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "pyobjc-framework-Cocoa is required on macOS. "
            "Install it with:  pip install pyobjc-framework-Cocoa"
        ) from exc
    return NSEvent, NSWorkspace


class MacOSBackend(PlatformBackend):
    """macOS implementation using Quartz and AppKit."""

    def __init__(self) -> None:
        self._prev_key_states: dict[int, bool] = {}
        # Eagerly resolve the lazy imports so we fail fast if deps are missing
        self._Quartz = _import_quartz()
        self._NSEvent, self._NSWorkspace = _import_appkit()

    # ── keyboard ───────────────────────────────────────────
    def is_key_pressed(self, key_code: int) -> bool:
        """Check if a key is currently held using CGEventSourceKeyState (read-only, no accessibility permission needed)."""
        return bool(
            self._Quartz.CGEventSourceKeyState(
                self._Quartz.kCGEventSourceStateHIDSystemState,
                key_code,
            )
        )

    def is_key_tapped(self, key_code: int) -> bool:
        """Edge-detect up→down transition (macOS has no GetAsyncKeyState bit 0x0001 equivalent)."""
        currently_down = self.is_key_pressed(key_code)
        was_down = self._prev_key_states.get(key_code, False)
        self._prev_key_states[key_code] = currently_down
        return currently_down and not was_down

    def get_typing_key_codes(self) -> tuple[int, ...]:
        return typing_key_codes()

    def get_modifier_key_codes(self) -> tuple[int, ...]:
        return modifier_key_codes()

    def is_modifier_down(self) -> bool:
        """Check modifier flags via CGEventSourceFlagsState."""
        flags = self._Quartz.CGEventSourceFlagsState(
            self._Quartz.kCGEventSourceStateHIDSystemState
        )
        # kCGEventFlagMaskControl=1<<12, kCGEventFlagMaskAlternate=1<<19, kCGEventFlagMaskCommand=1<<20
        return bool(flags & (0x1000 | 0x80000 | 0x100000))

    # ── window / cursor ────────────────────────────────────
    def get_foreground_window_rect(self, own_window_id: int) -> WindowRect | None:
        """Get the foreground window bounds using NSWorkspace + CGWindowListCopyWindowInfo."""
        workspace = self._NSWorkspace.sharedWorkspace()
        active_app = workspace.frontmostApplication()
        if active_app is None:
            return None

        pid = active_app.processIdentifier()
        window_list = self._Quartz.CGWindowListCopyWindowInfo(
            self._Quartz.kCGWindowListOptionOnScreenOnly
            | self._Quartz.kCGWindowListExcludeDesktopElements,
            self._Quartz.kCGNullWindowID,
        )
        for window_info in window_list:
            if window_info.get("kCGWindowOwnerPID") == pid:
                bounds = window_info.get("kCGWindowBounds")
                if bounds:
                    return WindowRect(
                        left=int(bounds["X"]),
                        top=int(bounds["Y"]),
                        right=int(bounds["X"]) + int(bounds["Width"]),
                        bottom=int(bounds["Y"]) + int(bounds["Height"]),
                    )
        return None

    def get_cursor_position(self) -> CursorPos | None:
        """Get cursor position, converting from macOS bottom-left origin to Qt top-left origin."""
        point = self._NSEvent.mouseLocation()
        screen_height = self._Quartz.CGDisplayPixelsHigh(self._Quartz.CGMainDisplayID())
        return CursorPos(x=int(point.x), y=int(screen_height - point.y))
