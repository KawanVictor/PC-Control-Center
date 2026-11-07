"""Ajustes de personalização baseados em Registro / APIs do Windows.

Cada ``Tweak`` descreve um valor do Registro e as opções possíveis. Aplicar = backup +
gravação + aviso ao Windows (WM_SETTINGCHANGE) + entrada no histórico (desfazível).
"""
from __future__ import annotations

import ctypes
import sys
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field

from ..core import regbackup
from ..core.winapi import is_admin
from . import changes

HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
ADVANCED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
DESKICONS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel"
CLASSIC_MENU = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}"
BUILD = sys.getwindowsversion().build


@dataclass
class Tweak:
    id: str
    section: str
    title: str
    description: str
    hive: int
    path: str
    name: str
    options: list[tuple] = field(default_factory=list)   # [(valor | None=padrão do Windows, rótulo)]
    default: object = None                               # valor assumido quando não existe
    vtype: int = winreg.REG_DWORD
    broadcast: str | None = None
    explorer_restart: bool = False
    refresh_desktop: bool = False
    admin: bool = False
    min_build: int = 0
    toggle: bool = False                                 # 2 opções → interruptor (opção[1] = ligado)

    @property
    def supported(self) -> bool:
        return BUILD >= self.min_build

    def current(self):
        v = regbackup.read_value(self.hive, self.path, self.name, None)
        return self.default if v is None else v

    def current_index(self) -> int:
        cur = self.current()
        for i, (v, _label) in enumerate(self.options):
            if v == cur or (v is None and cur == self.default):
                return i
        return -1

    def apply(self, value) -> int:
        """Aplica o valor (None = remove e volta ao padrão do Windows). Retorna o id no histórico."""
        if self.admin and not is_admin():
            raise PermissionError("Este ajuste exige executar como administrador.")
        group = regbackup.new_group()
        label = next((lbl for v, lbl in self.options if v == value), str(value))
        reason = f"personalize:{self.title} → {label}"
        if value is None:
            regbackup.delete_value(self.hive, self.path, self.name, reason, group)
        else:
            regbackup.set_value(self.hive, self.path, self.name, self.vtype, value, reason, group)
        if self.broadcast:
            changes.broadcast(self.broadcast)
        if self.refresh_desktop:
            changes.refresh_desktop()
        return changes.record("registry", f"{self.title}: {label}", group=group,
                              broadcast=[self.broadcast] if self.broadcast else [],
                              refresh_desktop=self.refresh_desktop, explorer_restart=self.explorer_restart)


def _toggle(off, on, off_label="Desligado", on_label="Ligado"):
    return [(off, off_label), (on, on_label)]


