"""공고 도구 시험용 공용 픽스처(Task 18). 문서는 tests/fixtures/notices/(출처는 SOURCES.md).

BUNDLE은 load_tables의 programs만 담은 묶음(app/data_layer/supports_index.py)이다.
"""
from pathlib import Path

from app.data_layer.docs_in import Doc, extract
from app.data_layer.supports_index import load_program_index
from app.tools.models import DraftField, DraftProgram, DraftTag, NoticeDraft, ToolLog
from app.tools.notice_tools import NoticeTools

ROOT = Path(__file__).resolve().parents[2]
NOTICES = ROOT / "tests" / "fixtures" / "notices"
BUNDLE = load_program_index(ROOT / "data" / "tables")

DOC_N1 = extract(NOTICES / "N1.txt")   # 2026 물류비 3차
DOC_N2 = extract(NOTICES / "N2.txt")   # 2024 물류비 2차
DOC_N7 = extract(NOTICES / "N7.txt")   # 통합공고 발췌: 1쪽 칼슘유황비료, 2쪽 친서민 소형농기계

LOGI = "JEJU-LOGI@2026-27"
SMALL = "DO-SMALL-MACHINE@2026"
CALC = "DO-CALCIUM-SULFUR@2026"

# 원문(N1)에 그대로 있는 인용
N1_PERIOD = "신청기간  : 수 화 2026. 7. 22.( ) ~ 8. 4.( )"
N1_CROPS = "지원품목 월동무 양배추 당근 조생양파"
N1_APPLICANT = "지 역 농 협  및  영 농 조 합 법 인"
# 원문(N7)에 그대로 있는 인용
N7_PERIOD = "신청기간 : '26. 1. 2.(금) ∼ 1. 16.(월)"
N7_CAP = "(1그룹) 10,000천원/대 (보조한도 7,000천원, 보조율 70%)"
N7_AREA = "밭작물재배면적(경지면적)이1,000㎡이상인농가"
N7_INCOME = "연간 농업 외 소득(본인) 3,700만원 이상인 경우"
N7_COOP_SCORE = "계통출하 실적(감귤류를 포함한 과수 제외)(2024.1~2025.12)① 계통출하기간 (최근 2년간) * 실적 없을 경우 0점 10"
N7_CALC_AREA = "지원규모:재배면적 0.1~5ha범위 내에서 시비량 기준 지원"
N7_CALC_DOSE = "시비량:200kg(10포)/10a(300평)"


def tools_for(doc: Doc) -> NoticeTools:
    return NoticeTools(doc, BUNDLE, ToolLog())


def program(action: str = "UPDATE", match_id: str | None = SMALL, program_key: str | None = None,
            questions: tuple[str, ...] = (), tags: tuple[tuple[str, str], ...] = (), **fields: tuple) -> DraftProgram:
    """fields: 칸 이름 → (값, 인용). tags: (이름표, 인용) 목록. 앵커는 검사 대상이 아니라 비워 둔다."""
    return DraftProgram(action=action, match_id=match_id, program_key=program_key, questions=questions,
                        fields={k: DraftField(value=v, quote=q) for k, (v, q) in fields.items()},
                        tags=tuple(DraftTag(label=lab, quote=q) for lab, q in tags))


def draft(*programs: DraftProgram) -> NoticeDraft:
    return NoticeDraft(programs=programs)


def draft_with(quote: str, **values) -> NoticeDraft:
    """기존 행 DO-SMALL-MACHINE 갱신 초안. 모든 칸이 같은 인용을 쓴다."""
    return draft(program(**{k: (v, quote) for k, v in values.items()}))


N1_TAGS = (("농협·조합법인이 신청", N1_APPLICANT), ("월동무·양배추·당근·양파", N1_CROPS),
           ("해상운송비 일부 지원", "출하한 생산자에 대해 해상운송비 일부 지원"),
           ("자조금 가입 증명 필요", "자조금 가입 증명서 농협은 명단 제출"))
DRAFT_N1_GOOD = draft(program(match_id=LOGI, apply_start=("2026-07-22", N1_PERIOD), apply_end=("2026-08-04", N1_PERIOD),
                              crop_in=(["월동무", "양배추", "당근", "양파"], N1_CROPS),
                              applicant=("농협경유", N1_APPLICANT), tags=N1_TAGS))
DRAFT_N1_BAD_QUOTE = draft(program(match_id=LOGI, apply_start=("2026-07-22", "신청기간은 2026년 7월 22일부터")))
DRAFT_WITH_RED = draft(program(match_id=LOGI, apply_start=("2026-07-23", N1_PERIOD)))      # 값이 인용과 다름
DRAFT_WITH_YELLOW = draft(program(match_id=SMALL, needs_coop=("Y", N7_COOP_SCORE)))       # 가점 혼동(노랑만)
