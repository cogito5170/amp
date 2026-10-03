"""MBPP 실행 샌드박스. 모형 도구가 아니라 고리가 돌린다(측정 호출은 도구를 끈 채로 둔다).

후보 코드 + setup + assert 들을 임시 디렉터리에서 `python -I` 하위 프로세스로 돌린다. 시간 제한을 둔다.
결과는 라벨만: pass · fail · timeout · error(문법 · import 등 assert 전 실패).
격리 한계(assumption): 같은 사용자 권한의 하위 프로세스다. 네트워크 · 파일 쓰기를 OS 수준에서 막지는 않는다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

PASS, FAIL, TIMEOUT, ERROR = "pass", "fail", "timeout", "error"

_HARNESS = r'''
import sys
src = open("candidate.py", encoding="utf-8").read()
setup = open("setup.py", encoding="utf-8").read()
tests = open("tests.py", encoding="utf-8").read().split("\n#--amp-test--\n")
g = {"__name__": "__amp__"}
try:
    exec(compile(setup + "\n" + src, "candidate.py", "exec"), g)
except BaseException:
    sys.exit(3)
for t in tests:
    if not t.strip():
        continue
    try:
        exec(compile(t, "test", "exec"), g)
    except AssertionError:
        sys.exit(1)
    except BaseException:
        sys.exit(1)
sys.exit(0)
'''


def run_tests(code: str, tests, setup: str = "", timeout: float = 10.0, python: str = sys.executable) -> str:
    with tempfile.TemporaryDirectory(prefix="amp-sbx-") as d:
        for name, body in (("candidate.py", code), ("setup.py", setup or ""),
                           ("tests.py", "\n#--amp-test--\n".join(tests)), ("harness.py", _HARNESS)):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(body)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "HOME": d}
        try:
            p = subprocess.run([python, "-I", "harness.py"], cwd=d, env=env, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return TIMEOUT
        return {0: PASS, 1: FAIL, 3: ERROR}.get(p.returncode, ERROR)
