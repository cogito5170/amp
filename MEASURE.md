# MEASURE — P1a 측정 장치 (CMD-AMP1 rev 6 · CMD-WA1)

AMP.md §10 P1a: 신호 다섯이 **단계 오류를 예측하는지** AUROC(95% 신뢰구간)로 잰다. 증폭(이득 · 자원 동원)은 짓지 않는다.
표준 라이브러리만 쓴다(Python ≥ 3.10).

## 구성

| 모듈 | 하는 일 |
|---|---|
| `amp/forms.py` | `amp-signal/1` · `amp-trace/1` 꼴과 검사기. unknown 은 null(0 이 아님). 원문 칸(prompt · answer · code …)이 있으면 거부 |
| `amp/callers.py` | 갈아 끼우는 호출기: `FakeCaller` · `ClaudeCLICaller`(claude -p) · `AnthropicAPICaller`(Messages API) · `GeminiCaller`(logprobs) |
| `amp/instrument.py` | 계기 대조(5% 넘으면 무효, 추적 없으면 unverified) · 예산 지킴이(상한 앞에서 호출하지 않음) |
| `amp/tasks.py` | GSM8K test · MBPP(test 분할 11–510) 읽기, 수 · 코드 뽑기 |
| `amp/sandbox.py` | MBPP 시험을 `python -I` 하위 프로세스로 실행(모형 도구가 아님) |
| `amp/signals.py` | uncertainty(sample_disagreement) · prediction_error · novelty · contradiction · stakes |
| `amp/loop.py` | 과제 하나 = 단계 2 개(GSM8K 풀이 → 검산, MBPP 쓰기 → 고치기), 단계마다 trace 한 줄 |
| `amp/prereg.py` | 사전 등록 생성기(같은 인자 → 같은 바이트) |
| `amp/analyze.py` | AUROC(Mann–Whitney, 동점 0.5) · 과제 군집 부트스트랩 CI · not_estimable · 신호 비용 비중 |
| `amp/measure.py` | 입구: pilot → calibration → (검정력 규칙) → eval(E_min 정지 규칙) → trace · summary · analysis |

## 사전 등록

`prereg/p1a.json` (sha256 `19b045c08582d27d136305bf3cd2a40b200cabde67aa6a7e921ea58c601c3280`) — 다시 만들기:

```sh
python -m amp.prereg --data-dir <데이터> --out prereg/p1a.json --note "v1: sizes are provisional until the pilot (10 tasks per suite) measures tokens per call and whether samples disagree; see revision_rule"
```

- 데이터: GSM8K test `gsm8k_test.jsonl`(sha256 `3730d312…9d14`) · MBPP `mbpp.jsonl`(sha256 `ccf64cea…a92a9f`). 저장소에 넣지 않는다.
- 시드 20261003 · n=5 · E_min=40 · 부족하면 `harder_subset` · 묶음마다 pilot 10 · calibration 40 · eval 최대 200.
- pilot 은 호출당 토큰과 표본 갈림만 잰다. 그 값으로 n · max_eval 을 바꾸면 **새 파일 · 새 sha** 다(분할 시드는 그대로). calibration · eval 호출 전에만 바꿀 수 있다.

## 돌리기

```sh
python -m amp.measure --prereg prereg/p1a.json --data-dir <데이터> --caller fake-oracle --out runs/x --cap 7 --initial-estimate 0
python -m amp.measure ... --phase pilot      # pilot 분할만
```

`--caller`: `fake` · `fake-oracle`(시뮬레이션, 정답을 앎) · `claude-cli` · `anthropic-api` · `gemini-api`.
실제 호출기 셋은 **baseline 의 다음 지시 전에는 쓰지 않는다**(rev 6 (3)). 실패 · 사용량 한도면 그 자리에서 멈추고 `summary.stopped` 에 까닭을 남긴다.

## 시험

```sh
python -m unittest discover -s tests -t .
```

T1 꼴 · T2 자식 환경 · T3 is_error 멈춤 · T4 계기 대조 · T5 예산 · T6 샌드박스 · T7 사전 등록 결정성 · T8 AUROC · T9 끝까지(가짜 · 시뮬레이션).
