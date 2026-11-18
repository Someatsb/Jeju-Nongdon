# 운영진 답변과 반영 위치

대회 운영진 답변(2026-11-06까지)이 설계에 준 제약과, 그것을 지키는 곳입니다.

| 운영진 답변 | 반영 | 위치 |
|---|---|---|
| 센터 PC는 Windows 11, Edge·Chrome | 배치 파일(`.bat`)로 실행, Edge로 열기·PDF 저장, 내장 파이썬 `runtime\python` | `run.bat`, `check_install.bat`, `README.md` 설치 5단계 |
| 허브 가공 파일(CSV 등)을 동봉해도 됨 | 도매가·면적 저장본과 표를 폴더에 넣음. 허브 데이터 목록 xlsx·카탈로그 수집본은 넣지 않음 | `data/snapshot/`, `data/tables/`, `docs/3_data_spec.md` |
| 센터의 실제 상담 데이터는 받을 수 없음 | 실데이터 없이 만든 시연 농가 5명과 손으로 쓴 골든 12건으로만 시험. 효과는 "미측정"으로 적음 | `samples/P1`~`P5`, `tests/golden/`, `README.md` 평가 색인 |
| 외부 LLM 사용 가능, 키는 입력 방식, 사용 설명서 필요 | 키는 `keys.bat set llm`으로 센터가 입력, 압축 파일에 키 없음. 보내는 항목을 제한하고 표로 공개. 키 없으면 기본 문장 | `docs/5_ai_disclosure.md`, `docs/7_llm_transfer.md`, `docs/2_user_manual.md` |
| 센터 PC의 보안(DLP)이 외부 통신에 영향을 줄 수 있음 | 키 없는 모드가 기본 경로. 연결 실패는 한 줄 알림 후 템플릿. 재생 시연 | `run_replay.bat`, `app/agents/llm/anthropic_adapter.py`(BANNER) |
| 신고하지 않은 프로그램은 설치하지 않음 | 설치 대상은 내장 파이썬과 `requirements.txt`의 부품뿐. 추가 설치 프로그램 없음 | `requirements.txt`, `scripts/build_runtime.py`, `docs/install_rehearsal.md` |
| 제출은 기획서 PDF와 zip만 필수 | 영상·GitHub는 만들지 않음. zip은 `scripts/build_zip.py`로 만듦 | `README.md`, `docs/6_operations.md` |
| 퇴실 시 삭제 원칙 | 어르신 이름·번호는 저장하지 않음. 문자 번호만 동의 후 암호 보관, 발송 뒤 삭제 | `docs/6_operations.md` 3절 |

미확인(질문하지 않기로 함): 센터 PC에서 인쇄 가능 여부는 운영진 미확인이며 기획서 한계 표에 적습니다.
