"""已核实的结算图标参考，只为缺字的历史记录关联图鉴资料。"""

from functools import lru_cache
from importlib.resources import files
from io import BytesIO

from PIL import Image, ImageChops, ImageStat

from bd2_fishing.game.fishing.catalogue import load_catalogue

ICON_REFERENCES = {"fish_05_06": "assets/fish_05_06_reward.png"}


@lru_cache(maxsize=1)
def _references():
    result = {}
    for identity, path in ICON_REFERENCES.items():
        with Image.open(
            BytesIO(files("bd2_fishing.game.fishing").joinpath(path).read_bytes())
        ) as image:
            result[identity] = image.convert("RGB")
    return result


def match_catch_icon(raw, location=None):
    if not raw:
        return None
    try:
        with Image.open(BytesIO(raw)) as original:
            width, height = original.size
            icon = original.crop(
                (
                    round(width * 394 / 945),
                    round(height * 61 / 532),
                    round(width * 424 / 945),
                    round(height * 92 / 532),
                )
            )
            icon = icon.convert("RGB").resize((24, 24), Image.Resampling.LANCZOS)
        catalogue = {fish.id: fish for fish in load_catalogue()}
        matches = []
        for identity, reference in _references().items():
            fish = catalogue[identity]
            if location is not None and fish.location != location:
                continue
            error = sum(ImageStat.Stat(ImageChops.difference(icon, reference)).mean) / 3
            # 仅接受接近同一图标的像素匹配；独立正例 < 1，已检查负例 > 18。
            if error <= 3:
                matches.append(fish)
        return matches[0] if len(matches) == 1 else None
    except (OSError, ValueError):
        return None
