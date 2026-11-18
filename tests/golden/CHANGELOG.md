# 골든 기대값 변경 기록 (Task 34)

원칙: 사양(설계 v2 · 12-B 사장 결정 · 계획서)이 정본, 골든 JSON은 사양의 예시, 엔진은 구현. 어긋남마다 "기대값 오류"(JSON 수정, 여기에 사유)와
"코드 오류"(모듈 수정, 단위 시험)로 가렸다. 사례 번호 · 이전 값 → 이후 값 · 근거 순서로 적는다. 근거 약어: 설계 = `docs/superpowers/specs/2026-11-07-jeju-chaenggim-design-v2.md`,
원장 = `.superpowers/sdd/2026-11-07-chaenggim-build-plan/progress.md`(번호는 줄), 계획서 = `docs/superpowers/plans/2026-11-07-chaenggim-build-plan.md`.
구분 칸의 **코드**는 JSON은 그대로 두고 모듈을 고친 것이다.

## A. 어댑터(`golden_adapter.py`) — 추측을 걷어 냄 (입력 해석)

| 항목 | 이전 | 이후 | 근거 |
|---|---|---|---|
| 땅 `own_part` | 소유 1.55ha 이상이면 own_part | `owns_farmland=Y`는 항상 `own_all`, N은 `rent_all` | JSON에 '일부 내 땅'을 가리는 칸이 없다. `tests/conftest.py` 대응표는 land_tenure를 own/partial/rent로 받지만 골든 JSON은 1라운드 칸(owns_farmland)만 준다. 소유 4,700평 초과는 `owned_over_4700py`가 따로 받는다 |
| 판매 경로 `sales_channel` | coop → coop, 밭떼기 계약 Y → field_contract_done, 둘 다 아님 → unknown | 변경 없음, 규칙을 docstring에 적음 | conftest 대응표 "coop_shipping=Y → coop, field_sold_contract=Y → field_contract_done" |
| 사례별 기준일·fixture | 모든 사례 2026-11-13 고정, `fixture` 무시 | `case_env(case)`가 `as_of`로 표·스냅샷을 읽고 `price_override`(합성 반월 평균)·`jasdc: saved_YYYYMMDD`(수급센터 저장본 절단)를 입힘 | B04·B03은 이 fixture 없이는 시험이 안 된다. G13·G14는 다른 기준일 |
| 매핑 없음 | — | `coop_member`, `offfarm_income_band`, `disaster_end_date`, `flags` 목록, `farmland_owned_years`·`jeju_residence_years`의 숫자(참/거짓만) | FarmProfile에 짝이 없다. 사례의 의도(조건 유무)는 유지 |

## B. 공통 규칙 결정

| 결정 | 내용 | 근거 |
|---|---|---|
| 빈 종이(all_set)의 정의 | A~D에 LIKELY/CHECK 줄이 하나라도 있거나 먼저 할 일(B)·급한 일(A)·계통 전환(C)이 있으면 빈 종이가 아니다. 다음 창(APPLY_NEXT)만 있는 종이도 비어 있지 않다 | 설계 §1(37행) 가장자리 ⑤ "시기 놓침"이 가장자리다. 빈 종이 문구 "새로 해당되는 돈은 찾지 못했습니다"(sheet_front_empty.html). 코드 그대로(`sheet.build_sheet`의 `core`) |
| 빈 종이의 '끊기지 않게' | 경영체 갱신 연도는 몇 년 뒤여도, 직불 교육은 직불을 받는 분(Y/N)이면 항상 나온다 | 설계 §12-A(2) "끊기지 않게 할 일(경영체 갱신 연도, 직불 교육)". 코드 수정(`sheet._keep_all`) |
| 작년 공고 기준 배지 | "2026년 기준 · 2027년 공고 전 · N월 확인"(코드)로 통일. 골든의 "2025-26 … 공고 전" 시즌 표기를 연도 표기로 | 설계 §12-A(2) 배지 예 "2026년 기준, 2027년 공고 전, ○월 확인". 가격안정관리제 행도 같은 문구 |
| `manual_check` 인쇄 꼬리표 | LIKELY = FAIL 0 · UNKNOWN 0 · 소득 심사 아님, CHECK = UNKNOWN ≥ 1이거나 소득 심사 | 코드(`sheet._print_tag`) 그대로, 시험 `test_sheet_tags` |
| 인쇄 안 하는 제도 | 농지연금·은퇴직불은 종이에 안 나온다(`actions.UNPRINTED_KEYS`). 골든은 `must_not_print`로 | 원장 128행 Ruling (3), 골든 P4 `must_not_print` |
| 농업 밖 제도 | "농업 밖 제도" 표시 폐기, 어르신 행복택시 hold 영구 | 설계 §12-B 2 (사장 결정 2026-11-08) |
| 앞면 한정 금지 글 | 뒷면 '뺀 것' 표에 제도 이름이 나오는 것은 정상이라 `must_not_print_front`(앞면만) 키를 새로 둠 | 설계 §7-2 뒷면 "못 넣은 것·뺀 것" |
| `all_set` 블록 | 러너가 이제 `front_top_must_include`·`keep_actions_must_include`·`calendar_3`·`kept_money.display`를 비교한다 | 예전에는 적혀만 있었다 |

## C. 사례별 기대값 변경 (JSON)

