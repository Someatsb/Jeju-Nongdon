# 증거 2026-11-13

| 파일 | 내용 |
|---|---|
| `front_measure.md` | 앞면 넘침 추정기의 재생 미리보기 5사례 픽셀 실측과 보정(상한 41.0) |
| `live_counsel_P4_runs.md` | 실호출 P4 3회(35.8·32.0·33.7초)와 발견한 결함 두 가지, 고친 커밋 |
| `tests_nokey.txt` | 키 파일을 치운 상태의 전체 시험 마지막 줄(1694 passed · 3 skipped · 1 xfailed, 11-13) |

재현 도구: `scripts/front_measure.py`(재생, 비용 없음), `scripts/capture_replay.py`(재생 화면 캡처), `scripts/capture_live.py`(키 있는 실호출, 1회 약 $0.12). 서버를 먼저 띄우고 끝나면 내린다.
