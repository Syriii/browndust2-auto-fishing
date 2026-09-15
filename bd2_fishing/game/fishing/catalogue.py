"""鱼种参考目录及明确别名查询；不识别鱼获或自动出售。"""

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

from bd2_fishing.game.fishing.mechanics.catalogue import MECHANISM_IDS
from bd2_fishing.game.islands.catalog import FishingLocation


@dataclass(frozen=True)
class Fish:
    id: str
    name: str
    name_tw: str
    aliases: tuple[str, ...]
    location: FishingLocation
    rarity: str
    rarity_rank: int
    availability: str
    possible_mechanisms: frozenset[str]
    image_url: str
    client_name_verified: bool
    image_asset: str


def normalize_name(name: str) -> str:
    """只统一 Unicode 和空白；译名差异由显式别名处理，不模糊猜测鱼种。"""
    return "".join(unicodedata.normalize("NFKC", name).split()).casefold()


def reward_name(text: str) -> str:
    """移除结算名称末尾的数量，不猜测被 OCR 丢失的文字。"""
    return re.sub(r"\s*[×xX*]\s*[1-9]\d*\s*$", "", unicodedata.normalize("NFKC", text)).strip()


def parse_catalogue(document):
    if document.get("schema_version") != 1:
        raise ValueError("不支持的鱼种目录版本")
    result, ids = [], set()
    for row in document["fish"]:
        identity = row["id"]
        if identity in ids:
            raise ValueError(f"重复鱼种编号：{identity}")
        ids.add(identity)
        claims = row["mechanism_claims"]
        possible = frozenset(item for values in claims.values() for item in values)
        if possible != frozenset(row["possible_mechanisms"]) or not possible <= MECHANISM_IDS:
            raise ValueError(f"机制并集不一致或含未知机制：{identity}")
        if row["availability"] not in {"day", "night", "both"}:
            raise ValueError(f"未知出现时段：{identity}")
        if {"common": 1, "rare": 2, "legendary": 3}.get(row["rarity"]) != row["rarity_rank"]:
            raise ValueError(f"稀有度不一致：{identity}")
        result.append(
            Fish(
                identity,
                row["name_zh"],
                row["name_tw"],
                tuple(sorted(set(row["aliases"]) | {row["name_zh"], row["name_tw"]})),
                FishingLocation[row["island_id"]],
                row["rarity"],
                row["rarity_rank"],
                row["availability"],
                possible,
                row["image"]["url"],
                row["client_name_verified"],
                row["image"]["runtime_asset"],
            )
        )
    return tuple(result)


@lru_cache(maxsize=1)
def load_catalogue() -> tuple[Fish, ...]:
    text = (
        files("bd2_fishing.game.fishing").joinpath("assets/fish_catalogue.json").read_text("utf-8")
    )
    return parse_catalogue(json.loads(text))


def find_fish(name: str, *, location: FishingLocation | None = None) -> tuple[Fish, ...]:
    """返回全部精确别名候选；歧义交给调用方处理，绝不取第一个冒充确认。"""
    key = normalize_name(name)
    if not key:
        return ()
    return tuple(
        fish
        for fish in load_catalogue()
        if (location is None or fish.location == location)
        and key in {normalize_name(alias) for alias in fish.aliases}
    )
