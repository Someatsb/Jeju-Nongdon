# 골든 케이스

`cases/*.json`은 골든 사양(golden-spec/2) 22건이다: P1~P5(페르소나), T1·T2(빈 종이), B01~B13(경계값), G13·G14(시즌 중간 기준일).
`test_golden.py`가 22건을 모두 돌린다: 프로필 → `build_fact_sheet` → `build_sheet` → `render_sheet`(설명 문장 없음)
→ `preflight == []` → 기대값 비교. `golden_adapter.py`가 사양의 1라운드 필드명을 `FarmProfile`로 옮긴다
(대응표는 `tests/conftest.py` 머리가 정본이고 어댑터 docstring에 규칙을 적었다). `make_samples.py`도 이 어댑터를 쓴다.

## 골든 12

P1, P2, P3, P4, P5, T1, T2 + B02(나이 상한), B04(가격 발동), B05(재해), B06(면적 경계 998㎡), B12(계통·자조금).
브리프의 G01~G12 이름은 쓰지 않고 기존 파일 이름을 그대로 쓴다. 나머지 B 케이스(B01·B03·B07~B11·B13)도 같이 돌지만 12에는 세지 않는다.

## 기대값을 바꿀 때

기대값(JSON)은 사양의 예시이고 정본은 사양(설계 v2·12-B)이다. 바꾸려면 `CHANGELOG.md`에 사례 번호·이전·이후 값·근거를 적는다.
못 맞춘 사례는 `test_golden.py`의 `XFAIL_TASK34`에 올려 xfail(strict=False)로 표시하고 `FAILURES.md` "미해결"에 정확한 이유를 적는다. 지금은 비어 있다(22건 통과).
`key_lines`·`first_actions`·`insurance`는 앞면 글에서만 찾는다(`program_key` 항목은 그 줄 안). 담당자용 글(2026-11-18 전에는 종이 뒷면)로 맞추려면 항목에 `"where": "back"`을 적는다: 종이에 뒷면이 없어 종이 글 + 결과 화면 직원용 창 글(`test_golden.staff_text`)에서 찾는다.
사례마다 `golden_adapter.case_env`가 `as_of`로 표·스냅샷을 읽고 `fixture.price_override`(합성 반월 평균)·`jasdc: saved_YYYYMMDD`를 입힌다.
`G13`(2026-01-15 당근)·`G14`(2026-03-15 양배추)는 시즌 중간 기준일이라 가격 민감도 시험(`scripts/sensitivity_prices.py --golden`, 결과는 `SENSITIVITY.md`)에서 판정이 뒤집힌다.
`run_tests.bat`은 `tests/REPORT.txt`에 "golden N/12 passed"를 적는다(XFAIL은 통과로 세지 않는다).

## 어댑터 가정 (`golden_adapter.py`)

사양의 1라운드 필드는 `FarmProfile`에 일대일로 없어 아래처럼 옮긴다. 어긋남 원인을 가릴 때 먼저 의심할 곳이다
(이 표는 설명일 뿐 어댑터 자체는 Task 34 쪽에서 맞춘다).

| FarmProfile 칸 | 사양 값 | 옮기는 규칙 (가정) |
|---|---|---|
| `sales_channel` | `coop_shipping`, `field_sold_contract` | 계통 출하 Y면 `coop`, 아니고 밭떼기 Y면 `field_contract_done`, 둘 다 아니면 `unknown`(`direct`는 쓰지 않음) |
| `land_tenure` | `owns_farmland`, `owned_area_ge_15500m2` | 땅 없음이면 `rent_all`, 있고 1.55ha 이상 Y면 `own_part`, 그 밖에는 `own_all` |
| `land_held_2y` | `farmland_owned_years` | 땅이 있을 때만: 햇수가 없거나 2 이상이면 True, 땅이 없으면 None |
| `owned_over_4700py` | `owned_area_ge_15500m2`, 총면적 | 땅이 있고 총면적이 1,000~9,554㎡일 때만 사양 값(Y면 True), 아니면 None |
| `mgmt_status` | `mgmt_registered`, `mgmt_years` | N이면 `none`, Y이고 2년 이상이면 `over_2y`, 2년 미만이면 `under_2y` |
| `spouse` | `spouse_status` | registered는 그대로, unregistered는 `cofarming_unregistered`, 그 밖에는 `none` |
| `selfpay_fund` | `selfpay_fund_member` | Y는 `paid`, N은 `not_paid`, `?`는 `unknown`, 자조금 품목 아닌 작물은 `na` |
| `ins_disaster` / `ins_safety` | `insurance_enrolled` | disaster면 모든 작물 True. safety면 본인, 배우자 등록이면 배우자까지 |
| `emd_code` | `eupmyeon`, `region` | 읍면이 없으면 행정시 이름(제주시) |
| 버림 | `coop_member`, `offfarm_income_band`, `disaster_end_date`, `flags` | FarmProfile에 칸이 없다 |
