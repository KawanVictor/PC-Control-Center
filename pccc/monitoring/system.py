"""Informações estáticas do sistema (nome do PC, versão do Windows, tempo ligado)."""
from __future__ import annotations

import platform
import sys
import time
import winreg

import psutil


def windows_version() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
            def q(name, default=""):
                try:
                    return winreg.QueryValueEx(k, name)[0]
                except OSError:
                    return default
            product = q("ProductName", "Windows")
            build = int(q("CurrentBuildNumber", "0") or 0)
            if build >= 22000:  # o registro ainda diz "Windows 10" no Windows 11
                product = product.replace("Windows 10", "Windows 11")
            return f"{product} {q('DisplayVersion')} (build {build}.{q('UBR', 0)})".replace("  ", " ")
    except OSError:
        return f"Windows {platform.release()} (build {sys.getwindowsversion().build})"


def system_info() -> dict:
    return {
        "hostname": platform.node(),
        "os": windows_version(),
        "arch": platform.machine(),
        "boot_time": psutil.boot_time(),
    }


def uptime_seconds() -> float:
    return time.time() - psutil.boot_time()
