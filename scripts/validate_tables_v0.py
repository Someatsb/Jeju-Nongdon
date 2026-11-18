# -*- coding: utf-8 -*-
"""
표 검증기 초안 (사원 B, 2026-11-07 2라운드)

data/tables/schema.json 하나를 기준으로 supports.csv, params_by_season.csv, crops.csv, interventions.csv를 검사하고
한국어 오류(저장 불가)와 경고(저장 가능, 확인 필요)를 출력한다. 행 번호는 Excel 기준(머리글 = 1행).

사용:
  python tools/validate_tables.py                 # data/tables 전체 검사
  python tools/validate_tables.py --today 2026-11-07
  python tools/validate_tables.py --file 다른경로/supports.csv   # 올린 파일 하나만(관리 화면이 부름)
  python tools/validate_tables.py --json          # 관리 화면용 JSON 출력
종료 코드: 오류가 있으면 1, 없으면 0.
외부 라이브러리 없음(표준 라이브러리만).
"""
import sys, os, csv, io, json, re, argparse, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLES = os.path.join(ROOT, "data", "tables")


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, table, row, col, label, value, code, msg, hint=""):
        self.items.append(dict(level=level, table=table, row=row, col=col, label=label, value=value, code=code, msg=msg, hint=hint))

    def err(self, *a, **k): self.add("오류", *a, **k)
    def warn(self, *a, **k): self.add("경고", *a, **k)

    @property
    def n_err(self): return sum(1 for x in self.items if x["level"] == "오류")


def read_csv(path, rep, table):
    """utf-8-sig → utf-8 → cp949 순으로 읽는다(한국어 Windows Excel의 CSV 저장은 cp949)."""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            text = raw.decode(enc)
            if enc == "cp949":
                rep.warn(table, 0, "", "", "", "E00", "파일이 cp949(Excel 기본)로 저장돼 있습니다. 저장할 때 UTF-8로 바꿉니다.")
            break
        except UnicodeDecodeError:
            continue
    else:
        rep.err(table, 0, "", "", "", "E01", "파일 글자 인코딩을 읽을 수 없습니다.", "Excel에서 'CSV UTF-8'로 저장해 주세요.")
        return None, []
    bad = sorted({ch for ch in text if ord(ch) > 127 and not _cp949_ok(ch)})
    if bad:
        rep.warn(table, 0, "", "", "".join(bad[:10]), "R17",
                 f"Excel에서 cp949 CSV로 저장하면 깨지는 글자가 있습니다: {' '.join(bad[:10])}", "'-' 같은 기본 글자로 바꾸거나 'CSV UTF-8'로 저장해 주세요.")
    rd = csv.DictReader(io.StringIO(text))
    return rd.fieldnames or [], list(rd)


def _cp949_ok(ch):
    try:
        ch.encode("cp949"); return True
    except UnicodeEncodeError:
        return False


def parse_date(s):
    return dt.date.fromisoformat(s)


def check_columns(cols_def, header, rep, table):
    keys = [c["key"] for c in cols_def]
    missing = [k for k in keys if k not in header]
    extra = [h for h in header if h not in keys]
    for k in missing:
        lab = next(c["label"] for c in cols_def if c["key"] == k)
        rep.err(table, 1, k, lab, "", "E02", f"'{lab}'({k}) 컬럼이 없습니다.", "양식 파일의 머리글을 그대로 써 주세요.")
    for h in extra:
        rep.err(table, 1, h, "", "", "E03", f"모르는 컬럼 '{h}'이 있습니다.", "오타인지 확인하거나 지워 주세요.")
    return not missing