TWEAKS: list[Tweak] = [
    # ---------------------------------------------------------------- Aparência
    Tweak("apps_mode", "appearance", "Modo dos aplicativos", "Tema claro ou escuro para janelas e apps.",
          HKCU, PERSONALIZE, "AppsUseLightTheme", [(0, "Escuro"), (1, "Claro")], 1, broadcast="ImmersiveColorSet"),
    Tweak("system_mode", "appearance", "Modo do Windows", "Barra de tarefas, menu Iniciar e Central de ações.",
          HKCU, PERSONALIZE, "SystemUsesLightTheme", [(0, "Escuro"), (1, "Claro")], 0, broadcast="ImmersiveColorSet"),
    Tweak("transparency", "appearance", "Efeitos de transparência", "Fundo translúcido (Mica/Acrílico) em janelas "
          "e na barra de tarefas.", HKCU, PERSONALIZE, "EnableTransparency", _toggle(0, 1), 1,
          broadcast="ImmersiveColorSet", toggle=True),
    Tweak("accent_start", "appearance", "Cor de destaque no Iniciar e na barra de tarefas",
          "Disponível com o modo do Windows escuro.", HKCU, PERSONALIZE, "ColorPrevalence", _toggle(0, 1), 0,
          broadcast="ImmersiveColorSet", toggle=True),
    Tweak("accent_titlebar", "appearance", "Cor de destaque nas barras de título",
          "Barras de título e bordas das janelas usam a cor de destaque.", HKCU, r"Software\Microsoft\Windows\DWM",
          "ColorPrevalence", _toggle(0, 1), 0, broadcast="ImmersiveColorSet", toggle=True),
    # --------------------------------------------------------- Barra de tarefas
    Tweak("taskbar_align", "taskbar", "Alinhamento da barra de tarefas", "Ícones à esquerda (estilo clássico) "
          "ou centralizados.", HKCU, ADVANCED, "TaskbarAl", [(0, "Esquerda"), (1, "Centro")], 1,
          broadcast="TraySettings", min_build=22000),
    Tweak("search_mode", "taskbar", "Pesquisa na barra de tarefas", "Como o botão de pesquisa aparece.",
          HKCU, r"Software\Microsoft\Windows\CurrentVersion\Search", "SearchboxTaskbarMode",
          [(0, "Oculta"), (1, "Somente ícone"), (3, "Ícone e rótulo"), (2, "Caixa de pesquisa")], 2,
          broadcast="TraySettings"),
    Tweak("task_view", "taskbar", "Botão Visão de Tarefas", "Atalho para áreas de trabalho virtuais.",
          HKCU, ADVANCED, "ShowTaskViewButton", _toggle(0, 1), 1, broadcast="TraySettings", toggle=True),
    Tweak("widgets_button", "taskbar", "Botão Widgets do Windows", "Painel de notícias e clima da Microsoft. "
          "Em algumas versões o Windows bloqueia esta alteração por apps externos.",
          HKCU, ADVANCED, "TaskbarDa", _toggle(0, 1), 1, broadcast="TraySettings", toggle=True, min_build=22000),
    Tweak("clock_seconds", "taskbar", "Segundos no relógio da barra de tarefas", "Usa um pouco mais de energia.",
          HKCU, ADVANCED, "ShowSecondsInSystemClock", _toggle(0, 1), 0, broadcast="TraySettings", toggle=True,
          min_build=22621),
    Tweak("end_task", "taskbar", "“Finalizar tarefa” no botão direito da barra",
          "Permite fechar apps travados direto pela barra de tarefas.", HKCU,
          ADVANCED + r"\TaskbarDeveloperSettings", "TaskbarEndTask", _toggle(0, 1), 0, broadcast="TraySettings",
          toggle=True, min_build=22631),
    # ------------------------------------------------- Área de trabalho e Explorer
    Tweak("icon_pc", "desktop", "Este Computador", "", HKCU, DESKICONS, "{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
          _toggle(1, 0), 1, refresh_desktop=True, toggle=True),
    Tweak("icon_recycle", "desktop", "Lixeira", "", HKCU, DESKICONS, "{645FF040-5081-101B-9F08-00AA002F954E}",
          _toggle(1, 0), 0, refresh_desktop=True, toggle=True),
    Tweak("icon_user", "desktop", "Arquivos do usuário", "", HKCU, DESKICONS, "{59031a47-3f72-44a7-89c5-5595fe6b30ee}",
          _toggle(1, 0), 1, refresh_desktop=True, toggle=True),
    Tweak("icon_network", "desktop", "Rede", "", HKCU, DESKICONS, "{F02C1A0D-BE21-4350-88B0-7367FC96EF3C}",
          _toggle(1, 0), 1, refresh_desktop=True, toggle=True),
    Tweak("icon_control", "desktop", "Painel de Controle", "", HKCU, DESKICONS,
          "{5399E694-6CE5-4D6C-8FCE-1D8870FDCBA0}", _toggle(1, 0), 1, refresh_desktop=True, toggle=True),
    Tweak("file_ext", "explorer", "Mostrar extensões de arquivos", "Exibe “.exe”, “.pdf”, etc. — ajuda a "
          "identificar arquivos suspeitos.", HKCU, ADVANCED, "HideFileExt", _toggle(1, 0), 1,
          refresh_desktop=True, toggle=True),
    Tweak("hidden_files", "explorer", "Mostrar arquivos ocultos", "", HKCU, ADVANCED, "Hidden", _toggle(2, 1), 2,
          refresh_desktop=True, toggle=True),
    Tweak("launch_to", "explorer", "O Explorador de Arquivos abre em", "", HKCU, ADVANCED, "LaunchTo",
          [(None, "Início (padrão)"), (1, "Este Computador"), (3, "Downloads")], 2),
    Tweak("startup_delay", "system", "Remover atraso dos apps de inicialização",
          "Por padrão o Windows espera ~10 s antes de abrir os apps de inicialização.", HKCU,
          r"Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize", "StartupDelayInMSec",
          _toggle(None, 0), None, toggle=True),
    Tweak("fast_startup", "system", "Inicialização rápida",
          "Liga mais rápido após desligar, mas pode atrapalhar atualizações e dual boot. Exige administrador.",
          HKLM, r"SYSTEM\CurrentControlSet\Control\Session Manager\Power", "HiberbootEnabled", _toggle(0, 1), 1,
          admin=True, toggle=True),
]
TWEAK_BY_ID = {t.id: t for t in TWEAKS}


