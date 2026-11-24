"""Generic Windows Credential Manager access (ctypes, standard library only): one secret per target name. Used by keystore (API keys) and fints_sync (PIN)."""
from __future__ import annotations
import sys

CRED_TARGET = "WealthView-FinTS"


def cred_write(secret: str, user: str = "pin", target: str = CRED_TARGET) -> bool:
    """store the PIN in the Windows Credential Manager; False off Windows"""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class CRED(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    blob = secret.encode("utf-16-le")
    buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
    c = CRED(0, 1, target, None, wintypes.FILETIME(0, 0), len(blob), buf, 2, 0, None, None, user)
    return bool(ctypes.windll.advapi32.CredWriteW(ctypes.byref(c), 0))        # type: ignore[attr-defined]


def cred_read(target: str = CRED_TARGET) -> str | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    p = ctypes.c_void_p()
    if not ctypes.windll.advapi32.CredReadW(target, 1, 0, ctypes.byref(p)):        # type: ignore[attr-defined]
        return None

    class CRED(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_byte))]
    c = ctypes.cast(p, ctypes.POINTER(CRED)).contents
    try:
        return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-16-le")
    finally:
        ctypes.windll.advapi32.CredFree(p)        # type: ignore[attr-defined]


def cred_delete(target: str) -> None:
    """remove one entry (nothing happens when there is none or off Windows)"""
    if sys.platform != "win32":
        return
    import ctypes
    ctypes.windll.advapi32.CredDeleteW(target, 1, 0)        # type: ignore[attr-defined]
