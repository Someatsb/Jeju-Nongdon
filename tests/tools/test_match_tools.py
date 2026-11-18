"""새 공고 맞춰 보기 도구(check_farmer, submit_matches) 시험. 인터넷·실제 AI 없음."""
import pytest
from conftest import AS_OF
from match_fixtures import BIRTH, CARROT, CROPS, FTA, LOAN, NOTICES, ORG_FERT, ORG_MAT, custom_notice, profile

from app.tools.match_tools import ASSERT_WORDS, CheckFarmerIn, CheckRecord, MatchTools, verdict_of
from app.tools.models import ToolLog

FEMALE_Q = "3. 지원대상: 도내 출산(예정) 여성농업인"
FTA_Q = "2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업"
FTA_PLACE = "나. 접수처: 지역 농·감협"
ORG_PLACE = "나. 신청장소: 농지 소재지 읍면동사무소"


def setup(notices=None, **over):
    t = MatchTools(profile(**over), list(notices or NOTICES.values()), CROPS, AS_OF)
    return t, t.registry(), ToolLog()


def ask(reg, log, key, kind, quote, **kw):
    return reg.dispatch("check_farmer", {"notice_key": key, "kind": kind, "quote": quote, **kw}, log)


def answer(reg, log, key, kind, quote, **kw) -> str:
    rec = ask(reg, log, key, kind, quote, **kw)
    assert rec.ok, rec.error
    return rec.result["answer"]


def test_fixture_notices_are_five_with_official_urls():
    assert len(NOTICES) == 5
    assert all(n.url and n.url.startswith("https://www.seogwipo.go.kr/") for n in NOTICES.values())


def test_answer_is_one_of_three_words_only():
    _, reg, log = setup()
    assert ask(reg, log, FTA, "작물", FTA_Q, crops=["감귤"]).content() == '{"answer": "예"}'


def test_crop_yes_no_and_group_words():
    _, reg, log = setup()                                                    # 노지감귤 농가
    assert answer(reg, log, FTA, "작물", FTA_Q, crops=["감귤"]) == "예"
    _, reg, log = setup(crops=CARROT)
    assert answer(reg, log, FTA, "작물", FTA_Q, crops=["감귤"]) == "아니오"
    n = custom_notice(target="지원대상: 과수 또는 월동채소 재배 농가")
    _, reg, log = setup([n])                                                 # 감귤은 과수
    assert answer(reg, log, n.key, "작물", n.target, crops=["과수"]) == "예"
    assert answer(reg, log, n.key, "작물", n.target, crops=["월동채소"]) == "아니오"
    _, reg, log = setup([n], crops=CARROT)
    assert answer(reg, log, n.key, "작물", n.target, crops=["월동채소"]) == "예"


def test_crop_word_not_in_table_is_unknown_not_no():
    n = custom_notice(target="지원대상: 시설원예 농가")
    _, reg, log = setup([n], crops=CARROT)
    assert answer(reg, log, n.key, "작물", n.target, crops=["시설원예"]) == "답에 없음"


def test_city_from_eupmyeon_and_dong_is_unknown():
    n = custom_notice(target="3. 지원대상: 서귀포시 출산 여성농업인")
    for emd, want in (("남원읍", "예"), ("애월읍", "아니오"), ("노형동", "답에 없음")):
        _, reg, log = setup([n], emd_code=emd)
        assert answer(reg, log, n.key, "행정시", n.target, choice="서귀포시") == want


def test_city_name_must_be_in_quote():
    _, reg, log = setup()
    assert not ask(reg, log, ORG_MAT, "행정시", ORG_PLACE, choice="서귀포시").ok


def test_sex():
    _, reg, log = setup()                                                    # 여성
    assert answer(reg, log, BIRTH, "성별", FEMALE_Q, choice="여성") == "예"
    assert not ask(reg, log, BIRTH, "성별", FEMALE_Q, choice="남성").ok          # 인용에 없는 값은 물을 수 없다
    n = custom_notice(target="3. 지원대상: 남성 농업인")
    _, reg, log = setup([n])
    assert answer(reg, log, n.key, "성별", n.target, choice="남성") == "아니오"


def test_age():
    n = custom_notice(target="3. 지원대상: 만 65세 이상 농업인")
    _, reg, log = setup([n])                                                 # 1952년생
    assert answer(reg, log, n.key, "나이 이상", n.target, number=65) == "예"
    assert answer(reg, log, n.key, "나이 이하", n.target, number=65) == "아니오"


