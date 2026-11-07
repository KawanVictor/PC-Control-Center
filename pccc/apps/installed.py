"""Inventário de programas instalados e desinstalação pelos mecanismos oficiais.

Fontes (as mesmas de Configurações → Aplicativos instalados):
* HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall          (64 bits)
* HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall (32 bits)
* HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall          (por usuário)
* Get-AppxPackage                                                        (Microsoft Store)

A desinstalação SEMPRE usa o desinstalador do próprio programa (UninstallString), o
MsiExec /X para pacotes MSI ou Remove-AppxPackage para apps da Store. Nenhum arquivo ou
chave de registro é apagado diretamente por este app.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import time
import winreg
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..core.logger import get_logger
from ..core.safety import ps_quote
from ..core.winapi import run_hidden

log = get_logger("installed")

UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "Máquina (64 bits)"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
     "Máquina (32 bits)"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "Usuário atual"),
]

# Categorias por palavras-chave (nome/fabricante/pasta). A primeira que bater vence.
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Jogos", ("steam", "epic games", "riot", "valorant", "league of legends", "battle.net", "blizzard",
               "ubisoft", "ea app", "electronic arts", "origin", "gog galaxy", "rockstar", "xbox", "minecraft",
               "roblox", "teamfight", "\\games\\", "steamapps", "garena", "hoyoverse", "mihoyo")),
    ("Navegadores", ("chrome", "firefox", "edge", "opera", "brave", "vivaldi", "browser")),
    ("Desenvolvimento", ("python", "visual studio", "vs code", "git", "node.js", "java", "jdk", "docker",
                         "sdk", "android studio", "jetbrains", "pycharm", "intellij", "cmake", "wsl", "postman",
                         "anaconda", ".net", "powershell")),
    ("Drivers e hardware", ("driver", "amd ", "radeon", "nvidia", "intel", "realtek", "asus", "armoury",
                            "lenovo", "dell", "hp ", "logitech", "razer", "corsair", "msi ", "chipset",
                            "bluetooth", "synaptics", "elan", "dolby", "thunderbolt")),
    ("Comunicação", ("discord", "whatsapp", "telegram", "teams", "zoom", "skype", "slack", "outlook", "thunderbird")),
    ("Multimídia", ("spotify", "vlc", "obs", "audacity", "media", "player", "photoshop", "adobe", "gimp", "krita",
                    "davinci", "premiere", "capcut", "netflix", "codec", "k-lite")),
    ("Produtividade", ("office", "word", "excel", "powerpoint", "onenote", "libreoffice", "notion", "pdf",
                       "acrobat", "7-zip", "winrar", "notepad++", "onedrive", "dropbox", "google drive")),
    ("Segurança", ("antivirus", "defender", "avast", "avg", "kaspersky", "norton", "mcafee", "malwarebytes",
                   "eset", "bitdefender", "vpn")),
    ("Runtimes e componentes", ("redistributable", "runtime", "visual c++", "directx", "webview2",
                                "framework", "vcredist", "update for", "hotfix")),
]

# Componentes dos quais outros programas costumam depender: exigem aviso extra.
SHARED_COMPONENTS = ("visual c++", "redistributable", "runtime", ".net", "directx", "webview2", "driver",
                     "chipset", "framework")


@dataclass
class InstalledApp:
    name: str
    version: str = ""
    publisher: str = ""
    size: int = 0                    # bytes (0 = desconhecido)
    install_date: float | None = None
    location: str = ""
    icon_path: str = ""
    uninstall_cmd: str = ""
    quiet_uninstall_cmd: str = ""
    modify_path: str = ""
    source: str = ""                 # Máquina (64 bits) / Usuário atual / Microsoft Store
    category: str = "Outros"
    system_component: bool = False
    is_store: bool = False
    is_msi: bool = False
    key: str = ""                    # caminho da chave no registro ou PackageFullName
    hive: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def can_uninstall(self) -> bool:
        return bool(self.uninstall_cmd) or self.is_store

    @property
    def is_shared_component(self) -> bool:
        low = self.name.lower()
        return any(k in low for k in SHARED_COMPONENTS)

    def best_location(self) -> str:
        """Pasta do programa: InstallLocation, ou a pasta do ícone / desinstalador."""
        for cand in (self.location, _exe_from_cmd(self.icon_path), _exe_from_cmd(self.uninstall_cmd)):
            if not cand:
                continue
            p = Path(cand.strip().strip('"'))
            if p.is_file():
                p = p.parent
            if p.is_dir() and p.name.lower() not in ("system32", "syswow64", "windows"):
                return str(p)
        return ""


def categorize(name: str, publisher: str, location: str) -> str:
    hay = f" {name} | {publisher} | {location} ".lower()
    for cat, keys in CATEGORY_RULES:
        if any(k in hay for k in keys):
            return cat
    if "microsoft" in publisher.lower():
        return "Microsoft"
    return "Outros"


def _exe_from_cmd(cmd: str) -> str:
    """Extrai o executável de um comando ('"C:\\x\\a.exe" /S' → C:\\x\\a.exe; ícones 'a.exe,0')."""
    if not cmd:
        return ""
    cmd = cmd.strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        return cmd[1:end] if end > 0 else cmd.strip('"')
    m = re.match(r"(.+?\.(exe|ico|dll|msi|cmd|bat))\b", cmd, re.I)
    if m:
        return m.group(1)
    return cmd.split(",")[0]


def split_command(cmd: str) -> tuple[str, str]:
    """Separa executável e argumentos de um UninstallString."""
    cmd = os.path.expandvars(cmd.strip())
    exe = _exe_from_cmd(cmd)
    if cmd.startswith('"'):
        rest = cmd[len(exe) + 2:]
    else:
        rest = cmd[len(exe):]
    return exe, rest.strip()


def msi_uninstall_args(cmd: str, key_name: str) -> tuple[str, str] | None:
    """Para MSI, troca /I (reparar/modificar) por /X (desinstalar) com o GUID do produto."""
    m = re.search(r"\{[0-9A-F-]{36}\}", cmd, re.I) or re.search(r"\{[0-9A-F-]{36}\}", key_name, re.I)
    if "msiexec" in cmd.lower() and m:
        return "msiexec.exe", f"/X{m.group(0)}"
    return None


def _q(key, name, default=None):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return default


def _parse_date(raw, key_handle) -> float | None:
    if isinstance(raw, str) and re.fullmatch(r"\d{8}", raw.strip()):
        try:
            return datetime.strptime(raw.strip(), "%Y%m%d").timestamp()
        except ValueError:
            pass
    # Sem InstallDate: usa a data da última gravação da chave (bom indicador).
    try:
        ft = winreg.QueryInfoKey(key_handle)[2]   # unidades de 100 ns desde 1601
        return ft / 1e7 - 11644473600
    except OSError:
        return None


def read_registry_apps() -> list[InstalledApp]:
    apps: list[InstalledApp] = []
    for hive, path, source in UNINSTALL_KEYS:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        name = _q(k, "DisplayName")
                        if not name or not str(name).strip():
                            continue
                        # Atualizações do Windows e entradas "filhas" não são programas.
                        if _q(k, "ParentKeyName") or _q(k, "ReleaseType") in ("Update", "Hotfix",
                                                                             "Security Update"):
                            continue
                        uninstall = _q(k, "UninstallString", "") or ""
                        size_kb = _q(k, "EstimatedSize", 0) or 0
                        publisher = (_q(k, "Publisher", "") or "").strip()
                        location = (_q(k, "InstallLocation", "") or "").strip().strip('"')
                        app = InstalledApp(
                            name=str(name).strip(),
                            version=str(_q(k, "DisplayVersion", "") or ""),
                            publisher=publisher,
                            size=int(size_kb) * 1024 if isinstance(size_kb, int) else 0,
                            install_date=_parse_date(_q(k, "InstallDate"), k),
                            location=location,
                            icon_path=os.path.expandvars((_q(k, "DisplayIcon", "") or "").strip()),
                            uninstall_cmd=uninstall,
                            quiet_uninstall_cmd=_q(k, "QuietUninstallString", "") or "",
                            modify_path=_q(k, "ModifyPath", "") or "",
                            source=source,
                            system_component=_q(k, "SystemComponent", 0) == 1,
                            is_msi=_q(k, "WindowsInstaller", 0) == 1 or "msiexec" in uninstall.lower(),
                            key=f"{path}\\{sub}",
                            hive=hive,
                        )
                        app.category = categorize(app.name, publisher, location)
                        apps.append(app)
                except OSError:
                    continue
    # O mesmo programa pode aparecer em mais de uma chave (ex.: 32 e 64 bits): deduplica.
    seen: dict[tuple, InstalledApp] = {}
    for a in apps:
        k = (a.name.lower(), a.version)
        if k not in seen or (not seen[k].uninstall_cmd and a.uninstall_cmd):
            seen[k] = a
    return list(seen.values())


_APPX_PS = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$names = @{}
try { Get-StartApps | ForEach-Object { $f = ($_.AppID -split '!')[0]; if (-not $names.ContainsKey($f)) { $names[$f] = $_.Name } } } catch {}
Get-AppxPackage -PackageTypeFilter Main | Where-Object { -not $_.IsFramework -and -not $_.NonRemovable -and $_.SignatureKind -ne 'System' } | ForEach-Object {
  [pscustomobject]@{ n = $_.Name; f = $_.PackageFullName; fam = $_.PackageFamilyName; v = $_.Version.ToString();
    p = $_.Publisher; l = $_.InstallLocation; d = $names[$_.PackageFamilyName]; s = [string]$_.SignatureKind }
} | ConvertTo-Json -Compress
"""


