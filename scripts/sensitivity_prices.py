# -*- coding: utf-8 -*-
"""
허브 가격 민감도 시험 (사원 B 초안, 2026-11-07) — 설계 문서 v2 §12-A (6) ③

질문: 허브 1361 가격이 ±10%·±20% 틀렸다면 종이의 어느 시세 줄이 뒤집히는가?
방법: 1361 averagePrice에 배수(0.8, 0.9, 1.0, 1.1, 1.2)를 곱해 11-13판과 같은 판정 정의로 다시 계산하고,
      배수 1.0 결과와 다른 줄을 뒤집힘으로 보고한다.

판정 정의(11-13판, params_by_season.csv에서 읽음)
  PRICE_STAB  반월(1~15·16~말) 1361 averagePrice 거래량 가중 평균 p
              p < 기준가 × band_lo → MET(아래) / p ≥ 기준가 × band_hi → NOT_MET(위) / 사이 → NEAR(근처, 농협 확인)
              진행 중 반월은 IN_PROGRESS_* (같은 분류에 접두어), 자료 5일 미만은 NO_DATA
  LOGISTICS   이번 달 1361 거래량 가중 월평균 m. 역산 구간 (lo, hi]: m ≤ lo → BELOW / m > hi → ABOVE / 사이 → NEAR.
              구간이 없으면 OFF(판정 끔)
  BUYOUT      12/1(11월이면 11/1)부터 기준일까지 누적 가중 평균의 전년 같은 기간 대비. 14일 미만이면 TOO_EARLY.
              ≤ −30%면 MET. 배수는 올해 값에만 곱한다(양쪽에 곱하면 비율이 그대로라 시험이 안 됨)

두 가지 모드
  --golden  tests/golden/cases/의 사례(기본: P1~P5, T1, T2, B01~B05 + 시즌 중간 G13·G14 = 14건. 없는 파일은 '없음'으로 보고)
  --sweep   2025-26 시즌의 모든 반월 끝날(as_of)에 대해 같은 시험 → "반월 n개 중 ±10%에서 뒤집히는 판정 m개"

엔진 연결(코어가 생기면): 이 파일의 judge_*()를 core의 compute(profile, as_of, data)로 바꾸고,
골든의 fixture.price_override와 같은 방식으로 배수 적용 데이터를 넘기면 된다. 출력 형식은 그대로 쓴다.
표준 라이브러리만 사용.
"""
import sys, os, csv, json, glob, argparse, collections, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = os.path.join(ROOT, "data", "snapshot", "hub_1361.csv")
TABLES = os.path.join(ROOT, "data", "tables")
GOLDEN = os.path.join(ROOT, "tests", "golden", "cases")
MULTS = (0.8, 0.9, 1.0, 1.1, 1.2)
MIN_DAYS = 5   # 반월 판정 최소 거래일(--min-days). 골든 P2·T2는 3일치로 판정을 기대 → 결정 필요
GOLDEN_KEY_TO_CROP = {"노지온주": "감귤_노지", "만감류": "감귤_만감"}
DEFAULT_CASES = ["P1", "P2", "P3", "P4", "P5", "T1", "T2", "B01", "B02", "B03", "B04", "B05", "G13", "G14"]  # 설계 v2 §12-A(1) 골든 12 + 시즌 중간 2(Task 34)


