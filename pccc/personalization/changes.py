"""Histórico de alterações de personalização (todas desfazíveis) e avisos ao Windows."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from ctypes import wintypes

import psutil

from ..core import regbackup
from ..core.database import Database
from ..core.logger import get_logger, log_operation

log = get_logger("personalization")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS personalization_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,          -- registry | wallpaper | theme | shortcut | spi | appbar
    title TEXT NOT NULL,
    data TEXT,                   -- JSON com o necessário para desfazer
    restored INTEGER NOT NULL DEFAULT 0
);
"""


def _db():
    db = Database.instance()
    if not getattr(db, "_perslog_ready", False):
        with db._lock:
            db._conn.executescript(_SCHEMA)
            db._conn.commit()
        db._perslog_ready = True
    return db


def record(kind: str, title: str, **data) -> int:
    db = _db()
    with db._lock:
        cur = db._conn.execute("INSERT INTO personalization_log (ts, kind, title, data) VALUES (?, ?, ?, ?)",
                               (int(time.time()), kind, title, json.dumps(data)))
        db._conn.commit()
    log_operation(f"personalize.{kind}", title)
    return cur.lastrowid


def history(limit: int = 100) -> list[dict]:
    db = _db()
    with db._lock:
        rows = db._conn.execute("SELECT id, ts, kind, title, data, restored FROM personalization_log "
                                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r[0], "ts": r[1], "kind": r[2], "title": r[3], "data": json.loads(r[4] or "{}"),
             "restored": bool(r[5])} for r in rows]


def undo(change_id: int) -> str:
    """Desfaz uma alteração. Retorna uma mensagem para o usuário."""
    entry = next((h for h in history(1000) if h["id"] == change_id), None)
    if entry is None:
        raise KeyError(change_id)
    if entry["restored"]:
        return "Esta alteração já foi desfeita."
    d, kind = entry["data"], entry["kind"]
    msg = "Alteração desfeita."
    if d.get("group"):
        regbackup.restore_group(d["group"])
    if kind == "autotheme":
        # desliga o tema automático e volta ao modo que estava antes de ligá-lo
        import winreg
        from ..core.config import Settings
        from .tweaks import PERSONALIZE
        from .autotheme import AutoTheme
        AutoTheme.instance().stop()
        Settings.instance().set("autotheme.enabled", False)
        g = regbackup.new_group()
        for name, key in (("AppsUseLightTheme", "apps"), ("SystemUsesLightTheme", "system")):
            if key in d:
                regbackup.set_value(winreg.HKEY_CURRENT_USER, PERSONALIZE, name, winreg.REG_DWORD, int(d[key]),
                                    "personalize:desfazer tema automático", g)
        broadcast("ImmersiveColorSet")
        if d.get("app_mode"):
            Settings.instance().set("appearance.mode", d["app_mode"])
        msg = "Tema automático desligado e modo anterior restaurado."
    if kind == "dynwall":
        from ..core.config import Settings
        from .dynwall import DynamicWallpaper
        from .dynwall import set_image
        DynamicWallpaper.instance().stop()
        Settings.instance().set("dynwall.enabled", False)
        orig = d.get("previous_original")
        prev = orig if orig and os.path.exists(orig) else d.get("previous")
        if prev and os.path.exists(prev):
            set_image(prev, d.get("style") or "fill")
            msg = "Papel de parede dinâmico desligado e imagem anterior restaurada."
        else:
            msg = "Papel de parede dinâmico desligado (a imagem anterior não existe mais)."
    if kind == "wallpaper":
        from .wallpaper import _spi_set_wallpaper
        # Prefere o arquivo original; a cópia de segurança é usada se ele não existir mais.
        orig = d.get("previous_original")
        prev = orig if orig and os.path.exists(orig) else d.get("previous")
        if prev and os.path.exists(prev):
            _spi_set_wallpaper(prev)
        else:
            msg = "A imagem anterior não existe mais; o estilo foi restaurado."
    elif kind == "theme":
        prev = d.get("previous")
        if prev and os.path.exists(prev):
            os.startfile(prev)
            msg = "O tema anterior foi reaplicado (o Windows pode abrir as Configurações)."
        else:
            msg = "O arquivo do tema anterior não existe mais."
    elif kind == "shortcut":
        from ..core.safety import safe_delete_file
        path = d.get("path")
        if path and safe_delete_file(path, "desfazer atalho criado pelo app"):
            msg = f"Atalho removido: {path}"
        else:
            msg = "O atalho já não existia."
    elif kind == "spi":
        from . import tweaks
        tweaks.set_spi(d["action"], d["previous"], record_change=False)
    elif kind == "appbar":
        from . import tweaks
        tweaks.set_taskbar_autohide(bool(d["previous"]), record_change=False)
    for area in d.get("broadcast", []) or []:
        broadcast(area)
    if d.get("refresh_desktop"):
        refresh_desktop()
    if d.get("explorer_restart"):
        msg += " Reinicie o Explorer para ver o efeito completo."
    db = _db()
    with db._lock:
        db._conn.execute("UPDATE personalization_log SET restored = 1 WHERE id = ?", (change_id,))
        db._conn.commit()
    log_operation("personalize.undo", entry["title"])
    return msg


# ----------------------------------------------------------- avisos ao Windows
def broadcast(area: str | None) -> None:
    """WM_SETTINGCHANGE: avisa Explorer e apps que uma configuração mudou (aplica sem reiniciar)."""
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    res = wintypes.DWORD()
    user32 = ctypes.WinDLL("user32")
    user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_wchar_p,
                                           wintypes.UINT, wintypes.UINT, ctypes.POINTER(wintypes.DWORD)]
    user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, area, SMTO_ABORTIFHUNG, 1500,
                               ctypes.byref(res))


def refresh_desktop() -> None:
    """Atualiza ícones da área de trabalho e associações (equivale a F5 no Explorer)."""
    SHCNE_ASSOCCHANGED, SHCNF_IDLIST = 0x08000000, 0
    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)


def restart_explorer() -> None:
    """Reinicia o Explorer (barra de tarefas/área de trabalho). Janelas de pasta abertas fecham."""
    try:
        me = psutil.Process().username()
    except psutil.Error:
        me = None
    for p in psutil.process_iter(["name", "username"]):
        # só o Explorer do usuário atual (outras contas conectadas não são afetadas)
        if (p.info["name"] or "").lower() == "explorer.exe" and (me is None or p.info["username"] == me):
            try:
                p.terminate()
            except psutil.Error:
                pass
    time.sleep(1.5)
    # O Windows costuma reiniciar o shell sozinho; se não, inicia manualmente.
    if not any((p.info["name"] or "").lower() == "explorer.exe" for p in psutil.process_iter(["name"])):
        subprocess.Popen(["explorer.exe"], close_fds=True)
    log_operation("personalize.restart_explorer")
