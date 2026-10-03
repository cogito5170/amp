"""T1 꼴 정상 · 틀린 예, 원문 칸 거부."""
import copy
import unittest

from amp import forms
from amp.forms import FormError, check_signal, check_trace, signal, unknown


def good_trace():
    sigs = {n: signal(n, 0.5, "valid", "test") for n in forms.SIGNAL_NAMES}
    sigs["contradiction"] = unknown("contradiction", "test")
    return {"schema": forms.TRACE_SCHEMA, "suite": "gsm8k", "task_id": "gsm8k-0001", "split": "eval", "step": 1,
            "signals": sigs, "label": 1, "calls": 5, "tokens": {"input": 10, "output": 5, "cache_read": 0, "cache_write": 0},
            "cost_usd": 0.001, "latency_s": 0.2, "invalid": False, "instrument": "verified"}


class Signals(unittest.TestCase):
    def test_good(self):
        check_signal(signal("novelty", 0.3, "valid", "char3"))
        check_signal(unknown("uncertainty", "sample_disagreement"))

    def test_unknown_is_not_zero(self):
        s = signal("novelty", 0.0, "valid", "x")
        s["validity"] = "unknown"
        with self.assertRaises(FormError):
            check_signal(s)
        with self.assertRaises(FormError):
            signal("novelty", None, "valid", "x")

    def test_out_of_range_and_names(self):
        with self.assertRaises(FormError):
            signal("novelty", 1.2, "valid", "x")
        with self.assertRaises(FormError):
            signal("loudness", 0.2, "valid", "x")
        with self.assertRaises(FormError):
            signal("novelty", 0.2, "valid", "")
        with self.assertRaises(FormError):
            signal("novelty", True, "valid", "x")


class Traces(unittest.TestCase):
    def test_good(self):
        check_trace(good_trace())

    def test_missing_signal_and_bad_label(self):
        t = good_trace()
        del t["signals"]["stakes"]
        self.assertTrue(forms.trace_problems(t))
        t = good_trace()
        t["label"] = 2
        self.assertTrue(forms.trace_problems(t))
        t = good_trace()
        t["invalid"] = True
        self.assertIn("trace.invalid_reason: required when invalid", forms.trace_problems(t))

    def test_raw_text_rejected_anywhere(self):
        for path in (("prompt",), ("answer",), ("signals", "novelty", "text")):
            t = copy.deepcopy(good_trace())
            node = t
            for k in path[:-1]:
                node = node[k]
            node[path[-1]] = "secret words"
            with self.assertRaises(FormError) as cm:
                check_trace(t)
            self.assertTrue(any("raw text" in p for p in cm.exception.problems), path)


if __name__ == "__main__":
    unittest.main()
