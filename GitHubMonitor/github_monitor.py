#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""GitHub Monitor (เวอร์ชัน Python): ดูยอดเข้าชม, clone และยอดดาวน์โหลดของ repo บน GitHub

ใช้ Python 3.6 ขึ้นไปที่มีอยู่ในเครื่อง (เช่น Anaconda) ใช้แค่ไลบรารีมาตรฐาน ไม่ต้องติดตั้งแพ็กเกจเพิ่ม

วิธีใช้
  python github_monitor.py             เปิดหน้าจอ dashboard เป็นแท็บในเบราว์เซอร์
  python github_monitor.py --install   ติดตั้งลงเครื่อง สร้างไอคอนบน Desktop แล้วเปิดโปรแกรม
  python github_monitor.py --collect   ดึงข้อมูลรอบเดียวแล้วจบ (Task Scheduler เรียกใช้)

สิ่งที่โปรแกรมทำ (สำหรับผู้ดูแลระบบ)
  - ต่ออินเทอร์เน็ตเฉพาะ https://api.github.com แบบอ่านอย่างเดียว ด้วย token ของผู้ใช้
  - เปิดเว็บเซิร์ฟเวอร์เฉพาะ 127.0.0.1 พอร์ตสุ่มให้หน้าจอในเบราว์เซอร์คุยด้วย ทุกคำสั่งต้องมีรหัสสุ่มของรอบนั้น
  - ข้อมูลอยู่ที่ %LOCALAPPDATA%\GitHubMonitor  token เข้ารหัสด้วย Windows DPAPI
  - ติดตั้งไฟล์ที่ %LOCALAPPDATA%\Programs\GitHub Monitor และสร้างไอคอนบน Desktop กับ Start Menu
  - ถ้าผู้ใช้กดเปิดเอง: ตั้งงาน Task Scheduler ชื่อ "GitHub Monitor Daily" ให้ดึงข้อมูลวันละครั้ง
  - ไม่ต้องใช้สิทธิ์ผู้ดูแลระบบ และไม่แก้ไขอะไรบน GitHub
