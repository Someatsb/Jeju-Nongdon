"""한 화면 규칙 점검: 화면마다 세 가지 창 크기에서 scrollHeight/scrollWidth 가 창 안에 드는지 표로 찍는다.

사용: python -X utf8 scripts/screen_fit.py --base http://127.0.0.1:8791 [--shots 폴더] [--notice-base http://127.0.0.1:8792]
새 공고 화면(sp_new*)은 시험용 새 공고가 올라 있는 서버가 따로 필요하다: 그 서버를 `--catalog-dir <폴더>` 로 띄운다
(폴더 안에 notices/ 를 만들고 tests/fixtures/catalog_notices/*.json 을 넣는다). --notice-base 가 없으면 그 화면은 건너뛴다.
화면을 더하려면 SCREENS 에 (이름, 경로, 준비 동작) 을 넣는다. 준비 동작은 page 를 받아 단추를 눌러 다음 단계로 넘기는 함수(없으면 None).
"""
import argparse
import sys
from pathlib import Path

from urllib.parse import quote

SIZES = [(1920, 940), (1536, 730), (1366, 650)]          # 기준 세 크기: "한 화면" 검사(세로·가로 모두)
# 새 크기: 모든 화면에 가로 스크롤 없음·칸 넘침 없음·창 밖으로 나간 요소 없음·아래 띠/주 단추가 보임을 보고,
# 가로로 넓은 창(폭 1000 이상, 높이 560 이상)에서는 첫 화면·질문·찾는 중·종이 고르기·직원 메뉴가 세로 스크롤도 없어야 하고,
# 폭 768 이상·높이 700 이상이면 첫 화면은 좁아도 한 화면에 들어야 한다.
SIZES_NEW = [(1280, 600), (1100, 700), (1024, 768), (900, 700), (768, 900), (600, 800), (420, 800), (360, 640)]
ALL_SIZES = SIZES + SIZES_NEW
RESULT_ONE: set[str] = set()       # (2026-11-15 3차: 결과 화면의 한 화면 규칙은 1920x940 에서만. ONE_SCREEN_AT_BIG 참고. 더 작은 창은 글씨를 줄이지 않고 세로 스크롤을 허용한다)
RESULT_NAMES = {"result", "result_P1", "result_P2", "result_P3", "result_P5"}        # 결과 화면(할 일 목록): 글씨 하한·그림 크기·아래 띠가 내용 끝을 가리지 않음을 모든 크기에서 본다
RESULT_BIG_ONE = {"result", "result_P1", "result_P2", "result_P3", "result_P5"}      # 1920x940 에서 결론 띠 + 줄(셋까지) + 알아 두세요 + 아래 띠가 스크롤 없이 한 화면인 사례(2026-11-15 점검 반영: 받을 것이 둘·셋인 줄은 큰 화면에서 가로 칸으로 나눠 P1·P3·P5 도 한 화면. 글씨는 줄이지 않는다)
ONE_SCREEN_WIDE = {"home", "q1_emd", "q2_crop", "q2b_crop2", "q2b_picked", "q2_x2", "q3_person", "q4_mgmt", "q5_sell", "q6_press", "q6_press_own", "q3_hint", "q6_hint",
                   "proxy_q1", "working", "typesheet", "staff"}


def _noop(page):
    return None


# --- 질문 화면(/counsel/input): 단추를 눌러 단계를 넘긴다. 가장 빽빽한 경우(작물 둘 다 자조금 품목, 땅 질문까지 나옴)로 점검한다 ---
def _go(n):
    """질문 화면에서 다음을 n번 눌러 (n+1)번째 단계로 간다(필요한 칸은 채운다)."""
    def prep(page):
        if n >= 1:
            page.click('[data-city-tab="제주시"]')
            page.click('label.choice:has(input[name="emd_code"][value="애월읍"])')
            page.click("#next-btn")
        if n >= 2:
            page.click('label.choice:has(input[name="crop1_crop_code"][value="마늘"])')
            page.fill('input[name="crop1_area_py"]', "1800")
            page.keyboard.press("Enter")                            # 숫자판을 닫는다
            page.click("[data-more].more-btn")                      # 둘째 작물 화면
            page.click('label.choice:has(input[name="crop2_crop_code"][value="월동무"])')
            page.fill('input[name="crop2_area_py"]', "900")
            page.keyboard.press("Enter")
            page.click("#next-btn")
        if n >= 3:
            page.click('label.choice:has(input[name="owner_sex"][value="M"])')
            page.fill('input[name="birth_year"]', "1955")
            page.click("#next-btn")
        if n >= 4:
            page.click('label.choice:has(input[name="mgmt_status"][value="over_2y"])')
            page.fill('input[name="mgmt_last_reg_year"]', "2025")
            page.click("#next-btn")
        if n >= 5:
            page.click("#next-btn")
    return prep


def _crop2(page):
    """2번 질문에서 마늘 1,800평을 고르고 '다른 밭도 있어요'를 눌러 둘째 작물 화면(아직 안 고름)을 본다."""
    _go(1)(page)
    page.click('label.choice:has(input[name="crop1_crop_code"][value="마늘"])')
    page.fill('input[name="crop1_area_py"]', "1800")
    page.keyboard.press("Enter")                                    # 숫자판을 닫는다
    page.click("[data-more].more-btn")
    page.wait_for_timeout(150)


