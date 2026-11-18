"""결과 화면·종이 색 줄이기(2026-11-14 밤, 설계 result-v2 7절): 글자는 검정 하나, 강조색은 주황 하나(세 곳), 청록은 결론 띠 바탕에만,
칸 바탕은 흰색 하나, 그림은 선 색 하나, 종이에는 청록이 없다. 규칙 이름은 실제 클래스를 따른다. 파일을 읽어 검사하므로 서버가 필요 없다."""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "app" / "ui" / "static"
RESULT = (STATIC / "result.css").read_text(encoding="utf8")
PRINT = (STATIC / "print.css").read_text(encoding="utf8")

OK_VARS = {"ink", "ink-soft", "tang-deep", "paper", "cream", "line", "sea", "sea-soft", "urgent", "later-bg", "sand", "sand-soft", "sand-dark", "tang-soft"}
BAD_VARS = {"tang", "rape", "moss", "cream-2"}      # 쓰지 않는 색 이름(app.css 의 나머지 색)
OK_WORDS = {"white", "black", "transparent", "currentcolor", "none", "inherit", "initial", "unset", "solid", "dashed", "dotted", "important"}
HEX = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
COLOR_DEFS = {"--tang-deep": "#A94607", "--sea": "#1F6F78", "--sea-soft": "#DCEEEC", "--urgent": "#C62828", "--sand": "#B8A98A", "--sand-soft": "#DDD3BC", "--sand-dark": "#8F8468", "--tang-soft": "#FFE6BF", "--tang": "#F28C1E"}      # 화면·종이가 같은 색 이름과 값(2026-11-17: 종이도 컬러)
INK_RGB = ("43", "39", "36")          # var(--ink) 의 rgb. 덮개 바깥 어두운 막과 그림자에만 쓴다


