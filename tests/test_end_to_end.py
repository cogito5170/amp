"""T9 가짜 호출기로 두 묶음을 끝까지: trace · 요약 · 분석 JSON 이 나오고 trace 는 꼴을 지킨다."""
import json
import os
import tempfile
import unittest

from amp import forms, measure, prereg
from amp.callers import CallError, FakeCaller
from amp.tasks import load_gsm8k, load_mbpp

from tests.helpers import write_synthetic


def read_json(path):
    with open(path) as f:
        return json.load(f)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        src = write_synthetic(os.path.join(d, "data"))
        tasks = {"gsm8k": load_gsm8k(os.path.join(d, "data", "gsm8k_test.jsonl")),
                 "mbpp": load_mbpp(os.path.join(d, "data", "mbpp.jsonl"))}
        self.doc = prereg.build(src, tasks, seed=3, n_samples=3, e_min=5, insufficient_rule="harder_subset",
                                n_pilot=2, n_cal=6, max_eval={"gsm8k": 20, "mbpp": 20}, budget_usd={"total": 15})
        self.tasks = measure.load_tasks(self.doc, os.path.join(d, "data"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_fake_run_writes_valid_trace_and_analysis(self):
        out = os.path.join(self.tmp.name, "run")
        res = measure.run(self.doc, self.tasks, FakeCaller(measure.fake_script(0.4), seed=1), out, cap_usd=5.0,
                          initial_estimate=0.0)
        self.assertIsNone(res["summary"]["stopped"])
        with open(os.path.join(out, "trace.jsonl")) as f:
            rows = [json.loads(line) for line in f]
        self.assertTrue(rows)
        for r in rows:
            forms.check_trace(r)
        self.assertEqual({r["split"] for r in rows}, {"pilot", "calibration", "eval"})
        self.assertEqual({r["step"] for r in rows}, {1, 2})
        an = read_json(os.path.join(out, "analysis.json"))
        self.assertEqual(set(an), {"gsm8k", "mbpp", "all"})
        for name in forms.SIGNAL_NAMES:
            self.assertIn(name, an["all"]["signals"])
        self.assertEqual(an["all"]["signals"]["stakes"]["status"], "not_estimable")
        self.assertIsNotNone(an["all"]["signal_cost_share"])
        s = read_json(os.path.join(out, "summary.json"))
        self.assertEqual(s["instrument_max_diff"], 0.0)
        for suite in ("gsm8k", "mbpp"):
            info = s["suites"][suite]
            self.assertEqual(info["pilot"], 2)
            self.assertEqual(info["calibration"], 6)
            self.assertGreaterEqual(info["eval_positives"], 5)          # 정지 규칙: E_min 에 닿으면 멈춤
            self.assertLess(info["eval_positives"], 5 + 2)              # 과제 하나는 양성을 많아야 2 개 더한다
            self.assertLessEqual(info["eval"], 20)
        # 원문이 어디에도 없다
        with open(os.path.join(out, "trace.jsonl")) as f:
            raw = f.read()
        self.assertNotIn("ANSWER", raw)
        self.assertNotIn("def f", raw)
        self.assertNotIn("apples", raw)

    def test_oracle_simulation_reaches_estimates(self):
        """정답을 아는 시뮬레이션 호출기로 AUROC · 신뢰구간 경로를 끝까지 지난다(값은 모형에 대해 아무것도 말하지 않는다)."""
        out = os.path.join(self.tmp.name, "oracle")
        caller = FakeCaller(measure.oracle_script(self.tasks, base_err=0.2, slope=0.6), seed=2)
        res = measure.run(self.doc, self.tasks, caller, out, cap_usd=5.0, initial_estimate=0.0)
        an = res["analysis"]["all"]
        self.assertEqual(an["signals"]["uncertainty"]["status"], "estimated")
        lo, hi = an["signals"]["uncertainty"]["ci95"]
        self.assertLessEqual(lo, an["signals"]["uncertainty"]["auroc"])
        self.assertGreaterEqual(hi, an["signals"]["uncertainty"]["auroc"])
        self.assertEqual(an["signals"]["stakes"]["status"], "not_estimable")

    def test_call_error_stops_and_is_reported(self):
        calls = {"n": 0}

        def script(s, u, k, rng):           # 열한 번째 호출에서 사용량 한도
            calls["n"] += 1
            return CallError("is_error", "limit") if calls["n"] == 11 else "ANSWER: 7"
        res = measure.run(self.doc, self.tasks, FakeCaller(script), os.path.join(self.tmp.name, "err"), cap_usd=5.0,
                          initial_estimate=0.0)
        self.assertEqual(res["summary"]["stopped"], "call_error:is_error")
        self.assertEqual(res["summary"]["calls"], 10)
        # 과제 1 은 끝났다(6 호출 → 단계 2 줄). 과제 2 는 단계 2 에서 실패했다 — 끝나지 않은 과제의 단계는 내지 않는다
        self.assertEqual(res["summary"]["steps"], 2)
        fc = FakeCaller(lambda s, u, k, rng: CallError("is_error", "limit"))
        res = measure.run(self.doc, self.tasks, fc, os.path.join(self.tmp.name, "err2"), cap_usd=5.0, initial_estimate=0.0)
        self.assertEqual(res["summary"]["stopped"], "call_error:is_error")
        self.assertEqual(res["summary"]["steps"], 0)

    def test_budget_stop(self):
        res = measure.run(self.doc, self.tasks, FakeCaller(measure.fake_script(), seed=1), os.path.join(self.tmp.name, "b"),
                          cap_usd=0.0005, initial_estimate=0.0001)
        self.assertEqual(res["summary"]["stopped"], "budget")
        self.assertLessEqual(res["summary"]["spent_usd"], 0.0005)

    def test_pilot_phase_only(self):
        res = measure.run(self.doc, self.tasks, FakeCaller(measure.fake_script(), seed=1), os.path.join(self.tmp.name, "p"),
                          cap_usd=5.0, initial_estimate=0.0, phase="pilot")
        self.assertNotIn("analysis", res)
        self.assertEqual(res["summary"]["suites"]["gsm8k"], {"pilot": 2, "calibration": 0, "eval": 0})

    def test_source_sha_mismatch_refuses(self):
        bad = json.loads(json.dumps(self.doc))
        bad["suites"]["gsm8k"]["source"]["sha256"] = "0" * 64
        with self.assertRaises(SystemExit):
            measure.load_tasks(bad, os.path.join(self.tmp.name, "data"))


if __name__ == "__main__":
    unittest.main()
