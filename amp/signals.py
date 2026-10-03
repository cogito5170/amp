"""신호 다섯 (AMP.md §3). 모두 [0,1], 없으면 unknown(0 이 아님). 원천을 칸으로 남긴다."""
from __future__ import annotations

import math
from collections import Counter

from .forms import signal, unknown

SIGNALS_VERSION = "amp-signals/1"


def disagreement(labels: list) -> float | None:
    """1 − (최빈값 수 / n). None 라벨(뽑지 못함)도 하나의 값으로 센다. n < 2 면 None."""
    if len(labels) < 2:
        return None
    top = Counter(labels).most_common(1)[0][1]
    return 1.0 - top / len(labels)


def mode(labels: list):
    """최빈값. 동률이면 먼저 나온 값(결정적)."""
    c = Counter(labels)
    best = max(c.values())
    return next(x for x in labels if c[x] == best)


def uncertainty_signal(labels: list) -> dict:
    v = disagreement(labels)
    return unknown("uncertainty", "sample_disagreement") if v is None else signal("uncertainty", v, "valid", "sample_disagreement")


def entropy_from_logprobs(logprobs: list[float] | None) -> float | None:
    """보조 신호(Gemini 등 logprob 을 주는 호출기): 고른 토큰 평균 놀람 −log p 를 1 − exp(−x) 로 [0,1] 에 둔다."""
    if not logprobs:
        return None
    x = -sum(logprobs) / len(logprobs)
    return 1.0 - math.exp(-max(0.0, x))


def char_ngrams(text: str, n: int = 3) -> frozenset:
    t = " ".join(text.lower().split())
    return frozenset(t[i:i + n] for i in range(max(0, len(t) - n + 1)))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


class Novelty:
    """과제 문장의 문자 3-gram 과 보정 분할 문장들의 최대 자카드 유사도 s 에 대해 1 − s. 모형 호출 없음."""

    def __init__(self, reference_texts: list[str]):
        self.ref = [char_ngrams(t) for t in reference_texts]

    def __call__(self, text: str, exclude_self: bool = False) -> dict:
        if not self.ref:
            return unknown("novelty", "char3_jaccard_vs_calibration")
        g = char_ngrams(text)
        sims = sorted((jaccard(g, r) for r in self.ref), reverse=True)
        if exclude_self and sims and sims[0] == 1.0:
            sims = sims[1:]
        if not sims:
            return unknown("novelty", "char3_jaccard_vs_calibration")
        return signal("novelty", 1.0 - sims[0], "valid", "char3_jaccard_vs_calibration")


def prediction_error_signal(value: float | None, source: str) -> dict:
    return unknown("prediction_error", source) if value is None else signal("prediction_error", value, "valid", source)


def contradiction_signal(value: float | None, source: str) -> dict:
    return unknown("contradiction", source) if value is None else signal("contradiction", value, "valid", source)


def stakes_signal(risk: str = "local") -> dict:
    """행동 위험 등급(action-spec risk): read 0 · local 0.5 · external 1. P1a 과제는 모두 local 이라 분산이 없다."""
    return signal("stakes", {"read": 0.0, "local": 0.5, "external": 1.0}[risk], "valid", f"task_risk_fixed:{risk}")
