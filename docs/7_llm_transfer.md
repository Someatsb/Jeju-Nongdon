# 외부 LLM 전송 항목 표

외부 모델로 나가는 요청은 모두 `build_payload()`(`app/agents/llm/payload.py`)를 지납니다. 어댑터 `generate()`의 첫 줄이고(`anthropic_adapter.py`), 상담 루프(`counsel.py::_Budgeted.generate`)와 공고 루프(`notice.py`), 새 공고 맞춰 보기(`match.py`), 새 공고 찾기(`scout.py`)에서도 한 번 더 지납니다. 걸리면 요청은 나가지 않고 템플릿(또는 직원 확인)으로 갑니다. 오류에는 필드 경로와 규칙 이름만 남고 걸린 글자는 남지 않습니다.

용도(purpose)는 다섯입니다. narrate(설명 쓰기), judge(문장 판정), notice(공개 공고문 읽기), match(새 공고 맞춰 보기), scout(새 공고 찾아오기). narrate·judge는 아래 규칙 5개를 모두 받고, 공개 공고 글을 싣는 notice·match·scout는 주민번호 규칙만 받습니다.

## 1. 보내는 것

| 용도 | 필드 | 목적 | 모양 예 | 안전한 이유 |
|---|---|---|---|---|
| narrate | `section` | 어느 구획을 쓸지 | `support` / `insurance` / `action` / `empty` | 고정 낱말 |
| narrate·judge | `fact_id` | 문장이 근거를 인용하는 열쇠 | `M:jeju_farmer_allowance` | 숫자 없는 별칭. `NarrativeItem`이 숫자를 거부 |
| narrate·judge | `program_id` | 문장 안 `{P:id}` 자리표시자 | `jeju_farmer_allowance` | 숫자 없는 별칭. 실제 id는 `aliases`에 있고 전송 JSON에서 제외 |
| narrate·judge | `status` | 상태에 맞는 말투 | `ELIGIBLE`, `OPEN_NOW` 같은 코드 | 코드 낱말 |
| narrate | `row_status` | 작년 공고 기준 표시 | `prior_year_reference` | 코드 낱말 |
| narrate·judge | `missing` | 부족한 조건 이름 | 조건 열 이름 목록(값은 없음) | 열 이름만. 농가 값은 없음 |
| narrate·judge | `window` | 신청 창 상태 | `open_now` / `upcoming` / `closed` ... | 날짜가 아닌 상태 낱말 |
| judge | `official_name` | 판정이 이름을 대조 | 제도 정식 이름 | 공개 제도 이름. 숫자 불가(검증). 농가 정보 아님 |
| judge | `office_id`, `cites` | 근거 연결 | `office:...` | 숫자 없는 id |
| judge | 심사 대상 문장 | 판정 | `{P:id}`가 든 짧은 문장 | 이미 규칙 검사를 지난 문장. 거름망을 또 지남 |
| narrate·judge | 지시문(system)·재생성 지시·응답 스키마 | 작업 설명 | `app/agents/prompts/` | 고정 글. 스키마 숫자는 길이 제한 키만 허용 |
| match | 공개 공고 글, 공고 조건 확인 도구의 호출과 답 | 새 공고가 이 어르신 답에 맞을지 확인 | 공고 인용, `check_farmer`의 답 "예"·"아니오"·"답에 없음" | 농가 값은 요청에 넣는 길이 없고 답은 세 낱말뿐. 같은 종류 조건을 기준값만 바꿔 세 번째 물으면 거절해 값을 좁혀 알아내지 못하게 함(`app/tools/match_tools.py`) |
| scout | 공식 게시판 글 목록·미리보기 | 새 농가 지원 공고 고르기 | 게시판 글 제목·미리보기 | 공개 글. 농가 정보 없음 |
| notice | 공개 공고문 글, 표 조회 도구의 호출·결과 | 공고 초안 만들기 | 공고 본문, 제도 표 행 | 공개 문서. 날짜·금액·기관 전화가 본래 있어 주민번호 규칙만 건다. 주민번호·휴대전화·메일이 든 문서는 호출 전에 막음(BLOCKED_PII) |

## 2. 안 보내는 것

