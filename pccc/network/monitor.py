"""Serviço de monitoramento de rede (thread própria).

Cadências:
* 1 s  — tráfego por interface, Wi-Fi (sinal), estatísticas de ping, status, eventos
* 5 s  — interfaces/IPs/gateway/DNS (detecta troca de rede ou de IP)
* 60 s — consumo de dados gravado no SQLite (por dia e por interface)
O ping roda em outra thread (PingMonitor) para que um timeout nunca atrase as leituras.
"""
from __future__ import annotations

import time
from dataclasses import replace
from datetime import date, timedelta

import psutil
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from ..core.config import Settings
from ..core.database import Database
from ..core.logger import get_logger
from .adapters import list_interfaces, pick_active
from .models import NetEvent, NetworkSnapshot, UsageTotals
from .ping import PingMonitor
from .wifi import WifiReader

log = get_logger("network")

EVENT_TEXT = {"wifi_down": "Wi-Fi desconectado", "wifi_up": "Wi-Fi conectado",
              "internet_down": "Internet indisponível", "internet_up": "Internet restabelecida",
              "ip_change": "Endereço IP alterado", "network_change": "Rede alterada"}


def stability_score(loss: float, jitter: float | None, avg: float | None, drops: int) -> tuple[int, str]:
    """Nota de 0 a 100 combinando perda, variação (jitter), latência e quedas recentes."""
    score = 100.0
    score -= loss * 3
    score -= min(30.0, (jitter or 0) * 0.6)
    score -= min(20.0, max(0.0, (avg or 0) - 60) * 0.2)
    score -= min(20.0, drops * 4)
    s = int(max(0, min(100, round(score))))
    label = "Excelente" if s >= 85 else "Boa" if s >= 70 else "Regular" if s >= 50 else "Ruim"
    return s, label


