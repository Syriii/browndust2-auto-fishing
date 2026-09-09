"""只用于取证的 QTE 外观线索；不识别技能身份，不决定输入。"""

import cv2

from bd2_fishing.game.fishing.pointer import read_pointer
from bd2_fishing.perception import image as vision
from bd2_fishing.runtime import geometry


class SceneSignals:
    def __init__(self, config, window, evidence_region):
        self.control_region = vision.build_region_from_config(config, "roi", window)
        self.evidence_region = evidence_region
        self.crops = {
            name: tuple(
                config.getint("roi", f"{name}_{side}_percent")
                for side in ("top", "bottom", "left", "right")
            )
            for name in ("qte", "time")
        }
        self.ranges = {
            name: vision.read_hsv_range(config, "roi", name)
            for name in ("white", "yellow", "blue", "red")
        }
        # 排除普通蓝色光晕和浅色分身；这里只生成外观候选，不派发技能动作。
        self.appearance_ranges = {
            "purple": ((125, 100, 150), (169, 255, 255)),
            "green": ((40, 100, 150), (85, 255, 255)),
        }
        self.time_ranges = [
            vision.read_hsv_range_from_keys(
                config,
                "roi",
                lower_prefix=f"time_lower_{color}",
                upper_prefix=f"time_upper_{color}",
            )
            for color in ("green", "red")
        ]
        self.time_threshold = geometry.scale_pixel_threshold(
            50, vision.build_pixel_threshold_scale(config, window)
        )

    def inspect(self, frame):
        region, source = self.control_region, self.evidence_region
        left, top = region.left - source.left, region.top - source.top
        right, bottom = left + region.width, top + region.height
        if left < 0 or top < 0 or right > frame.shape[1] or bottom > frame.shape[0]:
            return (), dict(roi_available=False)
        control = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2HSV)
        h, w = control.shape[:2]
        tt, tb, tl, tr = self.crops["time"]
        timer = control[h * tt // 100 : h * tb // 100, w * tl // 100 : w * tr // 100]
        active = (
            bool(timer.size)
            and sum(
                cv2.countNonZero(cv2.inRange(timer, color.lower, color.upper))
                for color in self.time_ranges
            )
            > self.time_threshold
        )
        qte_top, qte_bottom, qte_left, qte_right = self.crops["qte"]
        qte = control[
            h * qte_top // 100 : h * qte_bottom // 100, w * qte_left // 100 : w * qte_right // 100
        ]
        if not qte.size:
            return (), dict(roi_available=False)
        masks = {
            name: cv2.inRange(qte, value.lower, value.upper) for name, value in self.ranges.items()
        }
        pixels = {name: cv2.countNonZero(mask) for name, mask in masks.items()}
        for name, (lower, upper) in self.appearance_ranges.items():
            pixels[name] = cv2.countNonZero(cv2.inRange(qte, lower, upper))
        reading = read_pointer(qte)
        candidates = [dict(x=p.x, brightness=p.brightness) for p in reading.candidates]
        cursor = reading.x
        threshold = max(3, round(qte.shape[0] * qte.shape[1] * 0.003))
        signals = []
        for name in ("red", "purple", "green"):
            if pixels[name] >= threshold:
                signals.append(f"{name}_content")
        if len(candidates) > 1:
            signals.append("multiple_pointer_candidates")
        if pixels["blue"] or pixels["yellow"]:
            if cursor is None:
                signals.append("target_without_bright_pointer")
            if pixels["blue"] and not pixels["yellow"]:
                signals.append("blue_without_yellow")
            if pixels["yellow"] and not pixels["blue"]:
                signals.append("yellow_without_blue")
        else:
            signals.append("no_visible_target")
        return tuple(signals) if active else (), dict(
            roi_available=True,
            qte_active=active,
            pixels=pixels,
            bright_cursor_x=cursor,
            pointer_candidates=candidates,
            pointer_reason=reading.reason,
            qte_shape=list(qte.shape),
        )
