"""Temas do Windows (.theme): listar, mostrar prévia e aplicar.

Aplicar um tema usa o próprio Windows (abrir o arquivo .theme), que troca papel de parede,
cores, sons e cursores de forma consistente. O tema anterior fica no histórico para desfazer.
"""
from __future__ import annotations

import configparser
import ctypes
import glob
import os
import winreg
from dataclasses import dataclass

from ..core import regbackup
from . import changes

HKCU = winreg.HKEY_CURRENT_USER
THEMES_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes"


def load_indirect(s: str) -> str:
    """Resolve textos como '@%SystemRoot%\\System32\\themeui.dll,-2013' ou '@{pacote?ms-resource:...}'."""
    if not s or not s.startswith("@"):
        return s
    buf = ctypes.create_unicode_buffer(512)
    try:
        if ctypes.windll.shlwapi.SHLoadIndirectString(os.path.expandvars(s), buf, 512, None) == 0:
            return buf.value
    except Exception:
        pass
    return s


@dataclass
class ThemeInfo:
    path: str
    name: str
    wallpaper: str
    mode: str          # Escuro / Claro / ""
    current: bool = False


def list_themes() -> list[ThemeInfo]:
    win = os.environ.get("WINDIR", r"C:\Windows")
    files = glob.glob(os.path.join(win, r"Resources\Themes\*.theme"))
    files += glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Themes\*.theme"))
    cur = (regbackup.read_value(HKCU, THEMES_KEY, "CurrentTheme", "") or "").lower()
    out = []
    for f in files:
        cp = configparser.RawConfigParser(strict=False, interpolation=None)
        try:
            cp.read(f, encoding="utf-8-sig")
        except Exception:
            try:
                cp.read(f, encoding="mbcs")
            except Exception:
                continue
        name = load_indirect(cp.get("Theme", "DisplayName", fallback="") or os.path.splitext(os.path.basename(f))[0])
        if name.lower() == "custom":
            name = "Personalizado (atual)"
        wp = os.path.expandvars(cp.get("Control Panel\\Desktop", "Wallpaper", fallback=""))
        mode = cp.get("VisualStyles", "SystemMode", fallback="") or cp.get("VisualStyles", "AppMode", fallback="")
        mode = {"dark": "Escuro", "light": "Claro"}.get(mode.lower(), "")
        out.append(ThemeInfo(f, name, wp if os.path.isfile(wp) else "", mode, f.lower() == cur))
    return out


def apply_theme(path: str) -> int:
    if not path.lower().endswith(".theme") or not os.path.isfile(path):
        raise ValueError("Arquivo de tema inválido.")
    previous = regbackup.read_value(HKCU, THEMES_KEY, "CurrentTheme", "")
    os.startfile(path)   # o Windows aplica o tema (e abre a página de Personalização)
    return changes.record("theme", f"Tema aplicado: {os.path.basename(path)}", previous=previous, new=path)