| 사례 | 항목 | 이전 → 이후 | 구분 | 근거 |
|---|---|---|---|---|
| B01 | `must_not_print` "소규모 농가 경영안정" | 종이 전체 → `must_not_print_front`(앞면만) | 기대값 | 같은 사례 B01-K2가 뒷면에 이 제도가 "면적 조건에 안 맞음"으로 나와야 한다고 요구한다. 앞면에만 없으면 된다 |
| B01·B07 | "12월"(시즌 전 줄) | (JSON 그대로) | **코드** | 시즌 전 줄이 "시즌 전"만 찍고 판정 시작 달이 없었다 → "시즌 전 · 12월부터"(`sheet._support_line`) |
| B02 | B02-K1(은퇴직불 84·85세 줄) | 줄 요구 → 삭제, `must_not_print`에 "은퇴직불","농지연금" 추가 | 기대값 | 원장 128행 (3), `actions.UNPRINTED_KEYS` |
| B02 | B02-K2 "87세" | `["안전보험","87세"]` → `["안전보험"]` | 기대값 | NH안전보험 행은 출처 hold라 줄에 숫자를 안 찍는다(`Line.no_numbers`, 원장 Task 20) |
| B02 | also 농지연금·행복택시 | 줄 요구 → 삭제, 행복택시는 `must_not_print` | 기대값 | 설계 §12-B 2, UNPRINTED_KEYS |
| B03 | B03-K2(노지감귤 가격안정 STALE 줄) | 삭제 | 기대값 | `JEJU-CITRUS-PSTAB@2026-27`이 표에서 hold(기준가 미공개)라 줄이 없다. 예전 통과는 다른 행의 "농·감협" 글자 우연이었다 |
| B03 | B03-K1 "감귤 · 2026년 4월 6일 · 현재 값 아님" | (JSON 그대로) | **코드** | 머리에 '현재 값 아님' 띠가 없었다(설계 §6-3 ≥15일 빨간 배지). `render._stale_notes` + 머리 매크로. fixture `jasdc: saved_20260406` |
| B04 | K1 "kg당 최대 245원 하한가", K2 "작년 71원 예측 아님" | (JSON 그대로) | **코드** | 열림/근처 줄이 "작년 115만 원" 총액만 찍었다. 오늘 kg당 최대·하한가·작년 kg당 사실 + 예측 아님으로(`sheet._support_line`). 합성 fixture(반월 700원·8일)로 판정 MET |
| B04·B12·P2·P4·P5·T2 | 배지 "2025-26", `badge_basis` "2025-26 시즌 기준, 2026-27 공고 전" | → "2026년 기준" · "2026년 기준, 2027년 공고 전" | 기대값 | B절 배지 결정 |
| B05 | B05-K1 `must_not_include` 10일·20%·70%·대파대 | 삭제 | 기대값 | `NAT-DISASTER-RECOVERY@2026`이 confirmed로 올라왔고 10일·70%·20%가 G 2라운드에서 확인됨(표 evidence/notes). 골든은 hold 시절 가정 |
| B05 | `must_not_print` "농약대" | 삭제 | 기대값 | 같은 이유: 재해 줄 detail이 manual_check 원문(대파대·농약대 기준)을 그대로 찍는다 |
| B05 | B05-K2 "재해보험·농협·사고" | (JSON 그대로) | **코드** | 재해 피해 + 재해보험 가입이면 A칸에 "재해보험 사고 접수 · 가입하신 농협에 사고를 알려 주세요" 줄 추가(`sheet._claim_lines`) |
| B05 | also "준비 중" | (JSON 그대로) | **코드** | 뒷면에 "준비 중 n건"(hold 제도 수) 추가(`sheet_back.hold_note`) |
| B07 | B07-K2 "E칸 재해보험 8월" (ENROLLED) | 칸 E → 달력, `["재해보험","8월"]` → `["작물 보험"]` | 기대값 | 가입 중인 보험은 '들어 두시면 좋은 보험'(E)에 나오지 않는다(`sheet._section_e`는 ENROLLED를 빼고 빈 종이에서만 낸다). 다음 창은 '다음에 오실 때' 달력에 있다 |
| B08 | B08-K2 "1.55ha" | (JSON 그대로) | **코드** | 뒷면 '뺀 것' 이유에 기준·입력이 없었다 → "소유 면적 조건에 안 맞음 (기준 1.55ha · 입력 15501㎡ 이상)"(`sheet_back._fail_reason`) |
| B09 | B09-K1 농지연금 F줄 | 줄 요구 → 삭제, `must_not_print` "농지연금" | 기대값 | UNPRINTED_KEYS |
| B10 | B10-K1 은퇴직불 60만 | 줄 요구 → 삭제, `must_not_print` "은퇴직불" | 기대값 | UNPRINTED_KEYS |
| B11 | B11-K1 "거주 3년" | (JSON 그대로) | **코드** | 같은 '뺀 것' 이유 보강 |
| B13 | B13-K2 "의무자조금" PREREQ와 first_actions | 삭제 | 기대값 | `insurance.csv`·`supports.csv`에 만감류 수입안정보험의 자조금 요건이 없다(extra_requirement 빈 칸). 표에 없는 요건을 만들어 낼 수 없다 |
| B13 | B13-K1 "수입안정보험 만감류 4월 둘 중 하나" | (JSON 그대로) | **코드** | 보험 줄 제목이 작물 코드 앞토막("감귤")이라 노지온주와 만감류를 못 가렸다 → 표의 작물 이름(`sheet._crop_label`) |
| P1 | K1 "통지서" | (JSON 그대로) | **코드** | `NAT-DIRECT-ANY`(받는 직불 종류 모름)가 소농·면적직불 줄에 "직불 종류: 작년 통지서 확인"을 붙임(`sheet._direct_pay_note`) |
| P1 | K2 "수입안정보험 온주 대상 아님 재해보험" | (JSON 그대로) | **코드** | 보험 줄 sub "수입안정보험은 대상 아님 · 재해보험만" |
| P1 | KEEP_RISK 직불 교육 "10%","9월" | `["직불 교육","10%","9월"]` → `["직불 교육"]` | 기대값 | 감액률 10%와 9월 기한은 supports.csv 어느 행에도 없다(표 근거 없는 숫자는 못 찍는다, 설계 §7-4 "숫자 줄은 코드만") |
| P1 | also JEJU-PSTAB(상인 → 올해 해당 없음) | 삭제 | 기대값 | 노지감귤 가격안정관리제는 표에서 hold(기준가 미공개). hold는 줄이 없다(설계 §12-A(2) 행 상태 셋) |
| P1·P2·P3·P5 | also NHIS-FARMER-SUPPORT "농업 밖" · label | `["건강보험료","농업 밖"]` → `["건강보험료"]`, label 삭제 | 기대값 | 설계 §12-B 2 |
| P1·P2·P3·P4·P5·B02 | also JEJU-HAPPY-TAXI | 삭제 | 기대값 | 설계 §12-B 2(hold 영구, 범위 밖) |
| P2·P3·P5 | K1/K2/K1 배우자 등록 PREREQ "20만","45만" | (JSON 그대로) | **코드** | 먼저 할 일 `PREREQ:spouse_registration` 신설: 행복이용권(배우자 몫) + 2인 경영체 농민수당 차액(`actions._spouse`), 줄 detail에 두 금액 |
| P2 | K2 "1,088원","71원" | (JSON 그대로) | **코드** | 가격안정관리제 ALREADY 줄(E2)에 "이번 반월 아직(잠정) · 기준가 1,088원 · 작년 kg당 71원"(`sheet._section_e2`). 앞면이 가득 차 넘침 줄이어도 뒷면에 detail까지 찍음 |
| P2 | insurance "80%" | (JSON 그대로) | **코드** | 보험 줄 detail에 `insurance.csv extra_requirement`("싹이 밭의 80% 이상…") |
| P2 | also "이미 받고 계신 것" | (JSON 그대로) | **코드** | 뒷면 입력 요약에 추가(`sheet_back._receiving_names`) |
| P2 | 작년 기준 줄 2,309,000 → 2,310,000 | (JSON에 값 없음) | 기대값(원장 123행) | 10만 이상 1만 단위 반올림. 러너는 이 값을 비교하지 않으나 코드 값이 2,310,000(시험 `test_amounts`) |
| P3 | also 월동무 상인·올해, NAT-PSTAB-GARLIC "기준가격" | 삭제 | 기대값 | 월동무 가격안정 행이 표에 없고, 마늘 정부 가격안정제는 `NAT-PRICE-STAB-GO` hold |
| P4 | K1 "180만" | (JSON 그대로) | **코드** | 막힌 행의 금액 줄이 없어 `unlock_amounts`가 pipeline에 연결되지 않았다 → `actions._prereq`가 `unlock_amounts`로 채움 → "하시면 연 약 180만~258만 원" |
| P4 | K2 "153원" | (JSON 그대로) | **코드** | `_last_season_fact`가 읽을 금액 줄이 없었다 → 계통 전환으로 막힌 가격안정 행도 총액 없는 "작년 kg당 평균" 사실 줄을 가짐(`amounts._price_stab_crop` fact_only) |
| P4 | K2 한 줄 → K2·K3·K4 세 줄 | PSTAB만 → PSTAB·물류비·토양생태 | 기대값 | 원장 152행 Ruling: 세 행 모두 supports.csv에 계통 출하 조건이 있다(Task 15 재검토 확인) |
| P4 | insurance 수입안정·재해·안전 NOT_ELIGIBLE | → NEXT_WINDOW/CHECK, reasons `needs_mgmt` | 기대값 | 원장 109행 Ruling (2): 경영체 미등록은 숨기지 않고 안내 |
| T1 | `already_receiving`에 `NAT-PENSION-SUPPORT` 추가, all_set 키 "9월" 삭제, also JEJU-PSTAB info 삭제 | 입력·기대 변경 | 입력+기대값 | 표가 15~18행에서 43행으로 커져 "다 챙긴 농가"도 연금보험료 지원이 걸린다. 빈 종이 정의(B절)를 코드 그대로 두고 프로필을 "새 행도 받는 중"으로 갱신. 직불 교육 9월은 표 근거 없음. 골든 T1 `unverified`의 "기대를 바꾸지 프로필을 바꾸지 않는다"와 반대로 판단함(빈 종이 모드 시험이 사라지지 않게). 되돌리려면 T1·T2의 `paper_mode`를 normal로 바꾸면 된다 |
| T1 | K2 "끊기지 않게 경영체 2028년 직불 교육" | (JSON 그대로) | **코드** | 빈 종이는 갱신이 몇 년 뒤여도 연도와 직불 교육을 항상 낸다 |
| T1 | `must_not_print` "소농직불" | → `must_not_print_front` | 기대값 | 뒷면 '뺀 것'에 나오는 제도 이름 |
| T2 | `already_receiving`에 JEJU-LOGI, DO-SMALL-MACHINE, DO-IRRIGATION, JS-BIODEG, JEJU-SOIL-ECO 추가 | 입력 변경 | 입력 | 같은 이유(토양생태 휴경은 골든 T2 `unverified`가 이미 예고). 지키실 돈 "연 약 260만~325만 원" → "연 약 720만~805만 원"(토양생태 440만~460만, 칼슘유황 20만 포함), `kept_money` 값·calc 갱신 |
| T2 | K2 `must_include` "1,088원" | 삭제(가격안정관리제만) | 기대값 | 빈 종이에는 제도별 줄이 없다. 기준가·작년 사실은 줄이 있는 종이(P2·G13)에서 시험 |

