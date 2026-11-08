"""Visualizador de áudio."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt

from ..base import Canvas, Renderer


# ================================================================ 16. Visualizador de áudio
class VisualizerWidget(Renderer):
    type_id, title, glyph = "visualizer", "Visualizador de áudio", ""
    description = "Barras que dançam com o som que está tocando no PC."
    base_size = (320, 110)
    default_refresh = 33
    min_refresh = 33
    defaults = {"style": "bars", "bands": 32}

    def draw(self, c: Canvas) -> None:
        from ...media.visualizer import AudioVisualizer
        bands, peaks, _level = AudioVisualizer.instance().snapshot()
        n = max(8, min(48, int(self.opt["bands"])))
        step = len(bands) / n
        vals = [max(bands[int(i * step):int((i + 1) * step)] or [0]) for i in range(n)]
        pk = [max(peaks[int(i * step):int((i + 1) * step)] or [0]) for i in range(n)]
        x0, y0, w, h = 12, 10, c.w - 24, c.h - 20
        gap = 3
        bw = (w - gap * (n - 1)) / n
        mirror = self.opt["style"] == "mirror"
        from PySide6.QtGui import QLinearGradient, QBrush
        grad = QLinearGradient(0, y0 + h, 0, y0)
        grad.setColorAt(0, c.s.accent)
        grad.setColorAt(1, c.s.accent2)
        c.p.setPen(Qt.PenStyle.NoPen)
        c.p.setBrush(QBrush(grad))
        for i, v in enumerate(vals):
            bh = max(2.0, v * (h / 2 if mirror else h))
            x = x0 + i * (bw + gap)
            if mirror:
                c.p.drawRoundedRect(QRectF(x, y0 + h / 2 - bh, bw, bh * 2), bw / 2.5, bw / 2.5)
            else:
                c.p.drawRoundedRect(QRectF(x, y0 + h - bh, bw, bh), bw / 2.5, bw / 2.5)
                py = y0 + h - max(2.0, pk[i] * h) - 3
                c.rounded(x, py, bw, 2, 1, c.s.muted)
