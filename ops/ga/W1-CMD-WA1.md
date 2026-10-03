```ga
{"schema": "report/1", "from": "W1", "handled": [{"id": "CMD-WA1", "rev_seen": 1, "status": "done"}], "commits": [{"repo": "amp", "branch": "w1-p1a-harness", "sha": "d4f656f2f81d0589aad78fc96dbdb54bbb4c7af7"}]}
```
## Task
CMD-WA1: P1a 측정 장치. 수동 Runner로 했다. 강등 까닭은 BD-169(분류기 거부)와 BD-170(사용자 지시 '병렬로 진행해라')이고, 턴은 허브 AMP가 직접 했다. rlo 가드는 걸 자리가 없다.

## Execution
amp/ 패키지 10 모듈, 시험 5 파일(31 개), `prereg/p1a.json`, `MEASURE.md`, 시뮬레이션 실행 요약을 만들었다.

## Result
- 꼴 `amp-signal/1` · `amp-trace/1`. 원문 칸은 거부한다. unknown 은 null 로 둔다.
- 갈아 끼우는 호출기 넷: fake · claude-cli · anthropic-api · gemini-api.
  - claude-cli 의 깃발은 baseline 이 정한 그대로다. 자식 환경에서 CLAUDE_CODE_SESSION_ID 를 지운다.
  - 계기 대조는 결과 usage 와 transcript 를 견준다(5%).
  - is_error · 사용량 한도 · 예산이면 그 자리에서 멈춘다.
- 사전 등록 sha256 `19b045c08582d27d136305bf3cd2a40b200cabde67aa6a7e921ea58c601c3280`: 시드 20261003 · n=5 · E_min=40 · harder_subset · pilot 10 / calibration 40 / eval ≤200.

## Evidence
- verified: 시험 31 통과(`amp-test`). 변이 10/10 이 잡혔다: 세션 env · 예산 · 계기 문턱 · is_error · 원문 칸 · AUROC 부호 · 정지 규칙 · 사전 등록 결정성 · 시간 초과 · 오류 삼킴.
- verified: 같은 인자로 사전 등록을 두 번 만들었고 바이트가 같다(cmp).
- verified: 실제 데이터 + 사전 등록으로 가짜 호출 끝까지 두 번 돌렸다(비용 0, 모형 호출 0).
  - `fake`: 모두 틀림 → 신호 다섯 모두 not_estimable("no negatives"). 정상 동작이다.
  - `fake-oracle`(난이도로 오류를 흉내 낸 시뮬레이션): 4590 호출 · 718 단계. MBPP uncertainty AUROC 0.80 [0.75, 0.84]. GSM8K 는 p_cal 0.0125 → harder_subset 적용 → 양성 31 < 40 → underpowered 로 표시됐다.
  - 이 AUROC 값들은 모형에 대해 아무것도 말하지 않는다. 경로 확인일 뿐이다.
- partially verified: Gemini `responseLogprobs` · `logprobsResult.chosenCandidates[].logProbability` 칸 이름. 공식 python-genai types.py 로 확인했다. ai.google.dev 는 egress 에서 막혔다. 모형별 지원 여부는 확인하지 못했다.
- assumption: Haiku 캐시 가격(쓰기 1.25 · 읽기 0.10 /MTok). 입력 · 출력 1 · 5 는 참고표 값이다.

## Deviation
- Messages API · Gemini 호출기는 SDK 가 아니라 표준 라이브러리 HTTP 로 지었다(지시의 '표준 라이브러리만'). 실호출로는 검증하지 않았다.
- 신호 비용 비중이 0.80 이다(n=5 의 표본 4 개가 추가 호출). P1b 이득 설계에 큰 영향을 준다(Proposal).

## Proposal
- current: pilot(묶음마다 10 과제)으로 실제 호출당 토큰 · 표본 갈림을 잰다. 그 결과로 n · max_eval 을 다시 정한다(새 sha).
- future: GSM8K 는 haiku 정답률이 높으면 harder_subset 으로도 E_min 을 못 맞출 수 있다(시뮬레이션이 그 경로를 보였다). 더 어려운 묶음(예: GSM-hard 류)을 후보로 둔다.

## Request
실제 측정 경로(claude-cli · anthropic-api · gemini-api)를 정해 달라. baseline 지시다.
