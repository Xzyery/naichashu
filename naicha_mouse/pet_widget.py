"""NaichaMouse -- the main desktop pet widget."""

from __future__ import annotations

import json
import random
import sys
import threading
import time
from ctypes import c_void_p
from datetime import date
from pathlib import Path
from typing import Any, Optional

from PyQt5.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QCursor, QMovie, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QLabel,
    QMenu,
    QWidget,
)

from naicha_mouse import ai, gacha as gacha_mod
from naicha_mouse.agent_monitor import AgentStateMonitor
from naicha_mouse.constants import (
    AGENT_COMPLETE_DISPLAY_MS,
    AGENT_STATE_POLL_INTERVAL_MS,
    BASE_BUBBLE_HEIGHT,
    BASE_PET_SIZE,
    BASE_WINDOW_HEIGHT,
    BASE_WINDOW_WIDTH,
    COMPANION_EXP_AMOUNT,
    COMPANION_EXP_SECONDS,
    DAILY_INTERACTION_EXP_CAP,
    DEFAULT_SCALE_PERCENT,
    FONT_FAMILY,
    GACHA_DAILY_DISCOUNT_COST,
    GACHA_SINGLE_COST,
    GACHA_SUPER_PITY,
    GACHA_TEN_COST,
    MAX_LEVEL,
    TOOL_NAME_LABELS,
    TYPING_IDLE_TIMEOUT_SECONDS,
)
from naicha_mouse.dialogs import AiChatDialog, AiConfigDialog
from naicha_mouse.models import BUBBLE_FRAME_STYLES, DEFAULT_PROFILE, PetState
from naicha_mouse.platform_ import get_backend
from naicha_mouse.profile import (
    load_accessory_config,
    load_ai_config,
    load_dialogues,
    load_gacha_pool,
    load_profile,
    load_state_config,
    required_exp_for_level,
    save_ai_config as _save_ai_config,
    save_profile as _save_profile,
    title_for_level,
)
from naicha_mouse.resources import ACCESSORY_DIR, resolve_asset_path


