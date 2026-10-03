"""계기 대조 · 예산 지킴이 (AMP.md §11 · R12).

계기 대조: 호출기가 보고한 usage 와 독립된 추적 합을 견준다. 상대 차가 문턱(기본 5%)을 넘으면 그 호출은 무효다.
추적이 없으면 `unverified` 다 — 통과가 아니다.
예산 지킴이: 누적 비용 + 다음 호출 추정 비용이 상한을 넘으면 호출하지 않고 멈춘다(레일을 넘는 일은 없다).
"""
from __future__ import annotations

THRESHOLD = 0.05


def cross_check(reported: dict, tracked: dict | None, threshold: float = THRESHOLD) -> tuple[str, float | None]:
    if tracked is None:
        return "unverified", None
    a = sum(reported.get(k, 0) for k in ("input", "output", "cache_read", "cache_write"))
    b = sum(tracked.get(k, 0) for k in ("input", "output", "cache_read", "cache_write"))
    if a == 0 and b == 0:
        return "verified", 0.0
    diff = abs(a - b) / max(a, b)
    return ("mismatch" if diff > threshold else "verified"), round(diff, 6)


class BudgetStop(RuntimeError):
    pass


class BudgetGuard:
    """상한(USD) 안에서만 호출을 허락한다. `estimate` 는 다음 호출 한 번의 비용 추정이다.

    추정은 처음에 `initial_estimate`, 그 뒤로는 지금까지 본 호출당 비용의 최댓값을 쓴다(닫는 쪽).
    """

    def __init__(self, cap_usd: float, initial_estimate: float):
        self.cap = float(cap_usd)
        self.spent = 0.0
        self.calls = 0
        self.max_seen = float(initial_estimate)
        self.stopped = False

    def estimate(self) -> float:
        return self.max_seen

    def before(self) -> None:
        if self.stopped or self.spent + self.estimate() > self.cap:
            self.stopped = True
            raise BudgetStop(f"spent {self.spent:.4f} + next {self.estimate():.4f} > cap {self.cap:.4f}")

    def after(self, cost: float) -> None:
        self.spent += cost
        self.calls += 1
        self.max_seen = max(self.max_seen, cost)
