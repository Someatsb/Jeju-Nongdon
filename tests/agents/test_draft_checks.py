"""공고 초안 검사 8종(Task 18) — round1-B-data.md §3-4, round2-C-agent.md §6-1 validate_draft.

검사마다 정상·위반을 한 쌍 이상 둔다. 문서는 N7(통합공고 발췌), 기존 행은 supports.csv.
  1 인용  2 값·단위  3 칸 규칙(허용값·범위·형식)  4 순서  5 기존 행  6 개인정보  7 필수 칸  8 가점 혼동
"""
import pytest
from notice_fixtures import (
    BUNDLE,
    CALC,
    DOC_N1,
    DOC_N2,
    DOC_N7,
    LOGI,
    N7_AREA,
    N7_CALC_AREA,
    N7_CALC_DOSE,
    N7_CAP,
    N7_COOP_SCORE,
    N7_INCOME,
    N7_PERIOD,
    SMALL,
    draft,
    program,
)

from app.tools.draft_checks import pii_labels, run, squash
from app.tools.models import DraftField, DraftProgram, NoticeDraft, Skipped

N7_EXCLUDE = "최근 5년 이내 동일 친서민 농정시책 사업을 지원받은 자"
N7_TARGET = "○ 지원대상: 밭작물 재배농가"
N7_TITLE = "Ⅱ.2026년사업시행주요내용"

REQUIRED_NEW = dict(name=("소형농기계 지원", "소형 농기계 지원 사업"), agency=("행정시", "읍면 사무소 및 동 주민센터"),
                    applicant=("개인", N7_TARGET), apply_cycle=("연1회", N7_PERIOD), amount_type=("보조율", N7_CAP),
                    valid_from=("2026-01-02", N7_PERIOD), valid_to=("2026-01-16", N7_PERIOD))


def codes(*programs: DraftProgram, doc=DOC_N7) -> set[tuple[str, str, str]]:
    return {(i.code, i.field, i.level) for i in run(draft(*programs), doc, BUNDLE)}


