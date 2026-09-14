"""界面与钓鱼任务共用的个人鱼获服务。"""

import uuid
from datetime import datetime, timezone
from io import BytesIO

import cv2
from PIL import Image

from bd2_fishing.game.fishing.catalogue import load_catalogue
from bd2_fishing.game.fishing.catch_identity import identify_catch, refine_reward_identity
from bd2_fishing.infrastructure.fishing_journal import FishingJournal
from bd2_fishing.runtime import control

CONDITIONS = {"any": "任意尺寸", "max": "MAX 最大", "min": "MIN 最小", "both": "MAX ＋ MIN"}


class FishingCollection:
    def __init__(self, path=None):
        self.journal = FishingJournal(path)
        self.catalogue = {f.id: f for f in load_catalogue()}
        self.run_id = None
        self.targeted = False

    def save_targets(self, selected):
        rows = []
        for identity, condition in selected.items():
            if identity not in self.catalogue or condition not in CONDITIONS:
                raise ValueError("目标鱼或尺寸条件无效")
            rows.extend(
                (identity, c) for c in (("max", "min") if condition == "both" else (condition,))
            )
        self.journal.replace_targets(rows)

    def selected(self):
        result = {}
        for identity, condition in self.journal.targets():
            result[identity] = "both" if identity in result else condition
        return result

    def begin(self, targeted=False):
        if targeted and not self.journal.targets():
            raise ValueError("请先选择目标鱼")
        self.run_id = uuid.uuid4().hex
        self.targeted = targeted
        self.journal.begin_run(self.run_id, targeted)

    def confirm(self, observer):
        if observer.result.status != "caught":
            return
        fish, size_kind = identify_catch(observer.reward_readings, observer.current_location)
        frame = observer.evidence_frames.get("settlement.png")
        if frame is None:
            raise control.RunStopped("鱼获证据未取得，保留结算页面，请检查后重试")
        if fish is None and observer.engine is not None:
            height, width = frame.shape[:2]
            reward = frame[
                round(height * 0.08) : round(height * 0.21),
                round(width * 0.36) : round(width * 0.65),
            ]
            try:
                fish = refine_reward_identity(
                    observer.engine, reward, observer.reward_readings, observer.current_location
                )
                if fish is None:
                    readings = observer.engine.detect_and_recognize(
                        cv2.resize(reward, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                    )
                    fish, _ = identify_catch(readings, observer.current_location)
                    observer.evidence_metadata["identity_refinement"] = [
                        dict(text=t.text, score=t.score) for t in readings
                    ]
                else:
                    observer.evidence_metadata["identity_refinement"] = dict(
                        fish_id=fish.id, method="two_name_crops"
                    )
            except Exception as exc:
                # 已确认捕获仍须存入历史；鱼名不明只阻止完成指定鱼目标。
                observer.evidence_metadata["identity_refinement_error"] = str(exc)
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not ok:
            raise control.RunStopped("鱼获图片保存失败，保留结算页面")
        event = dict(
            run_id=self.run_id,
            round_id=observer.round_id,
            caught_at=datetime.now(timezone.utc).isoformat(),
            fish_id=fish.id if fish else None,
            name=fish.name if fish else observer.result.reward or "鱼种未确认",
            location=observer.current_location.value if observer.current_location else "未确认",
            size_cm=observer.result.size_cm,
            size_kind=size_kind,
            rarity=fish.rarity if fish else "unknown",
            stars=observer.result.stars,
            border_color=observer.result.border_color,
            new_record=observer.result.new_record,
        )
        try:
            self.journal.record(event, encoded.tobytes())
        except Exception as exc:
            raise control.RunStopped("鱼获记录写入失败，已停止并保留结算页面") from exc

    @property
    def completed(self):
        return self.targeted and not self.journal.targets()

    def picture(self, identity, size):
        raw = self.journal.evidence(identity)
        if not raw:
            return None
        with Image.open(BytesIO(raw)) as original:
            width, height = original.size
            image = original.crop(
                (
                    round(width * 388 / 945),
                    round(height * 54 / 532),
                    round(width * 430 / 945),
                    round(height * 97 / 532),
                )
            ).convert("RGB")
        image.thumbnail(size, Image.Resampling.LANCZOS)
        return image
