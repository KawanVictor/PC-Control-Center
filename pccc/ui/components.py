"""Componentes visuais reutilizáveis: cartões de vidro, medidores, gráficos e tabelas."""
from __future__ import annotations

import math
from typing import Callable, Iterable, TypeVar

import pyqtgraph as pg
from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QLinearGradient, QPainter, QPen,
                           QStaticText)
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QProgressBar, QPushButton, QSizePolicy,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.config import Settings
from .theme import Theme, ThemeManager, icon_font

W = TypeVar("W", bound=QWidget)   # ResponsiveGrid.add devolve o widget com o tipo dele

pg.setConfigOptions(antialias=True, background=None)


def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
        if obj.startswith("Badge"):  # selos não esticam na vertical
            lb.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    lb.setWordWrap(wrap)
    return lb


def restyle(w: QWidget, object_name: str) -> None:
    """Troca o objectName e reaplica o QSS (o Qt não repolsh sozinho)."""
    if w.objectName() == object_name:
        return
    w.setObjectName(object_name)
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def icon_label(glyph: str, size: float = 12, obj: str = "CardIcon") -> QLabel:
    lb = QLabel(glyph)
    lb.setFont(icon_font(size))
    lb.setObjectName(obj)
    return lb


class GlassCard(QFrame):
    """Cartão translúcido com cabeçalho opcional (ícone + título + widget à direita)."""

    def __init__(self, title: str = "", glyph: str = "", parent=None, margins: int = 16) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(margins, margins - 2, margins, margins)
        self.root.setSpacing(8)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        if glyph:
            self.header.addWidget(icon_label(glyph, 11))
        if title:
            self.title_label = label(title.upper(), "CardTitle")
            self.header.addWidget(self.title_label)
        self.header.addStretch(1)
        if title or glyph:
            self.root.addLayout(self.header)

    def add_header_widget(self, w: QWidget) -> None:
        self.header.addWidget(w)

    def add(self, w, stretch: int = 0):
        if isinstance(w, QWidget):
            self.root.addWidget(w, stretch)
        else:
            self.root.addLayout(w, stretch)
        return w