def check_cell(c, v, rep, table, rn, ctx):
    key, lab, typ = c["key"], c["label"], c["type"]
    if v is None: v = ""
    v = v.strip()
    if v == "":
        if c.get("required") is True:
            rep.err(table, rn, key, lab, v, "E10", f"{rn}행 '{lab}'({key})이 비어 있습니다.", c.get("help", ""))
        return None
    try:
        if typ == "int":
            x = int(v)
        elif typ == "float":
            x = float(v)
        elif typ == "date":
            x = parse_date(v)
        else:
            x = v
    except ValueError:
        ex = {"int": "예: 60", "float": "예: 0.5", "date": "예: 2026-01-16"}.get(typ, "")
        rep.err(table, rn, key, lab, v, "E11", f"{rn}행 '{lab}'({key})의 값 '{v}'은 {'숫자' if typ in ('int', 'float') else '날짜'} 형식이 아닙니다. {ex}")
        return None
    if typ in ("int", "float"):
        if "min" in c and x < c["min"] or "max" in c and x > c["max"]:
            rep.err(table, rn, key, lab, v, "E12", f"{rn}행 '{lab}' 값 {v}이 허용 범위({c.get('min')}~{c.get('max')}) 밖입니다.")
    if typ in ("str", "text") and "max" in c and len(v) > c["max"]:
        rep.err(table, rn, key, lab, v, "E13", f"{rn}행 '{lab}'이 {len(v)}자입니다. {c['max']}자 이하로 줄여 주세요.")
    if typ == "enum" and v not in c["enum"]:
        rep.err(table, rn, key, lab, v, "E14", f"{rn}행 '{lab}'에 '{v}'는 쓸 수 없습니다. 쓸 수 있는 값: {', '.join(c['enum'])}")
    if typ == "list_enum":
        for t in [t.strip() for t in v.split(";") if t.strip()]:
            if t not in c["enum"]:
                rep.err(table, rn, key, lab, v, "E14", f"{rn}행 '{lab}'에 '{t}'는 쓸 수 없습니다. 쓸 수 있는 값: {', '.join(c['enum'])}")
    if "pattern" in c and typ in ("str",) and not re.match(c["pattern"], v):
        rep.err(table, rn, key, lab, v, "E15", f"{rn}행 '{lab}' 값 '{v}'의 모양이 규칙과 다릅니다.", c.get("example", ""))
    if typ == "list_crop":
        for t in [t.strip() for t in v.split(";") if t.strip()]:
            if t not in ctx["crop_tokens"]:
                sug = [k for k, al in ctx["crop_alias"].items() if t in al]
                rep.err(table, rn, key, lab, v, "E16", f"{rn}행 '{lab}'에 '{t}'은 작물 목록에 없습니다." + (f" 혹시 '{sug[0]}'인가요?" if sug else ""),
                        "crops.csv의 crop_code 또는 그룹(밭작물·월동채소·과수·감귤)을 써 주세요.")
    if typ == "crop" and v not in ctx["crop_codes"]:
        rep.err(table, rn, key, lab, v, "E16", f"{rn}행 '{lab}'에 '{v}'은 작물 목록에 없습니다.")
    return x