"""
import os
import sys

# ---------- เตรียมสภาพแวดล้อม (ต้องทำก่อน import โมดูลอื่น) ----------

# เปิดด้วย pythonw (ไม่มีหน้าต่าง console) sys.stdout/stderr จะเป็น None ทำให้ print หรือ traceback พังได้
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# Anaconda: เวลาเปิดจากไอคอนหรือ Task Scheduler จะไม่ได้ activate environment
# Python จึงอาจหา DLL ของ ssl/ctypes ไม่เจอ เพิ่มโฟลเดอร์ DLL ของ conda ให้ก่อน import โมดูลเหล่านั้น
_DLL_DIRS = []
if os.name == "nt" and os.path.isdir(os.path.join(sys.prefix, "conda-meta")):
    _cands = [os.path.join(sys.prefix, p) for p in ("Library\\mingw-w64\\bin", "Library\\usr\\bin", "Library\\bin", "Scripts", "DLLs")]
    _cands = [d for d in _cands if os.path.isdir(d)]
    os.environ["PATH"] = os.pathsep.join(_cands + [sys.prefix, os.environ.get("PATH", "")])
    for _d in _cands:
        try:
            _DLL_DIRS.append(os.add_dll_directory(_d))
        except (AttributeError, OSError):
            pass

import base64  # noqa: E402
import datetime as dt  # noqa: E402
import hmac  # noqa: E402
import http.client  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import platform  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import shutil  # noqa: E402
import socketserver  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402
import webbrowser  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402

APP_NAME = "GitHub Monitor"
APP_VERSION = "1.3.0"
APP_ID = "GitHubMonitor"
TASK_NAME = "GitHub Monitor Daily"
IS_WIN = os.name == "nt"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(APP_DIR, "ui")
SCRIPT_NAME = "github_monitor.py"
ICON_NAME = "GitHubMonitor.ico"
DESCRIPTION = "ดูยอดเข้าชม, clone และยอดดาวน์โหลดของ GitHub (GitHub views, clones and downloads)"

# ---------- ข้อความที่โปรแกรมส่งให้หน้าจอ (ไทย, อังกฤษ) ข้อความของหน้าจอเองอยู่ใน ui/i18n.js ----------
LANGS = ("th", "en")
DEFAULT_LANG = "th"
MESSAGES = {
    # ข้อผิดพลาดจาก GitHub
    "unauthorized": ("token ใช้ไม่ได้หรือหมดอายุแล้ว ตรวจว่าคัดลอกมาครบ หรือสร้าง token ใหม่บน GitHub",
                     "The token is invalid or has expired. Check that you copied all of it, or create a new token on GitHub."),
    "rate": ("GitHub จำกัดจำนวนครั้งที่เรียกชั่วคราว ลองใหม่อีกครั้งในอีกสักพัก",
             "GitHub is limiting requests for now. Try again in a little while."),
    "no_traffic": ("token ไม่มีสิทธิ์อ่านยอดเข้าชม ต้องเปิดสิทธิ์ Administration แบบ Read-only",
                   "The token cannot read traffic data. Give it the Administration permission as Read-only."),
    "server": ("GitHub ตอบ {0}: เซิร์ฟเวอร์ GitHub มีปัญหาชั่วคราว",
               "GitHub returned {0}: GitHub's servers are having temporary problems"),
    "http": ("GitHub ตอบ {0}: {1}", "GitHub returned {0}: {1}"),
    "network": ("ต่อ GitHub ไม่ได้: {0}", "Could not connect to GitHub: {0}"),
    "bad_json": ("GitHub ตอบข้อมูลที่อ่านไม่ได้ (อาจติด proxy หรือหน้า login ของเครือข่าย)",
                 "GitHub sent a reply that could not be read (possibly a proxy or a network sign-in page)"),
    # token และการเก็บข้อมูล
    "token_decrypt": ("ถอดรหัส token ไม่ได้ (token ถูกบันทึกจากเครื่องหรือบัญชี Windows อื่น) ให้ใส่ token ใหม่",
                      "Could not decrypt the token (it was saved on another computer or Windows account). Enter a new token."),
    "token_format": ("รูปแบบ token ไม่ถูกต้อง ให้คัดลอก token ทั้งหมดที่ GitHub แสดง",
                     "That does not look like a token. Copy the whole token that GitHub shows."),
    "no_token": ("ยังไม่ได้ใส่ token", "No token has been entered yet"),
    "busy": ("มีการเก็บข้อมูลอีกงานกำลังทำอยู่ ลองใหม่อีกครั้งในอีกสักครู่",
             "Another collection is already running. Try again in a moment."),
    "unexpected": ("เกิดข้อผิดพลาด: {0}", "Something went wrong: {0}"),
    "save_token_failed": ("บันทึก token ไม่ได้: {0}", "Could not save the token: {0}"),
    "save_config_failed": ("บันทึกค่าตั้งไม่ได้: {0}", "Could not save the settings: {0}"),
    "bad_request": ("ข้อมูลไม่ถูกต้อง", "Invalid request"),
    "github_links_only": ("เปิดได้เฉพาะลิงก์ของ GitHub", "Only GitHub links can be opened"),
    # ความคืบหน้า
    "progress_start": ("กำลังเริ่ม", "Starting"),
    "progress_token": ("กำลังตรวจ token", "Checking the token"),
    "progress_repos": ("กำลังอ่านรายชื่อ repo", "Reading the repository list"),
    "progress_traffic": ("กำลังดึงยอดเข้าชมและดาวน์โหลด", "Collecting views and downloads"),
    # เก็บข้อมูลอัตโนมัติ
    "schedule_win_only": ("เก็บข้อมูลอัตโนมัติทุกวันมีเฉพาะบน Windows",
                          "Daily automatic collection is only available on Windows"),
    "schedule_need_install": ("ติดตั้งโปรแกรมก่อน จึงจะตั้งเก็บข้อมูลอัตโนมัติได้",
                              "Install the program first to turn on automatic collection"),
    "schedule_on_failed": ("ตั้งเก็บข้อมูลอัตโนมัติไม่สำเร็จ: {0}", "Could not turn on automatic collection: {0}"),
    "schedule_off_failed": ("ปิดเก็บข้อมูลอัตโนมัติไม่สำเร็จ: {0}", "Could not turn off automatic collection: {0}"),
    "settings_failed": ("ตั้งค่าไม่สำเร็จ: {0}", "Could not change the setting: {0}"),
    "schedule_text_win_only": ("เก็บข้อมูลอัตโนมัติทุกวันมีเฉพาะบน Windows ตอนนี้เก็บทุกครั้งที่เปิดโปรแกรม",
                               "Daily automatic collection is only available on Windows. For now, data is collected every time the program opens."),
    "schedule_text_on": ("เปิดอยู่: เก็บข้อมูลทุกวันเวลา 09:00 น. (ถ้าเครื่องปิดอยู่ตอนนั้น จะเก็บทันทีที่เปิดเครื่อง)",
                         "On: collects every day at 09:00 (if the computer is off then, it collects as soon as it starts)"),
    "schedule_text_off": ("ปิดอยู่: โปรแกรมเก็บข้อมูลทุกครั้งที่เปิด", "Off: the program collects every time it opens"),
    "schedule_text_need_install": ("ติดตั้งโปรแกรมก่อน จึงจะตั้งเก็บข้อมูลอัตโนมัติได้ ตอนนี้เก็บทุกครั้งที่เปิดโปรแกรม",
                                   "Install the program first to turn on automatic collection. For now, data is collected every time the program opens."),
    # ติดตั้ง / ถอนการติดตั้ง
    "install_win_only": ("ติดตั้งได้เฉพาะบน Windows", "Installation is only available on Windows"),
    "shortcut_failed": ("สร้างไอคอนไม่สำเร็จ: {0} ({1})", "Could not create the shortcut {0} ({1})"),
    "shortcut_win_only": ("ไม่ได้สร้างไอคอน (สร้างได้เฉพาะบน Windows)", "No shortcuts were created (only available on Windows)"),
    "shortcut_remove_failed": ("ลบไอคอนไม่ได้: {0} ({1})", "Could not remove the shortcut {0} ({1})"),
    "files_remove_failed": ("ลบไฟล์โปรแกรมได้ไม่ครบ ลบโฟลเดอร์นี้เองได้: {0} ({1})",
                            "Some program files could not be removed. You can delete this folder yourself: {0} ({1})"),
    "data_remove_failed": ("ลบข้อมูลได้ไม่ครบ ลบโฟลเดอร์นี้เองได้: {0} ({1})",
                           "Some data could not be removed. You can delete this folder yourself: {0} ({1})"),
}

# ชนิดไฟล์ใน release: ตัวติดตั้งคือสิ่งที่คนกดโหลดไปใช้ ส่วนแพ็กเกจ .7z มักถูกตัวติดตั้งแบบ Online โหลดต่อเอง
RE_INSTALLER = re.compile(r"\.(exe|msi|msix|appx|appxbundle|dmg|pkg|apk|aab|deb|rpm|appimage|snap|flatpak)$", re.I)
RE_PACKAGE = re.compile(r"\.(7z|zip|rar|tar\.gz|tgz|tar\.xz|tar\.bz2|gz|xz|bz2|whl|jar|nupkg|vsix|crx|xpi)$", re.I)
# หน้าแก้ไข/สร้าง/ลบไฟล์ เปิดได้แค่เจ้าของ จึงไม่นับเป็นหน้าที่คนอื่นสนใจ
RE_OWNER_ONLY = re.compile(r"^/(edit|new|delete|upload|settings)(/|$)")

CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".svg": "image/svg+xml",
}

FOLDER_LOCAL_APPDATA = "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}"
FOLDER_USER_PROGRAM_FILES = "{5CD7AEE2-2219-4A67-B85D-6C9CE15660CB}"
FOLDER_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
FOLDER_PROGRAMS = "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}"


def current_lang():
    """ภาษาที่ผู้ใช้เลือกไว้ล่าสุด (เก็บใน config.json)"""
    lang = load_config().get("lang")
    return lang if lang in LANGS else DEFAULT_LANG


def tr(key, *args, lang=None):
    """แปลรหัสข้อความเป็นภาษาที่ต้องการ ไม่ระบุภาษาจะใช้ภาษาที่ผู้ใช้เลือกไว้"""
    if lang not in LANGS:
        lang = current_lang()
    pair = MESSAGES.get(key)
    text = key if pair is None else pair[LANGS.index(lang)]
    if args:
        try:
            text = text.format(*args)
        except (IndexError, KeyError, ValueError):
            text = "%s %s" % (text, " ".join(str(a) for a in args))
    return text


class GMError(Exception):
    """ข้อผิดพลาดที่แสดงให้ผู้ใช้เห็นได้ตรง ๆ เก็บเป็นรหัสข้อความ แล้วค่อยแปลเป็นภาษาของหน้าจอตอนแสดง"""

    def __init__(self, key, *params, code="api", status=0):
        Exception.__init__(self, key)
        self.key = key
        self.params = params
        self.code = code
        self.status = status

    def text(self, lang=None):
        return tr(self.key, *self.params, lang=lang)

    def __str__(self):
        return self.text()


def utc_stamp(when=None):
    when = when or dt.datetime.now(dt.timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stamp(text):
    try:
        return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def day_of(ts):
    ts = ts or ""
    return ts[:10] if len(ts) >= 10 else ts


# ======================================================================
# Windows: เรียก API ของระบบผ่าน ctypes (มีมากับ Python อยู่แล้ว)
# ======================================================================

_WIN = None


def _winapi():
    """โหลดโครงสร้างของ Windows ครั้งเดียวตอนใช้งานจริง ระบบอื่นไม่โหลดส่วนนี้"""
    global _WIN
    if _WIN is None:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        def guid(text):
            u = uuid.UUID(text)
            return GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))

        _WIN = types.SimpleNamespace(ctypes=ctypes, wintypes=wintypes, GUID=GUID, DATA_BLOB=DATA_BLOB, guid=guid)
    return _WIN


def known_folder(folder_id, fallback):
    """หาโฟลเดอร์ของระบบตามจริง เช่น Desktop ที่ถูกย้ายไปอยู่ใน OneDrive"""
    if not IS_WIN:
        return fallback
    try:
        w = _winapi()
        ct = w.ctypes
        shell32 = ct.WinDLL("shell32")
        ole32 = ct.WinDLL("ole32")
        fn = shell32.SHGetKnownFolderPath
        fn.argtypes = [ct.POINTER(w.GUID), w.wintypes.DWORD, w.wintypes.HANDLE, ct.POINTER(ct.c_void_p)]
        fn.restype = ct.HRESULT
        ole32.CoTaskMemFree.argtypes = [ct.c_void_p]
        ole32.CoTaskMemFree.restype = None
        out = ct.c_void_p()
        fid = w.guid(folder_id)
        fn(ct.byref(fid), 0, None, ct.byref(out))
        try:
            path = ct.wstring_at(out.value) if out.value else ""
        finally:
            ole32.CoTaskMemFree(out)
        return path or fallback
    except Exception as e:  # ใช้ค่าสำรองถ้าเรียก API ไม่ได้
        logging.warning("known folder %s: %s", folder_id, e)
        return fallback


def _dpapi(data, encrypt):
    w = _winapi()
    ct = w.ctypes
    crypt32 = ct.WinDLL("crypt32", use_last_error=True)
    kernel32 = ct.WinDLL("kernel32")
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    blob_p = ct.POINTER(w.DATA_BLOB)
    fn.argtypes = [blob_p, ct.c_void_p, blob_p, ct.c_void_p, ct.c_void_p, w.wintypes.DWORD, blob_p]
    fn.restype = w.wintypes.BOOL
    kernel32.LocalFree.argtypes = [ct.c_void_p]
    kernel32.LocalFree.restype = ct.c_void_p
    data = bytes(data)
    buf = ct.create_string_buffer(data, len(data))
    blob_in = w.DATA_BLOB(len(data), ct.cast(buf, ct.POINTER(ct.c_char)))
    blob_out = w.DATA_BLOB()
    # 0x1 = CRYPTPROTECT_UI_FORBIDDEN: ห้ามระบบเด้งหน้าต่างถามผู้ใช้
    if not fn(ct.byref(blob_in), None, None, None, None, 0x1, ct.byref(blob_out)):
        raise ct.WinError(ct.get_last_error())
    try:
        return ct.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ct.cast(blob_out.pbData, ct.c_void_p))


def protect(data):
    """เข้ารหัสด้วยบัญชี Windows ของผู้ใช้ (DPAPI) ถอดได้เฉพาะบัญชีเดิมบนเครื่องเดิม"""
    if not IS_WIN:
        return bytes(data)  # ระบบอื่นใช้แค่ตอนทดสอบ
    return _dpapi(data, True)


def unprotect(data):
    if not IS_WIN:
        return bytes(data)
    return _dpapi(data, False)


def create_shortcut(lnk, target, arguments, workdir, description, icon):
    """สร้างไฟล์ .lnk ด้วย COM ของ Windows ถ้าวิธีแรกไม่ได้ ลองผ่าน pywin32 ที่มากับ Anaconda"""
    try:
        _shortcut_ctypes(lnk, target, arguments, workdir, description, icon)
        return
    except Exception as e:
        logging.warning("shortcut via ctypes failed: %s", e)
        first = e
    try:
        _shortcut_pywin32(lnk, target, arguments, workdir, description, icon)
    except Exception as e:
        logging.warning("shortcut via pywin32 failed: %s", e)
        raise first


def _shortcut_ctypes(lnk, target, arguments, workdir, description, icon):
    w = _winapi()
    ct = w.ctypes
    ole32 = ct.OleDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ct.c_void_p, w.wintypes.DWORD]
    ole32.CoCreateInstance.argtypes = [ct.POINTER(w.GUID), ct.c_void_p, w.wintypes.DWORD, ct.POINTER(w.GUID), ct.POINTER(ct.c_void_p)]
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    try:
        ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        initialized = True
    except OSError:
        initialized = False  # thread นี้เปิด COM แบบอื่นไว้แล้ว ใช้ต่อได้

    def method(obj, index, restype, *argtypes):
        vtbl = ct.cast(obj, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
        return ct.WINFUNCTYPE(restype, ct.c_void_p, *argtypes)(vtbl[index])

    hr, text = ct.HRESULT, ct.c_wchar_p
    clsid_shell_link = w.guid("{00021401-0000-0000-C000-000000000046}")
    iid_shell_link_w = w.guid("{000214F9-0000-0000-C000-000000000046}")
    iid_persist_file = w.guid("{0000010B-0000-0000-C000-000000000046}")
    link = ct.c_void_p()
    try:
        ole32.CoCreateInstance(ct.byref(clsid_shell_link), None, 1, ct.byref(iid_shell_link_w), ct.byref(link))
        try:
            # ลำดับใน vtable ของ IShellLinkW: SetDescription 7, SetWorkingDirectory 9, SetArguments 11, SetIconLocation 17, SetPath 20
            method(link, 20, hr, text)(link, target)
            method(link, 11, hr, text)(link, arguments)
            method(link, 9, hr, text)(link, workdir)
            method(link, 7, hr, text)(link, description)
            method(link, 17, hr, text, ct.c_int)(link, icon, 0)
            persist = ct.c_void_p()
            method(link, 0, hr, ct.POINTER(w.GUID), ct.POINTER(ct.c_void_p))(link, ct.byref(iid_persist_file), ct.byref(persist))
            try:
                method(persist, 6, hr, text, w.wintypes.BOOL)(persist, lnk, True)  # IPersistFile::Save
            finally:
                method(persist, 2, ct.c_ulong)(persist)  # Release
        finally:
            method(link, 2, ct.c_ulong)(link)
    finally:
        if initialized:
            ole32.CoUninitialize()


def _shortcut_pywin32(lnk, target, arguments, workdir, description, icon):
    import pythoncom
    from win32com.shell import shell

    pythoncom.CoInitialize()
    try:
        link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
        link.SetPath(target)
        link.SetArguments(arguments)
        link.SetWorkingDirectory(workdir)
        link.SetDescription(description)
        link.SetIconLocation(icon, 0)
        link.QueryInterface(pythoncom.IID_IPersistFile).Save(lnk, 0)
    finally:
        pythoncom.CoUninitialize()


def run_quiet(cmd, timeout=60):
    """รันคำสั่งของ Windows โดยไม่เปิดหน้าต่าง console คืน (exit code, ข้อความ)"""
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "timeout": timeout}
    if IS_WIN:
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    p = subprocess.run(cmd, **kw)
    out = p.stdout or b""
    for enc in ("oem", "mbcs", "utf-8"):
        try:
            return p.returncode, out.decode(enc).strip()
        except (LookupError, UnicodeDecodeError):
            continue
    return p.returncode, out.decode("utf-8", "replace").strip()


def gui_python():
    """pythonw.exe คือ Python แบบไม่มีหน้าต่าง console ใช้กับไอคอนและงานตามเวลา"""
    exe = sys.executable or "python"
    if IS_WIN:
        folder, name = os.path.split(exe)
        if name.lower() == "python.exe":
            w = os.path.join(folder, "pythonw.exe")
            if os.path.isfile(w):
                return w
    return exe


# ======================================================================
# โฟลเดอร์และไฟล์ของโปรแกรม
# ======================================================================


def data_dir():
    v = os.environ.get("GM_DATA_DIR")
    if v:
        return v
    if IS_WIN:
        local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(known_folder(FOLDER_LOCAL_APPDATA, local), APP_ID)
    return os.path.join(os.path.expanduser("~"), ".local", "share", APP_ID)


def install_dir():
    v = os.environ.get("GM_INSTALL_DIR")
    if v:
        return v
    if IS_WIN:
        local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(known_folder(FOLDER_USER_PROGRAM_FILES, os.path.join(local, "Programs")), APP_NAME)
    return os.path.join(os.path.expanduser("~"), ".local", "share", APP_ID + "-app")


DATA_DIR = data_dir()


def data_path(name):
    return os.path.join(DATA_DIR, name)


def can_install():
    return IS_WIN or bool(os.environ.get("GM_INSTALL_DIR"))


def is_installed():
    try:
        return os.path.samefile(APP_DIR, install_dir())
    except OSError:
        return False


def write_atomic(path, data):
    """เขียนไฟล์ชั่วคราวแล้วค่อยแทนที่ ไฟล์จริงจึงไม่ค้างครึ่ง ๆ กลาง ๆ ถ้าเครื่องดับ"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    last = None
    # บน Windows ถ้าโปรแกรมสแกนไวรัสหรือ indexer เปิดไฟล์อยู่ชั่วขณะ การแทนที่จะล้ม จึงลองซ้ำสั้น ๆ
    for _ in range(10):
        try:
            os.replace(tmp, path)
            return
        except OSError as e:
            last = e
            time.sleep(0.2)
    raise last


