# -*- coding: utf-8 -*-
"""캡처·측정 스크립트가 함께 쓰는 입력 흐름(질문 화면 -> 확인 화면 -> 찾는 중 -> 결과 화면).
질문 화면은 단계별로 한 장씩 보여 칸이 가려져 있으므로, 칸 값을 직접 넣고 폼을 제출한다(화면에 없는 칸은 건너뜀)."""
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
FILL_JS = """(form) => {
    const f = document.getElementById('qform');
    for (const [k, v] of Object.entries(form)) {
        const els = [...f.querySelectorAll('[name="' + k + '"]')];
        if (!els.length) continue;
        const e = els[0];
        if (e.type === 'radio') { const r = els.find(x => x.value === v); if (r) { r.checked = true; r.dispatchEvent(new Event('change', {bubbles: true})); } }
        else if (e.type === 'checkbox') e.checked = (v === 'on');
        else { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); }
    }
}"""


def demo_inputs() -> dict:
    return json.load(open(APP / "data/replay/demo_inputs.json", encoding="utf8"))


def goto(page, url, tries=3):
    for i in range(tries):
        try:
            page.goto(url)
            return
        except Exception:
            if i == tries - 1:
                raise
            page.wait_for_timeout(2500)


def fill_and_submit(page, base, form):
    """질문 화면에 값을 넣고 제출해 확인 화면까지 간다."""
    goto(page, base + "/counsel/input")
    page.evaluate(FILL_JS, form)
    with page.expect_navigation():
        page.evaluate("document.getElementById('qform').requestSubmit()")
    page.wait_for_url("**/counsel/confirm")
    edu = form.get("direct_payment_education")        # 확인 화면의 '직불 교육' 칸: 녹화와 같은 입력이 되게 값을 직접 넣는다(Y·N만 화면에 있다)
    if edu in ("Y", "N"):
        page.evaluate("(v) => { const e = document.querySelector('input[name=direct_payment_education][value=\"' + v + '\"]'); if (e) { e.checked = true; e.dispatchEvent(new Event('change', {bubbles: true})); } }", edu)


def to_result(page, base, form, already=()):
    """확인 화면에서 '결과 보기'를 눌러 찾는 중 화면을 거쳐 결과 화면(/counsel/preview)까지 간다.
    already: 확인 화면의 '이미 받고 계신 지원' 칸에 누를 제도 키(demo_inputs.json의 "already"). 재생 녹화와 같은 입력이어야 AI 설명 문장이 붙는다."""
    fill_and_submit(page, base, form)
    for key in already:
        page.locator(f'input[name="already"][value="{key}"]').check(force=True)
    page.click("#next-btn")
    page.wait_for_url("**/counsel/preview", timeout=60000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
