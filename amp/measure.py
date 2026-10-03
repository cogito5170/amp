"""측정 고리 입구: 사전 등록 파일을 읽고, 고른 호출기로 pilot · calibration · eval 을 돌리고, trace · 요약 · 분석을 쓴다.

    python -m amp.measure --prereg prereg/p1a.json --data-dir <데이터> --caller fake --out runs/fake --cap 7
    (--phase pilot 이면 pilot 분할만)

- 원천 파일의 sha256 이 사전 등록과 다르면 돌리지 않는다.
- 호출이 실패하면 · 예산에 닿으면 그 자리에서 멈추고 까닭을 요약에 남긴다(실패를 통과로 세지 않는다).
- 실제 호출기(claude-cli · anthropic-api · gemini-api)는 이 입구에서 고를 수 있지만, 실제 측정은 baseline 의 다음 지시 뒤에 한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .analyze import analyze
from .callers import AnthropicAPICaller, CallError, ClaudeCLICaller, FakeCaller, GeminiCaller
from .instrument import BudgetGuard
from .loop import RUNNERS, RunStop, Sampler
from .signals import Novelty
from .tasks import load_gsm8k, load_mbpp, sha256_file

LOADERS = {"gsm8k": load_gsm8k, "mbpp": load_mbpp}


def load_tasks(prereg: dict, data_dir: str) -> dict:
    out = {}
    for suite, s in prereg["suites"].items():
        path = os.path.join(data_dir, s["source"]["file"])
        got = sha256_file(path)
        if got != s["source"]["sha256"]:
            raise SystemExit(f"{suite}: source sha256 {got} != prereg {s['source']['sha256']}")
        out[suite] = {t.task_id: t for t in LOADERS[suite](path)}
    return out


def run(prereg: dict, tasks: dict, caller, out_dir: str, cap_usd: float, initial_estimate: float,
        phase: str = "all", e_min: int | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    e_min = prereg["e_min"] if e_min is None else e_min
    n = prereg["n_samples"]
    guard = BudgetGuard(cap_usd, initial_estimate)
    sampler = Sampler(caller, guard)
    rows: list[dict] = []
    summary = {"schema": "amp-run/1", "caller": getattr(caller, "kind", "?"), "phase": phase, "n_samples": n,
               "e_min": e_min, "cap_usd": cap_usd, "suites": {}, "stopped": None}
    trace_path = os.path.join(out_dir, "trace.jsonl")
    with open(trace_path, "w", encoding="utf-8") as tf:
        def emit(new):
            for r in new:
                tf.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            rows.extend(new)

        try:
            for suite in sorted(prereg["suites"]):
                s = prereg["suites"][suite]
                ts = tasks[suite]
                runner = RUNNERS[suite]
                novelty = Novelty([ts[t].text for t in s["calibration"]])
                info = summary["suites"][suite] = {"pilot": 0, "calibration": 0, "eval": 0}
                for tid in s["pilot"]:
                    emit(runner(ts[tid], "pilot", sampler, n, novelty))
                    info["pilot"] += 1
                if phase == "pilot":
                    continue
                for tid in s["calibration"]:
                    emit(runner(ts[tid], "calibration", sampler, n, novelty))
                    info["calibration"] += 1
                cal = [r for r in rows if r["suite"] == suite and r["split"] == "calibration" and not r["invalid"]]
                p_cal = sum(r["label"] for r in cal) / len(cal) if cal else 0.0
                expected = p_cal * 2 * s["max_eval"]
                order, rule_applied = s["eval_order"], None
                if expected < e_min:
                    rule_applied = prereg["insufficient_rule"]
                    if rule_applied == "harder_subset":
                        order = s["harder_order"]
                info.update(p_cal=round(p_cal, 4), expected_positives=round(expected, 2), rule_applied=rule_applied)
                pos = 0
                for tid in order:
                    if pos >= e_min:
                        break
                    new = runner(ts[tid], "eval", sampler, n, novelty)
                    emit(new)
                    pos += sum(r["label"] == 1 and not r["invalid"] for r in new)
                    info["eval"] += 1
                info["eval_positives"] = pos
                info["underpowered"] = pos < e_min
        except RunStop as e:
            summary["stopped"] = e.reason
    summary["spent_usd"] = round(guard.spent, 6)
    summary["calls"] = guard.calls
    summary["instrument"] = {s: sum(r.get("instrument") == s for r in rows) for s in ("verified", "unverified", "mismatch", "n/a")}
    summary["instrument_max_diff"] = sampler.max_diff
    summary["invalid_steps"] = sum(r["invalid"] for r in rows)
    summary["steps"] = len(rows)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, sort_keys=True, indent=1)
    result = {"summary": summary}
    if phase != "pilot":
        per = {suite: analyze([r for r in rows if r["suite"] == suite], e_min) for suite in sorted(prereg["suites"])}
        per["all"] = analyze(rows, e_min)
        with open(os.path.join(out_dir, "analysis.json"), "w", encoding="utf-8") as f:
            json.dump(per, f, ensure_ascii=False, sort_keys=True, indent=1)
        result["analysis"] = per
    return result


def fake_script(error_rate: float = 0.3):
    """가짜 측정용 답: GSM8K 는 표본마다 맞거나 틀린 수, MBPP 는 맞거나 틀린 코드 — 원문 데이터의 정답은 쓰지 않는다."""
    def script(system, user, k, rng):
        if "```python" in system or "Python" in system:
            body = "def f(*a, **k):\n    return None\n" if rng.random() < error_rate else "def f(*a, **k):\n    return 0\n"
            return f"```python\n{body}```"
        return f"ANSWER: {rng.randint(0, 3) if rng.random() < error_rate else 7}"
    return script


def oracle_script(tasks: dict, base_err: float = 0.1, slope: float = 0.5):
    """시뮬레이션 가짜 호출기: 정답을 알고, 과제 난이도가 높을수록 자주 틀린다(표본마다 따로).
    장치가 AUROC · 신뢰구간 경로를 끝까지 지나는지 보려는 것이다. 여기서 나온 AUROC 는 모형에 대해 아무것도 말하지 않는다."""
    by_text = {}
    for suite, ts in tasks.items():
        diffs = [t.difficulty for t in ts.values()] or [0]
        lo, hi = min(diffs), max(diffs)
        for t in ts.values():
            by_text[t.text] = (t, (t.difficulty - lo) / (hi - lo) if hi > lo else 0.0)

    def script(system, user, k, rng):
        hit = next(((t, d) for txt, (t, d) in by_text.items() if txt in user), None)
        if hit is None:
            return "ANSWER: 0"
        t, d = hit
        wrong = rng.random() < base_err + slope * d
        if t.suite == "gsm8k":
            return f"ANSWER: {rng.randint(0, 9) * 1000 + 1 if wrong else t.gold}"
        return "```python\n" + ("def __nothing__():\n    pass\n" if wrong else t.ref.replace("\r", "") + "\n") + "```"
    return script


def make_caller(name: str, out_dir: str, args, tasks: dict | None = None) -> object:
    if name == "fake":
        return FakeCaller(fake_script(args.fake_error_rate), seed=args.seed)
    if name == "fake-oracle":
        return FakeCaller(oracle_script(tasks or {}), seed=args.seed)
    if name == "claude-cli":
        return ClaudeCLICaller(config_dir=os.path.join(os.path.abspath(out_dir), "claude-config"))
    if name == "anthropic-api":
        return AnthropicAPICaller()
    if name == "gemini-api":
        if not args.gemini_model or not args.gemini_price:
            raise SystemExit("gemini-api needs --gemini-model and --gemini-price in:out (USD/MTok)")
        i, o = (float(x) for x in args.gemini_price.split(":"))
        return GeminiCaller(args.gemini_model, {"input": i, "output": o, "cache_read": 0.0, "cache_write": 0.0})
    raise SystemExit(f"unknown caller {name}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m amp.measure")
    ap.add_argument("--prereg", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--caller", default="fake", choices=("fake", "fake-oracle", "claude-cli", "anthropic-api", "gemini-api"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap", type=float, required=True, help="USD cap for this run (budget guard)")
    ap.add_argument("--initial-estimate", type=float, default=0.01, help="USD estimate of one call before any is seen")
    ap.add_argument("--phase", default="all", choices=("all", "pilot"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fake-error-rate", type=float, default=0.3)
    ap.add_argument("--gemini-model")
    ap.add_argument("--gemini-price")
    a = ap.parse_args(argv)
    with open(a.prereg, encoding="utf-8") as f:
        prereg = json.load(f)
    tasks = load_tasks(prereg, a.data_dir)
    res = run(prereg, tasks, make_caller(a.caller, a.out, a, tasks), a.out, a.cap, a.initial_estimate, a.phase)
    print(json.dumps(res["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if res["summary"]["stopped"] is None else 3


if __name__ == "__main__":
    sys.exit(main())
