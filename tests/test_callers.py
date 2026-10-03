"""T2 자식 환경 · T3 is_error 멈춤 · T4 계기 대조 · T5 예산 지킴이. 실제 claude · 네트워크는 부르지 않는다."""
import json
import os
import tempfile
import unittest

from amp import callers
from amp.callers import AnthropicAPICaller, CallError, ClaudeCLICaller, FakeCaller, GeminiCaller
from amp.instrument import BudgetGuard, BudgetStop, cross_check
from amp.loop import RunStop, Sampler


def cli_result(sid, inp=100, out=20, is_error=False, subtype="success"):
    return json.dumps({"type": "result", "subtype": subtype, "is_error": is_error, "result": "ANSWER: 7",
                       "session_id": sid, "total_cost_usd": 0.0002,
                       "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": 0,
                                 "cache_creation_input_tokens": 0}})


def write_transcript(config_dir, sid, inp, out, dup=True):
    d = os.path.join(config_dir, "projects", "-tmp-x")
    os.makedirs(d, exist_ok=True)
    msg = {"id": "msg_1", "role": "assistant", "usage": {"input_tokens": inp, "output_tokens": out}}
    with open(os.path.join(d, f"{sid}.jsonl"), "w") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user"}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": msg}) + "\n")
        if dup:  # 같은 message.id 가 두 줄 — 한 번만 센다
            f.write(json.dumps({"type": "assistant", "message": msg}) + "\n")


class FakeRunner:
    def __init__(self, make_out, transcript=None):
        self.make_out, self.transcript, self.calls = make_out, transcript, []

    def __call__(self, argv, stdin, env, timeout):
        sid = argv[argv.index("--session-id") + 1]
        self.calls.append({"argv": argv, "stdin": stdin, "env": env})
        if self.transcript:
            self.transcript(env["CLAUDE_CONFIG_DIR"], sid)
        return self.make_out(sid)


class ClaudeCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "cfg")

    def tearDown(self):
        self.tmp.cleanup()

    def test_argv_is_fixed_and_env_drops_parent_session(self):  # T2
        r = FakeRunner(lambda sid: (0, cli_result(sid), ""), lambda c, s: write_transcript(c, s, 100, 20))
        c = ClaudeCLICaller(self.cfg, runner=r, base_env={"PATH": "/bin", "CLAUDE_CODE_SESSION_ID": "parent-123", "HOME": "/h"})
        res = c.complete("ROLE", "question")
        call = r.calls[0]
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", call["env"])
        self.assertEqual(call["env"]["CLAUDE_CONFIG_DIR"], self.cfg)
        argv = call["argv"]
        self.assertEqual(argv[:9], ["claude", "-p", "--output-format", "json", "--model", "claude-haiku-4-5-20251001",
                                    "--tools", "", "--system-prompt"])
        self.assertIn("--strict-mcp-config", argv)
        sid = argv[argv.index("--session-id") + 1]
        self.assertNotEqual(sid, "parent-123")
        self.assertEqual(call["stdin"], "question")
        self.assertEqual(res.instrument, "verified")
        self.assertEqual(res.instrument_diff, 0.0)

    def test_is_error_raises(self):  # T3
        for out in (lambda sid: (1, cli_result(sid, is_error=True, subtype="error_during_execution"), ""),
                    lambda sid: (0, cli_result(sid, is_error=True), ""),
                    lambda sid: (1, "not json", "")):
            c = ClaudeCLICaller(self.cfg, runner=FakeRunner(out), base_env={})
            with self.assertRaises(CallError):
                c.complete("R", "q")

    def test_instrument_mismatch_and_unverified(self):  # T4
        r = FakeRunner(lambda sid: (0, cli_result(sid, 100, 20), ""), lambda c, s: write_transcript(c, s, 200, 20))
        res = ClaudeCLICaller(self.cfg, runner=r, base_env={}).complete("R", "q")
        self.assertEqual(res.instrument, "mismatch")
        self.assertGreater(res.instrument_diff, 0.05)
        r = FakeRunner(lambda sid: (0, cli_result(sid), ""))
        res = ClaudeCLICaller(os.path.join(self.tmp.name, "other"), runner=r, base_env={}).complete("R", "q")
        self.assertEqual(res.instrument, "unverified")
        self.assertIsNone(res.instrument_diff)


