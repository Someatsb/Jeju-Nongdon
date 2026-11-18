"""Windows DPAPI 얇은 껍데기(Task 39). 표준 라이브러리 ctypes만 쓴다.

현재 Windows 사용자 계정으로만 풀린다. 다른 PC·다른 계정에서는 풀리지 않는다.
Windows가 아니면 NotImplementedError.
"""
from __future__ import annotations

import sys

CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _call(data: bytes, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise NotImplementedError("DPAPI는 Windows에서만 쓸 수 있습니다.")
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.restype = wintypes.BOOL
    desc = wintypes.LPCWSTR if protect else ctypes.c_void_p
    fn.argtypes = [ctypes.POINTER(Blob), desc, ctypes.POINTER(Blob), ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]

    buf = ctypes.create_string_buffer(data, len(data))
    src = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    if not fn(ctypes.byref(src), "jeju-chaenggim" if protect else None, None, None, None,
              CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise OSError(f"DPAPI 실패(오류 {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def protect(data: bytes) -> bytes:
    return _call(data, True)


def unprotect(data: bytes) -> bytes:
    return _call(data, False)