_file_lock = threading.Lock()


def load_config():
    try:
        with open(data_path("config.json"), encoding="utf-8") as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(c):
    write_atomic(data_path("config.json"), json.dumps(c, ensure_ascii=False, indent=2).encode("utf-8"))


def set_token(cfg, token):
    cfg["token"] = base64.b64encode(protect(token.encode("utf-8"))).decode("ascii")


def get_token(cfg):
    raw = cfg.get("token") or ""
    if not raw:
        return ""
    try:
        return unprotect(base64.b64decode(raw)).decode("utf-8")
    except Exception as e:
        logging.warning("token decrypt: %s", e)
        raise GMError("token_decrypt", code="token")


def empty_history():
    return {"version": 1, "owner": "", "collected_at": "", "errors": {}, "repos": [], "daily": [],
            "snapshots": [], "releases": [], "referrers": [], "paths": []}


def load_history():
    with _file_lock:
        path = data_path("history.json")
        try:
            with open(path, encoding="utf-8") as f:
                h = json.load(f)
        except FileNotFoundError:
            return empty_history()
        except (OSError, ValueError) as e:
            # เก็บไฟล์ที่อ่านไม่ได้ไว้ก่อน ไม่เขียนทับ เผื่อผู้ใช้อยากกู้คืน
            logging.error("history unreadable: %s", e)
            try:
                os.replace(path, path + ".broken")
            except OSError:
                pass
            return empty_history()
        base = empty_history()
        if isinstance(h, dict):
            for k, v in h.items():
                if v is not None:
                    base[k] = v
        return base


