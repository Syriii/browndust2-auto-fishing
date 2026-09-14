"""只读图鉴服务：参考信息和离线鱼图，不创建任务或玩家进度。"""

from importlib.resources import files
from io import BytesIO

from PIL import Image

from bd2_fishing.game.fishing.catalogue import load_catalogue, normalize_name
from bd2_fishing.game.fishing.mechanics.catalogue import MECHANISMS

RARITIES = {"common": "普通", "rare": "稀有", "legendary": "传说"}
TIMES = {"day": "白天", "night": "夜晚", "both": "昼夜"}
GUIDE_TEXT = {
    "blue_lock": "蓝色区域会被锁住，需要瞄准黄色区域。",
    "speed": "指针移动更快。",
    "bite": "条上会出现牙齿，注意避开。",
    "shell": "贝壳会挡住部分区域。",
    "ink": "墨汁会遮挡视线。",
    "invisible": "指针会暂时隐形。",
    "freeze": "指针会被冻结，并出现冰晶数字。",
    "wall": "指针碰到墙壁会折返。",
    "clones": "出现多个指针，需要分辨真正的亮色指针。",
    "bubble": "指针进入泡泡球时，按空格消除泡泡。",
    "yellow_hide": "黄色区域会暂时消失。",
    "poison": "出现紫色区域，注意避开。",
    "slow": "指针移动变慢。",
    "green_hold": "绿色区域需要长按，再在边界前松开。",
}


class FishCatalogueService:
    def __init__(self):
        self.fish = load_catalogue()
        self.by_id = {fish.id: fish for fish in self.fish}

    def search(self, query="", *, island="全部钓场", time="全部时段", rarity="全部稀有度"):
        key = normalize_name(query)
        return tuple(
            fish
            for fish in self.fish
            if (island == "全部钓场" or fish.location.value == island)
            and (
                time == "全部时段"
                or fish.availability == "both"
                or TIMES[fish.availability] == time
            )
            and (rarity == "全部稀有度" or RARITIES[fish.rarity] == rarity)
            and (not key or any(key in normalize_name(alias) for alias in fish.aliases))
        )

    def picture(self, identity, size):
        fish = self.by_id[identity]
        resource = files("bd2_fishing.game.fishing").joinpath(fish.image_asset)
        with Image.open(BytesIO(resource.read_bytes())) as original:
            width, height = original.size
            # 原始图鉴卡片上半部为鱼图；下方作者尺寸和个人纪录不进入浏览界面。
            picture = original.crop(
                (
                    round(width * 0.145),
                    round(height * 0.05),
                    round(width * 0.96),
                    round(height * 0.47),
                )
            ).convert("RGB")
        picture.thumbnail(size, Image.Resampling.LANCZOS)
        return picture

    def details(self, identity):
        fish = self.by_id[identity]
        return {
            "facts": (
                ("稀有度", RARITIES[fish.rarity]),
                ("钓场", fish.location.value),
                ("时段", "全天" if fish.availability == "both" else TIMES[fish.availability]),
            ),
            "mechanisms": tuple(
                (item.name, GUIDE_TEXT[item.id])
                for item in MECHANISMS
                if item.id in fish.possible_mechanisms
            ),
        }
