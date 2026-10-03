"""T6 MBPP 샌드박스 · T7 사전 등록 결정성 · T8 AUROC · 신호 · 과제 뽑기."""
import os
import tempfile
import unittest

from amp import analyze, prereg, sandbox, signals
from amp.tasks import extract_code, extract_number, load_gsm8k, load_mbpp, norm_number

from tests.helpers import write_synthetic


class Sandbox(unittest.TestCase):  # T6
    def test_pass_fail_timeout_error(self):
        tests = ["assert add(1, 2) == 3"]
        self.assertEqual(sandbox.run_tests("def add(a, b):\n    return a + b\n", tests), sandbox.PASS)
        self.assertEqual(sandbox.run_tests("def add(a, b):\n    return a - b\n", tests), sandbox.FAIL)
        self.assertEqual(sandbox.run_tests("def add(a, b):\n    while True: pass\n", tests, timeout=1.0), sandbox.TIMEOUT)
        self.assertEqual(sandbox.run_tests("def add(a, b)\n    return 1\n", tests), sandbox.ERROR)
        self.assertEqual(sandbox.run_tests("import sys\ndef add(a, b):\n    sys.exit(0)\n", tests), sandbox.FAIL)

    def test_setup_code(self):
        self.assertEqual(sandbox.run_tests("def g():\n    return K\n", ["assert g() == 5"], setup="K = 5"), sandbox.PASS)


class Prereg(unittest.TestCase):  # T7
    def test_same_args_same_bytes_and_disjoint_splits(self):
        with tempfile.TemporaryDirectory() as d:
            src = write_synthetic(d)
            tasks = {"gsm8k": load_gsm8k(os.path.join(d, "gsm8k_test.jsonl")), "mbpp": load_mbpp(os.path.join(d, "mbpp.jsonl"))}
            kw = dict(seed=7, n_samples=5, e_min=4, insufficient_rule="harder_subset", n_pilot=2, n_cal=5,
                      max_eval={"gsm8k": 20, "mbpp": 20}, budget_usd={"total": 15})
            a = prereg.dumps(prereg.build(src, tasks, **kw))
            b = prereg.dumps(prereg.build(src, tasks, **kw))
            self.assertEqual(a, b)
            c = prereg.dumps(prereg.build(src, tasks, **dict(kw, seed=8)))
            self.assertNotEqual(a, c)
            doc = prereg.build(src, tasks, **kw)
            for s in doc["suites"].values():
                p, cal, ev = set(s["pilot"]), set(s["calibration"]), set(s["eval_order"])
                self.assertFalse(p & cal or p & ev or cal & ev)
                hard = s["harder_order"]
                self.assertFalse(set(hard) & (p | cal))
                self.assertEqual(len(hard), len(ev))
                diff = {t.task_id: t.difficulty for t in tasks["gsm8k"] + tasks["mbpp"]}
                self.assertEqual([diff[x] for x in hard], sorted((diff[x] for x in hard), reverse=True))
            with self.assertRaises(ValueError):
                prereg.build(src, tasks, **dict(kw, insufficient_rule="maybe"))


class Auroc(unittest.TestCase):  # T8
    def test_known_values(self):
        self.assertEqual(analyze.auroc([0.9, 0.8, 0.1, 0.2], [1, 1, 0, 0]), 1.0)
        self.assertEqual(analyze.auroc([0.1, 0.2, 0.9, 0.8], [1, 1, 0, 0]), 0.0)
        self.assertEqual(analyze.auroc([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]), 0.5)
        self.assertAlmostEqual(analyze.auroc([0.3, 0.5, 0.5, 0.1], [1, 1, 0, 0]), 0.625)  # (0+1+.5+1)/4
        self.assertIsNone(analyze.auroc([0.1, 0.2], [1, 1]))

    def test_random_near_half(self):
        import random
        rng = random.Random(1)
        xs = [rng.random() for _ in range(4000)]
        ys = [rng.randint(0, 1) for _ in range(4000)]
        self.assertAlmostEqual(analyze.auroc(xs, ys), 0.5, delta=0.03)

    def test_not_estimable_and_ci(self):
        from tests.test_forms import good_trace
        rows = []
        for i in range(60):
            t = good_trace()
            t["task_id"] = f"t{i}"
            t["label"] = int(i % 2 == 0)
            t["signals"]["novelty"]["value"] = 0.9 if i % 2 == 0 else 0.1
            rows.append(t)
        res = analyze.analyze(rows, e_min=20, reps=200)
        self.assertEqual(res["signals"]["novelty"]["status"], "estimated")
        self.assertEqual(res["signals"]["novelty"]["auroc"], 1.0)
        self.assertTrue(res["signals"]["novelty"]["predicts_error"])
        self.assertEqual(res["signals"]["stakes"]["status"], "not_estimable")       # 0.5 고정 → 분산 없음
        self.assertEqual(res["signals"]["contradiction"]["unknown"], 60)
        res = analyze.analyze(rows, e_min=100, reps=50)
        self.assertEqual(res["signals"]["novelty"]["status"], "not_estimable")
        self.assertIn("positives 30 < E_min 100", res["signals"]["novelty"]["why"])


class Pieces(unittest.TestCase):
    def test_disagreement_and_mode(self):
        self.assertEqual(signals.disagreement(["7", "7", "7", "7", "7"]), 0.0)
        self.assertAlmostEqual(signals.disagreement(["7", "7", "3", None, "7"]), 0.4)
        self.assertIsNone(signals.disagreement(["7"]))
        self.assertEqual(signals.mode(["3", "7", "7", "3"]), "3")

    def test_entropy_secondary(self):
        self.assertIsNone(signals.entropy_from_logprobs(None))
        self.assertAlmostEqual(signals.entropy_from_logprobs([0.0, 0.0]), 0.0)
        self.assertGreater(signals.entropy_from_logprobs([-2.0, -3.0]), 0.9)

    def test_number_and_code_extraction(self):
        self.assertEqual(extract_number("so 12 + 3\nANSWER: 1,234"), "1234")
        self.assertEqual(extract_number("the total is $18.50."), "18.5")
        self.assertIsNone(extract_number("no idea"))
        self.assertEqual(norm_number(" 72 "), "72")
        self.assertEqual(extract_code("here\n```python\ndef f():\n    return 1\n```\nbye"), "def f():\n    return 1\n")

    def test_novelty(self):
        nov = signals.Novelty(["Tom has 3 apples", "A train leaves at noon"])
        self.assertAlmostEqual(nov("Tom has 3 apples")["value"], 0.0)
        self.assertGreater(nov("Quantum flux capacitor")["value"], 0.8)
        self.assertEqual(signals.Novelty([])("x")["validity"], "unknown")


if __name__ == "__main__":
    unittest.main()
