# 골든 케이스 불일치 목록 (Task 27 → Task 34 결과)

Task 27이 적은 19건(골든 12 중 11건)의 어긋남은 Task 34에서 모두 닫았다. 사례별 사유는 `CHANGELOG.md`(기대값 오류 / 코드 오류, 이전·이후 값, 근거).
지금 `XFAIL_TASK34`는 비어 있다: 골든 12 모두와 나머지 B 8건, 시즌 중간 G13·G14까지 22건이 통과한다
(`pytest tests/golden -W error`: 사례당 두 시험 = 인쇄 전 검사 + 기대값 비교, 44 passed).

비교 범위(검토 1차 이후): `key_lines`·`first_actions`·`insurance`는 앞면 글에서만, `program_key`가 있는 항목은 그 줄 안에서만 찾는다. 뒷면 글은 항목에 `"where": "back"`(또는 `"section": "back"`)을 적어야 인정한다. `also`·고정 줄·`must_not_print`는 종이 전체.
`must_not_include`는 `program_key`로 줄을 찾으면 그 줄 안에서만 본다.

## 미해결 (러너가 비교하지 않는 기대 필드 · 아직 없는 기능)

골든 JSON에는 러너가 글자로 비교하지 않는 필드(`status`, `amount.kind`, `rank`, `banners` 등)가 있다. 아래는 그중 엔진과 다르다고 알려진 것이다.
시험은 통과하지만 기대값 문서로서 거짓이 되지 않도록 여기에 적는다. (P1·P5 "전환하면 ○만 원 더"는 검토 1차에서 구현해 이 표에서 뺐다.)

| 사례 | 필드 | 기대 | 현재 | 이유 |
|---|---|---|---|---|
| B03 | `banners` external_refresh "인터넷 없음" | 외부 갱신 실패 띠 | 없음 | `Header.refresh_ok`는 모델·`base.html`에 있으나 `pipeline.py`가 항상 None을 넣고 `RefreshReport`를 저장하지 않는다. 세션 단위 갱신 상태를 저장해 `build_fact_sheet(..., refresh_ok=)`로 넘기고 `_stale_notes`에 False 문구를 더해야 한다 — Task 26/28 후속. 핵심 경고(감귤 4월 6일 현재 값 아님)는 이미 찍힌다 |
| P3 | `banners` hub1361:마늘 "2026년 2월 26일 현재 값 아님" | 마늘 시세 STALE 띠 | 없음 | 스냅샷에는 마늘 시리즈가 있다(마지막 날 2026-02-26, `judge=True`). 그러나 기준일 11월은 마늘 판정 달이 아니라 OUT_OF_SEASON이 STALE보다 먼저 판정되어(`triggers._price_rule`) STALE 판정이 없고, 마늘 시세는 인쇄·사용되지 않아 띠가 붙일 대상이 없다. 필요하면 `render._stale_notes`가 농가 작물의 `snap.prices` 마지막 날을 직접 보게 할 수 있다 |
| 여러 사례 | `insurance[].reasons` (`needs:selfpay_fund+경작신고` 등) | 보험 상품의 자조금·경작신고 요건 | 없음 | `insurance.csv`에 그 요건 칸이 비어 있다(표 근거 없음) |
| P2·P3·P5 | 배우자 경영체 등록 unlock의 `status_after: CHECK`, 2년 계속 등록의 사람 단위 | 사람 단위 판정 | 배우자 몫을 행복이용권·2인 농민수당 차액으로만 계산 | 배우자 본인의 거주·소득·건보 조건은 입력에 없어 CHECK 꼬리표로만 남김(`spouse_birth_year`·`spouse_sex` 선택 입력) |

## 어댑터가 모르는 필드(매핑 없음)

`coop_member`, `offfarm_income_band`, `disaster_end_date`, `flags` 목록, `farmland_owned_years`·`jeju_residence_years`의 숫자. `CHANGELOG.md` A절.
