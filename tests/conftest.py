"""공용 픽스처. 페르소나 픽스처(P4_KWARGS 등)는 Task 2가 여기에 더한다."""
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 11, 13)


@pytest.fixture(autouse=True)
def _no_real_env_file(request, monkeypatch, tmp_path_factory):
    """진짜 키가 시험에 새어 들지 않게 한다: 프로젝트 .env, 사용자 폴더 .env, 시스템 keyring을 모두 바꾼다.
    실호출 시험(live)만 진짜를 본다."""
    if request.node.get_closest_marker("live"):
        return
    import keyring
    from app.agents.llm import keystore
    base = tmp_path_factory.getbasetemp()
    monkeypatch.setattr(keystore, "PROJECT_ENV", base / "no-project.env")
    monkeypatch.setattr(keystore, "user_env_path", lambda: base / "fake-home" / ".jeju-chaenggim" / ".env")

    class FakeKeyring:                      # 메모리 keyring: 처음엔 비어 있다
        def __init__(self):
            self.data = {}

        def get_password(self, service, username):
            return self.data.get((service, username))

        def set_password(self, service, username, password):
            self.data[(service, username)] = password

        def delete_password(self, service, username):
            self.data.pop((service, username), None)

    monkeypatch.setattr(keyring, "get_keyring", lambda: FakeKeyring())


@pytest.fixture
def tables_dir() -> Path:
    return ROOT / "data" / "tables"


@pytest.fixture
def snapshot_dir() -> Path:
    return ROOT / "data" / "snapshot"


# --- 페르소나 → FarmProfile 키워드 ---------------------------------------------------------
# 정본: research/dept/round2-M-personas.json(v 2026-11-08-r2v3). 그 파일은 1라운드 필드명
# (round1-C-agent.md §3-1)과 profile_ext를 쓰므로 2라운드 FarmProfile(round2-C-agent.md §5-1)
# 이름으로 옮겼다. 공통 대응:
#   profile.sex → owner_sex, profile.crop_key/area_m2 → crops[0], profile_ext.*_2 → crops[1]
#   crop_key: 노지온주 → 감귤_노지(crops.csv 코드), 나머지는 crops.csv 코드와 같음
#   coop_shipping=Y → sales_channel="coop", field_sold_contract=Y → "field_contract_done"
#   selfpay_fund_member Y/N/? → selfpay_fund paid/not_paid/unknown
#   total_farm_area_m2 → total_area_m2
#   land_tenure own/partial/rent → own_all/own_part/rent_all
#   farmland_owned_years ≥ 2 → land_held_2y=True, 땅이 없으면 None(5번 하위 질문이 안 나옴)
#   owned_over_4700py: 5a는 총면적 302~2,890평이고 내 땅이 있을 때만 나옴 → 그때 False, 아니면 None
#   mgmt_registered Y + mgmt_years ≥ 2 → mgmt_status="over_2y", N → "none"
#   profile_ext.mgmt_last_update_year → mgmt_last_reg_year
#   spouse_status registered / unregistered / not_farming·none → registered / cofarming_unregistered / none
#   jeju_residence_years ≥ 3 → residence_3y=True
#   health_insurance regional/dependent/employee/? → regional/dependent/employee/unknown
#   direct_pay_edu_done Y/N → flags.direct_payment_education, 재해 피해 없음 → disaster_damage=False
#   already_receiving: "X#2인이상"처럼 # 꼬리가 붙은 키는 program_key "X"로 줄임
#   insurance_enrolled "disaster" → crops[*].ins_disaster=True, "safety" → ins_safety
#   visitor self → "self", spouse(P5, 부인이 오심) → "family_proxy"
#   emd_code: 페르소나 라벨의 읍면 이름(형식 미정. 읍면동 표가 생기면 그 코드로 바꾼다)
# 버린 키(2라운드 FarmProfile에 없음): age(→ birth_year), coop_member, mgmt_years 숫자,
#   farmland_owned_years 숫자, offfarm_income_band, region(emd_code에서 나옴), flags 목록,
#   disaster_end_date, spouse_birth_year, area_pyeong(평 원값), fund_enrolled_pstab,
#   direct_pay_receiving, land_note, already_note.
# 공유 dict이므로 고치지 말고 {**P4_KWARGS, "키": 값}으로 복사해 쓴다.

P1_KWARGS = dict(  # 남원 노지감귤 1,500평, 74세 여성 독거, 상인 밭떼기
    visitor="self", owner_sex="F", emd_code="남원읍", birth_year=1952,
    crops=({"crop_code": "감귤_노지", "area_m2": 4959, "sales_channel": "field_contract_done", "selfpay_fund": "unknown"},),
    total_area_m2=4959, land_tenure="own_all", land_held_2y=True, owned_over_4700py=False,
    mgmt_status="over_2y", mgmt_last_reg_year=None, spouse="none", farming_years=45, residence_3y=True,
    health_ins="regional", flags={"disaster_damage": False, "direct_payment_education": "Y"},
    # direct_pay_receiving="unknown_type"(직불은 받는데 종류 모름)은 담을 필드가 없어 뺐다.
    already_receiving=frozenset({"JEJU-FARMER-ALLOW"}),
)

