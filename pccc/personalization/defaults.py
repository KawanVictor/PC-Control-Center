"""Aplicativos padrão (somente leitura).

O Windows protege as associações padrão com um hash (UserChoice): programas externos NÃO
podem trocá-las silenciosamente — e não devem. Por isso aqui mostramos o app atual de cada
tipo e o botão "Alterar" abre a tela oficial do Windows já no item certo.
"""
from __future__ import annotations

import winreg
from dataclasses import dataclass

from .themes import load_indirect

HKCU, HKCR = winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT

# (categoria, tipo, é protocolo?)
ITEMS = [("Navegador", "https", True), ("Navegador (http)", "http", True), ("E-mail", "mailto", True),
         ("PDF", ".pdf", False), ("Música", ".mp3", False), ("Vídeo", ".mp4", False),
         ("Imagens (JPG)", ".jpg", False), ("Imagens (PNG)", ".png", False), ("Texto", ".txt", False),
         ("Páginas HTML", ".html", False), ("Arquivos ZIP", ".zip", False)]


@dataclass
class DefaultApp:
    category: str
    kind: str
    prog_id: str
    app_name: str


def _read(hive, path, name=""):
    try:
        with winreg.OpenKey(hive, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def prog_id_name(prog_id: str) -> str:
    if not prog_id:
        return "Padrão do Windows"
    for path, name in ((rf"{prog_id}\Application", "ApplicationName"), (prog_id, "FriendlyTypeName"),
                       (prog_id, "")):
        v = _read(HKCR, path, name)
        if v:
            v = load_indirect(str(v))
            if v and not v.startswith("@"):
                return v
    return prog_id


def list_defaults() -> list[DefaultApp]:
    out = []
    for cat, kind, proto in ITEMS:
        if proto:
            pid = _read(HKCU, rf"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{kind}\UserChoice",
                        "ProgId")
        else:
            pid = _read(HKCU, rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{kind}\UserChoice",
                        "ProgId")
        out.append(DefaultApp(cat, kind, pid or "", prog_id_name(pid or "")))
    return out


def settings_uri(kind: str) -> str:
    """Abre o Configurações → Aplicativos padrão já filtrando pelo tipo (Windows 11)."""
    return "ms-settings:defaultapps"