def validate_supports(path, schema, ctx, rep, today):
    t = "supports"
    cols = schema["tables"][t]["columns"]
    header, rows = read_csv(path, rep, t)
    if header is None or not check_columns(cols, header, rep, t): return []
    seen, prog_name = {}, {}
    for i, r in enumerate(rows):
        rn = i + 2
        V = {c["key"]: check_cell(c, r.get(c["key"]), rep, t, rn, ctx) for c in cols}
        g = lambda k: (r.get(k) or "").strip()
        rid = g("id")
        if rid in seen:
            rep.err(t, rn, "id", "행 ID", rid, "R13", f"{rn}행 id '{rid}'이 {seen[rid]}행과 겹칩니다.")
        seen[rid] = rn
        pk = g("program_key")
        if rid and pk and not rid.startswith(pk + "@"):
            rep.err(t, rn, "id", "행 ID", rid, "R13", f"{rn}행 id는 program_key '{pk}@'로 시작해야 합니다.")
        if pk in prog_name and prog_name[pk][0] != g("agency").split("·")[0][:6] and False:
            pass
        prog_name.setdefault(pk, (g("agency"), rn))
        st = g("status")
        # R01 출처
        if st in ("confirmed", "prior_year_reference"):
            for k, lab in (("source_title", "근거 문서"), ("source_url", "근거 주소")):
                if not g(k):
                    rep.err(t, rn, k, lab, "", "R01", f"{rn}행 상태가 '{st}'인데 {lab}({k})가 비어 있습니다.", "'hold'로 두거나 출처를 넣어 주세요.")
            if g("source_url") and not all(u.strip().startswith("http") for u in g("source_url").split(" ; ")):
                rep.err(t, rn, "source_url", "근거 주소", g("source_url"), "R01", f"{rn}행 근거 주소는 http로 시작해야 합니다(여러 개면 ' ; ').")
        # R02 날짜 순서
        for a, b, la in (("valid_from", "valid_to", "적용 기간"), ("apply_start", "apply_end", "신청 기간")):
            if V.get(a) and V.get(b) and V[a] > V[b]:
                rep.err(t, rn, a, la, f"{g(a)}~{g(b)}", "R02", f"{rn}행 {la} 시작일({g(a)})이 끝나는 날({g(b)})보다 늦습니다.")
        # R03 신청 방식
        cyc = g("apply_cycle")
        if cyc == "연1회" and not g("apply_end"):
            rep.err(t, rn, "apply_end", "신청 마감일", "", "R03", f"{rn}행 신청 방식이 '연1회'인데 신청 마감일이 없습니다.")
        if cyc == "사후신청" and not g("event_type"):
            rep.err(t, rn, "event_type", "최근 일 조건", "", "R03", f"{rn}행 '사후신청'은 어떤 일(재해/사고) 뒤인지 event_type이 있어야 합니다.")
        # R04 나이
        if (g("min_age") or g("max_age")) and not g("age_basis"):
            rep.err(t, rn, "age_basis", "나이 기준일", "", "R04", f"{rn}행 나이 조건이 있는데 나이 기준일(age_basis)이 없습니다.", "신청일/연말/1월1일 중 하나")
        if V.get("min_age") is not None and V.get("max_age") is not None and V["min_age"] > V["max_age"]:
            rep.err(t, rn, "min_age", "최소 나이", g("min_age"), "R04", f"{rn}행 최소 나이가 최대 나이보다 큽니다.")
        if V.get("born_after") and V.get("born_before") and V["born_after"] >= V["born_before"]:
            rep.err(t, rn, "born_after", "출생일", "", "R04", f"{rn}행 born_after가 born_before보다 늦습니다.")
        # R05 면적
        if (g("min_ha") or g("max_ha")) and not g("area_basis"):
            rep.err(t, rn, "area_basis", "면적 기준", "", "R05", f"{rn}행 면적 조건이 있는데 면적 기준(area_basis)이 없습니다.", "경작/해당작물/소유/인증 중 하나")
        if V.get("min_ha") is not None and V.get("max_ha") is not None and V["min_ha"] > V["max_ha"]:
            rep.err(t, rn, "min_ha", "최소 면적", g("min_ha"), "R05", f"{rn}행 최소 면적이 최대 면적보다 큽니다.")
        for k in ("min_ha", "max_ha", "max_owned_ha"):
            if V.get(k) is not None and V[k] > 30 and k != "max_ha":
                rep.warn(t, rn, k, k, g(k), "R15", f"{rn}행 '{k}' {g(k)} — ha 단위입니다. 평으로 넣으셨다면 {V[k]*3.3058/10000:.4f}ha입니다.")
        # R06 E 짝
        if (g("needs_coop") == "E") != (g("needs_selfpay_fund") == "E"):
            rep.err(t, rn, "needs_coop", "계통출하·자조금", f"{g('needs_coop')}/{g('needs_selfpay_fund')}", "R06",
                    f"{rn}행 'E'(둘 중 하나)는 needs_coop와 needs_selfpay_fund에 함께 적어야 합니다.")
        # R07 소득
        if g("income_test") == "상한" and not g("income_max_manwon"):
            rep.err(t, rn, "income_max_manwon", "농외소득 상한", "", "R07", f"{rn}행 소득 기준이 '상한'인데 상한 금액(만원)이 없습니다.")
        # R08 지역
        if g("region_in") and not g("region_basis"):
            rep.err(t, rn, "region_basis", "지역 기준", "", "R08", f"{rn}행 행정시 조건이 있는데 주소지/농지소재지 기준이 없습니다.")
        # R09 금액 방식별 필수 칸
        at = g("amount_type")
        need = {"정액": ["amount_value"], "kg당": ["amount_value", "calc_basis"], "단위당": ["amount_value", "units_per_ha", "unit_name"], "규칙": ["rule_ref"]}.get(at, [])
        for k in need:
            if not g(k):
                rep.err(t, rn, k, k, "", "R09", f"{rn}행 금액 방식 '{at}'에는 '{k}' 칸이 필요합니다.")
        if at == "면적비례":
            if not (g("amount_value") or (g("amount_min") and g("amount_max"))):
                rep.err(t, rn, "amount_value", "금액", "", "R09", f"{rn}행 면적비례는 단가(amount_value) 또는 범위(amount_min~amount_max)가 필요합니다.")
            if not g("calc_basis"):
                rep.err(t, rn, "calc_basis", "곱하는 값", "", "R09", f"{rn}행 면적비례는 calc_basis(경작면적 등)가 필요합니다.")
        if at == "보조율" and not (g("rate_pct_min") or g("rate_pct_max")):
            rep.err(t, rn, "rate_pct_max", "보조율", "", "R09", f"{rn}행 보조율 방식인데 보조율(%)이 없습니다.")
        if V.get("amount_min") is not None and V.get("amount_max") is not None and V["amount_min"] > V["amount_max"]:
            rep.err(t, rn, "amount_min", "금액 범위", "", "R09", f"{rn}행 금액 하한이 상한보다 큽니다.")
        if V.get("rate_pct_min") is not None and V.get("rate_pct_max") is not None and V["rate_pct_min"] > V["rate_pct_max"]:
            rep.err(t, rn, "rate_pct_min", "보조율", "", "R09", f"{rn}행 보조율 하한이 상한보다 큽니다.")
        if at == "정액" and V.get("amount_value") is not None and V["amount_value"] < 1000:
            rep.warn(t, rn, "amount_value", "금액", g("amount_value"), "R15", f"{rn}행 정액 {g('amount_value')}원 — 원 단위입니다. 만원으로 넣으셨다면 {V['amount_value']*10000:,}원입니다.")
        # R12 규칙 참조 → params
        if g("rule_ref"):
            for crop in [x for x in g("crop_in").split(";") if x]:
                crops = ctx["group_members"].get(crop, [crop])
                for cc in crops:
                    key = "stab_base" if g("rule_ref") == "price_stab" else "logi_won_per_kg"
                    if (cc, key) not in ctx["params_keys"]:
                        rep.warn(t, rn, "rule_ref", "규칙 참조", g("rule_ref"), "R12", f"{rn}행 '{cc}'의 {key} 값이 params_by_season.csv에 없습니다(판정 안 함으로 인쇄됩니다).")
        # R16 상태와 기간
        if st == "prior_year_reference" and cyc == "연1회" and not g("next_month"):
            rep.err(t, rn, "next_month", "다음 신청 예상 월", "", "R16", f"{rn}행 '작년 기준' 행은 다음 신청 예상 월이 있어야 '○월쯤'으로 인쇄됩니다.")
        if st == "confirmed" and cyc == "연1회" and V.get("apply_end") and V["apply_end"] < today:
            rep.warn(t, rn, "status", "상태", st, "R16", f"{rn}행 신청 마감({g('apply_end')})이 지났습니다. 다음 회차 참고용이면 'prior_year_reference'로 바꿔 주세요.")
        # R15 경고
        if V.get("verified_date") and (today - V["verified_date"]).days > 180:
            rep.warn(t, rn, "verified_date", "확인일", g("verified_date"), "R15", f"{rn}행 확인일이 {(today - V['verified_date']).days}일 전입니다. 원문을 다시 확인해 주세요.")
        if V.get("valid_to") and V["valid_to"] < today and st != "hold":
            rep.warn(t, rn, "valid_to", "적용 종료일", g("valid_to"), "R15", f"{rn}행 적용 기간이 끝났습니다({g('valid_to')}). 새 회차로 바꾸거나 'hold'로 두세요.")
        for item in [x for x in g("manual_check").split(" / ") if x]:
            if len(item) > 60:
                rep.warn(t, rn, "manual_check", "직원 확인 항목", item[:20] + "…", "R15", f"{rn}행 확인 항목 한 개가 {len(item)}자입니다. 60자 이하로 나눠 주세요.")
        ctx.setdefault("rows_supports", []).append(r)
    # R11 excludes
    keys = {(r.get("program_key") or "").strip() for r in rows}
    for i, r in enumerate(rows):
        for x in [x.strip() for x in (r.get("excludes") or "").split(";") if x.strip()]:
            if x not in keys:
                rep.err(t, i + 2, "excludes", "같이 못 받는 제도", x, "R11", f"{i+2}행 excludes의 '{x}'는 표에 없는 제도 키입니다.")
    return rows


