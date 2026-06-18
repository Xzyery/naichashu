"""macOS platform backend — uses Quartz and AppKit."""

from __future__ import annotations

from naicha_mouse.platform_.base import CursorPos, PlatformBackend, WindowRect
from naicha_mouse.platform_.keys import modifier_key_codes, typing_key_codes

# Lazy imports — these only resolve on macOS where the packages exist.
# pyobjc-framework-Quartz and pyobjc-framework-AppKit must be installed.
import Quartz  # type: ignore[import-untyped]
from AppKit import NSEvent, NSWorkspace  # type: ignore[import-untyped]


class MacOSBackend(PlatformBackend):
    """macOS implementation using Quartz and AppKit."""

    def __init__(self) -> None:
        self._prev_key_states: dict[int, bool] = {}

    # ── keyboard ───────────────────────────────────────────
    def is_key_pressed(self, key_code: int) -> bool:
        """Check if a key is currently held using CGEventSourceKeyState (read-only, no accessibility permission needed)."""
        return bool(
            Quartz.CGEventSourceKeyState(
                Quartz.kCGEventSourceStateHIDSystemState,
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
        flags = Quartz.CGEventSourceFlagsState(
            Quartz.kCGEventSourceStateHIDSystemState
        )
        # kCGEventFlagMaskControl=1<<12, kCGEventFlagMaskAlternate=1<<19, kCGEventFlagMaskCommand=1<<20
        return bool(flags & (0x1000 | 0x80000 | 0x100000))

    # ── window / cursor ────────────────────────────────────
    def get_foreground_window_rect(self, own_window_id: int) -> WindowRect | None:
        """Get the foreground window bounds using NSWorkspace + CGWindowListCopyWindowInfo."""
        workspace = NSWorkspace.sharedWorkspace()
        active_app = workspace.frontmostApplication()
        if active_app is None:
            return None

        pid = active_app.processIdentifier()
        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
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
        point = NSEvent.mouseLocation()
        screen_height = Quartz.CGDisplayPixelsHigh(Quartz.CGMainDisplayID())
        return CursorPos(x=int(point.x), y=int(screen_height - point.y))