# (검사, 정상 초안, 위반 초안, 위반 때 나와야 할 (code, field, level))
PAIRS = [
    ("quote", program(income_max_manwon=(3700, N7_INCOME)),
     program(income_max_manwon=(3700, "연간 농업 외 소득 3,700만원 미만")), ("QUOTE_NOT_IN_DOC", "income_max_manwon", "RED")),
    ("quote-missing", program(income_max_manwon=(3700, N7_INCOME)),
     program(income_max_manwon=(3700, None)), ("QUOTE_MISSING", "income_max_manwon", "RED")),
    ("value-manwon", program(income_max_manwon=(3700, N7_INCOME)),
     program(income_max_manwon=(37000000, N7_INCOME)), ("VALUE_NOT_IN_QUOTE", "income_max_manwon", "RED")),
    ("value-thousand-won", program(cap_won=(7000000, N7_CAP)),
     program(cap_won=(7000, N7_CAP)), ("VALUE_NOT_IN_QUOTE", "cap_won", "RED")),
    ("value-m2-to-ha", program(min_ha=(0.1, N7_AREA)),
     program(min_ha=(1000, N7_AREA)), ("VALUE_NOT_IN_QUOTE", "min_ha", "RED")),
    ("value-date", program(apply_start=("2026-01-02", N7_PERIOD)),
     program(apply_start=("2026-02-01", N7_PERIOD)), ("VALUE_NOT_IN_QUOTE", "apply_start", "RED")),
    ("value-pct", program(rate_pct_max=(70, N7_CAP)),
     program(rate_pct_max=(75, N7_CAP)), ("VALUE_NOT_IN_QUOTE", "rate_pct_max", "RED")),
    ("schema-enum", program(applicant=("개인", N7_TARGET)),
     program(applicant=("개인농", N7_TARGET)), ("BAD_ENUM", "applicant", "RED")),
    ("schema-range", program(rate_pct_max=(70, N7_CAP)),
     program(rate_pct_max=(170, "보조율 170%")), ("OUT_OF_RANGE", "rate_pct_max", "RED")),
    ("schema-format", program(apply_start=("2026-01-02", N7_PERIOD)),
     program(apply_start=("2026. 1. 2.", N7_PERIOD)), ("BAD_VALUE", "apply_start", "RED")),
    ("schema-unknown", program(min_ha=(0.1, N7_AREA)),
     program(min_area=(0.1, N7_AREA)), ("UNKNOWN_FIELD", "min_area", "RED")),
    ("schema-corp", program(applicant=("개인", N7_TARGET)),
     program(applicant=("법인·단체", N7_TARGET)), ("NOT_INDIVIDUAL", "applicant", "YELLOW")),
    ("order", program(apply_start=("2026-01-02", N7_PERIOD), apply_end=("2026-01-16", N7_PERIOD)),
     program(apply_start=("2026-01-16", N7_PERIOD), apply_end=("2026-01-02", N7_PERIOD)), ("OUT_OF_ORDER", "apply_end", "RED")),
    ("program", program(match_id=SMALL, min_ha=(0.1, N7_AREA)),
     program(match_id="DO-NOT-THERE@2026", min_ha=(0.1, N7_AREA)), ("UNKNOWN_PROGRAM", "match_id", "RED")),
    ("program-key", program(match_id=SMALL, program_key="DO-SMALL-MACHINE", min_ha=(0.1, N7_AREA)),
     program(match_id=SMALL, program_key="JEJU-LOGI", min_ha=(0.1, N7_AREA)), ("UNKNOWN_PROGRAM", "program_key", "RED")),
    ("program-new", program("NEW", None, "DO-SMALL-MACHINE-B", **REQUIRED_NEW),
     program("NEW", None, "DO-SMALL-MACHINE", **REQUIRED_NEW), ("NEW_KEY_EXISTS", "program_key", "YELLOW")),
    ("pii", program(manual_check=("최근 다섯 해 안에 같은 친서민 사업 수혜 없음", N7_EXCLUDE)),
     program(manual_check=("담당 010-1234-5678 확인", N7_EXCLUDE)), ("PII_IN_DRAFT", "manual_check", "RED")),
    ("pii-question", program(min_ha=(0.1, N7_AREA), questions=("소득 기준 예외 대상이 누구인가요?",)),
     program(min_ha=(0.1, N7_AREA), questions=("홍길동 010-0000-0000 님 대상인가요?",)), ("PII_IN_DRAFT", "questions", "RED")),
    ("required", program(min_ha=(0.1, N7_AREA)),
     program("NEW", None, "DO-NEW-ROW", min_ha=(0.1, N7_AREA)), ("MISSING_REQUIRED", "agency", "YELLOW")),
    ("required-prior", program(status=("prior_year_reference", N7_TITLE), next_month=(1, N7_PERIOD),
                               expected_notice_month=(1, N7_PERIOD)),
     program(status=("prior_year_reference", N7_TITLE)), ("MISSING_REQUIRED", "expected_notice_month", "YELLOW")),
    ("bonus", program(min_ha=(0.1, N7_AREA)),
     program(needs_coop=("Y", N7_COOP_SCORE)), ("BONUS_AS_ELIGIBILITY", "needs_coop", "YELLOW")),
]


@pytest.mark.parametrize("name, good, bad, expected", PAIRS, ids=[p[0] for p in PAIRS])
def test_check_pair(name, good, bad, expected):
    assert codes(good) == set()
    assert expected in codes(bad)