## D. 새 사례

| 사례 | 내용 |
|---|---|
| G13 | 2026-01-15 당근, P2 프로필 복사에서 `JEJU-PSTAB` 받는 중만 뺌(받으면 앞면 줄이 안 된다). 반월 1~15일 거래량 가중 평균 1,163.6원(11일)이 기준가 1,088 × [0.911, 1.143) = [991, 1,244) 안 → NEAR. 줄: "곧 열릴 수 있음 · kg당 최대 245원 / 하한가 816원 / 작년 kg당 71원 · 예측 아님". 민감도 시험에서 ×0.8 → MET, ×1.1·×1.2 → NOT_MET으로 뒤집힘 |
| G14 | 2026-03-15 양배추, P4 프로필 복사. 3월 1~15일 평균 656.4원(12일) < 723 × 0.911 = 658.7 → MET이지만 밭떼기·자조금 미가입이라 줄은 계통 전환(열림 아님). 뒷면 가격 근거에 `PRICE_STAB · MET`, `LOGISTICS · NEAR`. 민감도: ×1.1·×1.2에서 PRICE_STAB MET → NEAR, ×0.8·×0.9에서 LOGISTICS NEAR → BELOW |
| 손으로 맞춘 값 | 위 평균·기준가는 `scripts/sensitivity_prices.py`(엔진과 별개 코드)의 `wavg`로 따로 계산해 엔진 값(1163.6 / 656.4)과 같음을 확인했다 |

## E. 코드 오류로 고친 것 (모듈 · 시험)

| 모듈 | 고침 | 시험 |
|---|---|---|
| `models.TriggerResult.crop_code`, `triggers.check_triggers` | 판정에 작물 코드 | `test_golden_review_fixes` |
| `sheet._Ctx.trigger` | **이월 항목 1**: 줄을 움직이는 판정(driving trigger)을 겨냥 작물 중 가장 '열린' 것으로 고름. `trigger_id`도 같은 판정 | `test_two_crop_line_follows_the_most_open_target_crop_trigger…`, `test_trigger_id_names_the_driving_crop…` |
| `amounts.target_crops`, `amounts._price_stab_crop(fact_only)` | 겨냥 작물, 막힌 가격안정 행의 작년 kg당 사실 | `test_blocked_pstab_keeps_last_season_kg_fact_only` |
| `actions._prereq` · `_group_change` | 막힌 행의 열리는 돈을 `unlock_amounts`로 | `test_blocked_prereq_line_unlock_money_comes_from_unlock_amounts` |
| `actions._spouse` · `sheet._spouse_detail` | 배우자 경영체 등록 먼저 할 일 | `test_spouse_registration_prereq_…`, `test_no_spouse_prereq_…` |
| `sheet._support_line`·`_section_e2` | 시즌 전 시작 달, kg당 최대·하한가·작년, E2 가격 사실 | `test_out_of_season_line_says_when_the_season_starts`, `test_open_price_line_prints_kg_facts_not_a_farm_total` |
| `sheet._prereq_line`·`_enroll_note` | 자조금 먼저 할 일에 "참여 신청도 필요 · 예년 N월" | `test_fund_prereq_names_the_enrollment_it_does_not_cover` |
| `sheet._keep_all` | 빈 종이 끊기지 않게 | 골든 T1·T2 (`all_set`) |
| `sheet._claim_lines`, `_crop_insurance_line` | 재해보험 사고 접수 줄, 보험 요건·수입안정 안내·작물 이름 | `test_disaster_with_enrolled_insurance_adds_a_claim_line`, `test_insurance_line_shows_…` |
| `sheet._direct_pay_note` | 직불 종류 모름 → 작년 통지서 | `test_direct_pay_line_asks_for_last_years_notice…` |
| `sheet_back` (`hold_note`, `_receiving_names`, `_fail_reason`, 건강보험 요약), `sheet_rules` (`UNIT_OF`, `KEY_NOTE`, `VALUE_LABEL["health_ins"]`) | 뒷면 준비 중 · 받고 계신 것 · 뺀 이유의 기준·입력 · 건강보험 한글 | `test_back_page_hold_note_receiving_names_and_failure_basis`, `test_back_input_summary_shows_health_insurance_in_korean` |
| `render._stale_notes`, `_sheet_macros.html`, `print.css` | '현재 값 아님' 띠(감귤 저장본·시세 STALE, 15일) | `test_stale_note_only_for_citrus_growers_and_only_from_15_days` |
| `sheet_back.html` | 넘침 줄의 detail도 뒷면에 | 골든 P2 |
| **이월 항목 2** `test_sheet_tags.test_back_page_never_prints_raw_codes` | 값 집합을 시험에 적지 않고 모델 Literal(`get_args`)과 판정기가 실제로 낸 field에서 읽음. 소스 글자 정규식 제거 | 같은 시험 |
| **이월 항목 3** 건강보험 조건 | 입력 요약에 건강보험 납부 방식(한글), `VALUE_LABEL["health_ins"]`를 Literal과 대조 | 같은 시험 |
| `tests/fixtures/preflight/*.html` | `TriggerResult.crop_code`로 계산 지문이 바뀌어 `python tests/preflight_support.py`로 다시 씀 | `test_preflight` |