def save_history(h):
    with _file_lock:
        path = data_path("history.json")
        if os.path.exists(path):
            try:
                shutil.copyfile(path, path + ".bak")  # สำรองรอบก่อนไว้ 1 ชุด
            except OSError:
                pass
        write_atomic(path, json.dumps(h, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


# ======================================================================
# GitHub REST API
# ======================================================================


def api_base():
    return (os.environ.get("GM_API_BASE") or "https://api.github.com").rstrip("/")


class GitHub(object):
    def __init__(self, token):
        self.token = token

    def get(self, path):
        """เรียก API แล้วแปลง JSON ลองซ้ำเมื่อเซิร์ฟเวอร์มีปัญหาชั่วคราว"""
        last = None
        for attempt in range(3):
            if attempt:
                time.sleep(attempt * 2)
            req = urllib.request.Request(api_base() + path, headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "GitHubMonitor/%s (Python)" % APP_VERSION,
            })
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read(32 << 20)
            except urllib.error.HTTPError as e:
                status = e.code
                try:
                    detail = e.read(1 << 20)
                except Exception:
                    detail = b""
                if status == 401:
                    raise GMError("unauthorized", code="unauthorized", status=401)
                if (status == 403 and e.headers.get("X-RateLimit-Remaining") == "0") or status == 429:
                    last = GMError("rate", code="rate", status=status)
                    continue
                if status >= 500:
                    last = GMError("server", status, status=status)
                    continue
                message = ""
                try:
                    message = json.loads(detail.decode("utf-8")).get("message", "")
                except Exception:
                    pass
                raise GMError("http", status, message, status=status)
            except (OSError, http.client.HTTPException) as e:
                reason = getattr(e, "reason", None) or e
                last = GMError("network", reason, code="network")
                continue
            try:
                return json.loads(body.decode("utf-8"))
            except ValueError:
                raise GMError("bad_json")
        raise last

    def traffic(self, path):
        try:
            return self.get(path)
        except GMError as e:
            if e.code == "api" and e.status == 403:
                raise GMError("no_traffic", code="no_traffic", status=403)
            raise

    def user(self):
        return (self.get("/user") or {}).get("login", "")

    def repos(self, login):
        out = []
        for page in range(1, 21):
            batch = self.get("/user/repos?affiliation=owner&sort=full_name&per_page=100&page=%d" % page) or []
            for r in batch:
                if ((r.get("owner") or {}).get("login") or "").lower() == login.lower():
                    out.append(r)
            if len(batch) < 100:
                break
        return out


def fetch_repo(client, owner, repo):
    res = {"repo": repo, "views": {}, "clones": {}, "referrers": [], "paths": [], "releases": [], "error": None, "code": None}
    base = "/repos/%s/%s" % (urllib.parse.quote(owner, safe=""), urllib.parse.quote(repo.get("name", ""), safe=""))
    try:
        res["views"] = client.traffic(base + "/traffic/views?per=day") or {}
        res["clones"] = client.traffic(base + "/traffic/clones?per=day") or {}
        res["referrers"] = client.traffic(base + "/traffic/popular/referrers") or []
        res["paths"] = client.traffic(base + "/traffic/popular/paths") or []
        res["releases"] = client.get(base + "/releases?per_page=100") or []
    except GMError as e:
        res["error"], res["code"] = e.text("en"), e.code
    return res


class Progress(object):
    """ความคืบหน้าของการดึงข้อมูล ให้หน้าจอแสดง (เก็บเป็นรหัสข้อความ แปลตามภาษาของหน้าจอตอนส่ง)"""

    def __init__(self):
        self._mu = threading.Lock()
        self._s = {"running": False, "done": 0, "total": 0, "message": "", "last_at": ""}
        self._error = None

    def update(self, **kw):
        with self._mu:
            self._s.update(kw)

    def step(self):
        with self._mu:
            self._s["done"] += 1

    def begin(self):
        with self._mu:
            if self._s["running"]:
                return False
            self._s.update(running=True, done=0, total=0, message="progress_start")
            return True

    def end(self, error):
        """error คือ GMError ของรอบนี้ หรือ None ถ้าสำเร็จ"""
        with self._mu:
            self._s.update(running=False, message="", last_at=utc_stamp())
            self._error = error

    def clear_error(self):
        with self._mu:
            self._error = None

    def snapshot(self, lang=None):
        with self._mu:
            s, err = dict(self._s), self._error
        s["message"] = tr(s["message"], lang=lang) if s["message"] else ""
        s["last_error"] = err.text(lang) if err else ""
        s["last_error_code"] = err.code if err else ""
        return s


def collect(token, progress):
    """ดึงข้อมูลทุก repo แล้วรวมเข้ากับประวัติเดิม"""
    client = GitHub(token)
    progress.update(message="progress_token", done=0, total=0)
    login = client.user()
    progress.update(message="progress_repos")
    repos = client.repos(login)
    progress.update(total=len(repos), message="progress_traffic")

    def work(repo):
        try:
            return fetch_repo(client, login, repo)
        finally:
            progress.step()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(work, repos))
    # ถ้าทุก repo ติดเรื่องสิทธิ์ แปลว่า token ขาดสิทธิ์ Administration ไม่ใช่ปัญหาราย repo
    if results and all(r["code"] == "no_traffic" for r in results):
        raise GMError("no_traffic", code="no_traffic", status=403)
    h = merge(load_history(), login, results, dt.datetime.now(dt.timezone.utc))
    save_history(h)
    logging.info("collected %d repos, %d errors", len(results), len(h["errors"]))
    return h