def _pretty_package_name(n: str) -> str:
    # "Microsoft.MicrosoftEdge.Stable" → "Microsoft Edge Stable"; "B9ECED6F.ASUSGIFTBOX" → "ASUSGIFTBOX"
    parts = n.split(".")
    if len(parts) > 1:
        parts = parts[1:]
    text = " ".join(parts)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text).strip() or n


def _manifest_names(location: str) -> tuple[str, str]:
    """(DisplayName, PublisherDisplayName) do AppxManifest.xml, ignorando 'ms-resource:'."""
    try:
        text = (Path(location) / "AppxManifest.xml").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "", ""
    props = re.search(r"<Properties>(.*?)</Properties>", text, re.S)
    block = props.group(1) if props else text

    def tag(name):
        m = re.search(rf"<{name}>\s*([^<]+?)\s*</{name}>", block)
        v = m.group(1) if m else ""
        return "" if v.startswith("ms-resource:") else v

    return tag("DisplayName"), tag("PublisherDisplayName")


def read_store_apps() -> list[InstalledApp]:
    try:
        out = run_hidden(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-Command", _APPX_PS], timeout=60)
        data = json.loads(out) if out.strip() else []
    except Exception as e:
        log.warning("Não foi possível listar apps da Store: %s", e)
        return []
    if isinstance(data, dict):
        data = [data]
    apps = []
    for d in data:
        loc = d.get("l") or ""
        try:
            ts = os.path.getctime(loc) if loc else None
        except OSError:
            ts = None
        man_name, man_pub = _manifest_names(loc) if loc else ("", "")
        pub = d.get("p") or ""
        m = re.search(r"CN=([^,]+)", pub)
        cn = m.group(1).strip() if m else pub
        # CN costuma ser um GUID em apps de terceiros; prefere o nome do manifesto.
        publisher = man_pub or cn
        name = d.get("d") or man_name or _pretty_package_name(d.get("n", ""))
        app = InstalledApp(name=name, version=d.get("v", ""), publisher=publisher, install_date=ts,
                           location=loc, source="Microsoft Store", is_store=True, key=d.get("f", ""),
                           extra={"family": d.get("fam", ""), "package": d.get("n", "")})
        app.category = categorize(name, publisher, loc)
        apps.append(app)
    return apps


def list_installed(include_store: bool = True) -> list[InstalledApp]:
    t = time.perf_counter()
    apps = read_registry_apps()
    if include_store:
        apps += read_store_apps()
    log.info("Inventário: %d programas em %.1f s", len(apps), time.perf_counter() - t)
    return sorted(apps, key=lambda a: a.name.lower())


def still_installed(app: InstalledApp) -> bool:
    """Confere se o programa ainda consta como instalado (após o desinstalador terminar)."""
    if app.is_store:
        try:
            pkg = ps_quote(app.extra.get("package", ""))
            out = run_hidden(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                              f"(Get-AppxPackage -Name {pkg} | Measure-Object).Count"], timeout=30)
            return out.strip() not in ("", "0")
        except Exception:
            return True
    try:
        winreg.OpenKey(app.hive, app.key).Close()
        return True
    except OSError:
        return False