## F. 수정한 파일 (레인 U 소유 포함)

`app/ui/render.py`(`_stale_notes`, `STALE_DAYS`), `app/ui/templates/_sheet_macros.html`(머리 띠), `app/ui/templates/sheet_back.html`(준비 중 줄, 넘침 줄 detail), `app/ui/static/print.css`(`.stale`). 나머지는 `app/core/*`. `app/agents/*`, `app/data_layer/*`, `data/tables/*`는 건드리지 않았다.

## G. 검토 1차 반영 (fix round 1)

### G-1. 러너: 앞면 글만 본다
`key_lines`·`first_actions`·`insurance`는 앞면 글에서만 찾고, `program_key`가 있는 항목은 그 줄(제목·글·작은 글씨·원문·배지) 안에서만 찾는다.
뒷면 글로 맞추려면 항목에 `"section": "back"` 또는 `"where": "back"`을 적는다(`also`는 종이 전체). 처음 어긋난 13건(검토가 센 24는 뒷면 이유가 정당한 B01/B06/B08/B11 포함) 각각의 결정:

| 사례 | 항목 | 결정 | 구분 | 근거 |
|---|---|---|---|---|
| P5 | first_actions "자조금 확인" | 앞면 B칸에 `ASK_COOP:fund` 줄 "자조금 가입 확인 · 농협에 자조금 가입을 확인하세요" | **코드** | 자조금 가입 여부를 몰라 CHECK가 된 제도가 있으면 농협에 물어보게(`actions._apply`). 브로콜리 가격안정관리제가 해당 |
| P5 | P5-K2 "브로콜리 가격 농협" | 줄 글자 "자료 오래됨" → "기준가 미확인 · 농협 확인" | **코드** | NO_DATA(note 기준가 미확인)는 자료가 오래된 게 아니다 — 글자가 틀렸다 |
| P1 | first_actions 자조금(selfpay_fund_member) | 삭제 | 기대값 | 자조금이 필요한 제도(노지감귤 가격안정)가 표에서 hold라 물어볼 대상이 없다 |
| B01 | B01-K1 "0.5ha" | 소농직불 줄에서 빼고 B01-K1b(`section: back`)로 | 기대값 | 표 `max_ha`는 0.86이고 "0.5ha 넘으면 면적직불 계산액이 130만 원 미만일 때만"은 manual_check라 창구 확인란(뒷면)에 있다 |
| B02 | B02-K2 "안전보험" | `where: back` | 기대값 | 앞면 7칸을 C·D 줄이 채워 NH안전보험은 넘침("앞면 항목 상한 → 이 면으로")으로 간다. 칸 순서 A→E 고정 |
| P2, G13 | insurance 당근 재해보험 "80%" | `where: back` | 기대값 | 위와 같음: B(배우자 등록)·D 줄이 앞면 7칸과 한 쪽 35줄 한계를 채운다. 가입 요건은 넘침 줄의 detail로 뒷면에 찍힌다 |
| P2 | P2-K2 (가격안정관리제 · 1,088원 · 71원) | `where: back` | 기대값 | 'E2 작년처럼 다시 신청'은 맨 마지막 칸이라 앞면이 차면 넘침. 뒷면 넘침 줄에 detail까지 찍힌다 |
| P3 | insurance 월동무 수입안정 배지 "8월" | `where: back` | 기대값 | 앞면이 A·B·C·D로 차서 월동무 보험 줄은 넘침. 실험: 금액 없는 자재 줄(quiet)을 먼저 넘기는 우선순위를 시도했으나 한 쪽 35줄 한계(preflight OVERFLOW)를 넘어 되돌렸다 |
| T2 | T2-K2 (가격안정관리제) | `where: back` | 기대값 | 빈 종이 앞면에는 제도별 줄이 없다(뒷면 '이미 받고 계신 것'에 이름) |

### G-2. 코드 오류로 더 고친 것
| 항목 | 고침 | 시험 |
|---|---|---|
| 배우자 성별 추측 | `actions._spouse`가 `spouse_sex`가 None이면 추측하지 않고 이름·금액 없는 CHECK 줄 "배우자 등록 여부와 대상 확인"만 낸다. 어댑터는 사례 JSON이 `spouse_sex`를 적은 곳(P2·P3·P5·G13: 아내)에서만 옮긴다 | `test_unknown_spouse_sex_gives_check_only_line…` |
| DIFF_IF_SWITCH | `AmountLine.kind` 추가. 소농직불 고정액 − 면적직불 범위(하한은 0 아래로 안 감, 상한이 0 이하면 줄 없음). 면적직불을 이미 받거나(소농 행은 EXCLUSIVE_OTHER) 받는 직불 종류를 모를 때(`NAT-DIRECT-ANY`) 소농 줄 detail에 "전환하면 약 N만~M만 원 더(확인)", CHECK 꼬리표. P1 23만~56만, P5 최대 약 25만 | `test_switch_money_line_*`, 골든 P1·P5(기대값 복원) |
| 배우자 안전보험 나이 | `insurance._spouse_birth_years`: 예전 코드는 배우자 태어난 해를 받지 않아 P3·P5 배우자 안전보험이 `age_unknown` CHECK였다. `spouse_birth_year`로 `age_bounds` 판정(통과 OPEN_NOW, 범위 밖 NOT_ELIGIBLE, 없으면 CHECK). 컨트롤러 Ruling "P2/P3 spouse ages via spouse_birth_year" | `test_spouse_safety_insurance_uses_spouse_birth_year` |
| 나이 판정(`age_bounds`) | 보험나이는 근거가 없어 쓰지 않고 신청일 기준 `age_bounds` 구간으로 판정, 걸치면 CHECK(원장 109행 Ruling (3)). 이 작업에서 코드를 바꾼 것은 없다(이미 Task 5·11 반영). 골든에서 보이는 곳: B02(1941생 안전보험 87세 상한, 숫자는 hold라 안 찍음) | `tests/unit/test_insurance.py` |
| 가격 줄 숫자의 작물 | `AmountLine.crop_code` 추가, `_kg_facts`가 줄을 움직이는 판정의 작물(`TriggerResult.crop_code`)과 같은 작물의 숫자만 쓴다. 쓰지 않던 `crops` 인자 삭제 | `test_price_amount_lines_carry_their_crop…` |
| 작년 공고 배지의 연도 | `notice_badge`: 공고 달이 올해 아직 앞(또는 이번 달)이면 "{올해-1}년 기준 · {올해}년 공고 전", 지났으면 "{올해}년 기준 · {내년}년 공고 전". 달을 모르면 예전 문구 | `test_prior_year_badge_year_follows_the_notice_month` |
| 정리 | `actions._spouse`의 이어 붙은 문장, `_keep_all`을 제목이 아닌 행동 종류로 중복 제거, `_fail_reason` 면적은 ha 하나로("기준 1.55ha · 입력 1.5501ha 이상"), `STALE_DAYS`는 `snapshot_models.freshness`와 같은 문턱, `scripts/sensitivity_prices.py` 파일 닫기(`with`) | 기존 시험 |

