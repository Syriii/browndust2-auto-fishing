"""app.ocr_setup：从现有实现分离的职责模块。"""

from __future__ import annotations

import configparser
import logging
import os

from bd2_fishing.game.observation import OCRContext, OCRRegions
from bd2_fishing.infrastructure import paths as paths
from bd2_fishing.infrastructure.ocr.engine import RapidOCREngine
from bd2_fishing.runtime import geometry as geometry
from bd2_fishing.runtime.geometry import Rect

log = logging.getLogger(__name__)


def resolve_ocr_resource_path(config: configparser.ConfigParser, key: str) -> str | None:
    """解析开发环境和 PyInstaller 环境下均可访问的 OCR 资源路径。"""
    configured_value = config.get("ocr", key, fallback="").strip()
    if not configured_value:
        return None

    resolved_path = paths.get_resource_path(configured_value)
    if os.path.exists(resolved_path):
        return resolved_path

    return None


def build_ocr_engine(config: configparser.ConfigParser) -> RapidOCREngine:
    """从配置读取可选模型路径并创建 RapidOCR 适配器。"""
    det_model_path = resolve_ocr_resource_path(config, "det_model_path")
    cls_model_path = resolve_ocr_resource_path(config, "cls_model_path")
    rec_model_path = resolve_ocr_resource_path(config, "rec_model_path")
    rec_keys_path = resolve_ocr_resource_path(config, "rec_keys_path")
    return RapidOCREngine(
        det_model_path=det_model_path,
        cls_model_path=cls_model_path,
        rec_model_path=rec_model_path,
        rec_keys_path=rec_keys_path,
        use_cls=config.getboolean("ocr", "use_cls", fallback=False),
    )


def build_optional_ocr_region(
    config: configparser.ConfigParser,
    region: Rect,
    *,
    left_key: str,
    top_key: str,
    right_key: str,
    bottom_key: str,
) -> Rect:
    """构建可选 OCR 区域；缺少任一边界配置时回退到完整游戏窗口。"""
    if not all(config.has_option("ocr", key) for key in (left_key, top_key, right_key, bottom_key)):
        left_percent = 0
        top_percent = 0
        right_percent = 100
        bottom_percent = 100
    else:
        left_percent = config.getint("ocr", left_key)
        top_percent = config.getint("ocr", top_key)
        right_percent = config.getint("ocr", right_key)
        bottom_percent = config.getint("ocr", bottom_key)
    return geometry.build_region_from_percent(
        region,
        left_percent=left_percent,
        top_percent=top_percent,
        right_percent=right_percent,
        bottom_percent=bottom_percent,
    )


def build_ocr_context(config: configparser.ConfigParser, region: Rect) -> OCRContext:
    """创建全部 OCR 区域，并在引擎初始化失败时自动关闭 OCR。"""
    ocr_regions = OCRRegions(
        build_optional_ocr_region(
            config,
            region,
            left_key="location_left_percent",
            top_key="location_top_percent",
            right_key="location_right_percent",
            bottom_key="location_bottom_percent",
        ),
        build_optional_ocr_region(
            config,
            region,
            left_key="map_left_percent",
            top_key="map_top_percent",
            right_key="map_right_percent",
            bottom_key="map_bottom_percent",
        ),
        build_optional_ocr_region(
            config,
            region,
            left_key="backpack_full_left_percent",
            top_key="backpack_full_top_percent",
            right_key="backpack_full_right_percent",
            bottom_key="backpack_full_bottom_percent",
        ),
    )

    ocr_enabled = config.getboolean("ocr", "enabled", fallback=False)
    ocr_engine = None
    if ocr_enabled:
        try:
            ocr_engine = build_ocr_engine(config)
        except Exception as exc:
            log.info(f">>> OCR init failed: {exc}")
            ocr_enabled = False

    return OCRContext(
        ocr_enabled,
        ocr_engine,
        ocr_regions,
    )
