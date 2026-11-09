"""Dashboard principal: visão geral em tempo real do computador."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QGridLayout, QHBoxLayout

from ...monitoring.models import Snapshot
from ...monitoring.system import system_info
from ..components import (CoreBars, DataTable, GlassCard, LiveChart, MetricCard, ResponsiveGrid,
                          RingGauge, label, legend, stat_block)
from ...network.monitor import NetworkService
from ..fmt import fmt_bits, fmt_bytes, fmt_mhz, fmt_pct, fmt_rate, fmt_temp, fmt_uptime
from ..history import History
from ..icons import G
from ..theme import SERIES
from .base import Page


def _greeting() -> str:
    h = datetime.now().hour
    return "Bom dia" if 5 <= h < 12 else "Boa tarde" if h < 18 else "Boa noite"


class DashboardPage(Page):
    title = "Painel"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        info = system_info()
        self.title_label.setText(f"{_greeting()} 👋")
        self.subtitle_label.setText(f"{info['hostname']}  ·  {info['os']}")
        self.uptime_badge = label("", "BadgeAccent")
        self.header_right.addWidget(self.uptime_badge)

        # ---- Linha 1: medidores circulares -------------------------------------
        gauges = GlassCard()
        gl = QHBoxLayout()
        gl.setSpacing(8)
        self.g_cpu = RingGauge("CPU", SERIES["cpu"])
        self.g_ram = RingGauge("Memória", SERIES["ram"])
        self.g_gpu = RingGauge("GPU", SERIES["gpu"])
        self.g_disk = RingGauge("Disco C:", SERIES["disk"])
        self.g_temp = RingGauge("Temp. CPU", SERIES["temp"])
        for g in (self.g_cpu, self.g_ram, self.g_gpu, self.g_disk, self.g_temp):
            g.setMinimumSize(110, 110)
            gl.addWidget(g, 1)
        gauges.add(gl)
        gauges.setMinimumHeight(150)
        self.add(gauges)

        # ---- Linha 2: cartões de métricas ---------------------------------------
        grid = ResponsiveGrid(min_col_width=290, max_cols=3)
        self.c_cpu = grid.add(MetricCard("Processador", G.CPU, SERIES["cpu"]))
        self.c_ram = grid.add(MetricCard("Memória RAM", G.MEMORY, SERIES["ram"]))
        self.c_gpu = grid.add(MetricCard("Placa de vídeo", G.GPU, SERIES["gpu"]))
        self.c_disk = grid.add(MetricCard("Armazenamento", G.DISK, SERIES["disk"], chart_max=None))
        self.c_net = grid.add(MetricCard("Rede", G.NETWORK, SERIES["down"], chart_max=None))
        self.c_sys = grid.add(self._system_card())
        self.add(grid)

        # ---- Linha 3: histórico + núcleos ---------------------------------------
        row = ResponsiveGrid(min_col_width=420, max_cols=2)
        hist = GlassCard("Uso nos últimos 2 minutos", G.HISTORY)
        hist.add(legend([("CPU", SERIES["cpu"]), ("RAM", SERIES["ram"]), ("GPU", SERIES["gpu"])]))
        self.hist_chart = LiveChart([("cpu", "CPU", SERIES["cpu"]), ("ram", "RAM", SERIES["ram"]),
                                     ("gpu", "GPU", SERIES["gpu"])], y_max=100, show_axis=True,
                                    y_fmt=lambda v: f"{v:.0f}%")
        self.hist_chart.setMinimumHeight(200)
        hist.add(self.hist_chart, 1)
        row.add(hist)

        cores = GlassCard("Uso por núcleo", G.CPU)
        self.cores_badge = label("", "Badge")
        cores.add_header_widget(self.cores_badge)
        self.core_bars = CoreBars()
        cores.add(self.core_bars, 1)
        row.add(cores)
        self.add(row)

        # ---- Linha 4: aplicativos + temperaturas --------------------------------
        row2 = ResponsiveGrid(min_col_width=420, max_cols=2)
        apps = GlassCard("Consumo por aplicativo", G.APPS)
        self.apps_badge = label("", "Badge")
        apps.add_header_widget(self.apps_badge)
        self.apps_table = DataTable(["Aplicativo", "Processos", "CPU", "Memória"])
        self.apps_table.setMinimumHeight(300)
        apps.add(self.apps_table, 1)
        row2.add(apps)

        temps = GlassCard("Temperaturas", G.TEMP)
        self.temp_source = label("", "Badge")
        temps.add_header_widget(self.temp_source)
        tg = QGridLayout()
        tg.setHorizontalSpacing(24)
        tg.setVerticalSpacing(14)
        w, self.t_cpu = stat_block("Processador")
        tg.addWidget(w, 0, 0)
        w, self.t_gpu = stat_block("Placa de vídeo")
        tg.addWidget(w, 0, 1)
        w, self.t_disk = stat_block("Discos")
        tg.addWidget(w, 1, 0, 1, 2)
        temps.add(tg)
        self.temp_chart = LiveChart([("cpu_temp", "CPU", SERIES["temp"]), ("gpu_temp", "GPU", SERIES["gpu"])],
                                    y_max=None, show_axis=True, y_fmt=lambda v: f"{v:.0f}°")
        self.temp_chart.setMinimumHeight(140)
        temps.add(self.temp_chart, 1)
        self.temp_hint = label("", "Faint", wrap=True)
        temps.add(self.temp_hint)
        row2.add(temps)
        self.add(row2)
        self.layout_.addStretch(1)

    def _system_card(self) -> GlassCard:
        card = GlassCard("Sistema", G.INFO)
        g = QGridLayout()
        g.setHorizontalSpacing(20)
        g.setVerticalSpacing(12)
        w, self.s_uptime = stat_block("Tempo ligado")
        g.addWidget(w, 0, 0)
        w, self.s_procs = stat_block("Processos")
        g.addWidget(w, 0, 1)
        w, self.s_threads = stat_block("Threads")
        g.addWidget(w, 1, 0)
        w, self.s_freq = stat_block("Frequência")
        g.addWidget(w, 1, 1)
        card.add(g)
        card.root.addStretch(1)
        return card

    # ----------------------------------------------------------------- update
    def on_snapshot(self, s: Snapshot) -> None:
        h = History.instance()
        cpu, mem = s.cpu, s.memory
        gpu = s.primary_gpu
        sysdrive = next((p for p in s.partitions if p.mount.upper().startswith("C")),
                        s.partitions[0] if s.partitions else None)

        self.uptime_badge.setText(f"Ligado há {fmt_uptime(s.uptime_s)}")
        self.g_cpu.set_value(cpu.percent)
        self.g_ram.set_value(mem.percent)
        self.g_gpu.set_value(gpu.percent if gpu else 0, None if gpu else "—")
        if sysdrive:
            self.g_disk.caption = f"Disco {sysdrive.mount.rstrip(chr(92))}"
            self.g_disk.set_value(sysdrive.percent)
        t = s.temps.cpu
        self.g_temp.set_value(t if t is not None else 0, fmt_temp(t))

        self.c_cpu.update_values(
            fmt_pct(cpu.percent), f"{cpu.cores} núcleos · {cpu.threads} threads",
            f"{fmt_mhz(cpu.freq_mhz)}\n{fmt_temp(s.temps.cpu)}", cpu.percent, h.get("cpu"),
            badge=cpu.name.replace("with Radeon Graphics", "").strip()[:28])
        self.c_ram.update_values(
            fmt_bytes(mem.used), f"de {fmt_bytes(mem.total)} · {fmt_bytes(mem.available)} disponível",
            fmt_pct(mem.percent), mem.percent, h.get("ram"))
        if gpu:
            vram = (f"VRAM {fmt_bytes(gpu.dedicated_used)} / {fmt_bytes(gpu.dedicated_total)}"
                    if gpu.dedicated_total else f"Compartilhada {fmt_bytes(gpu.shared_used)}")
            self.c_gpu.update_values(fmt_pct(gpu.percent), vram, fmt_temp(gpu.temperature),
                                     gpu.percent, h.get("gpu"), badge=gpu.name[:28])
        else:
            self.c_gpu.update_values("—", "Nenhuma GPU detectada")
        if sysdrive:
            self.c_disk.update_values(
                f"{fmt_bytes(sysdrive.free)} livres",
                f"↓ Leitura {fmt_rate(s.disk_io.read_bps)}  ·  ↑ Gravação {fmt_rate(s.disk_io.write_bps)}",
                f"{fmt_pct(sysdrive.percent)} usado\nde {fmt_bytes(sysdrive.total)}",
                sysdrive.percent,
                [a + b for a, b in zip(h.get("disk_read"), h.get("disk_write"))],
                badge=f"Atividade {fmt_pct(s.disk_io.active_percent)}")
        net = NetworkService.instance().latest
        badge, side = None, f"Total recebido\n{fmt_bytes(s.net_io.total_recv)}"
        if net is not None:
            w = net.wifi
            badge = (w.ssid[:26] if w.connected and w.ssid else
                     (net.active.name if net.active else "Desconectado"))
            ping = net.ping_internet.last_ms
            side = (f"Ping {ping:.0f} ms" if ping is not None else "Ping —") + \
                   (f"\nSinal {w.signal}%" if w.connected else "")
        self.c_net.update_values(
            fmt_bits(s.net_io.down_bps), f"↓ Download   ·   ↑ Upload {fmt_bits(s.net_io.up_bps)}",
            side, None, h.get("net_down"), badge=badge)

        self.s_uptime.setText(fmt_uptime(s.uptime_s))
        self.s_procs.setText(str(s.processes.total))
        self.s_threads.setText(f"{s.processes.threads:,}".replace(",", "."))
        self.s_freq.setText(fmt_mhz(cpu.freq_mhz))

        self.hist_chart.set_data({"cpu": h.get("cpu"), "ram": h.get("ram"), "gpu": h.get("gpu")})
        self.core_bars.set_values(cpu.per_core)
        self.cores_badge.setText(f"{len(cpu.per_core)} threads · {fmt_mhz(cpu.freq_mhz)}")

        apps = s.processes.apps[:14]
        self.apps_badge.setText(f"{s.processes.total} processos")
        self.apps_table.set_rows([[a.name, str(a.count), fmt_pct(a.cpu, 1), fmt_bytes(a.memory)]
                                  for a in apps])

        self.t_cpu.setText(fmt_temp(s.temps.cpu))
        self.t_gpu.setText(fmt_temp(s.temps.gpu))
        disks = s.temps.disks
        self.t_disk.setText(" · ".join(f"{k}: {v:.0f} °C" for k, v in disks.items()) if disks
                            else "N/D (requer administrador)")
        self.temp_source.setText(s.temps.source or "sem sensor")
        self.temp_hint.setText(s.temps.hint)
        self.temp_chart.set_data({"cpu_temp": h.get("cpu_temp"), "gpu_temp": h.get("gpu_temp")})
