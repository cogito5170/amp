# PREP — CMD-AMP1(P1a) 준비 (비용 0, 사전 등록 전)

> 운영자(AMP 세션)가 쓴 준비 문서다. **아직 측정하지 않았다.** 과제 묶음 · 분할은 여기서 **고정하지 않는다** —
> 사용자가 실행 경로를 고른 뒤 작업 턴이 `prereg/` 에 고정 파일을 만들고, 그 sha 를 보고한 다음에야 측정한다.
> 명세: baseline `AMP.md`(amp-1 rev 1). 지시: baseline#14 CMD-AMP1 rev 1.

## 1. 확인한 것 (verified, 비용 0)

| 것 | 결과 |
|---|---|
| ga-SDK 통합 머리 `7cb33ec` pip 설치 | `ga-sdk 0.1.0`, `ga` 명령 있음 |
| rlo-SDK `a152e14` pip 설치 | `rlo-sdk 0.5.0` |
| 데이터 원천(GitHub raw) | GSM8K test · MBPP · HumanEval 모두 200. Hugging Face 는 프록시가 막음(403) |
| `ANTHROPIC_API_KEY` | 없음 → 경로 (a) 는 사용자가 키를 넣어야 한다 |
| 헤드리스 자식의 인증 | (assumption) ga 헤드리스 Runner 는 `ANTHROPIC_BASE_URL` 만 넘긴다. 같은 종류의 클라우드 컨테이너에서 GA10–GA12 가 이 방식으로 돌았다(ga-SDK `examples/verify/ga11_results.json`). 이 컨테이너에서는 실제 호출 전이라 확인하지 않았다 |

## 2. ga 배치 (초안)

- 허브 = 이 세션(운영자). 작업 세션 하나 `W1`(머리글자 `WA`), 통로 `mailbox:W1`.
- `isolation: "clone"` · `runner: headless, model haiku, sandbox require` · `judge: llm haiku`.
- 저장소 `amp`: 시험 `{python} -m unittest discover -s tests`. 포장하면 `package` 를 켜서 Bundle (b) 도 돈다.
- 소유표: `amp/*` → `W1`, 단 `prereg/*` 는 W1 이 처음 한 번 쓰고 운영자가 고정 확인(sha 기록) 뒤에는 바꾸지 않는다.
- 예산(R12): `budget.cost` 를 **$15 아래**로 두고 턴 · Judge · 측정을 합쳐 센다. 측정 호출은 ga 밖에서 돌므로, 측정 스크립트가 호출마다 비용을 `amp-trace/1` 에 남기고 누적이 상한에 닿으면 실행 전에 멈춘다.

## 3. 과제 묶음 후보 (정답을 기계로 확인)

| 후보 | 단계(step)의 뜻 | 단계 오류 라벨 | 장단 |
|---|---|---|---|
| **GSM8K test** | 풀이 한 번 = 단계 하나. 2 단계 고리면 풀이 → 검산 | 최종 수가 정답과 다름 | 싸다(호출당 수백 토큰). 정답 확인이 문자열 비교로 끝난다 |
| **MBPP(sanitized 아님, test 분할)** | 코드 쓰기 → 시험 실행(도구) → 고치기 | 그 단계의 코드가 시험을 통과하지 못함 | `prediction_error`(시험 실패)가 자연스럽게 생긴다. 실행 샌드박스가 필요하다 |
| HumanEval | MBPP 와 같음 | 같음 | 164 개로 작다. 오염 가능성 높음 |

권고: **GSM8K + MBPP 두 묶음.** GSM8K 는 `uncertainty`(표본 불일치) 검사에, MBPP 는 도구 단계와 `prediction_error` 검사에 맞는다.
분할: 문턱을 고르는 **보정(calibration)** 분할과 AUROC 를 내는 **평가(held-out)** 분할을 나눈다. 크기와 시드는 사전 등록 파일에 적는다.

## 4. 신호 다섯 — 원천 계획

| 신호 | 원천(`source` 칸) | 비고 |
|---|---|---|
| `uncertainty` | `sample_disagreement`(같은 단계 n 표본의 답 불일치 비율). 토큰 확률은 Anthropic Messages API 가 주지 않는 것으로 안다 — 작업 턴이 문서로 다시 확인한다 | 명세 §3 이 허락한 대체 신호(baseline#14 판정) |
| `prediction_error` | 도구 단계 결과(시험 실패 · 예외) | rlo Sensor 의 실패 뒤 상태를 읽어 쓸 수 있는지 작업 턴이 본다(고치지 않음) |
| `novelty` | 과제 문장과 보정 분할의 거리(예: 문자 n-gram 자카드) | 싸게. 모형 호출 없음 |
| `contradiction` | 앞 단계 답과 지금 단계 답이 충돌하는가(검산이 풀이와 다름) | GSM8K 2 단계 고리에서 |
| `stakes` | 과제에 고정 라벨(`read`/`local`/`external`) | P1a 과제는 모두 `local` 일 가능성이 높다 → 분산이 없으면 AUROC 를 낼 수 없다고 보고한다 |

없는 신호는 0 이 아니라 `unknown` 이다(명세 §3).

## 5. 비용 계획 (estimate, not verified)

- 측정 호출이 `claude -p` 를 거치면 CLI 시스템 프롬프트가 붙는다. `--system-prompt` 로 바꾸고 도구를 끄더라도 호출당 비용은 **첫 호출에서 재야** 한다. 그 값으로 표본 수 n 과 과제 수를 정한다.
- 상한 배분 초안: 작업 턴 ≤ $6 · Judge ≤ $1 · 측정 ≤ $7 · 여유 $1. 7 일 사용량 창이 경고 상태라는 baseline 주의에 따라 회차마다 쓴 양을 기록한다.

## 6. 작업 턴에게 줄 지시 초안 (보내지 않았다)

```ga
{"schema": "directive/1", "id": "CMD-WA1", "rev": 1, "to": "W1",
 "goal": "P1a 측정 장치: amp-signal/1 · amp-trace/1 꼴과 시험, 과제 묶음 · 분할을 고정하는 사전 등록 파일, 측정 스크립트(아직 돌리지 않음)",
 "why": "CMD-AMP1 done_when (1)(2). 측정 전에 과제와 분할을 고정해야 AUROC 가 사후 선택이 아니다",
 "scope": "amp 저장소. 표준 라이브러리 우선. 모형 호출 코드는 짓되 시험에서는 가짜 호출만 쓴다. 비밀값 · 원문 대화를 trace 에 남기지 않는다",
 "done_when": "꼴 검사기 정상 · 틀린 예 시험 통과, prereg 파일에 묶음 · 분할 · 시드 · 크기 · 원천 sha256, 측정 스크립트가 가짜 호출로 끝까지 돌고 비용 상한에서 멈추는 시험"}
```
