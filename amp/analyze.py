"""분석기: 신호마다 단계 오류에 대한 AUROC 와 95% 신뢰구간 (CMD-AMP1 done_when (3)).

- AUROC = Mann–Whitney U / (n+ · n−). 동점은 0.5. 양성 = 단계 오류(label 1).
- 신뢰구간: 과제 단위 군집 부트스트랩(같은 과제의 단계들은 함께 뽑는다), 고정 시드, 기본 2000 회, 백분위 2.5–97.5.
- unknown 신호 · 무효 단계는 뺀다(수를 남긴다).
- 양성 수가 E_min 에 못 미치거나 · 음성이 없거나 · 값의 분산이 없으면 `not_estimable` 과 까닭.
- 신호를 재는 데 든 비용 비중 = 신호 cost.tokens 합 / 전체 토큰.
"""
from __future__ import annotations

import random
from collections import defaultdict

from .forms import SIGNAL_NAMES

ANALYSIS_VERSION = "amp-analysis/1"


def auroc(scores: list[float], labels: list[int]) -> float | None:
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None
    # 순위 기반 U: 평균 순위(동점 처리)
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    r_pos = sum(r for r, y in zip(ranks, labels) if y == 1)
    u = r_pos - len(pos) * (len(pos) + 1) / 2
    return u / (len(pos) * len(neg))


def _usable(rows: list[dict], name: str) -> tuple[list, list, list, int]:
    xs, ys, groups, unknown = [], [], [], 0
    for r in rows:
        if r.get("invalid") or r.get("label") is None:
            continue
        s = r["signals"][name]
        if s["value"] is None:
            unknown += 1
            continue
        xs.append(float(s["value"]))
        ys.append(int(r["label"]))
        groups.append(r["suite"] + ":" + r["task_id"])
    return xs, ys, groups, unknown


def bootstrap_ci(xs, ys, groups, reps: int = 2000, seed: int = 0, alpha: float = 0.05) -> tuple[float, float] | None:
    by = defaultdict(list)
    for x, y, g in zip(xs, ys, groups):
        by[g].append((x, y))
    keys = sorted(by)
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        bx, byy = [], []
        for _k in range(len(keys)):
            for x, y in by[keys[rng.randrange(len(keys))]]:
                bx.append(x)
                byy.append(y)
        a = auroc(bx, byy)
        if a is not None:
            vals.append(a)
    if len(vals) < reps * 0.5:
        return None
    vals.sort()
    lo = vals[int((alpha / 2) * (len(vals) - 1))]
    hi = vals[int((1 - alpha / 2) * (len(vals) - 1))]
    return round(lo, 4), round(hi, 4)


def analyze(rows: list[dict], e_min: int, reps: int = 2000, seed: int = 0, split: str = "eval") -> dict:
    rows = [r for r in rows if r["split"] == split]
    out = {"schema": ANALYSIS_VERSION, "split": split, "steps": len(rows),
           "invalid_steps": sum(bool(r.get("invalid")) for r in rows),
           "positives": sum(r.get("label") == 1 and not r.get("invalid") for r in rows),
           "negatives": sum(r.get("label") == 0 and not r.get("invalid") for r in rows),
           "e_min": e_min, "bootstrap": {"reps": reps, "seed": seed, "unit": "task"}, "signals": {}}
    for name in SIGNAL_NAMES:
        xs, ys, groups, unk = _usable(rows, name)
        npos, nneg = sum(ys), len(ys) - sum(ys)
        res = {"used": len(xs), "unknown": unk, "positives": npos, "negatives": nneg}
        why = []
        if npos < e_min:
            why.append(f"positives {npos} < E_min {e_min}")
        if nneg == 0:
            why.append("no negatives")
        if xs and len(set(xs)) == 1:
            why.append("no variance in signal")
        if not xs:
            why.append("no usable steps")
        a = auroc(xs, ys) if xs else None
        res["auroc"] = None if a is None else round(a, 4)
        if why:
            res["status"] = "not_estimable"
            res["why"] = why
            res["ci95"] = None
        else:
            res["ci95"] = bootstrap_ci(xs, ys, groups, reps, seed)
            res["status"] = "estimated" if res["ci95"] else "not_estimable"
            if res["ci95"] is None:
                res["why"] = ["bootstrap degenerate"]
            else:
                res["predicts_error"] = res["ci95"][0] > 0.5
        out["signals"][name] = res
    tot = sum(sum(r["tokens"].values()) for r in rows)
    sig = sum(r["signals"][n]["cost"]["tokens"] for r in rows for n in SIGNAL_NAMES)
    out["signal_cost_share"] = round(sig / tot, 4) if tot else None
    out["any_signal_predicts_error"] = any(v.get("predicts_error") for v in out["signals"].values())
    return out
