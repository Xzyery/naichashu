#!/usr/bin/env python3
"""Standalone hook handler for Claude Code / Codex CLI agent state reporting.

This script is called by agent hook configurations. It reads JSON from stdin,
maps the hook event to an agent state, and writes the state to a shared file.

Design constraints:
  - Zero external dependencies (stdlib only)
  - Never blocks the agent (always exits 0)
  - Writes atomically to avoid partial reads
"""

import json
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

# ── State file location ──────────────────────────────────────
STATE_DIR = Path.home() / ".naicha_mouse"
STATE_FILE = STATE_DIR / "agent_state.json"

# ── Event → state mapping ────────────────────────────────────
CLAUDE_CODE_MAP: dict[str, str] = {
    "UserPromptSubmit": "thinking",
    "PreToolUse": "working",
    "PostToolUse": "thinking",
    "Stop": "complete",
    "SubagentStop": "complete",
    "Notification": "waiting",
    "SessionStart": "idle",
}

CODEX_CLI_MAP: dict[str, str] = {
    "UserPromptSubmit": "thinking",
    "PreToolUse": "working",
    "PostToolUse": "thinking",
    "PreCompact": "working",
    "PostCompact": "thinking",
    "Stop": "complete",
    "SubagentStart": "working",
    "SubagentStop": "complete",
    "PermissionRequest": "waiting",
    "SessionStart": "idle",
}

MAX_TOOL_INPUT_LEN = 80


def _serialize_tool_input(tool_input: object) -> str:
    """Serialize tool_input to a brief string for display."""
    if tool_input is None:
        return ""
    if isinstance(tool_input, str):
        text = tool_input
    else:
        try:
            text = json.dumps(tool_input, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(tool_input)
    return text[:MAX_TOOL_INPUT_LEN]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--source")
    return parser.parse_args(argv)


def main() -> None:
    try:
        args = _parse_args(sys.argv[1:])

        # Read hook event payload from stdin
        raw = sys.stdin.read()
        if not raw.strip():
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return

        if not isinstance(payload, dict):
            return

        event_name = payload.get("hook_event_name", "")
        if not event_name:
            return

        # Determine source agent
        source = args.source or os.environ.get("NAICHA_AGENT_SOURCE", "claude_code")

        # Map event to state
        if source in {"codex", "codex_app", "codex_cli"}:
            state = CODEX_CLI_MAP.get(event_name)
        else:
            state = CLAUDE_CODE_MAP.get(event_name)

        if state is None:
            # Unknown event — ignore silently
            return

        # Extract tool info for working state
        tool_name = payload.get("tool_name") if state == "working" else None
        tool_input = _serialize_tool_input(payload.get("tool_input")) if state == "working" else None

        # Build state data
        state_data = {
            "source": source,
            "state": state,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "session_id": payload.get("session_id"),
            "cwd": payload.get("cwd"),
            "timestamp": int(time.time()),
        }

        # Write atomically
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(STATE_DIR), suffix=".json")
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(state_data, f, ensure_ascii=False)
            os.replace(tmp_path, str(STATE_FILE))
        except OSError:
            # Clean up temp file on error
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    except Exception:
        # Never let the hook crash — silently swallow all errors
        pass


if __name__ == "__main__":
    main()
