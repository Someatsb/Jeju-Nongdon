# 허브 가격 민감도 시험 결과 (골든 14건, Task 34)

실행: `python -X utf8 scripts/sensitivity_prices.py --golden` (기본 사례 = P1~P5, T1, T2, B01~B05 + 시즌 중간 G13·G14).
질문: 허브 1361 가격이 ±10%·±20% 틀렸다면 종이의 어느 시세 줄이 뒤집히는가? 배수 0.8·0.9·1.0·1.1·1.2를 곱해 같은 판정 정의로 다시 계산하고 1.0과 다른 줄을 보고한다.

## 출력(그대로)

```
[P1] 감귤_노지 2026-11-13 기준값 {'PRICE_STAB': 'NO_DATA', 'LOGISTICS': 'OFF', 'BUYOUT': 'NOT_APPLIED'} | 뒤집힘 없음
[P2] 당근 2026-11-13 기준값 {'PRICE_STAB': 'NO_DATA', 'LOGISTICS': 'OFF', 'BUYOUT': 'TOO_EARLY'} | 뒤집힘 없음
[P3] 마늘 2026-11-13 기준값 {'PRICE_STAB': 'PRE_SEASON', 'LOGISTICS': 'PRE_SEASON', 'BUYOUT': 'NOT_APPLIED'} | 뒤집힘 없음
[P4] 양배추 2026-11-13 기준값 {'PRICE_STAB': 'PRE_SEASON', 'LOGISTICS': 'PRE_SEASON', 'BUYOUT': 'TOO_EARLY'} | 뒤집힘 없음
[P5] 브로콜리 2026-11-13 기준값 {'PRICE_STAB': 'NO_SOURCE', 'LOGISTICS': 'NO_SOURCE', 'BUYOUT': 'NOT_APPLIED'} | 뒤집힘 없음
[T1] 감귤_노지 2026-11-13 기준값 {'PRICE_STAB': 'NO_DATA', 'LOGISTICS': 'OFF', 'BUYOUT': 'NOT_APPLIED'} | 뒤집힘 없음
[T2] 당근 2026-11-13 기준값 {'PRICE_STAB': 'NO_DATA', 'LOGISTICS': 'OFF', 'BUYOUT': 'TOO_EARLY'} | 뒤집힘 없음
[B01] 양배추 2026-11-13 기준값 {'PRICE_STAB': 'PRE_SEASON', 'LOGISTICS': 'PRE_SEASON', 'BUYOUT': 'TOO_EARLY'} | 뒤집힘 없음
[B02] 양배추 2026-11-13 기준값 {'PRICE_STAB': 'PRE_SEASON', 'LOGISTICS': 'PRE_SEASON', 'BUYOUT': 'TOO_EARLY'} | 뒤집힘 없음
[B03] 감귤_노지 2026-11-13 기준값 {'PRICE_STAB': 'NO_DATA', 'LOGISTICS': 'OFF', 'BUYOUT': 'NOT_APPLIED'} | 뒤집힘 없음
[B04] 당근 2026-11-13 기준값 {'PRICE_STAB': 'IN_PROGRESS_MET*', 'LOGISTICS': 'OFF', 'BUYOUT': 'TOO_EARLY'} | 뒤집힘 없음
[B05] 당근 2026-11-13 기준값 {'PRICE_STAB': 'NO_DATA', 'LOGISTICS': 'OFF', 'BUYOUT': 'TOO_EARLY'} | 뒤집힘 없음
[G13] 당근 2026-01-15 기준값 {'PRICE_STAB': 'NEAR', 'LOGISTICS': 'OFF', 'BUYOUT': 'MET'} | PRICE_STAB: ×0.8→MET, ×1.1→NOT_MET, ×1.2→NOT_MET
[G14] 양배추 2026-03-15 기준값 {'PRICE_STAB': 'MET', 'LOGISTICS': 'NEAR', 'BUYOUT': 'MET'} | PRICE_STAB: ×1.1→NEAR, ×1.2→NEAR; LOGISTICS: ×0.8→BELOW, ×0.9→BELOW
```

## 읽는 법

- 기준일 2026-11-13의 12건은 모두 "뒤집힘 없음"이다. 11월에는 당근·양배추 반월 판정이 PRE_SEASON·NO_DATA(거래일 부족)이거나 합성 평균(B04)이라 가격 오차가 판정을 못 움직인다. 그래서 시즌 중간 기준일 두 건을 더했다(B 제안).
- **G13 (당근 2026-01-15)**: 기준값 PRICE_STAB = NEAR. ×0.8 → MET(가격이 20% 낮았다면 "열림" 쪽), ×1.1·×1.2 → NOT_MET(가격이 10% 이상 높았다면 "아직"). 틀린 "열림"과 틀린 "해당 없음"이 모두 ±10~20%에서 나온다는 뜻이고, NEAR(근처 — 농협 확인) 구간이 비대칭 오류를 막는 완충이다.
- **G14 (양배추 2026-03-15)**: PRICE_STAB = MET(평균 656.4원 < 기준가 723 × 0.911 = 658.7). ×1.1·×1.2 → NEAR로 내려앉는다(가격이 10% 높았다면 MET이 아니라 근처). LOGISTICS = NEAR가 ×0.8·×0.9에서 BELOW로 뒤집힌다.
- 뒤집힘 ≥ 1 확인: G13 1건(3개 배수), G14 2건(PRICE_STAB 2배수 · LOGISTICS 2배수).
- 사례의 엔진 기대값은 `tests/golden/cases/G13.json`·`G14.json`(CHANGELOG D절). 이 스크립트는 엔진과 별개 코드로 같은 판정을 계산하므로 평균·판정이 엔진과 같다는 것(1163.6원 NEAR / 656.4원 MET)이 서로 대조가 된다.
