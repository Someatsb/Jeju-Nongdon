# 설치 리허설에서 나온 문제 (Task 33)

형식: 증상 → 원인 → 고침 → 다시 돌린 결과.

## 1. run_replay.bat / notice.bat이 동봉 파이썬을 쓰지 않음 (설치 결함, 고침)
- 증상: 리허설 폴더에서 `run_replay.bat`을 돌리자 서버 트레이스백에 `C:\Python\Lib\...`(이 PC의 시스템 파이썬)이 찍힘. 파이썬이 없는 깨끗한 PC라면 "python은 내부 또는 외부 명령이 아닙니다"로 멈출 일.
- 원인: 두 파일만 `python -X utf8 ...`을 직접 불렀다. 다른 bat(run, check_install, data, keys, tables, run_tests)은 `runtime\python\python.exe`를 고르는 `PY` 변수를 썼다.
- 고침: `run_replay.bat`, `notice.bat`에 같은 `PY` 선택 두 줄을 넣고 `"%PY%" -X utf8 ...`로 바꿈. `tests/test_notice_cli.py`의 bat 검사도 새 모양에 맞춤.
- 다시 돌린 결과: zip 다시 만들어 새 폴더에 풀고 `run_replay.bat`, `notice.bat --replay N1` 통과 (서버가 `runtime\python`으로 뜸).

## 2. 한글·공백 경로에서 상대 경로로 bat을 부르면 못 찾음 (이 리허설 도구의 문제, 제품 결함 아님)
- 증상: 시험 도구 bat에서 `cd /d "<한글 공백 경로>"` 뒤 `call check_install.bat`이 "인식되지 않는다"로 실패(`dir`에는 보임).
- 원인: 이 PC에서 cmd가 코드 페이지 전환 전 한글 현재 폴더의 상대 이름 조회를 못 하는 것으로 보임(절대 경로 `call "%RD%\check_install.bat"`는 성공). 제품 bat은 모두 첫 줄에 `cd /d "%~dp0"`를 쓰고 이후 `%~dp0` 절대 경로만 쓰므로 영향 없음. 더블클릭 실행은 영향 없음.
- 고침: 시험 도구가 절대 경로로 부르게 함. 제품 쪽 변경 없음.
- 결과: `check_install.bat` 오류 0건.

## 3. 루프백 소켓 불규칙 실패, WinError 10014 (환경 문제, 설치 결함 아님)
- 증상: `run.bat`/`run_replay.bat`이 "켜는 중 소켓 오류가 나서 다시 시도합니다"를 찍으며 8765 -> 8766 -> ... 으로 이동. 한 번은 8765~8772를 모두 소진해 서버가 안 뜸. 시험용 HTTP 클라이언트도 가끔 10014.
- 원인: 이 PC의 소켓 가로채기(메모리 `windows-loopback-flake`). 앱의 `app/launch.py` 재시도·포트 이동 동작은 설계대로 작동.
- 처리: 다시 실행(잠깐 쉬고). 시험 클라이언트에는 10014 재시도를 넣음. 코드 변경 없음.
- 결과: 재시도로 8765/8766에서 정상 기동 (5~7초).

## 4. check_install.bat은 끝에 `pause` (참고)
- 사람이 더블클릭하는 용도라 맞다. 자동 시험에서는 입력이 닫혀 있으면 곧바로 지나간다. 변경 없음.

## 5. check_install 주의 2건 (설치 결함 아님)
- 지원제도 표 검사: 오류 0, 경고 3건(interventions.csv 근거 주소 없음). 표 담당(lane G)에게 알림.
- AI 키 없음: 설계상 정상(키 없이 계산·종이 가능).

## 6. 제출 zip에 남은 일 (Task 37로 넘김, 일부는 2차에서 해결)
- (정정) pytest는 `runtime\site-packages`에 이미 들어 있었다(requirements.txt의 시험 칸). 2차 리허설에서 실제로 돌렸다(7번).
- 재생 녹화(`data/replay`)와 동봉 표·스냅샷 사이 input_hash 불일치는 나오지 않았다 (P1~P5, N1 모두 재생됨).
- zip 풀기에 약 31초(파워셸 Expand-Archive, 2800여 파일). 탐색기로 풀면 더 빠를 수 있음.

## 7. `run_tests.bat --golden`이 pytest 오류로 끝남 (스크립트 결함, 고침)
- 증상: 동봉 파이썬에서 `run_tests.bat --golden` -> "unrecognized arguments: --golden", "golden 0/12". `scripts/run_tests_report.py`에 `\R` 잘못된 이스케이프 경고도 있었다.
- 원인: `--golden`을 그대로 pytest에 넘겼다(구현 없음). 설명 글의 역슬래시.
- 고침: `--golden`이면 `tests/golden/test_golden.py`만 돌리고 "골든 N/12 통과" 한 줄을 보이며 REPORT.txt는 덮지 않는다. 역슬래시를 `/`로.
- 결과: 동작함. 현재 값은 "골든 1/12 통과" (11건이 Task 34 대기 XFAIL). 심사 T1 기준 12/12는 Task 34가 끝나야 한다.

## 8. 시스템 파이썬 조용한 대체 (재발 방지, 고침)
- 모든 bat이 `runtime\python\python.exe`가 없으면 안내 한 줄을 먼저 보이고 시스템 python으로 간다. `PYTHONUTF8=1`을 설정해 하위 프로세스도 UTF-8. 2차 리허설은 PATH에서 python을 뺀 셸에서 수행(통과).
- `build_runtime.py` 스모크에 pytest 등 시험 부품을 추가, requirements.txt 시험 칸에 pytest 의존(iniconfig, packaging, pluggy, pygments)을 버전 고정으로 명시.

## 9. 알려진 흔들림
- `tests/ui`의 ProactorEventLoop ResourceWarning ERROR(0~11건, 실행마다 다름)는 수정 전 HEAD에서도 같다(`-W error` 전체 실행). 환경 흔들림.
