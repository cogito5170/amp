"""자체 최소 고리: 과제 하나를 단계 2 개로 돌리고 단계마다 amp-trace/1 한 줄을 낸다 (AMP.md §9 주 실험장).

- GSM8K: 단계 1 풀이(n 표본, 최빈 수 = 단계 답) → 단계 2 검산(단계 1 답을 보여 주고 다시 풂, n 표본). 단계 오류 = 최빈 답 ≠ 정답.
- MBPP: 단계 1 코드 쓰기(첫 assert 만 보임, n 표본, 첫 표본 = 단계 답) → 단계 2 고치기(단계 1 코드와 보인 assert 결과를 줌).
  단계 오류 = 그 단계 코드가 숨긴 assert 하나라도 통과하지 못함.
- 답 · 코드 원문은 메모리에서만 쓴다. trace 에는 수와 라벨만 남는다.
- 호출이 실패하면(`CallError`) · 예산에 닿으면(`BudgetStop`) 그 자리에서 멈춘다. 끝나지 않은 과제의 단계는 내지 않는다.
"""
from __future__ import annotations

import time

from . import prompts, sandbox, signals
from .callers import CallError, CallResult
from .forms import TRACE_SCHEMA, check_trace
from .instrument import BudgetGuard, BudgetStop
from .tasks import Task, extract_code, extract_number

_WORST = {"n/a": 0, "verified": 1, "unverified": 2, "mismatch": 3}