def _crop2_picked(page):
    """둘째 작물(월동무 900평)을 고른 둘째 화면."""
    _crop2(page)
    page.click('label.choice:has(input[name="crop2_crop_code"][value="월동무"])')
    page.fill('input[name="crop2_area_py"]', "900")
    page.keyboard.press("Enter")                                    # 숫자판을 닫는다
    page.wait_for_timeout(150)


def _x2_line(page):
    """둘째 작물을 고른 뒤 이전으로 돌아온 첫째 화면: '둘째 작물: 월동무 900평 · 고치기' 한 줄이 보인다."""
    _crop2_picked(page)
    page.click(".btn-prev")
    page.wait_for_timeout(150)


def _press_own(page):
    """마지막 화면에서 "내 땅이에요"까지 눌러 "가진 땅 4,700평" 단추가 더 나온 가장 빽빽한 경우."""
    _go(5)(page)
    page.click('label.choice:has(input[name="land_tenure"][value="own_all"])')


def _hint_sex(page):
    """3번 질문에서 성별을 안 누르고 다음을 눌러 안내가 뜬 모습(안내가 단추 줄 위에서 화면을 밀지 않는지)."""
    _go(2)(page)
    page.click("#next-btn")
    page.wait_for_timeout(200)


def _hint_must(page):
    """마지막 화면에서 아무것도 안 누르고 결과 보기를 눌러 '햇수·배우자·거주' 안내가 뜬 모습."""
    _go(5)(page)
    page.click("#next-btn")
    page.wait_for_timeout(200)


def _numpad_area(page):
    _go(1)(page)
    page.click('input[name="crop1_area_py"]')


def _numpad_birth(page):
    _go(2)(page)
    page.click('input[name="birth_year"]')


# --- 확인·찾는 중·결과 화면: 질문을 끝까지 눌러 세션을 만든 뒤 간다(P4 애월 양배추). 확인·결과 화면은 스크롤이 허용된다 ---
def _answer_p4(page):
    """질문 화면을 P4(애월읍 양배추 3,630평 · 65세 남 · 경영체 없음)로 끝까지 눌러 확인 화면으로 간다."""
    page.click('[data-city-tab="제주시"]')
    page.click('label.choice:has(input[name="emd_code"][value="애월읍"])')
    page.click("#next-btn")
    page.click('label.choice:has(input[name="crop1_crop_code"][value="양배추"])')
    page.fill('input[name="crop1_area_py"]', "3630")
    page.click("#next-btn")
    page.click('label.choice:has(input[name="owner_sex"][value="M"])')
    page.fill('input[name="birth_year"]', "1961")
    page.click("#next-btn")
    page.click('label.choice:has(input[name="mgmt_status"][value="none"])')
    page.click("#next-btn")
    page.click('label.choice:has(input[name="crop1_sales_channel"][value="field_contract_done"])')
    page.click('label.choice:has(input[name="crop1_selfpay_fund"][value="not_paid"])')
    page.click("#next-btn")
    page.click('label.choice:has(input[name="farming_years"][value="5"])')
    page.click('label.choice:has(input[name="spouse"][value="none"])')
    page.click('label.choice:has(input[name="residence_3y"][value="on"])')
    page.click("#next-btn")
    page.wait_for_url("**/counsel/confirm", timeout=15000)


def _confirm(page):
    _answer_p4(page)


def _working(page):
    _answer_p4(page)
    page.click("#next-btn")
    page.wait_for_url("**/counsel/working", timeout=15000)


def _result(page):
    _answer_p4(page)
    page.click("#next-btn")
    page.wait_for_url("**/counsel/preview", timeout=30000)
    page.wait_for_timeout(600)


def _result_remind(page):
    """결과 화면에서 아래 띠의 '문자로 알림 받기'를 눌러 덮개를 연 모습."""
    _result(page)
    page.click(".rbar .rm-open")
    page.wait_for_timeout(250)


def _result_open(page):
    """결과 화면에서 '자세히 보기'를 눌러 덮개를 연 모습(올해는 어려운 것 · 창구 확인 · 쉬운 말 설명). 덮개 안은 따로 스크롤된다."""
    _result(page)
    page.click("#dt-open")
    page.wait_for_timeout(250)