| 항목 | 왜 안 나가나 |
|---|---|
| 금액(지원금·보험료·손익) | `narrative_input`이 싣지 않음. 숫자 규칙으로도 막힘 |
| 날짜·기준일·신청 기간 | 창은 상태 낱말만. 숫자 규칙 |
| 이름(어르신) | 입력 14항목에 이름이 없고 모델 입력에도 없음 |
| 전화·휴대전화 | 문자 안내 번호는 `FarmProfile`·모델 입력 밖(DPAPI 암호 보관). 전화 규칙 |
| 주민번호 | 입력 항목에 없음. 규칙은 모든 용도에서 적용 |
| 읍면동 | 43개 이름(emd 표 포함)을 부분 일치로 막음 |
| 나이·출생연도·면적·작물별 수량 | 모델 입력에 없음. 숫자 규칙 |
| 건강 낱말(입원·질병·진단·수술·치매·암 합성어) | 규칙으로 막음. 농가 입력의 사건 표시(`flags`)도 모델 입력에 없음 |
| 표 원본 행, 도매가 | narrate·judge에는 없음(notice의 제도 표 조회 도구만 공개 표 행을 돌려줌) |
| 공고 PDF 안의 개인정보 | 주민번호·휴대전화·메일 발견 시 호출 0회로 직원에게 넘김 |
| API 키 | 요청 본문에 없음. SDK 헤더로만 가고 로그·압축 파일에 없음 |
| 요청·응답 원문 | 어디에도 기록하지 않음(검수 로그는 코드·횟수만) |

## 3. 근거

| 규칙 | 코드 위치 | 시험 |
|---|---|---|
| 모든 호출이 거름망을 지남 | `payload.py::build_payload`, `anthropic_adapter.py::generate` 첫 줄, `counsel.py::_Budgeted.generate`, `notice.py` | `tests/agents/test_payload.py::test_gate_walks_every_request_field`, `test_payload_only_from_the_gate` |
| rrn `\d{6}-\d{7}` | `payload.py::RRN` | `test_payload_phone_and_resident_id_are_named`, `tests/agents/test_notice_loop.py::test_rrn_in_document_blocks_without_llm` |
| phone `\d{2,3}-\d{3,4}-\d{4}` | `payload.py::PHONE` | `test_payload_phone_and_resident_id_are_named` |
| 숫자 전부(전각·원문자 포함) | `payload.py::DIGIT`, `_walk`(숫자 값도 글자로) | `test_payload_rejects_digits_and_emd`, `test_payload_rejects_fullwidth_and_circled_digits`, `test_numbers_in_non_string_positions` |
| 읍면동 이름 | `payload.py::JEJU_EMD`, `load_emd_names` | `test_payload_rejects_emd_names`, `test_emd_names_builtin_table_and_digitless_variants`, `test_bad_emd_table_fails_loudly_once_and_payload_rejects` |
| 건강 낱말·암 | `payload.py::HEALTH`, `CANCER_WORDS` | `test_payload_rejects_health_words`, `test_payload_cancer_compounds_rejected`, `test_payload_am_inside_other_words_passes` |
| notice는 주민번호만 | `payload.py::PayloadGuard.build`(`_notice_rules`) | `test_notice_purpose_keeps_only_the_resident_id_rule` |
| 보내는 필드는 `narrative_input`뿐 | `core/pipeline.py::narrative_input`, `counsel.py::build_request` | `tests/identity/test_narrative_input_numberless.py::test_narrative_input_numberless_all_golden` |
| 별칭이 실제 id를 가림 | `models.py::NarrativeInput.aliases`(exclude) | `test_ids_are_placeholder_safe_and_aliases_map_back` |
| 오류가 걸린 글자를 안 담음 | `payload.py::PayloadRejected` | `test_rejection_names_the_field_never_the_text` |
| 공고 PDF 개인정보는 호출 전 차단 | `notice.py`(BLOCKED_PII), `draft_checks.py::pii_labels` | `tests/agents/test_notice_loop.py::test_n5_pii_blocks_without_llm` |
| 거름망 통과 문장만 종이에 | `counsel.py::Narrative.texts` | `tests/agents/test_counsel_scripted.py` |
| 새 공고 맞춰 보기에 어르신 값이 안 나감 | `tools/match_tools.py`, `agents/match.py` | `tests/agents/test_match_privacy.py` |

한계: 거름망은 글자 규칙입니다. 제도 이름은 공개 이름이라 허용하며, 이름에 숫자가 있으면 `NarrativeItem` 검증이, 읍면동·건강 낱말이 있으면 거름망이 막아 그 구획은 기본 문장이 됩니다. 제공자 쪽 보관·학습 이용은 이 프로그램이 통제하지 못하며 센터가 쓰는 키의 계약 조건을 따릅니다(법무 검토 권고: 유료 키만 사용).
