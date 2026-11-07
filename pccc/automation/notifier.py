"""Notificações do Windows com regras de cortesia.

Um alerta SEMPRE vai para a Central de alertas do app. O balão do Windows só aparece se:
* as notificações estão ligadas;
* não está em "silenciar por 1 hora";
* fora do horário de silêncio configurado;
* o Windows aceita notificações agora — jogo/vídeo em tela cheia, apresentação ou
  "Não incomodar" ligados bloqueiam (SHQueryUserNotificationState).
Alertas críticos (ex.: temperatura perigosa) ignoram as três últimas regras.
"""
from __future__ import annotations

import ctypes
import time
from datetime import datetime
from typing import Callable

from ..core.config import Settings
from ..core.logger import get_logger
from .store import Alert

log = get_logger("notifier")

QUNS = {1: "sem usuário", 2: "ocupado (tela cheia)", 3: "jogo em tela cheia (Direct3D)", 4: "modo apresentação",
        5: "aceita notificações", 6: "horário de silêncio do Windows", 7: "app da Store em tela cheia"}
_BLOCKING = {1, 2, 3, 4, 6, 7}


def windows_focus_state() -> int:
    state = ctypes.c_int(5)
    try:
        ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    except Exception:
        return 5
    return state.value


def _in_quiet_hours(start: str, end: str, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    try:
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
    except ValueError:
        return False
    cur = now.hour * 60 + now.minute
    s, e = sh * 60 + sm, eh * 60 + em
    return s <= cur < e if s <= e else (cur >= s or cur < e)   # atravessa a meia-noite


class Notifier:
    _instance: "Notifier | None" = None

    def __init__(self) -> None:
        self.sink: Callable[[str, str, str], None] | None = None   # definido pela janela (bandeja)
        self.snoozed_until = 0.0
        self.focus_state = windows_focus_state

    @classmethod
    def instance(cls) -> "Notifier":
        if cls._instance is None:
            cls._instance = Notifier()
        return cls._instance

    def snooze(self, minutes: int = 60) -> None:
        self.snoozed_until = time.time() + minutes * 60

    def blocked_reason(self, alert: Alert) -> str:
        """Motivo para NÃO mostrar o balão (vazio = pode mostrar)."""
        s = Settings.instance()
        if not s.get("notifications.enabled", True):
            return "notificações desligadas"
        if alert.severity == "critical":
            return ""
        if time.time() < self.snoozed_until:
            return "silenciado temporariamente"
        if s.get("notifications.silenced_by_scene", ""):
            return f"cenário {s.get('notifications.silenced_by_scene')}"
        if s.get("notifications.quiet_hours", False) and _in_quiet_hours(
                s.get("notifications.quiet_start", "22:00"), s.get("notifications.quiet_end", "07:00")):
            return "horário de silêncio"
        if s.get("notifications.respect_focus", True):
            st = self.focus_state()
            if st in _BLOCKING:
                return QUNS.get(st, "Windows ocupado")
        return ""

    def notify(self, alert: Alert) -> bool:
        reason = self.blocked_reason(alert)
        if reason:
            log.info("Alerta registrado sem balão (%s): %s", reason, alert.title)
            return False
        if self.sink is None:
            return False
        try:
            self.sink(alert.title, alert.message, alert.severity)
            return True
        except Exception:
            log.exception("Falha ao exibir notificação")
            return False