class RingGauge(QWidget):
    """Medidor circular animado (0–100)."""

    def __init__(self, caption: str = "", color: str | None = None, size: int = 120, parent=None) -> None:
        super().__init__(parent)
        self.caption = caption
        self._color = color
        self._value = 0.0
        self._text = "0%"
        self._font_side = -1
        self._static: dict[tuple, QStaticText] = {}
        self.setMinimumSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        ThemeManager.instance().changed.connect(lambda _t: self.update())
        animations_on = Settings.instance().get("appearance.animations", True)
        self._animate = bool(animations_on)
        Settings.instance().changed.connect(self._on_setting)

    def _on_setting(self, key: str, value) -> None:
        if key == "appearance.animations":
            self._animate = bool(value)

    def _on_anim(self, v) -> None:
        self._value = float(v)
        self.update()

    def set_value(self, value: float, text: str | None = None) -> None:
        value = float(max(0.0, min(100.0, float(value or 0.0))))
        self._text = text if text is not None else f"{value:.0f}%"
        self._anim.stop()
        # Sem animação fora da tela ou para variações pequenas (economiza CPU).
        if not self._animate or not self.isVisible() or abs(value - self._value) < 1.5:
            self._value = value
            self.update()
            return
        # Os dois valores precisam ser float, senão o Qt não interpola.
        self._anim.setStartValue(float(self._value))
        self._anim.setEndValue(value)
        self._anim.start()

    def sizeHint(self) -> QSize:
        return QSize(130, 130)

    def paintEvent(self, _e) -> None:
        t: Theme = ThemeManager.instance().theme
        side = min(self.width(), self.height())
        pw = max(6.0, side * 0.085)
        rect = QRectF((self.width() - side) / 2 + pw, (self.height() - side) / 2 + pw,
                      side - 2 * pw, side - 2 * pw)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        track = QPen(t.color("faint"), pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        c = QColor(t.p["faint"])
        c.setAlpha(55)
        track.setColor(c)
        p.setPen(track)
        p.drawArc(rect, 225 * 16, -270 * 16)

        base = QColor(self._color or t.accent)
        grad = QConicalGradient(rect.center(), 225)
        grad.setColorAt(0.0, base)
        grad.setColorAt(0.75, QColor(t.accent2) if not self._color else base.lighter(130))
        pen = QPen(QBrush(grad), pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        span = -270 * self._value / 100.0
        if self._value > 0.3:
            p.drawArc(rect, 225 * 16, int(span * 16))

        # Textos: fontes e QStaticText em cache. Recriar a fonte a cada quadro da
        # animação custava ~3 ms por drawText e dominava o uso de CPU da janela.
        if self._font_side != side:
            self._font_side = side
            self._f_value = QFont("Segoe UI Variable Display")
            self._f_value.setPixelSize(max(12, int(side * 0.2)))
            self._f_value.setWeight(QFont.Weight.DemiBold)
            self._f_caption = QFont("Segoe UI")
            self._f_caption.setPixelSize(max(9, int(side * 0.085)))
            self._static.clear()
        mid = rect.center()
        p.setPen(t.color("text"))
        p.setFont(self._f_value)
        st = self._static_text(self._text, self._f_value)
        sz = st.size()
        p.drawStaticText(QPointF(mid.x() - sz.width() / 2, mid.y() - sz.height() / 2 - side * 0.04), st)
        if self.caption:
            p.setPen(t.color("muted"))
            p.setFont(self._f_caption)
            st = self._static_text(self.caption, self._f_caption)
            p.drawStaticText(QPointF(mid.x() - st.size().width() / 2, mid.y() + side * 0.11), st)
        p.end()

    def _static_text(self, text: str, font: QFont) -> QStaticText:
        key = (text, font.pixelSize())
        st = self._static.get(key)
        if st is None:
            if len(self._static) > 64:
                self._static.clear()
            st = QStaticText(text)
            st.prepare(font=font)
            self._static[key] = st
        return st


class LiveChart(pg.PlotWidget):
    """Gráfico de linhas com preenchimento em gradiente para dados em tempo real.

    ``series``: lista de (chave, rótulo, cor). ``y_max`` fixo (ex.: 100 para %) ou None
    para escala automática. ``y_fmt`` formata os valores do eixo Y.
    """

    def __init__(self, series: list[tuple[str, str, str]], y_max: float | None = 100,
                 show_axis: bool = False, y_fmt: Callable[[float], str] | None = None,
                 fill: bool = True, height: int | None = None, parent=None) -> None:
        super().__init__(parent=parent)
        self._y_max = y_max
        self._y_fmt = y_fmt
        self._show_axis = show_axis
        self.setBackground(None)
        self.setStyleSheet("background: transparent; border: none;")
        self.setMenuEnabled(False)
        self.setMouseEnabled(False, False)
        self.hideButtons()
        pi = self.getPlotItem()
        pi.hideAxis("bottom")
        pi.layout.setContentsMargins(0, 4, 0, 0)
        if not show_axis:
            pi.hideAxis("left")
        else:
            ax = pi.getAxis("left")
            ax.setWidth(54)
            if y_fmt:
                ax.tickStrings = lambda values, scale, spacing: [y_fmt(v) for v in values]
        if height:
            self.setFixedHeight(height)
        self.curves: dict[str, pg.PlotDataItem] = {}
        for key, _label, color in series:
            item = pg.PlotDataItem(pen=pg.mkPen(color, width=2))
            if fill:
                g = QLinearGradient(0, 0, 0, 1)
                g.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
                top = QColor(color)
                top.setAlpha(90 if len(series) == 1 else 45)
                bot = QColor(color)
                bot.setAlpha(0)
                g.setColorAt(0, top)
                g.setColorAt(1, bot)
                item.setFillLevel(0)
                item.setBrush(QBrush(g))
            self.addItem(item)
            self.curves[key] = item
        self._apply_theme(ThemeManager.instance().theme)
        ThemeManager.instance().changed.connect(self._apply_theme)

    def sizeHint(self) -> QSize:  # o padrão do pyqtgraph (640×480) é grande demais
        return QSize(240, max(self.minimumHeight(), 80))

    def _apply_theme(self, t: Theme) -> None:
        pi = self.getPlotItem()
        pi.showGrid(x=False, y=self._show_axis, alpha=0.12 if t.dark else 0.2)
        if self._show_axis:
            ax = pi.getAxis("left")
            ax.setPen(pg.mkPen(None))
            ax.setTextPen(pg.mkPen(t.p["muted"]))

    def set_data(self, data: dict[str, list[float]]) -> None:
        # A janela de tempo é fixa (capacidade do histórico); os pontos reais ficam
        # alinhados à direita e o gráfico "cresce" da direita para a esquerda.
        from .history import History
        cap = History.instance().size
        peak = 0.0
        for key, values in data.items():
            item = self.curves.get(key)
            if item is None or not values:
                continue
            values = list(values)[-cap:]
            start = cap - len(values)
            item.setData(list(range(start, cap)), values, connect="finite")
            finite = [v for v in values if v == v]
            if finite:
                peak = max(peak, max(finite))
        self.setXRange(0, cap - 1, padding=0)
        if self._y_max is not None:
            self.setYRange(0, self._y_max, padding=0.02)
        else:
            # escala "bonita" acima do pico para a linha não encostar no topo
            top = max(peak * 1.2, 1.0)
            mag = 10 ** math.floor(math.log10(top))
            top = math.ceil(top / mag) * mag
            self.setYRange(0, top, padding=0)


class MetricCard(GlassCard):
    """Cartão de métrica: valor grande, linhas de detalhe, barra e mini gráfico."""

    def __init__(self, title: str, glyph: str, color: str, chart_max: float | None = 100,
                 parent=None) -> None:
        super().__init__(title, glyph, parent)
        self.badge = label("", "Badge")
        self.badge.hide()
        self.add_header_widget(self.badge)

        row = QHBoxLayout()
        self.value = label("—", "BigValue")
        row.addWidget(self.value)
        row.addStretch(1)
        self.side = label("", "Muted")
        self.side.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.side)
        self.add(row)

        self.sub = label("", "Muted")
        self.add(self.sub)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.add(self.bar)
        self.chart = LiveChart([("v", title, color)], y_max=chart_max, height=58)
        self.add(self.chart)

    def update_values(self, value: str, sub: str = "", side: str = "", progress: float | None = None,
                      series: list[float] | None = None, badge: str | None = None) -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        self.side.setText(side)
        if progress is None:
            self.bar.hide()
        else:
            self.bar.show()
            self.bar.setValue(int(max(0, min(100, progress)) * 10))
        if series is not None:
            self.chart.set_data({"v": series})
        if badge:
            self.badge.setText(badge)
            self.badge.show()
        else:
            self.badge.hide()


class CoreBars(QWidget):
    """Barras verticais com o uso de cada núcleo lógico."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._values: list[float] = []
        self.setMinimumHeight(120)
        ThemeManager.instance().changed.connect(lambda _t: self.update())

    def set_values(self, values: Iterable[float]) -> None:
        self._values = list(values)
        self.update()

    def paintEvent(self, _e) -> None:
        if not self._values:
            return
        t = ThemeManager.instance().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self._values)
        gap = 6
        label_h = 16
        w = (self.width() - gap * (n - 1)) / n
        h = self.height() - label_h - 4
        track = QColor(t.p["faint"])
        track.setAlpha(40)
        f = QFont("Segoe UI")
        f.setPixelSize(10)
        p.setFont(f)
        for i, v in enumerate(self._values):
            x = i * (w + gap)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(track)
            p.drawRoundedRect(QRectF(x, 0, w, h), 4, 4)
            bh = h * max(0.0, min(100.0, v)) / 100
            if bh > 1:
                g = QLinearGradient(0, h - bh, 0, h)
                hot = QColor("#fb7185") if v > 85 else QColor(t.accent)
                g.setColorAt(0, hot)
                g.setColorAt(1, QColor(t.accent2))
                p.setBrush(QBrush(g))
                p.drawRoundedRect(QRectF(x, h - bh, w, bh), 4, 4)
            p.setPen(t.color("muted"))
            p.drawText(QRectF(x - 4, h + 2, w + 8, label_h), Qt.AlignmentFlag.AlignCenter, f"{v:.0f}")
        p.end()


class ResponsiveGrid(QWidget):
    """Grade que reorganiza as colunas conforme a largura da janela (layout responsivo)."""

    def __init__(self, min_col_width: int = 300, max_cols: int = 4, spacing: int = 14, parent=None) -> None:
        super().__init__(parent)
        self.min_w = min_col_width
        self.max_cols = max_cols
        self._items: list[tuple[QWidget, int]] = []
        self._cols = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)

    def add(self, w: W, span: int = 1) -> W:
        self._items.append((w, span))
        self._relayout(force=True)
        return w

    def clear(self) -> None:
        """Remove (e destrói) todos os itens."""
        for w, _ in self._items:
            self.grid.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._items.clear()
        self._cols = 0

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._relayout()

    def _relayout(self, force: bool = False) -> None:
        # A coluna nunca é mais estreita que o maior mínimo real dos itens (senão a página
        # estoura a largura e o conteúdo é cortado à direita).
        child_min = max((w.minimumSizeHint().width() for w, span in self._items if span == 1), default=0)
        col_w = max(self.min_w, child_min + self.grid.spacing())
        cols = max(1, min(self.max_cols, (self.width() + self.grid.spacing()) // col_w
                          if self.width() > 0 else self.max_cols))
        if cols == self._cols and not force:
            return
        self._cols = cols
        for w, _ in self._items:
            self.grid.removeWidget(w)
        for c in range(self.max_cols):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)
        r = c = 0
        for w, span in self._items:
            span = min(span, cols)
            if c + span > cols:
                r, c = r + 1, 0
            self.grid.addWidget(w, r, c, 1, span)
            c += span
            if c >= cols:
                r, c = r + 1, 0


class Segmented(QWidget):
    """Grupo de botões exclusivos (ex.: 1h | 24h | 7d)."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str | None = None, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for key, text in options:
            b = QPushButton(text)
            b.setObjectName("Segment")
            b.setCheckable(True)
            # pode encolher um pouco em janelas estreitas (evita estourar a largura da página)
            b.setMinimumWidth(b.fontMetrics().horizontalAdvance(text) + 16)
            b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("key", key)
            self._group.addButton(b)
            lay.addWidget(b)
            if key == (current or options[0][0]):
                b.setChecked(True)
        self._group.buttonClicked.connect(lambda b: self.changed.emit(b.property("key")))

    def set_current(self, key: str) -> None:
        for b in self._group.buttons():
            if b.property("key") == key:
                b.setChecked(True)

    def current(self) -> str:
        b = self._group.checkedButton()
        return b.property("key") if b else ""


class ToggleSwitch(QCheckBox):
    """Interruptor liga/desliga animado (mesma API de um QCheckBox)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 24)
        self._pos = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate)
        ThemeManager.instance().changed.connect(lambda _t: self.update())

    def _on_anim(self, v) -> None:
        self._pos = float(v)
        self.update()

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(float(self._pos))
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on: bool) -> None:  # noqa: N802 (API do Qt)
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, _e) -> None:
        t = ThemeManager.instance().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off = QColor(t.p["faint"])
        off.setAlpha(90)
        if self._pos > 0:
            g = QLinearGradient(r.topLeft(), r.topRight())
            a1, a2 = QColor(t.accent), QColor(t.accent2)
            a1.setAlphaF(0.35 + 0.65 * self._pos)
            a2.setAlphaF(0.35 + 0.65 * self._pos)
            g.setColorAt(0, a1)
            g.setColorAt(1, a2)
            p.setBrush(QBrush(g) if self._pos > 0.5 else off)
        else:
            p.setBrush(off)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._pos
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        p.end()


class DataTable(QTableWidget):
    """Tabela simples, somente leitura, com atualização eficiente."""

    def __init__(self, headers: list[str], stretch_col: int = 0, parent=None) -> None:
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().hide()
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.verticalHeader().setDefaultSectionSize(30)
        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        for i in range(len(headers)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i == stretch_col else QHeaderView.ResizeMode.ResizeToContents)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def set_rows(self, rows: list[list[str]], align_right_from: int = 1) -> None:
        self.setUpdatesEnabled(False)
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = self.item(r, c)
                if item is None:
                    item = QTableWidgetItem()
                    self.setItem(r, c, item)
                item.setText(str(text))
                if c >= align_right_from:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setUpdatesEnabled(True)


def stat_block(title: str, value: str = "—") -> tuple[QWidget, QLabel]:
    """Bloco 'título pequeno + valor' usado nas grades de detalhes."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lay.addWidget(label(title, "Faint"))
    v = label(value, "Value")
    lay.addWidget(v)
    return w, v


def legend(items: list[tuple[str, str]]) -> QWidget:
    """Legenda horizontal: [(rótulo, cor)]."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(14)
    for text, color in items:
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 11pt;")
        lay.addWidget(dot)
        lay.addSpacing(-10)
        lay.addWidget(label(text, "Muted"))
    lay.addStretch(1)
    return w
