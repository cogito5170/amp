```ga
{"schema": "directive/1", "id": "CMD-WA1", "rev": 1, "to": "W1",
 "goal": "P1a 측정 장치를 amp 저장소에 짓는다: amp-signal/1 · amp-trace/1 꼴과 검사기, 갈아 끼울 수 있는 호출기(가짜 · claude -p 고정 깃발 · Messages API · Gemini API; 계기 대조 · 오류 멈춤 · 예산 지킴이 포함), MBPP 실행 샌드박스, 사전 등록 생성기, 측정 고리, AUROC 분석기 — 모두 가짜 호출로 시험한다",
 "why": "baseline CMD-AMP1 rev 6 의 done_when 과 AMP.md §11 · R12. 수동 Runner(강등 까닭: BD-169 분류기 거부, BD-170 사용자 지시 '병렬로 진행해라') — 허브 AMP 가 수동 Runner 로 이 턴을 한다. rlo 가드는 걸 자리가 없다(허브 세션에는 걸지 않음, METHOD §4c 7). 측정 전에 장치와 사전 등록을 고정해야 AUROC 가 사후 선택이 아니다",
 "scope": "amp 저장소의 amp/ · tests/ · prereg/ 만. PREP.md · README.md 는 허브(AMP) 소유라 고치지 않는다. Python 3.10+ 표준 라이브러리만. 실제 claude 호출 · 네트워크 금지(시험은 가짜 호출기만). 비밀값 · 프롬프트 원문 · 모형 답 원문을 trace 에 남기지 않는다(수와 라벨만). ~/.claude 를 건드리지 않는다",
 "done_when": "amp-test 로 전체 시험이 통과하고 그 수를 보고한다. 아래 본문의 시험 목록 T1–T9 가 각각 하나 이상의 시험으로 있다. 측정 고리가 가짜 호출기로 두 묶음을 끝까지 돌아 trace 와 분석 결과 JSON 을 낸다",
 "budget": {"runs": 1}}
```
## CMD-WA1 — P1a 측정 장치 (측정은 하지 않는다)

**왜.** 허브 AMP 는 baseline 의 CMD-AMP1 rev 6 을 받았다. 표본 n=5, E_min=40(rev 4). 신호 다섯(`uncertainty` · `prediction_error` · `novelty` · `contradiction` · `stakes`)이 단계 오류를 예측하는지 AUROC 로 잰다. 측정 호출은 허브가 나중에 돌린다. 이 지시는 **장치만** 짓는다. 명세 요지는 이 저장소의 `PREP.md` 에 있다.

**데이터(읽기만, 저장소에 넣지 않는다).** 경로는 인자로 받는다.
- GSM8K test: `/tmp/claude-0/-home-user/848b9e67-af02-5fb3-8bd9-7016023c738f/scratchpad/data/gsm8k_test.jsonl` (1319 줄, sha256 `3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14`). 정답은 `answer` 의 `#### ` 뒤 수다.
- MBPP: `/tmp/claude-0/-home-user/848b9e67-af02-5fb3-8bd9-7016023c738f/scratchpad/data/mbpp.jsonl` (974 줄, sha256 `ccf64ceae9c5403bf50a044cb6d505bfd2a2963ee58338ba268fd65beab92a9f`). 칸은 `task_id` · `text` · `test_list`(assert 3 개) · `test_setup_code`. 공식 test 분할은 task_id 11–510 이다.

**지을 것** (모듈 이름 · 나누는 법은 네가 정한다)
1. **꼴.** `amp-signal/1`: 신호 이름 · 값([0,1] 또는 null) · 유효성(`valid` · `stale` · `unknown`) · 원천(예 `sample_disagreement`) · 잰 비용(토큰 · 초). `amp-trace/1`: 한 단계 한 줄(JSONL) — 묶음 · 과제 id · 단계 번호 · 신호 묶음 · 라벨(단계 오류 0/1/null) · 호출 수 · 토큰(입력 · 출력 · 캐시 읽기 · 캐시 쓰기) · 비용 · 지연 · 무효 여부와 까닭. 검사기는 틀린 꼴을 거부하고, **원문 문자열 칸(프롬프트 · 답 · 코드)이 있으면 거부**한다. `unknown` 은 값 null 이고 0 이 아니다.
2. **고정 깃발 호출기.** 호출 하나 = 하위 프로세스 하나. 깃발은 허브가 정했고 모든 조건에 같으며, 사전 등록에 그대로 적힌다. 도구는 끈다(코드 실행은 고리의 샌드박스가 한다). 시스템 프롬프트는 과제 역할 한 장으로 바꾼다(호출마다 같은 머리 · 같은 비용). argv:
   `claude -p --output-format json --model claude-haiku-4-5-20251001 --tools "" --system-prompt <역할 한 장> --strict-mcp-config --session-id <새 uuid4>` (사용자 프롬프트는 stdin).
   - 자식 환경: 부모 환경을 복사하되 `CLAUDE_CODE_SESSION_ID` 를 **지운다**(자식은 부모 세션과 다른 새 세션이어야 하고, 계기 대조가 그 세션의 기록을 찾아야 한다). `CLAUDE_CONFIG_DIR` 은 호출기 인자로 받은 전용 디렉터리로 둔다.
   - 결과 JSON 에서 `is_error` 가 참이거나 `subtype` 이 성공이 아니면 **예외를 던져 고리 전체를 멈춘다**. 실패한 호출은 통과로 세지 않는다.
   - 결과 JSON 의 `usage`(input · output · cache_read · cache_creation)와 `total_cost_usd` 를 돌려준다.
   - **계기 대조:** `CLAUDE_CONFIG_DIR/projects/**/<session-id>.jsonl` 의 assistant 메시지 usage 합을 결과 JSON usage 와 비교한다. 상대 차가 5% 를 넘으면 그 호출을 무효로 표시한다. 파일이 없으면 `unverified` 로 표시한다(통과 아님). 최대 차를 실행 요약에 남긴다.
   - **예산 지킴이:** 누적 비용 + 다음 호출 추정 비용이 상한을 넘으면 호출하지 않고 멈춘다. 상한은 인자다.
