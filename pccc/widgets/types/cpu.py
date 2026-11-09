"""Monitor de CPU."""
from __future__ import annotations

from ...ui.fmt import fmt_mhz
from ...ui.icons import G
from ._common import RingWidget, hub


class CpuWidget(RingWidget):
    type_id, title, glyph, label, hist_key = "cpu", "Monitor de CPU", G.CPU, "CPU", "cpu"
    description = "Uso do processador, frequência real e temperatura."

    def values(self):
        s = hub().sys
        if not s:
            return None
        name = s.cpu.name.replace("with Radeon Graphics", "").replace("Processor", "").strip()
        t = s.temps.cpu
        return s.cpu.percent, [name[:22], fmt_mhz(s.cpu.freq_mhz),
                               f"{t:.0f} °C" if t is not None else f"{s.cpu.threads} threads"]
