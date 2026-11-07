"""Programas que iniciam com o Windows.

Fontes (as mesmas da aba "Aplicativos de inicialização" do Gerenciador de Tarefas):
* HKCU / HKLM \\...\\CurrentVersion\\Run  (e WOW6432Node para 32 bits)
* Pastas "Inicializar" do usuário e de todos os usuários
* Apps da Microsoft Store com tarefa de inicialização (StartupTask)

Ativar/desativar usa o MESMO mecanismo do Gerenciador de Tarefas: o valor em
...\\Explorer\\StartupApproved (ou o State da StartupTask). A entrada original nunca é
apagada, então a mudança é 100% reversível — e todo valor alterado ganha backup antes.
"""
from __future__ import annotations

import os
import struct
import time
import winreg
from dataclasses import dataclass
from pathlib import Path

from ..core import regbackup
from ..core.fileinfo import version_info
from ..core.logger import get_logger, log_operation
from .installed import split_command

log = get_logger("startup")

HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
APPMODEL = (r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
            r"\AppModel\SystemAppData")

# (hive, chave Run, subchave em StartupApproved, rótulo)
RUN_SOURCES = [
    (HKCU, r"Software\Microsoft\Windows\CurrentVersion\Run", "Run", "Registro (usuário)"),
    (HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "Run", "Registro (todos os usuários)"),
    (HKLM, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "Run32",
     "Registro (todos os usuários, 32 bits)"),
]


GENERIC_HOSTS = {"python", "pythonw", "windows host process (rundll32)", "windows command processor",
                 "windows powershell", "microsoft ® console based script host", "microsoft ® windows based script host",
                 "java(tm) platform se binary", "node.js javascript runtime"}


@dataclass
class StartupItem:
    name: str                 # nome do valor / atalho / tarefa
    command: str
    source: str               # rótulo legível
    kind: str                 # run | folder | store
    hive: int
    approved_path: str        # chave onde fica o estado
    approved_name: str        # nome do valor de estado
    enabled: bool = True
    exe: str = ""
    publisher: str = ""
    description: str = ""
    needs_admin: bool = False

    @property
    def display_name(self) -> str:
        # A descrição do executável é o nome que o Gerenciador de Tarefas mostra, exceto
        # para hospedeiros genéricos (python, rundll32, cmd...), em que o nome da entrada diz mais.
        if self.description and self.description.lower() not in GENERIC_HOSTS:
            return self.description
        return self.name


def _approved_state(hive: int, sub: str, name: str) -> bool:
    try:
        with winreg.OpenKey(hive, f"{APPROVED}\\{sub}") as k:
            data, _t = winreg.QueryValueEx(k, name)
            # 1º byte par (02/06) = ativado; ímpar (03/07) = desativado pelo usuário.
            return not (data and data[0] & 1)
    except FileNotFoundError:
        return True
    except OSError:
        return True


def _resolve_lnk(path: str) -> tuple[str, str]:
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        sc = win32com.client.Dispatch("WScript.Shell").CreateShortcut(path)
        return sc.TargetPath or "", sc.Arguments or ""
    except Exception:
        return "", ""


def _fill_exe_info(item: StartupItem) -> None:
    exe = item.exe
    if not exe:
        exe, _args = split_command(item.command)
    exe = os.path.expandvars(exe)
    if exe and not os.path.isabs(exe):
        found = _which(exe)
        exe = found or exe
    item.exe = exe
    info = version_info(exe) if exe else {}
    item.publisher = info.get("company", "")
    item.description = info.get("description", "") if len(info.get("description", "")) > 2 else ""


def _which(name: str) -> str:
    for d in [os.environ.get("WINDIR", r"C:\Windows") + r"\System32", os.environ.get("WINDIR", r"C:\Windows")]:
        p = Path(d) / name
        if p.is_file():
            return str(p)
    return ""


def list_startup() -> list[StartupItem]:
    items: list[StartupItem] = []

    for hive, path, sub, label in RUN_SOURCES:
        try:
            with winreg.OpenKey(hive, path) as k:
                i = 0
                while True:
                    try:
                        name, value, _t = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if not isinstance(value, str) or not value.strip():
                        continue
                    items.append(StartupItem(name=name, command=value, source=label, kind="run", hive=hive,
                                             approved_path=f"{APPROVED}\\{sub}", approved_name=name,
                                             enabled=_approved_state(hive, sub, name), needs_admin=hive == HKLM))
        except OSError:
            continue

    folders = [
        (HKCU, Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup",
         "Pasta Inicializar (usuário)"),
        (HKLM, Path(os.environ.get("PROGRAMDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\StartUp",
         "Pasta Inicializar (todos os usuários)"),
    ]
    for hive, folder, label in folders:
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for f in entries:
            if f.name.lower() == "desktop.ini" or f.is_dir():
                continue
            target, args = _resolve_lnk(str(f)) if f.suffix.lower() == ".lnk" else (str(f), "")
            items.append(StartupItem(name=f.stem, command=f'"{target or f}" {args}'.strip(), source=label,
                                     kind="folder", hive=hive, approved_path=f"{APPROVED}\\StartupFolder",
                                     approved_name=f.name, enabled=_approved_state(hive, "StartupFolder", f.name),
                                     exe=target, needs_admin=hive == HKLM))

    # Apps da Store com StartupTask (ex.: Teams, Spotify da Store)
    try:
        with winreg.OpenKey(HKCU, APPMODEL) as root:
            i = 0
            while True:
                try:
                    family = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, family) as fk:
                        j = 0
                        while True:
                            try:
                                task = winreg.EnumKey(fk, j)
                            except OSError:
                                break
                            j += 1
                            try:
                                with winreg.OpenKey(fk, task) as tk:
                                    state = winreg.QueryValueEx(tk, "State")[0]
                            except OSError:
                                continue
                            # 0/1 = desativado, 2 = ativado, 3/4 = definido por política
                            pretty = family.split("_")[0].split(".")[-1]
                            items.append(StartupItem(name=pretty, command=f"{family} ({task})",
                                                     source="Microsoft Store", kind="store", hive=HKCU,
                                                     approved_path=f"{APPMODEL}\\{family}\\{task}",
                                                     approved_name="State", enabled=state in (2, 4),
                                                     description=pretty))
                except OSError:
                    continue
    except OSError:
        pass

    for it in items:
        if it.kind != "store":
            _fill_exe_info(it)
    return items


def set_enabled(item: StartupItem, enabled: bool) -> int:
    """Ativa/desativa com backup. Retorna o id do backup (para desfazer).

    Lança PermissionError quando o item é de todos os usuários e o app não é administrador.
    """
    reason = f"startup:{'ativar' if enabled else 'desativar'} {item.display_name}"
    if item.kind == "store":
        bid = regbackup.set_value(item.hive, item.approved_path, "State", winreg.REG_DWORD,
                                  2 if enabled else 1, reason)
    else:
        if enabled:
            data = struct.pack("<I", 2) + b"\x00" * 8
        else:
            # 03 + FILETIME do momento em que foi desativado (mesmo formato do Gerenciador de Tarefas)
            ft = int((time.time() + 11644473600) * 1e7)
            data = struct.pack("<IQ", 3, ft)
        bid = regbackup.set_value(item.hive, item.approved_path, item.approved_name, winreg.REG_BINARY,
                                  data, reason)
    item.enabled = enabled
    log_operation("startup.set", f"{item.display_name} → {'ativado' if enabled else 'desativado'} ({item.source})")
    return bid
