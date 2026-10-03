"""사전 등록 생성기 (CMD-AMP1 done_when (1)). 같은 인자 → 같은 바이트(정렬된 JSON, 시각 칸 없음).

분할(묶음마다, 원천 풀을 시드로 한 번 섞어 앞에서부터 자른다):
  pilot        첫 호출 몇 번(호출당 토큰 · 표본 갈림)을 재는 데만 쓴다. AUROC 에 들어가지 않는다.
  calibration  novelty 기준 문장 · 오류율 p_cal 추정. AUROC 에 들어가지 않는다.
  eval         AUROC 를 내는 유일한 분할. 정해진 순서로 앞에서부터 돌리고, 양성(단계 오류)이 E_min 에 닿거나
               max_eval 에 닿거나 예산 지킴이가 멈추면 끝낸다(양성 수만 보는 정지 규칙 — 신호 값은 보지 않는다).
검정력 규칙(측정 전에 고정): 보정 분할의 단계 오류율 p_cal 로 기대 양성 = p_cal × 2 × max_eval 를 잰다.
  그것이 E_min 보다 작으면 `insufficient_rule` 을 따른다.
    harder_subset  eval 순서를 `harder_order`(난이도 내림차순, 같은 난이도는 섞인 순서) 로 바꾼다.
    underpowered   eval 은 그대로 돌리고 그 묶음을 "검정력 부족" 으로 보고한다.
"""
from __future__ import annotations

import hashlib
import json
import random

from . import prompts
from .analyze import ANALYSIS_VERSION
from .callers import HAIKU_PRICE, ClaudeCLICaller
from .forms import SIGNAL_NAMES, TRACE_SCHEMA
from .signals import SIGNALS_VERSION
from .tasks import Task

PREREG_SCHEMA = "amp-prereg/1"
RULES = ("harder_subset", "underpowered")


def split_pool(tasks: list[Task], seed: int, suite: str, n_pilot: int, n_cal: int, max_eval: int) -> dict:
    ids = sorted(t.task_id for t in tasks)
    rng = random.Random(f"{seed}:{suite}")
    rng.shuffle(ids)
    need = n_pilot + n_cal + max_eval
    if need > len(ids):
        raise ValueError(f"{suite}: pool {len(ids)} < pilot+calibration+eval {need}")
    pilot, cal, rest = ids[:n_pilot], ids[n_pilot:n_pilot + n_cal], ids[n_pilot + n_cal:]
    diff = {t.task_id: t.difficulty for t in tasks}
    pos = {tid: i for i, tid in enumerate(rest)}
    harder = sorted(rest, key=lambda t: (-diff[t], pos[t]))
    return {"pilot": pilot, "calibration": cal, "eval_order": rest[:max_eval], "harder_order": harder[:max_eval],
            "pool_size": len(ids)}


