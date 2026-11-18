# data/tables 글자 변경 기록

## 2026-11-08 chore: data notes

| 파일 | 행 | 이전 → 이후 | 이유 |
|---|---|---|---|
| crops.csv | 당근 notes | "1361 averagePrice는 행 단순평균이라 쓰지 말고 금액/거래량 사용" → 판정 입력은 1361 averagePrice 반월 거래량 가중(코드 기준), 1362 가락은 후보(미적용). judge_source 값(hub1362_garak)은 그대로 | 코드(triggers.py, params stab_price_basis)와 글이 반대였음. judge_source는 스키마 검증·감귤 연결에 쓰이므로 값 유지 |
| crops.csv | 양배추 notes | 재현 실패 문구만 → 판정 입력은 1361 반월 가중, 1362 가락 후보(미적용) 추가 | 같은 이유 |
| params_by_season.csv | 2025-26 당근 stab_band_lo method | 2017-01~2021-08 → 2017-01~2021-03 | agg_869_ratio.csv 실제 범위(마지막 반월 2021-03-16~31, 42행) |
| inbox_k_rows.csv | NHIS-FARMER-SUPPORT 2행 notes | "사장 §5-2 결정 대기" → "사장 결정 2026-11-08: 건보료 지원은 범위 안(IN)" | 사장 결정 반영 |
| inbox_k_rows.csv | JEJU-HAPPY-TAXI 2행 notes | "사장 §5-2 결정 대기" → "사장 결정 2026-11-08: 행복택시는 범위 밖(영구 hold)" | 사장 결정 반영 |


보류: interventions.csv의 근거 URL 없는 3행(2017-18 월동무, 2018-19 양배추, 2020-21 월동무)은 바꾸지 않았다. confirmed를 내리면 ISOLATION_HISTORY 횟수가 바뀌어 지문·재생 테스트가 깨진다. 사장·부서장 결정 필요.
