"""갈아 끼울 수 있는 모형 호출기 (CMD-AMP1 rev 6).

모든 호출기는 `complete(system, user) -> CallResult` 하나만 가진다. 측정 고리는 호출기를 모른다.
- FakeCaller          시험 · 가짜 측정용. 결정적이고 네트워크를 쓰지 않는다.
- ClaudeCLICaller     `claude -p` 헤드리스. 깃발은 baseline 이 정한 것(rev 4 (3))이고 사전 등록에 그대로 적힌다.
- AnthropicAPICaller  Messages API 직접(표준 라이브러리 HTTP). 키는 환경 변수에서 요청마다 읽고 저장하지 않는다.
- GeminiCaller        Gemini API generateContent. `responseLogprobs` 를 켜면 토큰 logprob 을 돌려받을 수 있다(문서 기준, 실호출로는 확인 안 함).

실패한 호출(오류 · 사용량 한도 · 꼴 오류)은 `CallError` 를 던진다. 고리는 그 자리에서 멈추고 통과로 세지 않는다(AMP.md §11, GA7).
실제 호출기는 이 저장소의 시험에서 부르지 않는다. 시험은 하위 프로세스 · HTTP 함수를 가짜로 끼운다.
"""
from __future__ import annotations

import dataclasses
import glob
import hashlib
import json
import os
import random
import subprocess
import time
import uuid
from typing import Callable

from .instrument import cross_check


class CallError(RuntimeError):
    """호출이 결과 없이 끝났다. kind: is_error · exit · parse · http · timeout."""

    def __init__(self, kind: str, detail: str = ""):
        self.kind = kind
        super().__init__(f"{kind}: {detail}"[:300])


@dataclasses.dataclass
class CallResult:
    text: str                                   # 메모리에서만 쓴다. trace 에 남기지 않는다
    usage: dict                                 # input · output · cache_read · cache_write (토큰)
    cost_usd: float
    latency_s: float
    session_id: str = ""
    logprobs: list | None = None                # 고른 토큰마다 logprob (주는 호출기만)
    instrument: str = "n/a"                     # verified · unverified · mismatch · n/a
    instrument_diff: float | None = None        # 결과 JSON usage 와 추적 합의 상대 차


def _usage(i=0, o=0, cr=0, cw=0) -> dict:
    return {"input": int(i), "output": int(o), "cache_read": int(cr), "cache_write": int(cw)}