def merge(prev, owner, results, now_utc):
    """รวมผลรอบนี้เข้ากับประวัติเดิม

    GitHub ให้ยอดรายวันย้อนหลังแค่ 14 วัน (วันตามเวลา UTC) จึงเขียนทับเฉพาะช่วงนั้น และเก็บวันที่เก่ากว่าไว้ตามเดิม
    repo ที่ดึงไม่สำเร็จใช้ค่าเดิมต่อ ไม่ถูกเขียนทับเป็น 0
    """
    h = empty_history()
    h["owner"] = owner
    h["collected_at"] = utc_stamp(now_utc)
    failed = set()
    for r in results:
        if r["error"]:
            failed.add(r["repo"]["name"])
            h["errors"][r["repo"]["name"]] = r["error"]

    # ---- ยอดรายวัน ----
    daily = {}
    active = set()
    for d in prev.get("daily") or []:
        daily[(d["date"], d["repo"])] = dict(d)
        active.add(d["repo"])
    today = now_utc.date()
    window = set((today - dt.timedelta(days=i)).isoformat() for i in range(14))
    for r in results:
        if r["error"]:
            continue
        name = r["repo"]["name"]
        views, clones = {}, {}
        for v in (r["views"] or {}).get("views") or []:
            views[day_of(v.get("timestamp"))] = v
            if v.get("count") or v.get("uniques"):
                active.add(name)
        for v in (r["clones"] or {}).get("clones") or []:
            clones[day_of(v.get("timestamp"))] = v
            if v.get("count") or v.get("uniques"):
                active.add(name)
        # repo ที่ยังไม่เคยมีใครเข้าเลยไม่ต้องเก็บแถว 0 ไว้ ไฟล์จะได้ไม่โตเปล่า ๆ
        if name not in active:
            continue
        for d in window | set(views) | set(clones):
            row = daily.get((d, name)) or {"date": d, "repo": name, "views": 0, "visitors": 0, "clones": 0, "cloners": 0}
            if d in views or d in window:
                v = views.get(d) or {}
                row["views"], row["visitors"] = v.get("count", 0), v.get("uniques", 0)
            if d in clones or d in window:
                v = clones.get(d) or {}
                row["clones"], row["cloners"] = v.get("count", 0), v.get("uniques", 0)
            daily[(d, name)] = row
    h["daily"] = sorted(daily.values(), key=lambda x: (x["date"], x["repo"]))

    # ---- release, แหล่งที่มา, หน้าที่ถูกเปิด (repo ที่ดึงไม่สำเร็จใช้ของเดิม) ----
    h["releases"] = [x for x in prev.get("releases") or [] if x["repo"] in failed]
    h["referrers"] = [x for x in prev.get("referrers") or [] if x["repo"] in failed]
    h["paths"] = [x for x in prev.get("paths") or [] if x["repo"] in failed]
    for r in results:
        if r["error"]:
            continue
        name = r["repo"]["name"]
        for rel in r["releases"]:
            assets = rel.get("assets") or []
            if rel.get("draft") or not assets:
                continue
            x = {"repo": name, "tag": rel.get("tag_name") or "",
                 "published": day_of(rel.get("published_at") or rel.get("created_at") or ""),
                 "assets": len(assets), "downloads_installer": 0, "downloads_package": 0, "downloads_other": 0, "downloads_all": 0}
            for a in assets:
                n, count = a.get("name") or "", a.get("download_count") or 0
                if RE_INSTALLER.search(n):
                    x["downloads_installer"] += count
                elif RE_PACKAGE.search(n):
                    x["downloads_package"] += count
                else:
                    x["downloads_other"] += count
            x["downloads_all"] = x["downloads_installer"] + x["downloads_package"] + x["downloads_other"]
            h["releases"].append(x)
        for f in r["referrers"]:
            h["referrers"].append({"repo": name, "referrer": f.get("referrer") or "", "views": f.get("count", 0), "visitors": f.get("uniques", 0)})
        prefix = "/" + owner + "/" + name
        for p in r["paths"]:
            path = p.get("path") or ""
            if path.lower().startswith(prefix.lower()):
                path = path[len(prefix):]
            path = path or "/"
            if RE_OWNER_ONLY.match(path):
                continue
            h["paths"].append({"repo": name, "path": path, "title": p.get("title") or "", "views": p.get("count", 0), "visitors": p.get("uniques", 0)})
    downloads = {}
    for x in h["releases"]:
        t = downloads.setdefault(x["repo"], [0, 0, 0])
        t[0] += x["downloads_installer"]
        t[1] += x["downloads_all"]
        t[2] += 1

    # ---- สรุปราย repo ----
    prev_repo = dict((x["repo"], x) for x in prev.get("repos") or [])
    for r in results:
        g = r["repo"]
        name = g["name"]
        x = {"repo": name, "description": g.get("description") or "", "fork": bool(g.get("fork")), "private": bool(g.get("private")),
             "stars": g.get("stargazers_count") or 0, "forks": g.get("forks_count") or 0, "open_issues": g.get("open_issues_count") or 0,
             "created": day_of(g.get("created_at")), "pushed": day_of(g.get("pushed_at"))}
        if r["error"]:
            p = prev_repo.get(name) or {}
            for k in ("views_14d", "visitors_14d", "clones_14d", "cloners_14d"):
                x[k] = p.get(k, 0)
        else:
            x["views_14d"] = (r["views"] or {}).get("count", 0)
            x["visitors_14d"] = (r["views"] or {}).get("uniques", 0)
            x["clones_14d"] = (r["clones"] or {}).get("count", 0)
            x["cloners_14d"] = (r["clones"] or {}).get("uniques", 0)
        t = downloads.get(name, [0, 0, 0])
        x["releases"], x["downloads_installer"], x["downloads_all"] = t[2], t[0], t[1]
        h["repos"].append(x)
    h["repos"].sort(key=lambda x: x["repo"].lower())

    # ---- ยอดสะสมตามวันที่เก็บ (วันตามเวลาเครื่อง) ไว้ดูว่า stars/ดาวน์โหลดเพิ่มขึ้นเท่าไร ----
    snaps, seen = {}, set()
    for s in prev.get("snapshots") or []:
        snaps[(s["date"], s["repo"])] = s
        seen.add(s["repo"])
    day = now_utc.astimezone().date().isoformat()
    for x in h["repos"]:
        if x["stars"] or x["forks"] or x["downloads_all"] or x["repo"] in seen:
            snaps[(day, x["repo"])] = {"date": day, "repo": x["repo"], "stars": x["stars"], "forks": x["forks"],
                                       "downloads_installer": x["downloads_installer"], "downloads_all": x["downloads_all"]}
    h["snapshots"] = sorted(snaps.values(), key=lambda s: (s["date"], s["repo"]))
    return h


def acquire_collect_lock():
    """กันไม่ให้เก็บข้อมูลซ้อนกันสองงาน (เช่น Task Scheduler กับปุ่มในหน้าจอ)"""
    path = data_path("collect.lock")
    try:
        if time.time() - os.path.getmtime(path) > 15 * 60:
            os.remove(path)  # lock ค้างจากงานที่ดับกลางคัน
    except OSError:
        pass
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        return path
    except OSError:
        return None


