"""Agent state monitor — polls state file and detects Trae IDE process.

This module provides AgentStateMonitor, a pure-Python class (no PyQt5 dependency)
that reads the shared agent state file and detects Trae IDE via platform backend.
State changes are reported through a callback.
"""

from __future__ import annotations

import json
import os
import re
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
SOURCE_CODEX = "codex"
SOURCE_CODEX_CLI = "codex_cli"
SOURCE_CODEX_APP = "codex_app"
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
    "PreCompact",
    "PostCompact",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "PermissionRequest",
    "SessionStart",
]

# ── Config file paths ────────────────────────────────────────
CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CODEX_CONFIG_TOML_PATH = Path.home() / ".codex" / "config.toml"
CODEX_HOOKS_PATH = Path.home() / ".codex" / "hooks.json"
CODEX_TOML_BEGIN_MARKER = "# BEGIN NAICHA HOOKS"
CODEX_TOML_END_MARKER = "# END NAICHA HOOKS"

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

        Priority: hook state file > desktop app detection.
        """
        new_state = STATE_IDLE
        new_data: dict[str, Any] | None = None

        # 1. Read hook state file
        file_state, file_data = self._read_state_file()
        if file_state != STATE_IDLE:
            new_state = file_state
            new_data = file_data

        # 2. Codex App detection (only if no active hook state)
        if new_state == STATE_IDLE:
            desktop_state = self._detect_codex_app_state()
            if desktop_state is not None:
                new_state = desktop_state
                new_data = {"source": SOURCE_CODEX_APP, "state": desktop_state}

        # 3. Trae detection (only if no active hook state)
        if new_state == STATE_IDLE and self._trae_detection_enabled:
            trae_state = self._detect_trae_state()
            if trae_state is not None:
                new_state = trae_state
                new_data = {"source": SOURCE_TRAE, "state": trae_state}

        # 4. Notify on change
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

    def _detect_codex_app_state(self) -> str | None:
        """Detect the Codex desktop app via process monitoring."""
        try:
            backend = get_backend()
            if not backend.is_process_running("Codex"):
                return None
            fg_app = backend.get_foreground_app_name()
            if fg_app and "Codex" in fg_app:
                return STATE_WORKING
            return STATE_IDLE
        except Exception:
            return None

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
        """Build a shell-agnostic hook command string for the given agent source."""
        python_path = sys.executable
        hook_script = AGENT_HOOKS_DIR / "agent_hook.py"
        return f'"{python_path}" "{hook_script}" --source "{source}"'

    def install_claude_code_hooks(self) -> bool:
        """Install hooks into Claude Code's settings.json. Returns True on success."""
        try:
            self._ensure_hook_script()
            command = self._build_hook_command(SOURCE_CLAUDE_CODE)
            return self._install_claude_code_hooks(command)
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
        """Install hooks into Codex (CLI/App) config. Returns True on success."""
        try:
            self._ensure_hook_script()
            command = self._build_hook_command(SOURCE_CODEX)
            return self._install_codex_cli_hooks(command)
        except Exception:
            return False

    def uninstall_codex_cli_hooks(self) -> bool:
        """Remove naicha hooks from Codex (CLI/App) config. Returns True on success."""
        try:
            ok_toml = self._uninstall_codex_toml_hooks(CODEX_CONFIG_TOML_PATH)
            ok_json = self._uninstall_hooks_from_config(CODEX_HOOKS_PATH)
            return ok_toml and ok_json
        except Exception:
            return False

    def is_codex_cli_hooks_installed(self) -> bool:
        """Check if naicha hooks are present in Codex (CLI/App) config."""
        return (
            self._check_codex_toml_hooks_installed(CODEX_CONFIG_TOML_PATH)
            or self._check_hooks_installed(CODEX_HOOKS_PATH)
        )

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

    def _read_text(self, path: Path) -> str | None:
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _write_text(self, path: Path, content: str) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = None, None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=path.suffix or ".tmp")
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(path))
            return True
        except OSError:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            return False

    def _build_codex_toml_block(self, command: str) -> str:
        command_literal = json.dumps(command, ensure_ascii=False)
        lines = [
            CODEX_TOML_BEGIN_MARKER,
            *[
                f'{event} = [{{ matcher = "", hooks = [{{ type = "command", command = {command_literal} }}] }}]'
                for event in CODEX_CLI_HOOK_EVENTS
            ],
            CODEX_TOML_END_MARKER,
        ]
        return "\n".join(lines)

    def _strip_managed_codex_toml_block(self, text: str) -> str:
        pattern = re.compile(
            rf"\n?{re.escape(CODEX_TOML_BEGIN_MARKER)}.*?{re.escape(CODEX_TOML_END_MARKER)}\n?",
            re.DOTALL,
        )
        return pattern.sub("\n", text)

    def _cleanup_empty_hooks_section(self, text: str) -> str:
        lines = text.splitlines()
        cleaned: list[str] = []
        i = 0

        while i < len(lines):
            line = lines[i]
            if line.strip() != "[hooks]":
                cleaned.append(line)
                i += 1
                continue

            j = i + 1
            section_lines: list[str] = []
            while j < len(lines) and not re.match(r"^\s*\[", lines[j]):
                section_lines.append(lines[j])
                j += 1

            has_content = any(
                section_line.strip() and not section_line.lstrip().startswith("#")
                for section_line in section_lines
            )
            if has_content:
                cleaned.append(line)
                cleaned.extend(section_lines)
            i = j

        result = "\n".join(cleaned).strip()
        return f"{result}\n" if result else ""

    def _upsert_codex_toml_hooks(self, text: str, command: str) -> str:
        text = self._strip_managed_codex_toml_block(text).rstrip()
        block = self._build_codex_toml_block(command)

        hooks_match = re.search(r"(?m)^\[hooks\]\s*$", text)
        if hooks_match:
            insert_at = hooks_match.end()
            updated = f"{text[:insert_at]}\n{block}{text[insert_at:]}"
        else:
            suffix = "\n\n" if text else ""
            updated = f"{text}{suffix}[hooks]\n{block}\n"

        return self._cleanup_empty_hooks_section(updated)

    def _install_codex_toml_hooks(self, config_path: Path, command: str) -> bool:
        text = self._read_text(config_path) or ""
        if "[hooks]" in text and CODEX_TOML_BEGIN_MARKER not in text:
            return False
        updated = self._upsert_codex_toml_hooks(text, command)
        return self._write_text(config_path, updated)

    def _uninstall_codex_toml_hooks(self, config_path: Path) -> bool:
        text = self._read_text(config_path)
        if text is None:
            return True
        updated = self._cleanup_empty_hooks_section(self._strip_managed_codex_toml_block(text))
        if updated == text:
            return True
        return self._write_text(config_path, updated)

    def _check_codex_toml_hooks_installed(self, config_path: Path) -> bool:
        text = self._read_text(config_path)
        if text is None:
            return False
        return CODEX_TOML_BEGIN_MARKER in text and "agent_hook.py" in text

    def _is_naicha_command(self, command: str) -> bool:
        """Check if a command string belongs to our hook."""
        return "agent_hook.py" in command

    def _is_naicha_hook_entry(self, entry: Any) -> bool:
        """Check if a hook entry belongs to us.

        Supports both formats:
        - Flat (legacy): {"type": "command", "command": "...agent_hook.py..."}
        - Matcher format: {"matcher": "...", "hooks": [{"type": "command", "command": "...agent_hook.py..."}]}
        """
        if not isinstance(entry, dict):
            return False

        # Flat format (our old buggy entries)
        cmd = entry.get("command", "")
        if self._is_naicha_command(cmd):
            return True

        # Matcher format (correct Claude Code / Codex CLI schema)
        hooks_list = entry.get("hooks", [])
        if isinstance(hooks_list, list):
            for h in hooks_list:
                if isinstance(h, dict) and self._is_naicha_command(h.get("command", "")):
                    return True

        return False

    # ── Claude Code hook installation (matcher schema) ──────

    def _install_claude_code_hooks(self, command: str) -> bool:
        """Install hooks into Claude Code's settings.json using the matcher schema.

        Claude Code expects each hook event entry to be:
        {"matcher": "", "hooks": [{"type": "command", "command": "..."}]}

        An empty matcher string "" matches all tools.
        """
        data = self._read_config(CLAUDE_SETTINGS_PATH)
        hooks = data.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            hooks = {}
            data["hooks"] = hooks

        # First: remove any old flat-format naicha entries (they're invalid)
        self._remove_legacy_naicha_entries(hooks)

        new_entry = {"matcher": "", "hooks": [{"type": "command", "command": command}]}

        for event in CLAUDE_CODE_HOOK_EVENTS:
            entries = hooks.get(event, [])
            if not isinstance(entries, list):
                entries = []

            # Check if our hook is already there (in matcher format)
            found = False
            for i, e in enumerate(entries):
                if isinstance(e, dict) and self._is_naicha_hook_entry(e):
                    # Update the entry (Python path may have changed)
                    entries[i] = new_entry
                    found = True
                    break

            if not found:
                entries.append(new_entry)
            hooks[event] = entries

        return self._write_config(CLAUDE_SETTINGS_PATH, data)

    # ── Codex CLI hook installation (matcher schema) ────────

    def _install_codex_cli_hooks(self, command: str) -> bool:
        """Install hooks into Codex's current config, with legacy JSON fallback."""
        if self._install_codex_toml_hooks(CODEX_CONFIG_TOML_PATH, command):
            # Remove our legacy JSON hook file entries to avoid duplicate execution.
            self._uninstall_hooks_from_config(CODEX_HOOKS_PATH)
            return True

        # Fallback for older Codex builds that still rely on hooks.json.
        data = self._read_config(CODEX_HOOKS_PATH)
        hooks = data.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            hooks = {}
            data["hooks"] = hooks

        self._remove_legacy_naicha_entries(hooks)

        new_entry = {"matcher": "", "hooks": [{"type": "command", "command": command}]}

        for event in CODEX_CLI_HOOK_EVENTS:
            entries = hooks.get(event, [])
            if not isinstance(entries, list):
                entries = []

            found = False
            for i, e in enumerate(entries):
                if isinstance(e, dict) and self._is_naicha_hook_entry(e):
                    entries[i] = new_entry
                    found = True
                    break

            if not found:
                entries.append(new_entry)
            hooks[event] = entries

        return self._write_config(CODEX_HOOKS_PATH, data)

    # ── Legacy entry cleanup ───────────────────────────────

    def _remove_legacy_naicha_entries(self, hooks: dict[str, Any]) -> bool:
        """Remove old flat-format naicha entries ({"type": "command", "command": "...agent_hook.py..."})
        that were incorrectly installed before the matcher schema fix.

        Returns True if any entries were removed.
        """
        changed = False
        for event, entries in list(hooks.items()):
            if not isinstance(entries, list):
                continue
            filtered = [e for e in entries if not (
                isinstance(e, dict)
                and "type" in e
                and "command" in e
                and "matcher" not in e
                and "hooks" not in e
                and self._is_naicha_command(e.get("command", ""))
            )]
            if len(filtered) != len(entries):
                changed = True
                if filtered:
                    hooks[event] = filtered
                else:
                    del hooks[event]
        return changed

    # ── Generic uninstall / check ──────────────────────────

    def _uninstall_hooks_from_config(self, config_path: Path) -> bool:
        """Remove all naicha hook entries (both flat and matcher format) from a config file."""
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
            filtered = [e for e in entries if not self._is_naicha_hook_entry(e)]
            if len(filtered) != len(entries):
                changed = True
                if filtered:
                    hooks[event] = filtered
                else:
                    del hooks[event]

        if changed:
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
            if isinstance(entries, list) and any(self._is_naicha_hook_entry(e) for e in entries):
                return True
        return False
