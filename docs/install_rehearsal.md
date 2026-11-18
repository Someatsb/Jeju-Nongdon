# 설치 리허설 기록 (Task 33, 2026-11-08)

개발 PC(Windows 11 Home)로 깨끗한 PC를 대신했다. 증거로는 부족하며 깨끗한 PC 시험(T1)은 11-12~13에 따로 한다.
화면 녹화는 11-14 사장 PC에서 (E10). 이 PC에서는 화면 녹화·스크린샷을 만들 수 없다.

- 꾸러미: `python -X utf8 scripts/build_zip.py --g1` -> `dist/jeju-nongdon-g1-20261108.zip` (모든 파일이 최상위 폴더 `jeju-nongdon/` 하나 아래에 있다. 풀면 `<풀 곳>\jeju-nongdon\`이 생기고 bat은 그 안에서 돌린다), 31.4 MB (MANIFEST 포함 3169개 파일, 경고선 300 MB / 한도 500 MB 가정). 비밀 검사 `OK 0 hits`, 추적되는 `.env` 없음.
- 푼 곳: `...\scratchpad\리허설 설치\` (한글 + 공백). 풀고 나서 MANIFEST.sha256 전체 대조: 불일치 0.

## 순서와 시간

| # | 단계 | 결과 | 시간 |
|---|---|---|---|
| 1 | zip 만들기 | 31.4 MB | 약 20초 |
| 2 | 풀기(Expand-Archive) | 성공 | 31초 |
| 3 | `check_install.bat` | 오류 0건, 주의 2건 (표 경고 3건, AI 키 없음) | 3.1초 |
| 4 | `run.bat --asof 2026-11-13 --nobrowser` | 8765 기동, /health `demo:true` | 5~7초 |
| 5 | P1~P5 인쇄(HTTP: 입력 -> 확인 -> 인쇄) | 5장 모두 막힘 없음(사전 점검 통과) | 5장 합계 0.5초 |
| 6 | 서버 끄기 | 프로세스 정리됨 | 즉시 |
| 7 | `run_replay.bat` | 8765/8766 기동, 모든 화면에 "재생 — 실제 LLM 호출 아님" 띠 | 2~5초 |
| 8 | 재생 P4 미리보기 | 검수 표에 주입·반려·통과 모두 표시 (P1~P3, P5는 통과) | 0.1초 |
| 9 | `notice.bat --replay N1` | `DRAFT_READY ...\data\inbox\N1-...\report.html`, 맨 위 재생 띠 | 1.0초 |
| 10 | `scripts\make_samples.py`(동봉 파이썬) | P1~P5 print.pdf 5개 저장 | 9.1초 |

run.bat 더블클릭부터 5장째 인쇄까지의 기계 시간은 10초 안팎(목표 3분). 사람이 화면을 누르는 시간은 포함하지 않는다.

## 고친 것
`docs/install_issues.md` 참고. 설치 결함은 1건(run_replay.bat, notice.bat이 동봉 파이썬을 안 씀) 고침. 나머지는 이 PC의 환경 문제(루프백 10014)와 시험 도구 문제.

## 남은 일
- 깨끗한 PC에서 T1 전 과정과 화면 녹화(E10): 11-14 사장 PC에서.
- `run_tests.bat --golden`(골든 12/12)은 zip에 pytest가 없어 이 리허설에서 못 돌림: Task 37에서 정함.
- 브라우저 자동 열기(`start msedge`)와 프린터 인쇄 대화상자는 이 리허설에서 사람이 보지 않음(--nobrowser).

## 2차 리허설 (수정 후, 시스템 파이썬 없는 PATH)

새 폴더 `...\scratchpad\리허설 설치3\jeju-nongdon\` (한글+공백). 셸 PATH를 `C:\Windows\System32;C:\Windows;...PowerShell`만 남겨 `python`이 없음을 확인(`where python` 없음)한 뒤 진행. zip은 깨끗한 git 상태에서(`--allow-dirty` 없이) 만들었다. 31.4 MB, 3169개.

| 단계 | 결과 | 시간 |
|---|---|---|
| 풀기 | MANIFEST 대조 불일치 0 | 30초 |
| `check_install.bat` | 오류 0건, 주의 2건(표 경고 3건, AI 키 없음) | 3.1초 |
| `run.bat --asof 2026-11-13` + P1~P5 | 8765 기동, 5장 모두 통과 | 기동 5초대, 인쇄 합계 0.5초 |
| `run_replay.bat` | 띠 표시, P4 주입/반려/통과 패널, 첫 화면 띠 | 기동 2~5초 |
| `notice.bat --replay N1` | DRAFT_READY, report.html | 1.1초 |
| `make_samples.py` | PDF 5개 | 7.5초 |
| `run_tests.bat --golden` (동봉 pytest) | 실행됨. 골든 1/12 통과(나머지 11건은 Task 34 몫의 XFAIL) | 2~5초 |
| 내장 파이썬 이름을 바꾼 뒤 `keys.bat list` | "내장 파이썬이 없어 시스템 python을 씁니다 — runtime 폴더를 확인하세요" 안내가 먼저 나옴 | 즉시 |

시스템 파이썬 없이도 위 전부가 동봉 파이썬으로 돌았다.
