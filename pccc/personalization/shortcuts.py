"""Criação de atalhos (.lnk) personalizados, com modelos prontos.

Atalhos criados entram no histórico: "desfazer" apaga o arquivo .lnk criado (nada mais).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ..core.com import ensure_com
from ..core.paths import is_frozen
from . import changes

WINDIR = os.environ.get("WINDIR", r"C:\Windows")
SYS32 = os.path.join(WINDIR, "System32")

# (nome, alvo, argumentos, ícone "arquivo,índice", descrição)
TEMPLATES = [
    ("Desligar o PC", os.path.join(SYS32, "shutdown.exe"), "/s /t 0", os.path.join(SYS32, "shell32.dll") + ",27",
     "Desliga imediatamente ao clicar"),
    ("Reiniciar o PC", os.path.join(SYS32, "shutdown.exe"), "/r /t 0", os.path.join(SYS32, "shell32.dll") + ",238",
     "Reinicia imediatamente ao clicar"),
    ("Bloquear a tela", os.path.join(SYS32, "rundll32.exe"), "user32.dll,LockWorkStation",
     os.path.join(SYS32, "shell32.dll") + ",47", "Mesmo que Win + L"),
    ("Modo Deus (todas as configurações)", os.path.join(WINDIR, "explorer.exe"),
     "shell:::{ED7BA470-8E54-465E-825C-99712043E01C}", os.path.join(SYS32, "imageres.dll") + ",109",
     "Pasta com mais de 200 configurações do Windows"),
    ("Gerenciador de Tarefas", os.path.join(SYS32, "Taskmgr.exe"), "", "", "Abre o Gerenciador de Tarefas"),
    ("Configurações do Windows", os.path.join(WINDIR, "explorer.exe"), "ms-settings:", "", "Abre o Configurações"),
]


def locations() -> dict[str, Path]:
    appdata = Path(os.environ.get("APPDATA", ""))
    return {
        "desktop": _onedrive_desktop() or Path(os.path.expanduser("~")) / "Desktop",
        "start": appdata / r"Microsoft\Windows\Start Menu\Programs",
    }


def _onedrive_desktop() -> Path | None:
    """Área de trabalho real (pode estar redirecionada para o OneDrive)."""
    import ctypes
    from ctypes import wintypes
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0:  # CSIDL_DESKTOPDIRECTORY
        return Path(buf.value)
    return None


def _unique(folder: Path, name: str) -> Path:
    safe = "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "Atalho"
    p = folder / f"{safe}.lnk"
    i = 2
    while p.exists():
        p = folder / f"{safe} ({i}).lnk"
        i += 1
    return p


def create_shortcut(name: str, target: str, args: str = "", where: str = "desktop", icon: str = "",
                    workdir: str = "", folder: Path | None = None) -> int:
    """Cria o .lnk e registra no histórico. ``folder`` permite outro destino (usado nos testes)."""
    if not target:
        raise ValueError("Informe o programa, pasta ou site de destino.")
    is_url = target.startswith(("http://", "https://"))
    if not is_url and not os.path.exists(target):
        raise ValueError("O destino não existe.")
    dest_dir = folder or locations()[where]
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = _unique(dest_dir, name)
    ensure_com(multithreaded=False)
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    if is_url:
        # Atalho de site: abre pelo navegador padrão via explorer
        sc = shell.CreateShortcut(str(path))
        sc.TargetPath = os.path.join(WINDIR, "explorer.exe")
        sc.Arguments = f'"{target}"'
        sc.IconLocation = os.path.join(SYS32, "shell32.dll") + ",13"
    else:
        sc = shell.CreateShortcut(str(path))
        sc.TargetPath = target
        sc.Arguments = args
        sc.WorkingDirectory = workdir or (os.path.dirname(target) if os.path.isfile(target) else "")
        if icon:
            sc.IconLocation = icon
    sc.Save()
    place = "pasta escolhida" if folder else ("Área de trabalho" if where == "desktop" else "Menu Iniciar")
    return changes.record("shortcut", f"Atalho criado: {path.name} ({place})",
                          path=str(path), target=target, args=args)


def app_target() -> tuple[str, str]:
    """Alvo e argumentos para um atalho do próprio PC Control Center."""
    if is_frozen():
        return sys.executable, ""
    exe = Path(sys.executable).with_name("pythonw.exe")
    main_py = Path(__file__).resolve().parents[2] / "main.py"
    return str(exe), f'"{main_py}"'