### G-3. 새 시험
`tests/golden/test_golden.py::test_mid_season_cases_flip_under_price_error_and_agree_with_the_engine`: 스크립트의 `run_case`를 불러 G13(PRICE_STAB NEAR → ×0.8 MET, ×1.1·×1.2 NOT_MET)·G14(PRICE_STAB MET → ×1.1·×1.2 NEAR, LOGISTICS NEAR → ×0.8·×0.9 BELOW)의 뒤집힘을 단정하고, 엔진의 배수 1.0 판정이 스크립트와 같은지 비교한다(파일 쓰기 없음).

### G-4. 기대값 문구 갱신
| 사례 | 항목 | 이전 → 이후 | 근거 |
|---|---|---|---|
| G13, G14 | 가격안정관리제 줄 배지 | "2026년 기준 · 2027년 공고 전" → "2025년 기준 · 2026년 공고 전" | 1월·3월에는 올해 9월 공고가 아직 앞이다(G-2 배지 연도). 표는 2026-11 판, 스냅샷은 11-08 판을 기준일만 바꿔 쓴 시험이라 값은 그 판의 것임 |
| P1, P5 | 소농직불 줄 | 전환 차액 문구 요구 복원 | G-2 DIFF_IF_SWITCH |
| B05 | B05-K1 `why`·`must_not_include` | hold 시절 설명 삭제 | 재해복구비 행은 confirmed(C절 B05) |
| T1, T2 | `unverified` | "표에 제도가 늘면 프로필(already_receiving)을 늘려 '다 받고 있는 농가' 페르소나를 유지한다(2026-11-08 결정)" | 컨트롤러 결정 |

### G-5. 이월(미해결)
FAILURES.md "미해결"에 정리: B03 "인터넷 없음" 띠(`Header.refresh_ok`를 저장된 `RefreshReport`에서 연결해야 함 — Task 26/28 후속), P3 마늘 STALE 띠(스냅샷에는 마늘 시리즈가 있고 마지막 날이 2026-02-26이지만 OUT_OF_SEASON이 STALE보다 먼저 판정돼 시세가 인쇄되지 않는다).

## H. 2026-11-11 평가단 3차 보완

| 사례 | 이전 → 이후 | 구분 | 근거 |
|---|---|---|---|
| G13, G14 (calc 설명문) | 경계 배수 0.92·1.148 → 0.911·1.143 (G13 구간 [1,001, 1,249) → [991, 1,244), G14 665.2 → 658.7) | 기대값(설명문만) | 0.920/1.148은 저장본 `agg_869_ratio.csv`에서 나오지 않았다. `_ratio_bounds`와 같은 inclusive 분위수 재계산값 p90 1.0977·p10 0.8746 → 1/p90 = 0.911, 1/p10 = 1.143. 판정(G13 NEAR, G14 MET)은 그대로이고 뒤집힌 사례는 0건. |
| tests/unit/test_triggers.py `test_band_edges` | 경계 919.9/920.0/1147.9/1148.0 → 910.9/911.0/1142.9/1143.0 | 단위 시험 | 같은 이유(경계 배수 0.920/1.148 → 0.911/1.143(저장본 재계산)). |
| tests/unit/test_golden_review_fixes.py | "하시면 연 …" → "하시고 조건 맞으면 연 …" | 단위 시험 | A줄(먼저 하실 일) 문구가 "하시면"만으로는 확정처럼 읽힌다는 평가 지적. 골든 P4는 금액 "180만"만 보므로 JSON은 그대로. |
| tests/ui/test_replay.py | 재생 시험의 P4 입력 `P4_FORM`(3,600평) → 시연 입력 `DEMO["P4"]["form"]`(3,630평 = 12,000㎡) | 시험 입력 | 재생 P4 입력을 골든 P4와 같은 프로필로 통일(지문 9cd623f4 하나). |

## I. 2026-11-13 4차 심사 보완(v6): 종이 문구를 지원제도 표와 일치

| 사례 | 이전 → 이후 | 구분 | 근거 |
|---|---|---|---|
| 22건 전부 FIXED-DISCLAIMER | `must_include` "해당될 수 있는" → "이 종이를 뽑아 준 곳" | 기대값 | 바닥글 첫 줄을 "이 종이를 뽑아 준 곳: 제주빅데이터센터 창구 · 궁금한 점도 그곳에"로 바꿈(심사: 어르신이 어디에 물어야 할지 모름). `sheet_rules.DISCLAIMER` |
| B02 | B02-K2(E칸 NH안전보험, where back) 삭제, `must_not_print_front`에 "안전보험" | 기대값 | NH안전보험 행(10행)은 status=hold다. hold 출처의 보험 줄은 앞면에서 빼고 뒷면 '준비 중' 수에만 센다(`sheet._section_e`). 앞면 줄과 뒷면 "준비 중 3건"이 어긋났었다 |
| G13 | also "PRICE_STAB · NEAR" → "가격안정관리제 · 곧 열릴 수 있음" | 기대값 | 뒷면 가격 판정 근거 줄의 영문 코드를 한글로(`sheet_back.price_basis`) |
| G14 | also "PRICE_STAB · MET" → "가격안정관리제 · 열림", "LOGISTICS · NEAR" → "물류비 지원 · 곧 열릴 수 있음" | 기대값 | 같은 이유 |
| P3 | A줄 `first_actions` must_include "대정농협" → "지역농협" | 기대값 | "대정농협"은 앞면 '가실 곳'의 토양생태 접수처 나열("성산·…·대정농협, 수급관리센터")에 우연히 들어 있던 글자였다. 가실 곳은 이제 직접 신청·먼저 할 일 줄의 접수처를 먼저 담고 최대 3칸이라 토양생태(C구역) 칸은 밀린다. A줄의 접수처는 표에서 "지역농협"이다 |
| P3 | 월동무 수입안정보험 `badge_must_include` "8월"(where back) → "8~10월" | 기대값 | 뒷면 넘침 줄의 "다음 가입은 8월 1일부터"가 "다음 가입 8~10월(농협 확인)"로 바뀜: 재해보험(시작 8/1)·수입안정보험(시작 8/1)처럼 상품마다 시작일이 달라 한 날짜로 단정하지 않는다(`sheet._crop_insurance_line`) |
| tests/unit/test_calendar.py | 달력 칸의 창 "둘 다 열린 기간(교집합)" → "합집합(가장 이른 시작~가장 늦은 마감) + 제도별 달 라벨" | 단위 시험 | 둘째 칸이 농민수당 창(3/9~31)만 써서 직불(3/1~5/31)을 3월 말에 끝나는 것처럼 보이게 했다. `no_overlap` 시험은 이름을 `…takes_union_window`로 바꿔 합집합을 확인 |
| tests/unit/test_sheet.py, test_sheet_tags.py | "작년 kg당 153원" → "지난 시즌 kg당 153원", NH안전보험 hold 줄 존재 → 앞면에 없음 | 단위 시험 | C구역 사실 줄 표기·hold 보험 앞면 제외 |
| tests/ui/test_confirm.py `test_new_counsel_clears_session` | 문자 번호를 넣는 제출을 대신 입력(mode=proxy) → 일반 입력 | 시험 입력 | 대신 입력은 이제 문자 동의를 받지 않는다(번호가 와도 버림). 새 시험 `test_proxy_input_ignores_reminder_consent`가 대신 입력 쪽을 확인 |