P2_KWARGS = dict(  # 구좌 당근 3,000평, 68세 부부(계통·자조금, 부인 미등록)
    visitor="self", owner_sex="M", emd_code="구좌읍", birth_year=1958,
    crops=({"crop_code": "당근", "area_m2": 9917, "sales_channel": "coop", "selfpay_fund": "paid"},),
    total_area_m2=9917, land_tenure="own_part", land_held_2y=True, owned_over_4700py=None,
    mgmt_status="over_2y", mgmt_last_reg_year=2025, spouse="cofarming_unregistered", farming_years=40,
    residence_3y=True, health_ins="regional", flags={"disaster_damage": False, "direct_payment_education": "Y"},
    already_receiving=frozenset({"JEJU-FARMER-ALLOW", "NAT-DIRECT-AREA", "JEJU-PSTAB", "JEJU-LOGI", "NHIS-FARMER-SUPPORT"}),
)

P3_KWARGS = dict(  # 대정 마늘 1,800평 + 월동무 900평, 71세 부부(마늘 보험 오늘 마감)
    visitor="self", owner_sex="M", emd_code="대정읍", birth_year=1955,
    crops=(
        {"crop_code": "마늘", "area_m2": 5950, "sales_channel": "coop", "selfpay_fund": "paid"},
        {"crop_code": "월동무", "area_m2": 2975, "sales_channel": "field_contract_done", "selfpay_fund": "unknown"},
    ),
    total_area_m2=8926, land_tenure="own_part", land_held_2y=True, owned_over_4700py=False,
    mgmt_status="over_2y", mgmt_last_reg_year=2023, spouse="cofarming_unregistered", farming_years=45,
    residence_3y=True, health_ins="regional", flags={"disaster_damage": False, "direct_payment_education": "N"},
    already_receiving=frozenset({"JEJU-FARMER-ALLOW", "NAT-DIRECT-AREA"}),
)

P4_KWARGS = dict(  # 애월 양배추 3,600평 임차, 1961년생, 경영체 미등록, 상인 밭떼기
    visitor="self", owner_sex="M", emd_code="애월읍", birth_year=1961,
    crops=({"crop_code": "양배추", "area_m2": 11901, "sales_channel": "field_contract_done", "selfpay_fund": "not_paid"},),
    total_area_m2=11901, land_tenure="rent_all", land_held_2y=None, owned_over_4700py=None,
    mgmt_status="none", mgmt_last_reg_year=None, spouse="none", farming_years=3, residence_3y=True,
    health_ins="unknown",
    # direct_pay_edu_done="?" → "NA": 직불을 받지 않음(경영체 미등록, round2-A-service.md §4-4 14번 "직불 안 받음").
    flags={"disaster_damage": False, "direct_payment_education": "NA"},
)

P5_KWARGS = dict(  # 한림 브로콜리 2,100평, 경영주 남편 1950년생, 1956년생 부인이 와서 상담
    visitor="family_proxy", owner_sex="M", emd_code="한림읍", birth_year=1950,
    crops=({"crop_code": "브로콜리", "area_m2": 6942, "sales_channel": "coop", "selfpay_fund": "unknown"},),
    total_area_m2=6942, land_tenure="own_all", land_held_2y=True, owned_over_4700py=False,
    mgmt_status="over_2y", mgmt_last_reg_year=2024, spouse="cofarming_unregistered", farming_years=50,
    residence_3y=True, health_ins="regional", flags={"disaster_damage": False, "direct_payment_education": "Y"},
    already_receiving=frozenset({"JEJU-FARMER-ALLOW", "NAT-DIRECT-AREA"}),
)

T1_KWARGS = dict(  # 빈 종이 ①: 표선 노지감귤 1,800평, 70세 부부(경영체·배우자 등록, 상인 판매)
    visitor="self", owner_sex="M", emd_code="표선면", birth_year=1956,
    crops=({"crop_code": "감귤_노지", "area_m2": 5950, "sales_channel": "field_contract_done", "selfpay_fund": "unknown",
            "ins_disaster": True},),
    total_area_m2=5950, land_tenure="own_all", land_held_2y=True, owned_over_4700py=False,
    mgmt_status="over_2y", mgmt_last_reg_year=2024, spouse="registered", farming_years=45, residence_3y=True,
    health_ins="regional", flags={"disaster_damage": False, "direct_payment_education": "N"},
    already_receiving=frozenset({"JEJU-FARMER-ALLOW", "NAT-DIRECT-SMALL", "JEJU-WOMEN-VOUCHER", "NHIS-FARMER-SUPPORT", "JEJU-HAPPY-TAXI"}),
    # insurance_enrolled에 "safety"가 있고 부부 모두 등록된 빈 종이 사례라 두 사람 모두 든 것으로 봤다.
    ins_safety=frozenset({"owner", "spouse"}),
)

T2_KWARGS = dict(  # 빈 종이 ②: 구좌 당근 3,000평, 68세 부부(계통·자조금·부부 등록)
    visitor="self", owner_sex="M", emd_code="구좌읍", birth_year=1958,
    crops=({"crop_code": "당근", "area_m2": 9917, "sales_channel": "coop", "selfpay_fund": "paid", "ins_disaster": True},),
    total_area_m2=9917, land_tenure="own_part", land_held_2y=True, owned_over_4700py=None,
    mgmt_status="over_2y", mgmt_last_reg_year=2023, spouse="registered", farming_years=40, residence_3y=True,
    health_ins="regional", flags={"disaster_damage": False, "direct_payment_education": "Y"},
    already_receiving=frozenset({"JEJU-FARMER-ALLOW", "NAT-DIRECT-AREA", "JEJU-PSTAB", "JEJU-LOGI", "JEJU-WOMEN-VOUCHER",
                                 "NHIS-FARMER-SUPPORT", "JEJU-HAPPY-TAXI", "DO-CALCIUM-SULFUR"}),
    ins_safety=frozenset({"owner", "spouse"}),
)
