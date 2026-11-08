"""Relógio digital."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt

from ...ui.icons import G
from ..base import Canvas, Renderer
from ._common import DIAS, MESES


# ============================================================================ 1. Relógio
class ClockWidget(Renderer):
    type_id, title, glyph = "clock", "Relógio digital", G.CLOCK
    description = "Hora grande com segundos e data por extenso."
    base_size = (270, 118)
    defaults = {"h24": True, "seconds": True, "show_date": True}

    def draw(self, c: Canvas) -> None:
        now = datetime.now()
        hm = now.strftime("%H:%M") if self.opt["h24"] else now.strftime("%I:%M").lstrip("0")
        has_date = self.opt["show_date"]
        y = 6 if has_date else 18
        c.text(18, y, 190, 70, hm, 58, 600, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        right = []
        if self.opt["seconds"]:
            right.append(now.strftime("%S"))
        if not self.opt["h24"]:
            right.append("AM" if now.hour < 12 else "PM")
        if right:
            # logo após os números grandes, alinhado à base deles
            from PySide6.QtGui import QFontMetricsF
            sx = min(18 + QFontMetricsF(c.s.font(58, 600)).horizontalAdvance(hm) + 8, 214)
            c.text(sx, y + 30, 60, 30, right[0], 22, 500, color=c.s.accent, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
            if len(right) > 1:
                c.text(sx, y + 10, 60, 20, right[1], 13, 600, color=c.s.muted)
        if has_date:
            txt = f"{DIAS[now.weekday()]}, {now.day} de {MESES[now.month - 1]}"
            c.text(20, 80, 240, 26, txt, 15, 500, color=c.s.muted)