# ------------------------------------------------- menu de contexto clássico (Win11)
def classic_menu_enabled() -> bool:
    return regbackup.read_value(HKCU, CLASSIC_MENU + r"\InprocServer32", "", None) is not None


def set_classic_menu(enabled: bool) -> int:
    """Menu do botão direito completo (Windows 10) no Windows 11. Exige reiniciar o Explorer."""
    group = regbackup.new_group()
    path = CLASSIC_MENU + r"\InprocServer32"
    if enabled:
        regbackup.set_value(HKCU, path, "", winreg.REG_SZ, "", "personalize:menu clássico → ligado", group)
    else:
        regbackup.delete_value(HKCU, path, "", "personalize:menu clássico → desligado", group)
        regbackup._remove_if_empty(HKCU, path)
        regbackup._remove_if_empty(HKCU, CLASSIC_MENU)
    return changes.record("registry", f"Menu de contexto clássico: {'ligado' if enabled else 'desligado'}",
                          group=group, explorer_restart=True)


# ------------------------------------------------------ animações (SystemParametersInfo)
SPI_GETCLIENTAREAANIMATION, SPI_SETCLIENTAREAANIMATION = 0x1042, 0x1043
SPIF_UPDATEINIFILE, SPIF_SENDCHANGE = 0x01, 0x02


def get_animations() -> bool:
    v = wintypes.BOOL()
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(v), 0)
    return bool(v.value)


def set_spi(action: int, value: bool, record_change: bool = True) -> int | None:
    previous = get_animations() if action == SPI_SETCLIENTAREAANIMATION else None
    ctypes.windll.user32.SystemParametersInfoW(action, 0, ctypes.c_void_p(1 if value else 0),
                                               SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
    if record_change:
        return changes.record("spi", f"Efeitos de animação: {'ligados' if value else 'desligados'}",
                              action=action, previous=previous)
    return None


def set_animations(on: bool) -> int:
    return set_spi(SPI_SETCLIENTAREAANIMATION, on)


# ------------------------------------------- ocultar barra de tarefas (SHAppBarMessage)
class APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uCallbackMessage", wintypes.UINT),
                ("uEdge", wintypes.UINT), ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]


ABM_GETSTATE, ABM_SETSTATE, ABS_AUTOHIDE, ABS_ALWAYSONTOP = 0x4, 0xA, 0x1, 0x2


def _appbar(msg: int, lparam: int = 0) -> int:
    abd = APPBARDATA(cbSize=ctypes.sizeof(APPBARDATA))
    abd.hWnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
    abd.lParam = lparam
    shell32 = ctypes.WinDLL("shell32")
    shell32.SHAppBarMessage.restype = ctypes.c_size_t
    shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
    return shell32.SHAppBarMessage(msg, ctypes.byref(abd))


def taskbar_autohide() -> bool:
    return bool(_appbar(ABM_GETSTATE) & ABS_AUTOHIDE)


def set_taskbar_autohide(on: bool, record_change: bool = True) -> int | None:
    """Aplica na hora (mesma API das Configurações) — sem reiniciar o Explorer."""
    previous = taskbar_autohide()
    _appbar(ABM_SETSTATE, ABS_AUTOHIDE if on else ABS_ALWAYSONTOP)
    if record_change:
        return changes.record("appbar", f"Ocultar barra de tarefas automaticamente: {'sim' if on else 'não'}",
                              previous=previous)
    return None