def load_tables():
    with open(os.path.join(TABLES, "crops.csv"), encoding="utf-8-sig") as f:
        crops = {r["crop_code"]: r for r in csv.DictReader(f)}
    params = collections.defaultdict(dict)
    with open(os.path.join(TABLES, "params_by_season.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            params[(r["season"], r["crop"])][r["param"]] = r
    return crops, params


def load_1361():
    by = collections.defaultdict(dict)
    with open(HUB, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d = dt.date(int(r["baseDate"][:4]), int(r["baseDate"][4:6]), int(r["baseDate"][6:]))
            v = float(r["transactionVolume"])
            if v > 0: by[r["cultivar"]][d] = (float(r["averagePrice"]), v)
    return by


def series(by, cultivars, mult=1.0, mult_from=None):
    out = collections.defaultdict(lambda: [0.0, 0.0])
    for cv in cultivars:
        for d, (p, v) in by.get(cv, {}).items():
            m = mult if (mult_from is None or d >= mult_from) else 1.0
            out[d][0] += p * m * v; out[d][1] += v
    return out


def wavg(S, a, b):
    ds = [d for d in S if a <= d <= b]
    V = sum(S[d][1] for d in ds)
    return (sum(S[d][0] for d in ds) / V if V else None), len(ds)


def season_of(d, months):
    first = int(months[0])
    return f"{d.year}-{str(d.year + 1)[2:]}" if d.month >= first and first >= 7 else f"{d.year - 1}-{str(d.year)[2:]}"


def param(params, crop, season, key, ok=None):
    """이번 시즌 값이 없으면 직전 시즌 값 + 배지(carried)."""
    seasons = sorted({s for (s, c) in params if c == crop and s != "-"}, reverse=True)
    for s in [season] + [x for x in seasons if x < season]:
        r = params.get((s, crop), {}).get(key)
        if r and r["value"] and (ok is None or r["status"] in ok):
            return r["value"], (s != season)
    return None, False


def half_bounds(d):
    if d.day <= 15: return d.replace(day=1), d.replace(day=15)
    nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return d.replace(day=16), nxt - dt.timedelta(days=1)


def judge_price_stab(by, crops, params, crop, asof, mult, override=None):
    c = crops.get(crop)
    if not c or c["judge_source"] == "없음": return "NO_SOURCE"
    months = [m for m in c["season_months"].split(";") if m]
    if str(asof.month) not in months: return "PRE_SEASON"
    season = season_of(asof, months)
    base, carried = param(params, crop, season, "stab_base", {"공표", "공고", "보도"})
    if base is None: return "NO_BASE"
    lo, _ = param(params, crop, season, "stab_band_lo"); hi, _ = param(params, crop, season, "stab_band_hi")
    a, b = half_bounds(asof)
    if override:
        p, n = override["avg_won_per_kg"] * mult, override["n_days_with_data"]
    else:
        S = series(by, [x for x in c["judge_cultivars"].split(";") if x], mult)
        p, n = wavg(S, a, min(b, asof))
    if p is None or n < MIN_DAYS: return "NO_DATA"
    base = float(base)
    cls = "MET" if p < base * float(lo) else ("NOT_MET" if p >= base * float(hi) else "NEAR")
    return ("IN_PROGRESS_" if asof < b else "") + cls + ("*" if carried else "")


def judge_logistics(by, crops, params, crop, asof, mult):
    c = crops.get(crop)
    if not c or c["judge_source"] == "없음": return "NO_SOURCE"
    months = [m for m in c["season_months"].split(";") if m]
    if str(asof.month) not in months: return "PRE_SEASON"
    season = season_of(asof, months)
    lo, _ = param(params, crop, season, "breakeven_lo", {"역산"}); hi, _ = param(params, crop, season, "breakeven_hi", {"역산"})
    if lo is None or hi is None: return "OFF"
    S = series(by, [x for x in c["judge_cultivars"].split(";") if x], mult)
    m, n = wavg(S, asof.replace(day=1), asof)
    if m is None or n < 5: return "NO_DATA"
    return "BELOW" if m <= float(lo) else ("ABOVE" if m > float(hi) else "NEAR")


def judge_buyout(by, crops, crop, asof, mult):
    if crop not in ("월동무", "당근", "양배추"): return "NOT_APPLIED"
    c = crops[crop]
    start = asof.replace(day=1) if asof.month == 11 else dt.date(asof.year if asof.month == 12 else asof.year - 1, 12, 1)
    if asof.month not in (11, 12, 1, 2, 3, 4, 5): return "PRE_SEASON"
    cvs = [x for x in (c["dist_cultivars"] or c["judge_cultivars"]).split(";") if x]
    S = series(by, cvs, mult, mult_from=start)
    now, n = wavg(S, start, asof)
    ly, _ = wavg(S, start.replace(year=start.year - 1), asof.replace(year=asof.year - 1))
    if now is None or ly is None or n < 10 or (asof - start).days < 14: return "TOO_EARLY"
    return "MET" if now / ly - 1 <= -0.30 else "NOT_MET"


RULES = ("PRICE_STAB", "LOGISTICS", "BUYOUT")


def run_case(by, crops, params, crop, asof, override=None):
    res = {}
    for m in MULTS:
        res[m] = dict(PRICE_STAB=judge_price_stab(by, crops, params, crop, asof, m, override),
                      LOGISTICS=judge_logistics(by, crops, params, crop, asof, m),
                      BUYOUT=judge_buyout(by, crops, crop, asof, m))
    flips = {r: {m: res[m][r] for m in MULTS if res[m][r] != res[1.0][r]} for r in RULES}
    return res, flips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", nargs="*", help="사례 ID(기본 12건)")
    ap.add_argument("--sweep", action="store_true", help="2025-26 시즌 반월 끝날 전체")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-days", type=int, default=5)
    a = ap.parse_args()
    global MIN_DAYS; MIN_DAYS = a.min_days
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    crops, params = load_tables(); by = load_1361()
    out = {"golden": [], "sweep": {}}
    if a.golden is not None or not a.sweep:
        for cid in (a.golden or DEFAULT_CASES):
            f = os.path.join(GOLDEN, f"{cid}.json")
            if not os.path.exists(f):
                out["golden"].append(dict(case=cid, status="파일 없음")); continue
            g = json.load(open(f, encoding="utf-8"))
            crop = GOLDEN_KEY_TO_CROP.get(g["profile"]["crop_key"], g["profile"]["crop_key"])
            asof = dt.date.fromisoformat(g["as_of"])
            ov = (g.get("fixture") or {}).get("price_override")
            ov = ov if ov and ov.get("rule") == "PRICE_STAB" else None
            res, flips = run_case(by, crops, params, crop, asof, ov)
            out["golden"].append(dict(case=cid, crop=crop, as_of=str(asof), base=res[1.0], flips=flips))
    if a.sweep:
        for crop, s, e in (("당근", dt.date(2025, 11, 1), dt.date(2026, 3, 31)), ("양배추", dt.date(2025, 12, 1), dt.date(2026, 5, 31)), ("월동무", dt.date(2025, 12, 1), dt.date(2026, 4, 30))):
            d = s; pts = []
            while d <= e:
                _, b = half_bounds(d); pts.append(b); d = b + dt.timedelta(days=1)
            cnt = collections.Counter(); tot = collections.Counter(); detail = []; risk = collections.Counter()
            for p in pts:
                res, flips = run_case(by, crops, params, crop, p)
                for r in RULES:
                    if res[1.0][r] in ("NOT_APPLIED", "OFF", "PRE_SEASON", "NO_SOURCE", "NO_BASE"): continue
                    tot[r] += 1
                    for m in (0.9, 1.1):
                        if m in flips[r]: cnt[(r, "±10%")] += 1; break
                    for m in (0.8, 1.2):
                        if m in flips[r]: cnt[(r, "±20%")] += 1; break
                    for m, v in flips[r].items():
                        tag = "±10%" if m in (0.9, 1.1) else "±20%"
                        if v.replace("IN_PROGRESS_", "").rstrip("*") in ("NOT_MET", "ABOVE") and res[1.0][r].replace("IN_PROGRESS_", "").rstrip("*") not in ("NOT_MET", "ABOVE"):
                            risk[(r, tag, "틀린 해당 없음 쪽")] += 1
                        if v.replace("IN_PROGRESS_", "").rstrip("*") in ("MET", "BELOW") and res[1.0][r].replace("IN_PROGRESS_", "").rstrip("*") not in ("MET", "BELOW"):
                            risk[(r, tag, "틀린 열림 쪽")] += 1
                    if flips[r]: detail.append(f"{p} {r} {res[1.0][r]} → " + ", ".join(f"×{m}:{v}" for m, v in flips[r].items()))
            out["sweep"][crop] = dict(points=len(pts), judged=dict(tot), flipped={f"{r} {k}": v for (r, k), v in cnt.items()},
                                      direction={f"{r} {t} {d}": v for (r, t, d), v in sorted(risk.items())}, detail=detail)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str)); return
    for g in out["golden"]:
        if g.get("status"): print(f"[{g['case']}] {g['status']}"); continue
        fl = "; ".join(f"{r}: " + ", ".join(f"×{m}→{v}" for m, v in f.items()) for r, f in g["flips"].items() if f) or "뒤집힘 없음"
        print(f"[{g['case']}] {g['crop']} {g['as_of']} 기준값 {g['base']} | {fl}")
    for crop, s in out["sweep"].items():
        print(f"\n[시즌 시험] {crop} 반월 끝날 {s['points']}개, 판정 대상 {s['judged']}, 뒤집힘 {s['flipped'] or '없음'}")
        print(f"   방향별: {s['direction'] or '없음'}")
        for x in s["detail"]: print("   ", x)


if __name__ == "__main__":
    main()
