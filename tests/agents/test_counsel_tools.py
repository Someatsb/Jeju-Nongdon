"""상담 도구 3개(Task 28): 이름·보험 설명은 숫자 없이, 형식 오류는 한국어 오류 기록으로."""
import re

from counsel_fixtures import BUNDLE, good_section

from app.tools.counsel_tools import CounselTools
from app.tools.models import ToolLog

TOOLS = CounselTools(BUNDLE)
REG = TOOLS.registry()
DIGIT = re.compile(r"[0-9０-９①-⑳]")


def call(name, **args):
    return REG.dispatch(name, args, ToolLog())


def test_three_tools_registered_without_digits_in_schemas():
    assert [s["name"] for s in REG.schemas()] == ["get_program_detail", "get_product_detail", "submit_narrative"]
    assert not DIGIT.search(str([s["description"] for s in REG.schemas()]))


def test_program_detail_known_and_unknown():
    pid = next(p.id for p in BUNDLE.programs if p.name == "제주 농민수당")
    rec = call("get_program_detail", id=pid)
    assert rec.ok and rec.result["name"] == "제주 농민수당" and rec.result["needs_mgmt"] is True
    assert not DIGIT.search(str({k: v for k, v in rec.result.items() if k != "id"}))
    bad = call("get_program_detail", id="NOPE")
    assert not bad.ok and "제도가 없습니다" in bad.error


def test_product_detail_real_product():
    rec = call("get_product_detail", id="crop_disaster:양배추")
    assert rec.ok and rec.result["label"] == "농작물재해보험" and rec.result["crops"] == ["양배추"]
    assert rec.result["needs_mgmt"] is True and rec.result["office_id"]
    assert not DIGIT.search(str(rec.result))
    assert call("get_product_detail", id="nh_safety").ok


def test_product_detail_unknown_is_korean_error():
    rec = call("get_product_detail", id="crop_disaster:없는작물")
    assert not rec.ok and "보험 상품이 없습니다" in rec.error
    assert not call("get_product_detail", id="nope").ok


def test_submit_narrative_roundtrip_and_error():
    ok = call("submit_narrative", section_json=good_section("support"))
    assert ok.ok and ok.result["section"]["section"] == "support"
    bad = call("submit_narrative", section_json="이건 JSON이 아닙니다")
    assert not bad.ok and "구획 형식 오류" in bad.error
