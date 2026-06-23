"""Gacha / lottery system — draw logic, reward application, rarity helpers."""

from __future__ import annotations

import random
import time
from typing import Any

from naicha_mouse.constants import GACHA_SUPER_PITY
from naicha_mouse.models import BUBBLE_FRAME_STYLES


# ── rarity helpers ─────────────────────────────────────────


def rarity_rank(rarity: str) -> int:
    return {"normal": 0, "rare": 1, "super_rare": 2, "hidden": 3}.get(rarity, 0)


def rarity_label(rarity: str) -> str:
    return {
        "normal": "普通",
        "rare": "稀有",
        "super_rare": "超稀有",
        "hidden": "隐藏",
    }.get(rarity, rarity)


def duplicate_shards_for_rarity(rarity: str) -> int:
    return {
        "normal": 1,
        "rare": 3,
        "super_rare": 8,
        "hidden": 20,
    }.get(rarity, 1)


# ── draw logic ─────────────────────────────────────────────


def choose_gacha_rarity(
    gacha_pool: dict[str, Any],
    force_min_rarity: str | None = None,
) -> str:
    rarities = gacha_pool.get("rarities", {})
    candidates = [
        (r, float(w))
        for r, w in rarities.items()
        if float(w) > 0 and rewards_for_rarity(gacha_pool, r)
    ]
    if force_min_rarity:
        minimum = rarity_rank(force_min_rarity)
        candidates = [
            (r, w) for r, w in candidates if rarity_rank(r) >= minimum
        ]
    if not candidates:
        return "normal"
    return random.choices(
        [r for r, _ in candidates],
        weights=[w for _, w in candidates],
        k=1,
    )[0]


def rewards_for_rarity(gacha_pool: dict[str, Any], rarity: str) -> list[dict[str, Any]]:
    return [
        item
        for item in gacha_pool.get("rewards", [])
        if item.get("rarity") == rarity and float(item.get("weight", 1)) > 0
    ]


def choose_reward_for_rarity(gacha_pool: dict[str, Any], rarity: str) -> dict[str, Any]:
    rewards = rewards_for_rarity(gacha_pool, rarity)
    if not rewards:
        rewards = gacha_pool.get("rewards", [])
    return random.choices(
        rewards,
        weights=[float(item.get("weight", 1)) for item in rewards],
        k=1,
    )[0]


