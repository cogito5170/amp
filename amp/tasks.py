"""과제 묶음: GSM8K test · MBPP. 데이터는 저장소에 넣지 않고 경로로 받는다. 원천 sha256 은 사전 등록에 적힌다."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re


@dataclasses.dataclass(frozen=True)
class Task:
    suite: str          # "gsm8k" | "mbpp"
    task_id: str
    text: str           # 문제 문장 (메모리에서만)
    gold: str           # GSM8K: 정답 수(정규화) · MBPP: 쓰지 않음
    tests: tuple = ()   # MBPP: assert 문들
    setup: str = ""     # MBPP: test_setup_code
    difficulty: int = 0 # 어려운 부분집합 규칙의 값: GSM8K 정답 풀이 줄 수 · MBPP 참조 코드 줄 수
    ref: str = ""       # MBPP 참조 코드 — 측정에는 쓰지 않는다(시뮬레이션 가짜 호출기만 쓴다)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def norm_number(s: str) -> str | None:
    """'1,234.50' → '1234.5', '-3' → '-3'. 수가 아니면 None."""
    s = s.strip().replace(",", "").replace("$", "")
    try:
        x = float(s)
    except ValueError:
        return None
    if x == int(x):
        return str(int(x))
    return repr(round(x, 6)).rstrip("0").rstrip(".")


def extract_number(answer: str) -> str | None:
    """모형 답에서 최종 수를 뽑는다: 'ANSWER: <수>' 줄이 있으면 그것, 없으면 마지막 수."""
    m = re.search(r"ANSWER\s*[:=]\s*\$?\s*(" + _NUM.pattern + ")", answer, re.IGNORECASE)
    if m:
        return norm_number(m.group(1))
    nums = _NUM.findall(answer)
    return norm_number(nums[-1]) if nums else None


def load_gsm8k(path: str) -> list[Task]:
    out = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            r = json.loads(line)
            sol, _, gold = r["answer"].rpartition("####")
            out.append(Task("gsm8k", f"gsm8k-{i:04d}", r["question"], norm_number(gold) or gold.strip(),
                            difficulty=len([ln for ln in sol.strip().splitlines() if ln.strip()])))
    return out


def load_mbpp(path: str, lo: int = 11, hi: int = 510) -> list[Task]:
    """공식 test 분할은 task_id 11–510."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if lo <= int(r["task_id"]) <= hi:
                code_lines = [ln for ln in r["code"].splitlines() if ln.strip()]
                out.append(Task("mbpp", f"mbpp-{int(r['task_id']):03d}", r["text"], "", tuple(r["test_list"]),
                                r.get("test_setup_code") or "", difficulty=len(code_lines), ref=r["code"]))
    return out


_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_code(answer: str) -> str:
    """첫 ```python 펜스의 내용. 펜스가 없으면 답 전체."""
    m = _FENCE.search(answer)
    return (m.group(1) if m else answer).strip() + "\n"
