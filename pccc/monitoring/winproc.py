"""Dados de processos que exigem APIs de janela/processo do Windows.

* ``visible_windows()`` — PID → título da janela principal visível (como a seção
  "Aplicativos" do Gerenciador de Tarefas: janelas visíveis, sem dono, não ocultas pelo DWM)
* ``image_path(pid)``   — caminho completo do executável (sem administrador, via
  PROCESS_QUERY_LIMITED_INFORMATION)
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_dwm = ctypes.WinDLL("dwmapi")

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_CLOAKED = 14

_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [_EnumProc, wintypes.LPARAM]
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]


def visible_windows() -> dict[int, str]:
    result: dict[int, str] = {}

    def cb(hwnd, _lp):
        if not _user32.IsWindowVisible(hwnd) or _user32.GetWindow(hwnd, GW_OWNER):
            return True
        if _user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        n = _user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        cloaked = wintypes.DWORD(0)
        _dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if cloaked.value:
            return True  # janela "escondida" (apps UWP suspensos, outras áreas de trabalho)
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        result.setdefault(pid.value, buf.value)
        return True

    _user32.EnumWindows(_EnumProc(cb), 0)
    return result


def image_path(pid: int) -> str:
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        _kernel32.CloseHandle(h)


def current_session() -> int:
    import os
    s = wintypes.DWORD()
    _kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(s))
    return s.value
