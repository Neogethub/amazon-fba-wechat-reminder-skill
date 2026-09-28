"""Small macOS Keychain adapter. Secrets never enter shell arguments or files."""

import ctypes as C
import sys


class Keychain:
    def __init__(self, service, account="default"):
        if sys.platform != "darwin":
            raise RuntimeError("此凭证配置需要 macOS 钥匙串。")
        self.service = service.encode("utf-8")
        self.account = account.encode("utf-8")
        self.security = C.CDLL("/System/Library/Frameworks/Security.framework/Security")
        self.core = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.core.CFRelease.argtypes = [C.c_void_p]
        self.core.CFRelease.restype = None
        signatures = {
            "SecKeychainFindGenericPassword": [C.c_void_p, C.c_uint32, C.c_char_p,
                C.c_uint32, C.c_char_p, C.POINTER(C.c_uint32),
                C.POINTER(C.c_void_p), C.POINTER(C.c_void_p)],
            "SecKeychainAddGenericPassword": [C.c_void_p, C.c_uint32, C.c_char_p,
                C.c_uint32, C.c_char_p, C.c_uint32, C.c_void_p, C.POINTER(C.c_void_p)],
            "SecKeychainItemModifyAttributesAndData": [C.c_void_p, C.c_void_p,
                C.c_uint32, C.c_void_p],
            "SecKeychainItemFreeContent": [C.c_void_p, C.c_void_p],
            "SecKeychainItemDelete": [C.c_void_p],
        }
        for name, args in signatures.items():
            function = getattr(self.security, name)
            function.argtypes = args
            function.restype = C.c_int32

    def _find(self):
        size, data, item = C.c_uint32(), C.c_void_p(), C.c_void_p()
        status = self.security.SecKeychainFindGenericPassword(None,
            len(self.service), self.service, len(self.account), self.account,
            C.byref(size), C.byref(data), C.byref(item))
        if status == -25300:
            return None, None
        self._check(status)
        try:
            value = C.string_at(data, size.value)
        finally:
            self.security.SecKeychainItemFreeContent(None, data)
        return value, item

    @staticmethod
    def _check(status):
        if status:
            raise RuntimeError("钥匙串操作失败（系统代码 %d）。请检查钥匙串是否解锁，并允许本机 Python 访问此项目的凭证。" % status)

    def read(self):
        value, item = self._find()
        if item:
            self.core.CFRelease(item)
        return value.decode("utf-8") if value is not None else None

    def write(self, value):
        value = value.encode("utf-8")
        _, item = self._find()
        try:
            if item:
                status = self.security.SecKeychainItemModifyAttributesAndData(
                    item, None, len(value), value)
            else:
                status = self.security.SecKeychainAddGenericPassword(None,
                    len(self.service), self.service, len(self.account), self.account,
                    len(value), value, C.byref(item := C.c_void_p()))
            self._check(status)
        finally:
            if item:
                self.core.CFRelease(item)

    def delete(self):
        """Used by the isolated dummy-credential test only."""
        _, item = self._find()
        if item:
            try:
                self._check(self.security.SecKeychainItemDelete(item))
            finally:
                self.core.CFRelease(item)