def store_uninstall_command(package_full_name: str) -> str:
    """Comando PowerShell oficial para remover um app da Store (nome validado e escapado)."""
    if not re.fullmatch(r"[\w.\-~]+", package_full_name or ""):
        raise ValueError("Nome de pacote inválido")
    return f"Remove-AppxPackage -Package {ps_quote(package_full_name)}"


def uninstall_plan(app: InstalledApp) -> tuple[str, str, str]:
    """Retorna (programa, argumentos, descrição legível) do comando de desinstalação oficial."""
    if app.is_store:
        pkg = app.key
        if not re.fullmatch(r"[\w.\-~]+", pkg):
            raise ValueError("Nome de pacote inválido")
        return ("powershell.exe", f"-NoProfile -NonInteractive -Command {store_uninstall_command(pkg)}",
                f"Remove-AppxPackage -Package {pkg}")
    if not app.uninstall_cmd:
        raise ValueError("Este programa não informa um desinstalador.")
    msi = msi_uninstall_args(app.uninstall_cmd, app.key) if app.is_msi else None
    if msi:
        exe, args = msi
    else:
        exe, args = split_command(app.uninstall_cmd)
    return exe, args, f"{exe} {args}".strip()


__all__ = ["InstalledApp", "list_installed", "uninstall_plan", "still_installed", "split_command", "shlex"]