class CrossCheck(unittest.TestCase):  # T4
    def test_threshold(self):
        u = {"input": 100, "output": 0, "cache_read": 0, "cache_write": 0}
        self.assertEqual(cross_check(u, dict(u))[0], "verified")
        self.assertEqual(cross_check(u, dict(u, input=104))[0], "verified")
        self.assertEqual(cross_check(u, dict(u, input=106))[0], "mismatch")
        self.assertEqual(cross_check(u, None), ("unverified", None))


class Budget(unittest.TestCase):  # T5
    def test_guard_stops_before_cap(self):
        g = BudgetGuard(cap_usd=0.05, initial_estimate=0.02)
        g.before(); g.after(0.02)
        g.before(); g.after(0.02)
        with self.assertRaises(BudgetStop):
            g.before()
        self.assertLessEqual(g.spent, 0.05)

    def test_sampler_does_not_call_past_cap(self):
        fc = FakeCaller(lambda s, u, k, rng: "x" * 4000, price={"input": 1e3, "output": 1e3})
        s = Sampler(fc, BudgetGuard(cap_usd=3.0, initial_estimate=0.5))
        with self.assertRaises(RunStop) as cm:
            s.sample("gsm8k.solve", "q", 10)
        self.assertEqual(cm.exception.reason, "budget")
        self.assertLessEqual(s.guard.spent, 3.0)
        self.assertLess(fc.calls, 10)

    def test_sampler_stops_on_call_error(self):  # T3
        fc = FakeCaller(lambda s, u, k, rng: CallError("is_error", "usage limit") if k == 2 else "ANSWER: 1")
        s = Sampler(fc, BudgetGuard(1.0, 0.0))
        with self.assertRaises(RunStop) as cm:
            s.sample("gsm8k.solve", "q", 5)
        self.assertEqual(cm.exception.reason, "call_error:is_error")
        self.assertEqual(s.guard.calls, 2)


class HttpCallers(unittest.TestCase):
    def test_anthropic_parses_and_rate_limit_stops(self):
        os.environ["AMP_TEST_KEY"] = "k"
        try:
            ok = lambda url, h, b, t: (200, {"id": "m", "content": [{"type": "text", "text": "ANSWER: 3"}],
                                            "usage": {"input_tokens": 1000000, "output_tokens": 0}})
            r = AnthropicAPICaller(post=ok, key_env="AMP_TEST_KEY").complete("R", "q")
            self.assertEqual(r.text, "ANSWER: 3")
            self.assertAlmostEqual(r.cost_usd, 1.0)
            with self.assertRaises(CallError) as cm:
                AnthropicAPICaller(post=lambda *a: (429, {"type": "error"}), key_env="AMP_TEST_KEY").complete("R", "q")
            self.assertEqual(cm.exception.kind, "is_error")
        finally:
            del os.environ["AMP_TEST_KEY"]
        with self.assertRaises(CallError):
            AnthropicAPICaller(key_env="AMP_NO_SUCH_KEY").complete("R", "q")

    def test_gemini_logprobs(self):
        os.environ["AMP_TEST_KEY"] = "k"
        try:
            seen = {}

            def post(url, h, body, t):
                seen.update(body)
                return 200, {"candidates": [{"content": {"parts": [{"text": "ANSWER: 4"}]},
                                             "logprobsResult": {"chosenCandidates": [{"logProbability": -0.1}, {"logProbability": -2.0}]}}],
                             "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3}}
            r = GeminiCaller("m", {"input": 1.0, "output": 1.0}, post=post, key_env="AMP_TEST_KEY").complete("R", "q")
            self.assertTrue(seen["generationConfig"]["responseLogprobs"])
            self.assertEqual(r.logprobs, [-0.1, -2.0])
            self.assertEqual(r.usage["input"], 10)
        finally:
            del os.environ["AMP_TEST_KEY"]


if __name__ == "__main__":
    unittest.main()