class NetworkWorker(QObject):
    snapshot = Signal(object)  # NetworkSnapshot

    def __init__(self) -> None:
        super().__init__()
        self._s = Settings.instance()
        self._ready = False

    @Slot()
    def start(self) -> None:
        from ..core.com import ensure_com
        ensure_com()
        try:
            self._db = Database.instance()
            self._wifi = WifiReader()
            self._ping = PingMonitor(interval_s=max(0.5, self._s.get("network.ping_interval_ms", 1000) / 1000))
            self._ping.set_target("internet", self._s.get("network.ping_host", "1.1.1.1"))
            self._ping_enabled = bool(self._s.get("network.ping_enabled", True))
            if self._ping_enabled:
                self._ping.start()
            self._interfaces = list_interfaces()
            self._active = pick_active(self._interfaces)
            self._last_io = psutil.net_io_counters(pernic=True)
            self._last_t = time.monotonic()
            self._usage_base = dict(self._last_io)   # base para contabilizar consumo
            self._status = "unknown"
            self._wifi_connected: bool | None = None
            self._last_ssid = ""
            self._last_ip = ""
            self._events: list[NetEvent] = [NetEvent(ts, k, m) for ts, k, m in
                                            self._db.net_events(int(time.time()) - 86400, 50)]
            self._usage = self._load_usage()
        except Exception:
            log.exception("Falha ao iniciar monitor de rede")
            return

        self._fast = QTimer(self)
        self._fast.timeout.connect(self._tick)
        self._fast.start(1000)
        self._ifs_timer = QTimer(self)
        self._ifs_timer.timeout.connect(self._refresh_interfaces)
        self._ifs_timer.start(5000)
        self._usage_timer = QTimer(self)
        self._usage_timer.timeout.connect(self._flush_usage)
        self._usage_timer.start(60_000)
        self._s.changed.connect(self._on_setting)
        self._ready = True
        self._refresh_interfaces()
        log.info("Monitor de rede iniciado")

    # --------------------------------------------------------------- configuração
    def _on_setting(self, key: str, value) -> None:
        if key == "network.ping_host":
            self._ping.set_target("internet", str(value))
        elif key == "network.ping_enabled":
            self._ping_enabled = bool(value)
            if self._ping_enabled and not self._ping.running:
                self._ping = PingMonitor(self._ping.interval)
                self._ping.set_target("internet", self._s.get("network.ping_host", "1.1.1.1"))
                self._refresh_interfaces()
                self._ping.start()
            elif not self._ping_enabled:
                self._ping.stop()

    @Slot()
    def refresh_now(self) -> None:
        if self._ready:
            self._refresh_interfaces()
            self._tick()

    # ---------------------------------------------------------------- eventos
    def _event(self, kind: str, detail: str = "") -> None:
        msg = EVENT_TEXT.get(kind, kind) + (f" — {detail}" if detail else "")
        ev = NetEvent(time.time(), kind, msg)
        self._events.insert(0, ev)
        del self._events[100:]
        try:
            self._db.add_net_event(int(ev.ts), kind, msg)
        except Exception:
            log.exception("Falha ao gravar evento de rede")
        log.info("Evento de rede: %s", msg)

    # ------------------------------------------------------------- interfaces
    def _refresh_interfaces(self) -> None:
        try:
            self._interfaces = list_interfaces()
        except Exception:
            log.exception("Falha ao listar interfaces")
            return
        active = pick_active(self._interfaces)
        self._active = active
        gw = next((g for g in (active.gateways if active else []) if "." in g), "")
        self._ping.set_target("gateway", gw)
        ip = active.ipv4[0] if active and active.ipv4 else ""
        if self._last_ip and ip and ip != self._last_ip:
            self._event("ip_change", f"{self._last_ip} → {ip} ({active.name if active else '?'})")
        if ip:
            self._last_ip = ip

    # ------------------------------------------------------------------- tick
    def _tick(self) -> None:
        try:
            snap = self._build()
            self.snapshot.emit(snap)
        except Exception:
            log.exception("Erro no monitor de rede")

    def _build(self) -> NetworkSnapshot:
        now = time.monotonic()
        dt = max(now - self._last_t, 1e-3)
        io = psutil.net_io_counters(pernic=True)
        interfaces = [replace(i) for i in self._interfaces]   # cópias: a UI lê em outra thread
        active_name = self._active.name if self._active else None
        snap = NetworkSnapshot(ts=time.time(), interfaces=interfaces,
                               active=next((i for i in interfaces if i.name == active_name), None))

        for iface in interfaces:
            cur, prev = io.get(iface.name), self._last_io.get(iface.name)
            if cur is None:
                continue
            iface.total_recv, iface.total_sent = cur.bytes_recv, cur.bytes_sent
            if prev is not None:
                iface.down_bps = max(0.0, (cur.bytes_recv - prev.bytes_recv) / dt)
                iface.up_bps = max(0.0, (cur.bytes_sent - prev.bytes_sent) / dt)
            if iface.is_physical:
                snap.down_bps += iface.down_bps
                snap.up_bps += iface.up_bps
        self._last_io, self._last_t = io, now

        # Wi-Fi
        snap.wifi = self._wifi.read()
        w = snap.wifi
        if w.available:
            if self._wifi_connected is not None and w.connected != self._wifi_connected:
                self._event("wifi_up" if w.connected else "wifi_down", w.ssid or self._last_ssid)
            elif w.connected and self._last_ssid and w.ssid and w.ssid != self._last_ssid:
                self._event("network_change", f"{self._last_ssid} → {w.ssid}")
                self._refresh_interfaces()
            self._wifi_connected = w.connected
            if w.ssid:
                self._last_ssid = w.ssid

        # Ping e status
        if self._ping_enabled:
            snap.ping_internet = self._ping.stats("internet")
            snap.ping_gateway = self._ping.stats("gateway")
        has_link = self._active is not None and self._active.up
        fails = self._ping.consecutive_failures("internet") if self._ping_enabled else 0
        if not has_link:
            status = "offline"
        elif self._ping_enabled and fails >= 3:
            status = "no_internet"
        else:
            status = "online"
        if self._status != "unknown" and status != self._status:
            if status == "online":
                self._event("internet_up")
            elif self._status == "online":
                self._event("internet_down", "sem resposta do servidor de teste" if status == "no_internet"
                            else "nenhuma interface conectada")
            self._refresh_interfaces()  # rede mudou: relê IPs/gateway
        self._status = status
        snap.status = status

        cutoff = time.time() - 86400
        snap.events = [e for e in self._events if e.ts >= cutoff][:30]
        snap.drops_24h = sum(1 for e in snap.events if e.kind in ("internet_down", "wifi_down"))
        p = snap.ping_internet
        snap.stability, snap.stability_label = stability_score(p.loss_pct, p.jitter_ms, p.avg_ms, snap.drops_24h)
        if not self._ping_enabled:
            snap.stability_label = "Ping desativado"
        snap.usage = self._usage_with_pending(io)
        return snap

    # ---------------------------------------------------------------- consumo
    def _load_usage(self) -> UsageTotals:
        since = (date.today() - timedelta(days=29)).isoformat()
        rows = self._db.net_usage_by_day(since)
        return UsageTotals(daily=[(d, int(rx or 0), int(tx or 0)) for d, rx, tx in rows])

    def _pending(self, io) -> dict[str, tuple[int, int]]:
        """Bytes ainda não gravados, por interface física."""
        physical = {i.name for i in self._interfaces if i.is_physical}
        out = {}
        for name, cur in io.items():
            if name not in physical:
                continue
            base = self._usage_base.get(name)
            if base is None:
                out[name] = (0, 0)
                continue
            rx = cur.bytes_recv - base.bytes_recv
            tx = cur.bytes_sent - base.bytes_sent
            # Contador zerado (adaptador reiniciado): conta a partir do zero.
            out[name] = (rx if rx >= 0 else cur.bytes_recv, tx if tx >= 0 else cur.bytes_sent)
        return out

    def _usage_with_pending(self, io) -> UsageTotals:
        today = date.today().isoformat()
        rx_p = sum(v[0] for v in self._pending(io).values())
        tx_p = sum(v[1] for v in self._pending(io).values())
        daily = list(self._usage.daily)
        if daily and daily[-1][0] == today:
            day, rx0, tx0 = daily[-1]
            daily[-1] = (day, rx0 + rx_p, tx0 + tx_p)
        else:
            daily.append((today, rx_p, tx_p))
        week = (date.today() - timedelta(days=6)).isoformat()
        u = UsageTotals(daily=daily)
        for d, rx, tx in daily:
            u.month_rx += rx
            u.month_tx += tx
            if d >= week:
                u.week_rx += rx
                u.week_tx += tx
            if d == today:
                u.today_rx, u.today_tx = rx, tx
        return u

    def _flush_usage(self) -> None:
        try:
            io = psutil.net_io_counters(pernic=True)
            today = date.today().isoformat()
            for name, (rx, tx) in self._pending(io).items():
                self._db.add_net_usage(today, name, rx, tx)
            self._usage_base = dict(io)
            self._usage = self._load_usage()
        except Exception:
            log.exception("Falha ao gravar consumo de dados")

    @Slot()
    def stop(self) -> None:
        if self._ready:
            for t in (self._fast, self._ifs_timer, self._usage_timer):
                t.stop()
            self._flush_usage()
            self._ping.stop()
            self._wifi.close()


class NetworkService(QObject):
    snapshot = Signal(object)
    _instance: "NetworkService | None" = None
    _stop_requested = Signal()
    _refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.latest: NetworkSnapshot | None = None
        self._thread = QThread()
        self._thread.setObjectName("NetworkThread")
        self._worker = NetworkWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self._worker.snapshot.connect(self._on_snapshot)
        self._stop_requested.connect(self._worker.stop)
        self._refresh_requested.connect(self._worker.refresh_now)

    @classmethod
    def instance(cls) -> "NetworkService":
        if cls._instance is None:
            cls._instance = NetworkService()
        return cls._instance

    def start(self) -> None:
        self._thread.start()

    def refresh(self) -> None:
        self._refresh_requested.emit()

    def _on_snapshot(self, snap: NetworkSnapshot) -> None:
        self.latest = snap
        self.snapshot.emit(snap)

    def stop(self) -> None:
        self._stop_requested.emit()
        self._thread.quit()
        self._thread.wait(3000)