def release_collect_lock(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


# ======================================================================
# งานเก็บข้อมูลอัตโนมัติ (Task Scheduler) และการติดตั้ง
# ======================================================================

TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>GitHub Monitor: collect GitHub traffic and download counts once a day.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""

_task_cache = {"at": 0.0, "exists": False}


def _xml(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def installed_script():
    return os.path.join(install_dir(), SCRIPT_NAME)


def task_exists(refresh=False):
    if not IS_WIN:
        return False
    now = time.time()
    if refresh or now - _task_cache["at"] > 60:
        try:
            code, _ = run_quiet(["schtasks", "/Query", "/TN", TASK_NAME])
            _task_cache["exists"] = code == 0
        except Exception as e:
            logging.warning("schtasks query: %s", e)
            _task_cache["exists"] = False
        _task_cache["at"] = now
    return _task_cache["exists"]


def schedule_enable():
    if not IS_WIN:
        raise GMError("schedule_win_only", code="schedule")
    script = installed_script()
    if not os.path.isfile(script):
        raise GMError("schedule_need_install", code="schedule")
    doc = TASK_XML.format(
        start=dt.datetime.now().strftime("%Y-%m-%d") + "T09:00:00",
        command=_xml('"%s"' % gui_python()),
        arguments=_xml('"%s" --collect' % script),
        workdir=_xml(install_dir()),
    )
    tmp = os.path.join(tempfile.gettempdir(), "GitHubMonitor-task-%d.xml" % os.getpid())
    with open(tmp, "wb") as f:
        f.write(doc.encode("utf-16"))  # มี BOM ตามที่ schtasks ต้องการ
    try:
        code, out = run_quiet(["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/XML", tmp])
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    task_exists(refresh=True)
    if code != 0:
        raise GMError("schedule_on_failed", out or "schtasks exit %d" % code, code="schedule")
    logging.info("scheduled task created")


def schedule_disable():
    if not IS_WIN or not task_exists(refresh=True):
        return
    code, out = run_quiet(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
    task_exists(refresh=True)
    if code != 0:
        raise GMError("schedule_off_failed", out or "schtasks exit %d" % code, code="schedule")
    logging.info("scheduled task deleted")


def schedule_info(lang=None):
    if not IS_WIN:
        return {"available": False, "enabled": False, "text": tr("schedule_text_win_only", lang=lang)}
    enabled = task_exists()
    if enabled:
        key = "schedule_text_on"
    elif os.path.isfile(installed_script()):
        key = "schedule_text_off"
    else:
        key = "schedule_text_need_install"
    return {"available": enabled or os.path.isfile(installed_script()), "enabled": enabled, "text": tr(key, lang=lang)}


def install_info():
    return {"available": can_install(), "installed": is_installed(),
            "has_copy": os.path.isfile(installed_script()), "dir": install_dir()}


def shortcut_paths():
    home = os.path.expanduser("~")
    desk = known_folder(FOLDER_DESKTOP, os.path.join(home, "Desktop"))
    progs = known_folder(FOLDER_PROGRAMS, os.path.join(os.environ.get("APPDATA", home), "Microsoft", "Windows", "Start Menu", "Programs"))
    return [os.path.join(desk, APP_NAME + ".lnk"), os.path.join(progs, APP_NAME + ".lnk")]


def install(stop_other=False, lang=None):
    """คัดลอกโปรแกรมไปไว้ที่ถาวรและสร้างไอคอน (ไม่ต้องใช้สิทธิ์ admin)"""
    if not can_install():
        raise GMError("install_win_only", code="install")
    target = install_dir()
    if stop_other:
        info = read_instance()
        if info and ask_instance(info, "/api/quit"):
            time.sleep(2)  # ให้โปรแกรมตัวเดิมปิดก่อนคัดลอกไฟล์ใหม่ทับ
    os.makedirs(os.path.join(target, "ui"), exist_ok=True)
    if not is_installed():
        for name in (SCRIPT_NAME, ICON_NAME, "README.txt"):
            src = os.path.join(APP_DIR, name)
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(target, name))
        for name in os.listdir(UI_DIR):
            src = os.path.join(UI_DIR, name)
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(target, "ui", name))
    script = os.path.join(target, SCRIPT_NAME)
    python = gui_python()
    notes, shortcuts = [], []  # notes: (รหัสข้อความ, ค่าในข้อความ)
    if IS_WIN:
        for lnk in shortcut_paths():
            try:
                os.makedirs(os.path.dirname(lnk), exist_ok=True)
                create_shortcut(lnk, python, '"%s"' % script, target, DESCRIPTION, os.path.join(target, ICON_NAME))
                shortcuts.append(lnk)
            except Exception as e:
                logging.warning("shortcut %s: %s", lnk, e)
                notes.append(("shortcut_failed", (lnk, e)))
    else:
        notes.append(("shortcut_win_only", ()))
    info = {"python": python, "dir": target, "at": utc_stamp(), "version": APP_VERSION}
    write_atomic(data_path("install.json"), json.dumps(info, ensure_ascii=False, indent=2).encode("utf-8"))
    logging.info("installed to %s with %s", target, python)
    return {"dir": target, "python": python, "shortcuts": shortcuts,
            "warnings": [tr(k, *a, lang=lang) for k, a in notes],
            "warnings_en": [tr(k, *a, lang="en") for k, a in notes]}


def close_logging():
    root = logging.getLogger()
    for handler in list(root.handlers):
        try:
            handler.close()
        finally:
            root.removeHandler(handler)


def uninstall(delete_data, lang=None):
    if lang not in LANGS:
        lang = current_lang()  # อ่านก่อน เพราะอาจลบไฟล์ค่าตั้งทิ้งระหว่างทาง
    warnings = []
    if IS_WIN:
        try:
            schedule_disable()
        except GMError as e:
            warnings.append(e.text(lang))
        except Exception as e:
            warnings.append(tr("unexpected", e, lang=lang))
        for lnk in shortcut_paths():
            try:
                if os.path.exists(lnk):
                    os.remove(lnk)
            except OSError as e:
                warnings.append(tr("shortcut_remove_failed", lnk, e, lang=lang))
    target = install_dir()
    if os.path.isdir(target):
        try:
            os.chdir(os.path.expanduser("~"))  # Windows ไม่ยอมลบโฟลเดอร์ที่โปรแกรมกำลังใช้เป็นโฟลเดอร์ทำงาน
        except OSError:
            pass
        try:
            shutil.rmtree(target)
        except OSError as e:
            warnings.append(tr("files_remove_failed", target, e, lang=lang))
    logging.info("uninstalled (delete_data=%s)", delete_data)
    if delete_data:
        close_logging()  # ไฟล์ log ที่เปิดค้างไว้จะทำให้ลบโฟลเดอร์ข้อมูลไม่ได้
        try:
            shutil.rmtree(DATA_DIR)
        except OSError as e:
            warnings.append(tr("data_remove_failed", DATA_DIR, e, lang=lang))
    return warnings


# ======================================================================
# โปรแกรมที่เปิดอยู่ (เปิดซ้ำจะใช้ตัวเดิม) และการเปิดเบราว์เซอร์
# ======================================================================

_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # คุยกับ 127.0.0.1 ห้ามผ่าน proxy


def read_instance():
    try:
        with open(data_path("instance.json"), encoding="utf-8") as f:
            info = json.load(f)
        if int(info.get("port") or 0) and info.get("key"):
            return info
    except (OSError, ValueError, TypeError):
        pass
    return None


def ask_instance(info, path):
    """ส่งคำสั่งไปยังโปรแกรมที่เปิดอยู่แล้ว คืน True ถ้ามีตัวที่เปิดอยู่และรับคำสั่ง"""
    try:
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (int(info["port"]), path), data=b"{}", method="POST",
                                     headers={"X-GM-Key": str(info["key"]), "Content-Type": "application/json"})
        with _LOCAL_OPENER.open(req, timeout=3) as resp:
            return resp.status < 300
    except Exception:
        return False


def app_url(port, key, lang=None):
    # l= บอกหน้าจอว่าใช้ภาษาไหน หน้าจอจึงแสดงภาษาที่เลือกไว้ได้ตั้งแต่แรกโดยไม่กะพริบ
    return "http://127.0.0.1:%d/?k=%s&l=%s" % (port, key, lang if lang in LANGS else current_lang())


