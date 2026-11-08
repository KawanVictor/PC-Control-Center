"""Tema automático: claro de dia, escuro à noite (pelo sol do seu local ou por horário fixo).

Troca o modo do Windows (apps e/ou barra de tarefas) e, se quiser, o tema do próprio PC
Control Center. Só age nas TRANSIÇÕES (ao amanhecer/anoitecer, ou quando liga a função):
se você mudar o modo manualmente no meio do dia, ele respeita até a próxima transição.

Ao ligar, o estado original é registrado no Histórico de personalização — desfazer volta
ao modo que estava antes. As gravações no Registro usam o backup de sempre (regbackup).
"""
from __future__ import annotations

import winreg
from datetime import datetime, time as dtime

from PySide6.QtCore import QObject, QTimer, Signal

from ..core import regbackup
from ..core.config import Settings
from ..core.logger import get_logger, log_operation
from . import changes, sun
from .tweaks import PERSONALIZE

log = get_logger("autotheme")
HKCU = winreg.HKEY_CURRENT_USER


def _parse(hhmm: str | None, default: str) -> dtime:
    try:
        h, m = (int(x) for x in (hhmm or default).split(":"))
        return dtime(h, m)
    except ValueError:
        h, m = (int(x) for x in default.split(":"))
        return dtime(h, m)


def desired_light(now: datetime | None = None, cfg: dict | None = None) -> bool:
    now = now or datetime.now()
    cfg = cfg or Settings.instance().get("autotheme", {}) or {}
    if cfg.get("mode", "sun") == "sun":
        return sun.is_daytime(now)
    light_at, dark_at = _parse(cfg.get("light_at"), "07:00"), _parse(cfg.get("dark_at"), "19:00")
    t = now.time()
    if light_at <= dark_at:
        return light_at <= t < dark_at
    return t >= light_at or t < dark_at


def windows_light() -> tuple[int, int]:
    """(AppsUseLightTheme, SystemUsesLightTheme)."""
    return (int(regbackup.read_value(HKCU, PERSONALIZE, "AppsUseLightTheme", 1)),
            int(regbackup.read_value(HKCU, PERSONALIZE, "SystemUsesLightTheme", 0)))


def apply(light: bool, cfg: dict | None = None, reason: str = "autotheme") -> None:
    cfg = cfg or Settings.instance().get("autotheme", {}) or {}
    v = 1 if light else 0
    group = regbackup.new_group()
    if cfg.get("apps", True):
        regbackup.set_value(HKCU, PERSONALIZE, "AppsUseLightTheme", winreg.REG_DWORD, v, reason, group)
    if cfg.get("system", True):
        regbackup.set_value(HKCU, PERSONALIZE, "SystemUsesLightTheme", winreg.REG_DWORD, v, reason, group)
    changes.broadcast("ImmersiveColorSet")
    if cfg.get("app_theme", True):
        Settings.instance().set("appearance.mode", "light" if light else "dark")
    log_operation("autotheme.apply", "claro" if light else "escuro")


class AutoTheme(QObject):
    switched = Signal(bool)          # True = claro
    _instance: "AutoTheme | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._last: bool | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)

    @classmethod
    def instance(cls) -> "AutoTheme":
        if cls._instance is None:
            cls._instance = AutoTheme()
        return cls._instance

    def start(self) -> None:
        """Liga o relógio (também usado pela luz quente automática)."""
        self._last = None
        self._timer.start(60_000)
        self.tick()

    def stop(self) -> None:
        # o relógio continua se a luz quente automática estiver ligada
        self._last = None
        if not Settings.instance().get("display.warm_auto"):
            self._timer.stop()

    def warm_tick(self, force: bool = False) -> None:
        """Luz quente automática: liga ao anoitecer e desliga ao amanhecer (só nas transições)."""
        s = Settings.instance()
        from .display import WarmFilter
        wf = WarmFilter.instance()
        if not s.get("display.warm_auto"):
            if force and wf.level:
                wf.set_level(0)
            self._warm_last = None
            return
        if not self._timer.isActive():
            self._timer.start(60_000)
        night = not sun.is_daytime()
        if force or night != getattr(self, "_warm_last", None):
            self._warm_last = night
            try:
                wf.set_level(int(s.get("display.warm_level", 50)) if night else 0)
            except OSError as e:
                log.warning("Luz quente: %s", e)

    def enable(self, on: bool) -> None:
        s = Settings.instance()
        if on and not s.get("autotheme.enabled"):
            apps, system = windows_light()
            changes.record("autotheme", "Tema automático ligado (modo anterior registrado)",
                           apps=apps, system=system, app_mode=s.get("appearance.mode"))
        s.set("autotheme.enabled", on)
        if on:
            self.start()
        else:
            self.stop()

    def boot(self) -> None:
        """Na abertura do app: liga o relógio se o tema ou a luz quente automáticos estiverem ativos."""
        s = Settings.instance()
        if s.get("autotheme.enabled") or s.get("display.warm_auto"):
            self.start()

    def tick(self) -> None:
        s = Settings.instance()
        self.warm_tick()
        if not s.get("autotheme.enabled"):
            return
        want = desired_light()
        if want != self._last:          # só nas transições
            self._last = want
            try:
                apply(want)
                self.switched.emit(want)
            except Exception as e:     # noqa: BLE001
                log.warning("Tema automático: %s", e)

    @staticmethod
    def next_change(now: datetime | None = None) -> tuple[str, datetime | None]:
        """('claro'|'escuro', horário) da próxima troca (para mostrar na interface)."""
        now = now or datetime.now()
        cfg = Settings.instance().get("autotheme", {}) or {}
        if cfg.get("mode", "sun") == "sun":
            loc = sun.location()
            from datetime import timedelta
            for d in (0, 1):
                day = (now + timedelta(days=d)).date()
                rise, set_ = sun.sun_times(float(loc["lat"]), float(loc["lon"]), day)
                for t, kind in ((rise, "claro"), (set_, "escuro")):
                    if t and t > now:
                        return kind, t
            return "", None
        from datetime import timedelta
        cands = []
        for key, kind, default in (("light_at", "claro", "07:00"), ("dark_at", "escuro", "19:00")):
            hm = _parse(cfg.get(key), default)
            dt = now.replace(hour=hm.hour, minute=hm.minute, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=1)
            cands.append((dt, kind))
        dt, kind = min(cands)
        return kind, dt
