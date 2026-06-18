"""Abstract base class for platform-specific OS interactions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowRect:
    """Normalised rectangle for any platform."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class CursorPos:
    """Cursor position in screen coordinates (origin top-left)."""

    x: int
    y: int


class PlatformBackend(ABC):
    """Abstract interface for platform-specific OS interactions."""

    @abstractmethod
    def is_key_pressed(self, key_code: int) -> bool:
        """Return True if the key identified by *key_code* is currently held down."""
        ...

    @abstractmethod
    def is_key_tapped(self, key_code: int) -> bool:
        """Return True if the key was tapped since the last poll (edge-triggered)."""
        ...

    @abstractmethod
    def get_typing_key_codes(self) -> tuple[int, ...]:
        """Return platform-specific key codes that count as 'typing'."""
        ...

    @abstractmethod
    def get_modifier_key_codes(self) -> tuple[int, ...]:
        """Return key codes for shortcut modifiers (Ctrl/Cmd, Alt, Win)."""
        ...

    @abstractmethod
    def is_modifier_down(self) -> bool:
        """Return True if any shortcut modifier key is held."""
        ...

    @abstractmethod
    def get_foreground_window_rect(self, own_window_id: int) -> WindowRect | None:
        """Return bounding rect of the foreground window (excluding *own_window_id*),
        or None if it cannot be determined."""
        ...

    @abstractmethod
    def get_cursor_position(self) -> CursorPos | None:
        """Return current cursor position in screen coordinates, or None."""
        ...

    @abstractmethod
    def is_process_running(self, process_name: str) -> bool:
        """Return True if a process with the given name is currently running."""
        ...

    @abstractmethod
    def get_foreground_app_name(self) -> str | None:
        """Return the name of the foreground application, or None if it cannot be determined."""
        ...
