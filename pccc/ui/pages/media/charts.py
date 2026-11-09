"""Desenhos usados nas abas de mídia: medidor de nível, espectro e minigráfico."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ....media.visualizer import AudioVisualizer
from ...theme import ThemeManager


class LevelMeter(QWidget):
    """Barrinha do nível de som (0–1)."""

    def __init__(self) -> None:
        super().__init__()
        self.value = 0.0
        self.setFixedSize(70, 8)

    def set_value(self, v: float) -> None:
        if abs(v - self.value) > 0.01:
            self.value = v
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(QRectF(self.rect()), 4, 4)
        w = self.width() * max(0.0, min(1.0, self.value * 1.4))
        if w > 1:
            p.setBrush(QColor("#34d399") if self.value < 0.7 else QColor("#fbbf24"))
            p.drawRoundedRect(QRectF(0, 0, w, self.height()), 4, 4)
        p.end()


class SpectrumView(QWidget):
    """Visualizador grande (30 quadros/s enquanto visível)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(170)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._timer.start(33)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    def paintEvent(self, _e) -> None:
        bands, peaks, _lvl = AudioVisualizer.instance().snapshot()
        t = ThemeManager.instance().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n = len(bands)
        gap = 4
        bw = (w - gap * (n - 1)) / n
        g = QLinearGradient(0, h, 0, 0)
        g.setColorAt(0, QColor(t.accent))
        g.setColorAt(1, QColor(t.accent2))
        p.setPen(Qt.NoPen)
        for i, v in enumerate(bands):
            x = i * (bw + gap)
            bh = max(3.0, v * (h - 8))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(x, h - bh, bw, bh), bw / 3, bw / 3)
            py = h - max(3.0, peaks[i] * (h - 8)) - 5
            p.setBrush(QColor(255, 255, 255, 140))
            p.drawRoundedRect(QRectF(x, py, bw, 2.5), 1, 1)
        p.end()


class Sparkline(QWidget):
    def __init__(self, height: int = 90) -> None:
        super().__init__()
        self.values: list[float] = []
        self.setMinimumHeight(height)

    def set_values(self, vals: list[float]) -> None:
        self.values = list(vals)
        self.update()

    def paintEvent(self, _e) -> None:
        if len(self.values) < 2:
            return
        t = ThemeManager.instance().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        top = max(max(self.values) * 1.15, 30)
        step = w / 59
        x0 = w - step * (len(self.values) - 1)
        path = QPainterPath()
        for i, v in enumerate(self.values):
            pt = (x0 + i * step, h - h * min(1.0, v / top))
            path.moveTo(*pt) if i == 0 else path.lineTo(*pt)
        p.setPen(QPen(QColor(t.accent), 2))
        p.drawPath(path)
        p.setPen(QColor(t.p["muted"]))
        p.drawText(4, 14, f"{top:.0f}")
        p.end()