def validate_params(path, schema, ctx, rep, today):
    t = "params_by_season"
    td = schema["tables"][t]
    header, rows = read_csv(path, rep, t)
    if header is None or not check_columns(td["columns"], header, rep, t): return []
    pdict = td["param_dict"]; seen = {}
    for i, r in enumerate(rows):
        rn = i + 2
        for c in td["columns"]:
            if c["type"] == "param": continue
            check_cell(c, r.get(c["key"]), rep, t, rn, ctx)
        g = lambda k: (r.get(k) or "").strip()
        p, st = g("param"), g("status")
        if p not in pdict:
            rep.err(t, rn, "param", "항목", p, "R14", f"{rn}행 항목 '{p}'은 사전에 없습니다. 쓸 수 있는 항목: {', '.join(pdict)}"); continue
        if g("unit") != pdict[p]["unit"]:
            rep.err(t, rn, "unit", "단위", g("unit"), "R14", f"{rn}행 '{p}'의 단위는 '{pdict[p]['unit']}'이어야 합니다(지금 '{g('unit')}').")
        if st in ("역산", "계산", "추정", "미확인") and not g("method"):
            rep.err(t, rn, "method", "방법", "", "R14", f"{rn}행 등급이 '{st}'이면 계산·판단 방법(method)을 적어 주세요.")
        if st != "미확인" and not g("value"):
            rep.err(t, rn, "value", "값", "", "R14", f"{rn}행 값이 비어 있습니다. 모르면 등급을 '미확인'으로 두세요.")
        if st == "미확인" and g("value"):
            rep.warn(t, rn, "value", "값", g("value"), "R14", f"{rn}행 등급이 '미확인'인데 값이 있습니다. 판정에 쓰지 않습니다.")
        if st in ("공표", "공고", "보도") and not g("source_title") and not g("method"):
            rep.err(t, rn, "source_title", "근거", "", "R14", f"{rn}행 '{st}' 값에는 근거(source_title)나 방법(method)이 있어야 합니다.")
        k = (g("season"), g("crop"), p)
        if k in seen:
            rep.err(t, rn, "param", "항목", p, "R13", f"{rn}행 ({k[0]}, {k[1]}, {p})이 {seen[k]}행과 겹칩니다.")
        seen[k] = rn
        if g("value") and pdict[p]["unit"] in ("원/kg", "ha", "kg/10a"):
            try:
                if float(g("value")) <= 0: rep.err(t, rn, "value", "값", g("value"), "E12", f"{rn}행 값은 0보다 커야 합니다.")
            except ValueError:
                rep.err(t, rn, "value", "값", g("value"), "E11", f"{rn}행 '{p}' 값 '{g('value')}'이 숫자가 아닙니다.")
        if g("value") and pdict[p]["unit"] == "날짜":
            try: parse_date(g("value"))
            except ValueError: rep.err(t, rn, "value", "값", g("value"), "E11", f"{rn}행 날짜 형식이 아닙니다(예: 2025-10-31).")
    # 역산 구간 짝
    for (s, c, p), rn in seen.items():
        if p == "breakeven_lo":
            lo = next((r for r in rows if (r["season"], r["crop"], r["param"]) == (s, c, "breakeven_lo")), None)
            hi = next((r for r in rows if (r["season"], r["crop"], r["param"]) == (s, c, "breakeven_hi")), None)
            if hi is None:
                rep.err(t, rn, "param", "항목", p, "R14", f"{rn}행 breakeven_lo에 짝인 breakeven_hi가 없습니다.")
            elif lo["value"] and hi["value"] and float(lo["value"]) >= float(hi["value"]):
                rep.err(t, rn, "value", "값", lo["value"], "R14", f"{rn}행 역산 구간이 모순입니다(하한 {lo['value']} ≥ 상한 {hi['value']}). 판정을 끄려면 '미확인'으로.")
    return rows


