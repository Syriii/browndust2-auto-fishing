"""QTE 色区按键的状态规则；不等待、不截图、不执行输入。"""


class TargetEntryTrigger:
    """同一次重合只触发一次，确认离开目标后才重新允许触发。"""

    def __init__(self):
        self.armed = True
        self.target = None

    def observe(self, overlap: bool | None, target: str) -> bool:
        # 截图/光标/目标不明不等于已经离开；不能借丢帧重新放行。
        if overlap is None:
            return False
        if target != self.target:
            self.armed = True
            self.target = target
        if not overlap:
            self.armed = True
            return False
        if not self.armed:
            return False
        self.armed = False
        return True
