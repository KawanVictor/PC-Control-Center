"""Cor de destaque do Windows.

O app Configurações grava a cor em vários lugares; gravamos os mesmos:
* Explorer\\Accent: AccentPalette (8 tons, RGBA), AccentColorMenu, StartColorMenu (ABGR)
* DWM: AccentColor (ABGR), ColorizationColor e ColorizationAfterglow (ARGB, alfa 0xC4)
* Control Panel\\Desktop: AutoColorization (0 = manual, 1 = escolher a partir do papel de parede)
Tudo com backup em um único grupo — "desfazer" restaura a paleta original byte a byte.
"""
from __future__ import annotations

import colorsys
import winreg

from ..core import regbackup
from . import changes

HKCU = winreg.HKEY_CURRENT_USER
ACCENT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"
DWM = r"Software\Microsoft\Windows\DWM"
DESKTOP = r"Control Panel\Desktop"

# Cores sugeridas (as mesmas famílias da grade do Windows)
PRESETS = ["#0078D4", "#0063B1", "#8E8CD8", "#6B69D6", "#8764B8", "#B146C2", "#C239B3", "#E3008C",
           "#E81123", "#D13438", "#CA5010", "#FF8C00", "#FFB900", "#498205", "#107C10", "#00B294",
           "#038387", "#00B7C3", "#2D7D9A", "#515C6B", "#567C73", "#7E735F"]


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _abgr(r: int, g: int, b: int) -> int:
    return 0xFF000000 | (b << 16) | (g << 8) | r


def palette(hex_color: str) -> list[tuple[int, int, int]]:
    """8 tons: 3 mais claros, o próprio (índice 3), 3 mais escuros e o 8º preservado do Windows."""
    r, g, b = (c / 255 for c in _hex_to_rgb(hex_color))
    h, l, s = colorsys.rgb_to_hls(r, g, b)

    def tone(light: float) -> tuple[int, int, int]:
        rr, gg, bb = colorsys.hls_to_rgb(h, max(0.0, min(1.0, light)), s)
        return round(rr * 255), round(gg * 255), round(bb * 255)

    lights = [tone(l + (1 - l) * f) for f in (0.65, 0.40, 0.15)]
    darks = [tone(l * f) for f in (0.90, 0.69, 0.49)]   # proporções medidas na paleta padrão do Windows
    return lights + [_hex_to_rgb(hex_color)] + darks


def _set_auto(value: bool, reason: str, group: str) -> None:
    """Grava AutoColorization no MESMO tipo que o Windows já usa (normalmente DWORD)."""
    try:
        with winreg.OpenKey(HKCU, DESKTOP) as k:
            _v, vtype = winreg.QueryValueEx(k, "AutoColorization")
    except OSError:
        vtype = winreg.REG_DWORD
    data = (1 if value else 0) if vtype == winreg.REG_DWORD else ("1" if value else "0")
    regbackup.set_value(HKCU, DESKTOP, "AutoColorization", vtype, data, reason, group)


def current() -> dict:
    menu = regbackup.read_value(HKCU, ACCENT, "AccentColorMenu", None)
    auto = regbackup.read_value(HKCU, DESKTOP, "AutoColorization", 0)
    if isinstance(menu, int):
        r, g, b = menu & 0xFF, (menu >> 8) & 0xFF, (menu >> 16) & 0xFF
        color = f"#{r:02X}{g:02X}{b:02X}"
    else:
        color = "#0078D4"
    return {"color": color, "auto": str(auto) == "1"}


def set_accent(hex_color: str) -> int:
    group = regbackup.new_group()
    reason = f"personalize:cor de destaque → {hex_color}"
    pal = palette(hex_color)
    old = regbackup.read_value(HKCU, ACCENT, "AccentPalette", b"")
    last = bytes(old[28:32]) if isinstance(old, (bytes, bytearray)) and len(old) >= 32 else bytes((0xF7, 0x63, 0x0C, 0))
    data = b"".join(bytes((r, g, b, 0)) for r, g, b in pal[:7]) + last
    r, g, b = _hex_to_rgb(hex_color)
    dr, dg, db = pal[4]
    argb = 0xC4000000 | (r << 16) | (g << 8) | b
    sv = regbackup.set_value
    sv(HKCU, ACCENT, "AccentPalette", winreg.REG_BINARY, data, reason, group)
    sv(HKCU, ACCENT, "AccentColorMenu", winreg.REG_DWORD, _abgr(r, g, b), reason, group)
    sv(HKCU, ACCENT, "StartColorMenu", winreg.REG_DWORD, _abgr(dr, dg, db), reason, group)
    sv(HKCU, DWM, "AccentColor", winreg.REG_DWORD, _abgr(r, g, b), reason, group)
    sv(HKCU, DWM, "ColorizationColor", winreg.REG_DWORD, argb, reason, group)
    sv(HKCU, DWM, "ColorizationAfterglow", winreg.REG_DWORD, argb, reason, group)
    _set_auto(False, reason, group)
    changes.broadcast("ImmersiveColorSet")
    return changes.record("registry", f"Cor de destaque: {hex_color.upper()}", group=group,
                          broadcast=["ImmersiveColorSet"])


def set_auto_from_wallpaper(on: bool) -> int:
    group = regbackup.new_group()
    _set_auto(on, f"personalize:cor automática → {on}", group)
    changes.broadcast("ImmersiveColorSet")
    return changes.record("registry", f"Cor de destaque automática pelo papel de parede: {'sim' if on else 'não'}",
                          group=group, broadcast=["ImmersiveColorSet"])