def validate_simple(name, path, schema, ctx, rep):
    td = schema["tables"][name]
    header, rows = read_csv(path, rep, name)
    if header is None or not check_columns(td["columns"], header, rep, name): return []
    keyspec = td["key"] if isinstance(td["key"], list) else [td["key"]]
    seen = {}
    for i, r in enumerate(rows):
        rn = i + 2
        for c in td["columns"]:
            if c["type"] in ("list_str", "list_int"): continue
            check_cell(c, r.get(c["key"]), rep, name, rn, ctx)
        k = tuple((r.get(x) or "").strip() for x in keyspec)
        if k in seen: rep.err(name, rn, keyspec[0], "키", "/".join(k), "R13", f"{rn}행이 {seen[k]}행과 겹칩니다.")
        seen[k] = rn
        if name == "interventions" and r.get("confirmed") in ("확인", "보도1건") and r.get("type") != "없음" and not (r.get("source_url") or "").strip():
            rep.warn(name, rn, "source_url", "근거 주소", "", "R15", f"{rn}행 '{r.get('confirmed')}'인데 근거 주소가 없습니다. 원문 링크를 보강해 주세요.")
    return rows


def build_ctx(schema, rep, crops_path, params_path):
    ctx = {"crop_codes": set(), "crop_tokens": set(), "crop_alias": {}, "group_members": {}, "params_keys": set()}
    if os.path.exists(crops_path):
        _, rows = read_csv(crops_path, Report(), "crops")
        for r in rows:
            cc = r["crop_code"].strip(); ctx["crop_codes"].add(cc)
            ctx["crop_alias"][cc] = [a.strip() for a in (r.get("aliases") or "").split(";")]
            for gname in [x.strip() for x in (r.get("groups") or "").split(";") if x.strip()]:
                ctx["group_members"].setdefault(gname, []).append(cc)
        ctx["crop_tokens"] = ctx["crop_codes"] | set(ctx["group_members"])
    if os.path.exists(params_path):
        _, rows = read_csv(params_path, Report(), "params")
        for r in rows:
            ctx["params_keys"].add((r["crop"].strip(), r["param"].strip()))
    return ctx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=TABLES)
    ap.add_argument("--file", help="한 파일만 검사(파일 이름으로 표 종류를 정함)")
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    today = parse_date(a.today)
    schema = json.load(open(os.path.join(a.dir, "schema.json"), encoding="utf-8"))
    rep = Report()
    P = lambda n: os.path.join(a.dir, schema["tables"][n]["file"])
    ctx = build_ctx(schema, rep, P("crops"), P("params_by_season"))
    targets = ["crops", "params_by_season", "interventions", "supports"]
    if a.file:
        base = os.path.basename(a.file)
        targets = [n for n in targets if schema["tables"][n]["file"] == base] or ["supports"]
    for n in targets:
        path = a.file if a.file else P(n)
        if not os.path.exists(path):
            rep.err(n, 0, "", "", "", "E04", f"{path} 파일이 없습니다."); continue
        if n == "supports": validate_supports(path, schema, ctx, rep, today)
        elif n == "params_by_season": validate_params(path, schema, ctx, rep, today)
        else: validate_simple(n, path, schema, ctx, rep)
    if a.json:
        print(json.dumps(rep.items, ensure_ascii=False, indent=1, default=str))
    else:
        for x in rep.items:
            print(f"[{x['level']}] {x['table']} {x['code']} {x['msg']}" + (f"  → {x['hint']}" if x["hint"] else ""))
        nw = len(rep.items) - rep.n_err
        print(f"\n검사 끝: 오류 {rep.n_err}건, 경고 {nw}건" + (" — 오류가 있어 저장할 수 없습니다." if rep.n_err else " — 저장할 수 있습니다."))
    sys.exit(1 if rep.n_err else 0)


if __name__ == "__main__":
    main()
