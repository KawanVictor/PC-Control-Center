"""Desempenho detalhado: CPU, memória, GPU, discos e histórico de longo prazo (SQLite)."""
from __future__ import annotations

import time

import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ...core.database import Database
from ...monitoring.models import Snapshot
from ..components import (DataTable, GlassCard, LiveChart, ResponsiveGrid, Segmented, label, legend,
                          stat_block)
from ..fmt import fmt_bytes, fmt_mhz, fmt_pct, fmt_rate, fmt_temp, fmt_uptime
from ..history import History
from ..icons import G
from ..theme import SERIES, ThemeManager
from .base import Page


def _stats_grid(names: list[str], cols: int = 4) -> tuple[QGridLayout, dict]:
    g = QGridLayout()
    g.setHorizontalSpacing(28)
    g.setVerticalSpacing(14)
    out = {}
    for i, n in enumerate(names):
        w, v = stat_block(n)
        g.addWidget(w, i // cols, i % cols)
        out[n] = v
    return g, out


# =============================================================================== CPU
class CpuView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        main = GlassCard("Utilização do processador", G.CPU)
        self.name = label("", "BadgeAccent")
        main.add_header_widget(self.name)
        self.chart = LiveChart([("cpu", "CPU", SERIES["cpu"])], y_max=100, show_axis=True,
                               y_fmt=lambda v: f"{v:.0f}%")
        self.chart.setMinimumHeight(220)
        main.add(self.chart, 1)
        g, self.stats = _stats_grid(["Utilização", "Frequência atual", "Frequência base", "Temperatura",
                                     "Núcleos físicos", "Processadores lógicos", "Processos", "Threads",
                                     "Tempo ligado"], cols=5)
        main.add(g)
        lay.addWidget(main)

        cores = GlassCard("Processadores lógicos", G.PERFORMANCE)
        self.core_grid = ResponsiveGrid(min_col_width=150, max_cols=6, spacing=8)
        self.core_charts: list[tuple[LiveChart, QLabel]] = []
        cores.add(self.core_grid)
        lay.addWidget(cores)

        top = GlassCard("Processos que mais usam CPU", G.PROCESS)
        self.table = DataTable(["Processo", "PID", "CPU", "Memória", "Threads"])
        self.table.setMinimumHeight(330)
        top.add(self.table)
        lay.addWidget(top)

    def _ensure_cores(self, n: int) -> None:
        if len(self.core_charts) == n:
            return
        for i in range(n):
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            lb = label(f"CPU {i}", "Faint")
            v.addWidget(lb)
            ch = LiveChart([("v", "", SERIES["cpu"])], y_max=100, height=64)
            v.addWidget(ch)
            self.core_grid.add(box)
            self.core_charts.append((ch, lb))

    def update_view(self, s: Snapshot) -> None:
        h = History.instance()
        c = s.cpu
        self.name.setText(c.name)
        self.chart.set_data({"cpu": h.get("cpu")})
        st = self.stats
        st["Utilização"].setText(fmt_pct(c.percent))
        st["Frequência atual"].setText(fmt_mhz(c.freq_mhz))
        st["Frequência base"].setText(fmt_mhz(c.base_mhz))
        st["Temperatura"].setText(fmt_temp(s.temps.cpu))
        st["Núcleos físicos"].setText(str(c.cores))
        st["Processadores lógicos"].setText(str(c.threads))
        st["Processos"].setText(str(s.processes.total))
        st["Threads"].setText(f"{s.processes.threads:,}".replace(",", "."))
        st["Tempo ligado"].setText(fmt_uptime(s.uptime_s))
        self._ensure_cores(len(c.per_core))
        for i, (ch, lb) in enumerate(self.core_charts):
            if i < len(h.cores):
                ch.set_data({"v": list(h.cores[i])})
                lb.setText(f"CPU {i}  ·  {c.per_core[i]:.0f}%")
        self.table.set_rows([[p.name, str(p.pid), fmt_pct(p.cpu, 1), fmt_bytes(p.memory), str(p.threads)]
                             for p in s.processes.top_cpu])


# =========================================================================== Memória
class MemoryView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        main = GlassCard("Uso de memória", G.MEMORY)
        self.total_badge = label("", "BadgeAccent")
        main.add_header_widget(self.total_badge)
        self.chart = LiveChart([("ram", "RAM", SERIES["ram"])], y_max=100, show_axis=True,
                               y_fmt=lambda v: f"{v:.0f}%")
        self.chart.setMinimumHeight(200)
        main.add(self.chart, 1)

        comp = QVBoxLayout()
        comp.setSpacing(6)
        comp.addWidget(label("Memória física", "Faint"))
        self.phys_bar = QProgressBar()
        self.phys_bar.setTextVisible(False)
        self.phys_bar.setRange(0, 1000)
        comp.addWidget(self.phys_bar)
        comp.addWidget(label("Memória virtual (confirmada / limite)", "Faint"))
        self.commit_bar = QProgressBar()
        self.commit_bar.setTextVisible(False)
        self.commit_bar.setRange(0, 1000)
        comp.addWidget(self.commit_bar)
        main.add(comp)

        g, self.stats = _stats_grid(["Em uso", "Disponível", "Total", "Em cache",
                                     "Confirmada", "Limite de confirmação", "Arquivo de paginação",
                                     "Uso da paginação"], cols=4)
        main.add(g)
        lay.addWidget(main)

        top = GlassCard("Processos que mais usam memória", G.PROCESS)
        hint = label("Memória = conjunto de trabalho privado (mesmo critério do Gerenciador de Tarefas)", "Faint")
        top.add(hint)
        self.table = DataTable(["Processo", "PID", "Memória", "CPU", "Threads"])
        self.table.setMinimumHeight(330)
        top.add(self.table)
        lay.addWidget(top)

    def update_view(self, s: Snapshot) -> None:
        m = s.memory
        self.total_badge.setText(f"{fmt_bytes(m.total)} instalados")
        self.chart.set_data({"ram": History.instance().get("ram")})
        self.phys_bar.setValue(int(m.percent * 10))
        if m.commit_limit:
            self.commit_bar.setValue(int(m.commit_used / m.commit_limit * 1000))
        st = self.stats
        st["Em uso"].setText(f"{fmt_bytes(m.used)} ({fmt_pct(m.percent)})")
        st["Disponível"].setText(fmt_bytes(m.available))
        st["Total"].setText(fmt_bytes(m.total))
        st["Em cache"].setText(fmt_bytes(m.cached))
        st["Confirmada"].setText(fmt_bytes(m.commit_used))
        st["Limite de confirmação"].setText(fmt_bytes(m.commit_limit))
        st["Arquivo de paginação"].setText(fmt_bytes(m.swap_total))
        st["Uso da paginação"].setText(f"{fmt_bytes(m.swap_used)} ({fmt_pct(m.swap_percent)})")
        self.table.set_rows([[p.name, str(p.pid), fmt_bytes(p.memory), fmt_pct(p.cpu, 1), str(p.threads)]
                             for p in s.processes.top_memory])


# =============================================================================== GPU
class GpuView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        self._index = 0

        main = GlassCard("Placa de vídeo", G.GPU)
        self.selector = QComboBox()
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.selector.currentIndexChanged.connect(lambda i: setattr(self, "_index", max(0, i)))
        main.add_header_widget(self.selector)
        self.chart = LiveChart([("gpu", "GPU", SERIES["gpu"])], y_max=100, show_axis=True,
                               y_fmt=lambda v: f"{v:.0f}%")
        self.chart.setMinimumHeight(200)
        main.add(self.chart, 1)
        g, self.stats = _stats_grid(["Utilização", "Temperatura", "VRAM dedicada em uso", "VRAM dedicada total",
                                     "Memória compartilhada em uso", "Memória compartilhada total"], cols=3)
        main.add(g)
        lay.addWidget(main)

        row = ResponsiveGrid(min_col_width=380, max_cols=2)
        eng = GlassCard("Engines da GPU", G.PERFORMANCE)
        self.engine_box = QVBoxLayout()
        self.engine_box.setSpacing(8)
        self.engine_rows: dict[str, tuple] = {}
        eng.add(self.engine_box)
        eng.root.addStretch(1)
        row.add(eng)
        vram = GlassCard("VRAM dedicada", G.MEMORY)
        self.vram_chart = LiveChart([("v", "VRAM", SERIES["ram"])], y_max=None, show_axis=True,
                                    y_fmt=lambda v: fmt_bytes(v, 0))
        self.vram_chart.setMinimumHeight(170)
        vram.add(self.vram_chart)
        row.add(vram)
        lay.addWidget(row)

    def _engine_row(self, name: str):
        if name not in self.engine_rows:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            n = label(name)
            n.setFixedWidth(150)
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setRange(0, 1000)
            v = label("0%", "Muted")
            v.setFixedWidth(46)
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            h.addWidget(n)
            h.addWidget(bar, 1)
            h.addWidget(v)
            self.engine_box.addWidget(w)
            self.engine_rows[name] = (bar, v)
        return self.engine_rows[name]

    def update_view(self, s: Snapshot) -> None:
        if not s.gpus:
            return
        names = [g.name for g in s.gpus]
        if [self.selector.itemText(i) for i in range(self.selector.count())] != names:
            self.selector.blockSignals(True)
            self.selector.clear()
            self.selector.addItems(names)
            primary = s.primary_gpu
            self._index = s.gpus.index(primary) if primary in s.gpus else 0
            self.selector.setCurrentIndex(self._index)
            self.selector.blockSignals(False)
        i = min(self._index, len(s.gpus) - 1)
        g = s.gpus[i]
        h = History.instance()
        self.chart.set_data({"gpu": h.get(f"gpu{i}")})
        self.vram_chart.set_data({"v": h.get(f"gpu{i}_vram")})
        st = self.stats
        st["Utilização"].setText(fmt_pct(g.percent))
        st["Temperatura"].setText(fmt_temp(g.temperature))
        st["VRAM dedicada em uso"].setText(fmt_bytes(g.dedicated_used))
        st["VRAM dedicada total"].setText(fmt_bytes(g.dedicated_total))
        st["Memória compartilhada em uso"].setText(fmt_bytes(g.shared_used))
        st["Memória compartilhada total"].setText(fmt_bytes(g.shared_total))
        for name in sorted(g.engines, key=lambda k: (k != "3D", k)):
            bar, v = self._engine_row(name)
            bar.setValue(int(g.engines[name] * 10))
            v.setText(fmt_pct(g.engines[name]))


# ============================================================================ Discos
class DisksView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        io = GlassCard("Leitura e gravação", G.DISK)
        io.add(legend([("Leitura", SERIES["down"]), ("Gravação", SERIES["up"])]))
        self.io_chart = LiveChart([("disk_read", "Leitura", SERIES["down"]),
                                   ("disk_write", "Gravação", SERIES["up"])],
                                  y_max=None, show_axis=True, y_fmt=lambda v: fmt_rate(v))
        self.io_chart.setMinimumHeight(200)
        io.add(self.io_chart, 1)
        g, self.stats = _stats_grid(["Leitura", "Gravação", "Tempo ativo"], cols=3)
        io.add(g)
        lay.addWidget(io)

        self.parts_card = GlassCard("Unidades", G.FOLDER)
        self.parts_box = QVBoxLayout()
        self.parts_box.setSpacing(12)
        self.parts_card.add(self.parts_box)
        self.part_rows: dict[str, tuple] = {}
        lay.addWidget(self.parts_card)

        phys = GlassCard("Discos físicos", G.DISK)
        self.phys_table = DataTable(["Modelo", "Tipo", "Barramento", "Capacidade", "Saúde", "Temperatura"])
        self.phys_table.setMinimumHeight(70)
        self.phys_table.setMaximumHeight(160)
        phys.add(self.phys_table)
        phys.add(label("Temperatura dos discos requer executar como administrador ou o LibreHardwareMonitor aberto.",
                       "Faint", wrap=True))
        lay.addWidget(phys)

    def update_view(self, s: Snapshot) -> None:
        h = History.instance()
        self.io_chart.set_data({"disk_read": h.get("disk_read"), "disk_write": h.get("disk_write")})
        self.stats["Leitura"].setText(fmt_rate(s.disk_io.read_bps))
        self.stats["Gravação"].setText(fmt_rate(s.disk_io.write_bps))
        self.stats["Tempo ativo"].setText(fmt_pct(s.disk_io.active_percent))

        for p in s.partitions:
            if p.mount not in self.part_rows:
                w = QWidget()
                v = QVBoxLayout(w)
                v.setContentsMargins(0, 0, 0, 0)
                v.setSpacing(4)
                top = QHBoxLayout()
                name = label("", "Value")
                info = label("", "Muted")
                top.addWidget(name)
                top.addStretch(1)
                top.addWidget(info)
                bar = QProgressBar()
                bar.setTextVisible(False)
                bar.setRange(0, 1000)
                v.addLayout(top)
                v.addWidget(bar)
                self.parts_box.addWidget(w)
                self.part_rows[p.mount] = (name, info, bar)
            name, info, bar = self.part_rows[p.mount]
            name.setText(f"{p.label or 'Disco local'} ({p.mount.rstrip(chr(92))})  ·  {p.fstype}")
            info.setText(f"{fmt_bytes(p.free)} livres de {fmt_bytes(p.total)}  ·  {fmt_pct(p.percent)} usado")
            bar.setValue(int(p.percent * 10))

        self.phys_table.set_rows([[d.name, d.media, d.bus, fmt_bytes(d.size, 0), d.health,
                                   fmt_temp(d.temperature)] for d in s.physical_disks])


# ========================================================================= Histórico
class HistoryView(QWidget):
    RANGES = {"1h": 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        top = QHBoxLayout()
        top.addWidget(label("Médias gravadas a cada minuto no banco local (SQLite).", "Muted"))
        top.addStretch(1)
        self.range = Segmented([("1h", "1 hora"), ("24h", "24 horas"), ("7d", "7 dias"), ("30d", "30 dias")])
        self.range.changed.connect(lambda _k: self.reload())
        top.addWidget(self.range)
        lay.addLayout(top)

        self.empty = label("Ainda não há histórico suficiente neste período. Uma média é gravada a cada minuto "
                           "enquanto o app está aberto (inclusive na bandeja).", "Muted", wrap=True)
        lay.addWidget(self.empty)

        self.plots = {}
        for key, title, series, fmt in (
            ("usage", "CPU, RAM e GPU (%)", [("cpu", "CPU", SERIES["cpu"]), ("ram", "RAM", SERIES["ram"]),
                                            ("gpu", "GPU", SERIES["gpu"])], lambda v: f"{v:.0f}%"),
            ("temp", "Temperaturas (°C)", [("cpu_temp", "CPU", SERIES["temp"]), ("gpu_temp", "GPU", SERIES["gpu"])],
             lambda v: f"{v:.0f}°"),
            ("net", "Rede", [("net_down", "Download", SERIES["down"]), ("net_up", "Upload", SERIES["up"])], fmt_rate),
            ("disk", "Disco", [("disk_read", "Leitura", SERIES["down"]), ("disk_write", "Gravação", SERIES["up"])],
             fmt_rate),
        ):
            card = GlassCard(title, G.HISTORY)
            card.add(legend([(lbl, c) for _k, lbl, c in series]))
            pw = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
            pw.setBackground(None)
            pw.setMenuEnabled(False)
            pw.hideButtons()
            pw.setMinimumHeight(190)
            pw.sizeHint = lambda: QSize(240, 190)
            pw.showGrid(x=False, y=True, alpha=0.12)
            ax = pw.getAxis("left")
            ax.setWidth(60)
            ax.tickStrings = (lambda f: lambda values, scale, spacing: [f(v) for v in values])(fmt)
            curves = {k: pw.plot(pen=pg.mkPen(c, width=1.8)) for k, _l, c in series}
            card.add(pw)
            lay.addWidget(card)
            self.plots[key] = (pw, curves)
        self._style_axes(ThemeManager.instance().theme)
        ThemeManager.instance().changed.connect(self._style_axes)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.reload)
        self._timer.start(60_000)

    def _style_axes(self, t) -> None:
        for pw, _ in self.plots.values():
            for name in ("left", "bottom"):
                ax = pw.getAxis(name)
                ax.setPen(pg.mkPen(t.p["faint"]))
                ax.setTextPen(pg.mkPen(t.p["muted"]))

    def reload(self) -> None:
        if not self.isVisible():
            return
        since = int(time.time()) - self.RANGES.get(self.range.current(), 3600)
        cols = ("cpu", "ram", "gpu", "cpu_temp", "gpu_temp", "net_down", "net_up", "disk_read", "disk_write")
        try:
            rows = Database.instance().query_metrics(since, cols)
        except Exception:
            rows = []
        enough = len(rows) >= 2
        self.empty.setVisible(not enough)
        for pw, _ in self.plots.values():
            pw.parentWidget().setVisible(enough)
        if not enough:
            return
        xs = [r[0] for r in rows]
        data = {c: [r[i + 1] if r[i + 1] is not None else float("nan") for r in rows] for i, c in enumerate(cols)}
        for pw, curves in self.plots.values():
            for k, curve in curves.items():
                curve.setData(xs, data[k], connect="finite")
            pw.enableAutoRange()


# ============================================================================== Page
class PerformancePage(Page):
    title = "Desempenho"
    subtitle = "Monitoramento detalhado de CPU, memória, GPU e armazenamento"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tabs = Segmented([("cpu", "Processador"), ("mem", "Memória"), ("gpu", "GPU"),
                               ("disk", "Discos"), ("hist", "Histórico")])
        self.header_right.addWidget(self.tabs)
        # Em vez de QStackedWidget (que reserva a altura da maior aba), as abas ficam no
        # mesmo layout e só a atual é exibida — widgets ocultos não ocupam espaço.
        self.views = {"cpu": CpuView(), "mem": MemoryView(), "gpu": GpuView(), "disk": DisksView(),
                      "hist": HistoryView()}
        for v in self.views.values():
            self.add(v)
        self.current = "cpu"
        self.layout_.addStretch(1)
        self.tabs.changed.connect(self._switch)
        self._switch("cpu")

    def _switch(self, key: str) -> None:
        self.current = key
        self.tabs.set_current(key)
        for k, v in self.views.items():
            v.setVisible(k == key)
        hist = self.views["hist"]
        if key == "hist" and isinstance(hist, HistoryView):
            hist.reload()
        elif self.isVisible():
            from ...monitoring.collector import MonitorService
            snap = MonitorService.instance().latest
            if snap:
                self.on_snapshot(snap)

    def on_shown(self) -> None:
        hist = self.views["hist"]
        if self.tabs.current() == "hist" and isinstance(hist, HistoryView):
            hist.reload()

    def on_snapshot(self, snap: Snapshot) -> None:
        view = self.views[self.current]
        if hasattr(view, "update_view"):
            view.update_view(snap)
