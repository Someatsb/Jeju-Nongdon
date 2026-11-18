"""새 공고 맞춰 보기 도구 - 검수 지적 반영 시험(숫자 곁 낱말, 부분 제출 보관, 해요체 단정, 알 수 없음 글, 인용 뜻)."""
import pytest
from conftest import AS_OF
from match_fixtures import CROPS, FTA, LOAN, NOTICES, ORG_FERT, custom_notice, profile

from app.tools.match_tools import MatchTools
from app.tools.models import ToolLog

FTA_Q = "2027년 FTA기금 과수(감귤) 고품질시설현대화 지원사업"
PERIOD = "2026. 11. 9.(월) ~ 11. 23.(월)"


def setup(notices=None, **over):
    t = MatchTools(profile(**over), list(notices or NOTICES.values()), CROPS, AS_OF)
    return t, t.registry(), ToolLog()


def ask(reg, log, key, kind, quote, **kw):
    return reg.dispatch("check_farmer", {"notice_key": key, "kind": kind, "quote": quote, **kw}, log)


def submit(reg, log, *items):
    return reg.dispatch("submit_matches", {"items": list(items)}, log)


# --- 숫자는 그 종류의 낱말 바로 곁에 있어야 한다 ----------------------------------------------

@pytest.mark.parametrize("kind,number,extra", [
    ("나이 이상", 9, {}), ("나이 이상", 11, {}), ("나이 이하", 23, {}), ("나이 이상", 2026, {}),
    ("넓이 이상", 9, {"unit": "평"}), ("넓이 이상", 9, {"unit": "ha"}),
    ("농사 햇수 이상", 9, {}), ("제주 거주 햇수 이상", 23, {}),
])
def test_date_numbers_cannot_be_used_as_age_area_or_years(kind, number, extra):
    n = custom_notice(apply_period=PERIOD)
    _, reg, log = setup([n])
    rec = ask(reg, log, n.key, kind, PERIOD, number=number, **extra)
    assert not rec.ok and "곁" in rec.error


def test_year_in_a_title_is_not_a_years_criterion():
    _, reg, log = setup()
    assert not ask(reg, log, FTA, "농사 햇수 이상", FTA_Q, number=2027).ok


def test_unit_must_be_the_one_right_after_the_number():
    q = "지원대상: 농사짓는 땅 5,000㎡ 이상 또는 0.5ha 이하 농업인"
    n = custom_notice(target=q)
    _, reg, log = setup([n])
    assert not ask(reg, log, n.key, "넓이 이상", q, number=5000, unit="ha").ok
    assert not ask(reg, log, n.key, "넓이 이상", q, number=5000, unit="평").ok
    assert ask(reg, log, n.key, "넓이 이상", q, number=5000, unit="㎡").ok
    assert ask(reg, log, n.key, "넓이 이하", q, number=0.5, unit="ha").ok


def test_age_needs_se_right_after_number():
    q = "지원대상: 만 65세 이상, 신청 9일 전"
    n = custom_notice(target=q)
    _, reg, log = setup([n])
    assert not ask(reg, log, n.key, "나이 이상", q, number=9).ok
    assert ask(reg, log, n.key, "나이 이상", q, number=65).ok


def test_numeric_questions_are_capped_across_notices():
    notices = [custom_notice(f"new-a{i}", target=f"지원대상: 만 {60 + i}세 이상 농업인") for i in range(12)]
    t = MatchTools(profile(), notices, CROPS, AS_OF, max_total=30)
    reg, log = t.registry(), ToolLog()
    oks = [ask(reg, log, n.key, "나이 이상", n.target, number=60 + i).ok for i, n in enumerate(notices)]
    assert oks[:10] == [True] * 10 and oks[10:] == [False, False]
    again = ask(reg, log, notices[0].key, "나이 이상", notices[0].target, number=60)
    assert again.ok                                                     # 앞에서 물은 것은 같은 답(횟수에 세지 않는다)
    other = ask(reg, log, notices[10].key, "나이 이하", notices[10].target, number=70)
    assert not other.ok and "나이" in other.error                       # 이상·이하는 한 묶음으로 센다


# --- 첫 제출 일부만 걸려도 통과한 글은 보관 --------------------------------------------------

def with_two():
    t, reg, log = setup([NOTICES[FTA], NOTICES[LOAN]])
    assert ask(reg, log, FTA, "작물", FTA_Q, crops=["감귤"]).ok
    assert ask(reg, log, LOAN, "그 밖", NOTICES[LOAN].target).ok
    return t, reg, log


def test_passed_items_of_a_failed_first_submit_are_kept():
    t, reg, log = with_two()
    loan = {"notice_key": LOAN, "why": "창업 계획이 있는 분이 대상이라 맞는지 알 수 없어요", "ask": ["사업 계획이 필요한지"]}
    first = submit(reg, log, {"notice_key": FTA, "why": "꼭 받아요", "ask": []}, loan)
    assert not first.ok and not t.done
    second = submit(reg, log, {"notice_key": FTA, "why": "감귤 농가가 신청하는 사업이라 맞을 수 있어요", "ask": []})
    assert second.ok and t.done
    assert FTA in t.submitted and t.submitted[LOAN][1] == ("사업 계획이 필요한지",) and not t.defaulted


