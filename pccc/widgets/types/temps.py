"""Monitor de temperatura."""
from __future__ import annotations

from PySide6.QtCore import Qt

from ...ui.icons import G
from ..base import Canvas, Renderer
from ._common import RED, heat, hub, no_data


# ========================================================================== 7. Temperatura
class TempWidget(Renderer):
    type_id, title, glyph = "temps", "Monitor de temperatura", G.TEMP
    description = "CPU, GPU e discos com cores de alerta (verde, âmbar, vermelho)."
    base_size = (250, 132)
    defaults = {"warn": 70, "hot": 85}

    def draw(self, c: Canvas) -> None:
        s = hub().sys
        if not s:
            no_data(c)
            return
        c.glyph(12, 8, 22, 22, G.TEMP, 12)
        c.text(36, 8, 200, 22, "Temperaturas", 12.5, 600)
        rows = [("CPU", s.temps.cpu), ("GPU", s.temps.gpu)]
        rows += list(s.temps.disks.items())[:1]
        warn, hot = self.opt["warn"], self.opt["hot"]
        for i, (name, v) in enumerate(rows):
            y = 36 + i * 22
            col = heat(v, warn, hot)
            c.text(14, y, 70, 18, name[:10], 11.5, color=c.s.muted)
            c.bar(76, y + 6, 110, 6, (v or 0) / 1.1, col)
            c.text(190, y, 50, 18, f"{v:.0f}°" if v is not None else "N/D", 12, 600, color=col,
                   align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        c.spark(14, 104, 222, 22, hub().hist["cpu_temp"], RED, vmax=110)