## J. 2026-11-14 종이 단순화(가실 곳별 카드 + 결론 한 줄): 배치가 달라져서 고친 시험

사실(숫자·금액·날짜·전화·제도 이름·접수처)은 하나도 바꾸지 않았다. 골든 JSON 22건의 기대값은 그대로이고, 줄(Line) 글에 걸린 기대(`program_key` 항목)는 모델이 그대로라 통과한다. 달라진 것은 "어디에 찍히는가"뿐이다.
앞면 조건 줄·부연·확인 달·날짜 칸·보험 설명이 뒷면 맨 위 "앞면에서 줄인 내용 · 조건 대조" 표로 옮겨 갔다(설계 `docs/design/2026-11-14-result-paper-simplify-spec.md` 3·4절). 기준선 대조(`compare_facts`: 숫자·금액·날짜·전화 토큰과 제도·접수처 이름)는 27건 모두 빠진 사실 0, 새 숫자 0이다.

| 시험 | 이전 → 이후 | 구분 | 근거 |
|---|---|---|---|
| tests/golden/test_golden.py `check_case` | 줄에 안 매인 항목(보험·첫 행동·배지 달)의 must_include를 "앞면 글" → "앞면 글 + 뒷면 '앞면에서 줄인 내용' 표" 에서 찾는다 | 시험 규칙(JSON 그대로) | 보험 줄의 "재해보험·수입안정보험 둘 중 하나만", 확인 달("8월 확인"), 먼저 하실 일의 부연("45만"·"20만"), 빈 종이 달력("3월")이 앞면에서 뒷면 표로 이동. 15건(B01·B02·B06·B07·B12·B13·G13·P1~P5·T1·T2 등)이 이 이동 때문에만 걸렸다. 사실이 아니라 위치 변경 |
| tests/agents/test_counsel_scripted.py | 설명 문장 전부가 앞면 `p.narr`에 → 할 일·지원 첫 문장만 앞면, 나머지(보험)는 종이 어딘가(뒷면)에 | 시험 기대 | 설계 3절: "한마디로" 칸에는 AI 문장 최대 둘(할 일 첫 문장, 지원 첫 문장). 보험 문장은 뒷면 |
| tests/ui/test_narr_zone.py | "support 문장은 그 제도가 든 구역(C/D) 머리 아래" → "문장은 한마디로 칸(할 일 → 지원 차례), 보험은 뒷면" | 시험 교체 | C/D 구역 머리가 없어지고 가실 곳 카드로 바뀜(`render._support_zone` 삭제) |
| tests/ui/test_render.py | 달력 세 칸 `.front .cal .c` → 뒷면 "다음에 오실 때" 행 세 줄 · 설명 문장 3개 → 앞면 1~2개 + 뒷면 · 카드 수·한마디로 칸·넘침(설명 문장 두 줄씩) 시험 추가 | 시험 기대 | 달력 칸은 뒷면 표로(설계 3절 "날짜 네모 셋은 뒷면"). 카드 상한 셋·한 장 규칙 |
| tests/ui/test_preflight.py, tests/preflight_support.py, tests/fixtures/preflight/*.html | 작년 기준 배지 없음(09): 항목 배지 지우기 → 머리의 "○년 기준 · ○년 공고 전" 배지 지우기 + 앞면에 작년 기준 제도 숫자 심기. 11개 픽스처 다시 만듦 | 시험 입력·픽스처 | PRIOR_NO_BADGE: 앞면은 항목마다가 아니라 머리에 한 번(설계 3절). 뒷면 숫자 근거 칸의 행별 배지 규칙은 그대로 |
| tests/unit/test_sheet_cards.py (새) | — | 새 시험 | 카드 묶음 층: 22건 + 재생 5건 전부에서 (가) 줄이 하나도 안 빠짐 (나) 카드 셋 이하 (다) 먼저 하실 일이 첫 카드 (라) 결론 한 줄이 설계 2절 규칙 |

코드 쪽 고침(기대값이 아니라 뒷면 글): 가격 판정 근거 줄의 영문 코드 `NOT_APPLICABLE` → "해당 없음", 조건표 성별 코드 `M`/`F` → "남"/"여", 숫자 근거 칸의 접수처 영문 코드(`emd_home` 등)와 출처 칸의 `supports:…@2026` → 쉬운 이름(`sheet_back.BACK_STATUS`, `render.plain_source`). 골든 기대값에는 이 코드를 요구하는 항목이 없다.

## K. 2026-11-15 표현 정리(말끝 해요체 · 때 글을 기준일에서 본 말로 · 같은 것은 한 이름으로): 글자만 바뀐 기대값

사실(숫자·금액·날짜·전화·제도 이름·접수처)은 하나도 바꾸지 않았다. 아래 두 글자열만 JSON 의 기대 글을 새 글에 맞췄다.

| 사례 | 이전 → 이후 | 구분 | 근거 |
|---|---|---|---|
| T1·T2 빈 종이 제목(`front_top_must_include`·`kept_money` 근처 두 곳씩) | "다 챙기고 계십니다" → "다 챙기고 계세요" | 기대값 글(뜻 같음) | 합쇼체를 해요체로(부장 판정). `sheet_rules.EMPTY_TITLE` |
| P1-K2 온주 보험 줄 `must_include` | "대상 아님" → "대상이 아니에요" | 기대값 글(뜻 같음) | 같은 줄 `수입안정보험은 대상이 아니에요`(이전 "수입안정보험 대상 아님·재해보험만"). 수입안정보험을 못 든다는 사실은 그대로 |

그 밖에 때를 말하는 줄 글(예: "예년 3월" → "내년 3월쯤", "상시 신청" → "언제든 신청할 수 있어요")은 골든 JSON 이 요구하지 않아 기대값 변경이 없다. 달 숫자는 그대로다.

## 종이 앞면 두 구역 (2026-11-15, 사장 지시: 지금 할 수 있는 것과 내년 것을 섞지 않는다)

종이 앞면을 결과 화면과 같은 「지금 하실 일」(가실 곳 상자) · 「앞으로 신청할 것」(달 순서 목록) 두 구역으로 바꿨다. **금액·자격·날짜 기대값은 하나도 바뀌지 않았다**(골든 JSON 그대로, 시험 47건 통과).
바뀐 것은 앞면의 순서·번호·이름표뿐이다.

| 항목 | 이전 → 이후 | 구분 | 근거 |
|---|---|---|---|
| 어댑터 `build_paper` | `render_sheet(...)`에 `programs`를 안 넘김 → `programs=bundle.programs`를 넘김 | 어댑터 | 앱(`routes_counsel._render`)은 늘 표를 넘긴다. 표가 없으면 '지금 신청할 수 있는 줄'을 못 가려 앞으로 구역이 전부가 된다. 기대 글은 그대로 통과 |
| 앞면 상자 | 가실 곳 상자 안에 오늘 할 일과 내년 지원이 섞임, 번호 ①②③ 이 줄 수 한도로 잘림 → 지금 구역 줄만 든 상자, 번호는 화면 지금 구역 1부터 | 코드 | 화면 `split_screen`을 종이가 그대로 씀 |
| 상자 딱지 | "먼저 하실 일"·"언제든 신청할 수 있어요" → 없음(급한 줄은 마감 날짜 알약) | 코드 | 화면과 같게(구역 제목이 그 뜻) |
| 그 밖에 | 알아 두세요의 "그 밖에: N …" 줄 → 앞으로 구역이 대신함 | 코드 | 앞면에 실린 지원을 또 말하지 않는다 |
| 뒷면 번호 | 상자에 없는 줄은 "그 밖에" → "앞으로"(같이 확인해요는 그 줄의 때) | 코드 | 번호가 없는 앞으로 줄은 지원 이름과 때로 가리킴 |
| 급한 줄 | 날짜 글 "11월 13일까지 · 5일 남음" → "11월 13일까지"(알약) | 코드 | 종이는 며칠 뒤에도 읽는다 |

## 종이 앞면 검증 손질 (2026-11-16)

검증 사원 둘의 지적을 고쳤다. **금액·자격·날짜 기대값은 바뀌지 않았다**(골든 JSON 그대로).
| 항목 | 이전 → 이후 | 구분 | 근거 |
|---|---|---|---|
| 앞으로 구역 줄 | 덧말 → 줄 순으로만 양보 → 덧말 → 곳 → 줄(못 실은 줄은 달·이름·금액 요약) 순 | 코드 | 지원이 많은 농가도 앞면에서 달·이름·금액이 보이게 |
| 못 실은 줄의 달 | '내년 8~10월'을 '10월'로 → '8~10월' | 코드 | 화면·뒷면과 같은 구간 |
| 알아 두세요 | 영농도우미·재해 피해·올해는 어려운 것 줄이 앞면에 있었음 → 화면과 같은 줄(가실 때·끊기지 않게)만 | 코드 | 화면에 없는 줄은 뒷면(알아 두세요·올해는 어려워요)에 이미 있다 |
| 뒷면 같이 확인 표 | 자조금 가입 확인 줄 '이것을 하시면 알아볼 수 있는 지원 N가지' → '이것을 해야 ○○을 받을 수 있어요'(이름 전부) | 코드 | 화면과 같은 말 |
| 빈 종이 앞면 | 「먼저 가실 곳」 딱지·굵은 테두리, 구역 제목 없음 → 두 구역 제목(끊기지 않게 할 일 = 지금 하실 일, 다시 가입할 보험 = 앞으로 신청할 것), 딱지·굵은 테두리 없음 | 코드 | 화면과 같은 구역 이름 |
| 높이 어림 | 화면이 다시 쓴 줄(이것을 해야 ○○을…)을 안 세던 것을 실제 그려지는 줄로 센다 | 코드 | 실측 대조(B12 상자 18px 작게 잡히던 것) |

## 종이 2차 손질 (2026-11-16, 부장 결정: 달력이 앞면에 반드시 보이게)

앞으로 신청할 것이 지원 많은 농가에서 "외 N가지 · 뒷면에 있어요" 한 줄로 사라지던 것을 고쳤다. **금액·자격·날짜 기대값은 하나도 바뀌지 않았다**(골든 JSON·기대 글 그대로, 골든 시험 통과). 바뀐 것은 앞면의 모양과 뒷면의 칸 구성뿐이다.

| 항목 | 이전 → 이후 | 구분 | 근거 |
|---|---|---|---|
| 앞으로 구역 양보 차례 | 덧말 → 곳 → 줄(먼 달부터) → 상자 뒷줄 → 달마다 한 줄로 접기(FOLD, 달·이름·금액) → 접은 줄 14pt(FOLD_SM) → (마지막) 가장 먼 달부터 "외 ○가지(○월)" | 코드 | 골든 22건 + 재생 5건에서 마지막 단계는 골든 P5(다섯 달 중 두 달만 실림)와 재생 P5(네 달) 두 건이다("재생 P5 한 건뿐"은 사실과 달랐다. 2026-11-16 검증 지적, 아래 3차에서 이름·달·금액을 적도록 고침) |
| 상자 덧말 | 늘 실림 → 자리가 모자라면 앞으로 구역보다 먼저 뒷면으로(뒷면 표에는 그대로) | 코드 | 알아 두세요 → 상자 덧말 → 앞으로 구역 순으로 양보 |
| 알아 두세요 | 세 줄 한도 → 반드시 두 줄("같이 확인해요"·"가실 때"), 나머지(끊기지 않게·접수 중 공고·서류)는 자리가 남을 때만, 못 실으면 "알아 두실 것이 N가지 더 있어요 · 뒷면에 있어요" | 코드 | 알아 두세요가 먼저 양보 |
| AI 한마디 자리 | 앞으로 구역을 정할 때 문장 한 줄 자리를 상수로 남김 → 남기지 않음(상자·앞으로 구역을 정한 뒤 남는 자리에 실음) | 코드 | 달력이 먼저(문장 없는 농가에서 123px 이 비던 것) |
| 때 칸 | "내년 4월 27일부터 가입할 수 있어요"가 네다섯 줄로 꺾임 → 때 칸에는 "내년 4월 27일부터", "가입할 수 있어요"는 줄의 덧말 | 코드 | 때 칸 40mm |
| 곳 이름 | "읍·면사무소, 동 주민센터"가 낱말 하나만 다음 줄로 → 한 덩어리로 내려감 | 코드(CSS) | |
| 급한 줄 알약 | "11월 13일까지" → 마감이 기준일이면 "오늘까지(11월 13일)" | 코드 | 오늘이 마감임이 보이고 며칠 뒤에도 날짜가 남는다 |
| 뒷면 입력 요약 | 같이 확인해요 표가 자리를 가져가면 입력 요약이 먼저 빠짐(재생 P1·P2·P3·P5) → 맨 나중에 양보(전 사례에 있다) | 코드 | 창구 직원이 이 종이만 보고 어떤 농가인지 알아야 한다 |
| 뒷면 표 글자 | 7.5pt 고정 → 자리가 남으면 8·8.5·9pt | 코드 | 자리가 모자란 사례만 7.5pt |
| 높이 어림 | 앞으로 구역 줄·상자·접은 줄을 글자별 실측 폭으로 다시 맞춤(앞면 어림 − 실측 ±3px), 앞면 한도 37.1 → 37.0줄, 뒷면 한도 960 → 975px(칸 안 줄 꺾임을 글자별 폭으로 센 뒤) | 코드 | 남는 여백 40px 이상 + 쓸 수 있는데 안 쓴 자리가 늘지 않게 |
| 이미 다 받는 농가 결과 화면 | 「지금 하실 일」 안에 "내년 4월 27일부터 가입할 수 있어요"(다시 가입할 보험) → 지금(끊기지 않게 할 일) / 앞으로(다시 가입할 보험, 달 목록) 두 구역 | 코드(화면) | 종이와 같은 나누기. 다른 농가의 화면은 전후 HTML 이 같다 |

## 종이 3차 손질 (2026-11-16, 검증 사원 지적 반영)

**금액·자격·날짜 기대값은 바뀌지 않았다**(골든 JSON·기대 글 그대로). 바뀐 것은 앞면 모양뿐이다.

| 항목 | 이전 → 이후 | 구분 | 근거 |
|---|---|---|---|
| 못 실은 앞으로 줄 | "외 ○가지(○월) · 뒷면에 있어요" → "외 ○가지: 5월 토양생태환경보전 약 308만~322만 원 · 8월 브로콜리 농작물보험 · 제주형 가격안정관리제(브로콜리) · 뒷면에 있어요"(달·이름·금액이 앞면에 있다) | 코드 | 골든 P5 에서 가장 큰 돈(5월)이 앞면에서 안 보이던 것, 재생 P5 의 가격안정관리제 이름이 앞면에 없던 것 |
| 앞으로 구역 단계 | 이웃한 두 모양 사이에 한 달씩 올리는 중간 모양 추가(가까운 달부터 덧말·곳·펼친 줄 복원) | 코드 | 모든 달을 한꺼번에 올려 60~110px 이 남던 것(B05 94→45, B06 181→64, 골든 P3 108→50 등) |
| 앞면 아래 여백 한도 | 40px → 35px(한도 37.0 → 37.2줄) | 코드 | 한 단계 더 풍부한 모양이 실측 37~41px 이 남는데 어림 때문에 못 실리던 것 |
| 지금 접수 중인 공고 | 알아 두세요의 한 줄("공고 ○개가 맞을 수 있어요 · 뒷면에 있어요") → 자리가 있으면 「지금 하실 일」 끝에 "공고 이름 · 11월 23일까지"(화면 상자와 같은 공고·날짜). 자리가 없으면 전과 같다 | 코드 | 마감이 10일 남은 공고가 앞면에서 안 보이던 것(재생 P1) |



## 종이 앞면 = 화면 표 그대로 (2026-11-17, 사장 지시: 인쇄는 지금 최종 결과와 같은 내용이 복사되면 좋겠다)

**금액·자격·날짜 기대값과 골든 JSON은 하나도 바뀌지 않았다.** 바뀐 것은 앞면 모양과 뒷면 이름표뿐이다.

| 항목 | 이전 → 이후 | 구분 | 근거 |
|---|---|---|---|
| 앞면 줄임 | 달마다 한 줄로 접기 · "외 N가지 · 뒷면에 있어요" · 곳·덧말 빼기 · 상자 뒷줄 접기 → 모두 없앰. 화면 표의 줄·덧말·곳이 앞면에 전부 있다 | 코드 | 화면과 같은 글 |
| 한 쪽에 안 들어갈 때 | 줄이기 → 글자 단계(지원 이름·설명 16·14pt → 15·13 → 14·12), 그래도 넘치면 표가 다음 쪽으로 이어짐(이어진 쪽 머리 "제주 농돈 · (이어서)") | 코드 | 내용을 빼지 않는다. 앞면이 두 쪽이어도 인쇄 전 점검(OVERFLOW)은 쪽마다 한 쪽 한도로 본다 |
| 알아 두세요 | 자리가 남을 때만 항목을 싣고 "알아 두실 것이 N가지 더 있어요" → 화면과 같이 전부 | 코드 | 화면과 같은 글 |
| AI가 읽은 공고 줄 | 이름 · 마감 날짜만 → 화면과 같이 왜 맞는지 · 안내 · 물어볼 것 · "조건은 창구에서 확인하세요"(공고 자세히 보기 단추만 뺌) | 코드 | 화면과 같은 글 |
| 번호 | 앞면 가실 곳 번호 동그라미와 뒷면 "앞면 번호" 칸 → 번호 없음. 뒷면 대조표·같이 확인해요는 가실 곳 짧은 이름(농협·농관원 …)·앞으로·달로 가리킴 | 코드 | 번호를 없앰 |
| 뒷면 표 이름 | "앞면에서 줄인 내용 · 조건 확인" → "앞면 표의 조건 확인 · 근거"(줄인 내용이 없어졌다). `test_golden._reduced` 가 이 이름을 찾는다 | 코드(시험) | 앞면에 없는 줄이 없다 |
| 결론 칸 색 | 진한 청록 바탕 + 흰 글자 → 감귤 주황 바탕 + 먹색 글자(화면 결론 띠와 같다) | 코드(CSS) | |

## 종이 뒷면을 없앰 (2026-11-18, 사장 결정: 종이는 한 장 한 면)

**금액·자격·날짜 기대값과 골든 JSON은 하나도 바뀌지 않았다.** 바뀐 것은 시험이 글을 찾는 곳뿐이다.

| 항목 | 이전 → 이후 | 구분 | 근거 |
|---|---|---|---|
| 뒷면 글을 보던 기대(`also` · `"where": "back"` · `"section": "back"` · 줄에 안 매인 항목) | 종이 뒷면 글 → 종이 글 + 결과 화면 '직원용 · 자세한 내용 보기' 창 글·종이에 싣지 않는 줄을 담은 `Sheet.front`·`Sheet.back`·`FactSheet.facts`·빈 종이 달력 세 칸(`test_golden.staff_text`) | 코드(시험) | 담당자용 내용은 화면 직원용 창으로 옮겼다. 기대 글이 사라지지 않았는지는 그 자료에서 본다 |
| `must_not_print` · `must_not_print_front` | 종이 전체(앞뒤) → 종이 글만(뒷면이 없으니 둘이 같다) | 코드(시험) | 직원용 창에는 '뺀 것' 이름이 있어도 된다 |
| 줄에 안 매인 항목의 찾는 곳 | 앞면 + 뒷면 '앞면 표의 조건 확인 · 근거' 표(`_reduced`) → 종이 글 + staff_text | 코드(시험) | 뒷면 표가 없다 |
| 뒷면 '못 실은 것' 건너뜀(`detail_left_out`) | 뒷면 칸이 빠졌다고 종이가 말하면 건너뜀 → 없앰 | 코드(시험) | 뒷면이 없다 |
| 인쇄 전 검사 | HEADER3·NO_FINGERPRINT·BACK_OVERFLOW(뒷면 검사) → 없앰. 데이터 기준일·계산 지문은 화면 직원용 창 맨 아래 | 코드 | 뒷면이 없다 |