3. **MBPP 실행 샌드박스.** 후보 코드 + `test_setup_code` + assert 를 임시 디렉터리에서 `python -I` 하위 프로세스로 돌린다. 시간 제한을 둔다. 결과는 통과 · 실패 · 시간 초과 · 예외 라벨만 남긴다. 모형 도구가 아니라 고리가 돌린다(`--tools ""` 유지).
4. **고리(단계 정의).** 표본 수 n 은 인자다.
   - GSM8K, 단계 2 개. 단계 1 = 풀이(n 표본, 최빈 수 = 단계 답). 단계 2 = 검산(질문 + 단계 1 답을 주고 다시 확인한 최종 수, n 표본). 단계 오류 = 그 단계 최빈 답 ≠ 정답.
   - MBPP, 단계 2 개. 단계 1 = 코드 쓰기. 프롬프트에는 `text` 와 **첫 assert 하나만** 보인다(n 표본, 첫 표본을 단계 답으로). 단계 2 = 고치기. 단계 1 코드와 보인 assert 의 실행 결과를 주고 고친 코드를 받는다. 단계 오류 = 그 단계 코드가 **숨긴 assert 둘** 중 하나라도 실패.
   - 답 · 코드 원문은 메모리에서만 쓰고 trace 에는 남기지 않는다.
5. **신호.**
   - `uncertainty`: 원천 `sample_disagreement` = 1 − (최빈 답 수 / n). MBPP 는 표본마다 보인 assert 의 실행 결과 라벨로 센다. n=1 이면 unknown.
   - `prediction_error`: MBPP 는 보인 assert 실패(1/0). GSM8K 는 답에서 수를 뽑지 못한 표본 비율. 둘 다 원천을 적는다.
   - `novelty`: 과제 문장의 문자 3-gram 집합과 **보정 분할** 문장들의 최대 자카드 유사도 s 에 대해 1 − s. 모형 호출 없음.
   - `contradiction`: 단계 2 에서 단계 2 답 ≠ 단계 1 답(GSM8K), 단계 2 코드의 보인 assert 결과 ≠ 단계 1 결과(MBPP). 단계 1 은 unknown.
   - `stakes`: 모든 과제 `local` 고정 → 값 0.5, 유효성 valid. 분석기가 분산 없음을 잡는다.
6. **사전 등록 생성기.** 인자(시드 · 묶음별 보정/평가 크기 · n · E_min · 못 맞출 때의 규칙 `harder_subset` 또는 `underpowered` · 어려운 부분집합의 규칙)를 받아 `prereg/` 아래 JSON 을 쓴다. 넣을 것: 원천 sha256, 고른 과제 id 목록(보정 · 평가), 호출 argv 와 역할 프롬프트 sha256, 신호 정의 판, 분석 방법. 같은 인자면 같은 바이트를 낸다. **허브가 크기를 정한 뒤 고정한다. 너는 생성기와 시험만 짓고 실제 prereg 파일은 만들지 않는다.**
7. **분석기.** 평가 분할만 쓴다. 신호마다 다음을 낸다.
   - AUROC(Mann–Whitney, 동점은 0.5)
   - 95% 신뢰구간: 과제 단위 군집 부트스트랩, 고정 시드, 2000 회
   - 쓴 단계 수와 unknown 으로 뺀 수
   - 양성(오류) 수가 E_min 에 못 미치거나 값의 분산이 없으면 `not_estimable` 과 까닭
   - 신호를 재는 데 든 비용의 비중(표본 n−1 개의 추가 호출 비용 / 전체)

**시험 목록(각각 하나 이상)**
- T1 꼴 정상 · 틀린 예, 원문 칸 거부
- T2 자식 환경에 `CLAUDE_CODE_SESSION_ID` 가 없다
- T3 `is_error` → 고리가 멈추고 실패로 센다
- T4 계기 대조: 같음 · 5% 초과 무효 · 파일 없음 unverified
- T5 예산 지킴이가 상한 앞에서 호출하지 않는다
- T6 MBPP 샌드박스: 통과 · 실패 · 시간 초과
- T7 사전 등록 생성기: 같은 인자 → 같은 바이트
- T8 AUROC: 알려진 값(완전 분리 1.0 · 무작위 근처 0.5 · 동점), not_estimable
- T9 가짜 호출기로 두 묶음 각 몇 과제를 끝까지 돌려 trace · 분석 JSON 이 나온다

**순서.** 없음. 다 못 하면 한 것과 못 한 것을 갈라 보고한다. 막히면 멈추고 묻는다. 그것도 결과다.
