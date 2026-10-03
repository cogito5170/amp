"""꼴 `amp-signal/1` · `amp-trace/1` 과 검사기 (AMP.md §3 · §7).

- 신호 값은 [0,1] 또는 None. None 이면 유효성은 반드시 `unknown` 이다 — unknown 은 0 이 아니다.
- trace 에는 수와 라벨만 남긴다. 프롬프트 · 답 · 코드 원문 칸이 있으면 거부한다.
"""
from __future__ import annotations

SIGNAL_SCHEMA = "amp-signal/1"
TRACE_SCHEMA = "amp-trace/1"
SIGNAL_NAMES = ("uncertainty", "prediction_error", "novelty", "contradiction", "stakes")
VALIDITY = ("valid", "stale", "unknown")
# 원문을 담을 수 있는 칸 이름. trace 어디에든 있으면 거부한다(§7 "원문을 남기지 않는다").
RAW_TEXT_KEYS = frozenset({"prompt", "system", "answer", "answers", "code", "text", "completion", "response",
                           "content", "question", "solution", "raw", "message", "messages"})
TRACE_KEYS = {"schema", "suite", "task_id", "split", "step", "signals", "label", "calls", "tokens", "cost_usd",
              "latency_s", "invalid", "invalid_reason", "instrument"}
TOKEN_KEYS = ("input", "output", "cache_read", "cache_write")


class FormError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def signal(name: str, value, validity: str, source: str, cost_tokens: int = 0, cost_s: float = 0.0) -> dict:
    """amp-signal/1 하나를 만들고 검사한다."""
    s = {"schema": SIGNAL_SCHEMA, "name": name, "value": value, "validity": validity, "source": source,
         "cost": {"tokens": cost_tokens, "seconds": round(cost_s, 6)}}
    check_signal(s)
    return s


def unknown(name: str, source: str) -> dict:
    return signal(name, None, "unknown", source)


def signal_problems(s, path="signal") -> list[str]:
    p = []
    if not isinstance(s, dict):
        return [f"{path}: not an object"]
    if s.get("schema") != SIGNAL_SCHEMA:
        p.append(f"{path}.schema: must be {SIGNAL_SCHEMA}")
    if s.get("name") not in SIGNAL_NAMES:
        p.append(f"{path}.name: unknown signal {s.get('name')!r}")
    v, val = s.get("value"), s.get("validity")
    if val not in VALIDITY:
        p.append(f"{path}.validity: must be one of {VALIDITY}")
    if v is None:
        if val != "unknown":
            p.append(f"{path}: value null needs validity unknown")
    elif not _num(v) or not 0.0 <= v <= 1.0:
        p.append(f"{path}.value: must be in [0,1] or null")
    elif val == "unknown":
        p.append(f"{path}: validity unknown needs value null")
    if not isinstance(s.get("source"), str) or not s.get("source"):
        p.append(f"{path}.source: required")
    c = s.get("cost")
    if not isinstance(c, dict) or not _num(c.get("tokens")) or not _num(c.get("seconds")):
        p.append(f"{path}.cost: needs tokens and seconds")
    extra = set(s) - {"schema", "name", "value", "validity", "source", "cost"}
    if extra:
        p.append(f"{path}: unknown keys {sorted(extra)}")
    return p


def check_signal(s) -> None:
    p = signal_problems(s)
    if p:
        raise FormError(p)


def _raw_keys(obj, path="") -> list[str]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in RAW_TEXT_KEYS:
                out.append(f"{path}.{k}" if path else k)
            out += _raw_keys(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _raw_keys(v, f"{path}[{i}]")
    return out


def trace_problems(t) -> list[str]:
    if not isinstance(t, dict):
        return ["trace: not an object"]
    p = [f"trace.{k}: raw text field is not allowed" for k in _raw_keys(t)]
    if t.get("schema") != TRACE_SCHEMA:
        p.append(f"trace.schema: must be {TRACE_SCHEMA}")
    for k in ("suite", "task_id", "split"):
        if not isinstance(t.get(k), str) or not t.get(k):
            p.append(f"trace.{k}: required string")
    if not isinstance(t.get("step"), int) or isinstance(t.get("step"), bool) or t["step"] < 1:
        p.append("trace.step: integer >= 1")
    sigs = t.get("signals")
    if not isinstance(sigs, dict) or set(sigs) != set(SIGNAL_NAMES):
        p.append(f"trace.signals: must have exactly {SIGNAL_NAMES}")
    else:
        for n, s in sigs.items():
            p += signal_problems(s, f"trace.signals.{n}")
            if isinstance(s, dict) and s.get("name") != n:
                p.append(f"trace.signals.{n}: name mismatch")
    if t.get("label") not in (0, 1, None) or isinstance(t.get("label"), bool):
        p.append("trace.label: 0, 1 or null")
    if not isinstance(t.get("calls"), int) or t["calls"] < 0:
        p.append("trace.calls: integer >= 0")
    tok = t.get("tokens")
    if not isinstance(tok, dict) or set(tok) != set(TOKEN_KEYS) or not all(_num(tok[k]) for k in TOKEN_KEYS):
        p.append(f"trace.tokens: needs {TOKEN_KEYS}")
    for k in ("cost_usd", "latency_s"):
        if not _num(t.get(k)) or t[k] < 0:
            p.append(f"trace.{k}: number >= 0")
    if not isinstance(t.get("invalid"), bool):
        p.append("trace.invalid: bool")
    if t.get("invalid") and not t.get("invalid_reason"):
        p.append("trace.invalid_reason: required when invalid")
    if "instrument" in t and t["instrument"] not in ("verified", "unverified", "mismatch", "n/a"):
        p.append("trace.instrument: verified | unverified | mismatch | n/a")
    extra = set(t) - TRACE_KEYS
    if extra:
        p.append(f"trace: unknown keys {sorted(extra)}")
    return p


def check_trace(t) -> None:
    p = trace_problems(t)
    if p:
        raise FormError(p)
