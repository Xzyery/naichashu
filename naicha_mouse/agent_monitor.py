"""Agent state monitor — polls state file and detects Trae IDE process.

This module provides AgentStateMonitor, a pure-Python class (no PyQt5 dependency)
that reads the shared agent state file and detects Trae IDE via platform backend.
State changes are reported through a callback.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from naicha_mouse.constants import AGENT_STATE_TIMEOUT_SECONDS
from naicha_mouse.platform_ import get_backend
from naicha_mouse.resources import AGENT_HOOKS_DIR, AGENT_STATE_FILE

# ── Agent source identifiers ────────────────────────────────
SOURCE_CLAUDE_CODE = "claude_code"
SOURCE_CODEX_CLI = "codex_cli"
SOURCE_TRAE = "trae"

# ── State names ──────────────────────────────────────────────
STATE_IDLE = "idle"
STATE_THINKING = "thinking"
STATE_WORKING = "working"
STATE_COMPLETE = "complete"
STATE_WAITING = "waiting"
STATE_ERROR = "error"

# ── Hook events to install ───────────────────────────────────
CLAUDE_CODE_HOOK_EVENTS = [
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SubagentStop",
    "Notification",
    "SessionStart",
]

CODEX_CLI_HOOK_EVENTS = [
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SubagentStop",
    "PermissionRequest",
    "SessionStart",
]

# ── Config file paths ────────────────────────────────────────
CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CODEX_HOOKS_PATH = Path.home() / ".codex" / "hooks.json"

# Callback signature: (new_state: str, state_data: dict | None) -> None
StateCallback = Callable[[str, dict[str, Any] | None], None]


class AgentStateMonitor:
    """Monitors coding agent state via file polling and process detection."""

    def __init__(
        self,
        on_state_change: StateCallback,
        trae_detection_enabled: bool = False,
    ) -> None:
        self._on_state_change = on_state_change
        self._trae_detection_enabled = trae_detection_enabled
        self._current_state = STATE_IDLE
        self._current_data: dict[str, Any] | None = None
        self._last_mtime: float = 0.0

    # ── Public API ──────────────────────────────────────────

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def current_data(self) -> dict[str, Any] | None:
        return self._current_data

    @property
    def trae_detection_enabled(self) -> bool:
        return self._trae_detection_enabled

    @trae_detection_enabled.setter
    def trae_detection_enabled(self, value: bool) -> None:
        self._trae_detection_enabled = value

    def poll(self) -> None:
        """Check for state changes. Called periodically by the host timer.

        Priority: hook state file > Trae process detection.
        """
        new_state = STATE_IDLE
        new_data: dict[str, Any] | None = None

        # 1. Read hook state file
        file_state, file_data = self._read_state_file()
        if file_state != STATE_IDLE:
            new_state = file_state
            new_data = file_data

        # 2. Trae detection (only if no active hook state)
        if new_state == STATE_IDLE and self._trae_detection_enabled:
            trae_state = self._detect_trae_state()
            if trae_state is not None:
                new_state = trae_state
                new_data = {"source": SOURCE_TRAE, "state": trae_state}

        # 3. Notify on change
        if new_state != self._current_state:
            self._current_state = new_state
            self._current_data = new_data
            self._on_state_change(new_state, new_data)

    # ── State file reading ──────────────────────────────────

    def _read_state_file(self) -> tuple[str, dict[str, Any] | None]:
        """Read and parse the agent state file. Returns (state, data) or (idle, None)."""
        path = AGENT_STATE_FILE
        if not path.exists():
            return STATE_IDLE, None

        # Skip re-reading if file hasn't been modified
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return STATE_IDLE, None

        if mtime == self._last_mtime:
            # File unchanged; but still check for staleness
            if self._current_data and self._current_state != STATE_IDLE:
                ts = self._current_data.get("timestamp", 0)
                if time.time() - ts > AGENT_STATE_TIMEOUT_SECONDS:
                    self._last_mtime = 0.0  # Reset so we re-read next time
                    return STATE_IDLE, None
            return self._current_state, self._current_data

        self._last_mtime = mtime

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return STATE_IDLE, None

        if not isinstance(data, dict):
            return STATE_IDLE, None

        # Check staleness
        ts = data.get("timestamp", 0)
        if not isinstance(ts, (int, float)) or time.time() - ts > AGENT_STATE_TIMEOUT_SECONDS:
            return STATE_IDLE, None

        state = data.get("state", STATE_IDLE)
        if state not in (STATE_IDLE, STATE_THINKING, STATE_WORKING,
                         STATE_COMPLETE, STATE_WAITING, STATE_ERROR):
            return STATE_IDLE, None

        return state, data

    # ── Trae detection ──────────────────────────────────────

    def _detect_trae_state(self) -> str | None:
        """Detect Trae IDE state via process monitoring. Returns None if not applicable."""
        try:
            backend = get_backend()
            if not backend.is_process_running("Trae"):
                return None
            fg_app = backend.get_foreground_app_name()
            if fg_app and "Trae" in fg_app:
                return STATE_WORKING
            return STATE_IDLE
        except Exception:
            return None

    # ── Hook installation ───────────────────────────────────

    def _ensure_hook_script(self) -> Path:
        """Copy agent_hook.py to ~/.naicha_mouse/hooks/ and return the path."""
        AGENT_HOOKS_DIR.mkdir(parents=True, exist_ok=True)
        dest = AGENT_HOOKS_DIR / "agent_hook.py"

        # Find source: bundled next to this module or in the package
        source = Path(__file__).resolve().parent / "hooks" / "agent_hook.py"
        if not source.exists():
            # Fallback: try from resources
            from naicha_mouse.resources import RESOURCE_DIR
            source = RESOURCE_DIR / "naicha_mouse" / "hooks" / "agent_hook.py"

        if source.exists() and (not dest.exists() or source.stat().st_mtime > dest.stat().st_mtime):
            shutil.copy2(source, dest)

        return dest

    def _build_hook_command(self, source: str) -> str:
        """Build the hook command string for the given agent source."""
        python_path = sys.executable
        hook_script = AGENT_HOOKS_DIR / "agent_hook.py"
        if sys.platform == "win32":
            return f'set NAICHA_AGENT_SOURCE={source} && "{python_path}" "{hook_script}"'
        return f'NAICHA_AGENT_SOURCE={source} "{python_path}" "{hook_script}"'

    def install_claude_code_hooks(self) -> bool:
        """Install hooks into Claude Code's settings.json. Returns True on success."""
        try:
            self._ensure_hook_script()
            command = self._build_hook_command(SOURCE_CLAUDE_CODE)
            return self._install_hooks_into_config(
                config_path=CLAUDE_SETTINGS_PATH,
                events=CLAUDE_CODE_HOOK_EVENTS,
                command=command,
            )
        except Exception:
            return False

    def uninstall_claude_code_hooks(self) -> bool:
        """Remove naicha hooks from Claude Code's settings.json. Returns True on success."""
        try:
            return self._uninstall_hooks_from_config(CLAUDE_SETTINGS_PATH)
        except Exception:
            return False

    def is_claude_code_hooks_installed(self) -> bool:
        """Check if naicha hooks are present in Claude Code's settings."""
        return self._check_hooks_installed(CLAUDE_SETTINGS_PATH)

    def install_codex_cli_hooks(self) -> bool:
        """Install hooks into Codex CLI's hooks.json. Returns True on success."""
        try:
            self._ensure_hook_script()
            command = self._build_hook_command(SOURCE_CODEX_CLI)
            return self._install_hooks_into_config(
                config_path=CODEX_HOOKS_PATH,
                events=CODEX_CLI_HOOK_EVENTS,
                command=command,
            )
        except Exception:
            return False

    def uninstall_codex_cli_hooks(self) -> bool:
        """Remove naicha hooks from Codex CLI's hooks.json. Returns True on success."""
        try:
            return self._uninstall_hooks_from_config(CODEX_HOOKS_PATH)
        except Exception:
            return False

    def is_codex_cli_hooks_installed(self) -> bool:
        """Check if naicha hooks are present in Codex CLI's config."""
        return self._check_hooks_installed(CODEX_HOOKS_PATH)

    # ── Config file manipulation ────────────────────────────

    def _read_config(self, config_path: Path) -> dict[str, Any]:
        """Read a JSON config file, returning an empty dict if it doesn't exist."""
        if not config_path.exists():
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_config(self, config_path: Path, data: dict[str, Any]) -> bool:
        """Write a JSON config file atomically. Returns True on success."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            tmp_fd, tmp_path = None, None
            try:
                tmp_fd, tmp_path = tempfile.mkstemp(
                    dir=str(config_path.parent), suffix=".json"
                )
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                os.replace(tmp_path, str(config_path))
                return True
            except OSError:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                return False
        except Exception:
            return False

    def _is_naicha_hook(self, hook_entry: Any) -> bool:
        """Check if a hook entry is one of ours (by checking the command string)."""
        if isinstance(hook_entry, dict):
            cmd = hook_entry.get("command", "")
            return "agent_hook.py" in cmd
        return False

    def _install_hooks_into_config(
        self,
        config_path: Path,
        events: list[str],
        command: str,
    ) -> bool:
        """Add naicha hook entries to a config file for the given events."""
        data = self._read_config(config_path)
        hooks = data.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            hooks = {}
            data["hooks"] = hooks

        new_entry = {"type": "command", "command": command}

        for event in events:
            entries = hooks.get(event, [])
            if not isinstance(entries, list):
                entries = []
            # Check if our hook is already there
            if any(self._is_naicha_hook(e) for e in entries):
                # Update the command in case Python path changed
                for i, e in enumerate(entries):
                    if self._is_naicha_hook(e) and isinstance(e, dict):
                        entries[i] = new_entry
                        break
            else:
                entries.append(new_entry)
            hooks[event] = entries

        return self._write_config(config_path, data)

    def _uninstall_hooks_from_config(self, config_path: Path) -> bool:
        """Remove all naicha hook entries from a config file."""
        data = self._read_config(config_path)
        if not data:
            return True  # Nothing to remove

        hooks = data.get("hooks", {})
        if not isinstance(hooks, dict):
            return True

        changed = False
        for event, entries in list(hooks.items()):
            if not isinstance(entries, list):
                continue
            filtered = [e for e in entries if not self._is_naicha_hook(e)]
            if len(filtered) != len(entries):
                changed = True
                if filtered:
                    hooks[event] = filtered
                else:
                    del hooks[event]

        if changed:
            # Clean up empty hooks dict
            if not hooks:
                del data["hooks"]
            return self._write_config(config_path, data)
        return True

    def _check_hooks_installed(self, config_path: Path) -> bool:
        """Check if any naicha hooks are present in the config file."""
        data = self._read_config(config_path)
        hooks = data.get("hooks", {})
        if not isinstance(hooks, dict):
            return False
        for entries in hooks.values():
            if isinstance(entries, list) and any(self._is_naicha_hook(e) for e in entries):
                return True
        return False