def test_age_at_boundary_is_unknown_because_birthday_is_unknown():
    n = custom_notice(target="3. 지원대상: 만 74세 이상 농업인")
    _, reg, log = setup([n])                                                 # 2026-1952 = 74세 또는 73세
    assert answer(reg, log, n.key, "나이 이상", n.target, number=74) == "답에 없음"


def test_area_units_convert():
    q = "지원대상: 농사짓는 땅 1,000평 이상 또는 0.5ha 이하 또는 5,000㎡ 이상"
    n = custom_notice(target=q)
    _, reg, log = setup([n])                                                 # 4,959㎡
    assert answer(reg, log, n.key, "넓이 이상", q, number=1000, unit="평") == "예"
    assert answer(reg, log, n.key, "넓이 이하", q, number=0.5, unit="ha") == "예"
    assert answer(reg, log, n.key, "넓이 이상", q, number=5000, unit="㎡") == "아니오"
    assert not ask(reg, log, n.key, "넓이 이상", q, number=1000).ok         # 단위가 없으면 거절


def test_other_kinds_from_profile():
    q = "농업경영체 등록, 농협 출하, 직장가입자, 최근 60일 재해 피해, 내 땅, 배우자, 농사 10년 이상, 제주 거주 3년 이상"
    n = custom_notice(target=q)
    t = MatchTools(profile(), [n], CROPS, AS_OF, max_per_notice=20)
    reg, log = t.registry(), ToolLog()      # 경영체 등록, 상인 밭떼기, 지역가입, 전부 내 땅, 배우자 없음, 농사 45년, 제주 3년 이상
    assert answer(reg, log, n.key, "경영체 등록", q) == "예"
    assert answer(reg, log, n.key, "농협 출하", q) == "아니오"
    assert answer(reg, log, n.key, "건강보험 종류", q, choice="직장") == "아니오"
    assert answer(reg, log, n.key, "최근 재해 피해", q) == "아니오"
    assert answer(reg, log, n.key, "땅 소유", q) == "예"
    assert answer(reg, log, n.key, "농사 햇수 이상", q, number=10) == "예"
    assert answer(reg, log, n.key, "제주 거주 햇수 이상", q, number=3) == "예"
    assert answer(reg, log, n.key, "배우자 공동 영농", q) == "아니오"


def test_unknown_profile_values_give_unknown():
    q = "농업경영체 등록, 농협 출하, 직장가입자, 내 땅, 농사 10년 이상"
    n = custom_notice(target=q)
    unknown_crop = ({"crop_code": "감귤_노지", "area_m2": 4959, "sales_channel": "unknown", "selfpay_fund": "unknown"},)
    _, reg, log = setup([n], mgmt_status="unknown", land_tenure="unknown", health_ins="unknown", birth_year=None,
                        farming_years=None, farming_10y_plus=False, owner_sex=None, crops=unknown_crop)
    assert answer(reg, log, n.key, "경영체 등록", q) == "답에 없음"
    assert answer(reg, log, n.key, "농협 출하", q) == "답에 없음"
    assert answer(reg, log, n.key, "건강보험 종류", q, choice="직장") == "답에 없음"
    assert answer(reg, log, n.key, "땅 소유", q) == "답에 없음"
    assert answer(reg, log, n.key, "농사 햇수 이상", q, number=10) == "답에 없음"


def test_other_kind_is_always_unknown_and_emd_cannot_be_asked():
    _, reg, log = setup()
    assert answer(reg, log, ORG_MAT, "그 밖", ORG_PLACE) == "답에 없음"
    bad = ask(reg, log, ORG_MAT, "읍면동", ORG_PLACE)
    assert not bad.ok and "kind" in bad.error
    kinds = CheckFarmerIn.model_json_schema()["properties"]["kind"]["enum"]
    assert "읍면동" not in kinds and "그 밖" in kinds


def test_quote_must_be_literal_in_that_notice_only():
    _, reg, log = setup()
    assert answer(reg, log, FTA, "그 밖", "나.  접수처:   지역 농·감협") == "답에 없음"          # 공백은 무시
    bad = ask(reg, log, FTA, "그 밖", "나. 접수처: 지역 농협")
    assert not bad.ok and "그대로 없어요" in bad.error
    assert not ask(reg, log, LOAN, "그 밖", FTA_PLACE).ok                                      # 다른 공고의 글
    assert not ask(reg, log, FTA, "그 밖", "신청").ok                                          # 너무 짧은 인용
    assert not ask(reg, log, "new-없는공고", "그 밖", FTA_PLACE).ok