@pytest.mark.parametrize("field, value, quote", [
    ("min_ha", 0.1, N7_CALC_AREA),           # 0.1~5ha의 앞 숫자(단위 없음)
    ("max_ha", 5, N7_CALC_AREA),
    ("max_owned_ha", 0.1, N7_CALC_DOSE),     # 10a → 0.1ha
    ("max_owned_ha", 0.0992, N7_CALC_DOSE),  # 300평 → 0.09917ha (0.5% 안)
    ("apply_end", "2026-01-16", N7_PERIOD),  # 연도 없는 끝 날짜는 앞 날짜의 해
    ("amount_value", 2000, "지원단가:분상‧입상 구분없이 2,000원/포(20kg)정액지원"),
])
def test_unit_conversions_pass(field, value, quote):
    assert codes(program(match_id=CALC, **{field: (value, quote)})) == set()


def test_value_sixteen_is_not_fifteen_in_last_year_notice():
    quote = "지원단가 월동무 원 양배추 원  : ( ) 15 /kg, ( ) 23 /kg"
    assert codes(program(match_id=LOGI, amount_value=(15, quote)), doc=DOC_N2) == set()
    assert ("VALUE_NOT_IN_QUOTE", "amount_value", "RED") in codes(program(match_id=LOGI, amount_value=(16, quote)), doc=DOC_N2)


def test_n1_short_end_date_takes_year_of_start():
    quote = "신청기간  : 수 화 2026. 7. 22.( ) ~ 8. 4.( )"
    assert codes(program(match_id=LOGI, apply_end=("2026-08-04", quote)), doc=DOC_N1) == set()


def test_quote_normalizes_spacing_fullwidth_and_tilde():
    # 원문: "재배면적 0.1~5ha범위", "추가‧" — 공백·물결·가운뎃점을 바꿔 써도 같은 인용
    assert codes(program(match_id=CALC, min_ha=(0.1, "재배 면적 0.1∼5 ha 범위"))) == set()
    assert squash("분상‧입상 ∼ ～") == squash("분상·입상~~")


def test_issue_carries_program_index_and_korean_message():
    issues = run(draft(program(min_ha=(0.1, N7_AREA)), program(match_id=CALC, max_ha=(9, N7_CALC_AREA))), DOC_N7, BUNDLE)
    assert [(i.program, i.code) for i in issues] == [(1, "VALUE_NOT_IN_QUOTE")]
    assert any("가" <= ch <= "힣" for ch in issues[0].message)


def test_bad_enum_suggests_close_value():
    issue = next(i for i in run(draft(program(applicant=("개인농", N7_TARGET))), DOC_N7, BUNDLE) if i.code == "BAD_ENUM")
    assert "개인" in issue.message


def test_same_program_without_fields_is_clean_and_skipped_titles_are_scanned():
    assert run(draft(program("SAME", SMALL)), DOC_N7, BUNDLE) == []
    d = NoticeDraft(skipped=(Skipped(title="선정 결과", reason="홍길동 010-1234-5678 명단"),))
    assert [(i.program, i.code, i.field) for i in run(d, DOC_N7, BUNDLE)] == [(None, "PII_IN_DRAFT", "skipped")]


def test_empty_values_mean_absent_and_are_not_checked():
    p = DraftProgram(action="UPDATE", match_id=SMALL, fields={"min_ha": DraftField(value=None), "notes": DraftField(value="")})
    assert run(draft(p), DOC_N7, BUNDLE) == []


@pytest.mark.parametrize("text, labels", [
    ("담당 010-1234-5678", ("phone",)),
    ("01012345678로 연락", ("phone",)),
    ("주민번호 500101-1234567", ("rrn",)),
    ("메일 someone@example.com", ("email",)),
    ("문의 064-710-3272 (감귤유통과)", ()),  # 기관 대표 전화는 개인정보로 보지 않는다
])
def test_pii_labels(text, labels):
    assert pii_labels(text) == labels


def test_fixture_pii_property_for_later_tasks():
    texts = {n: "\n".join(p.text for p in d.pages) for n, d in (("N1", DOC_N1), ("N2", DOC_N2), ("N7", DOC_N7))}
    assert all(pii_labels(t) == () for t in texts.values())
    from notice_fixtures import NOTICES
    assert pii_labels((NOTICES / "N5.txt").read_text(encoding="utf-8")) == ("phone",)
