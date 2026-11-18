# 실측 증거 묶음 (2026-11-11, 개발 PC)

기획서 9·13쪽 숫자의 원자료입니다. 모델: Anthropic claude-opus-5-5(개발자 키, 센터 키 아님). 지시문: narrate-v2 · notice-v2 · judge-v1. 입력 기준일은 시연 기준일 2026-11-13으로 고정. 키·개인정보는 들어 있지 않습니다(`scripts/check_secrets.py` 통과).

| 파일 | 내용 | 만든 방법 |
|---|---|---|
| `live_counsel_P1~P5.json` | 시연 농가 5건 상담 설명 실호출: 호출별 목적·구획·시도·입력/출력 토큰, 검수 로그(규칙 코드·판정 결과), 소요, 지문 | `scripts/record_replay.py`의 `demo_fact_sheet` → `app.agents.counsel.narrate`를 실제 클라이언트로 1회씩 |
| `live_counsel_B02/B06/B12.json` | 지시문 수정에 쓰지 않은 골든 입력 3건(`tests/golden/cases`) 같은 방식 | 골든 프로필 → `build_fact_sheet` → `narrate` |
| `live_notice_N1.json`, `live_notice_N7.json` | 공고 에이전트 실호출: 도구 호출 순서, 결정, 초안 칸, 직원 질문, 토큰 | `app.agents.notice.run_notice` (N1 `data/replay/N1.txt`, N7 `tests/fixtures/notices/N7.txt`) |
| `judge_inject.json` | 판정 모델 주입 시험 11문장(틀린 8·맞는 3)의 규칙 결과와 판정 답 | P4 사실표에 문장을 넣고 `check_rules` → `reviewer._judge` |
| `compare_official_hits.md` | 2025-26 시즌 반월별 가격안정관리제 판정 vs 공식 발동 횟수 | `python -X utf8 scripts/compare_official_hits.py` (동봉 저장본, 키 불필요) |
| `tests_nokey.txt` | 키 없는 PC 조건(.env 없음)의 자동 시험 마지막 줄 | `python -X utf8 -m pytest -q tests` |

재현: 키가 있으면 `scripts/record_replay.py --live`로 같은 형식의 녹화를 다시 만들 수 있습니다(설명 문장은 비결정적이라 글자까지 같지는 않고, 숫자·지문은 같습니다). 키가 없으면 `compare_official_hits.py`와 자동 시험만 재현됩니다.