def _demo(pid, open_detail=False):
    """재생 시연 입력 P1~P5(data/replay/demo_inputs.json)로 결과 화면까지 간다(2026-11-14 2차: 줄이 셋이고 오른쪽 줄이 많은 P2·P3 포함)."""
    def prep(page):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _drive import demo_inputs, fill_and_submit
        from urllib.parse import urlsplit
        u = urlsplit(page.url)
        d = demo_inputs()[pid]
        fill_and_submit(page, f"{u.scheme}://{u.netloc}", d["form"])
        for key in d.get("already") or ():      # 확인 화면의 '이미 받고 계신 지원' 칸(창 크기에 따라 눌림이 흔들려서 값을 직접 넣는다)
            page.evaluate("(k) => { const e = document.querySelector('input[name=already][value=\"' + k + '\"]'); if (e) { e.checked = true; e.dispatchEvent(new Event('change', {bubbles: true})); } }", key)
        page.click("#next-btn")
        page.wait_for_url("**/counsel/preview", timeout=60000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        if open_detail:
            page.click("#dt-open")
            page.wait_for_timeout(250)
    return prep


# 스크롤을 허용하는 화면(확인·결과)은 가로 넘침만 FAIL이고, 주 단추·요약이 첫 화면 안에 보이는지를 따로 본다: 화면 이름 → 첫 화면 안에 있어야 하는 칸(CSS 선택자)
SCROLL_OK = {
    "confirm": ["#next-btn"],
    "result_open_P3": [".dt-close"], "result_open": [".dt-close"],        # 덮개는 창에 고정되어 늘 한 화면이고 덮개 뒤 결과 화면은 스크롤을 허용(3차)
    "result": [".btn-print"], "result_P1": [".btn-print"], "result_P2": [".btn-print"], "result_P3": [".btn-print"], "result_P5": [".btn-print"],
    "result_remind": ["#rm-send"],
    "notice": [],       # 직원용 공고 근거 보고서: 사업·이름표 표가 길어 세로로 스크롤된다(가로 넘침만 본다)
    "sp_list": [".actionbar .btn-main"], "sp_list_f": [".actionbar .btn-main"], "sp_table": [".actionbar .btn-main"],
    "sp_table_one": [".actionbar .btn-main"], "sp_nolink": [".actionbar .btn-main"], "sp_hold": [".actionbar .btn-main"],
    "sp_new": [".actionbar .btn-main"], "sp_new_list": [".actionbar .btn-main"], "sp_allow": [".actionbar .btn-main"],
}
# 1920x940에서만 더 요구하는 칸(작은 창에서는 아래로 스크롤해도 된다)
FIRST_VIEW_BIG = {}


def _filter_citrus(page):
    """지원 전체 보기에서 걸러 보기 단추(감귤)를 누른 모습."""
    page.click('a.sp-chip[href="/supports?f=citrus"]')
    page.wait_for_url("**/supports?f=citrus")
    page.wait_for_timeout(150)


def _filter_new(page):
    page.click('a.sp-chip[href="/supports?f=new"]')
    page.wait_for_url("**/supports?f=new")
    page.wait_for_timeout(150)


NEW_KEY = quote("new-새공고_예시", safe="")      # tests/fixtures/catalog_notices/새공고_예시.json 을 notices/ 에 넣은 서버에서
NOTICE_SCREENS = {"sp_new", "sp_new_list"}


# (이름, 경로, 준비 동작). 뒤 단계가 화면을 더 넣는다.
SCREENS = [
    ("home", "/", None),
    ("q1_emd", "/counsel/input", None),
    ("q2_crop", "/counsel/input", _go(1)),
    ("q2b_crop2", "/counsel/input", _crop2),
    ("q2b_picked", "/counsel/input", _crop2_picked),
    ("q2_x2", "/counsel/input", _x2_line),
    ("q3_person", "/counsel/input", _go(2)),
    ("q4_mgmt", "/counsel/input", _go(3)),
    ("q5_sell", "/counsel/input", _go(4)),
    ("q6_press", "/counsel/input", _go(5)),
    ("q6_press_own", "/counsel/input", _press_own),
    ("q3_hint", "/counsel/input", _hint_sex),
    ("q6_hint", "/counsel/input", _hint_must),
    ("q2_numpad", "/counsel/input", _numpad_area),
    ("q3_numpad", "/counsel/input", _numpad_birth),
    ("proxy_q1", "/counsel/input?mode=proxy", None),
    ("confirm", "/counsel/input", _confirm),
    ("working", "/counsel/input", _working),
    ("result", "/counsel/input", _result),
    ("result_P1", "/counsel/input", _demo("P1")),
    ("result_P2", "/counsel/input", _demo("P2")),
    ("result_P3", "/counsel/input", _demo("P3")),
    ("result_P5", "/counsel/input", _demo("P5")),
    ("result_open_P3", "/counsel/input", _demo("P3", True)),
    ("result_remind", "/counsel/input", _result_remind),
    ("result_open", "/counsel/input", _result_open),
    ("typesheet", "/typesheet", None),
    ("staff", "/staff", None),
    ("notice", "/staff/notice/N1-df8255b2", None),
    ("hold", "/__hold", None),          # 인쇄 보류 화면: --hold-html 로 받은 파일을 이 경로로 돌려준다
    ("notfound", "/zzz-none", None),    # 없는 주소(오류 화면)
    ("sp_list", "/supports", None),
    ("sp_list_f", "/supports", _filter_citrus),            # 걸러 보기 단추를 누른 모습
    ("sp_table", "/supports/NAT-CROP-INS", None),          # 표 지원(작물 일곱 가지, 원문 링크 있음, 가장 긴 안내)
    ("sp_table_one", "/supports/NAT-PENSION-SUPPORT", None),   # 표 지원(한 줄짜리, 링크 있음): 1920x940에서 한 화면
    ("sp_nolink", "/supports/NAT-DISASTER-RECOVERY", None), # 원문 링크가 없는 지원
    ("sp_hold", "/supports/JEJU-HAPPY-TAXI", None),        # 아직 확인 중인 지원(값이 비어 휑한 쪽)
    ("sp_new", "/supports/" + NEW_KEY, None),              # 새 공고(--notice-base 서버)
    ("sp_new_list", "/supports?f=new", None),
    ("sp_allow", "/supports/JEJU-FARMER-ALLOW", None),     # 조건이 한 가지뿐인 지원: 1536x730 에서 한눈에 띠와 '누가 받나요'가 스크롤 없이 보인다
]
# 주 단추(또는 아래 띠)가 창 안에 보여야 하는 화면: 화면 이름 → 선택자
MAIN_BTN = {"home": ".btn-xl", "confirm": "#next-btn", "result": ".btn-print", "result_P1": ".btn-print", "result_P2": ".btn-print", "result_P3": ".btn-print", "result_P5": ".btn-print", "result_open_P3": ".dt-close", "result_remind": "#rm-send", "result_open": ".dt-close", "typesheet": "#next-btn", "proxy_q1": "#next-btn"}
for _n in ("q1_emd", "q2_crop", "q2b_crop2", "q2b_picked", "q2_x2", "q3_person", "q4_mgmt", "q5_sell", "q6_press", "q6_press_own", "q3_hint", "q6_hint"):
    MAIN_BTN[_n] = "#next-btn"
for _n in ("sp_list", "sp_list_f", "sp_table", "sp_table_one", "sp_nolink", "sp_hold", "sp_new", "sp_new_list", "sp_allow"):
    MAIN_BTN[_n] = ".actionbar .btn-main"
# 모든 창 크기에서 눈에 보여야 하는 단추(좁은 창에서는 아래로 스크롤해야 닿는 것까지 허용하고, 가려지지만 않으면 된다)
EXTRA_VISIBLE = {"home": ["a.btn-all"]}
ONE_SCREEN_AT_BIG = {"sp_table_one"} | RESULT_BIG_ONE       # 한 줄짜리 지원 안내는 1920x940에서 스크롤 없이 한 화면(긴 안내는 스크롤을 허용)
# 지원 전체 보기·안내의 새 틀(설계서 2026-11-14-supports-readability-spec, 2차: 목록을 표로)을 지키는지: 목록은 표 한 장이고 표 줄 하나가 하나의 링크(높이 76px 이상(끝난 것·시기 모름은 64px),
# 줄 전체가 눌림), 머리 줄이 위에 붙는다, 묶음 사이 32px 이상(첫 묶음 16px), 가실 곳(어디서 신청해요) 칸 글 20px 이상, 접는 칸 누르는 곳 48px 이상,
# 안내의 한눈에 띠와 '누가 받나요'. 글자 20px 미만은 없다. 첫 화면에 줄이 몇 개 보이는지는 보지 않는다(빽빽하게 만들지 않는다).
SP_JS = """() => {
  const ab = document.querySelector('.actionbar'), top = ab ? ab.getBoundingClientRect().top : innerHeight;
  const cards = [...document.querySelectorAll('tr.sp-row')];
  const low = cards.filter(a => a.getBoundingClientRect().height < (a.classList.contains('is-low') ? 63.5 : 75.5)).length;
  const bandGap = [...document.querySelectorAll('.sp-gh')].map((h, i) => { const g = h.closest('section').previousElementSibling, prev = g ? g.getBoundingClientRect().bottom : 0; return {gap: h.getBoundingClientRect().top - prev, first: i === 0, hgt: h.getBoundingClientRect().height}; });
  const gapBad = bandGap.filter(x => x.gap < (x.first ? 15.5 : 39.5) || x.hgt < 55.5).length;
  const wheres = [...document.querySelectorAll('.sp-where')], whereBad = wheres.filter(p => { const c = getComputedStyle(p); return parseFloat(c.fontSize) < 19.99 || parseInt(c.fontWeight) < 500; }).length + cards.filter(tr => !tr.querySelector('.sp-c-where .sp-where')).length;
  const nested = cards.filter(a => a.querySelectorAll('a').length !== 1).length;
  const wide = cards.filter(tr => { const a = tr.querySelector('a.sp-card'); const b = tr.getBoundingClientRect(), c = document.elementFromPoint(b.right - 20, Math.min(Math.max(b.top + b.height / 2, 1), innerHeight - 1)); return b.bottom <= top + 1 && b.top >= 0 && c !== a && !(c && a.contains(c)); }).length;
  const boxes = [...document.querySelectorAll('.sp-bx')], sticky = boxes.length ? boxes.every(b => b.querySelector('thead th') && b.firstElementChild.matches('h2.sp-gh')) : null;   // 상자마다 제목 띠가 첫 요소이고 칸 머리 줄이 있다(4차: 머리 줄은 상자마다 되풀이)
  const cols = new Set(cards.map(tr => [...tr.children].map(c => Math.round(c.getBoundingClientRect().width)).join(','))).size;
  const sums = [...document.querySelectorAll('.sp-fold summary')].filter(e => e.getBoundingClientRect().height < 47.5).length;
  const small = [];
  for (const e of document.querySelectorAll('.spmain *')) {
    if (e.closest('svg, [hidden]') || !e.getClientRects().length) continue;
    if ([...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) && parseFloat(getComputedStyle(e).fontSize) < (e.matches('.sp-tab .sp-new') ? 17.99 : 19.99)) small.push(e.className || e.tagName);
  }
  const shown = (sel) => { const e = document.querySelector(sel); if (!e) return null; const b = e.getBoundingClientRect(); return b.top >= 0 && b.bottom <= top + 1; };
  return {rows: cards.filter(a => a.getBoundingClientRect().bottom <= top + 1 && a.getBoundingClientRect().top >= 0).length, total: cards.length, low, gapBad, whereBad, nested, wide, sticky, cols, sums, small: small.slice(0, 4),
          glance: shown('.sp-glance'), who: shown('.sp-who')};
}"""
SP_ONE_VIEW = {"sp_table_one", "sp_allow"}            # 1536x730 에서 한눈에 띠와 '누가 받나요'가 스크롤 없이 보이는 안내
# 확인 화면(어르신 기준 2026-11-15): 상자마다 제목 띠(24px 이상, 상자 사이 32px 이상), 카드 이름 24px·설명 20px 이상·높이 76px 이상·카드 사이 12px 이상,
# 선택 칸 40px 이상이 이름 앞(왼쪽), 고르면 굵은 검정 테두리 + 체크, 폭 900 이상은 두 칸·미만은 한 칸, 세로 스크롤은 허용하되 가로 스크롤 없음,
# 끝까지 내리면 아래 띠가 마지막 상자를 가리지 않는다, 어디에도 18px 미만 글씨가 없다.
CONFIRM_JS = """(w) => {
  const bad = [], r = (e) => e.getBoundingClientRect(), fs = (e) => parseFloat(getComputedStyle(e).fontSize);
  const boxes = [...document.querySelectorAll('.c-box')].filter((b) => b.getClientRects().length);
  if (boxes.length < 2) bad.push('상자 ' + boxes.length);
  boxes.forEach((b, i) => {
    const band = b.firstElementChild;
    if (!band || !band.matches('h2.c-band')) bad.push('제목 띠가 첫 요소 아님');
    else if (fs(band) < 23.99) bad.push('띠 글씨 ' + fs(band));
    if (i && r(b).top - r(boxes[i - 1]).bottom < 31.5) bad.push('상자 사이 ' + Math.round(r(b).top - r(boxes[i - 1]).bottom));
  });
  const faces = [...document.querySelectorAll('.c-cards .choice-face')];
  faces.forEach((f) => {
    if (r(f).height < 75.5) bad.push('카드 높이 ' + Math.round(r(f).height));
    const m = f.querySelector('.choice-mark'), l = f.querySelector('.choice-label'), s = f.querySelector('.choice-sub');
    if (r(m).width < 39.5 || r(m).height < 39.5) bad.push('선택 칸 ' + Math.round(r(m).width));
    if (r(m).right > r(l).left + 1) bad.push('선택 칸이 이름 앞이 아님');
    if (fs(l) < 23.99) bad.push('이름 글씨 ' + fs(l));
    if (s && fs(s) < 19.99) bad.push('설명 글씨 ' + fs(s));
  });
  const li = [...document.querySelectorAll('.c-cards > li')];
  for (let i = 0; i < li.length; i++) for (let j = i + 1; j < li.length; j++) {
    const a = r(li[i]), b = r(li[j]);
    const gx = Math.max(b.left - a.right, a.left - b.right), gy = Math.max(b.top - a.bottom, a.top - b.bottom);
    if (a.top < b.bottom && b.top < a.bottom ? gx < 11.5 && gx > -1 : (a.left < b.right && b.left < a.right ? gy < 11.5 && gy > -1 : false)) { bad.push('카드 사이 좁음'); i = li.length; break; }
  }
  const cols = new Set(li.map((e) => Math.round(r(e).left))).size;
  if (w >= 900 && li.length > 1 && cols !== 2) bad.push('두 칸 아님 ' + cols);
  if (w < 900 && cols !== 1) bad.push('한 칸 아님 ' + cols);
  for (const e of document.querySelectorAll('.cbody *, .actionbar *')) {
    if (e.closest('svg, [hidden]') || !e.getClientRects().length) continue;
    if ([...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && fs(e) < 17.99) bad.push('18px 미만 ' + (e.className || e.tagName));
  }
  window.scrollTo(0, document.documentElement.scrollHeight);
  const bar = document.querySelector('.actionbar'), last = boxes[boxes.length - 1];
  if (last && bar && r(last).bottom > r(bar).top + 1) bad.push('아래 띠가 마지막 상자를 가림');
  window.scrollTo(0, 0);
  return bad.slice(0, 6);
}"""
CONFIRM_PICKED_JS = """() => {
  const input = document.querySelector('.c-cards input[type=checkbox]'); input.click();
  const f = input.nextElementSibling, m = f.querySelector('.choice-mark'), cs = getComputedStyle(f);
  const n = document.querySelector('[data-count]');
  const bad = [];
  if (parseFloat(cs.borderTopWidth) < 5.99 || cs.borderTopColor !== 'rgb(43, 39, 36)') bad.push('고른 카드 테두리 ' + cs.borderTopWidth + ' ' + cs.borderTopColor);
  if (getComputedStyle(m.querySelector('svg')).opacity !== '1') bad.push('체크 안 보임');
  if (!n || !/1가지 골랐어요/.test(n.textContent)) bad.push('개수 글 ' + (n && n.textContent));
  return bad;
}"""
NUMPAD = {"q2_numpad": 'input[name="crop1_area_py"]', "q3_numpad": 'input[name="birth_year"]'}

JS_CHECK = """() => {
  const W = innerWidth, H = innerHeight;
  const vis = (e) => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0'; };
  const clippedByAncestor = (e) => { for (let a = e.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
      const o = getComputedStyle(a).overflowX; if (o !== 'visible') return true; } return false; };
  const out = [];
  for (const e of document.querySelectorAll('body *')) {
    if (e.closest('svg') && e.tagName.toLowerCase() !== 'svg') continue;
    if (e.closest('.pv-box, .sr, .numpad[hidden], [hidden]')) continue;
    if (!vis(e)) continue;
    const r = e.getBoundingClientRect();
    if ((r.right > W + 1 || r.left < -1) && !clippedByAncestor(e)) out.push((e.className && e.className.baseVal === undefined ? '.' + String(e.className).split(' ')[0] : e.tagName) + ':' + Math.round(r.left) + '..' + Math.round(r.right));
  }
  // 글자 크기: 글이 들어 있는 보이는 요소가 16px 아래이면 걸린다(종이 미리보기 안은 따로 문서라 여기 안 잡힌다)
  const small = [];
  for (const e of document.querySelectorAll('body *')) {
    if (e.closest('svg, .sr, [hidden]') || !vis(e)) continue;
    const own = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
    if (own && parseFloat(getComputedStyle(e).fontSize) < 16 - 0.01) small.push(e.tagName + ':' + String(e.className).split(' ')[0] + '=' + getComputedStyle(e).fontSize);
  }
  // 단추 높이
  const short = [];
  for (const e of document.querySelectorAll('.btn, .tab, .choice-face, .numkey')) {
    if (!vis(e)) continue;
    if (e.getBoundingClientRect().height < 51.5) short.push(String(e.className).split(' ')[0] + '=' + Math.round(e.getBoundingClientRect().height));
  }
  // 단추끼리 겹침
  // (스크롤 칸 밖으로 잘려 안 보이는 부분은 뺀다)
  const shown = (e) => { let r = e.getBoundingClientRect(); let L = r.left, T = r.top, R = r.right, B = r.bottom;
    for (let a = e.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
      const cs = getComputedStyle(a); if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
      const q = a.getBoundingClientRect(); L = Math.max(L, q.left); T = Math.max(T, q.top); R = Math.min(R, q.right); B = Math.min(B, q.bottom); }
    return (R > L && B > T) ? {left: L, top: T, right: R, bottom: B} : null; };
  const bs = [...document.querySelectorAll('.btn, .tab, .choice-face, .numkey')].filter(e => vis(e) && !e.closest('.actionbar, .numpad') && (!document.querySelector('.rm-modal:not([hidden]), .dt.open') || e.closest('.rm-modal, .dt.open'))).map(shown).filter(x => x);   // 아래 고정 띠·숫자판은 스크롤 내용 위에 얹히는 것이라 뺀다
  let overlap = 0;
  for (let i = 0; i < bs.length; i++) for (let j = i + 1; j < bs.length; j++) {
    const a = bs[i], b = bs[j];
    const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left), oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    if (ox > 4 && oy > 4) overlap++;
  }
  // 안쪽 넘침(한 화면이어야 할 때 쓴다)
  const inner = [];
  for (const sel of ['body', 'main', '.steps', '.qstep.is-current', '.home', '.hero', '.hero-text', '.lower', '.work', '.smain', '.s-wrap']) {
    const e = document.querySelector(sel); if (!e || !vis(e)) continue;
    const own = e.matches('.qstep[data-step="6"]') || (sel === '.steps' && document.querySelector('.qstep.is-current[data-step="6"]'));   // 마지막 질문은 낮은 창에서 스스로 스크롤한다(글씨를 줄이지 않는다)
    if (e.scrollHeight > e.clientHeight + 1 && !(own && getComputedStyle(document.querySelector('.qstep[data-step="6"]')).overflowY === 'auto')) inner.push(sel + ':' + e.scrollHeight + '>' + e.clientHeight);
  }
  return {offscreen: out.slice(0, 5), nOff: out.length, small: small.slice(0, 5), nSmall: small.length, short: short.slice(0, 5), nShort: short.length, overlap, inner};
}"""


# 결과 화면(3차) 검사: 글씨 하한(px) · 가실 곳 그림 크기 · 맨 아래까지 내렸을 때 아래 띠가 내용 끝을 가리지 않음. 끝에 다시 맨 위로 올려 둔다.
RESULT_JS = """() => {
  const wide = document.documentElement.clientWidth >= 1000;
  const floors = {'.rr-name': wide ? 28 : 24, '.rr-todo .rt-t': 26, '.rr-tel b': 22, '.rr-checks .rt-t': 20, '.rg-t': 24, '.rg-m:not(.is-text)': 28, '.rg-m.is-text': 24, '.rr-ph small': 24, '.rx-when': 22, '.rx-urgent b': 22, '.rx': 20, '.rbar-note': 20, '.rn-note': 20, '.know-t': 22, '.know li': 20, '.rb-sub': 20, '.rb-who': 20};
  const bad = [];
  for (const [s, f] of Object.entries(floors)) {
    const v = [...document.querySelectorAll(s)].filter(e => e.offsetParent).map(e => parseFloat(getComputedStyle(e).fontSize));
    if (v.length && Math.min(...v) < f - 0.01) bad.push(s + ':' + Math.min(...v));
  }
  const pics = [...document.querySelectorAll('.rr-pic svg')].map(e => e.getBoundingClientRect().width);
  const picMin = wide ? 64 : 56;
  const rows = document.querySelectorAll('.rr').length;
  window.scrollTo(0, document.documentElement.scrollHeight);
  const bar = document.querySelector('.rbar').getBoundingClientRect();
  const ends = [...document.querySelectorAll('.know, .rrows .rr:last-child')].filter(e => e.offsetParent).map(e => e.getBoundingClientRect().bottom);
  const covered = ends.length ? Math.max(...ends) > bar.top + 1 : false;
  const barBottom = bar.bottom <= window.innerHeight + 1;
  window.scrollTo(0, 0);
  return {bad, pic: pics.length ? Math.min(...pics) : 0, picMin, rows, covered, barBottom};
}"""


def _in_view(page, sel, h, w):
    box = page.evaluate("(s) => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return [r.top, r.bottom, r.left, r.right]; }", sel)
    return box is not None and box[0] >= -1 and box[1] <= h + 1 and box[2] >= -1 and box[3] <= w + 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--shots", default=None)
    ap.add_argument("--notice-base", default=None, help="새 공고가 올라 있는 서버(sp_new 화면용)")
    ap.add_argument("--only", default=None, help="화면 이름 하나만")
    ap.add_argument("--sizes", default=None, help="예: 420x800,1024x768 만 점검")
    ap.add_argument("--hold-html", default=None, help="인쇄 보류 화면을 미리 만들어 둔 HTML 파일")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    sizes = ALL_SIZES
    if args.sizes:
        sizes = [tuple(int(v) for v in t.split("x")) for t in args.sizes.split(",")]
    hold_html = Path(args.hold_html).read_text(encoding="utf-8") if args.hold_html else None
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    rows, bad = [], 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, path, prep in SCREENS:
            if args.only and args.only != name:
                continue
            if name == "hold" and hold_html is None:
                continue
            if name in NOTICE_SCREENS and not args.notice_base:
                continue
            base = (args.notice_base if name in NOTICE_SCREENS else args.base).rstrip("/")
            for w, h in sizes:
                ctx = browser.new_context(viewport={"width": w, "height": h})
                page = ctx.new_page()
                if name == "hold":
                    page.route("**/__hold", lambda r: r.fulfill(status=200, body=hold_html, content_type="text/html; charset=utf-8"))
                last = None
                for _ in range(3):
                    try:
                        page.goto(base + path, wait_until="load", timeout=15000)
                        break
                    except Exception as e:  # 이 PC는 가끔 localhost 연결이 실패한다
                        last = e
                        page.wait_for_timeout(2500)
                else:
                    raise last
                page.wait_for_timeout(300)
                page.set_default_timeout(6000)
                try:
                    (prep or _noop)(page)
                except Exception as e:   # 단추가 가려져 눌리지 않는 것도 깨짐이다
                    bad += 1
                    rows.append((name, f"{w}x{h}", 0, 0, "FAIL 준비 동작 실패(단추가 안 보이거나 가려짐): " + str(e).splitlines()[0][:90]))
                    if shots:
                        page.screenshot(path=str(shots / f"{name}_{w}x{h}.png"))
                    ctx.close()
                    continue
                page.wait_for_timeout(200)
                sh, sw = page.evaluate("[document.documentElement.scrollHeight, document.documentElement.scrollWidth]")
                # data-fit 표시가 붙은 칸은 내용이 칸 밖으로 넘치면(겹침·잘림) 실패로 본다
                clipped = page.evaluate("[...document.querySelectorAll('[data-fit]')].filter(e => (e.scrollHeight > e.clientHeight + 1 && getComputedStyle(e).overflowY !== 'auto') || e.scrollWidth > e.clientWidth + 1).length")   # 스스로 스크롤하는 칸(마지막 질문의 낮은 창)은 넘침이 아니다
                chk = page.evaluate(JS_CHECK)
                old = (w, h) in SIZES
                narrow = w < 1000
                wide_one = (w >= 1000 and h >= 560 and name in ONE_SCREEN_WIDE) or (name in RESULT_ONE and w >= 1280 and h >= 600) or (name == "home" and w >= 768 and h >= 700)
                fails = []
                miss = []
                if name in SCROLL_OK and old:
                    need = SCROLL_OK[name] + (FIRST_VIEW_BIG.get(name, []) if (w, h) == SIZES[0] else [])
                    for sel in need:
                        box = page.evaluate("(s) => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return [r.top, r.bottom]; }", sel)
                        if box is None or box[0] < 0 or box[1] > h + 1:
                            miss.append(sel)
                    if sw > w:
                        fails.append("가로 스크롤")
                else:
                    if old or wide_one:
                        if sh > h:
                            fails.append(f"세로 스크롤 {sh}>{h}")
                        if chk["inner"]:
                            fails.append("안쪽 넘침 " + ",".join(chk["inner"]))
                    if sw > w:
                        fails.append("가로 스크롤")
                if miss:
                    fails.append("첫 화면 밖: " + ", ".join(miss))
                if clipped:
                    fails.append(f"칸 넘침 {clipped}")
                if not old:
                    if chk["nOff"]:
                        fails.append("창 밖 요소 " + ";".join(chk["offscreen"]))
                    sel = MAIN_BTN.get(name)
                    if sel and not _in_view(page, sel, h, w):
                        fails.append(f"주 단추 안 보임 {sel}")
                    if name in NUMPAD:
                        # 숫자판이 떠 있어도 입력 칸·숫자판이 창 안에 있고 서로 가리지 않는다
                        r = page.evaluate("""(s) => { const i = document.querySelector(s).getBoundingClientRect(); const n = document.querySelector('.numpad'); const nr = n ? n.getBoundingClientRect() : null;
                            return {i: [i.top, i.bottom], n: nr ? [nr.top, nr.bottom] : null}; }""", NUMPAD[name])
                        if r["n"] is None or r["i"][0] < -1 or r["i"][1] > r["n"][0] + 1 or r["n"][1] > h + 1:
                            fails.append(f"숫자판·입력칸 {r}")
                    if chk["overlap"]:
                        fails.append(f"단추 겹침 {chk['overlap']}")
                    if chk["nSmall"]:
                        fails.append("16px 미만 글 " + ";".join(chk["small"][:3]))
                    if narrow and name not in ("notfound", "notice") and chk["nShort"]:
                        fails.append("52px 미만 단추 " + ";".join(chk["short"][:3]))
                for sel in EXTRA_VISIBLE.get(name, []):
                    if old or wide_one:
                        if not _in_view(page, sel, h, w):
                            fails.append(f"단추 안 보임 {sel}")
                    elif not page.is_visible(sel):
                        fails.append(f"단추 가려짐 {sel}")
                if name == "confirm":
                    cb = page.evaluate(CONFIRM_JS, w) + page.evaluate(CONFIRM_PICKED_JS)
                    if cb:
                        fails.append("확인 화면 " + "; ".join(cb))
                if name == "working":
                    wt = page.evaluate("document.querySelector('.work').innerText")
                    gone = [x for x in ("쉬운 말로", "풀고", "대조", "검사", "AI가") if x in wt]
                    if gone or "받을 수 있는 지원을 찾고 있어요" not in wt:
                        fails.append("찾는 중 글 " + str(gone or "한 가지 뜻 아님"))
                if name.startswith("sp_"):
                    spc = page.evaluate(SP_JS)
                    if spc["low"]:
                        fails.append(f"낮은 줄 {spc['low']}(76px 미만, 끝난 것은 64px 미만)")
                    if spc["gapBad"]:
                        fails.append(f"상자 사이 40px 미만 또는 제목 띠 56px 미만 {spc['gapBad']}")
                    if spc["whereBad"]:
                        fails.append(f"가실 곳 칸이 없거나 글 20px/굵기 500 미달 {spc['whereBad']}")
                    if spc["nested"]:
                        fails.append("줄의 링크가 하나가 아님")
                    if spc["wide"]:
                        fails.append("줄 오른쪽 끝을 눌러도 줄 링크가 아님")
                    if spc["sticky"] is False:
                        fails.append("상자에 제목 띠 또는 칸 머리 줄이 없음")
                    if spc["cols"] > 1 and w >= 760:
                        fails.append(f"칸 폭이 줄마다 다름 {spc['cols']}")
                    if spc["sums"]:
                        fails.append("접는 칸 누르는 곳 48px 미만")
                    if spc["small"]:
                        fails.append("20px 미만 글 " + ";".join(spc["small"]))
                    if name in SP_ONE_VIEW and (w, h) == (1536, 730) and not (spc["glance"] and spc["who"]):
                        fails.append("한눈에 띠·누가 받나요가 첫 화면 밖")
                if name in RESULT_NAMES:
                    rj = page.evaluate(RESULT_JS)
                    if rj["bad"]:
                        fails.append("결과 글씨 하한 미달 " + ";".join(rj["bad"]))
                    if rj["pic"] < rj["picMin"] - 0.01:
                        fails.append(f"가실 곳 그림 {rj['pic']:.0f}px < {rj['picMin']}px")
                    if rj["covered"]:
                        fails.append("아래 띠가 내용 끝을 가림")
                    if not rj["barBottom"]:
                        fails.append("아래 띠가 창 아래에 붙어 있지 않음")
                if (w, h) == SIZES[0] and name in ONE_SCREEN_AT_BIG and sh > h:
                    fails.append(f"1920x940에서 한 화면이 아님 {sh}>{h}")
                ok = not fails
                bad += 0 if ok else 1
                rows.append((name, f"{w}x{h}", sh, sw, ("PASS" if ok else "FAIL " + " | ".join(fails))))
                if shots:
                    page.screenshot(path=str(shots / f"{name}_{w}x{h}.png"))
                ctx.close()
        browser.close()
    print(f"{'screen':<14}{'window':<11}{'scrollH':>8}{'scrollW':>9}  result")
    for r in rows:
        print(f"{r[0]:<14}{r[1]:<11}{r[2]:>8}{r[3]:>9}  {r[4]}")
    print("ALL PASS" if not bad else f"{bad} FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
