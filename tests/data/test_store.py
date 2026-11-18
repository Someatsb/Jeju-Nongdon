"""익명 기록(Task 26, U26). 로그에는 띠(월·행정시·나이대·면적대)와 코드만 남는다."""
import json
import re
from datetime import date

import pytest
from pydantic import ValidationError

from app.core.models import FarmProfile
from app.data_layer import store
from app.data_layer.store import SessionLog, band_profile
from conftest import P1_KWARGS, P3_KWARGS

AS_OF = date(2026, 11, 13)
RAW = {"emd_code", "birth_year", "area_m2", "total_area_m2"}


def _log(**kw):
    base = dict(month="2026-11", city="서귀포시", age_band="70대", area_band="0.5~1ha", crops=("감귤_노지",),
                mgmt_status="over_2y", sales_channel="coop", matched_ids=("A",), already_ids=(), first_heard_count=1,
                prereq_ids=(), printed=True)
    return SessionLog(**{**base, **kw})


def test_session_log_has_no_raw_pii(tmp_path):
    entry = store.log(store.new_session(AS_OF), _log(), logs_dir=tmp_path)
    assert not RAW & set(entry)
    line = (tmp_path / "sessions" / "2026-11.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert not RAW & set(json.loads(line)) and json.loads(line)["reminder_saved"] is False


def test_log_appends_lines_into_month_file(tmp_path):
    store.log("ABCDEF", _log(), logs_dir=tmp_path)
    store.log("GHJKLM", _log(month="2026-12"), logs_dir=tmp_path)
    store.log("ABCDEF", _log(printed=False), logs_dir=tmp_path)
    assert len((tmp_path / "sessions" / "2026-11.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert (tmp_path / "sessions" / "2026-12.jsonl").exists()


def test_session_id_six_unambiguous_chars():
    ids = {store.new_session(AS_OF) for _ in range(200)}
    assert len(ids) > 190
    assert all(re.fullmatch(r"[A-HJ-NP-Z2-9]{6}", i) for i in ids)


def test_session_log_rejects_unknown_and_bad_fields():
    with pytest.raises(ValidationError):
        _log(emd_code="남원읍")
    with pytest.raises(ValidationError):
        _log(month="2026-13")
    with pytest.raises(ValidationError):
        _log(city="남원읍")


def test_log_rejects_bad_session_id(tmp_path):
    with pytest.raises(ValueError):
        store.log("../x", _log(), logs_dir=tmp_path)


def test_band_profile_derives_bands_and_never_copies_raw_fields():
    p = FarmProfile(**P1_KWARGS)
    s = band_profile(p, AS_OF, city="서귀포시", matched_ids=("X",), printed=True)
    dumped = json.dumps(s.model_dump(mode="json"), ensure_ascii=False)
    assert (s.month, s.city, s.age_band, s.area_band, s.crops) == ("2026-11", "서귀포시", "70대", "≤0.5ha", ("감귤_노지",))
    assert s.first_heard_count == 0 and s.already_ids == ("JEJU-FARMER-ALLOW",) and s.sales_channel == "field_contract_done"
    for raw in ("남원읍", "1952", "4959"):
        assert raw not in dumped
    assert not RAW & set(s.model_dump())


def test_band_profile_mixed_channels_and_area_sum():
    p = FarmProfile(**{**P3_KWARGS, "total_area_m2": None})
    s = band_profile(p, AS_OF, city="제주시")
    assert s.area_band != "모름" and len(s.crops) == 2


@pytest.mark.parametrize("m2,band", [(5000, "≤0.5ha"), (5001, "0.5~1ha"), (10000, "0.5~1ha"), (10001, "1~2ha"),
                                     (20001, "2~5ha"), (50001, "5ha+"), (None, "모름")])
def test_area_band_edges(m2, band):
    assert store.area_band(m2) == band


@pytest.mark.parametrize("age,band", [(25, "30세 미만"), (30, "30대"), (74, "70대"), (80, "80대 이상"), (None, "모름")])
def test_age_band_edges(age, band):
    assert store.age_band(None if age is None else AS_OF.year - age, AS_OF) == band
