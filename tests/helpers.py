"""시험용 합성 데이터 · 가짜 호출기. 실제 데이터 · 네트워크 · 모형을 쓰지 않는다."""
import json
import os

from amp.tasks import sha256_file


def write_synthetic(d: str, n_gsm: int = 40, n_mbpp: int = 40) -> dict:
    os.makedirs(d, exist_ok=True)
    g = os.path.join(d, "gsm8k_test.jsonl")
    with open(g, "w") as f:
        for i in range(n_gsm):
            steps = "\n".join(f"step {k}" for k in range(1 + i % 4))
            f.write(json.dumps({"question": f"Tom has {i} apples and buys {i % 7} more boxes of pears. How many? case {i}",
                                "answer": f"{steps}\n#### {7 if i % 3 else 7}"}) + "\n")
    m = os.path.join(d, "mbpp.jsonl")
    with open(m, "w") as f:
        for i in range(n_mbpp):
            tid = 11 + i
            f.write(json.dumps({"task_id": tid, "text": f"Write a function f that returns zero for any input, variant {i}.",
                                "code": "def f(*a, **k):\n" + "    x = 0\n" * (1 + i % 3) + "    return 0",
                                "test_list": ["assert f(1) == 0", "assert f(2) == 0", "assert f('a') == 0"],
                                "test_setup_code": ""}) + "\n")
    return {"gsm8k": {"file": "gsm8k_test.jsonl", "sha256": sha256_file(g)},
            "mbpp": {"file": "mbpp.jsonl", "sha256": sha256_file(m)}}
