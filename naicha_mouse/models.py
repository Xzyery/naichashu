"""Data models: PetState, DEFAULT_PROFILE, BUBBLE_FRAME_STYLES."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PetState:
    id: str
    label: str
    category: str
    file: str
    bubble_group: str
    is_random_enabled: bool
    random_group: str
    random_weight: int
    triggers: tuple[str, ...]


DEFAULT_PROFILE: dict[str, Any] = {
    "level": 1,
    "exp": 0,
    "total_companion_seconds": 0,
    "today_companion_seconds": 0,
    "interaction_value": 0,
    "today_interaction_exp": 0,
    "today_interactions": 0,
    "focus_completed_count": 0,
    "last_opened_date": "",
    "companion_exp_seconds_buffer": 0,
    "coins": 0,
    "total_coins_earned": 0,
    "today_coin_earned": 0,
    "milk_tea_shards": 0,
    "owned_accessories": [],
    "temporary_accessories": {},
    "accessories": {},
    "equipped_accessory": "",
    "owned_titles": [],
    "equipped_title": "",
    "owned_bubble_frames": [],
    "equipped_bubble_frame": "",
    "owned_special_performances": [],
    "owned_dialogues": [],
    "owned_dialogue_packs": [],
    "dialogue_rewards_seen": {},
    "gacha_draw_count": 0,
    "gacha_pity_counter": 0,
    "last_discount_draw_date": "",
}

BUBBLE_FRAME_STYLES: dict[str, dict[str, Any]] = {
    "": {
        "label": "默认奶茶气泡",
        "normal": {
            "background": "rgba(255, 248, 238, 232)",
            "color": "#6f4b3e",
            "border": "2px solid rgba(178, 128, 98, 210)",
            "padding": "6px 10px",
        },
        "status": {
            "background": "rgba(255, 250, 242, 246)",
            "color": "#6f4b3e",
            "border": "2px solid rgba(188, 132, 103, 230)",
            "padding": "10px 14px",
        },
        "decoration": "♡ 奶茶鼠",
        "status_decoration": "♡",
        "decoration_color": "rgba(178, 128, 98, 185)",
    },
    "rare_bubble_cream": {
        "label": "奶盖气泡边框",
        "normal": {
            "background": "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255, 255, 247, 244), stop:0.42 rgba(255, 251, 235, 240), stop:1 rgba(255, 242, 219, 236))",
            "color": "#6a4536",
            "border": "3px solid rgba(218, 169, 115, 232)",
            "padding": "8px 12px",
        },
        "status": {
            "background": "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255, 255, 247, 250), stop:0.42 rgba(255, 251, 235, 248), stop:1 rgba(255, 242, 219, 246))",
            "color": "#6a4536",
            "border": "3px solid rgba(218, 169, 115, 238)",
            "padding": "10px 14px",
        },
        "decoration": "奶盖 ◦ ◦",
        "status_decoration": "奶盖",
        "decoration_color": "rgba(194, 128, 80, 190)",
    },
    "perm_cream_frame": {
        "label": "永久奶盖气泡边框",
        "normal": {
            "background": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(255, 255, 238, 246), stop:0.5 rgba(255, 246, 219, 242), stop:1 rgba(255, 235, 198, 238))",
            "color": "#643f31",
            "border": "3px solid rgba(236, 186, 94, 240)",
            "padding": "8px 12px",
        },
        "status": {
            "background": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(255, 255, 238, 252), stop:0.5 rgba(255, 246, 219, 250), stop:1 rgba(255, 235, 198, 248))",
            "color": "#643f31",
            "border": "3px solid rgba(236, 186, 94, 245)",
            "padding": "10px 14px",
        },
        "decoration": "✦ 满糖奶盖 ✦",
        "status_decoration": "满糖",
        "decoration_color": "rgba(197, 125, 50, 205)",
    },
}