def test_number_and_crop_words_must_be_in_quote():
    q = "지원대상: 만 65세 이상 감귤 농업인"
    n = custom_notice(target=q)
    _, reg, log = setup([n])
    assert not ask(reg, log, n.key, "나이 이상", q, number=70).ok                # 인용에 없는 숫자
    assert not ask(reg, log, n.key, "나이 이상", q).ok                           # 숫자가 없다
    assert not ask(reg, log, n.key, "작물", q, crops=["양배추"]).ok              # 인용에 없는 작물 낱말
    assert not ask(reg, log, n.key, "작물", q, crops=[]).ok
    assert answer(reg, log, n.key, "작물", q, crops=["감귤"]) == "예"


def test_per_notice_cap_is_six_and_repeats_are_free():
    t, reg, log = setup()
    n = NOTICES[ORG_FERT]
    quotes = [n.content[i:i + 12] for i in range(0, 84, 12)]                  # 서로 다른 인용 일곱 개
    assert len(set(quotes)) == 7
    for q in quotes[:6]:
        assert ask(reg, log, ORG_FERT, "그 밖", q).ok
    err = ask(reg, log, ORG_FERT, "그 밖", quotes[6])
    assert not err.ok and "횟수" in err.error
    assert ask(reg, log, ORG_FERT, "그 밖", quotes[0]).ok                     # 앞에서 물은 것과 같은 질문은 같은 답
    assert len(t.checks_of(ORG_FERT)) == 6


def test_total_cap():
    t = MatchTools(profile(), list(NOTICES.values()), CROPS, AS_OF, max_total=3)
    reg, log = t.registry(), ToolLog()
    for key in (FTA, LOAN, BIRTH):
        assert ask(reg, log, key, "그 밖", NOTICES[key].apply_period).ok
    assert not ask(reg, log, ORG_MAT, "그 밖", NOTICES[ORG_MAT].apply_period).ok
    assert MatchTools(profile(), [], CROPS, AS_OF).__dict__["_max_total"] == 24
    assert MatchTools(profile(), [], CROPS, AS_OF).__dict__["_max_per"] == 6


def test_third_value_for_same_kind_is_refused():
    q = "지원대상: 만 60세 또는 65세 또는 70세 이상 농업인"
    n = custom_notice(target=q)
    _, reg, log = setup([n])
    assert ask(reg, log, n.key, "나이 이상", q, number=60).ok
    assert ask(reg, log, n.key, "나이 이상", q, number=65).ok
    third = ask(reg, log, n.key, "나이 이상", q, number=70)
    assert not third.ok and "기준만 바꿔" in third.error
    assert ask(reg, log, n.key, "나이 이상", q, number=60).ok                  # 앞에서 물은 것을 다시 묻는 것은 같은 답
    assert ask(reg, log, n.key, "나이 이하", q, number=70).ok                  # 다른 종류는 따로 센다


def test_verdict_is_computed_from_checks():
    def rec(*answers):
        return [CheckRecord("k", "작물", "q", a, ()) for a in answers]
    assert verdict_of(rec()) == "알 수 없음"
    assert verdict_of(rec("답에 없음", "답에 없음")) == "알 수 없음"
    assert verdict_of(rec("예", "답에 없음")) == "알 수 없음"          # 답에 없음이 하나라도 있으면 알 수 없음(설계서 4절)
    assert verdict_of(rec("예", "예")) == "맞을 수 있음"
    assert verdict_of(rec("답에 없음", "예")) == "알 수 없음"
    assert verdict_of(rec("아니오", "답에 없음")) == "안 맞음"
    assert verdict_of(rec("예", "예", "아니오")) == "안 맞음"
    assert verdict_of(rec("아니오")) == "안 맞음"


def test_core_condition_never_asked_cannot_be_fit():
    """성별 예 하나만 확인하고 출산 같은 핵심 조건을 그 밖으로 묻지 않아도 맞을 수 있음이 나오면 안 된다(부장 검수)."""
    t, reg, log = setup([NOTICES[BIRTH]])
    assert answer(reg, log, BIRTH, "성별", FEMALE_Q, choice="여성") == "예"
    assert t.verdict_for(BIRTH) == "알 수 없음"
    t2, reg2, log2 = setup([NOTICES[FTA]])
    assert answer(reg2, log2, FTA, "작물", FTA_Q, crops=["감귤"]) == "예"
    assert t2.verdict_for(FTA) == "맞을 수 있음"


# --- submit_matches ---------------------------------------------------------------------------

def submit(reg, log, *items):
    return reg.dispatch("submit_matches", {"items": list(items)}, log)


def with_checks():
    t, reg, log = setup()
    assert answer(reg, log, FTA, "작물", FTA_Q, crops=["감귤"]) == "예"
    assert answer(reg, log, ORG_FERT, "그 밖", NOTICES[ORG_FERT].target) == "답에 없음"
    return t, reg, log