# 가격(USD / 백만 토큰). claude-haiku-4-5 입력 1 · 출력 5 는 claude-api 참고표(2026-09-25 캐시) 값이다.
# 캐시 쓰기 1.25 · 읽기 0.10 은 입력 가격의 1.25 배 · 0.1 배로 둔 가정이다 — 사전 등록에 적고, 실측 전에 확인한다.
HAIKU_PRICE = {"input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.10}


def price_usd(usage: dict, price: dict) -> float:
    return sum(usage.get(k, 0) * price.get(k, 0.0) for k in ("input", "output", "cache_read", "cache_write")) / 1e6


# ------------------------------------------------------------------------------------------------ 가짜

class FakeCaller:
    """결정적 가짜 호출기. `script(system, user, k, rng) -> str | CallError` 로 답을 정한다.

    k 는 같은 (system, user) 를 몇 번째로 불렀는지(0 부터) — 표본마다 다른 답을 낼 수 있다.
    토큰은 글자 수에서 어림한다(4 글자 = 1 토큰). 비용은 `price` 로 계산한다.
    """

    kind = "fake"

    def __init__(self, script: Callable, seed: int = 0, price: dict | None = None, instrument: str = "verified"):
        self.script = script
        self.rng = random.Random(seed)
        self.price = price or HAIKU_PRICE
        self.instrument = instrument
        self.seen: dict[str, int] = {}
        self.calls = 0

    def complete(self, system: str, user: str) -> CallResult:
        key = hashlib.sha256((system + "\x00" + user).encode()).hexdigest()
        k = self.seen.get(key, 0)
        self.seen[key] = k + 1
        self.calls += 1
        out = self.script(system, user, k, self.rng)
        if isinstance(out, CallError):
            raise out
        u = _usage(i=(len(system) + len(user)) // 4 + 1, o=len(out) // 4 + 1)
        return CallResult(text=out, usage=u, cost_usd=price_usd(u, self.price), latency_s=0.0,
                          session_id=f"fake-{self.calls}", instrument=self.instrument,
                          instrument_diff=0.0 if self.instrument == "verified" else None)


# ------------------------------------------------------------------------------------------------ claude -p

def run_subprocess(argv: list[str], stdin: str, env: dict, timeout: float) -> tuple[int, str, str]:
    p = subprocess.run(argv, input=stdin, text=True, capture_output=True, env=env, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


class ClaudeCLICaller:
    """`claude -p` 한 번 = 호출 하나. 깃발은 모든 조건에 같다(호스트 설정, 사전 등록에 적힘).

    - 자식 환경: 부모 환경을 복사하되 `CLAUDE_CODE_SESSION_ID` 를 지운다. 자식은 새 세션(`--session-id`)이어야 하고,
      계기 대조는 그 세션의 기록을 찾아야 한다.
    - `CLAUDE_CONFIG_DIR` 은 측정 전용 디렉터리다. ~/.claude 를 건드리지 않는다.
    - 계기 대조: 결과 JSON 의 usage 와 `<config_dir>/projects/**/<session-id>.jsonl` 의 assistant usage 합을 견준다.
    """

    kind = "claude-cli"
    MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, config_dir: str, model: str = MODEL, executable: str = "claude", timeout: float = 300.0,
                 runner: Callable = run_subprocess, base_env: dict | None = None):
        self.config_dir = str(config_dir)
        self.model = model
        self.executable = executable
        self.timeout = timeout
        self.runner = runner
        self.base_env = base_env

    def argv(self, system: str, session_id: str) -> list[str]:
        return [self.executable, "-p", "--output-format", "json", "--model", self.model, "--tools", "",
                "--system-prompt", system, "--strict-mcp-config", "--session-id", session_id]

    def env(self) -> dict:
        env = dict(os.environ if self.base_env is None else self.base_env)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        env["CLAUDE_CONFIG_DIR"] = self.config_dir
        return env

    def complete(self, system: str, user: str) -> CallResult:
        sid = str(uuid.uuid4())
        t0 = time.monotonic()
        try:
            rc, out, _err = self.runner(self.argv(system, sid), user, self.env(), self.timeout)
        except subprocess.TimeoutExpired as e:
            raise CallError("timeout", str(e)) from None
        dt = time.monotonic() - t0
        try:
            r = json.loads(out)
        except (json.JSONDecodeError, TypeError):
            raise CallError("parse", f"rc={rc}") from None
        if r.get("is_error") or r.get("subtype") not in (None, "success"):
            raise CallError("is_error", f"subtype={r.get('subtype')}")
        if rc != 0:
            raise CallError("exit", f"rc={rc}")
        u = r.get("usage") or {}
        usage = _usage(u.get("input_tokens", 0), u.get("output_tokens", 0),
                       u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0))
        status, diff = cross_check(usage, transcript_usage(self.config_dir, r.get("session_id") or sid))
        return CallResult(text=str(r.get("result", "")), usage=usage, cost_usd=float(r.get("total_cost_usd") or 0.0),
                          latency_s=dt, session_id=r.get("session_id") or sid, instrument=status, instrument_diff=diff)


def transcript_usage(config_dir: str, session_id: str) -> dict | None:
    """세션 기록의 assistant usage 합. 같은 message.id 가 여러 줄이면 마지막 줄만 센다. 기록이 없으면 None."""
    paths = glob.glob(os.path.join(config_dir, "projects", "**", f"{session_id}.jsonl"), recursive=True)
    if not paths:
        return None
    by_msg: dict[str, dict] = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                m = e.get("message") or {}
                if e.get("type") == "assistant" and isinstance(m.get("usage"), dict):
                    by_msg[m.get("id") or f"{path}:{i}"] = m["usage"]
    tot = _usage()
    for u in by_msg.values():
        tot["input"] += u.get("input_tokens", 0)
        tot["output"] += u.get("output_tokens", 0)
        tot["cache_read"] += u.get("cache_read_input_tokens", 0)
        tot["cache_write"] += u.get("cache_creation_input_tokens", 0)
    return tot


# ------------------------------------------------------------------------------------------------ HTTP 호출기

def http_post_json(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, dict]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json", **headers},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except json.JSONDecodeError:
            return e.code, {}


class AnthropicAPICaller:
    """Messages API(`POST /v1/messages`) 직접. 토큰 logprob 은 없다. 키는 `ANTHROPIC_API_KEY` 에서 요청마다 읽는다."""

    kind = "anthropic-api"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str = "claude-haiku-4-5", max_tokens: int = 1024, temperature: float | None = 1.0,
                 price: dict | None = None, timeout: float = 120.0, post: Callable = http_post_json,
                 key_env: str = "ANTHROPIC_API_KEY"):
        self.model, self.max_tokens, self.temperature = model, max_tokens, temperature
        self.price, self.timeout, self.post, self.key_env = price or HAIKU_PRICE, timeout, post, key_env

    def complete(self, system: str, user: str) -> CallResult:
        key = os.environ.get(self.key_env)
        if not key:
            raise CallError("http", f"{self.key_env} not set")
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}]}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        t0 = time.monotonic()
        status, r = self.post(self.URL, {"x-api-key": key, "anthropic-version": "2023-06-01"}, body, self.timeout)
        dt = time.monotonic() - t0
        if status != 200 or r.get("type") == "error":
            raise CallError("is_error" if status in (429, 529) else "http", f"status={status}")
        u = r.get("usage") or {}
        usage = _usage(u.get("input_tokens", 0), u.get("output_tokens", 0),
                       u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0))
        text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
        return CallResult(text=text, usage=usage, cost_usd=price_usd(usage, self.price), latency_s=dt,
                          session_id=r.get("id", ""), instrument="n/a")


