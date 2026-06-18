"""Path utilities and resource/application directory constants."""

from __future__ import annotations

import sys
from pathlib import Path


def get_resource_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


RESOURCE_DIR = get_resource_dir()
APP_DIR = get_app_dir()
BASE_DIR = RESOURCE_DIR

STATE_MAP_PATH = RESOURCE_DIR / "naicha_mouse_state_map.json"
DIALOGUES_PATH = RESOURCE_DIR / "naicha_mouse_dialogues.json"
PROFILE_PATH = APP_DIR / "naicha_mouse_profile.json"
GACHA_POOL_PATH = RESOURCE_DIR / "naicha_mouse_gacha_pool.json"
ACCESSORY_CONFIG_PATH = RESOURCE_DIR / "naicha_mouse_accessories.json"
ACCESSORY_DIR = RESOURCE_DIR / "accessories"
AI_CONFIG_PATH = APP_DIR / "naicha_mouse_ai_config.json"


def resolve_asset_path(asset_folder: Path, filename: str) -> Path:
    asset_path = Path(filename)
    if asset_path.is_absolute():
        return asset_path

    candidates = [asset_folder / asset_path, RESOURCE_DIR / asset_path, APP_DIR / asset_path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
