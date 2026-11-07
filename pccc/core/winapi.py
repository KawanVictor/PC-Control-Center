"""Integrações nativas com o Windows (ctypes / pywin32)."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

from .logger import get_logger, log_operation

log = get_logger("winapi")

CREATE_NO_WINDOW = 0x08000000


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def windows_build() -> int:
    return sys.getwindowsversion().build


def apply_window_effects(hwnd: int, dark: bool) -> None:
    """Barra de título escura/clara e cantos arredondados (Windows 11)."""
    try:
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (19 em builds antigos do Win10)
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(value),
                                         ctypes.sizeof(value)) == 0:
                break
        if windows_build() >= 22000:
            corner = ctypes.c_int(2)  # DWMWCP_ROUND
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(corner), ctypes.sizeof(corner))
    except Exception as e:
        log.debug("Efeitos DWM indisponíveis: %s", e)


def shell_open(target: str, args: str = "", admin: bool = False) -> bool:
    """Abre um programa/documento via ShellExecute. ``admin`` pede elevação (UAC)."""
    verb = "runas" if admin else "open"
    rc = ctypes.windll.shell32.ShellExecuteW(None, verb, target, args or None, None, 1)
    ok = rc > 32
    log_operation("shell.open", f"{target} {args} admin={admin}", "ok" if ok else f"erro {rc}")
    return ok


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


def shell_execute_wait(target: str, args: str = "", timeout_s: float = 3600, show: int = 1) -> int | None:
    """Executa via ShellExecuteEx (respeita o UAC do próprio programa) e espera terminar.

    Retorna o código de saída, ou None se não foi possível iniciar (ex.: UAC recusado).
    Deve ser chamado fora da thread da interface.
    """
    SEE_MASK_NOCLOSEPROCESS = 0x40
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "open"
    info.lpFile = target
    info.lpParameters = args or None
    info.nShow = show
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()   # 1223 = usuário recusou o UAC
        log_operation("shell.execute", f"{target} {args}", f"erro {err}")
        return None
    log_operation("shell.execute", f"{target} {args}")
    if not info.hProcess:
        return 0
    k32 = ctypes.WinDLL("kernel32")
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.WaitForSingleObject(info.hProcess, int(timeout_s * 1000))
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    k32.CloseHandle(info.hProcess)
    return code.value


def open_folder(path: str) -> bool:
    """Abre a pasta no Explorer; se for um arquivo, abre a pasta com ele selecionado."""
    if not path or not os.path.exists(path):
        return False
    if os.path.isfile(path):
        subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)])
    else:
        os.startfile(path)
    return True


def relaunch_as_admin() -> bool:
    """Reabre o próprio app elevado. O processo atual deve encerrar se retornar True."""
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(sys.argv[1:])
    else:
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in [os.path.abspath(sys.argv[0])] + sys.argv[1:])
    return shell_open(exe, params, admin=True)


def run_hidden(cmd: list[str], timeout: float = 10) -> str:
    """Executa um comando sem abrir janela e devolve a saída (texto)."""
    out = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    for enc in ("utf-8", "cp850", "mbcs"):
        try:
            return out.stdout.decode(enc)
        except UnicodeDecodeError:
            continue
    return out.stdout.decode("utf-8", "replace")