def perform_gacha_draw(
    gacha_pool: dict[str, Any],
    profile: dict[str, Any],
    accessories: dict[str, Any],
    force_min_rarity: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Perform a single gacha draw.

    Returns (result_dict, updated_profile).
    """
    rarity = choose_gacha_rarity(gacha_pool, force_min_rarity)
    if (
        int(profile["gacha_pity_counter"]) >= GACHA_SUPER_PITY
        and rarity_rank(rarity) >= rarity_rank("rare")
        and rarity_rank(rarity) < rarity_rank("super_rare")
    ):
        rarity = "super_rare"

    reward = choose_reward_for_rarity(gacha_pool, rarity)
    result, profile = apply_gacha_reward(reward, rarity, profile, accessories, gacha_pool)
    profile["gacha_draw_count"] = int(profile["gacha_draw_count"]) + 1
    if rarity_rank(rarity) >= rarity_rank("super_rare"):
        profile["gacha_pity_counter"] = 0
    else:
        profile["gacha_pity_counter"] = int(profile["gacha_pity_counter"]) + 1
    return result, profile


# ── reward application ─────────────────────────────────────


def apply_gacha_reward(
    reward: dict[str, Any],
    rarity: str,
    profile: dict[str, Any],
    accessories: dict[str, Any],
    gacha_pool: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    reward_type = reward.get("type", "dialogue")
    title = str(reward.get("title", reward.get("text", reward.get("id", "神秘奖励"))))
    duplicate = False
    shard_gain = 0
    detail = ""

    if reward_type == "dialogue":
        mode = reward.get("mode", "instant")
        reward_id = str(reward.get("id", title))
        profile["dialogue_rewards_seen"] = profile.get("dialogue_rewards_seen", {})
        seen = profile["dialogue_rewards_seen"]
        seen[reward_id] = int(seen.get(reward_id, 0)) + 1
        if mode == "instant":
            detail = str(reward.get("text", title))
        elif mode == "unlock":
            if reward_id in profile.get("owned_dialogues", []):
                duplicate = True
                shard_gain = duplicate_shards_for_rarity(rarity)
                detail = f"重复口头禅转为奶茶碎片 +{shard_gain}"
            else:
                profile.setdefault("owned_dialogues", []).append(reward_id)
                detail = f"新口头禅解锁：{reward.get('text', title)}"
        elif mode == "pack":
            if reward_id in profile.get("owned_dialogue_packs", []):
                duplicate = True
                shard_gain = duplicate_shards_for_rarity(rarity)
                detail = f"重复语言包转为奶茶碎片 +{shard_gain}"
            else:
                profile.setdefault("owned_dialogue_packs", []).append(reward_id)
                count = len(reward.get("dialogues", []))
                detail = f"语言包解锁：{title}（{count} 句）"

    elif reward_type == "interaction":
        amount = int(reward.get("amount", 0))
        profile["interaction_value"] = int(profile.get("interaction_value", 0)) + amount
        detail = f"互动值 +{amount}"

    elif reward_type == "coins":
        amount = int(reward.get("amount", 0))
        profile["coins"] = int(profile.get("coins", 0)) + amount
        detail = f"金币返还 +{amount}"

    elif reward_type == "shards":
        amount = int(reward.get("amount", 0))
        shard_gain = amount
        detail = f"奶茶碎片 +{amount}"

    elif reward_type == "accessory":
        reward_id = str(reward.get("id", title))
        if reward.get("temporary", False):
            if reward_id in profile.get("owned_accessories", []):
                duplicate = True
                shard_gain = max(1, duplicate_shards_for_rarity(rarity))
                detail = f"已拥有永久款，临时配饰转为奶茶碎片 +{shard_gain}"
            else:
                minutes = int(reward.get("duration_minutes", 20))
                profile.setdefault("temporary_accessories", {})[reward_id] = int(time.time()) + minutes * 60
                detail = f"临时配饰：{title}（{minutes} 分钟）"
        elif reward_id in profile.get("owned_accessories", []):
            duplicate = True
            shard_gain = duplicate_shards_for_rarity(rarity)
            detail = f"重复配饰转为奶茶碎片 +{shard_gain}"
        else:
            profile.setdefault("owned_accessories", []).append(reward_id)
            detail = f"永久配饰解锁：{title}"

    elif reward_type == "title":
        reward_id = str(reward.get("id", title))
        if reward_id in profile.get("owned_titles", []):
            duplicate = True
            shard_gain = duplicate_shards_for_rarity(rarity)
            detail = f"重复称号转为奶茶碎片 +{shard_gain}"
        else:
            profile.setdefault("owned_titles", []).append(reward_id)
            if not profile.get("equipped_title"):
                profile["equipped_title"] = reward_id
            detail = f"称号解锁：{title}"

    elif reward_type == "bubble_frame":
        reward_id = str(reward.get("id", title))
        if reward_id in profile.get("owned_bubble_frames", []):
            duplicate = True
            shard_gain = duplicate_shards_for_rarity(rarity)
            detail = f"重复边框转为奶茶碎片 +{shard_gain}"
        else:
            profile.setdefault("owned_bubble_frames", []).append(reward_id)
            if not profile.get("equipped_bubble_frame"):
                profile["equipped_bubble_frame"] = reward_id
            detail = f"气泡边框解锁：{title}"

    elif reward_type == "performance":
        reward_id = str(reward.get("id", title))
        if reward_id in profile.get("owned_special_performances", []):
            duplicate = True
            shard_gain = duplicate_shards_for_rarity(rarity)
            detail = f"重复演出转为奶茶碎片 +{shard_gain}"
        else:
            profile.setdefault("owned_special_performances", []).append(reward_id)
            detail = f"演出收藏解锁：{title}"

    elif reward_type == "bundle":
        interaction = int(reward.get("interaction", 0))
        coins = int(reward.get("coins", 0))
        shards = int(reward.get("shards", 0))
        unlocked: list[str] = []
        duplicate_unlocks = 0
        if interaction:
            profile["interaction_value"] = int(profile.get("interaction_value", 0)) + interaction
        if coins:
            profile["coins"] = int(profile.get("coins", 0)) + coins

        for accessory_id in reward.get("accessories", []):
            accessory_id = str(accessory_id)
            label = accessories.get("items", {}).get(accessory_id, {}).get("label", accessory_id)
            if accessory_id in profile.get("owned_accessories", []):
                duplicate_unlocks += 1
                continue
            profile.setdefault("owned_accessories", []).append(accessory_id)
            profile["equipped_accessory"] = accessory_id
            unlocked.append(f"配饰：{label}")

        t_map = title_rewards(gacha_pool)
        for title_id in reward.get("titles", []):
            title_id = str(title_id)
            if title_id in profile.get("owned_titles", []):
                duplicate_unlocks += 1
                continue
            profile.setdefault("owned_titles", []).append(title_id)
            profile["equipped_title"] = title_id
            unlocked.append(f"称号：{t_map.get(title_id, title_id)}")

        f_map = bubble_frame_rewards(gacha_pool)
        for frame_id in reward.get("bubble_frames", []):
            frame_id = str(frame_id)
            if frame_id in profile.get("owned_bubble_frames", []):
                duplicate_unlocks += 1
                continue
            profile.setdefault("owned_bubble_frames", []).append(frame_id)
            profile["equipped_bubble_frame"] = frame_id
            unlocked.append(f"气泡：{f_map.get(frame_id, frame_id)}")

        p_map = performance_rewards(gacha_pool)
        for performance_id in reward.get("performances", []):
            performance_id = str(performance_id)
            if performance_id in profile.get("owned_special_performances", []):
                duplicate_unlocks += 1
                continue
            profile.setdefault("owned_special_performances", []).append(performance_id)
            unlocked.append(f"演出：{p_map.get(performance_id, {}).get('title', performance_id)}")

        dialogue_rewards = {
            str(item.get("id")): item
            for item in gacha_pool.get("rewards", [])
            if item.get("type") == "dialogue"
        }
        for dialogue_id in reward.get("dialogues", []):
            dialogue_id = str(dialogue_id)
            dialogue = dialogue_rewards.get(dialogue_id, {})
            target = "owned_dialogue_packs" if dialogue.get("mode") == "pack" else "owned_dialogues"
            if dialogue_id in profile.get(target, []):
                duplicate_unlocks += 1
                continue
            profile.setdefault(target, []).append(dialogue_id)
            seen = profile.get("dialogue_rewards_seen", {})
            seen[dialogue_id] = int(seen.get(dialogue_id, 0)) + 1
            profile["dialogue_rewards_seen"] = seen
            unlocked.append(f"口头禅：{dialogue.get('title', dialogue_id)}")

        shard_gain = shards
        if duplicate_unlocks:
            shard_gain += duplicate_unlocks * duplicate_shards_for_rarity(rarity)
        unlocked_text = "；".join(unlocked[:4])
        if len(unlocked) > 4:
            unlocked_text += f"；等 {len(unlocked)} 项收藏"
        detail = (
            f"满糖大奖：互动值 +{interaction}，金币 +{coins}，奶茶碎片 +{shards}"
            + (f"\n解锁 {unlocked_text}" if unlocked_text else "")
            + (f"\n重复收藏转碎片 +{duplicate_unlocks * duplicate_shards_for_rarity(rarity)}" if duplicate_unlocks else "")
        )

    if shard_gain:
        profile["milk_tea_shards"] = int(profile.get("milk_tea_shards", 0)) + shard_gain

    result = {
        "id": reward.get("id", title),
        "title": title,
        "rarity": rarity,
        "type": reward_type,
        "detail": detail or title,
        "duplicate": duplicate,
        "state_id": reward.get("state_id") or state_for_gacha_reward(rarity, reward_type),
    }
    return result, profile


# ── reward catalog helpers ─────────────────────────────────


def title_rewards(gacha_pool: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("id")): str(item.get("title", item.get("id")))
        for item in gacha_pool.get("rewards", [])
        if item.get("type") == "title"
    }


def bubble_frame_rewards(gacha_pool: dict[str, Any]) -> dict[str, str]:
    rewards = {
        str(item.get("id")): str(item.get("title", item.get("id")))
        for item in gacha_pool.get("rewards", [])
        if item.get("type") == "bubble_frame"
    }
    for frame_id, style in BUBBLE_FRAME_STYLES.items():
        if frame_id:
            rewards.setdefault(frame_id, str(style["label"]))
    return rewards


def performance_rewards(gacha_pool: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        str(item.get("id")): {
            "title": str(item.get("title", item.get("id"))),
            "state_id": str(item.get("state_id") or state_for_gacha_reward(str(item.get("rarity", "normal")), "performance")),
        }
        for item in gacha_pool.get("rewards", [])
        if item.get("type") == "performance"
    }


def state_for_gacha_reward(rarity: str, reward_type: str) -> str:
    if rarity == "hidden":
        return "event_happy_fly"
    if rarity == "super_rare":
        return "event_cheer_dance"
    if rarity == "rare":
        return "gift_flower"
    if reward_type == "dialogue":
        return random.choice(["idle_nod", "idle_cute"])
    return random.choice(["idle_cute", "idle_good"])
