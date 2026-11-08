"""Rede e Wi-Fi: conexão, sinal, velocidade em tempo real, latência, estabilidade,
detalhes da interface, consumo de dados, teste de velocidade e histórico de tráfego."""
from __future__ import annotations

import time
from collections import deque
from datetime import date, datetime, timedelta

import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QMessageBox, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from ...core.database import Database
from ...core.winapi import shell_open
from ...network.models import InterfaceInfo, NetworkSnapshot
from ...network.monitor import NetworkService
from ...network.speedtest import SpeedResult, SpeedTestRunner
from ..components import (DataTable, GlassCard, LiveChart, ResponsiveGrid, RingGauge, Segmented, ToggleSwitch,
                          label, legend, restyle, stat_block)
from ..fmt import fmt_bits, fmt_bytes
from ..history import History
from ..icons import G
from ..theme import SERIES, ThemeManager
from .base import Page

STATUS = {"online": ("Conectado à internet", "BadgeAccent"),
          "no_internet": ("Conectado, sem internet", "Badge"),
          "offline": ("Desconectado", "Badge"),
          "unknown": ("Verificando...", "Badge")}


def _ms(v: float | None) -> str:
    return "—" if v is None else (f"{v:.0f} ms" if v >= 1 else "< 1 ms")


def _grid(names: list[str], cols: int) -> tuple[QGridLayout, dict]:
    g = QGridLayout()
    g.setHorizontalSpacing(24)
    g.setVerticalSpacing(12)
    out = {}
    for i, n in enumerate(names):
        w, v = stat_block(n)
        v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)  # permite copiar IPs etc.
        g.addWidget(w, i // cols, i % cols)
        out[n] = v
    return g, out


def _signal_label(pct: int) -> str:
    return "Excelente" if pct >= 80 else "Bom" if pct >= 60 else "Razoável" if pct >= 40 else "Fraco"


class NetworkPage(Page):
    title = "Rede e Wi-Fi"
    subtitle = "Conexão, velocidade, latência e consumo de dados em tempo real"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        size = History.instance().size
        self._down = deque(maxlen=size)
        self._up = deque(maxlen=size)
        self._auto = True
        self._selected_iface: str | None = None
        self._snap: NetworkSnapshot | None = None

        # ---- cabeçalho -----------------------------------------------------------
        self.status_badge = label("Verificando...", "Badge")
        self.header_right.addWidget(self.status_badge)
        self.header_right.addSpacing(8)
        self.header_right.addWidget(label("Atualização automática", "Muted"))
        self.auto_toggle = ToggleSwitch()
        self.auto_toggle.setChecked(True)
        self.auto_toggle.toggled.connect(self._set_auto)
        self.header_right.addWidget(self.auto_toggle)
        refresh = QPushButton("Atualizar agora")
        refresh.clicked.connect(self._refresh_now)
        self.header_right.addWidget(refresh)

        # ---- abas: Conexão (tudo abaixo) | Dispositivos na rede -------------------
        self.tabs = Segmented([("conn", "Conexão"), ("devices", "Dispositivos na rede")])
        self.tabs.changed.connect(self.switch)
        self.add(self.tabs)
        page_layout = self.layout_
        self.conn_view = QWidget()
        self.layout_ = QVBoxLayout(self.conn_view)      # o conteúdo da aba Conexão vai para cá
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(16)

        # ---- linha 1: Wi-Fi + tráfego --------------------------------------------
        row1 = ResponsiveGrid(min_col_width=440, max_cols=2)
        self.wifi_card = GlassCard("Wi-Fi", G.NETWORK)
        self.wifi_badge = label("", "Badge")
        self.wifi_card.add_header_widget(self.wifi_badge)
        top = QHBoxLayout()
        self.signal_gauge = RingGauge("Sinal", SERIES["down"])
        self.signal_gauge.setFixedSize(132, 132)
        top.addWidget(self.signal_gauge)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.ssid = label("—", "BigValue")
        self.ssid.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.wifi_sub = label("", "Muted", wrap=True)
        col.addStretch(1)
        col.addWidget(self.ssid)
        col.addWidget(self.wifi_sub)
        col.addStretch(1)
        top.addLayout(col, 1)
        self.wifi_card.add(top)
        g, self.wf = _grid(["Intensidade (RSSI)", "Canal / Banda", "Padrão", "Segurança",
                            "Velocidade do link", "BSSID (roteador)"], cols=3)
        self.wifi_card.add(g)
        self.wifi_warn = label("", "Faint", wrap=True)
        self.wifi_warn.setStyleSheet("color: #fbbf24;")
        self.loc_btn = QPushButton("Abrir configurações de localização")
        self.loc_btn.clicked.connect(lambda: shell_open("ms-settings:privacy-location"))
        self.wifi_card.add(self.wifi_warn)
        self.wifi_card.add(self.loc_btn)
        self.wifi_warn.hide()
        self.loc_btn.hide()
        row1.add(self.wifi_card)

        traffic = GlassCard("Velocidade em tempo real", G.PERFORMANCE)
        self.iface_badge = label("", "Badge")
        traffic.add_header_widget(self.iface_badge)
        speeds = QHBoxLayout()
        for attr, _glyph, title, color in (("down_val", G.DOWN, "Download", SERIES["down"]),
                                          ("up_val", G.UP, "Upload", SERIES["up"])):
            box = QVBoxLayout()
            box.setSpacing(0)
            t = label(f"{'↓' if attr == 'down_val' else '↑'}  {title}", "Muted")
            t.setStyleSheet(f"color: {color};")
            v = label("—", "BigValue")
            setattr(self, attr, v)
            box.addWidget(t)
            box.addWidget(v)
            speeds.addLayout(box, 1)
        traffic.add(speeds)
        self.traffic_chart = LiveChart([("down", "Download", SERIES["down"]), ("up", "Upload", SERIES["up"])],
                                       y_max=None, show_axis=True, y_fmt=lambda v: fmt_bits(v))
        self.traffic_chart.setMinimumHeight(170)
        traffic.add(self.traffic_chart, 1)
        self.totals = label("", "Faint")
        traffic.add(self.totals)
        row1.add(traffic)
        self.add(row1)

        # ---- linha 2: latência + estabilidade ------------------------------------
        row2 = ResponsiveGrid(min_col_width=440, max_cols=2)
        lat = GlassCard("Latência (ping)", G.CLOCK)
        self.ping_target = label("", "Badge")
        lat.add_header_widget(self.ping_target)
        g, self.pg = _grid(["Internet", "Roteador (gateway)", "Média", "Jitter", "Mín / Máx", "Perda de pacotes"],
                           cols=3)
        lat.add(g)
        lat.add(legend([("Internet", SERIES["cpu"]), ("Roteador", SERIES["gpu"])]))
        self.ping_chart = LiveChart([("internet", "Internet", SERIES["cpu"]), ("gateway", "Roteador", SERIES["gpu"])],
                                    y_max=None, show_axis=True, fill=False, y_fmt=lambda v: f"{v:.0f} ms")
        self.ping_chart.setMinimumHeight(150)
        lat.add(self.ping_chart, 1)
        row2.add(lat)

        stab = GlassCard("Estabilidade da conexão", G.SHIELD)
        top2 = QHBoxLayout()
        self.stab_gauge = RingGauge("Estabilidade", SERIES["gpu"])
        self.stab_gauge.setFixedSize(132, 132)
        top2.addWidget(self.stab_gauge)
        col2 = QVBoxLayout()
        self.stab_label = label("—", "BigValue")
        self.stab_sub = label("Baseado em perda de pacotes, jitter, latência e quedas nas últimas 24 h.",
                              "Muted", wrap=True)
        col2.addStretch(1)
        col2.addWidget(self.stab_label)
        col2.addWidget(self.stab_sub)
        col2.addStretch(1)
        top2.addLayout(col2, 1)
        stab.add(top2)
        stab.add(label("Eventos de conexão (24 h)", "Faint"))
        self.events = DataTable(["Horário", "Evento"], stretch_col=1)
        self.events.setMinimumHeight(140)
        stab.add(self.events, 1)
        row2.add(stab)
        self.add(row2)

        # ---- linha 3: detalhes da interface --------------------------------------
        det = GlassCard("Detalhes da conexão", G.INFO)
        self.iface_combo = QComboBox()
        self.iface_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.iface_combo.activated.connect(self._pick_iface)
        det.add_header_widget(self.iface_combo)
        g, self.dt = _grid(["Interface", "Status", "Tipo", "Adaptador",
                            "Endereço IPv4", "Gateway padrão", "Servidores DNS", "Endereço MAC",
                            "Endereço IPv6", "DHCP", "Velocidade do link", "MTU"], cols=4)
        for k in ("Adaptador", "Endereço IPv6", "Servidores DNS", "Gateway padrão"):
            self.dt[k].setWordWrap(True)
            self.dt[k].setStyleSheet("font-size: 10pt;")
        det.add(g)
        self.add(det)

        # ---- linha 4: consumo + teste de velocidade ------------------------------
        row4 = ResponsiveGrid(min_col_width=440, max_cols=2)
        usage = GlassCard("Consumo de dados", G.DOWN)
        g, self.us = _grid(["Hoje", "Últimos 7 dias", "Últimos 30 dias"], cols=3)
        usage.add(g)
        usage.add(legend([("Recebido", SERIES["down"]), ("Enviado", SERIES["up"])]))
        self.usage_plot = pg.PlotWidget()
        self.usage_plot.setBackground(None)
        self.usage_plot.setMenuEnabled(False)
        self.usage_plot.setMouseEnabled(False, False)
        self.usage_plot.hideButtons()
        self.usage_plot.setMinimumHeight(170)
        self.usage_plot.sizeHint = lambda: QSize(240, 170)
        self.usage_plot.getAxis("left").setWidth(60)
        self.usage_plot.getAxis("left").tickStrings = lambda values, s, sp: [fmt_bytes(v, 0) for v in values]
        self.usage_plot.showGrid(y=True, alpha=0.12)
        usage.add(self.usage_plot, 1)
        usage.add(label("Soma das interfaces físicas (Wi-Fi e cabo). Gravado a cada minuto.", "Faint", wrap=True))
        row4.add(usage)

        sp = GlassCard("Teste de velocidade", G.PERFORMANCE)
        self.sp_server = label("", "Badge")
        sp.add_header_widget(self.sp_server)
        g, self.st = _grid(["Download", "Upload", "Latência", "Jitter"], cols=4)
        for v in self.st.values():
            v.setObjectName("BigValue")
            v.setStyleSheet("font-size: 18pt;")
        sp.add(g)
        self.sp_phase = label("Clique em Iniciar para medir sua conexão.", "Muted")
        sp.add(self.sp_phase)
        self.sp_bar = QProgressBar()
        self.sp_bar.setRange(0, 1000)
        self.sp_bar.setTextVisible(False)
        sp.add(self.sp_bar)
        btns = QHBoxLayout()
        self.sp_btn = QPushButton("Iniciar teste")
        self.sp_btn.setObjectName("Primary")
        self.sp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sp_btn.clicked.connect(self._toggle_speedtest)
        btns.addWidget(self.sp_btn)
        btns.addStretch(1)
        self.sp_ip = label("", "Faint")
        self.sp_ip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        btns.addWidget(self.sp_ip)
        sp.add(btns)
        sp.add(label("Servidor: Cloudflare (o mais próximo). Duração ~16 s. Em conexões rápidas consome "
                     "100–400 MB — evite em planos de dados limitados.", "Faint", wrap=True))
        sp.add(label("Testes anteriores", "Faint"))
        self.sp_hist = DataTable(["Data", "Download", "Upload", "Latência", "Rede"], stretch_col=4)
        self.sp_hist.setMinimumHeight(130)
        sp.add(self.sp_hist, 1)
        row4.add(sp)
        self.add(row4)

        # ---- linha 5: histórico de tráfego ---------------------------------------
        hist = GlassCard("Histórico de tráfego", G.HISTORY)
        self.hist_range = Segmented([("1h", "1 hora"), ("24h", "24 horas"), ("7d", "7 dias")])
        self.hist_range.changed.connect(lambda _k: self._load_history())
        hist.add_header_widget(self.hist_range)
        hist.add(legend([("Download", SERIES["down"]), ("Upload", SERIES["up"])]))
        self.hist_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.hist_plot.setBackground(None)
        self.hist_plot.setMenuEnabled(False)
        self.hist_plot.hideButtons()
        self.hist_plot.setMinimumHeight(180)
        self.hist_plot.sizeHint = lambda: QSize(240, 180)
        self.hist_plot.showGrid(y=True, alpha=0.12)
        self.hist_plot.getAxis("left").setWidth(70)
        self.hist_plot.getAxis("left").tickStrings = lambda values, s, sp: [fmt_bits(v) for v in values]
        self.hist_down = self.hist_plot.plot(pen=pg.mkPen(SERIES["down"], width=1.8))
        self.hist_up = self.hist_plot.plot(pen=pg.mkPen(SERIES["up"], width=1.8))
        self.hist_empty = label("Ainda não há histórico suficiente (médias gravadas a cada minuto).", "Muted")
        hist.add(self.hist_empty)
        hist.add(self.hist_plot)
        self.add(hist)
        self.layout_ = page_layout
        from .lan import DevicesView
        self.devices_view = DevicesView(self)
        self.add(self.conn_view)
        self.add(self.devices_view)
        self.layout_.addStretch(1)
        self.devices_view.hide()

        self._style_plots(ThemeManager.instance().theme)
        ThemeManager.instance().changed.connect(self._style_plots)

        self.runner = SpeedTestRunner(self)
        self.runner.progress.connect(self._sp_progress)
        self.runner.result.connect(self._sp_done)

        self._slow = QTimer(self)
        self._slow.timeout.connect(self._load_history)
        self._slow.start(60_000)

    # ------------------------------------------------------------------ helpers
    def _style_plots(self, t) -> None:
        for pw in (self.usage_plot, self.hist_plot):
            for name in ("left", "bottom"):
                ax = pw.getAxis(name)
                ax.setPen(pg.mkPen(t.p["faint"]))
                ax.setTextPen(pg.mkPen(t.p["muted"]))

    def _set_auto(self, on: bool) -> None:
        self._auto = on
        if on and NetworkService.instance().latest:
            self.on_net_snapshot(NetworkService.instance().latest)

    def _refresh_now(self) -> None:
        NetworkService.instance().refresh()
        self._load_history()
        self._load_speedtests()
        snap = NetworkService.instance().latest
        if snap:
            self._render(snap)

    def _pick_iface(self, _i: int) -> None:
        self._selected_iface = self.iface_combo.currentData()
        if self._snap:
            self._render_details(self._snap)

    def switch(self, key: str) -> None:
        """'conn' (conexão) ou 'devices' (aparelhos na rede)."""
        self.tabs.set_current(key)
        self.conn_view.setVisible(key == "conn")
        self.devices_view.setVisible(key == "devices")
        if key == "devices":
            self.devices_view.on_shown()
        self.relayout()

    def on_shown(self) -> None:
        if self.tabs.current() == "devices":
            self.devices_view.on_shown()
        self._load_history()
        self._load_speedtests()
        snap = NetworkService.instance().latest
        if snap:
            self._render(snap)

    # ------------------------------------------------------------------ dados
    def on_net_snapshot(self, snap: NetworkSnapshot) -> None:
        # Os buffers do gráfico continuam acumulando mesmo com a página pausada.
        self._down.append(snap.down_bps)
        self._up.append(snap.up_bps)
        if self._auto and self.isVisible():
            self._render(snap)

    def _render(self, s: NetworkSnapshot) -> None:
        self._snap = s
        text, obj = STATUS.get(s.status, STATUS["unknown"])
        self.status_badge.setText(text)
        restyle(self.status_badge, obj)

        # Wi-Fi
        w = s.wifi
        if not w.available:
            self.ssid.setText("Sem Wi-Fi")
            self.wifi_sub.setText("Nenhum adaptador Wi-Fi encontrado.")
            self.signal_gauge.set_value(0, "—")
            self.wifi_badge.setText("indisponível")
        elif not w.connected:
            self.ssid.setText("Desconectado")
            self.wifi_sub.setText(f"{w.adapter} · {w.state}")
            self.signal_gauge.set_value(0, "—")
            self.wifi_badge.setText(w.state)
        else:
            self.ssid.setText(w.ssid or "(nome oculto)")
            self.wifi_sub.setText(f"Sinal {_signal_label(w.signal).lower()} · {w.adapter}")
            self.signal_gauge.set_value(w.signal)
            self.wifi_badge.setText("Conectado")
        self.wf["Intensidade (RSSI)"].setText(f"{w.rssi} dBm" if w.rssi is not None else "—")
        self.wf["Canal / Banda"].setText(f"{w.channel} · {w.band}" if w.channel else "—")
        self.wf["Padrão"].setText(w.standard or "—")
        self.wf["Segurança"].setText(w.security or "—")
        self.wf["Velocidade do link"].setText(f"{w.rx_mbps:.0f} Mbps" if w.rx_mbps else "—")
        self.wf["BSSID (roteador)"].setText(w.bssid or "—")
        self.wifi_warn.setText(w.error)
        self.wifi_warn.setVisible(bool(w.error))
        self.loc_btn.setVisible("localização" in w.error)

        # Tráfego
        a = s.active
        self.iface_badge.setText(a.name if a else "sem conexão")
        self.down_val.setText(fmt_bits(s.down_bps))
        self.up_val.setText(fmt_bits(s.up_bps))
        self.traffic_chart.set_data({"down": list(self._down), "up": list(self._up)})
        if a:
            self.totals.setText(f"Desde que o Windows iniciou ({a.name}): recebidos {fmt_bytes(a.total_recv)} · "
                                f"enviados {fmt_bytes(a.total_sent)}")

        # Latência
        pi, pgw = s.ping_internet, s.ping_gateway
        self.ping_target.setText(f"alvo: {pi.target or '—'}")
        self.pg["Internet"].setText(_ms(pi.last_ms) if pi.sent else "desativado")
        self.pg["Roteador (gateway)"].setText(_ms(pgw.last_ms) if pgw.target else "—")
        self.pg["Média"].setText(_ms(pi.avg_ms))
        self.pg["Jitter"].setText(_ms(pi.jitter_ms))
        self.pg["Mín / Máx"].setText(f"{_ms(pi.min_ms)} / {_ms(pi.max_ms)}" if pi.min_ms is not None else "—")
        loss = self.pg["Perda de pacotes"]
        loss.setText(f"{pi.loss_pct:.0f}%".replace(".", ","))
        loss.setStyleSheet("color: #fb7185;" if pi.loss_pct >= 2 else "")
        self.ping_chart.set_data({"internet": pi.history, "gateway": pgw.history})

        # Estabilidade
        self.stab_gauge.set_value(s.stability, f"{s.stability}")
        self.stab_label.setText(s.stability_label)
        self.stab_sub.setText(f"{s.drops_24h} queda(s) nas últimas 24 h · perda {pi.loss_pct:.0f}% · "
                              f"jitter {_ms(pi.jitter_ms)}. Baseado nos últimos 60 pings.")
        self.events.set_rows([[datetime.fromtimestamp(e.ts).strftime("%d/%m %H:%M:%S"), e.message]
                              for e in s.events] or [["—", "Nenhuma queda ou mudança registrada"]],
                             align_right_from=99)

        self._render_details(s)

        # Consumo
        u = s.usage
        self.us["Hoje"].setText(f"↓ {fmt_bytes(u.today_rx)}  ↑ {fmt_bytes(u.today_tx)}")
        self.us["Últimos 7 dias"].setText(f"↓ {fmt_bytes(u.week_rx)}  ↑ {fmt_bytes(u.week_tx)}")
        self.us["Últimos 30 dias"].setText(f"↓ {fmt_bytes(u.month_rx)}  ↑ {fmt_bytes(u.month_tx)}")
        self._render_usage(u.daily)

    def _render_details(self, s: NetworkSnapshot) -> None:
        shown = [i for i in s.interfaces if i.kind != "Loopback" and (i.up or i.is_physical)]
        names = [i.name for i in shown]
        current = [self.iface_combo.itemData(i) for i in range(self.iface_combo.count())]
        if names != current:
            self.iface_combo.blockSignals(True)
            self.iface_combo.clear()
            for i in shown:
                mark = "  ★ ativa" if s.active and i.name == s.active.name else ""
                self.iface_combo.addItem(f"{i.name} ({i.kind}){mark}", i.name)
            self.iface_combo.blockSignals(False)
        name = self._selected_iface or (s.active.name if s.active else (names[0] if names else None))
        idx = self.iface_combo.findData(name)
        if idx >= 0:
            self.iface_combo.setCurrentIndex(idx)
        iface: InterfaceInfo | None = next((i for i in shown if i.name == name), None)
        d = self.dt
        if iface is None:
            for v in d.values():
                v.setText("—")
            return
        d["Interface"].setText(iface.name)
        d["Status"].setText("Conectada" if iface.up else "Desconectada")
        d["Tipo"].setText(iface.kind)
        d["Adaptador"].setText(iface.description)
        d["Endereço IPv4"].setText("\n".join(iface.ipv4) or "—")
        d["Gateway padrão"].setText("\n".join(g for g in iface.gateways) or "—")
        d["Servidores DNS"].setText("\n".join(iface.dns[:4]) or "—")
        d["Endereço MAC"].setText(iface.mac or "—")
        d["Endereço IPv6"].setText("\n".join(ip for ip in iface.ipv6 if not ip.startswith("fe80"))[:200]
                                   or "\n".join(iface.ipv6[:1]) or "—")
        d["DHCP"].setText(f"Ativado ({iface.dhcp_server})" if iface.dhcp and iface.dhcp_server
                          else "Ativado" if iface.dhcp else "Desativado (IP fixo)")
        d["Velocidade do link"].setText(f"{iface.link_mbps:.0f} Mbps" if iface.link_mbps else "—")
        d["MTU"].setText(str(iface.mtu) if iface.mtu and iface.mtu < 100000 else "—")

    def _render_usage(self, daily: list[tuple[str, int, int]]) -> None:
        days = [(date.today() - timedelta(days=13 - i)).isoformat() for i in range(14)]
        by = {d: (rx, tx) for d, rx, tx in daily}
        rx = [by.get(d, (0, 0))[0] for d in days]
        tx = [by.get(d, (0, 0))[1] for d in days]
        self.usage_plot.clear()
        xs = list(range(14))
        self.usage_plot.addItem(pg.BarGraphItem(x=[x - 0.18 for x in xs], height=rx, width=0.34,
                                                brush=SERIES["down"], pen=pg.mkPen(None)))
        self.usage_plot.addItem(pg.BarGraphItem(x=[x + 0.18 for x in xs], height=tx, width=0.34,
                                                brush=SERIES["up"], pen=pg.mkPen(None)))
        ticks = [(i, f"{d[8:10]}/{d[5:7]}") for i, d in enumerate(days) if i % 2 == 1 or i == 13]
        self.usage_plot.getAxis("bottom").setTicks([ticks])
        self.usage_plot.setXRange(-0.6, 13.6, padding=0)
        self.usage_plot.setYRange(0, max(rx + tx + [1024 * 1024]) * 1.15, padding=0)

    def _load_history(self) -> None:
        if not self.isVisible():
            return
        span = {"1h": 3600, "24h": 86400, "7d": 7 * 86400}[self.hist_range.current()]
        try:
            rows = Database.instance().query_metrics(int(time.time()) - span, ("net_down", "net_up"))
        except Exception:
            rows = []
        enough = len(rows) >= 2
        self.hist_empty.setVisible(not enough)
        self.hist_plot.setVisible(enough)
        if enough:
            xs = [r[0] for r in rows]
            self.hist_down.setData(xs, [r[1] or 0 for r in rows])
            self.hist_up.setData(xs, [r[2] or 0 for r in rows])
            self.hist_plot.enableAutoRange()

    # ----------------------------------------------------------- teste de velocidade
    def _toggle_speedtest(self) -> None:
        if self.runner.isRunning():
            self.runner.cancel()
            self.sp_phase.setText("Cancelando...")
            return
        snap = NetworkService.instance().latest
        if snap and snap.status != "online":
            QMessageBox.warning(self, "Teste de velocidade", "Sem conexão com a internet no momento.")
            return
        for v in self.st.values():
            v.setText("—")
        self.sp_btn.setText("Cancelar")
        restyle(self.sp_btn, "Danger")
        self.sp_bar.setValue(0)
        self.runner.begin()

    def _sp_progress(self, phase: str, frac: float, mbps: float) -> None:
        base = {"Conectando ao servidor": 0, "Latência": 0.05, "Download": 0.1, "Upload": 0.55}.get(phase, 0)
        span = 0.45 if phase in ("Download", "Upload") else 0.05
        self.sp_bar.setValue(int((base + span * frac) * 1000))
        if phase == "Download":
            self.st["Download"].setText(f"{mbps:.0f} Mbps")
        elif phase == "Upload":
            self.st["Upload"].setText(f"{mbps:.0f} Mbps")
        self.sp_phase.setText(f"{phase}..." + (f"  {mbps:.1f} Mbps" if mbps else ""))

    def _sp_done(self, r: SpeedResult) -> None:
        self.sp_btn.setText("Iniciar teste")
        restyle(self.sp_btn, "Primary")
        if r.error:
            self.sp_phase.setText(r.error)
            self.sp_bar.setValue(0)
            return
        self.sp_bar.setValue(1000)
        self.st["Download"].setText(f"{r.down_mbps:.0f} Mbps")
        self.st["Upload"].setText(f"{r.up_mbps:.0f} Mbps")
        self.st["Latência"].setText(_ms(r.latency_ms))
        self.st["Jitter"].setText(_ms(r.jitter_ms))
        self.sp_server.setText(r.server)
        self.sp_ip.setText(f"IP público: {r.public_ip}")
        self.sp_phase.setText(f"Concluído · {fmt_bytes(r.bytes_used)} transferidos")
        snap = NetworkService.instance().latest
        try:
            Database.instance().add_speedtest({
                "ts": r.ts, "down_mbps": r.down_mbps, "up_mbps": r.up_mbps, "latency_ms": r.latency_ms,
                "jitter_ms": r.jitter_ms, "server": r.server, "public_ip": r.public_ip,
                "iface": snap.active.name if snap and snap.active else "",
                "ssid": snap.wifi.ssid if snap else ""})
        except Exception:
            pass
        self._load_speedtests()

    def _load_speedtests(self) -> None:
        try:
            rows = Database.instance().speedtests(10)
        except Exception:
            rows = []
        self.sp_hist.set_rows([[datetime.fromtimestamp(ts).strftime("%d/%m %H:%M"),
                                f"{d:.0f} Mbps" if d else "—", f"{u:.0f} Mbps" if u else "—", _ms(lat),
                                ssid or iface or "—"]
                               for ts, d, u, lat, _j, _srv, _ip, iface, ssid in rows]
                              or [["—", "", "", "", "Nenhum teste ainda"]], align_right_from=1)

    def shutdown(self) -> None:
        if self.runner.isRunning():
            self.runner.cancel()
            self.runner.wait(5000)
