"""多个可见泡泡分别去重；有界状态，不截图、等待或外推光标。"""

from bd2_fishing.game.fishing.mechanics.bubbles import BubbleController


class BubbleTargets:
    def __init__(self):
        self.controllers = []
        self.span = None

    @property
    def consumed(self):
        return any(c.consumed for c in self.controllers)

    def invalidate_observation(self):
        for controller in self.controllers:
            controller.invalidate_observation()

    def observe(self, spans, cursor, now, *, blocked=False, uncertain=False):
        spans = sorted(spans)
        if len(spans) > 4 or any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            self.invalidate_observation()
            return False
        pending = list(self.controllers)
        assignments = []
        for span in spans:
            matches = [c for c in pending if c.span and span[0] < c.span[1] and span[1] > c.span[0]]
            if len(matches) > 1:
                self.invalidate_observation()
                return False
            controller = matches[0] if matches else BubbleController()
            if matches:
                pending.remove(controller)
            assignments.append((controller, span))
        # 消失必须有连续新鲜观测；遮挡和多义候选不作已消失处理。
        for controller in pending:
            controller.observe((), None, now, uncertain=uncertain)
        active = [c for c in pending if c.span is not None]
        if len(active) + len(assignments) > 4:
            self.invalidate_observation()
            return False
        self.controllers = active + [c for c, _ in assignments]
        pressed = False
        for controller, span in assignments:
            if controller.observe((span,), None if pressed else cursor, now, blocked=blocked):
                self.span, pressed = controller.span, True
        return pressed
