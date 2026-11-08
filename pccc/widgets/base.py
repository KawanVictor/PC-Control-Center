"""Base dos widgets: configuração, desenho vetorial escalável e utilitários de pintura.

Cada widget desenha em um "canvas virtual" de tamanho fixo (``base_size``). A janela aplica
``QPainter.scale`` conforme a largura escolhida pelo usuário: redimensionar fica nítido em
qualquer tamanho, e o mesmo código desenha a miniatura da galeria.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field
from typing import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QFontMetricsF, QLinearGradient, QPainter,
                           QPainterPath, QPen)

from ..ui.theme import ThemeManager, icon_font_family


@dataclass
class WidgetConfig:
    type: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    x: int = 100
    y: int = 100
    width: int = 0                 # 0 = tamanho padrão do tipo
    visible: bool = True
    locked: bool = False
    layer: str = "bottom"          # bottom (atrás das janelas) | normal | top (sempre visível)
    accent: str = ""               # vazio = cor de destaque do tema
    bg: str = "#0b1020"
    bg_opacity: float = 0.55
    text: str = "#e6eaf2"
    font_scale: float = 1.0
    refresh_ms: int = 1000
    options: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WidgetConfig":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


class Style:
    """Cores e fontes resolvidas para um widget (inclui cache de QFont)."""

    def __init__(self, cfg: WidgetConfig) -> None:
        t = ThemeManager.instance().theme
        self.accent = QColor(cfg.accent or t.accent)
        self.accent2 = QColor(t.accent2) if not cfg.accent else QColor(cfg.accent).lighter(135)
        self.text = QColor(cfg.text or "#e6eaf2")
        self.muted = QColor(self.text)
        self.muted.setAlphaF(0.62)
        self.faint = QColor(self.text)
        self.faint.setAlphaF(0.22)
        self.font_scale = max(0.5, min(2.0, float(cfg.font_scale or 1.0)))
        self._fonts: dict[tuple, QFont] = {}

    def font(self, px: float, weight: int = 400, family: str = "Segoe UI Variable Display") -> QFont:
        key = (round(px, 1), weight, family)
        f = self._fonts.get(key)
        if f is None:
            f = QFont(family)
            f.setPixelSize(max(6, int(round(px * self.font_scale))))
            f.setWeight(QFont.Weight(weight))
            f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)  # escala suave
            self._fonts[key] = f
        return f

    def icon(self, px: float) -> QFont:
        return self.font(px, 400, icon_font_family())


class Canvas:
    """Utilitários de desenho no espaço virtual do widget."""

    def __init__(self, p: QPainter, style: Style, w: float, h: float) -> None:
        self.p, self.s, self.w, self.h = p, style, w, h

    # ------------------------------------------------------------------ texto
    def text(self, x, y, w, h, s: str, px: float = 12, weight: int = 400, color: QColor | None = None,
             align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, family: str = "Segoe UI Variable Display") -> None:
        font = self.s.font(px, weight, family)
        self.p.setFont(font)
        self.p.setPen(color or self.s.text)
        if "\n" not in s:
            # Linha única: corta com "…" em vez de cortar no meio de uma letra.
            s = QFontMetricsF(font).elidedText(s, Qt.TextElideMode.ElideRight, w)
        self.p.drawText(QRectF(x, y, w, h), int(align), s)

    def glyph(self, x, y, w, h, g: str, px: float = 14, color: QColor | None = None,
              align=Qt.AlignmentFlag.AlignCenter) -> None:
        self.p.setFont(self.s.icon(px))
        self.p.setPen(color or self.s.accent)
        self.p.drawText(QRectF(x, y, w, h), int(align), g)

    # ------------------------------------------------------------- medidores
    def ring(self, cx, cy, r, value: float, width: float = 7, color: QColor | None = None,
             span_deg: float = 270) -> None:
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        start = 90 + span_deg / 2
        self.p.setPen(QPen(self.s.faint, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        self.p.drawArc(rect, int(start * 16), int(-span_deg * 16))
        v = max(0.0, min(100.0, value or 0.0))
        if v > 0.5:
            c = color or self.s.accent
            g = QConicalGradient(rect.center(), start)
            g.setColorAt(0, c)
            g.setColorAt(span_deg / 360, c.lighter(140) if color else self.s.accent2)
            self.p.setPen(QPen(QBrush(g), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            self.p.drawArc(rect, int(start * 16), int(-span_deg * v / 100 * 16))

    def bar(self, x, y, w, h, value: float, color: QColor | None = None) -> None:
        r = h / 2
        self.p.setPen(Qt.PenStyle.NoPen)
        self.p.setBrush(self.s.faint)
        self.p.drawRoundedRect(QRectF(x, y, w, h), r, r)
        v = max(0.0, min(100.0, value or 0.0))
        if v > 0:
            c = color or self.s.accent
            g = QLinearGradient(x, 0, x + w, 0)
            g.setColorAt(0, c)
            g.setColorAt(1, c.lighter(135) if color else self.s.accent2)
            self.p.setBrush(QBrush(g))
            self.p.drawRoundedRect(QRectF(x, y, max(h, w * v / 100), h), r, r)

    def spark(self, x, y, w, h, values: Iterable[float], color: QColor | None = None,
              vmax: float | None = None, capacity: int = 60, fill: bool = True) -> None:
        vals = [v for v in values][-capacity:]
        if len(vals) < 2:
            return
        top = vmax if vmax else max(max(vals) * 1.15, 1e-9)
        step = w / (capacity - 1)
        x0 = x + w - step * (len(vals) - 1)
        pts = [QPointF(x0 + i * step, y + h - h * min(1.0, max(0.0, v / top))) for i, v in enumerate(vals)]
        c = color or self.s.accent
        path = QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        if fill:
            area = QPainterPath(path)
            area.lineTo(pts[-1].x(), y + h)
            area.lineTo(pts[0].x(), y + h)
            area.closeSubpath()
            g = QLinearGradient(0, y, 0, y + h)
            top_c = QColor(c)
            top_c.setAlphaF(0.35)
            bot_c = QColor(c)
            bot_c.setAlphaF(0.0)
            g.setColorAt(0, top_c)
            g.setColorAt(1, bot_c)
            self.p.setPen(Qt.PenStyle.NoPen)
            self.p.setBrush(QBrush(g))
            self.p.drawPath(area)
        self.p.setBrush(Qt.BrushStyle.NoBrush)
        self.p.setPen(QPen(c, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        self.p.drawPath(path)

    def rounded(self, x, y, w, h, r, color: QColor) -> None:
        self.p.setPen(Qt.PenStyle.NoPen)
        self.p.setBrush(color)
        self.p.drawRoundedRect(QRectF(x, y, w, h), r, r)


class Renderer:
    """Base de todos os widgets. Subclasses definem metadados e ``draw``."""

    type_id = ""
    title = ""
    description = ""
    glyph = ""
    base_size = (240, 140)
    default_refresh = 1000
    min_refresh = 250             # intervalo mínimo de redesenho (ms); o visualizador usa ~30 fps
    defaults: dict = {}
    needs: set[str] = set()       # system, network, weather, media, battery

    def __init__(self, cfg: WidgetConfig) -> None:
        self.cfg = cfg
        for k, v in self.defaults.items():
            cfg.options.setdefault(k, v)

    @property
    def opt(self) -> dict:
        return self.cfg.options

    def draw(self, c: Canvas) -> None:  # pragma: no cover — implementado nas subclasses
        raise NotImplementedError

    def hit_areas(self) -> list[tuple[QRectF, str]]:
        """Áreas clicáveis no espaço virtual: [(retângulo, id)]."""
        return []

    def on_click(self, area_id: str) -> None:
        pass

    def tooltip(self) -> str:
        return ""


def fmt_rate_short(bps: float, bits: bool = True) -> str:
    if bits:
        v = bps * 8
        for unit, div in (("Gbps", 1e9), ("Mbps", 1e6), ("Kbps", 1e3)):
            if v >= div:
                return f"{v / div:.1f} {unit}".replace(".", ",")
        return f"{v:.0f} bps"
    for unit, div in (("GB/s", 2 ** 30), ("MB/s", 2 ** 20), ("KB/s", 2 ** 10)):
        if bps >= div:
            return f"{bps / div:.1f} {unit}".replace(".", ",")
    return f"{bps:.0f} B/s"


def clamp01(v: float) -> float:
    return 0.0 if v != v else max(0.0, min(1.0, v))


__all__ = ["WidgetConfig", "Style", "Canvas", "Renderer", "fmt_rate_short", "clamp01", "math"]
