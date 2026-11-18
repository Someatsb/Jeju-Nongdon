> 이 기록은 2026-11-08~13 시점의 것이며 지금 화면과 다를 수 있습니다.

# 관문 G1 스톱워치 기록 (Task 27)

측정일 2026-11-08 · 개발 PC(Windows 11, 보안 모듈이 localhost 소켓을 가끔 막음) · 인터넷 없이 실행 · 키 없음 · 내장 파이썬 3.12.10(`runtime\python`).
기준: 3분 이내.

## 준비(한 번만, 인터넷 필요)

| 단계 | 시간 |
|---|---|
| `python scripts\build_runtime.py` (내장 파이썬 받기 11MB·지문 대조·풀기·부품 28개 설치·확인) | 약 29초 (pip 캐시 있음) |
| 두 번째 실행(이미 된 단계 건너뜀) | 1초 안팎, 같은 결과 |

## 본 측정

| 단계 | 명령 | 걸린 시간 |
|---|---|---|
| 서버 켜기 | `.\run.bat --asof 2026-11-13 --nobrowser` → `/health` 응답까지 | 1.35초 (cmd 경유) · 직접 실행 5회 중 4회 1.0~1.3초 |
| 종이 5건 HTML | `runtime\python\python.exe -X utf8 scripts\make_samples.py --no-pdf` (P1~P5) | 0.6초 |
| 종이 5건 HTML + PDF | 같은 명령에서 `--no-pdf` 없이(Edge 화면 없는 모드) | 6.9초 (P당 약 1.2초) |

합계(켜기 + HTML 5건 + PDF 5건) 약 10초. 기준 3분보다 훨씬 빠르다.
사전 점검(preflight)은 5건 모두 빈 목록.

## 소켓 오류가 난 경우

5회 중 1회, 첫 시도에서 "켜는 중 소켓 오류가 나서 다시 시도합니다."가 찍히고 다음 포트(8766)로 켜졌다
(실행기의 재시도가 그대로 동작함). 이 경우 켜는 시간은 8765번에서 끝난 경우보다 몇 초 길다.
`cmd /c run.bat` 처럼 점(`.\`) 없이 부르면 이 PC에서는 "run.bat을 찾을 수 없다"가 나온다
(현재 폴더 실행 제한 설정). 더블클릭이나 `.\run.bat` 은 정상이다.

## 수동으로 남은 것

- 센터 PC에서 사람이 하는 스톱워치(더블클릭부터 화면, 상담 입력부터 인쇄)는 현장 시험에서 다시 잰다.
- 이 PC에서는 프린터로 실제 출력은 하지 않았다(PDF 저장까지만).

## 수정 1차: 런타임 보강 뒤 스모크 (2026-11-08)

`requirements.txt`에 keyring, pypdf, anthropic과 그 의존 부품(pywin32-ctypes, jaraco.classes, more-itertools, jiter, docstring_parser, sniffio, httpx2, httpcore2, truststore)을 더하고
`runtime\site-packages`를 지운 뒤 `python scriptsuild_runtime.py`를 다시 돌렸다(`--python-version 3.12 --platform win_amd64 --implementation cp --only-binary=:all:`).
스모크 결과: `keyring, pypdf, anthropic, fastapi, uvicorn, jinja2, pydantic, multipart, httpx, app.config 모두 불러왔습니다.` 완료 표시(`runtime\.complete`)는 이 확인 뒤에만 쓴다.
두 번째 실행은 설치를 건너뛰고 스모크만 다시 확인한다.