def test_second_submit_wins_and_unresubmitted_failure_is_counted_as_default():
    t, reg, log = with_two()
    assert not submit(reg, log, {"notice_key": FTA, "why": "꼭 받아요", "ask": []},
                      {"notice_key": LOAN, "why": "맞는지 알 수 없어요", "ask": ["하나"]}).ok
    assert submit(reg, log, {"notice_key": LOAN, "why": "맞는지 알 수 없어요", "ask": ["둘"]}).ok
    assert t.submitted[LOAN][1] == ("둘",) and t.defaulted == {FTA}


# --- 해요체 단정, 한글 금액·한글 숫자 ---------------------------------------------------------

def fit_tools():
    t, reg, log = setup()
    assert ask(reg, log, FTA, "작물", FTA_Q, crops=["감귤"]).ok
    return t, reg, log


@pytest.mark.parametrize("why", ["감귤 농가라서 시설비를 받을 수 있어요", "시설비를 받으실 수 있어요", "시설비를 지원받게 돼요", "꼭 받아요",
                                 "돈이 나와요", "시설비를 지원해요", "감귤 농가라 꼭 맞아요", "지원돼요", "무조건 맞을 수 있어요"])
def test_haeyo_style_assertions_are_refused(why):
    t, reg, log = fit_tools()
    rec = submit(reg, log, {"notice_key": FTA, "why": why, "ask": []})
    assert not rec.ok and "단정" in rec.error


@pytest.mark.parametrize("why,part", [("수백만 원을 지원해 줄 수도 있어요", "금액"), ("수천만원이 들어요", "금액"),
                                      ("나이가 예순다섯 살이라 맞을 수 있어요", "숫자"), ("삼십만 원이 필요해요", "금액")])
def test_hangul_money_and_hangul_numbers_are_refused(why, part):
    t, reg, log = fit_tools()
    rec = submit(reg, log, {"notice_key": FTA, "why": why, "ask": []})
    assert not rec.ok and part in rec.error


def test_hedge_haeyo_is_still_fine():
    t, reg, log = fit_tools()
    assert submit(reg, log, {"notice_key": FTA, "why": "감귤 농가라 맞을 수 있어요", "ask": ["농협에서 받는지"]}).ok


# --- 알 수 없음 · 확인 0번 · 확인하지 않은 조건 ------------------------------------------------

def test_submit_without_any_check_is_sent_back():
    t, reg, log = setup()
    rec = submit(reg, log, {"notice_key": FTA, "why": "감귤 농가라 맞을 수 있어요", "ask": []})
    assert not rec.ok and "확인" in rec.error and not t.done


def test_unknown_verdict_always_gets_the_default_sentence_but_keeps_asks():
    t, reg, log = setup()
    assert ask(reg, log, ORG_FERT, "그 밖", NOTICES[ORG_FERT].target).ok
    assert submit(reg, log, {"notice_key": ORG_FERT, "why": "감귤 농가라 맞을 수 있어요", "ask": ["인증이 필요한지"]}).ok
    why, asks = t.submitted[ORG_FERT]
    assert why == "맞는지 아직 알 수 없어요. 조건은 창구에서 확인하세요" and asks == ("인증이 필요한지",)


def test_fit_text_cannot_claim_an_unconfirmed_condition():
    t, reg, log = fit_tools()
    rec = submit(reg, log, {"notice_key": FTA, "why": "감귤 농가이고 나이도 맞을 수 있어요", "ask": []})
    assert not rec.ok and "확인하지 않은" in rec.error
    assert submit(reg, log, {"notice_key": FTA, "why": "감귤 농가라 맞을 수 있어요", "ask": ["나이 조건이 있는지"]}).ok


# --- 인용이 그 종류를 실제로 말해야 한다 --------------------------------------------------------

def test_quote_must_speak_about_the_kind():
    t, reg, log = setup()
    bad = ask(reg, log, FTA, "경영체 등록", FTA_Q)
    assert not bad.ok and "말하는" in bad.error
    assert not ask(reg, log, FTA, "땅 소유", FTA_Q).ok
    assert not ask(reg, log, FTA, "농협 출하", FTA_Q).ok


def test_disaster_without_sixty_days_is_unknown():
    q = "지원대상: 최근 60일 안에 재해 피해를 입은 농업인"
    q2 = "지원대상: 재해 피해 농가"
    n = custom_notice(target=q + "\n" + q2)
    _, reg, log = setup([n])
    a = ask(reg, log, n.key, "최근 재해 피해", q2)
    assert a.ok and a.result["answer"] == "답에 없음"
    b = ask(reg, log, n.key, "최근 재해 피해", q)
    assert b.ok and b.result["answer"] == "아니오"
