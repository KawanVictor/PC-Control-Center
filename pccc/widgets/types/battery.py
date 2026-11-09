"""Monitor de bateria."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor

from ..base import Canvas, Renderer
from ._common import AMBER, GREEN, RED, hub, no_data


# ============================================================================ 13. Bateria
class BatteryWidget(Renderer):
    type_id, title, glyph = "battery", "Monitor de bateria", ""
    description = "Carga, status do carregador e tempo restante."
    base_size = (232, 104)
    default_refresh = 5000

    def draw(self, c: Canvas) -> None:
        b = hub().battery
        if b is None:
            no_data(c, "Este computador não tem bateria")
            return
        pct = b.percent
        col = RED if pct < 20 and not b.power_plugged else AMBER if pct < 40 and not b.power_plugged else GREEN
        # corpo da bateria
        c.p.setPen(c.s.muted)
        c.p.setBrush(Qt.NoBrush)
        c.p.drawRoundedRect(QRectF(16, 28, 70, 40), 7, 7)
        c.rounded(87, 40, 5, 16, 2, c.s.muted)
        c.rounded(20, 32, 62 * pct / 100, 32, 4, col)
        if b.power_plugged:
            c.glyph(16, 28, 70, 40, "", 16, QColor("#0b1020") if pct > 55 else c.s.text)
        c.text(104, 14, 120, 40, f"{pct:.0f}%", 30, 600)
        if b.power_plugged:
            status = "Carregando" if pct < 100 else "Carregada · na tomada"
        else:
            secs = b.secsleft
            status = (f"{secs // 3600}h {secs % 3600 // 60:02d}min restantes"
                      if isinstance(secs, int) and secs > 0 else "Na bateria")
        c.text(104, 54, 124, 20, status, 11, color=c.s.muted)
        c.text(16, 76, 210, 20, "Modo economia recomendado" if pct < 20 and not b.power_plugged else "",
               10, color=RED)
