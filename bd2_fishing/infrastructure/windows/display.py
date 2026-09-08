"""DXGI 输出与虚拟桌面坐标转换；纯坐标逻辑可离线测试。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bd2_fishing.runtime import control as run_control

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DisplayOutput:
    device_idx: int
    output_idx: int
    name: str
    bounds: tuple[int, int, int, int]

    def contains(self, region):
        left, top, right, bottom = region
        ml, mt, mr, mb = self.bounds
        return ml <= left < right <= mr and mt <= top < bottom <= mb

    def local_region(self, region):
        if not self.contains(region):
            raise RuntimeError(
                "截图区域超出所选显示器，请将游戏完整放在一块屏幕内后点击开始钓鱼 重试"
            )
        left, top, right, bottom = region
        ml, mt, _, _ = self.bounds
        return left - ml, top - mt, right - ml, bottom - mt


def select_output(outputs, region):
    for output in outputs:
        if output.contains(region):
            return output
    raise RuntimeError(
        "游戏客户区跨屏、超出桌面或没有可用显示器；请完整移到一块屏幕后点击开始钓鱼 重试"
    )


@dataclass
class _OutputBinding:
    info: DisplayOutput
    adapter: object
    output: object


def _enumerate_bindings():
    # DXcam 0.3.0 的全局 DXFactory 会缓存启动时的输出列表。
    # 保留本次枚举的原生对象，不把新索引传给旧工厂。升级依赖时核对这些内部接口。
    from dxcam.core.output import Output
    from dxcam.util.io import enum_dxgi_adapters, enum_dxgi_outputs

    result = []
    device_idx = 0
    for adapter in enum_dxgi_adapters():
        outputs = enum_dxgi_outputs(adapter)
        if not outputs:
            continue
        for output_idx, pointer in enumerate(outputs):
            output = Output(pointer)
            if not output.attached_to_desktop:
                continue
            rect = output.desc.DesktopCoordinates
            info = DisplayOutput(
                device_idx,
                output_idx,
                output.devicename,
                (rect.left, rect.top, rect.right, rect.bottom),
            )
            result.append(_OutputBinding(info, adapter, output))
        device_idx += 1
    return result


def enumerate_outputs():
    return [binding.info for binding in _enumerate_bindings()]


def create_camera_for_region(region, output_color="BGR"):
    """使用本次枚举的适配器和输出创建独立相机，所有权交给调用者。"""
    from dxcam import DXCamera
    from dxcam.core.device import Device

    run_control.checkpoint()
    bindings = _enumerate_bindings()
    outputs = [binding.info for binding in bindings]
    log.info("本次截图输出枚举：%s；游戏区域=%s", outputs, region)
    selected = select_output(outputs, region)
    binding = next(binding for binding in bindings if binding.info is selected)
    camera = None
    try:
        binding.output.update_desc()
        rect = binding.output.desc.DesktopCoordinates
        if (
            not binding.output.attached_to_desktop
            or (rect.left, rect.top, rect.right, rect.bottom) != selected.bounds
        ):
            raise RuntimeError("显示器布局在截图初始化期间变化；请等待显示器稳定后重新开始")
        # 有意绕过 dxcam.create 的进程级索引缓存，但沿用其 DXCamera 和后端实现。
        camera = DXCamera(
            output=binding.output,
            device=Device(binding.adapter),
            region=None,
            output_color=output_color,
        )
        run_control.sleep(0.1)  # 沿用 DXFactory.create 的初始化稳定等待，并响应停止。
        run_control.checkpoint()
        return camera, selected
    except BaseException:
        if camera is not None:
            camera.release()
        raise


def normalize_virtual_point(x, y, bounds):
    """SendInput 绝对移动使用虚拟桌面范围；映射到目标像素中心。"""
    left, top, right, bottom = bounds
    if not left <= x < right or not top <= y < bottom:
        raise ValueError("鼠标目标超出虚拟桌面")
    return (
        min(65535, ((2 * (x - left) + 1) * 65536) // (2 * (right - left))),
        min(65535, ((2 * (y - top) + 1) * 65536) // (2 * (bottom - top))),
    )
