"""Motor de alertas: avalia cada leitura de sistema e de rede contra as regras.

Para cada condição guarda "desde quando está verdadeira". Dispara quando ela dura
``duration`` segundos e o último disparo da mesma condição foi há mais de ``cooldown``
minutos. Condições por item (cada aplicativo, cada unidade de disco) são independentes.
"""
from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.config import Settings
from ..core.logger import get_logger
from ..monitoring.models import ProcessEntry, Snapshot
from ..network.models import NetworkSnapshot
from ..ui.fmt import fmt_bytes
from . import store
from .notifier import Notifier
from .rules import CRITICAL_TEMP, Rule, load_rules
from .store import Alert
from .usage import UsageTracker

log = get_logger("alerts")


class AlertEngine(QObject):
    fired = Signal(object)           # Alert
    unread_changed = Signal(int)
    _instance: "AlertEngine | None" = None

    def __init__(self, clock: Callable[[], float] = time.time, notifier: Notifier | None = None) -> None:
        super().__init__()
        self.clock = clock
        self.notifier = notifier or Notifier.instance()
        self.rules: dict[str, Rule] = load_rules()
        self.usage = UsageTracker()
        self._since: dict[str, float] = {}
        self._last_fire: dict[str, float] = {}
        self._net_down_since: float | None = None
        self._net_alerted = False
        self._last_procs: list[ProcessEntry] | None = None
        Settings.instance().changed.connect(self._on_setting)
        store.prune()

    @classmethod
    def instance(cls) -> "AlertEngine":
        if cls._instance is None:
            cls._instance = AlertEngine()
        return cls._instance

    def connect_services(self) -> None:
        from ..monitoring.collector import MonitorService
        from ..network.monitor import NetworkService
        MonitorService.instance().snapshot.connect(self.on_system)
        NetworkService.instance().snapshot.connect(self.on_network)
        # relatório semanal automático (verifica uma vez por hora)
        self._weekly = QTimer(self)
        self._weekly.timeout.connect(self._maybe_weekly_report)
        self._weekly.start(3600_000)
        QTimer.singleShot(60_000, self._maybe_weekly_report)

    def _on_setting(self, key: str, _v) -> None:
        if key.startswith("alerts") or key == "*":
            self.rules = load_rules()

    # ------------------------------------------------------------------ núcleo
    def _check(self, key: str, rule: Rule, active: bool, make: Callable[..., Alert]) -> None:
        now = self.clock()
        if not rule.enabled or not active:
            self._since.pop(key, None)
            return
        start = self._since.setdefault(key, now)
        if now - start < rule.duration:
            return
        if now - self._last_fire.get(key, -1e12) < rule.cooldown * 60:
            return
        self._last_fire[key] = now
        self.fire(make())

    def fire(self, alert: Alert) -> Alert:
        alert.ts = self.clock()
        alert.notified = self.notifier.notify(alert)
        store.save_alert(alert)
        log.info("ALERTA [%s] %s — %s", alert.severity, alert.title, alert.message)
        self.fired.emit(alert)
        self.unread_changed.emit(store.unread_count())
        return alert

    # ---------------------------------------------------------------- sistema
    def on_system(self, s: Snapshot) -> None:
        try:
            self._eval_system(s)
            self.usage.on_snapshot(s, self.clock())
        except Exception:
            log.exception("Erro ao avaliar alertas")

    def _eval_system(self, s: Snapshot) -> None:
        r = self.rules
        cpu = s.cpu.percent
        self._check("cpu", r["cpu"], cpu >= r["cpu"].threshold, lambda: Alert(
            "cpu", "warning", "Uso de CPU elevado",
            f"O processador está em {cpu:.0f}% há mais de {_dur(r['cpu'].duration)}."
            + _top(s, "cpu"), cpu, r["cpu"].action))

        m = s.memory
        self._check("ram", r["ram"], m.percent >= r["ram"].threshold, lambda: Alert(
            "ram", "warning", "Memória RAM quase cheia",
            f"{m.percent:.0f}% em uso ({fmt_bytes(m.used)} de {fmt_bytes(m.total)}). "
            f"O Windows passa a usar o disco e tudo fica mais lento." + _top(s, "mem"), m.percent, r["ram"].action))

        if m.commit_limit:
            pct = m.commit_used / m.commit_limit * 100
            self._check("commit", r["commit"], pct >= r["commit"].threshold, lambda: Alert(
                "commit", "critical" if pct >= 97 else "warning", "Memória virtual quase esgotada",
                f"{pct:.0f}% do limite ({fmt_bytes(m.commit_used)} de {fmt_bytes(m.commit_limit)}). "
                "Programas podem fechar sozinhos. Feche aplicativos que não está usando.", pct, r["commit"].action))

        for key, temp in (("cpu_temp", s.temps.cpu), ("gpu_temp", s.temps.gpu)):
            rule = r[key]
            hot = temp is not None and temp >= rule.threshold
            crit = temp is not None and temp >= CRITICAL_TEMP[key]
            part = "O processador" if key == "cpu_temp" else "A placa de vídeo"
            self._check(key, rule, hot, lambda t=temp, c=crit, p=part, k=key, a=rule.action: Alert(
                k, "critical" if c else "warning", f"Temperatura da {'CPU' if k == 'cpu_temp' else 'GPU'} alta",
                f"{p} está a {t:.0f} °C. Verifique a ventilação (saídas de ar livres, superfície rígida) "
                "e feche programas pesados.", t, a))

        rule = r["disk_free"]
        for p in s.partitions:
            free_pct = 100 - p.percent
            self._check(f"disk:{p.mount}", rule, free_pct <= rule.threshold, lambda p=p, f=free_pct: Alert(
                "disk_free", "critical" if f <= 3 else "warning", f"Pouco espaço em {p.mount.rstrip(chr(92))}",
                f"Restam {fmt_bytes(p.free)} ({f:.0f}%). Use a Limpeza de Disco ou o Sensor de Armazenamento "
                "e desinstale programas que não usa.", f, rule.action))

        apps = s.processes.apps
        if apps and apps is not self._last_procs:
            self._last_procs = apps
            rc, rm = r["app_cpu"], r["app_ram"]
            names = set()
            for a in apps:
                low = a.name.lower()
                if low in ("system", "memory compression", "registry"):
                    continue
                names.add(low)
                self._check(f"app_cpu:{low}", rc, a.cpu >= rc.threshold, lambda a=a: Alert(
                    "app_cpu", "warning", f"{a.name} está pesando na CPU",
                    f"{a.name} usa {a.cpu:.0f}% da CPU há mais de {_dur(rc.duration)}"
                    f"{f' ({a.count} processos)' if a.count > 1 else ''}. Se não estiver usando, feche-o.",
                    a.cpu, rc.action))
                self._check(f"app_ram:{low}", rm, a.memory >= rm.threshold * 2 ** 30, lambda a=a: Alert(
                    "app_ram", "warning", f"{a.name} está usando muita memória",
                    f"{a.name} ocupa {fmt_bytes(a.memory)} de RAM"
                    f"{f' em {a.count} processos' if a.count > 1 else ''}.", a.memory / 2 ** 30, rm.action))
            # apps que fecharam: zera o "desde quando"
            for key in [k for k in self._since if k.startswith(("app_cpu:", "app_ram:"))]:
                if key.split(":", 1)[1] not in names:
                    self._since.pop(key, None)

        from ..widgets.hub import DataHub
        bat = DataHub.instance().battery if DataHub._instance else None
        if bat is not None:
            rb = r["battery"]
            self._check("battery", rb, bat.percent <= rb.threshold and not bat.power_plugged, lambda: Alert(
                "battery", "critical" if bat.percent <= 8 else "warning", "Bateria fraca",
                f"{bat.percent:.0f}% restantes. Conecte o carregador.", bat.percent))

    # ------------------------------------------------------------------- rede
    def on_network(self, n: NetworkSnapshot) -> None:
        try:
            self._eval_network(n)
        except Exception:
            log.exception("Erro ao avaliar alerta de rede")

    def _eval_network(self, n: NetworkSnapshot) -> None:
        rule = self.rules["internet"]
        now = self.clock()
        down = n.status in ("offline", "no_internet")
        if down:
            if self._net_down_since is None:
                self._net_down_since = now
            if rule.enabled and not self._net_alerted and now - self._net_down_since >= rule.threshold:
                self._net_alerted = True
                if n.status == "offline":
                    msg = ("O Wi-Fi foi desconectado." if n.wifi.available and not n.wifi.connected
                           else "Nenhuma conexão de rede ativa.")
                else:
                    msg = ("Conectado à rede, mas sem acesso à internet. Pode ser o roteador ou o provedor — "
                           "tente reiniciar o roteador.")
                self.fire(Alert("internet", "warning", "Conexão com a internet caiu", msg, None, rule.action))
        else:
            if self._net_alerted:
                mins = (now - (self._net_down_since or now)) / 60
                self.fire(Alert("internet_back", "info", "Internet restabelecida",
                                f"A conexão voltou após {_dur(int(mins * 60))}.", None, rule.action))
            self._net_down_since = None
            self._net_alerted = False

    # ---------------------------------------------------------------- relatórios
    def _maybe_weekly_report(self) -> None:
        s = Settings.instance()
        if not s.get("alerts.weekly_report", True):
            return
        last = float(s.get("alerts.last_weekly_report", 0) or 0)
        if self.clock() - last < 7 * 86400 - 3600:
            return
        try:
            from .reports import build_report, export_html
            path = export_html(build_report("7d"))
            s.set("alerts.last_weekly_report", int(self.clock()))
            self.fire(Alert("report", "info", "Relatório semanal pronto",
                            "Seu resumo de desempenho dos últimos 7 dias foi gerado. Abra em Alertas → Relatórios.",
                            None, f"open:{path}"))
        except Exception:
            log.exception("Falha ao gerar relatório semanal")

    def shutdown(self) -> None:
        self.usage.flush()


def _dur(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} s"
    m = round(seconds / 60)
    return f"{m} minuto{'s' if m != 1 else ''}" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def _top(s: Snapshot, by: str) -> str:
    apps = sorted(s.processes.apps, key=lambda a: a.cpu if by == "cpu" else a.memory, reverse=True)
    apps = [a for a in apps if a.name.lower() not in ("system", "memory compression")][:3]
    if not apps:
        return ""
    if by == "cpu":
        items = ", ".join(f"{a.name.removesuffix('.exe')} ({a.cpu:.0f}%)" for a in apps)
    else:
        items = ", ".join(f"{a.name.removesuffix('.exe')} ({fmt_bytes(a.memory)})" for a in apps)
    return f" Maiores consumidores: {items}."
