"""刚消失的已确认泡泡附近绿残影仅作局部避让，不猜测新的长按技能。"""

from dataclasses import replace


class BubbleMemory:
    def __init__(self):
        self.previous = ()
        self.previous_at = None
        self.confirmed = []

    def normalize(self, regions, now):
        self.confirmed = [(span, seen) for span, seen in self.confirmed if 0 <= now - seen <= 0.8]
        fresh = self.previous_at is not None and 0 < now - self.previous_at <= 0.25
        for span in regions.bubble_spans:
            if fresh and any(
                span[0] < old[1]
                and old[0] < span[1]
                and abs(sum(span) - sum(old)) <= max(6, (span[1] - span[0]) * 0.4)
                for old in self.previous
            ):
                self.confirmed = [
                    (old, seen)
                    for old, seen in self.confirmed
                    if not (span[0] < old[1] and old[0] < span[1])
                ]
                self.confirmed.append((span, now))
        self.confirmed = self.confirmed[-4:]
        self.previous, self.previous_at = regions.bubble_spans, now
        if not regions.green_present or not regions.green_spans:
            return regions
        remnants = tuple(
            span
            for span in regions.green_spans
            if any(
                left - max(3, round((right - left) * 0.15)) <= span[0]
                and span[1] <= right + max(3, round((right - left) * 0.15))
                for (left, right), _ in self.confirmed
            )
        )
        if not remnants:
            return regions
        remaining = tuple(span for span in regions.green_spans if span not in remnants)
        blocked = regions.blocked.copy()
        for left, right in remnants:
            blocked[max(0, left - 3) : right + 3] = True
        green = regions.green
        if green is not None and not any(a < green.right and b > green.left for a, b in remaining):
            green = None
        return replace(
            regions,
            green_present=bool(remaining),
            green=green,
            green_spans=remaining,
            blocked=blocked,
            bubble_remnant_spans=remnants,
        )