def test_good_submit_is_accepted_and_kept():
    t, reg, log = with_checks()
    rec = submit(reg, log, {"notice_key": FTA, "why": "감귤 농가가 신청하는 시설 사업이라 맞을 수 있어요", "ask": ["농협에서 받는지"]},
                 {"notice_key": ORG_FERT, "why": "농업경영체여야 하는데 맞는지 알 수 없어요", "ask": []})
    assert rec.ok and t.done and t.submitted[FTA][1] == ("농협에서 받는지",) and not t.defaulted


@pytest.mark.parametrize("why,part", [
    ("신청 기한이 12월 9일까지예요 9일", "숫자"),
    ("신청하면 500만 원을 지원해요", "숫자"),
    ("오십만 원을 지원해요", "금액"),
    ("이 사업은 받으실 수 있습니다", "단정"),
    ("틀림없이 맞아요", "단정"),
    ("전액 지원이라 맞을 수 있어요", "단정"),
    ("Smart farm 사업이에요", "영어"),
    ("new_fta 사업이에요", "영어"),
    ("가" * 90, "너무 길어요"),
    ("", "비었"),
])
def test_bad_text_is_refused_with_reason(why, part):
    t, reg, log = with_checks()
    rec = submit(reg, log, {"notice_key": FTA, "why": why, "ask": []})
    assert not rec.ok and part in rec.error and not t.done


def test_numbers_and_english_that_the_notice_itself_has_are_allowed():
    t, reg, log = with_checks()
    rec = submit(reg, log, {"notice_key": FTA, "why": "FTA기금 시설 사업이고 접수는 2026. 11. 9.부터예요", "ask": []})
    assert rec.ok, rec.error


def test_money_from_the_quote_is_allowed_but_other_notice_money_is_not():
    t, reg, log = setup()
    assert answer(reg, log, ORG_MAT, "그 밖", NOTICES[ORG_MAT].content.split("\n")[2]) == "답에 없음"
    ok = submit(reg, log, {"notice_key": ORG_MAT, "why": "맞는지 알 수 없어요", "ask": ["인용에 나온 (유기) 200만원/ha 지원인지"]})
    assert ok.ok, ok.error
    t, reg, log = setup()
    answer(reg, log, ORG_MAT, "그 밖", NOTICES[ORG_MAT].content.split("\n")[2])
    assert not submit(reg, log, {"notice_key": ORG_MAT, "why": "맞는지 알 수 없어요", "ask": ["단가 82,560원인지"]}).ok


def test_too_many_asks_and_unknown_key():
    t, reg, log = with_checks()
    assert not submit(reg, log, {"notice_key": FTA, "why": "맞을 수 있어요", "ask": ["가", "나", "다"]}).ok
    t, reg, log = with_checks()
    assert not submit(reg, log, {"notice_key": "new-없음", "why": "맞을 수 있어요"}).ok


def test_second_bad_submit_falls_back_to_default_for_that_notice_only():
    t, reg, log = with_checks()
    good = {"notice_key": ORG_FERT, "why": "맞는지 알 수 없어요", "ask": []}
    first = submit(reg, log, {"notice_key": FTA, "why": "꼭 받습니다", "ask": []}, good)
    assert not first.ok and not t.done
    second = submit(reg, log, {"notice_key": FTA, "why": "또 받습니다", "ask": []}, good)
    assert second.ok and t.done and t.defaulted == {FTA}
    assert FTA not in t.submitted and t.submitted[ORG_FERT][0] == "맞는지 아직 알 수 없어요. 조건은 창구에서 확인하세요"
    assert not submit(reg, log, {"notice_key": FTA, "why": "맞을 수 있어요"}).ok     # 이미 받았다


def test_text_of_not_fit_notice_is_not_checked_or_kept():
    n = custom_notice(target="3. 지원대상: 남성 농업인")
    t, reg, log = setup([n])
    assert answer(reg, log, n.key, "성별", n.target, choice="남성") == "아니오"
    rec = submit(reg, log, {"notice_key": n.key, "why": "받습니다 2026", "ask": []})
    assert rec.ok and t.submitted[n.key] == ("", ())


def test_hedge_words_are_not_caught():
    assert not any(w in "맞을수있어요조건이어울려요창구에서확인하세요" for w in ASSERT_WORDS)


def test_registry_has_two_tools_and_schema_has_no_description_digit():
    _, reg, _ = setup()
    assert [s["name"] for s in reg.schemas()] == ["check_farmer", "submit_matches"]
