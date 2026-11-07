"""Papel de parede.

Antes de trocar, a imagem atual é COPIADA para %APPDATA%\\PCControlCenter\\wallpapers
(o arquivo original pode ser temporário ou apagado depois) — assim "desfazer" sempre
consegue voltar à imagem anterior. O estilo (preencher, ajustar...) vai para o Registro com backup.
"""
from __future__ import annotations

import ctypes
import glob
import os
import shutil
import time
import winreg

from ..core import regbackup
from ..core.paths import data_dir
from . import changes

HKCU = winreg.HKEY_CURRENT_USER
DESKTOP = r"Control Panel\Desktop"
SPI_GETDESKWALLPAPER, SPI_SETDESKWALLPAPER = 0x0073, 0x0014
SPIF = 0x01 | 0x02

# estilo → (WallpaperStyle, TileWallpaper)
STYLES = {"fill": ("10", "0"), "fit": ("6", "0"), "stretch": ("2", "0"), "tile": ("0", "1"),
          "center": ("0", "0"), "span": ("22", "0")}
STYLE_LABELS = {"fill": "Preencher", "fit": "Ajustar", "stretch": "Ampliar", "tile": "Lado a lado",
                "center": "Centralizar", "span": "Estender (vários monitores)"}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".jfif", ".heic")


def backup_dir():
    d = data_dir() / "wallpapers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def current_path() -> str:
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, 1024, buf, 0)
    return buf.value


def current_style() -> str:
    ws = str(regbackup.read_value(HKCU, DESKTOP, "WallpaperStyle", "10"))
    tile = str(regbackup.read_value(HKCU, DESKTOP, "TileWallpaper", "0"))
    for key, (s, t) in STYLES.items():
        if s == ws and t == tile:
            return key
    return "fill"


def _spi_set_wallpaper(path: str) -> bool:
    return bool(ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, path, SPIF))


def builtin_wallpapers() -> list[str]:
    win = os.environ.get("WINDIR", r"C:\Windows")
    files = []
    for pattern in (r"Web\Wallpaper\**\*.*", r"Web\4K\Wallpaper\Windows\*.*"):
        files += [f for f in glob.glob(os.path.join(win, pattern), recursive=True)
                  if f.lower().endswith(IMAGE_EXT)]
    # remove duplicatas de resolução (4K) mantendo a ordem
    seen, out = set(), []
    for f in files:
        k = os.path.basename(f).lower()
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out[:40]


def set_wallpaper(path: str, style: str = "fill") -> int:
    if not os.path.isfile(path) or not path.lower().endswith(IMAGE_EXT):
        raise ValueError("Escolha um arquivo de imagem válido.")
    if style not in STYLES:
        raise ValueError("Estilo inválido.")
    prev = current_path()
    saved = ""
    if prev and os.path.isfile(prev):
        ext = os.path.splitext(prev)[1] or ".jpg"
        saved = str(backup_dir() / f"anterior_{int(time.time())}{ext}")
        shutil.copy2(prev, saved)
    group = regbackup.new_group()
    ws, tile = STYLES[style]
    reason = f"personalize:papel de parede → {os.path.basename(path)}"
    regbackup.set_value(HKCU, DESKTOP, "WallpaperStyle", winreg.REG_SZ, ws, reason, group)
    regbackup.set_value(HKCU, DESKTOP, "TileWallpaper", winreg.REG_SZ, tile, reason, group)
    if not _spi_set_wallpaper(os.path.abspath(path)):
        regbackup.restore_group(group)
        raise OSError("O Windows recusou a imagem.")
    return changes.record("wallpaper", f"Papel de parede: {os.path.basename(path)} ({STYLE_LABELS[style]})",
                          group=group, previous_original=prev, previous=saved, new=os.path.abspath(path))


def set_style(style: str) -> int:
    return set_wallpaper(current_path(), style)


def previous_wallpapers(limit: int = 12) -> list[str]:
    files = sorted(backup_dir().glob("anterior_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(f) for f in files[:limit]]
