"""Per-user DPAPI encrypted pairing storage. Passwords and PINs are not logged."""
import base64
import ctypes
from ctypes import wintypes
import ipaddress
import json
import os
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data: bytes, decrypt=False) -> bytes:
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    out = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    func = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    func.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    func.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not func(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.data, out.size)
    finally:
        kernel.LocalFree(out.data)


def normalize_account(value):
    value = value.strip()
    if value.isascii() and value.isdecimal():
        number = int(value)
        if not 0 < number < 2**64:
            raise ValueError("PSN Account-ID 数值超出范围。")
        return base64.b64encode(number.to_bytes(8, "little")).decode()
    try:
        data = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError("Account-ID 需为 8 字节的 Base64，或十进制数字；不是 PSN 昵称。") from exc
    if len(data) != 8 or not any(data):
        raise ValueError("Account-ID 解码后必须为 8 字节且非零。")
    return base64.b64encode(data).decode()


def validate_host(value):
    try:
        addr = ipaddress.IPv4Address(value.strip())
    except Exception as exc:
        raise ValueError("请输入 PS5 的 IPv4 地址，例如 192.168.1.50。") from exc
    if addr.is_unspecified or addr.is_multicast or addr.is_loopback or int(addr) == 0xffffffff:
        raise ValueError("请输入局域网内 PS5 的地址。")
    return str(addr)


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else Path(os.environ["LOCALAPPDATA"]) / "PS5OBSStandalone"
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = self.root / "settings.json"
        self.pairing = self.root / "pairing.dpapi"

    def load_config(self):
        if not self.config.exists():
            return {}
        try:
            return json.loads(self.config.read_text("utf-8"))
        except (ValueError, OSError):
            return {}

    def save_config(self, data):
        temp = self.config.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        temp.replace(self.config)

    def save_profiles(self, data):
        temp = self.pairing.with_suffix(".tmp")
        temp.write_bytes(dpapi(json.dumps(data).encode()))
        temp.replace(self.pairing)

    def load_profiles(self):
        if not self.pairing.exists():
            return {}
        try:
            return json.loads(dpapi(self.pairing.read_bytes(), decrypt=True).decode())
        except Exception as exc:
            raise ValueError("无法解密配对资料，请用原 Windows 用户打开，或重新配对。") from exc