def open_url(url):
    if os.environ.get("GM_NO_WINDOW"):
        logging.info("open %s", url.split("?")[0])
        return
    webbrowser.open(url, new=2)


def open_folder(path):
    if os.environ.get("GM_NO_WINDOW"):
        logging.info("open folder %s", path)
        return
    if IS_WIN:
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ======================================================================
# เว็บเซิร์ฟเวอร์ในเครื่องสำหรับหน้าจอ
# ======================================================================


class Server(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer เดิมเรียก getfqdn ซึ่งบางเครือข่ายใช้เวลาหลายวินาที ไม่จำเป็นสำหรับ 127.0.0.1
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request, client_address):
        logging.debug("request error", exc_info=True)


class App(object):
    def __init__(self):
        self.key = secrets.token_hex(24)
        self.port = 0
        self.hosts = set()
        self.httpd = None
        self.progress = Progress()
        self.mu = threading.Lock()
        self.seen = False
        self.last_ping = 0.0
        self.bye = 0.0
        self.quit_reason = None
        self.collect_thread = None

    def touch(self):
        with self.mu:
            self.seen, self.last_ping = True, time.time()

    def stop(self, reason):
        with self.mu:
            if self.quit_reason:
                return
            self.quit_reason = reason
        logging.info("quit: %s", reason)
        threading.Thread(target=self.httpd.shutdown, daemon=True).start()

    def watchdog(self):
        """ปิดโปรแกรมเมื่อแท็บถูกปิด เผื่อเวลาไว้มากเพราะเบราว์เซอร์ชะลอแท็บที่ไม่ได้ดูอยู่"""
        start = time.time()
        while True:
            time.sleep(5)
            with self.mu:
                seen, last, bye, quitting = self.seen, self.last_ping, self.bye, self.quit_reason
            if quitting:
                return
            now = time.time()
            if not seen and now - start > 180:
                return self.stop("browser never connected")
            if seen and bye > last and now - bye > 15:
                return self.stop("tab closed")
            if seen and now - last > 30 * 60:
                return self.stop("tab idle")

    def start_collect(self):
        if not self.progress.begin():
            return False
        self.collect_thread = threading.Thread(target=self._collect_job, name="collect")
        self.collect_thread.start()
        return True

    def _collect_job(self):
        error = None
        lock = acquire_collect_lock()
        if lock is None:
            error = GMError("busy", code="busy")
        else:
            try:
                token = get_token(load_config())
                if not token:
                    error = GMError("no_token", code="token")
                else:
                    collect(token, self.progress)
            except GMError as e:
                error = e
            except Exception as e:
                logging.exception("collect")
                error = GMError("unexpected", e, code="internal")
            finally:
                release_collect_lock(lock)
        if error:
            logging.warning("collect error: %s", error.text("en"))
        self.progress.end(error)

    def auto_collect(self):
        """เปิดโปรแกรมแล้วเก็บข้อมูลให้เลย ถ้ารอบล่าสุดเก่ากว่า 6 ชั่วโมง"""
        try:
            if not load_config().get("token"):
                return
            last = parse_stamp(load_history().get("collected_at"))
            if last and dt.datetime.now(dt.timezone.utc) - last < dt.timedelta(hours=6):
                return
            self.start_collect()
        except Exception:
            logging.exception("auto collect")

    def state(self, lang=None):
        cfg = load_config()
        saved = cfg.get("lang") if cfg.get("lang") in LANGS else DEFAULT_LANG
        if lang not in LANGS:
            lang = saved
        return {
            "version": "%s (Python %s)" % (APP_VERSION, platform.python_version()),
            "lang": saved,
            "configured": bool(cfg.get("token")),
            "login": cfg.get("login", ""),
            "show_private": bool(cfg.get("show_private")),
            "collected_at": load_history().get("collected_at", ""),
            "progress": self.progress.snapshot(lang),
            "data_dir": DATA_DIR,
            "schedule": schedule_info(lang),
            "install": install_info(),
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "GitHubMonitor/" + APP_VERSION
    sys_version = ""

    def log_message(self, fmt, *args):
        logging.debug("http " + fmt, *args)

    @property
    def app(self):
        return self.server.app

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, code, message):
        self._json({"error": message}, code)

    def lang(self):
        """ภาษาของแท็บที่ส่งคำสั่งมา (หน้าจอส่ง X-GM-Lang มากับทุกคำสั่ง) ไม่มีก็ใช้ภาษาที่เลือกไว้"""
        v = self.headers.get("X-GM-Lang", "")
        return v if v in LANGS else current_lang()

    def _fail(self, code, key, *args):
        self._error(code, tr(key, *args, lang=self.lang()))

    def _guard(self):
        """ต้องมาที่ 127.0.0.1 ของพอร์ตนี้ และคำสั่ง /api ต้องมีรหัสของรอบนี้ กันเว็บอื่นในเครื่องยิงคำสั่งเข้ามา"""
        if self.headers.get("Host", "") not in self.app.hosts:
            self._send(403, b"forbidden", "text/plain")
            return None
        parts = urllib.parse.urlsplit(self.path)
        path = parts.path
        if path.startswith("/api/"):
            given = self.headers.get("X-GM-Key", "")
            if not given and path == "/api/bye":
                # สัญญาณตอนปิดแท็บส่งด้วย sendBeacon ซึ่งตั้ง header ไม่ได้ จึงรับรหัสจาก URL เฉพาะคำสั่งนี้
                given = (urllib.parse.parse_qs(parts.query).get("k") or [""])[0]
            given = given.encode("latin-1", "replace")
            if not hmac.compare_digest(given, self.app.key.encode("ascii")):
                self._send(403, b"forbidden", "text/plain")
                return None
        return path

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 65536:
            raise ValueError("body too large")
        raw = self.rfile.read(n) if n > 0 else b""
        if not raw.strip():
            return {}
        obj = json.loads(raw.decode("utf-8"))
        return obj if isinstance(obj, dict) else {}

    def do_GET(self):
        path = self._guard()
        if path is None:
            return
        if path == "/api/state":
            self.app.touch()
            return self._json(self.app.state(self.lang()))
        if path == "/api/history":
            return self._json(load_history())
        if path.startswith("/api/"):
            return self._error(404, "not found")
        name = "index.html" if path == "/" else path.lstrip("/")
        ext = os.path.splitext(name)[1].lower()
        file_path = os.path.join(UI_DIR, name)
        # เสิร์ฟเฉพาะไฟล์ระดับบนสุดในโฟลเดอร์ ui ที่มีนามสกุลที่รู้จัก
        if "/" in name or "\\" in name or ext not in STATIC_TYPES or not os.path.isfile(file_path):
            return self._send(404, b"not found", "text/plain")
        with open(file_path, "rb") as f:
            self._send(200, f.read(), STATIC_TYPES[ext])

    def do_DELETE(self):
        path = self._guard()
        if path is None:
            return
        if path != "/api/token":
            return self._error(404, "not found")
        cfg = load_config()
        cfg.pop("token", None)
        cfg.pop("login", None)
        save_config(cfg)
        self._json({"ok": True})

    def do_POST(self):
        path = self._guard()
        if path is None:
            return
        try:
            body = self._body()
        except (ValueError, UnicodeDecodeError):
            return self._fail(400, "bad_request")
        app = self.app
        if path == "/api/ping":
            app.touch()
            return self._json({"ok": True})
        if path == "/api/bye":
            # แท็บกำลังปิดหรือรีโหลด: ถ้าไม่มีสัญญาณกลับมาภายใน 15 วินาทีถือว่าปิดแล้ว
            with app.mu:
                app.bye = time.time()
            logging.info("tab closing or reloading")
            return self._json({"ok": True})
        if path == "/api/quit":
            self._json({"ok": True})
            return app.stop("quit requested")
        if path == "/api/token":
            return self._save_token(body)
        if path == "/api/settings":
            cfg = load_config()
            if "show_private" in body:
                cfg["show_private"] = bool(body["show_private"])
            if body.get("lang") in LANGS:
                cfg["lang"] = body["lang"]
            try:
                save_config(cfg)
            except OSError as e:
                return self._fail(500, "save_config_failed", e)
            return self._json({"ok": True})
        if path == "/api/collect":
            return self._json({"ok": True, "started": app.start_collect()})
        if path == "/api/open":
            target = str(body.get("target") or "")
            if target == "datadir":
                open_folder(DATA_DIR)
            elif target.startswith("https://github.com/") or target.startswith("https://docs.github.com/"):
                open_url(target)
            else:
                return self._fail(400, "github_links_only")
            return self._json({"ok": True})
        lang = self.lang()
        if path == "/api/schedule":
            try:
                if body.get("enabled"):
                    schedule_enable()
                else:
                    schedule_disable()
            except GMError as e:
                return self._error(400, e.text(lang))
            except Exception as e:
                logging.exception("schedule")
                return self._fail(500, "settings_failed", e)
            return self._json({"ok": True, "schedule": schedule_info(lang)})
        if path == "/api/install":
            try:
                res = install(stop_other=False, lang=lang)
            except GMError as e:
                return self._error(400, e.text(lang))
            except Exception as e:
                logging.exception("install")
                return self._error(500, str(e))  # หน้าจอเติม "ติดตั้งไม่สำเร็จ:" ให้เอง
            return self._json({"ok": True, "dir": res["dir"], "shortcuts": res["shortcuts"], "warnings": res["warnings"]})
        if path == "/api/uninstall":
            try:
                warnings = uninstall(bool(body.get("delete_data")), lang=lang)
            except Exception as e:
                logging.exception("uninstall")
                return self._error(500, str(e))  # หน้าจอเติม "ถอนการติดตั้งไม่สำเร็จ:" ให้เอง
            self._json({"ok": True, "warnings": warnings})
            return app.stop("uninstalled")
        return self._error(404, "not found")

    def _save_token(self, body):
        lang = self.lang()
        token = str(body.get("token") or "").strip()
        if len(token) < 20 or re.search(r"\s", token):
            return self._fail(400, "token_format")
        try:
            login = GitHub(token).user()
        except GMError as e:
            return self._error(400, e.text(lang))
        cfg = load_config()
        try:
            set_token(cfg, token)
        except Exception as e:
            logging.exception("protect token")
            return self._fail(500, "save_token_failed", e)
        cfg["login"] = login
        try:
            save_config(cfg)
        except OSError as e:
            return self._fail(500, "save_config_failed", e)
        self.app.progress.clear_error()
        self.app.start_collect()
        return self._json({"ok": True, "login": login})


