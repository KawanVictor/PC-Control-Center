"""Atalhos de teclado globais (funcionam em qualquer programa), via RegisterHotKey do Windows.

Se a combinação já pertence a outro programa, o Windows recusa e o app avisa — nenhum
atalho de outro programa é "roubado". Os atalhos ficam em settings: ``hotkeys.bindings``
({ação: "Ctrl+Alt+W"}).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget

from ..core.config import Settings
from ..core.logger import get_logger, log_operation

log = get_logger("hotkeys")

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

BASE_ACTIONS = {
    "open_app": "Abrir o PC Control Center",
    "toggle_widgets": "Mostrar/ocultar widgets",
    "scene_off": "Voltar ao normal (desativar cenário)",
    "mute": "Som: mudo / ativar",
    "vol_up": "Som: aumentar volume",
    "vol_down": "Som: diminuir volume",
    "media_play": "Música: tocar / pausar",
    "media_next": "Música: próxima",
    "media_prev": "Música: anterior",
    "livewall": "Papel de parede animado: ligar/desligar",
    "fps": "Contador de FPS: ligar/desligar",
    "obs_record": "OBS: iniciar/parar gravação",
    "warm": "Luz quente: ligar/desligar",
}

DEFAULTS = {"toggle_widgets": "Ctrl+Alt+W", "open_app": "Ctrl+Alt+P", "scene:game": "Ctrl+Alt+J",
            "scene_off": "Ctrl+Alt+N"}


def actions() -> dict[str, str]:
    from . import scenes
    out = dict(BASE_ACTIONS)
    for sc in scenes.scenes():
        out[f"scene:{sc['id']}"] = f"Ativar cenário “{sc['name']}”"
    return out


def bindings() -> dict[str, str]:
    b = Settings.instance().get("hotkeys.bindings")
    return dict(DEFAULTS) if not isinstance(b, dict) else dict(b)


# --------------------------------------------------------- texto → (mods, vk)
_VK_NAMED = {
    "Space": 0x20, "PgUp": 0x21, "PgDown": 0x22, "End": 0x23, "Home": 0x24, "Left": 0x25, "Up": 0x26,
    "Right": 0x27, "Down": 0x28, "Ins": 0x2D, "Insert": 0x2D, "Del": 0x2E, "Delete": 0x2E, "Pause": 0x13,
    "Print": 0x2C, "ScrollLock": 0x91, "Backspace": 0x08, "Tab": 0x09, "Return": 0x0D, "Enter": 0x0D,
    "Esc": 0x1B, "-": 0xBD, "=": 0xBB, ",": 0xBC, ".": 0xBE, ";": 0xBA, "/": 0xBF, "'": 0xDE, "[": 0xDB,
    "]": 0xDD, "\\": 0xDC, "`": 0xC0,
}


def parse(text: str) -> tuple[int, int]:
    """'Ctrl+Alt+W' → (modificadores, código virtual). Levanta ValueError se inválido."""
    if not text:
        raise ValueError("vazio")
    parts = [p.strip() for p in text.replace(" ", "").split("+") if p.strip()] if text != "+" else []
    if not parts:
        raise ValueError("vazio")
    mods, key = 0, parts[-1]
    for m in parts[:-1]:
        ml = m.lower()
        if ml in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif ml == "alt":
            mods |= MOD_ALT
        elif ml == "shift":
            mods |= MOD_SHIFT
        elif ml in ("meta", "win"):
            mods |= MOD_WIN
        else:
            raise ValueError(f"modificador desconhecido: {m}")
    if len(key) == 1 and key.upper().isalnum():
        vk = ord(key.upper())
    elif key.upper().startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    elif key in _VK_NAMED:
        vk = _VK_NAMED[key]
    else:
        raise ValueError(f"tecla não suportada: {key}")
    is_fkey = 0x70 <= vk <= 0x87
    if not mods and not is_fkey:
        raise ValueError("Use pelo menos Ctrl, Alt, Shift ou Win (ou uma tecla F1–F24).")
    return mods, vk


def normalize(seq: QKeySequence | str) -> str:
    text = seq.toString(QKeySequence.SequenceFormat.PortableText) if isinstance(seq, QKeySequence) else str(seq)
    return text.split(",")[0].strip()


# ---------------------------------------------------------------- gerente
class _Receiver(QWidget):
    """Janela invisível que recebe WM_HOTKEY (funciona mesmo com diálogos abertos)."""

    def __init__(self, on_hotkey) -> None:
        super().__init__()
        self._on = on_hotkey
        self.winId()

    def nativeEvent(self, event_type, message):
        if event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self._on(int(msg.wParam))
                return True, 0
        return False, 0


class HotkeyManager(QObject):
    triggered = Signal(str)        # ação
    _instance: "HotkeyManager | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._recv: _Receiver | None = None
        self._ids: dict[int, str] = {}
        self.errors: dict[str, str] = {}      # ação → motivo (ex.: em uso por outro programa)

    @classmethod
    def instance(cls) -> "HotkeyManager":
        if cls._instance is None:
            cls._instance = HotkeyManager()
        return cls._instance

    def _hwnd(self) -> int:
        if self._recv is None:
            self._recv = _Receiver(self._fire)
        return int(self._recv.winId())

    def _fire(self, hid: int) -> None:
        action = self._ids.get(hid)
        if action:
            log.info("Atalho: %s", action)
            self.triggered.emit(action)

    def unregister_all(self) -> None:
        if self._recv is None:
            return
        for hid in list(self._ids):
            ctypes.windll.user32.UnregisterHotKey(self._hwnd(), hid)
        self._ids.clear()

    def apply(self) -> dict[str, str]:
        """(Re)registra todos os atalhos. Retorna {ação: erro} dos que falharam."""
        self.unregister_all()
        self.errors = {}
        if not Settings.instance().get("hotkeys.enabled", True):
            return self.errors
        hwnd = self._hwnd()
        valid = actions()
        for i, (action, text) in enumerate(sorted(bindings().items()), start=1):
            if not text or action not in valid:
                continue
            try:
                mods, vk = parse(text)
            except ValueError as e:
                self.errors[action] = str(e)
                continue
            if ctypes.windll.user32.RegisterHotKey(hwnd, i, mods | MOD_NOREPEAT, vk):
                self._ids[i] = action
            else:
                self.errors[action] = f"{text} já está em uso por outro programa"
        if self.errors:
            log.info("Atalhos não registrados: %s", self.errors)
        return self.errors

    def set_binding(self, action: str, text: str) -> str:
        """Define (ou remove, com texto vazio) um atalho. Retorna erro ou ''."""
        b = bindings()
        text = normalize(text) if text else ""
        if text:
            parse(text)                              # valida (ValueError)
            for other, t in b.items():
                if other != action and t.lower() == text.lower():
                    raise ValueError(f"{text} já está sendo usado em “{actions().get(other, other)}”.")
            b[action] = text
        else:
            b.pop(action, None)
        Settings.instance().set("hotkeys.bindings", b)
        log_operation("hotkeys.set", f"{action} = {text or '(nenhum)'}")
        return self.apply().get(action, "")
