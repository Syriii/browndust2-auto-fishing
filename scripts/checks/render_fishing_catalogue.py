"""从鱼种唯一数据源生成参考表；--check 只核对，不修改文档。"""

import argparse
import json
from pathlib import Path

from bd2_fishing.game.fishing.catalogue import load_catalogue
from bd2_fishing.game.fishing.mechanics.catalogue import MECHANISMS
from bd2_fishing.game.islands.catalog import FishingLocation

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "docs/reference/fishing/fish-catalogue.md"


def render():
    # 先执行目录完整性验证，再生成显示数据；不联网取图，不读取玩家记录。
    load_catalogue()
    data = json.loads(
        (ROOT / "bd2_fishing/game/fishing/assets/fish_catalogue.json").read_text(encoding="utf-8")
    )
    mechanisms = {item.id: item.name for item in MECHANISMS}
    lines = [
        "# 六岛鱼种参考图鉴",
        "",
        "[资料库](README.md) · [来源与繁简说明](sources.md) · [图片选鱼方案](../../design/fish-targets.md)",
        "",
        "核对日期：2026-09-14。84 种鱼；绿色一贝壳／蓝色二贝壳／彩色三贝壳对应普通／稀有／传说。",
        "名称为简体参考名，尚未逐项核对用户客户端；别名、来源分歧、尺寸参考及图片哈希保存在 JSON。",
        "“初始距离”是 QTE 距离，不是鱼身尺寸。可能机制采用来源并集，不表示该局实际已出现。",
        "鱼图链接指向社区原图，仅用于核对；原图里的个人纪录不属于用户的鱼获记录。",
        "",
        "此表由 `scripts/checks/render_fishing_catalogue.py` 生成，请修改唯一 JSON 数据源后重新生成。",
    ]
    for location in FishingLocation:
        rows = [row for row in data["fish"] if row["island_id"] == location.name]
        lines += [
            "",
            f"## {location.value}（{len(rows)} 种）",
            "",
            "| ID | 简体参考名 | 繁体名 | 稀有度 | 时段 | 初始距离 cm | 可能机制 | 鱼图 |",
            "| --- | --- | --- | --- | --- | ---: | --- | --- |",
        ]
        for row in rows:
            fields = [
                row["id"],
                row["name_zh"],
                row["name_tw"],
                {"common": "普通／1", "rare": "稀有／2", "legendary": "传说／3"}[row["rarity"]],
                {"day": "白天", "night": "夜晚", "both": "昼夜"}[row["availability"]],
                str(row["initial_distance_cm"]),
                "、".join(mechanisms[item] for item in row["possible_mechanisms"])
                or "未列特殊机制",
                f"[原图]({row['image']['url']})",
            ]
            lines.append("| " + " | ".join(fields) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != expected:
            parser.exit(1, "图鉴文档与数据源不一致，请重新生成。\n")
        print("鱼种目录与文档一致：84 种，六岛。")
    else:
        TARGET.write_text(expected, encoding="utf-8")
        print(TARGET)


if __name__ == "__main__":
    main()