class GeminiCaller:
    """Gemini API generateContent. `logprobs=True` 면 `responseLogprobs` 를 켠다(모형에 따라 지원 여부가 다르다 — 문서로 확인할 것).

    키는 `GEMINI_API_KEY` 에서 요청마다 읽는다. 가격은 인자로 받는다(기본값 없음 — 사전 등록에 적는다).
    """

    kind = "gemini-api"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, model: str, price: dict, temperature: float | None = 1.0, max_tokens: int = 1024,
                 logprobs: bool = True, timeout: float = 120.0, post: Callable = http_post_json,
                 key_env: str = "GEMINI_API_KEY"):
        self.model, self.price, self.temperature, self.max_tokens = model, price, temperature, max_tokens
        self.logprobs, self.timeout, self.post, self.key_env = logprobs, timeout, post, key_env

    def complete(self, system: str, user: str) -> CallResult:
        key = os.environ.get(self.key_env)
        if not key:
            raise CallError("http", f"{self.key_env} not set")
        gen = {"maxOutputTokens": self.max_tokens}
        if self.temperature is not None:
            gen["temperature"] = self.temperature
        if self.logprobs:
            gen["responseLogprobs"] = True
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": gen}
        t0 = time.monotonic()
        status, r = self.post(self.URL.format(model=self.model), {"x-goog-api-key": key}, body, self.timeout)
        dt = time.monotonic() - t0
        if status != 200 or "error" in r:
            raise CallError("is_error" if status == 429 else "http", f"status={status}")
        cands = r.get("candidates") or []
        if not cands:
            raise CallError("parse", "no candidates")
        c = cands[0]
        text = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", []))
        lp = None
        chosen = (c.get("logprobsResult") or {}).get("chosenCandidates")
        if chosen:
            lp = [float(x.get("logProbability", 0.0)) for x in chosen]
        m = r.get("usageMetadata") or {}
        usage = _usage(m.get("promptTokenCount", 0), m.get("candidatesTokenCount", 0), m.get("cachedContentTokenCount", 0), 0)
        return CallResult(text=text, usage=usage, cost_usd=price_usd(usage, self.price), latency_s=dt,
                          session_id=r.get("responseId", ""), logprobs=lp, instrument="n/a")
