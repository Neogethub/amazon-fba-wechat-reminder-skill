"""Keep local credentials in macOS Keychain or Windows user-bound DPAPI."""
import base64
import ctypes as C
from ctypes import wintypes as W
import json
import sys

from local_state import ROOT, private_write
from mac_keychain import Keychain

SERVICE = "io.github.neogethub.fba-shipment-reminder"
SEALED_FILE = ROOT / "credentials.dpapi"


def windows_crypt(data, decrypt=False):
    if sys.platform != "win32":
        raise RuntimeError("DPAPI 只可在 Windows 上使用。")
    class Blob(C.Structure):
        _fields_ = [("size", W.DWORD), ("data", C.POINTER(C.c_ubyte))]
    buffer = (C.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    output = Blob()
    crypt = C.WinDLL("crypt32", use_last_error=True)
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [C.c_void_p]
    kernel.LocalFree.restype = C.c_void_p
    func = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    func.argtypes = [C.POINTER(Blob), C.c_void_p, C.POINTER(Blob), C.c_void_p,
                     C.c_void_p, W.DWORD, C.POINTER(Blob)]
    func.restype = W.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN; encryption is tied to the current Windows user.
    if not func(C.byref(source), None, None, None, None, 1, C.byref(output)):
        raise RuntimeError("Windows 凭证加密或解密失败，请使用原 Windows 用户重新配置。")
    try:
        return C.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(C.cast(output.data, C.c_void_p))


def storage_available():
    if sys.platform not in ("darwin", "win32"):
        raise RuntimeError("Linux 请通过环境变量配置凭证；本机配置页支持 macOS 和 Windows。")


def save_credentials(values):
    storage_available()
    raw = json.dumps(values, ensure_ascii=False)
    if sys.platform == "darwin":
        Keychain(SERVICE).write(raw)
    else:
        private_write(SEALED_FILE, base64.b64encode(windows_crypt(raw.encode("utf-8"))).decode("ascii"))


def read_credentials():
    storage_available()
    try:
        if sys.platform == "darwin":
            raw = Keychain(SERVICE).read()
        elif SEALED_FILE.exists():
            raw = windows_crypt(base64.b64decode(SEALED_FILE.read_text(encoding="utf-8")), True).decode("utf-8")
        else:
            raw = None
        if raw is None:
            raise ValueError("尚未配置，请运行 configure.py setup。")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (UnicodeError, ValueError):
        raise ValueError("未找到有效本机凭证，请运行 configure.py setup 重新配置。") from None
