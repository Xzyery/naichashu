"""Profile and configuration load/save, level/exp calculations."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from naicha_mouse.constants import MAX_LEVEL
from naicha_mouse.models import DEFAULT_PROFILE, PetState
from naicha_mouse.resources import (
    ACCESSORY_CONFIG_PATH,
    AI_CONFIG_PATH,
    BASE_DIR,
    DIALOGUES_PATH,
    GACHA_POOL_PATH,
    PROFILE_PATH,
    STATE_MAP_PATH,
    resolve_asset_path,
)


def load_state_config() -> tuple[
    dict[str, PetState], Path, str, list[str], str, dict[str, int]
]:
    with STATE_MAP_PATH.open("r", encoding="utf-8") as file:
        raw = json.load(file)

    asset_folder = BASE_DIR / raw.get("assetFolder", "IMG_5791")
    states: dict[str, PetState] = {}
    missing_assets: list[str] = []

    for item in raw.get("states", []):
        filename = item.get("file") or item.get("gif")
        if not filename:
            continue
        asset_path = resolve_asset_path(asset_folder, filename)
        if not asset_path.exists():
            missing_assets.append(filename)
            continue

        states[item["id"]] = PetState(
            id=item["id"],
            label=item.get("label", item["id"]),
            category=item.get("category", "idle"),
            file=filename,
            bubble_group=item.get("bubble_group", "idle"),
            is_random_enabled=bool(item.get("is_random_enabled", False)),
            random_group=item.get("random_group", "none"),
            random_weight=max(0, int(item.get("random_weight", 0))),
            triggers=tuple(item.get("triggers", [])),
        )

    if not states:
        detail = "、".join(missing_assets[:5]) if missing_assets else "无可用状态"
        raise RuntimeError(f"没有可播放的奶茶鼠素材：{detail}")

    default_state = raw.get("defaultState", "idle_static_cute")
    if default_state not in states:
        default_state = next(iter(states))

    startup_sequence = [
        state_id for state_id in raw.get("startupSequence", []) if state_id in states
    ]
    if not startup_sequence:
        startup_sequence = [default_state]

    exit_state = raw.get("exitState", "exit_goodbye")
    if exit_state not in states:
        exit_state = default_state

    random_groups = {
        group: max(0, int(weight))
        for group, weight in raw.get("randomGroups", {}).items()
    }
    return states, asset_folder, default_state, startup_sequence, exit_state, random_groups


def load_dialogues() -> dict[str, list[str]]:
    fallback = {
        "startup": ["奶茶鼠已到岗。"],
        "exit": ["我先下班啦，明天见。"],
        "idle": ["我在这里陪你。"],
        "typing": ["咔哒咔哒"],
        "level_up": ["升级啦，奶茶鼠变得更会陪伴了。"],
    }
    if not DIALOGUES_PATH.exists():
        return fallback

    with DIALOGUES_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    for key, value in fallback.items():
        data.setdefault(key, value)
    return data


def load_gacha_pool() -> dict[str, Any]:
    if not GACHA_POOL_PATH.exists():
        return {
            "rarities": {"normal": 68, "rare": 24, "super_rare": 7, "hidden": 1},
            "rewards": [],
        }

    with GACHA_POOL_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    data.setdefault("rarities", {"normal": 68, "rare": 24, "super_rare": 7, "hidden": 1})
    data.setdefault("rewards", [])
    return data


def load_accessory_config() -> dict[str, Any]:
    if not ACCESSORY_CONFIG_PATH.exists():
        return {"default": "", "items": {}}

    with ACCESSORY_CONFIG_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    data.setdefault("default", "")
    data.setdefault("items", {})
    return data


def load_ai_config() -> dict[str, str]:
    default = {
        "provider": "openai",
        "base_url": "",
        "api_key": "",
        "model": "",
    }
    if not AI_CONFIG_PATH.exists():
        return default
    try:
        with AI_CONFIG_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return default
    return {
        "provider": str(data.get("provider", "openai")),
        "base_url": str(data.get("base_url", "")),
        "api_key": str(data.get("api_key", "")),
        "model": str(data.get("model", "")),
    }


def save_ai_config(config: dict[str, str]) -> None:
    with AI_CONFIG_PATH.open("w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)


def load_profile() -> tuple[dict[str, Any], bool]:
    profile = DEFAULT_PROFILE.copy()
    loaded: dict[str, Any] = {}
    if PROFILE_PATH.exists():
        with PROFILE_PATH.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
        profile.update({key: loaded.get(key, value) for key, value in profile.items()})

    for key, default_value in DEFAULT_PROFILE.items():
        if isinstance(default_value, int):
            try:
                profile[key] = int(profile.get(key, default_value))
            except (TypeError, ValueError):
                profile[key] = default_value
        elif isinstance(default_value, list):
            value = profile.get(key, default_value)
            profile[key] = list(value) if isinstance(value, list) else default_value.copy()
        elif isinstance(default_value, dict):
            value = profile.get(key, default_value)
            profile[key] = dict(value) if isinstance(value, dict) else default_value.copy()
        elif isinstance(default_value, str):
            profile[key] = str(profile.get(key, default_value) or "")

    if "coins" not in loaded:
        starter_coins = max(
            int(profile.get("coins", 0)),
            int(profile.get("exp", 0)),
            int(profile.get("interaction_value", 0)),
        )
        profile["coins"] = starter_coins
        profile["total_coins_earned"] = max(int(profile["total_coins_earned"]), starter_coins)
        profile["today_coin_earned"] = max(
            int(profile["today_coin_earned"]),
            int(profile.get("today_interaction_exp", 0)),
        )

    today = date.today().isoformat()
    daily_start_pending = profile.get("last_opened_date") != today
    if daily_start_pending:
        profile["today_companion_seconds"] = 0
        profile["today_interaction_exp"] = 0
        profile["today_interactions"] = 0
        profile["focus_completed_count"] = 0
        profile["today_coin_earned"] = 0
        profile["last_opened_date"] = today

    profile["level"] = max(1, min(MAX_LEVEL, int(profile["level"])))
    if int(profile["level"]) >= MAX_LEVEL:
        profile["exp"] = max(0, int(profile["exp"]))
    return profile, daily_start_pending


def save_profile(profile: dict[str, Any]) -> None:
    with PROFILE_PATH.open("w", encoding="utf-8") as file:
        json.dump(profile, file, ensure_ascii=False, indent=2)


def required_exp_for_level(level: int) -> int:
    return int(55 + level * level * 0.25 + level * 18)


def title_for_level(level: int) -> str:
    titles = [
        (52, "满糖奶茶鼠"),
        (35, "超级陪伴鼠"),
        (20, "桌面守护鼠"),
        (10, "奶茶搭子"),
        (5, "熟悉的奶茶鼠"),
        (1, "刚来的奶茶鼠"),
    ]
    for required_level, title in titles:
        if level >= required_level:
            return title
    return "刚来的奶茶鼠"