class NaichaMouse(QWidget):
    ai_reply_ready = pyqtSignal(str)
    ai_error_ready = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        (
            self.states,
            self.asset_folder,
            self.default_state,
            self.startup_sequence,
            self.exit_state,
            self.random_groups,
        ) = load_state_config()
        self.dialogues = load_dialogues()
        self.gacha_pool = load_gacha_pool()
        self.accessories = load_accessory_config()
        self.ai_config = load_ai_config()
        self.profile, self.daily_start_pending = load_profile()
        self.ensure_accessory_profile()

        self.user_scale = DEFAULT_SCALE_PERCENT / 100
        self.pet_size = max(72, int(BASE_PET_SIZE * self.user_scale))
        self.window_width = max(190, int(BASE_WINDOW_WIDTH * self.user_scale))
        self.window_height = max(
            self.pet_size + 80,
            int(BASE_WINDOW_HEIGHT * self.user_scale),
        )
        self.bubble_height = max(58, int(BASE_BUBBLE_HEIGHT * self.user_scale))

        self.current_state_id = self.default_state
        self.current_movie: Optional[QMovie] = None
        self.drag_offset: Optional[QPoint] = None
        self.press_pos: Optional[QPoint] = None
        self.click_blocked = False
        self.startup_active = True
        self.exiting = False
        self.focus_active = False
        self.focus_seconds_left = 0
        self.recent_random_states: list[str] = []
        self.manual_state_index = -1
        self.last_feed_at = 0.0
        self.pending_level_message: Optional[str] = None
        self.status_panel_active = False
        self.last_dialogue_text = ""
        self.accessory_pixmap: Optional[QPixmap] = None
        self.accessory_dragging = False
        self.accessory_drag_offset = QPoint()
        self.accessory_pending_context_menu = False
        self.accessory_press_pos: Optional[QPoint] = None
        self.ai_busy = False
        self.ai_chat_dialog: Optional[AiChatDialog] = None
        self.chat_history: list[dict[str, str]] = []

        self.typing_follow_enabled = True
        self.typing_bubble_enabled = True
        self.typing_active = False
        self.last_typing_at = 0.0
        self.last_follow_move_at = 0.0
        self.key_down: set[int] = set()
        self.typing_key_count = 0
        self.last_typing_bubble_text = ""

        # Agent detection state
        self.agent_detection_enabled = self.profile.get("agent_detection_enabled", False)
        self.trae_detection_enabled = self.profile.get("trae_detection_enabled", False)
        self.agent_active = False
        self.agent_current_state = "idle"
        self._agent_monitor: AgentStateMonitor | None = None
        self._agent_state_timer: QTimer | None = None

        self.roam_mode = "off"
        self.roam_direction = 1
        self.roam_edge_index = 0
        self.roam_speed = 7
        self.edge_drift_until = 0.0

        self.setWindowTitle("奶茶鼠")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(self.window_width, self.window_height)

        self.bubble = QLabel(self)
        self.bubble.setWordWrap(True)
        self.bubble.setAlignment(Qt.AlignCenter)
        self.bubble.hide()

        self.bubble_decoration = QLabel(self)
        self.bubble_decoration.setAlignment(Qt.AlignTop | Qt.AlignRight)
        self.bubble_decoration.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.bubble_decoration.hide()

        self.pet_label = QLabel(self)
        self.pet_label.setAlignment(Qt.AlignCenter)
        self.pet_label.setContextMenuPolicy(Qt.NoContextMenu)

        self.accessory_label = QLabel(self)
        self.accessory_label.setAlignment(Qt.AlignCenter)
        self.accessory_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.accessory_label.hide()

        self.ai_reply_ready.connect(self.finish_ai_reply)
        self.ai_error_ready.connect(self.finish_ai_error)

        self.apply_layout()
        self.setup_timers()
        self.setup_agent_monitor()
        self.move_to_bottom_right()
        QTimer.singleShot(0, self.ensure_always_on_top)
        QTimer.singleShot(0, self.play_startup_sequence)

    # ── profile / config wrappers ──────────────────────────

    def _save_profile(self) -> None:
        _save_profile(self.profile)

    def _save_ai_config(self) -> None:
        _save_ai_config(self.ai_config)

    def _bump_dialogue_seen(self, reward_id: str) -> None:
        seen = self.profile["dialogue_rewards_seen"]
        seen[reward_id] = int(seen.get(reward_id, 0)) + 1

    def _grant_gacha_interaction_value(self, amount: int) -> int:
        if amount <= 0:
            return 0
        self.profile["interaction_value"] = int(self.profile["interaction_value"]) + amount
        self.add_exp_to_profile(amount)
        return amount

    @staticmethod
    def format_duration(seconds: int) -> str:
        minutes = max(0, seconds) // 60
        hours, mins = divmod(minutes, 60)
        if hours:
            return f"{hours}小时{mins}分"
        return f"{mins}分"

    @staticmethod
    def add_action(menu: QMenu, title: str, callback: Any) -> QAction:
        action = QAction(title, menu)
        action.triggered.connect(lambda checked=False: callback())
        menu.addAction(action)
        return action

    def ensure_accessory_profile(self) -> None:
        self.profile.setdefault("accessories", {})
        self.profile.setdefault("owned_accessories", [])
        self.profile.setdefault("temporary_accessories", {})
        default_id = self.accessories.get("default", "")

        # Crown is already generated locally, so grant it as a testing accessory.
        if default_id and default_id not in self.profile["owned_accessories"]:
            self.profile["owned_accessories"].append(default_id)
        if default_id and not self.profile.get("equipped_accessory"):
            self.profile["equipped_accessory"] = default_id

        for accessory_id, config in self.accessories.get("items", {}).items():
            stored = self.profile["accessories"].setdefault(accessory_id, {})
            stored.setdefault("visible", True)
            stored.setdefault("x_ratio", float(config.get("x_ratio", 0.5)))
            stored.setdefault("y_ratio", float(config.get("y_ratio", 0.2)))
            stored.setdefault("scale", float(config.get("scale", 1.0)))

    def setup_timers(self) -> None:
        self.bubble_timer = QTimer(self)
        self.bubble_timer.setSingleShot(True)
        self.bubble_timer.timeout.connect(self.hide_bubble)

        self.return_timer = QTimer(self)
        self.return_timer.setSingleShot(True)
        self.return_timer.timeout.connect(self.return_to_idle)

        self.random_idle_timer = QTimer(self)
        self.random_idle_timer.setSingleShot(True)
        self.random_idle_timer.timeout.connect(self.play_random_idle)

        self.idle_talk_timer = QTimer(self)
        self.idle_talk_timer.setSingleShot(True)
        self.idle_talk_timer.timeout.connect(self.idle_chatter)

        self.companion_timer = QTimer(self)
        self.companion_timer.timeout.connect(self.tick_companion_time)
        self.companion_timer.start(60 * 1000)

        self.focus_timer = QTimer(self)
        self.focus_timer.timeout.connect(self.tick_focus)

        self.drink_timer = QTimer(self)
        self.drink_timer.timeout.connect(self.remind_drink_water)
        self.drink_timer.start(45 * 60 * 1000)

        self.sedentary_timer = QTimer(self)
        self.sedentary_timer.timeout.connect(self.remind_stretch)
        self.sedentary_timer.start(60 * 60 * 1000)

        self.typing_timer = QTimer(self)
        self.typing_timer.timeout.connect(self.poll_typing)
        self.typing_timer.start(35)

        self.roam_timer = QTimer(self)
        self.roam_timer.timeout.connect(self.update_roaming)
        self.roam_timer.start(55)

    def setup_agent_monitor(self) -> None:
        """Set up the coding agent state monitor."""
        self._agent_monitor = AgentStateMonitor(
            on_state_change=self._on_agent_state_change,
            trae_detection_enabled=self.trae_detection_enabled,
        )
        self._agent_state_timer = QTimer(self)
        self._agent_state_timer.timeout.connect(self._agent_monitor.poll)
        if self.agent_detection_enabled:
            self._agent_state_timer.start(AGENT_STATE_POLL_INTERVAL_MS)

    def _on_agent_state_change(self, new_state: str, state_data: dict | None) -> None:
        """Callback when agent state changes. Maps agent states to pet states."""
        # Map agent state to pet state ID
        state_map = {
            "thinking": "agent_thinking",
            "working": "agent_working",
            "complete": "agent_complete",
            "waiting": "agent_waiting",
            "error": "agent_error",
            "idle": "agent_idle",
        }
        pet_state_id = state_map.get(new_state)
        if pet_state_id is None:
            return

        # Don't override startup/exit animations
        if self.startup_active or self.exiting:
            return

        self.agent_current_state = new_state
        is_active = new_state not in ("idle",)
        self.agent_active = is_active

        if is_active:
            self.return_timer.stop()
            self.random_idle_timer.stop()
            self.idle_talk_timer.stop()

        # Build bubble message
        message = None
        bubble_ms = 3200
        return_after_ms = None

        if new_state == "working" and state_data:
            tool_name = state_data.get("tool_name", "")
            tool_label = TOOL_NAME_LABELS.get(tool_name, tool_name) if tool_name else "操作"
            source = state_data.get("source", "")
            source_label = {
                "claude_code": "Claude Code",
                "codex": "Codex",
                "codex_cli": "Codex",
                "codex_app": "Codex App",
                "trae": "Trae",
            }.get(source, source)
            message = f"AI {tool_label}中... [{source_label}]"
            bubble_ms = 5000
        elif new_state == "thinking" and state_data:
            source = state_data.get("source", "")
            source_label = {
                "claude_code": "Claude Code",
                "codex": "Codex",
                "codex_cli": "Codex",
                "codex_app": "Codex App",
                "trae": "Trae",
            }.get(source, source)
            message = f"AI 思考中... [{source_label}]"
            bubble_ms = 5000
        elif new_state == "complete":
            return_after_ms = AGENT_COMPLETE_DISPLAY_MS
        elif new_state == "idle":
            # Agent went idle, return to normal idle
            if not self.focus_active and self.roam_mode == "off":
                self.return_to_idle()
                self.schedule_random_idle()
                self.schedule_idle_chatter()
            elif self.focus_active:
                self.play_state("work_study_static" if "work_study_static" in self.states else "work_study")
            return

        # Don't override focus mode animation (but still update bubble)
        if self.focus_active and is_active:
            # Show agent state as bubble text over focus animation
            if message:
                self.show_bubble(message, bubble_ms)
            return

        self.play_state(pet_state_id, message, bubble_ms, return_after_ms=return_after_ms)

    def apply_layout(self) -> None:
        self.setFixedSize(self.window_width, self.window_height)
        font_size = max(10, int(14 * self.user_scale))
        border_radius = max(8, int(14 * self.user_scale))
        self.bubble.setAlignment(Qt.AlignCenter)
        self.bubble.setStyleSheet(self.bubble_style(font_size, border_radius))
        self.bubble.setGeometry(12, 8, self.window_width - 24, self.bubble_height)
        if self.bubble.isVisible():
            self.update_bubble_decoration(status=False)
        self.pet_label.setGeometry(
            (self.window_width - self.pet_size) // 2,
            self.window_height - self.pet_size - 2,
            self.pet_size,
            self.pet_size,
        )
        self.update_accessory_label()

    def bubble_style(self, font_size: int, border_radius: int, *, status: bool = False) -> str:
        style_key = "status" if status else "normal"
        frame = BUBBLE_FRAME_STYLES.get(
            self.current_bubble_frame_id(),
            BUBBLE_FRAME_STYLES[""],
        )[style_key]
        line_height = "line-height: 130%;" if status else ""
        return f"""
        QLabel {{
            background: {frame["background"]};
            color: {frame["color"]};
            border: {frame["border"]};
            border-radius: {border_radius}px;
            padding: {frame["padding"]};
            font-family: {FONT_FAMILY};
            font-size: {font_size}px;
            {line_height}
        }}
        """

    def update_bubble_decoration(self, *, status: bool = False) -> None:
        style = BUBBLE_FRAME_STYLES.get(
            self.current_bubble_frame_id(),
            BUBBLE_FRAME_STYLES[""],
        )
        key = "status_decoration" if status else "decoration"
        text = str(style.get(key, ""))
        if not text or not self.bubble.isVisible():
            self.bubble_decoration.hide()
            return
        font_size = max(8, int((10 if status else 9) * self.user_scale))
        self.bubble_decoration.setText(text)
        self.bubble_decoration.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {style.get("decoration_color", "rgba(178, 128, 98, 185)")};
                border: none;
                padding: {max(5, int(6 * self.user_scale))}px {max(8, int(10 * self.user_scale))}px 0 0;
                font-family: {FONT_FAMILY};
                font-size: {font_size}px;
                font-weight: 600;
            }}
            """
        )
        self.bubble_decoration.setGeometry(self.bubble.geometry())
        self.bubble_decoration.show()
        self.bubble_decoration.raise_()

    def save_profile(self) -> None:
        with PROFILE_PATH.open("w", encoding="utf-8") as file:
            json.dump(self.profile, file, ensure_ascii=False, indent=2)

    def grant_capped_exp(
        self,
        amount: int,
        *,
        count_interaction: bool = True,
        interaction_value_delta: int | None = None,
        award_coins: bool = True,
    ) -> int:
        if amount <= 0:
            return 0

        if count_interaction:
            self.profile["today_interactions"] = int(self.profile["today_interactions"]) + 1

        remaining = DAILY_INTERACTION_EXP_CAP - int(self.profile["today_interaction_exp"])
        awarded = max(0, min(amount, remaining))
        if awarded > 0:
            if interaction_value_delta is None:
                interaction_value_delta = awarded
            interaction_value_delta = min(interaction_value_delta, awarded)
            self.profile["interaction_value"] = (
                int(self.profile["interaction_value"]) + interaction_value_delta
            )
            self.profile["today_interaction_exp"] = (
                int(self.profile["today_interaction_exp"]) + awarded
            )
            self.add_exp_to_profile(awarded)
            if award_coins:
                self.add_coins(awarded)
        self._save_profile()
        return awarded

    def grant_uncapped_exp(self, amount: int, *, award_coins: bool = True) -> int:
        if amount <= 0:
            return 0
        self.profile["interaction_value"] = int(self.profile["interaction_value"]) + amount
        self.add_exp_to_profile(amount)
        if award_coins:
            self.add_coins(amount)
        self._save_profile()
        return amount

    def grant_gacha_interaction_value(self, amount: int) -> int:
        if amount <= 0:
            return 0
        self.profile["interaction_value"] = int(self.profile["interaction_value"]) + amount
        self.add_exp_to_profile(amount)
        return amount

    def add_coins(self, amount: int) -> None:
        if amount <= 0:
            return
        self.profile["coins"] = int(self.profile["coins"]) + amount
        self.profile["total_coins_earned"] = int(self.profile["total_coins_earned"]) + amount
        self.profile["today_coin_earned"] = int(self.profile["today_coin_earned"]) + amount

    def add_exp_to_profile(self, amount: int) -> None:
        level = int(self.profile["level"])
        if level >= MAX_LEVEL:
            self.profile["level"] = MAX_LEVEL
            return

        self.profile["exp"] = int(self.profile["exp"]) + amount
        leveled_up = False
        while level < MAX_LEVEL:
            required = required_exp_for_level(level)
            if int(self.profile["exp"]) < required:
                break
            self.profile["exp"] = int(self.profile["exp"]) - required
            level += 1
            leveled_up = True

        if level >= MAX_LEVEL:
            level = MAX_LEVEL
            self.profile["exp"] = 0

        self.profile["level"] = level
        if leveled_up:
            self.pending_level_message = self.level_up_message(level)

    def level_up_message(self, level: int) -> str:
        template = random.choice(self.dialogue_lines("level_up"))
        return template.format(level=level, title=title_for_level(level))

    def show_pending_level_up(self) -> None:
        if not self.pending_level_message:
            return
        message = self.pending_level_message
        self.pending_level_message = None
        self.show_bubble(message, 5200)

    def tick_companion_time(self) -> None:
        if self.exiting:
            return

        self.profile["total_companion_seconds"] = (
            int(self.profile["total_companion_seconds"]) + 60
        )
        self.profile["today_companion_seconds"] = (
            int(self.profile["today_companion_seconds"]) + 60
        )
        self.profile["companion_exp_seconds_buffer"] = (
            int(self.profile["companion_exp_seconds_buffer"]) + 60
        )

        while int(self.profile["companion_exp_seconds_buffer"]) >= COMPANION_EXP_SECONDS:
            self.profile["companion_exp_seconds_buffer"] = (
                int(self.profile["companion_exp_seconds_buffer"]) - COMPANION_EXP_SECONDS
            )
            self.profile["interaction_value"] = (
                int(self.profile["interaction_value"]) + COMPANION_EXP_AMOUNT
            )
            self.add_exp_to_profile(COMPANION_EXP_AMOUNT)
            self.add_coins(COMPANION_EXP_AMOUNT)

        self._save_profile()
        self.show_pending_level_up()

    def state_path(self, state_id: str) -> Path:
        return resolve_asset_path(self.asset_folder, self.states[state_id].file)

    def play_state(
        self,
        state_id: str,
        message: Optional[str] = None,
        bubble_ms: int = 3200,
        return_after_ms: Optional[int] = None,
    ) -> None:
        if state_id not in self.states:
            state_id = self.default_state

        self.return_timer.stop()
        self.current_state_id = state_id
        asset_path = self.state_path(state_id)

        if self.current_movie is not None:
            self.current_movie.stop()
            self.current_movie.deleteLater()
            self.current_movie = None

        if asset_path.suffix.lower() == ".gif":
            movie = QMovie(str(asset_path))
            movie.setCacheMode(QMovie.CacheAll)
            movie.setScaledSize(QSize(self.pet_size, self.pet_size))
            self.current_movie = movie
            self.pet_label.setMovie(movie)
            movie.start()
        else:
            pixmap = QPixmap(str(asset_path))
            self.pet_label.setPixmap(
                pixmap.scaled(
                    self.pet_size,
                    self.pet_size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )

        if message:
            self.show_bubble(message, bubble_ms)

        if return_after_ms is not None and not self.protected_mode():
            self.return_timer.start(return_after_ms)
        self.update_accessory_label()

    def play_startup_sequence(self) -> None:
        self.startup_active = True
        if self.daily_start_pending:
            self.grant_capped_exp(
                10,
                count_interaction=False,
                interaction_value_delta=10,
            )
            self.daily_start_pending = False

        first_state = self.startup_sequence[0]
        first_message = random.choice(
            ["唔...起床中...", *self.dialogue_lines("startup")]
        )
        self.play_state(first_state, first_message, bubble_ms=3600)

        if len(self.startup_sequence) > 1:
            QTimer.singleShot(2800, self.play_startup_arrive)
            QTimer.singleShot(5600, self.finish_startup)
        else:
            QTimer.singleShot(3200, self.finish_startup)

    def play_startup_arrive(self) -> None:
        if self.exiting:
            return
        self.play_state(
            self.startup_sequence[1],
            random.choice(self.dialogue_lines("startup")),
            bubble_ms=3600,
        )

    def finish_startup(self) -> None:
        if self.exiting:
            return
        self.startup_active = False
        self.ensure_always_on_top()
        self.return_to_idle()
        self.show_pending_level_up()
        self.schedule_random_idle()
        self.schedule_idle_chatter()

    def ensure_always_on_top(self) -> None:
        """Re-assert top-most behavior, especially on macOS."""
        if not (self.windowFlags() & Qt.WindowStaysOnTopHint):
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            if self.isVisible():
                self.show()
        if self.isVisible():
            self.raise_()
        if sys.platform == "darwin":
            self._ensure_macos_window_level()

    def _ensure_macos_window_level(self) -> None:
        """Pin the native macOS window above regular app windows and across spaces."""
        try:
            import objc  # type: ignore[import-untyped]
            from AppKit import (  # type: ignore[import-untyped]
                NSFloatingWindowLevel,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
            )

            native_view = objc.objc_object(c_void_p=int(self.winId()))
            ns_window = native_view.window()
            if ns_window is None:
                return

            ns_window.setLevel_(NSFloatingWindowLevel)
            behavior = int(ns_window.collectionBehavior())
            behavior |= int(NSWindowCollectionBehaviorCanJoinAllSpaces)
            behavior |= int(NSWindowCollectionBehaviorFullScreenAuxiliary)
            ns_window.setCollectionBehavior_(behavior)
        except Exception:
            pass

    def show_from_tray(self) -> None:
        """Restore the pet from the tray and bring it back to the front."""
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.raise_()
        self.activateWindow()
        self.ensure_always_on_top()

    def toggle_visibility_from_tray(self) -> None:
        if self.isVisible():
            self.hide()
            return
        self.show_from_tray()

    def exit_sequence(self) -> None:
        if self.exiting:
            return
        self.exiting = True
        self.random_idle_timer.stop()
        self.idle_talk_timer.stop()
        self.focus_timer.stop()
        self.return_timer.stop()
        self._save_profile()
        self.play_state(
            self.exit_state,
            "我先下班啦，明天见。",
            bubble_ms=3500,
        )
        QTimer.singleShot(3500, QApplication.quit)

    def show_bubble(self, text: str, duration_ms: int = 3200) -> None:
        if self.status_panel_active:
            self.restore_normal_layout()
        if "\n" not in text:
            self.last_dialogue_text = text
        font_size = max(10, int(14 * self.user_scale))
        border_radius = max(8, int(14 * self.user_scale))
        self.bubble.setText(text)
        self.bubble.setAlignment(Qt.AlignCenter)
        self.bubble.setStyleSheet(self.bubble_style(font_size, border_radius))
        self.bubble.setGeometry(12, 8, self.window_width - 24, self.bubble_height)
        self.bubble.show()
        self.bubble.raise_()
        self.update_bubble_decoration(status=False)
        self.bubble_timer.start(duration_ms)

    def show_status_bubble(self, text: str, duration_ms: int = 8600) -> None:
        self.bubble_timer.stop()
        old_right = self.x() + self.width()
        old_bottom = self.y() + self.height()

        line_count = text.count("\n") + 1
        font_size = max(12, min(15, int(14 * self.user_scale)))
        panel_height = max(190, line_count * (font_size + 8) + 30)
        screen = self.screen_geometry()
        status_width = min(max(self.window_width, 360), max(260, screen.width() - 16))
        status_height = max(self.window_height, self.pet_size + panel_height + 28)

        self.status_panel_active = True
        self.setFixedSize(status_width, status_height)
        self.bubble.setText(text)
        self.bubble.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.bubble.setStyleSheet(
            self.bubble_style(font_size, max(14, int(16 * self.user_scale)), status=True)
        )
        self.bubble.setGeometry(12, 8, status_width - 24, panel_height)
        self.pet_label.setGeometry(
            (status_width - self.pet_size) // 2,
            status_height - self.pet_size - 2,
            self.pet_size,
            self.pet_size,
        )
        self.move(self.clamp_window_to_screen(QPoint(old_right - status_width, old_bottom - status_height)))
        self.bubble.show()
        self.bubble.raise_()
        self.update_bubble_decoration(status=True)
        self.bubble_timer.start(duration_ms)

    def hide_bubble(self) -> None:
        self.bubble.hide()
        self.bubble_decoration.hide()
        if self.status_panel_active:
            self.restore_normal_layout()

    def restore_normal_layout(self) -> None:
        old_right = self.x() + self.width()
        old_bottom = self.y() + self.height()
        self.status_panel_active = False
        self.apply_layout()
        self.move(self.clamp_window_to_screen(QPoint(old_right - self.width(), old_bottom - self.height())))

    def current_accessory_id(self) -> str:
        accessory_id = str(self.profile.get("equipped_accessory", ""))
        if accessory_id in self.accessories.get("items", {}):
            return accessory_id
        return str(self.accessories.get("default", ""))

    def current_accessory_config(self) -> Optional[dict[str, Any]]:
        accessory_id = self.current_accessory_id()
        return self.accessories.get("items", {}).get(accessory_id)

    def current_accessory_label(self) -> str:
        config = self.current_accessory_config() or {}
        return str(config.get("label", "当前配饰"))

    def current_accessory_state(self) -> dict[str, Any]:
        accessory_id = self.current_accessory_id()
        config = self.current_accessory_config() or {}
        stored = self.profile.setdefault("accessories", {}).setdefault(accessory_id, {})
        stored.setdefault("visible", True)
        stored.setdefault("x_ratio", float(config.get("x_ratio", 0.5)))
        stored.setdefault("y_ratio", float(config.get("y_ratio", 0.2)))
        stored.setdefault("scale", float(config.get("scale", 1.0)))
        return stored

    def current_accessory_path(self) -> Optional[Path]:
        config = self.current_accessory_config()
        if not config:
            return None
        path = ACCESSORY_DIR / str(config.get("file", ""))
        return path if path.exists() else None

    def should_show_accessory(self) -> bool:
        if self.status_panel_active or self.exiting or self.startup_active:
            return False
        if self.typing_active or self.agent_active or self.drag_offset is not None or self.roam_mode != "off":
            return False
        if self.current_state_id in self.states:
            category = self.states[self.current_state_id].category
            if category in {"startup", "exit", "typing", "movement", "agent"}:
                return False
        accessory_id = self.current_accessory_id()
        if not accessory_id:
            return False
        state = self.current_accessory_state()
        return bool(state.get("visible", True)) and self.current_accessory_path() is not None

    def update_accessory_label(self) -> None:
        if not hasattr(self, "accessory_label"):
            return
        if not self.should_show_accessory():
            self.accessory_label.hide()
            return

        config = self.current_accessory_config() or {}
        state = self.current_accessory_state()
        path = self.current_accessory_path()
        if path is None:
            self.accessory_label.hide()
            return

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.accessory_label.hide()
            return

        base_width = max(18, int(self.pet_size * float(config.get("width_ratio", 0.23))))
        width = max(18, int(base_width * float(state.get("scale", 1.0))))
        height = max(18, int(pixmap.height() * width / max(1, pixmap.width())))
        scaled = pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.accessory_pixmap = scaled
        pet_rect = self.pet_label.geometry()
        center_x = pet_rect.left() + int(float(state.get("x_ratio", 0.5)) * pet_rect.width())
        center_y = pet_rect.top() + int(float(state.get("y_ratio", 0.2)) * pet_rect.height())
        self.accessory_label.setGeometry(center_x - scaled.width() // 2, center_y - scaled.height() // 2, scaled.width(), scaled.height())
        self.accessory_label.setPixmap(scaled)
        self.accessory_label.show()
        self.accessory_label.raise_()
        self.bubble.raise_()
        if self.bubble_decoration.isVisible():
            self.bubble_decoration.raise_()

    def accessory_hit_test(self, pos: QPoint) -> bool:
        if not self.accessory_label.isVisible() or self.accessory_pixmap is None:
            return False
        if not self.accessory_label.geometry().contains(pos):
            return False
        local = pos - self.accessory_label.pos()
        if local.x() < 0 or local.y() < 0:
            return False
        image = self.accessory_pixmap.toImage()
        if local.x() >= image.width() or local.y() >= image.height():
            return False
        return image.pixelColor(local).alpha() > 20

    def begin_accessory_drag_if_pending(self) -> None:
        if not self.accessory_pending_context_menu or self.accessory_press_pos is None:
            return
        self.accessory_dragging = True
        self.accessory_pending_context_menu = False
        if self.accessory_label.isVisible():
            self.accessory_drag_offset = self.accessory_press_pos - self.accessory_label.pos()
        else:
            self.accessory_drag_offset = QPoint()
        self.show_bubble(f"正在调整{self.current_accessory_label()}位置。", 1800)

    def move_accessory_to(self, pos: QPoint) -> None:
        if not self.accessory_dragging:
            return
        top_left = pos - self.accessory_drag_offset
        center = QPoint(
            top_left.x() + self.accessory_label.width() // 2,
            top_left.y() + self.accessory_label.height() // 2,
        )
        pet_rect = self.pet_label.geometry()
        x_ratio = (center.x() - pet_rect.left()) / max(1, pet_rect.width())
        y_ratio = (center.y() - pet_rect.top()) / max(1, pet_rect.height())
        state = self.current_accessory_state()
        state["x_ratio"] = max(-0.25, min(1.25, x_ratio))
        state["y_ratio"] = max(-0.25, min(1.25, y_ratio))
        self.update_accessory_label()

    def finish_accessory_drag(self) -> None:
        self.accessory_dragging = False
        self.accessory_pending_context_menu = False
        self.accessory_press_pos = None
        self._save_profile()
        self.show_bubble(f"{self.current_accessory_label()}戴好啦。", 2200)

    def set_accessory_visible(self, visible: bool) -> None:
        self.current_accessory_state()["visible"] = visible
        self._save_profile()
        self.update_accessory_label()
        label = self.current_accessory_label()
        self.show_bubble(f"{label}出现啦。" if visible else f"{label}先收起来。", 2200)

    def adjust_accessory_scale(self, delta: float) -> None:
        state = self.current_accessory_state()
        state["scale"] = max(0.5, min(1.6, float(state.get("scale", 1.0)) + delta))
        self._save_profile()
        self.update_accessory_label()

    def reset_accessory_position(self) -> None:
        accessory_id = self.current_accessory_id()
        config = self.current_accessory_config() or {}
        self.profile.setdefault("accessories", {})[accessory_id] = {
            "visible": True,
            "x_ratio": float(config.get("x_ratio", 0.5)),
            "y_ratio": float(config.get("y_ratio", 0.2)),
            "scale": float(config.get("scale", 1.0)),
        }
        self._save_profile()
        self.update_accessory_label()
        self.show_bubble(f"{self.current_accessory_label()}回到默认位置。", 2200)

    def equip_accessory(self, accessory_id: str) -> None:
        if accessory_id not in self.accessories.get("items", {}):
            return
        self.profile["equipped_accessory"] = accessory_id
        self.current_accessory_state()["visible"] = True
        self._save_profile()
        self.update_accessory_label()
        label = self.accessories["items"][accessory_id].get("label", accessory_id)
        self.show_bubble(f"已佩戴：{label}", 2400)

    def available_accessory_ids(self) -> list[str]:
        now = int(time.time())
        available = set(self.profile.get("owned_accessories", []))
        for accessory_id, expires_at in self.profile.get("temporary_accessories", {}).items():
            try:
                if int(expires_at) > now:
                    available.add(accessory_id)
            except (TypeError, ValueError):
                continue
        default_id = self.accessories.get("default", "")
        if default_id:
            available.add(default_id)
        return [
            accessory_id
            for accessory_id in self.accessories.get("items", {})
            if accessory_id in available and (ACCESSORY_DIR / self.accessories["items"][accessory_id].get("file", "")).exists()
        ]

    def dialogue_lines(self, group: str) -> list[str]:
        lines = self.dialogues.get(group) or self.dialogues.get("idle") or ["奶茶鼠在。"]
        base_lines = [str(line) for line in lines if str(line).strip()] or ["奶茶鼠在。"]
        unlocked = self.unlocked_dialogues_for_group(group)
        if unlocked:
            chance = 0.15 if group == "idle" else 0.10
            candidates = [line for line in unlocked if line != self.last_dialogue_text]
            if candidates and random.random() < chance:
                return [random.choice(candidates)]
        return base_lines

    def unlocked_dialogues_for_group(self, group: str) -> list[str]:
        rewards = {
            item.get("id"): item
            for item in self.gacha_pool.get("rewards", [])
            if item.get("type") == "dialogue"
        }
        unlocked: list[str] = []

        for reward_id in self.profile.get("owned_dialogues", []):
            reward = rewards.get(reward_id)
            if not reward:
                continue
            target_groups = reward.get("target_groups", ["idle"])
            if group in target_groups:
                unlocked.append(str(reward.get("text", reward_id)))

        for pack_id in self.profile.get("owned_dialogue_packs", []):
            reward = rewards.get(pack_id)
            if not reward:
                continue
            for item in reward.get("dialogues", []):
                target_groups = item.get("target_groups", ["idle"])
                if group in target_groups:
                    unlocked.append(str(item.get("text", "")).strip())

        return [line for line in unlocked if line]

    def protected_mode(self) -> bool:
        return (
            self.startup_active
            or self.exiting
            or self.focus_active
            or self.typing_active
            or self.agent_active
            or self.drag_offset is not None
            or self.roam_mode != "off"
        )

    def schedule_random_idle(self) -> None:
        if self.exiting:
            return
        self.random_idle_timer.start(random.randint(12_000, 25_000))

    def schedule_idle_chatter(self) -> None:
        if self.exiting:
            return
        self.idle_talk_timer.start(random.randint(30_000, 60_000))

    def random_enabled_states(self, group: str | None = None) -> list[PetState]:
        states = [
            state
            for state in self.states.values()
            if state.is_random_enabled and state.random_weight > 0
        ]
        if group is not None:
            states = [state for state in states if state.random_group == group]
        return states

    def choose_random_group(self) -> str:
        available_groups: list[str] = []
        weights: list[int] = []
        for group, weight in self.random_groups.items():
            if weight <= 0:
                continue
            if self.random_enabled_states(group):
                available_groups.append(group)
                weights.append(weight)

        if not available_groups:
            return "daily"
        return random.choices(available_groups, weights=weights, k=1)[0]

    def select_random_state(self) -> PetState:
        group = self.choose_random_group()
        candidates = self.random_enabled_states(group)
        filtered = [
            state
            for state in candidates
            if state.id != self.current_state_id and state.id not in self.recent_random_states
        ]
        pool = filtered or [state for state in candidates if state.id != self.current_state_id]
        if not pool:
            pool = candidates or self.random_enabled_states() or [self.states[self.default_state]]

        return random.choices(
            pool,
            weights=[max(1, state.random_weight) for state in pool],
            k=1,
        )[0]

    def remember_random_state(self, state_id: str) -> None:
        self.recent_random_states.append(state_id)
        self.recent_random_states = self.recent_random_states[-4:]

    def random_message_for_state(self, state: PetState) -> Optional[str]:
        if state.random_group == "daily":
            return None
        if state.random_group == "relax" and random.random() > 0.45:
            return None
        return random.choice(self.dialogue_lines(state.bubble_group))

    def play_random_idle(self) -> None:
        try:
            if self.protected_mode():
                return
            state = self.select_random_state()
            self.remember_random_state(state.id)
            self.play_state(
                state.id,
                self.random_message_for_state(state),
                bubble_ms=3600,
                return_after_ms=random.randint(4200, 7200),
            )
        finally:
            self.schedule_random_idle()

    def idle_candidates(self) -> list[PetState]:
        candidates = self.random_enabled_states("daily")
        return candidates or [self.states[self.default_state]]

    def return_to_idle(self) -> None:
        if self.exiting or self.focus_active:
            return
        candidates = [
            state
            for state in self.idle_candidates()
            if state.id != self.current_state_id and state.id not in self.recent_random_states
        ]
        pool = candidates or self.idle_candidates()
        state = random.choices(
            pool,
            weights=[max(1, state.random_weight) for state in pool],
            k=1,
        )[0]
        self.remember_random_state(state.id)
        self.play_state(state.id)

    def idle_chatter(self) -> None:
        try:
            if (
                not self.startup_active
                and not self.exiting
                and not self.focus_active
                and not self.typing_active
                and not self.bubble.isVisible()
            ):
                self.show_bubble(random.choice(self.dialogue_lines("idle")), 3600)
        finally:
            self.schedule_idle_chatter()

    def configure_ai_chat(self) -> None:
        dialog = AiConfigDialog(self.ai_config, self)
        if dialog.exec_() != QDialog.Accepted:
            return

        self.ai_config = dialog.values()
        self._save_ai_config()
        self.show_bubble("AI 聊天配置已保存。", 2600)

    def ai_config_ready(self) -> bool:
        provider = self.ai_config.get("provider", "openai")
        return bool(
            provider in {"openai", "anthropic", "gemini"}
            and ai.normalize_ai_url(
                self.ai_config.get("base_url", ""),
                provider,
                self.ai_config.get("model", "").strip(),
            )
            and self.ai_config.get("model", "").strip()
            and self.ai_config.get("api_key", "").strip()
        )

    def ask_ai_chat(self) -> None:
        if not self.ai_config_ready():
            self.show_bubble("先配置 AI 地址、模型和 Key。", 2800)
            self.configure_ai_chat()
            if not self.ai_config_ready():
                return

        if self.ai_chat_dialog is None:
            self.ai_chat_dialog = AiChatDialog(self)
            self.ai_chat_dialog.send_requested.connect(self.send_ai_chat_message)
            self.ai_chat_dialog.clear_requested.connect(self.clear_ai_chat)
        self.ai_chat_dialog.set_waiting(self.ai_busy)
        self.ai_chat_dialog.show()
        self.ai_chat_dialog.raise_()
        self.ai_chat_dialog.activateWindow()

    def send_ai_chat_message(self, prompt: str) -> None:
        prompt = prompt.strip()
        if not prompt:
            return
        if self.ai_busy:
            self.show_bubble("上一句还在路上，等我咕噜一下。", 2600)
            if self.ai_chat_dialog is not None:
                self.ai_chat_dialog.append_line("奶茶鼠", "上一句还在路上，等我咕噜一下。")
            return
        self.ai_busy = True
        if self.ai_chat_dialog is not None:
            self.ai_chat_dialog.append_line("我", prompt)
            self.ai_chat_dialog.append_line("奶茶鼠", "组织语言中...")
            self.ai_chat_dialog.set_waiting(True)
        self.chat_history.append({"role": "user", "content": prompt})
        self.chat_history = ai.trim_chat_history(self.chat_history)
        self.show_bubble("奶茶鼠正在组织语言...", 3600)
        thread = threading.Thread(
            target=ai.request_ai_reply,
            args=(self.ai_config, self.chat_history, self.ai_reply_ready, self.ai_error_ready),
            daemon=True,
        )
        thread.start()

    def finish_ai_reply(self, reply: str) -> None:
        self.ai_busy = False
        cleaned = " ".join(reply.split())
        self.chat_history.append({"role": "assistant", "content": cleaned})
        self.chat_history = ai.trim_chat_history(self.chat_history)
        if self.ai_chat_dialog is not None:
            self.ai_chat_dialog.replace_last_line("奶茶鼠", cleaned)
            self.ai_chat_dialog.set_waiting(False)
        if len(cleaned) > 82:
            self.show_status_bubble("奶茶鼠说：\n" + cleaned, 9000)
        else:
            self.show_bubble(cleaned, 7200)

    def finish_ai_error(self, message: str) -> None:
        self.ai_busy = False
        if self.ai_chat_dialog is not None:
            self.ai_chat_dialog.replace_last_line("奶茶鼠", message)
            self.ai_chat_dialog.set_waiting(False)
        self.show_status_bubble(message, 7600)

    def clear_ai_chat(self) -> None:
        self.chat_history.clear()
        if self.ai_chat_dialog is not None:
            self.ai_chat_dialog.chat_view.clear()
        self.show_bubble("聊天上下文清空啦。", 2400)

    def tick_focus(self) -> None:
        if not self.focus_active:
            return

        self.focus_seconds_left -= 1
        if self.focus_seconds_left == 25 * 60 - 4 and "work_study_static" in self.states:
            self.play_state("work_study_static")

        if self.focus_seconds_left <= 0:
            self.complete_focus()
            return

        if self.focus_seconds_left % 300 == 0:
            minutes = self.focus_seconds_left // 60
            self.show_bubble(f"还剩 {minutes} 分钟，我还在。", 2600)

    def complete_focus(self) -> None:
        self.focus_active = False
        self.focus_timer.stop()
        self.profile["focus_completed_count"] = int(self.profile["focus_completed_count"]) + 1
        self.grant_capped_exp(25, interaction_value_delta=25)
        state_id = random.choice(["event_cheer_dance", "event_fireworks"])
        self.play_state(
            state_id,
            "25 分钟完成！去休息一下吧。",
            bubble_ms=5200,
            return_after_ms=5000,
        )
        self.show_pending_level_up()

    def poll_typing(self) -> None:
        if not self.typing_follow_enabled or self.startup_active or self.exiting:
            return

        if self.is_shortcut_modifier_down():
            self.key_down.clear()
            return

        pressed: set[int] = set()
        tapped: set[int] = set()
        for key_code in get_backend().get_typing_key_codes():
            if get_backend().is_key_pressed(key_code):
                pressed.add(key_code)
            if get_backend().is_key_tapped(key_code):
                tapped.add(key_code)

        new_keys = (pressed - self.key_down) | tapped
        self.key_down = pressed
        now = time.monotonic()

        if new_keys:
            self.last_typing_at = now
            if not self.typing_active:
                self.start_typing_follow(now)
            self.typing_key_count += len(new_keys)
            self.update_typing_bubble()
            self.follow_typing_target(now)
            return

        if not self.typing_active:
            return

        if now - self.last_typing_at <= TYPING_IDLE_TIMEOUT_SECONDS:
            if now - self.last_follow_move_at >= 0.28:
                self.follow_typing_target(now)
            return

        self.stop_typing_follow()

    @staticmethod
    def is_shortcut_modifier_down() -> bool:
        return get_backend().is_modifier_down()

    def start_typing_follow(self, now: float) -> None:
        self.typing_active = True
        self.typing_key_count = 0
        self.last_typing_bubble_text = ""
        self.return_timer.stop()
        self.random_idle_timer.stop()
        self.idle_talk_timer.stop()
        if not self.agent_active:
            self.play_state("typing")
        self.follow_typing_target(now, snap=True)

    def stop_typing_follow(self) -> None:
        self.typing_active = False
        self.key_down.clear()
        self.typing_key_count = 0
        self.last_typing_bubble_text = ""
        if self.focus_active:
            self.play_state("work_study_static" if "work_study_static" in self.states else "work_study")
            return
        if self.roam_mode != "off":
            self.play_state("movement_run")
            return
        self.return_to_idle()
        self.schedule_random_idle()
        self.schedule_idle_chatter()

    def update_typing_bubble(self) -> None:
        if not self.typing_bubble_enabled:
            return
        text = self.build_typing_bubble_text()
        if text == self.last_typing_bubble_text:
            return
        self.last_typing_bubble_text = text
        self.show_bubble(text, 1800)

    def build_typing_bubble_text(self) -> str:
        count = max(1, self.typing_key_count)
        phrases = self.dialogue_lines("typing")
        phrase = phrases[(count - 1) // 4 % len(phrases)]
        return f"{phrase}  ⌨ x {count}"

    def typing_target_position(self) -> QPoint:
        screen = QApplication.primaryScreen().availableGeometry()
        backend = get_backend()
        own_wid = int(self.winId())

        rect = backend.get_foreground_window_rect(own_wid)
        if rect is not None and rect.width > 120 and rect.height > 120:
            target_x = rect.right - self.width() - 22
            target_y = rect.bottom - self.height() - 22
            return self.clamp_to_screen(QPoint(target_x, target_y), screen)

        cursor = backend.get_cursor_position()
        if cursor is not None:
            return self.clamp_to_screen(QPoint(cursor.x + 28, cursor.y + 28), screen)
        return self.pos()

    @staticmethod
    def clamp_to_screen(pos: QPoint, screen: Any) -> QPoint:
        x = max(screen.left(), min(pos.x(), screen.right()))
        y = max(screen.top(), min(pos.y(), screen.bottom()))
        return QPoint(x, y)

    def clamp_window_to_screen(self, pos: QPoint) -> QPoint:
        screen = QApplication.primaryScreen().availableGeometry()
        x = max(screen.left(), min(pos.x(), screen.right() - self.width()))
        y = max(screen.top(), min(pos.y(), screen.bottom() - self.height()))
        return QPoint(x, y)

    def follow_typing_target(self, now: float, snap: bool = False) -> None:
        self.last_follow_move_at = now
        target = self.clamp_window_to_screen(self.typing_target_position())
        if snap:
            self.move(target)
            return

        current = self.pos()
        dx = target.x() - current.x()
        dy = target.y() - current.y()
        if abs(dx) + abs(dy) < 8:
            return

        self.move(current.x() + int(dx * 0.35), current.y() + int(dy * 0.35))

    def toggle_typing_follow(self) -> None:
        self.typing_follow_enabled = not self.typing_follow_enabled
        if self.typing_follow_enabled:
            self.key_down.clear()
            self.last_typing_at = 0.0
            self.show_bubble("打字跟随已开启。", 2600)
            return

        if self.typing_active:
            self.typing_active = False
            self.return_to_idle()
        self.key_down.clear()
        self.show_bubble("打字跟随已关闭。", 2600)

    def toggle_typing_bubble(self) -> None:
        self.typing_bubble_enabled = not self.typing_bubble_enabled
        self.typing_key_count = 0
        self.last_typing_bubble_text = ""
        message = "打字气泡已开启。" if self.typing_bubble_enabled else "打字气泡已关闭。"
        self.show_bubble(message, 2600)

    # ── Agent detection toggles ────────────────────────────

    def toggle_agent_detection(self) -> None:
        self.agent_detection_enabled = not self.agent_detection_enabled
        self.profile["agent_detection_enabled"] = self.agent_detection_enabled
        self._save_profile()

        if self.agent_detection_enabled:
            if self._agent_state_timer is not None:
                self._agent_state_timer.start(AGENT_STATE_POLL_INTERVAL_MS)
            self.show_bubble("Agent 检测已开启。", 2600)
        else:
            if self._agent_state_timer is not None:
                self._agent_state_timer.stop()
            self.agent_active = False
            self.agent_current_state = "idle"
            if not self.focus_active and self.roam_mode == "off":
                self.return_to_idle()
                self.schedule_random_idle()
                self.schedule_idle_chatter()
            self.show_bubble("Agent 检测已关闭。", 2600)

    def toggle_claude_code_hooks(self) -> None:
        if self._agent_monitor is None:
            return
        if self._agent_monitor.is_claude_code_hooks_installed():
            if self._agent_monitor.uninstall_claude_code_hooks():
                self.show_bubble("Claude Code Hooks 已卸载。", 3200)
            else:
                self.show_bubble("卸载失败，请检查权限。", 3200)
        else:
            if self._agent_monitor.install_claude_code_hooks():
                self.show_bubble("Claude Code Hooks 已安装！重启 Claude Code 生效。", 4200)
            else:
                self.show_bubble("安装失败，请检查配置文件。", 3200)

    def toggle_codex_cli_hooks(self) -> None:
        if self._agent_monitor is None:
            return
        if self._agent_monitor.is_codex_cli_hooks_installed():
            if self._agent_monitor.uninstall_codex_cli_hooks():
                self.show_bubble("Codex Hooks 已卸载。", 3200)
            else:
                self.show_bubble("卸载失败，请检查权限。", 3200)
        else:
            if self._agent_monitor.install_codex_cli_hooks():
                self.show_bubble("Codex Hooks 已安装！重启 Codex / Codex App 生效。", 4200)
            else:
                self.show_bubble("安装失败，请检查配置文件。", 3200)

    def toggle_trae_detection(self) -> None:
        self.trae_detection_enabled = not self.trae_detection_enabled
        self.profile["trae_detection_enabled"] = self.trae_detection_enabled
        self._save_profile()

        if self._agent_monitor is not None:
            self._agent_monitor.trae_detection_enabled = self.trae_detection_enabled
        message = "Trae IDE 检测已开启。" if self.trae_detection_enabled else "Trae IDE 检测已关闭。"
        self.show_bubble(message, 2600)

    def show_agent_status(self) -> None:
        if self._agent_monitor is None:
            self.show_bubble("Agent 监控未启动。", 2600)
            return
        state_labels = {
            "idle": "待命",
            "thinking": "思考中",
            "working": "工作中",
            "complete": "已完成",
            "waiting": "等待输入",
            "error": "出错",
        }
        state = self._agent_monitor.current_state
        data = self._agent_monitor.current_data
        label = state_labels.get(state, state)

        if data and data.get("source"):
            source = data["source"]
            source_label = {
                "claude_code": "Claude Code",
                "codex": "Codex",
                "codex_cli": "Codex",
                "codex_app": "Codex App",
                "trae": "Trae",
            }.get(source, source)
            tool = data.get("tool_name", "")
            tool_info = f" [{TOOL_NAME_LABELS.get(tool, tool)}]" if tool else ""
            self.show_bubble(f"Agent: {source_label} — {label}{tool_info}", 5000)
        else:
            self.show_bubble(f"Agent 状态: {label}", 3200)

    def screen_geometry(self) -> Any:
        return QApplication.primaryScreen().availableGeometry()

    def move_to_bottom_right(self) -> None:
        screen = self.screen_geometry()
        self.move(screen.right() - self.width() - 24, screen.bottom() - self.height() - 24)

    def summon_back(self) -> None:
        self.roam_mode = "off"
        self.move_to_bottom_right()
        self.play_state(
            "movement_arrive",
            random.choice(self.dialogue_lines("movement")),
            return_after_ms=3200,
        )

    def edge_margin(self) -> int:
        return 8

    def set_roam_mode(self, mode: str) -> None:
        self.roam_mode = mode
        self.roam_direction = 1
        self.roam_edge_index = 0
        self.edge_drift_until = 0.0

        messages = {
            "off": "我先乖乖待着。",
            "bottom": "底部散步开始。",
            "edge": "边缘巡游开始。",
        }
        if mode == "bottom":
            self.move_to_bottom_lane()
        elif mode == "edge":
            self.move_to_nearest_edge_corner()

        if mode != "off":
            self.play_state("movement_run")
        else:
            self.return_to_idle()
        self.show_bubble(messages.get(mode, "移动模式已切换。"), 2600)

    def update_roaming(self) -> None:
        if self.roam_mode == "off" or self.startup_active or self.exiting:
            return
        if self.typing_active or self.focus_active or self.drag_offset is not None:
            return

        if self.roam_mode == "bottom":
            self.ensure_movement_state()
            self.update_bottom_roam()
        elif self.roam_mode == "edge":
            self.ensure_movement_state(edge=True)
            self.update_edge_roam()

    def ensure_movement_state(self, *, edge: bool = False) -> None:
        now = time.monotonic()
        if edge and now > self.edge_drift_until and random.random() < 0.006:
            self.edge_drift_until = now + 1.8
            self.play_state("movement_drift")
            return
        if now <= self.edge_drift_until:
            return
        if self.current_state_id not in {"movement_run", "movement_drift"}:
            self.play_state("movement_run")

    def move_to_bottom_lane(self) -> None:
        screen = self.screen_geometry()
        margin = self.edge_margin()
        y = screen.bottom() - self.height() - margin
        x = max(screen.left() + margin, min(self.pos().x(), screen.right() - self.width() - margin))
        self.move(QPoint(x, y))

    def update_bottom_roam(self) -> None:
        screen = self.screen_geometry()
        margin = self.edge_margin()
        left = screen.left() + margin
        right = screen.right() - self.width() - margin
        bottom = screen.bottom() - self.height() - margin

        x = self.pos().x() + self.roam_speed * self.roam_direction
        if x >= right:
            x = right
            self.roam_direction = -1
        elif x <= left:
            x = left
            self.roam_direction = 1

        self.move(QPoint(x, bottom))

    def edge_waypoints(self) -> list[QPoint]:
        screen = self.screen_geometry()
        margin = self.edge_margin()
        left = screen.left() + margin
        right = screen.right() - self.width() - margin
        top = screen.top() + margin
        bottom = screen.bottom() - self.height() - margin
        return [
            QPoint(left, bottom),
            QPoint(right, bottom),
            QPoint(right, top),
            QPoint(left, top),
        ]

    def move_to_nearest_edge_corner(self) -> None:
        waypoints = self.edge_waypoints()
        current = self.pos()
        distances = [
            abs(point.x() - current.x()) + abs(point.y() - current.y())
            for point in waypoints
        ]
        self.roam_edge_index = distances.index(min(distances))
        self.move(waypoints[self.roam_edge_index])

    def update_edge_roam(self) -> None:
        waypoints = self.edge_waypoints()
        target = waypoints[(self.roam_edge_index + 1) % len(waypoints)]
        current = self.pos()
        next_pos = self.step_towards(current, target, self.roam_speed)
        self.move(next_pos)

        if (
            abs(next_pos.x() - target.x()) <= self.roam_speed
            and abs(next_pos.y() - target.y()) <= self.roam_speed
        ):
            self.move(target)
            self.roam_edge_index = (self.roam_edge_index + 1) % len(waypoints)

    @staticmethod
    def step_towards(current: QPoint, target: QPoint, step: int) -> QPoint:
        def axis(now: int, goal: int) -> int:
            if abs(goal - now) <= step:
                return goal
            return now + step if goal > now else now - step

        return QPoint(axis(current.x(), target.x()), axis(current.y(), target.y()))

    def pet_once(self) -> None:
        state_id = random.choice(["idle_cute", "relax_ticklish", "idle_good"])
        self.grant_capped_exp(2, interaction_value_delta=2)
        self.play_state(
            state_id,
            random.choice(self.dialogue_lines("pet")),
            return_after_ms=3200,
        )
        self.show_pending_level_up()

    def feed_food(self) -> None:
        now = time.monotonic()
        if now - self.last_feed_at < 90:
            state_id = "food_not_hungry"
            message = "不饿啦，先放一放。"
            exp = 0
        else:
            state_id = random.choice(["food_eat", "food_hungry"])
            message = random.choice(self.dialogue_lines("food"))
            exp = 5
            self.last_feed_at = now

        if exp:
            self.grant_capped_exp(exp, interaction_value_delta=5)
        self.play_state(state_id, message, return_after_ms=4200)
        self.show_pending_level_up()

    def give_flower(self) -> None:
        self.grant_capped_exp(5, interaction_value_delta=5)
        self.play_state(
            "gift_flower",
            random.choice(self.dialogue_lines("gift")),
            return_after_ms=4200,
        )
        self.show_pending_level_up()

    def start_focus(self, minutes: int = 25) -> None:
        self.roam_mode = "off"
        self.focus_active = True
        self.focus_seconds_left = minutes * 60
        self.focus_timer.start(1000)
        self.play_state(
            "work_study",
            random.choice(self.dialogue_lines("study")),
            bubble_ms=4200,
        )

    def stop_focus(self) -> None:
        self.focus_active = False
        self.focus_seconds_left = 0
        self.focus_timer.stop()
        self.play_state(
            random.choice(["event_cheer_dance", "event_fireworks"]),
            "专注已结束，先喘口气。",
            bubble_ms=3600,
            return_after_ms=4200,
        )

    def take_break(self) -> None:
        state_id = random.choice(
            ["relax_slacking", "relax_swing", "relax_sleeping", "relax_go_sleep"]
        )
        self.play_state(
            state_id,
            random.choice(self.dialogue_lines("break")),
            bubble_ms=3600,
            return_after_ms=7000,
        )

    def remind_drink_water(self) -> None:
        if self.protected_mode():
            return
        self.play_state(
            "event_raise_hand",
            "该喝水了。",
            bubble_ms=4200,
            return_after_ms=4200,
        )

    def remind_stretch(self) -> None:
        if self.focus_active or self.typing_active or self.exiting:
            return
        state_id = random.choice(["exercise", "stretch"])
        self.play_state(
            state_id,
            random.choice(self.dialogue_lines("reminder")),
            bubble_ms=4200,
            return_after_ms=5200,
        )

    def encourage(self) -> None:
        self.play_state(
            "event_cheer_dance",
            random.choice(self.dialogue_lines("encourage")),
            bubble_ms=3800,
            return_after_ms=4200,
        )

    def celebrate(self) -> None:
        self.grant_capped_exp(3, interaction_value_delta=3)
        state_id = random.choice(
            ["event_fireworks", "event_dance", "event_dance3", "event_happy_fly"]
        )
        self.play_state(
            state_id,
            random.choice(self.dialogue_lines("celebrate")),
            bubble_ms=4200,
            return_after_ms=5000,
        )
        self.show_pending_level_up()

    def switch_idle_now(self) -> None:
        state = self.select_random_state()
        self.remember_random_state(state.id)
        self.play_state(
            state.id,
            random.choice(self.dialogue_lines(state.bubble_group)),
            bubble_ms=3200,
            return_after_ms=4200,
        )

    def next_random_state(self) -> PetState:
        states = self.random_enabled_states()
        if not states:
            return self.states[self.default_state]
        self.manual_state_index = (self.manual_state_index + 1) % len(states)
        return states[self.manual_state_index]

    def switch_to_next_state(self) -> None:
        if self.startup_active or self.exiting:
            return
        self.return_timer.stop()
        state = self.next_random_state()
        self.remember_random_state(state.id)
        message = f"切到：{state.label}"
        if state.random_group != "daily":
            lines = self.dialogue_lines(state.bubble_group)
            if lines:
                message = random.choice(lines)
        self.play_state(
            state.id,
            message,
            bubble_ms=3200,
            return_after_ms=5200,
        )

    def double_click_jump(self) -> None:
        self.play_state(
            "event_jump",
            random.choice(self.dialogue_lines("celebrate")),
            return_after_ms=3200,
        )

    def single_gacha_cost(self) -> int:
        if self.profile.get("last_discount_draw_date") != date.today().isoformat():
            return GACHA_DAILY_DISCOUNT_COST
        return GACHA_SINGLE_COST

    def open_gacha_machine(self) -> None:
        cost = self.single_gacha_cost()
        message = (
            "奶茶鼠扭蛋机\n"
            f"金币 {int(self.profile['coins'])}\n"
            f"单抽 {cost} 金币，十连 {GACHA_TEN_COST} 金币\n"
            f"奶茶碎片 {int(self.profile['milk_tea_shards'])}\n"
            f"超稀有保底 {int(self.profile['gacha_pity_counter'])}/{GACHA_SUPER_PITY}"
        )
        self.play_state("event_nod" if "event_nod" in self.states else "idle_nod")
        self.show_status_bubble(message, 6400)

    def draw_gacha_once(self) -> None:
        cost = self.single_gacha_cost()
        if not self.spend_coins(cost):
            self.show_bubble(f"金币不够啦，还差 {cost - int(self.profile['coins'])} 枚。", 3600)
            return

        if cost == GACHA_DAILY_DISCOUNT_COST:
            self.profile["last_discount_draw_date"] = date.today().isoformat()

        result, self.profile = gacha_mod.perform_gacha_draw(self.gacha_pool, self.profile, self.accessories)
        self._save_profile()
        self.present_gacha_results([result], cost)

    def draw_gacha_ten(self) -> None:
        if not self.spend_coins(GACHA_TEN_COST):
            self.show_bubble(
                f"十连需要 {GACHA_TEN_COST} 金币，还差 {GACHA_TEN_COST - int(self.profile['coins'])} 枚。",
                4200,
            )
            return

        results = [self.perform_gacha_draw() for _ in range(10)]
        if not any(gacha_mod.rarity_rank(item["rarity"]) >= gacha_mod.rarity_rank("rare") for item in results):
            results[-1] = self.perform_gacha_draw(force_min_rarity="rare")

        self._save_profile()
        self.present_gacha_results(results, GACHA_TEN_COST)

    def spend_coins(self, amount: int) -> bool:
        if int(self.profile["coins"]) < amount:
            return False
        self.profile["coins"] = int(self.profile["coins"]) - amount
        return True

    def current_bubble_frame_id(self) -> str:
        equipped = str(self.profile.get("equipped_bubble_frame", ""))
        if not equipped:
            return ""
        if equipped in self.profile.get("owned_bubble_frames", []):
            return equipped
        return ""

    def bubble_frame_label(self, frame_id: str | None = None) -> str:
        frame_id = self.current_bubble_frame_id() if frame_id is None else frame_id
        if not frame_id:
            return str(BUBBLE_FRAME_STYLES[""]["label"])
        return gacha_mod.bubble_frame_rewards(self.gacha_pool).get(
            frame_id,
            str(BUBBLE_FRAME_STYLES.get(frame_id, {}).get("label", frame_id)),
        )

    def equip_bubble_frame(self, frame_id: str) -> None:
        if frame_id and frame_id not in self.profile.get("owned_bubble_frames", []):
            return
        self.profile["equipped_bubble_frame"] = frame_id
        self._save_profile()
        self.apply_layout()
        if frame_id:
            self.show_bubble(f"气泡样式已切换：{self.bubble_frame_label(frame_id)}", 2800)
        else:
            self.show_bubble("气泡样式已切回默认。", 2600)

    def show_bubble_frames_panel(self) -> None:
        owned = self.profile.get("owned_bubble_frames", [])
        if not owned:
            self.show_status_bubble("奶茶鼠气泡样式\n还没有获得气泡边框，可以从扭蛋机抽到。", 5200)
            return
        lines = [
            "奶茶鼠气泡样式",
            f"当前使用：{self.bubble_frame_label()}",
            f"已获得边框：{len(owned)} 个",
        ]
        frame_map = gacha_mod.bubble_frame_rewards(self.gacha_pool)
        lines.extend(f"- {frame_map.get(frame_id, frame_id)}" for frame_id in owned)
        self.show_status_bubble("\n".join(lines), 7200)

    def play_collected_performance(self, performance_id: str) -> None:
        if performance_id not in self.profile.get("owned_special_performances", []):
            return
        data = gacha_mod.performance_rewards(self.gacha_pool).get(performance_id)
        if not data:
            return
        self.play_state(data["state_id"], f"演出回放：{data['title']}", bubble_ms=3400, return_after_ms=5200)

    def show_performances_panel(self) -> None:
        owned = self.profile.get("owned_special_performances", [])
        if not owned:
            self.show_status_bubble("奶茶鼠演出收藏\n还没有获得演出，可以从扭蛋机抽到。", 5200)
            return
        performance_map = gacha_mod.performance_rewards(self.gacha_pool)
        lines = ["奶茶鼠演出收藏", f"已收藏演出：{len(owned)} 个"]
        lines.extend(
            f"- {performance_map.get(performance_id, {}).get('title', performance_id)}"
            for performance_id in owned
        )
        self.show_status_bubble("\n".join(lines), 7200)

    def equipped_title_label(self) -> str:
        equipped = str(self.profile.get("equipped_title", ""))
        if not equipped:
            return "未佩戴"
        return gacha_mod.title_rewards(self.gacha_pool).get(equipped, equipped)

    def equip_title(self, title_id: str) -> None:
        if title_id and title_id not in self.profile.get("owned_titles", []):
            return
        self.profile["equipped_title"] = title_id
        self._save_profile()
        label = self.equipped_title_label()
        self.show_bubble("称号已摘下。" if not title_id else f"已佩戴称号：{label}", 2600)

    def show_titles_panel(self) -> None:
        owned = self.profile.get("owned_titles", [])
        title_map = gacha_mod.title_rewards(self.gacha_pool)
        if not owned:
            self.show_status_bubble("奶茶鼠称号\n还没有获得称号，可以从扭蛋机抽到。", 5200)
            return
        lines = ["奶茶鼠称号", f"当前佩戴：{self.equipped_title_label()}"]
        lines.extend(f"- {title_map.get(title_id, title_id)}" for title_id in owned)
        self.show_status_bubble("\n".join(lines), 7200)

    def present_gacha_results(self, results: list[dict[str, Any]], spent: int) -> None:
        best = max(results, key=lambda item: gacha_mod.rarity_rank(str(item["rarity"])))
        self.play_state(best["state_id"], return_after_ms=5200)

        if len(results) == 1:
            item = results[0]
            message = (
                f"扭蛋结果：{gacha_mod.rarity_label(item['rarity'])}\n"
                f"{item['detail']}\n"
                f"消耗金币 {spent}，剩余 {int(self.profile['coins'])}"
            )
            self.show_status_bubble(message, 7600)
            self.show_pending_level_up()
            return

        counts: dict[str, int] = {}
        for item in results:
            label = gacha_mod.rarity_label(str(item["rarity"]))
            counts[label] = counts.get(label, 0) + 1

        highlights = [
            f"{gacha_mod.rarity_label(item['rarity'])}：{item['detail']}"
            for item in results
            if gacha_mod.rarity_rank(str(item["rarity"])) >= gacha_mod.rarity_rank("rare")
        ][:4]
        if not highlights:
            highlights = [f"普通：{results[-1]['detail']}"]
        summary = "、".join(f"{key}x{value}" for key, value in counts.items())
        message = (
            "十连结果  ૮ ˶ᵔ ᵕ ᵔ˶ ა\n"
            f"{summary}\n"
            + "\n".join(highlights)
            + f"\n消耗金币 {spent}，剩余 {int(self.profile['coins'])}"
        )
        self.show_status_bubble(message, 9000)
        self.show_pending_level_up()

    def show_status_panel(self) -> None:
        level = int(self.profile["level"])
        title = title_for_level(level)
        total = self.format_duration(int(self.profile["total_companion_seconds"]))
        today = self.format_duration(int(self.profile["today_companion_seconds"]))
        current_exp = int(self.profile["exp"])
        next_exp = required_exp_for_level(level) if level < MAX_LEVEL else 0
        exp_text = "满级啦" if level >= MAX_LEVEL else f"{current_exp}/{next_exp}"
        dialogue_count = len(self.profile.get("owned_dialogues", [])) + sum(
            len(item.get("dialogues", []))
            for item in self.gacha_pool.get("rewards", [])
            if item.get("id") in self.profile.get("owned_dialogue_packs", [])
        )
        message = (
            "奶茶鼠小档案  ૮ ˶ᵔ ᵕ ᵔ˶ ა\n"
            f"♡ Lv.{level}  {title}\n"
            f"🏷 称号  {self.equipped_title_label()}\n"
            f"☁ 总陪伴  {total}\n"
            f"☀ 今日陪伴  {today}\n"
            f"✦ 累计互动值  {int(self.profile['interaction_value'])}\n"
            f"🍡 升级互动值  {exp_text}\n"
            f"🪙 金币  {int(self.profile['coins'])}\n"
            f"🧋 奶茶碎片  {int(self.profile['milk_tea_shards'])}\n"
            f"☕ 今日互动值  {int(self.profile['today_interaction_exp'])}/{DAILY_INTERACTION_EXP_CAP}\n"
            f"🎖 已获得称号  {len(self.profile.get('owned_titles', []))} 个\n"
            f"🫧 气泡样式  {self.bubble_frame_label()}（{len(self.profile.get('owned_bubble_frames', []))} 个）\n"
            f"🎬 演出收藏  {len(self.profile.get('owned_special_performances', []))} 个\n"
            f"💬 已解锁口头禅  {dialogue_count} 条\n"
            f"⏱ 今日专注  {int(self.profile['focus_completed_count'])} 次"
        )
        self.show_status_bubble(message)

    @staticmethod
    def format_duration(seconds: int) -> str:
        minutes = max(0, seconds) // 60
        hours, mins = divmod(minutes, 60)
        if hours:
            return f"{hours}小时{mins}分"
        return f"{mins}分"

    def set_scale_percent(self, percent: int) -> None:
        self.user_scale = percent / 100
        self.pet_size = max(72, int(BASE_PET_SIZE * self.user_scale))
        self.window_width = max(190, int(BASE_WINDOW_WIDTH * self.user_scale))
        self.window_height = max(
            self.pet_size + 80,
            int(BASE_WINDOW_HEIGHT * self.user_scale),
        )
        self.bubble_height = max(58, int(BASE_BUBBLE_HEIGHT * self.user_scale))
        self.apply_layout()
        self.play_state(self.current_state_id)
        if self.roam_mode == "bottom":
            self.move_to_bottom_lane()
        elif self.roam_mode == "edge":
            self.move_to_nearest_edge_corner()

    def contextMenuEvent(self, event: Any) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            f"""
            QMenu {{
                background: #fff8ee;
                color: #6f4b3e;
                border: 1px solid #d7aa86;
                padding: 6px;
                font-family: {FONT_FAMILY};
                font-size: 13px;
            }}
            QMenu::item {{
                padding: 7px 26px 7px 18px;
                border-radius: 6px;
            }}
            QMenu::item:selected {{
                background: #f4d7b6;
            }}
            """
        )

        actions_menu = menu.addMenu("常用动作")
        self.add_action(actions_menu, "摸摸奶茶鼠", self.pet_once)
        self.add_action(actions_menu, "喂点东西", self.feed_food)
        self.add_action(actions_menu, "送你花花", self.give_flower)
        self.add_action(actions_menu, "休息一下", self.take_break)
        self.add_action(actions_menu, "鼓励我一下", self.encourage)
        self.add_action(actions_menu, "庆祝一下", self.celebrate)
        self.add_action(actions_menu, "久坐伸展", self.remind_stretch)

        focus_menu = menu.addMenu("聊天和成长")
        if self.focus_active:
            self.add_action(focus_menu, "结束专注", self.stop_focus)
        else:
            self.add_action(focus_menu, "开始专注", self.start_focus)
        self.add_action(focus_menu, "状态面板", self.show_status_panel)

        title_menu = focus_menu.addMenu("称号")
        self.add_action(title_menu, "查看称号", self.show_titles_panel)
        owned_titles = self.profile.get("owned_titles", [])
        if owned_titles:
            self.add_action(title_menu, "摘下称号", lambda: self.equip_title(""))
            title_menu.addSeparator()
            title_map = gacha_mod.title_rewards(self.gacha_pool)
            for title_id in owned_titles:
                label = title_map.get(title_id, title_id)
                prefix = "✓ " if title_id == self.profile.get("equipped_title", "") else ""
                self.add_action(title_menu, f"{prefix}佩戴 {label}", lambda title_id=title_id: self.equip_title(title_id))
        else:
            empty_action = QAction("还没有称号", title_menu)
            empty_action.setEnabled(False)
            title_menu.addAction(empty_action)

        bubble_menu = focus_menu.addMenu("气泡样式")
        self.add_action(bubble_menu, "查看气泡样式", self.show_bubble_frames_panel)
        default_prefix = "✓ " if not self.current_bubble_frame_id() else ""
        self.add_action(bubble_menu, f"{default_prefix}使用 默认奶茶气泡", lambda: self.equip_bubble_frame(""))
        owned_frames = self.profile.get("owned_bubble_frames", [])
        if owned_frames:
            bubble_menu.addSeparator()
            frame_map = gacha_mod.bubble_frame_rewards(self.gacha_pool)
            for frame_id in owned_frames:
                label = frame_map.get(frame_id, frame_id)
                prefix = "✓ " if frame_id == self.current_bubble_frame_id() else ""
                self.add_action(bubble_menu, f"{prefix}使用 {label}", lambda frame_id=frame_id: self.equip_bubble_frame(frame_id))
        else:
            empty_action = QAction("还没有气泡边框", bubble_menu)
            empty_action.setEnabled(False)
            bubble_menu.addAction(empty_action)

        performance_menu = focus_menu.addMenu("演出收藏")
        self.add_action(performance_menu, "查看演出收藏", self.show_performances_panel)
        owned_performances = self.profile.get("owned_special_performances", [])
        if owned_performances:
            performance_menu.addSeparator()
            performance_map = gacha_mod.performance_rewards(self.gacha_pool)
            for performance_id in owned_performances:
                label = performance_map.get(performance_id, {}).get("title", performance_id)
                self.add_action(performance_menu, f"播放 {label}", lambda performance_id=performance_id: self.play_collected_performance(performance_id))
        else:
            empty_action = QAction("还没有演出收藏", performance_menu)
            empty_action.setEnabled(False)
            performance_menu.addAction(empty_action)

        ai_menu = focus_menu.addMenu("AI 聊天")
        self.add_action(ai_menu, "和奶茶鼠聊天", self.ask_ai_chat)
        self.add_action(ai_menu, "配置 API", self.configure_ai_chat)
        self.add_action(ai_menu, "清空聊天上下文", self.clear_ai_chat)

        gacha_menu = menu.addMenu("奶茶鼠扭蛋机")
        balance_action = QAction(
            f"金币 {int(self.profile['coins'])} / 碎片 {int(self.profile['milk_tea_shards'])}",
            gacha_menu,
        )
        balance_action.setEnabled(False)
        gacha_menu.addAction(balance_action)
        self.add_action(gacha_menu, "查看扭蛋机", self.open_gacha_machine)
        self.add_action(gacha_menu, f"单抽（{self.single_gacha_cost()} 金币）", self.draw_gacha_once)
        self.add_action(gacha_menu, f"十连（{GACHA_TEN_COST} 金币）", self.draw_gacha_ten)

        accessory_menu = menu.addMenu("配饰")
        current_state = self.current_accessory_state()
        self.add_action(
            accessory_menu,
            "隐藏当前配饰" if current_state.get("visible", True) else "显示当前配饰",
            lambda: self.set_accessory_visible(not bool(current_state.get("visible", True))),
        )
        self.add_action(accessory_menu, "小一点", lambda: self.adjust_accessory_scale(-0.1))
        self.add_action(accessory_menu, "默认大小", lambda: self.adjust_accessory_scale(1.0 - float(self.current_accessory_state().get("scale", 1.0))))
        self.add_action(accessory_menu, "大一点", lambda: self.adjust_accessory_scale(0.1))
        self.add_action(accessory_menu, "重置位置", self.reset_accessory_position)
        available = self.available_accessory_ids()
        if available:
            accessory_menu.addSeparator()
            for accessory_id in available:
                label = self.accessories["items"][accessory_id].get("label", accessory_id)
                prefix = "✓ " if accessory_id == self.current_accessory_id() else ""
                self.add_action(accessory_menu, f"{prefix}佩戴 {label}", lambda accessory_id=accessory_id: self.equip_accessory(accessory_id))
        display_menu = menu.addMenu("显示和移动")
        self.add_action(display_menu, "换个常驻动作", self.switch_idle_now)
        self.add_action(display_menu, "召唤回来", self.summon_back)

        move_menu = display_menu.addMenu("移动模式")
        self.add_action(move_menu, "停止移动", lambda: self.set_roam_mode("off"))
        self.add_action(move_menu, "底部散步", lambda: self.set_roam_mode("bottom"))
        self.add_action(move_menu, "边缘巡游", lambda: self.set_roam_mode("edge"))

        size_menu = display_menu.addMenu("大小")
        for percent in (30, 40, 50, 60, 70, 80, 90, 100):
            self.add_action(size_menu, f"{percent}%", lambda percent=percent: self.set_scale_percent(percent))

        opacity_menu = display_menu.addMenu("透明度")
        self.add_action(opacity_menu, "70%", lambda: self.setWindowOpacity(0.7))
        self.add_action(opacity_menu, "85%", lambda: self.setWindowOpacity(0.85))
        self.add_action(opacity_menu, "100%", lambda: self.setWindowOpacity(1.0))

        settings_menu = menu.addMenu("设置")
        typing_title = "关闭打字跟随" if self.typing_follow_enabled else "开启打字跟随"
        self.add_action(settings_menu, typing_title, self.toggle_typing_follow)
        bubble_title = "关闭打字气泡" if self.typing_bubble_enabled else "开启打字气泡"
        self.add_action(settings_menu, bubble_title, self.toggle_typing_bubble)

        agent_menu = menu.addMenu("Coding Agent")
        agent_detect_title = "关闭 Agent 检测" if self.agent_detection_enabled else "开启 Agent 检测"
        self.add_action(agent_menu, agent_detect_title, self.toggle_agent_detection)

        if self.agent_detection_enabled and self._agent_monitor is not None:
            agent_menu.addSeparator()
            claude_installed = self._agent_monitor.is_claude_code_hooks_installed()
            claude_title = "卸载 Claude Code Hooks" if claude_installed else "安装 Claude Code Hooks"
            self.add_action(agent_menu, claude_title, self.toggle_claude_code_hooks)

            codex_installed = self._agent_monitor.is_codex_cli_hooks_installed()
            codex_title = "卸载 Codex Hooks" if codex_installed else "安装 Codex Hooks"
            self.add_action(agent_menu, codex_title, self.toggle_codex_cli_hooks)

            agent_menu.addSeparator()
            trae_title = "关闭 Trae IDE 检测" if self.trae_detection_enabled else "开启 Trae IDE 检测"
            self.add_action(agent_menu, trae_title, self.toggle_trae_detection)

            agent_menu.addSeparator()
            self.add_action(agent_menu, "Agent 状态", self.show_agent_status)

        menu.addSeparator()
        self.add_action(menu, "状态面板", self.show_status_panel)

        menu.addSeparator()
        self.add_action(menu, "退出", self.exit_sequence)
        menu.exec_(QCursor.pos())

    @staticmethod
    def add_action(menu: QMenu, title: str, callback: Any) -> QAction:
        action = QAction(title, menu)
        action.triggered.connect(lambda checked=False: callback())
        menu.addAction(action)
        return action

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.RightButton and self.accessory_hit_test(event.pos()):
            self.accessory_pending_context_menu = True
            self.accessory_press_pos = event.pos()
            QTimer.singleShot(250, self.begin_accessory_drag_if_pending)
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            self.drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            self.press_pos = event.globalPos()
            if not self.startup_active and not self.exiting:
                self.play_state("movement_drift", random.choice(self.dialogue_lines("movement")), 1800)
            event.accept()

    def mouseMoveEvent(self, event: Any) -> None:
        if event.buttons() & Qt.RightButton and self.accessory_dragging:
            self.move_accessory_to(event.pos())
            event.accept()
            return

        if event.buttons() & Qt.LeftButton and self.drag_offset is not None:
            self.move(event.globalPos() - self.drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.RightButton:
            if self.accessory_dragging:
                self.finish_accessory_drag()
                event.accept()
                return
            if self.accessory_pending_context_menu:
                self.accessory_pending_context_menu = False
                self.accessory_press_pos = None
                self.contextMenuEvent(event)
                event.accept()
                return

        if event.button() != Qt.LeftButton or self.press_pos is None:
            return

        moved = (event.globalPos() - self.press_pos).manhattanLength()
        self.drag_offset = None
        self.press_pos = None
        if moved > 160:
            self.play_state("movement_jump_far", return_after_ms=2600)
        elif moved < 6 and not self.click_blocked:
            QTimer.singleShot(180, self.pet_once)
        elif self.roam_mode != "off":
            self.play_state("movement_run")
        else:
            self.return_to_idle()
        self.update_accessory_label()
        self.click_blocked = False
        event.accept()

    def mouseDoubleClickEvent(self, event: Any) -> None:
        if event.button() == Qt.LeftButton:
            self.click_blocked = True
            self.switch_to_next_state()
            event.accept()

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self.ensure_always_on_top)

    def closeEvent(self, event: Any) -> None:
        if self.exiting:
            self._save_profile()
            event.accept()
            return
        event.ignore()
        self.exit_sequence()