def parse(css: str):
    """[(선택자 한 개, {속성: 값})]. @media 안의 규칙도 풀어서 담는다."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for d in body.split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls[k.strip()] = v.strip()
        for s in sel.split(","):
            s = " ".join(s.split())
            if s and not s.startswith("@"):
                out.append((s, decls))
    return out


def merged(rules):
    d = {}
    for sel, decls in rules:
        d.setdefault(sel, {}).update(decls)
    return d


R, P = parse(RESULT), parse(PRINT)
RD, PD = merged(R), merged(P)


def hexrgb(h: str):
    h = h.lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def neutral(h: str) -> bool:
    r, g, b = hexrgb(h)
    return max(r, g, b) - min(r, g, b) <= 12      # 흰색·회색·검정에 가까운 색(#1c1916 포함)


COLOR_PROPS = ("color", "background", "background-color", "border-color", "outline-color", "fill", "stroke")


def stray_colors(rules):
    """허용 목록 밖의 색을 (선택자, 속성, 값)으로."""
    bad = []
    for sel, decls in rules:
        for prop, val in decls.items():
            if prop.startswith("--"):
                if COLOR_DEFS.get(prop, "").lower() == val.lower():
                    continue
                if HEX.fullmatch(val) and neutral(val):              # --ink · --ink-soft · --line 같은 검정·회색 정의
                    continue
                if not re.search(r"#|rgb|var\(", val):
                    continue
                bad.append((sel, prop, val)); continue
            if sel in ('.rband', '.v2 .sh') and ('var(--tang)' in val or '#D97A12' in val):      # 2026-11-17 사장: 맨 위 결론 띠는 감귤 주황(--tang)과 같은 계열의 조금 진한 주황 그림자
                continue
            for name in re.findall(r"var\(--([\w-]+)", val):
                if name in BAD_VARS:
                    bad.append((sel, prop, val))
            for m in HEX.finditer(val):
                if sel == '.zn-lab' and prop == 'background' and m.group(0).upper() == '#FFE6BF':      # 2026-11-16 사장: 지금 하실 일 칸은 옅은 주황
                    continue
                if not neutral(m.group(0)):
                    bad.append((sel, prop, val))
            for m in re.finditer(r"rgba?\(([^)]*)\)", val):
                parts = [p.strip() for p in m.group(1).replace("/", ",").split(",")]
                if tuple(parts[:3]) != INK_RGB and not (parts[0] == parts[1] == parts[2]):
                    bad.append((sel, prop, val))
            if prop in COLOR_PROPS:
                rest = re.sub(r"var\([^)]*\)|#\w+|rgba?\([^)]*\)", "", val)
                for w in re.findall(r"[a-zA-Z]+", rest):
                    if w.lower() not in OK_WORDS:
                        bad.append((sel, prop, val))
    return bad


# ---------------- 허용 목록 ----------------
def test_result_css_uses_only_allowed_colors():
    assert stray_colors(R) == []


def test_print_css_uses_only_allowed_colors():
    assert stray_colors(P) == []


def test_print_css_is_in_color_like_the_screen_and_teal_hex_only_in_the_color_definitions():      # 2026-11-17 사장 지시: 인쇄도 컬러(흑백 프린터에서도 읽히게 글·굵기·테두리를 함께 쓴다)
    assert PD[".v2"]["--sea"] == "#1F6F78" and PD[".v2"]["--sea-soft"] == "#DCEEEC" and PD[".v2"]["--urgent"] == "#C62828"      # 화면과 같은 색 값
    for sel, decls in P:
        for prop, val in decls.items():
            if prop.startswith("--"):
                continue                          # 색 정의는 위에서 따로 본다
            for m in HEX.finditer(val):
                r, g, b = hexrgb(m.group(0))
                assert not (g > r + 20 and b > r + 20), (sel, m.group(0))      # 청록 16진 값을 곳곳에 쓰지 않는다(변수로만)


# ---------------- 청록은 결론 띠 바탕과 새로 나온 공고 상자의 제목 띠 바탕에만 ----------------
def test_sea_only_on_the_conclusion_band_background():
    for sel, decls in R:
        for prop, val in decls.items():
            if "var(--sea)" in val:
                assert prop.startswith("border") or ":focus" in sel, (sel, prop)    # 진한 청록 바탕은 결론 띠와 번호 동그라미만. 테두리·초점 테두리는 그대로
    band = RD[".rband"]
    assert band["background"] == "var(--tang)" and band["color"] == "var(--ink)" and "var(--sea)" not in band["border"] and "#000" not in band["box-shadow"]      # 결론 띠: 감귤 주황 바탕 + 먹색 글자(2026-11-17 사장)


def test_band_text_is_white_and_amount_is_white_not_yellow():
    assert RD[".rb-hi"]["color"] == "var(--ink)" and "rape" not in RESULT
    assert RD[".rb-edit"]["color"] == "var(--ink)"
    assert "underline" in RD[".rb-hi"].get("text-decoration", "")                  # 흰 글씨 + 밑줄로 강조
    assert RD[".rb-hi"].get("font-weight") == "800"
    assert RD[".rb-hi"].get("font-size")                                           # 가장 큰 굵은 글씨(띠 안에서 한 단계 더 크게)


# ---------------- 칸 바탕은 흰색 하나 ----------------
CELL = re.compile(r"(^|[ >])\.(pbox|bx|bxr)(\.is-first|\.is-wide)?$|\.is-first$")


@pytest.mark.parametrize("rules,css", [(R, RESULT), (P, PRINT)], ids=["result.css", "print.css"])
def test_row_cells_have_one_plain_background(rules, css):
    seen = 0
    for sel, decls in rules:
        if not CELL.search(sel) or sel.startswith(".bx-tag"):
            continue
        for prop in ("background", "background-color"):
            if prop in decls:
                seen += 1
                assert decls[prop] in ("var(--paper)", "#fff", "transparent", "none"), (sel, decls[prop])
    assert seen >= 1
    for old in ("FFF1DC", "FFE9C9", "FFE3B8", "rgba(31, 111, 120", "rgba(255, 253, 245", "e4f1ef", "fff0db"):
        assert old.lower() not in css.lower(), old


def test_rows_are_split_by_a_thin_line_not_a_tint():
    assert "var(--line)" in RD[".bxr + .bxr"]["border-top"]          # 화면: 상자 안의 줄은 가는 선으로만 나눈다
    assert "var(--sand-soft)" in PD[".v2 .pr"]["border-top"]           # 종이: 상자 안의 줄도 가는 선으로만(검정이 아니라 옅은 모래색)


# ---------------- 글자는 검정, 강조색은 주황 셋뿐 ----------------
def test_phone_period_and_todo_text_are_ink_on_paper_and_band_text_is_white():
    d, prefix = PD, ".v2 "
    for name in (".pr-text", ".pr-when", ".pr-m", ".pr-unlock"):
        assert d[prefix + name]["color"] == "var(--ink)", name              # 줄 글자는 흰 바탕 위 검정
    assert d[prefix + ".pb-band"]["color"] == "var(--ink)" and d[prefix + ".pb-band"]["background"] == "var(--sea-soft)"      # 가실 곳 띠(빈 종이): 옅은 청록 바탕 + 먹색 글자(진한 청록은 결론 띠와 번호 동그라미뿐)
    assert d[prefix + ".pb-t"]["color"] == "var(--ink)" and d[prefix + ".pz-h"]["background"] == "var(--tang-soft)" and d[prefix + ".pz-later .pz-h"]["background"] == "var(--sea-soft)" and d[prefix + ".pz-h"]["color"] == "var(--ink)"      # 대분류 칸: 지금 = 옅은 주황, 앞으로 = 옅은 청록 바탕 + 먹색 굵은 글자
    assert d[prefix + ".pb-tel b"]["font-weight"] in ("800", "700")     # 전화는 굵게


def test_screen_row_text_is_ink_on_white_and_band_text_is_white():
    for name in (".bxr-t", ".bxr-text", ".bxr-when", ".bxr-m", ".nn-name", ".nn-why"):
        assert RD[name].get("color", "var(--ink)") == "var(--ink)", name          # 색을 따로 정하지 않으면 본문 검정 그대로
    assert RD[".bx-band"]["color"] == "var(--ink)" and RD[".bx-band"]["background"] in ("#fff", "var(--paper)")      # 표의 소분류 칸(가실 곳): 흰 바탕 + 먹색 글자
    assert RD[".zn-lab"]["background"] == "#FFE6BF" and RD[".lt .zn-lab"]["background"] == "var(--sea-soft)" and RD[".zn-h"]["color"] == "var(--ink)"      # 대분류 칸 "지금 하실 일": 옅은 청록 바탕 + 먹색 글자(진한 청록은 맨 위 결론 띠와 번호 동그라미만)
    assert ".bx-no" not in RD      # 화면에는 번호 동그라미가 없다
    assert RD[".bx"]["background"] == "#fff"
    assert RD[".bx-pic"]["background"] == "#fff"               # 검정 선 그림은 흰 판 위에


def test_small_notes_are_ink_soft_and_unlock_is_underlined_ink():
    assert RD[".bxr-note"]["color"] == "var(--ink-soft)"
    assert RD[".bxr-unlock"]["color"] == "var(--ink)" and "underline" not in RD[".bxr-unlock"].get("text-decoration", "")      # 누르는 링크가 아니라 그냥 글(2026-11-17)
    assert ".rn-more" not in RD      # "… 더 보기"도 그냥 글
    assert PD[".v2 .pr-unlock"]["color"] == "var(--ink)" and "underline" not in PD[".v2 .pr-unlock"].get("text-decoration", "")      # 종이에서는 누를 수 없어 밑줄 없음(이름은 뒷면에)
    assert PD[".v2 .pb-more"]["color"] in ("var(--ink-soft)", "var(--ink)")


def tang_users(rules):
    return sorted({sel for sel, decls in rules for prop, v in decls.items() if "tang-deep" in v and prop != "--tang-deep"})


def test_orange_only_on_amount_first_row_and_pill_on_screen():
    # 받을 금액 글(숫자가 든 금액 덩어리 .rg-amt) · "먼저 하실 일" 줄의 굵은 테두리와 딱지 · 아래 띠의 주 단추(app.css 의 .btn-primary 가 칠한다). 그 밖에 주황 없음
    # (2026-11-15 점검 반영: 디자인 원칙 3의 넷째 곳 '급한 남은 날 표시'(.rx-urgent b, 마감이 급한 보험 줄의 '오늘까지'·'○일 남음'). 종이에는 싣지 않는다)
    # (2026-11-15 4차: 남은 날 딱지는 빨강(--urgent)으로 옮겨 주황은 셋뿐: 금액 · "먼저 하실 일" 상자(굵은 테두리·딱지) · 주 단추)
    assert tang_users(R) == [".bxr-amt", ".lt-amt"], tang_users(R)      # 2026-11-15 두 구역: 주황은 금액(지금 구역·앞으로 구역)뿐. "먼저 하실 일" 딱지·굵은 테두리는 없어졌다
    assert RD[".bxr-amt"]["color"] == "var(--tang-deep)" and RD[".bxr-m"]["color"] == "var(--ink)" and RD[".bxr-pre"].get("color") is None      # 금액 덩어리만 주황(앞 말은 검정)
    assert ".bx-tag.is-first" not in RD and ".bx.is-first" not in RD
    assert RD[".rtab"]["border"].endswith("var(--sea)")                       # 표 바깥 테두리는 진한 청록(검정 아님, 2026-11-16 사장)


def test_orange_only_on_amount_first_row_and_pill_on_paper():
    users = tang_users(P)
    # 종이(2026-11-17 컬러): 주황은 금액(지금 구역 줄 · 앞으로 줄)뿐. 결론 띠 금액은 흰 글자 밑줄이고 상자 굵은 테두리는 없다. 빨강은 마감 날짜 알약, 진한 청록은 결론 띠와 번호 동그라미뿐
    assert set(users) == {".v2 .pr-amt", ".v2 .lr-amt"}, users        # 2026-11-15 두 구역: 앞으로 목록의 금액(.lr-amt)도 같은 주황
    red = sorted({sel for sel, decls in P for prop, v in decls.items() if "var(--urgent)" in v})
    assert red == [".v2 .pr-pill", ".v2 .rnt-d"], red                    # 빨강은 마감 날짜 알약(테두리 + 글자)뿐
    dark = sorted({sel for sel, decls in P for prop, v in decls.items() if prop in ("background", "background-color") and v.strip() == "var(--sea)"})
    assert dark == [], dark        # 진한 청록 바탕은 없다(결론 칸은 감귤 주황, 앞면에 번호 동그라미는 없고 뒷면도 없다)
    soft = sorted({sel for sel, decls in P for prop, v in decls.items() if prop in ("background", "background-color") and v.strip() == "var(--sea-soft)"})
    assert soft == [".v2 .pb-band", ".v2 .pz-later .pz-h"] and PD[".v2 .pz-h"]["background"] == "var(--tang-soft)", soft      # 옅은 청록 바탕: 앞으로 대분류 칸 · 가실 곳 띠 · 달 이름표(먹색 글자), 지금 하실 일 대분류 칸은 옅은 주황


def test_number_is_a_sea_disc_in_the_band_and_paper_arrow_is_ink():
    assert ".bx-no" not in RD      # 화면에는 번호 동그라미가 없다
    assert ".v2 .pb-no" not in PD and ".v2 .pc .pb-no" not in PD      # 종이에도 번호 동그라미는 없다(2026-11-17)


# ---------------- 그림: 선 색 하나 ----------------
@pytest.mark.parametrize("rules,scope", [(P, ".v2 svg.ic")], ids=["paper-front"])
def test_icons_are_one_line_color(rules, scope):
    found = [(s, d) for s, d in rules if s.startswith(scope)]
    assert found, scope
    blob = " ".join(f"{k}:{v}" for s, d in found for k, v in d.items())
    assert "stroke:var(--ink)" in blob.replace(": ", ":") and "fill:#fff" in blob.replace(": ", ":"), scope


# ---------------- 아래 띠·덮개 ----------------
def test_bottom_bar_only_print_button_is_filled_orange():
    assert RD[".rbar .btn-home"]["background"] in ("#fff", "var(--paper)")
    assert not [s for s, _ in R if "btn-primary" in s and "rbar" in s]       # 주황 채움은 app.css 의 .btn-primary(종이로 뽑기) 하나
    assert RD[".btn-sea"]["background"] != "var(--sea)"                      # "닫고 돌아가기"는 청록 채움이 아님


def test_overlays_use_no_tint_background():
    assert RD[".dt-note"]["background"] in ("var(--paper)", "#fff")
    for sel in (".reminder-line", ".rm-err", ".after"):
        assert RD[sel]["background"] in ("var(--paper)", "#fff"), sel
    assert RD[".rm-fmt"]["color"] == "var(--ink)"


# ---------------- 종이 ----------------
def test_paper_conclusion_box_is_white_with_thick_black_border():
    sh = PD[".v2 .sh"]
    assert sh["background"] == "var(--tang)" and sh["color"] == "var(--ink)" and "var(--tang)" in sh["border"] and sh["border"].startswith("3")      # 종이 결론 칸: 화면 결론 띠처럼 감귤 주황 바탕 + 먹색 글자
    hi = PD[".v2 .rb-hi"]      # 밑줄은 글자 장식(흰색): 테두리로 그으면 아랫줄 글자에 닿는다(2026-11-16)
    assert hi["color"] == "var(--ink)" and hi["text-decoration"] == "underline" and hi["text-decoration-color"] == "var(--ink)"
    assert "border-bottom" not in hi


# ---------------- 화면 전체: 진한 청록(--sea) 바탕은 결론 띠와 번호 동그라미뿐(2026-11-15 최종) ----------------
SCREEN_CSS_FILES = ("result.css", "flow.css", "supports.css", "question.css", "staff.css", "scout.css", "typesheet.css")
DARK_BG_OK = {".rband", ".bx-no", ".dt-no", ".t-n"}      # 결론 띠 · 번호 동그라미(.t-n 은 유형별 안내 번호)


def test_dark_sea_background_only_on_conclusion_band_and_number_circles():
    for fn in SCREEN_CSS_FILES:
        for sel, decls in parse((STATIC / fn).read_text(encoding="utf8")):
            for prop in ("background", "background-color"):
                if decls.get(prop, "").strip() == "var(--sea)":
                    assert sel in DARK_BG_OK or ":focus" in sel, (fn, sel)


@pytest.mark.parametrize("fn,sel", [("flow.css", ".c-band"), ("supports.css", ".sp-gh"), ("supports.css", ".sp-fold summary")])
def test_bands_are_soft_sea_with_ink_text_and_dark_rule_below(fn, sel):
    d = merged(parse((STATIC / fn).read_text(encoding="utf8")))[sel]      # 가실 곳 상자·확인 화면 상자·지원 목록 묶음 제목 띠
    assert d["background"] == "var(--sea-soft)" and d["color"] == "var(--ink)" and d["border-bottom"] == "3px solid var(--sea)"


def test_screen_has_no_black_borders_or_icon_stripping():
    """2026-11-16 사장: 결과 화면 검정 줄이기. 로고·그림 색 빼기 규칙 없음, 표·상자 테두리와 덮개 주 단추에 먹색 칠이 없다."""
    css = RESULT
    assert ".page-r svg.ic [" not in css and ".page-r a.brand svg [" not in css and "border-color: var(--ink-soft)" not in css
    assert ".rm-btns .btn-primary, .after .btn-primary" not in css
    for sel in (".rband", ".rtab", ".know", ".after", ".rm-card", ".zn + .zn"):
        for k, v in RD.get(sel, {}).items():
            if k == "border" or k == "border-top" or k == "box-shadow":
                assert "var(--ink)" not in v, (sel, k, v)