# ======================================================================
# โหมดการทำงาน
# ======================================================================


def run_app():
    # เปิดซ้ำ: เปิดแท็บใหม่ของตัวที่เปิดอยู่ ไม่สร้างโปรแกรมตัวที่สอง
    info = read_instance()
    if info and ask_instance(info, "/api/ping"):
        open_url(app_url(int(info["port"]), info["key"]))
        logging.info("handed off to running instance")
        return 0
    app = App()
    httpd = Server(("127.0.0.1", 0), Handler)
    httpd.app = app
    app.httpd = httpd
    app.port = httpd.server_address[1]
    app.hosts = {"127.0.0.1:%d" % app.port, "localhost:%d" % app.port}
    instance = {"port": app.port, "key": app.key, "pid": os.getpid()}
    write_atomic(data_path("instance.json"), json.dumps(instance).encode("utf-8"))
    url = app_url(app.port, app.key)
    logging.info("ui at http://127.0.0.1:%d/", app.port)
    threading.Thread(target=app.auto_collect, name="auto-collect", daemon=True).start()
    if os.environ.get("GM_NO_WINDOW"):
        print("GitHub Monitor UI: " + url, flush=True)
    else:
        print("GitHub Monitor is running at http://127.0.0.1:%d/  (closing the browser tab stops it)" % app.port, flush=True)
        open_url(url)
        threading.Thread(target=app.watchdog, name="watchdog", daemon=True).start()
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        try:
            current = read_instance()
            if current and current.get("pid") == os.getpid():
                os.remove(data_path("instance.json"))
        except OSError:
            pass
        # รอให้งานเก็บข้อมูลที่ค้างอยู่จบก่อนปิด ข้อมูลจะได้ไม่หาย
        if app.collect_thread is not None:
            app.collect_thread.join(timeout=120)
    return 0


def run_collect_once():
    """ใช้ตอน Task Scheduler เรียก --collect ถ้าโปรแกรมเปิดอยู่ ให้ตัวที่เปิดอยู่เก็บแทน ไม่ให้สองตัวเขียนไฟล์พร้อมกัน"""
    info = read_instance()
    if info and ask_instance(info, "/api/collect"):
        logging.info("collect delegated to running instance")
        return 0
    try:
        token = get_token(load_config())
    except GMError as e:
        logging.error("collect: %s", e.text("en"))
        return 1
    if not token:
        logging.info("collect: no token")
        return 0
    lock = acquire_collect_lock()
    if lock is None:
        logging.info("collect: another collection is running")
        return 0
    try:
        collect(token, Progress())
        return 0
    except GMError as e:
        logging.error("collect: %s", e.text("en"))
        return 1
    except Exception:
        logging.exception("collect")
        return 1
    finally:
        release_collect_lock(lock)


def run_install_cli():
    print("GitHub Monitor %s - install" % APP_VERSION)
    print("Python: %s" % sys.executable)
    try:
        res = install(stop_other=True)
    except Exception as e:
        logging.exception("install")
        print("Install failed: %s" % e)
        return 1
    print("Installed to: %s" % res["dir"])
    for lnk in res["shortcuts"]:
        print("Shortcut: %s" % lnk)
    for note in res["warnings_en"]:
        print("Note: %s" % note)
    kw = {"cwd": res["dir"], "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if IS_WIN:
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    try:
        subprocess.Popen([res["python"], os.path.join(res["dir"], SCRIPT_NAME)], **kw)
    except OSError as e:
        print("Could not start GitHub Monitor: %s" % e)
        return 1
    print("Opening GitHub Monitor in your web browser ...")
    return 0


def setup_logging(mode):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        path = data_path("log.txt")
        try:
            if os.path.getsize(path) > 1 << 20:
                os.replace(path, path + ".old")  # ไม่ให้ไฟล์ log โตไปเรื่อย ๆ
        except OSError:
            pass
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.info("start %s %s (Python %s, %s) mode=%r pid=%d", APP_NAME, APP_VERSION, platform.python_version(), sys.executable, mode, os.getpid())


def main(argv):
    mode = argv[1] if len(argv) > 1 else ""
    if mode in ("-h", "--help"):
        print(__doc__)
        return 0
    if mode == "--version":
        print("%s %s" % (APP_NAME, APP_VERSION))
        return 0
    setup_logging(mode)
    if mode == "--collect":
        return run_collect_once()
    if mode == "--install":
        return run_install_cli()
    if mode in ("", "--portable"):
        return run_app()
    print("Unknown option %s (use --help)" % mode)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