class RunStop(RuntimeError):
    """고리를 멈춘다. reason: call_error:<kind> · budget."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class Sampler:
    """호출기 + 예산 지킴이. 단계 하나의 호출을 모아 토큰 · 비용 · 계기 상태를 센다."""

    def __init__(self, caller, guard: BudgetGuard):
        self.caller, self.guard = caller, guard
        self.max_diff: float | None = None     # 계기 대조 최대 상대 차(잰 호출만)

    def sample(self, role: str, user: str, n: int) -> list[CallResult]:
        out = []
        for _ in range(n):
            try:
                self.guard.before()
            except BudgetStop as e:
                raise RunStop("budget") from e
            try:
                r = self.caller.complete(prompts.ROLES[role], user)
            except CallError as e:
                raise RunStop(f"call_error:{e.kind}") from e
            self.guard.after(r.cost_usd)
            if r.instrument_diff is not None:
                self.max_diff = max(self.max_diff or 0.0, r.instrument_diff)
            out.append(r)
        return out


def _row(task: Task, split: str, step: int, sigs: dict, label: int | None, results: list[CallResult], t0: float) -> dict:
    tok = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for r in results:
        for k in tok:
            tok[k] += r.usage.get(k, 0)
    inst = max((r.instrument for r in results), key=_WORST.__getitem__, default="n/a")
    row = {"schema": TRACE_SCHEMA, "suite": task.suite, "task_id": task.task_id, "split": split, "step": step,
           "signals": sigs, "label": label, "calls": len(results), "tokens": tok,
           "cost_usd": round(sum(r.cost_usd for r in results), 8), "latency_s": round(time.monotonic() - t0, 4),
           "invalid": inst == "mismatch", "instrument": inst}
    if row["invalid"]:
        row["invalid_reason"] = "instrument_mismatch"
    check_trace(row)
    return row


def _signal_cost(results: list[CallResult]) -> int:
    """표본 n−1 개(첫 표본 밖)의 토큰 — 불확실성을 재는 데 든 추가 계산."""
    return sum(sum(r.usage.values()) for r in results[1:])


def _with_cost(s: dict, tokens: int) -> dict:
    s = dict(s)
    s["cost"] = {"tokens": int(tokens), "seconds": s["cost"]["seconds"]}
    return s


def run_gsm8k(task: Task, split: str, sampler: Sampler, n: int, novelty: signals.Novelty) -> list[dict]:
    nov = novelty(task.text, exclude_self=(split == "calibration"))
    rows = []
    t0 = time.monotonic()
    r1 = sampler.sample("gsm8k.solve", prompts.gsm8k_solve(task.text), n)
    a1 = [extract_number(r.text) for r in r1]
    m1 = signals.mode(a1)
    sig1 = {"uncertainty": _with_cost(signals.uncertainty_signal(a1), _signal_cost(r1)),
            "prediction_error": signals.prediction_error_signal(sum(a is None for a in a1) / n, "gsm8k_unparseable_fraction"),
            "novelty": nov, "contradiction": signals.contradiction_signal(None, "gsm8k_check_vs_solve"),
            "stakes": signals.stakes_signal("local")}
    rows.append(_row(task, split, 1, sig1, int(m1 != task.gold), r1, t0))
    t0 = time.monotonic()
    r2 = sampler.sample("gsm8k.check", prompts.gsm8k_check(task.text, m1), n)
    a2 = [extract_number(r.text) for r in r2]
    m2 = signals.mode(a2)
    sig2 = {"uncertainty": _with_cost(signals.uncertainty_signal(a2), _signal_cost(r2)),
            "prediction_error": signals.prediction_error_signal(sum(a is None for a in a2) / n, "gsm8k_unparseable_fraction"),
            "novelty": nov, "contradiction": signals.contradiction_signal(float(m2 != m1), "gsm8k_check_vs_solve"),
            "stakes": signals.stakes_signal("local")}
    rows.append(_row(task, split, 2, sig2, int(m2 != task.gold), r2, t0))
    return rows


def _hidden_fail(code: str, task: Task, timeout: float) -> int:
    hidden = list(task.tests[1:]) or list(task.tests)
    return int(sandbox.run_tests(code, hidden, task.setup, timeout) != sandbox.PASS)


def run_mbpp(task: Task, split: str, sampler: Sampler, n: int, novelty: signals.Novelty, timeout: float = 10.0) -> list[dict]:
    nov = novelty(task.text, exclude_self=(split == "calibration"))
    shown = task.tests[0]
    rows = []
    t0 = time.monotonic()
    r1 = sampler.sample("mbpp.write", prompts.mbpp_write(task.text, shown), n)
    c1 = [extract_code(r.text) for r in r1]
    o1 = [sandbox.run_tests(c, [shown], task.setup, timeout) for c in c1]
    sig1 = {"uncertainty": _with_cost(signals.uncertainty_signal(o1), _signal_cost(r1)),
            "prediction_error": signals.prediction_error_signal(float(o1[0] != sandbox.PASS), "mbpp_shown_test_fail"),
            "novelty": nov, "contradiction": signals.contradiction_signal(None, "mbpp_fix_vs_write_shown_outcome"),
            "stakes": signals.stakes_signal("local")}
    rows.append(_row(task, split, 1, sig1, _hidden_fail(c1[0], task, timeout), r1, t0))
    t0 = time.monotonic()
    r2 = sampler.sample("mbpp.fix", prompts.mbpp_fix(task.text, shown, c1[0], o1[0]), n)
    c2 = [extract_code(r.text) for r in r2]
    o2 = [sandbox.run_tests(c, [shown], task.setup, timeout) for c in c2]
    sig2 = {"uncertainty": _with_cost(signals.uncertainty_signal(o2), _signal_cost(r2)),
            "prediction_error": signals.prediction_error_signal(float(o2[0] != sandbox.PASS), "mbpp_shown_test_fail"),
            "novelty": nov,
            "contradiction": signals.contradiction_signal(float(o2[0] != o1[0]), "mbpp_fix_vs_write_shown_outcome"),
            "stakes": signals.stakes_signal("local")}
    rows.append(_row(task, split, 2, sig2, _hidden_fail(c2[0], task, timeout), r2, t0))
    return rows


RUNNERS = {"gsm8k": run_gsm8k, "mbpp": run_mbpp}