def build(sources: dict, tasks: dict, *, seed: int, n_samples: int, e_min: int, insufficient_rule: str,
          n_pilot: int, n_cal: int, max_eval: dict, budget_usd: dict, note: str = "") -> dict:
    """sources: {suite: {"file": 이름, "sha256": …}} · tasks: {suite: [Task]}."""
    if insufficient_rule not in RULES:
        raise ValueError(f"insufficient_rule must be one of {RULES}")
    suites = {}
    for suite in sorted(tasks):
        sp = split_pool(tasks[suite], seed, suite, n_pilot, n_cal, max_eval[suite])
        suites[suite] = {"source": sources[suite], "pool_size": sp["pool_size"], "max_eval": max_eval[suite],
                         "pilot": sp["pilot"], "calibration": sp["calibration"], "eval_order": sp["eval_order"],
                         "harder_order": sp["harder_order"],
                         "difficulty": {"gsm8k": "nonblank lines of the reference solution before ####",
                                        "mbpp": "nonblank lines of the reference code"}[suite]}
    sample_cli = ClaudeCLICaller("<CLAUDE_CONFIG_DIR>").argv("<role prompt>", "<new uuid4>")
    return {
        "schema": PREREG_SCHEMA,
        "spec": "AMP.md amp-1 rev 1 §10 P1a",
        "directive": "CMD-AMP1 rev 6",
        "note": note,
        "seed": seed,
        "n_samples": n_samples,
        "e_min": e_min,
        "insufficient_rule": insufficient_rule,
        "power_rule": "expected positives = p_cal * 2 * max_eval; if < e_min apply insufficient_rule (decided after calibration, before eval)",
        "stopping_rule": "eval in listed order until eval positives >= e_min, or max_eval tasks, or budget stop",
        "suites": suites,
        "steps": {
            "gsm8k": {"1": "solve, n samples, step answer = modal number", "2": "check given step-1 answer, n samples, modal number",
                      "label": "step answer != gold"},
            "mbpp": {"1": "write; only the first assert shown; n samples; step answer = first sample",
                     "2": "fix given step-1 code and shown-test result; n samples; first sample",
                     "label": "step code fails any hidden assert (asserts 2..)"}},
        "signals": {"version": SIGNALS_VERSION, "names": list(SIGNAL_NAMES),
                    "uncertainty": "sample_disagreement = 1 - mode_count/n (gsm8k: extracted number, mbpp: shown-test outcome)",
                    "uncertainty_secondary": "token entropy from logprobs when the caller returns them (reported, not the primary)",
                    "prediction_error": "gsm8k: unparseable fraction; mbpp: shown test failed for the step answer",
                    "novelty": "1 - max char-3gram Jaccard vs calibration texts",
                    "contradiction": "step 2 only: gsm8k check != solve; mbpp shown outcome changed; step 1 unknown",
                    "stakes": "fixed local (0.5) — expected no variance → not_estimable",
                    "unknown_is_not_zero": True},
        "host": {"loop": "amp.loop (self-built minimal loop, AMP.md §9)", "trace": TRACE_SCHEMA,
                 "roles_sha256": prompts.roles_sha256(),
                 "callers": {"claude-cli": {"argv": sample_cli, "env": "copy of parent minus CLAUDE_CODE_SESSION_ID; CLAUDE_CONFIG_DIR = run-private dir",
                                            "instrument": "result usage vs transcript usage (dedup by message id); > 5% = invalid; missing = unverified"},
                             "anthropic-api": {"model": "claude-haiku-4-5", "temperature": 1.0, "max_tokens": 1024},
                             "gemini-api": {"model": "<chosen with the path>", "temperature": 1.0, "responseLogprobs": True}},
                 "same_settings_for_all_conditions": True,
                 "code_execution": "amp.sandbox (python -I subprocess, timeout 10 s), not a model tool"},
        "analysis": {"version": ANALYSIS_VERSION, "split": "eval", "positive": "step error", "auroc": "Mann-Whitney, ties 0.5",
                     "ci": "95% percentile, task-cluster bootstrap, 2000 reps, seed 0",
                     "excluded": "unknown signal values and invalid steps (counted)",
                     "predicts_error": "lower CI bound > 0.5", "not_estimable": "positives < e_min, no negatives, or no variance"},
        "budget_usd": budget_usd,
        "price_assumption_usd_per_mtok": {"claude-haiku-4-5": HAIKU_PRICE,
                                          "note": "input/output from Anthropic price table; cache rates assumed 1.25x / 0.1x of input"},
        "revision_rule": "pilot calls may change n_samples and max_eval before any calibration or eval call; that makes a new prereg file with a new sha256, splits keep the same seed",
    }


def dumps(doc: dict) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


def sha256(doc: dict) -> str:
    return hashlib.sha256(dumps(doc)).hexdigest()


def main(argv=None) -> int:
    """python -m amp.prereg --data-dir <데이터> --out prereg/p1a.json [인자…] — 사전 등록 파일을 쓰고 sha256 을 찍는다."""
    import argparse
    import os

    from .tasks import load_gsm8k, load_mbpp, sha256_file

    ap = argparse.ArgumentParser(prog="python -m amp.prereg")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261003)
    ap.add_argument("--n-samples", type=int, default=5)
    ap.add_argument("--e-min", type=int, default=40)
    ap.add_argument("--rule", default="harder_subset", choices=RULES)
    ap.add_argument("--n-pilot", type=int, default=10)
    ap.add_argument("--n-cal", type=int, default=40)
    ap.add_argument("--max-eval-gsm8k", type=int, default=200)
    ap.add_argument("--max-eval-mbpp", type=int, default=200)
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    files = {"gsm8k": "gsm8k_test.jsonl", "mbpp": "mbpp.jsonl"}
    sources = {s: {"file": f, "sha256": sha256_file(os.path.join(a.data_dir, f))} for s, f in files.items()}
    tasks = {"gsm8k": load_gsm8k(os.path.join(a.data_dir, files["gsm8k"])),
             "mbpp": load_mbpp(os.path.join(a.data_dir, files["mbpp"]))}
    doc = build(sources, tasks, seed=a.seed, n_samples=a.n_samples, e_min=a.e_min, insufficient_rule=a.rule,
                n_pilot=a.n_pilot, n_cal=a.n_cal, max_eval={"gsm8k": a.max_eval_gsm8k, "mbpp": a.max_eval_mbpp},
                budget_usd={"total": 15, "worker_turns": 6, "judge": 1, "measurement": 7, "reserve": 1}, note=a.note)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "wb") as f:
        f.write(dumps(doc))
    print(sha256(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
