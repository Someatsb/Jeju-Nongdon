"""Task 39: DPAPI 껍데기. 실제 왕복은 Windows에서만."""
import sys

import pytest

from app.data_layer import dpapi


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI는 Windows 전용")
def test_real_dpapi_round_trip():
    secret = "010-1234-5678 삼춘".encode("utf-8")
    blob = dpapi.protect(secret)
    assert blob != secret and b"010-1234-5678" not in blob
    assert dpapi.unprotect(blob) == secret


@pytest.mark.skipif(sys.platform == "win32", reason="비Windows 전용")
def test_non_windows_raises():
    with pytest.raises(NotImplementedError):
        dpapi.protect(b"x")
