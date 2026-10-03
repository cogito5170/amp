"""역할 프롬프트(시스템 한 장)와 사용자 프롬프트 틀. 바뀌면 sha256 이 바뀌고 사전 등록이 깨진다."""
from __future__ import annotations

import hashlib

GSM8K_SOLVE = ("You solve grade-school math word problems. Think briefly, then give the final numeric answer "
               "on the last line exactly as: ANSWER: <number>")
GSM8K_CHECK = ("You check a proposed answer to a grade-school math word problem. Re-solve the problem independently, "
               "then give the final numeric answer on the last line exactly as: ANSWER: <number>")
MBPP_WRITE = ("You write a single self-contained Python function that satisfies the task. Reply with one ```python "
              "code block and nothing else. Do not print or read input.")
MBPP_FIX = ("You fix a Python function given the task, the current code and a test result. Reply with one ```python "
            "code block containing the full corrected code and nothing else.")

ROLES = {"gsm8k.solve": GSM8K_SOLVE, "gsm8k.check": GSM8K_CHECK, "mbpp.write": MBPP_WRITE, "mbpp.fix": MBPP_FIX}


def gsm8k_solve(question: str) -> str:
    return f"Problem:\n{question}"


def gsm8k_check(question: str, proposed: str | None) -> str:
    shown = proposed if proposed is not None else "(no answer)"
    return f"Problem:\n{question}\n\nProposed answer: {shown}"


def mbpp_write(text: str, shown_test: str) -> str:
    return f"Task:\n{text}\n\nYour code must pass this test:\n{shown_test}"


def mbpp_fix(text: str, shown_test: str, code: str, result: str) -> str:
    return f"Task:\n{text}\n\nTest:\n{shown_test}\n\nCurrent code:\n```python\n{code}```\n\nTest result: {result}"


def roles_sha256() -> dict:
    return {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sorted(ROLES.items())}
