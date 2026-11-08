"""Janela de um widget na área de trabalho.

* Sem borda, fundo translúcido, fora da barra de tarefas e do Alt+Tab, nunca rouba o foco.
* Arrastar com o botão esquerdo (encaixa nas bordas da tela e em outros widgets).
* Redimensionar pelo canto inferior direito (mantém a proporção; o desenho é vetorial).
* Botão direito: configurar, bloquear, camada, ocultar, remover.
"""
from __future__ import annotations

import ctypes

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

from ..core.logger import get_logger
from .base import Canvas, Renderer, Style, WidgetConfig

log = get_logger("widgets.window")

GRIP = 16          # tamanho da alça de redimensionar (px de tela)
SNAP = 12          # distância de encaixe (px)
MIN_SCALE, MAX_SCALE = 0.5, 3.0

HWND_BOTTOM, HWND_TOP = 1, 0
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10


def paint_widget(p: QPainter, renderer: Renderer, cfg: WidgetConfig, w: float, h: float,
                 style: Style | None = None, hover: bool = False) -> None:
    """Desenha fundo + conteúdo de um widget no retângulo (0,0,w,h). Usado também na galeria."""
    bw, bh = renderer.base_size
    s = w / bw
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.save()
    p.scale(s, s)
    bg = QColor(cfg.bg or "#0b1020")
    bg.setAlphaF(max(0.0, min(1.0, cfg.bg_opacity)))
    p.setPen(QPen(QColor(255, 255, 255, 38 if hover else 20), 1 / s))
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(0.5, 0.5, bw - 1, bh - 1), 16, 16)
    renderer.draw(Canvas(p, style or Style(cfg), bw, bh))
    p.restore()


class DesktopWidgetWindow(QWidget):
    changed = Signal(object)            # cfg alterada (posição/tamanho/opções) → salvar
    action = Signal(str, object)        # configure | hide | remove | open_app

    def __init__(self, renderer: Renderer, peers=None) -> None:
        super().__init__(None)
        self.renderer = renderer
        self.cfg = renderer.cfg
        self._peers = peers or (lambda: [])
        self._style = Style(self.cfg)
        self._drag: QPoint | None = None
        self._resizing = False
        self._pressed_area: str | None = None
        self._hover = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self.apply_layer(show=False)
        self.apply_geometry()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self.apply_refresh()

    # ------------------------------------------------------------ configuração
    def apply_layer(self, show: bool = True) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint
        if self.cfg.layer == "top":
            flags |= Qt.WindowType.WindowStaysOnTopHint
        elif self.cfg.layer == "bottom":
            flags |= Qt.WindowType.WindowStaysOnBottomHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if show and (was_visible or self.cfg.visible):
            self.show()

    def apply_geometry(self) -> None:
        bw, bh = self.renderer.base_size
        w = self.cfg.width or bw
        w = int(max(bw * MIN_SCALE, min(bw * MAX_SCALE, w)))
        self.cfg.width = w
        self.setFixedSize(w, int(round(w * bh / bw)))
        self.move(self.cfg.x, self.cfg.y)

    def apply_refresh(self) -> None:
        ms = int(self.cfg.refresh_ms or 1000)
        if self.renderer.type_id == "clock":
            ms = min(ms, 1000)
        if self.renderer.min_refresh < 250:          # animação contínua (visualizador)
            ms = self.renderer.default_refresh
        self._timer.start(max(self.renderer.min_refresh, ms))

    def restyle(self) -> None:
        self._style = Style(self.cfg)
        self.apply_geometry()
        self.apply_refresh()
        self.update()

    def sink(self) -> None:
        """Mantém widgets da camada 'atrás' abaixo das janelas normais."""
        if self.cfg.layer == "bottom" and self.isVisible():
            ctypes.windll.user32.SetWindowPos(int(self.winId()), HWND_BOTTOM, 0, 0, 0, 0,
                                              SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

    def surface(self) -> None:
        """Traz para cima sem ativar (usado quando a área de trabalho fica em primeiro plano)."""
        if self.isVisible():
            ctypes.windll.user32.SetWindowPos(int(self.winId()), HWND_TOP, 0, 0, 0, 0,
                                              SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

    # ------------------------------------------------------------------ pintura
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        try:
            paint_widget(p, self.renderer, self.cfg, self.width(), self.height(), self._style, self._hover)
            if self._hover and not self.cfg.locked:
                c = QColor(self._style.text)
                c.setAlpha(120)
                p.setPen(QPen(c, 1.5))
                w, h = self.width(), self.height()
                for i in (4, 8, 12):  # alça de redimensionar
                    p.drawLine(QPointF(w - i - 3, h - 3), QPointF(w - 3, h - i - 3))
        except Exception:
            log.exception("Erro ao desenhar widget %s", self.cfg.type)
        finally:
            p.end()

    # -------------------------------------------------------------------- mouse
    def _to_base(self, pos) -> QPointF:
        bw, _bh = self.renderer.base_size
        s = self.width() / bw
        return QPointF(pos.x() / s, pos.y() / s)

    def _area_at(self, pos) -> str | None:
        pt = self._to_base(pos)
        for rect, aid in self.renderer.hit_areas():
            if rect.contains(pt):
                return aid
        return None

    def _in_grip(self, pos) -> bool:
        return not self.cfg.locked and pos.x() > self.width() - GRIP and pos.y() > self.height() - GRIP

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()
        if self._in_grip(pos):
            self._resizing = True
            return
        self._pressed_area = self._area_at(pos)
        if self._pressed_area is None and not self.cfg.locked:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        pos = e.position().toPoint()
        if self._resizing:
            bw, _ = self.renderer.base_size
            new_w = max(bw * MIN_SCALE, min(bw * MAX_SCALE, pos.x()))
            self.cfg.width = int(new_w)
            self.apply_geometry()
            self.update()
            return
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            target = e.globalPosition().toPoint() - self._drag
            self.move(self._snap(target))
            return
        if self._in_grip(pos):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif self._area_at(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif not self.cfg.locked:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._resizing or self._drag is not None:
            self.cfg.x, self.cfg.y = self.x(), self.y()
            self.changed.emit(self.cfg)
        elif self._pressed_area and self._pressed_area == self._area_at(e.position().toPoint()):
            try:
                self.renderer.on_click(self._pressed_area)
            except Exception:
                log.exception("Erro na ação do widget")
            self.update()
            if self.renderer.type_id == "calendar":
                pass
        self._resizing = False
        self._drag = None
        self._pressed_area = None

    def mouseDoubleClickEvent(self, e) -> None:
        if self._area_at(e.position().toPoint()) is None:
            self.action.emit("configure", self)

    def enterEvent(self, _e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = False
        self.update()

    def wheelEvent(self, e) -> None:
        # Ctrl + roda do mouse = redimensionar rapidamente
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier and not self.cfg.locked:
            bw, _ = self.renderer.base_size
            step = 1.08 if e.angleDelta().y() > 0 else 1 / 1.08
            self.cfg.width = int(max(bw * MIN_SCALE, min(bw * MAX_SCALE, self.width() * step)))
            self.apply_geometry()
            self.changed.emit(self.cfg)

    # ------------------------------------------------------------------ encaixe
    def _snap(self, pt: QPoint) -> QPoint:
        x, y, w, h = pt.x(), pt.y(), self.width(), self.height()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        xs = [area.left(), area.right() + 1]
        ys = [area.top(), area.bottom() + 1]
        for other in self._peers():
            if other is self or not other.isVisible():
                continue
            g = other.geometry()
            xs += [g.left() - 8, g.right() + 1 + 8, g.left(), g.right() + 1]
            ys += [g.top() - 8, g.bottom() + 1 + 8, g.top(), g.bottom() + 1]
        for edge in xs:
            if abs(x - edge) < SNAP:
                x = edge
            elif abs(x + w - edge) < SNAP:
                x = edge - w
        for edge in ys:
            if abs(y - edge) < SNAP:
                y = edge
            elif abs(y + h - edge) < SNAP:
                y = edge - h
        return QPoint(x, y)

    # -------------------------------------------------------------------- menu
    def contextMenuEvent(self, e) -> None:
        m = QMenu(self)
        m.addAction("Configurar...", lambda: self.action.emit("configure", self))
        lock = m.addAction("Bloquear posição e tamanho")
        lock.setCheckable(True)
        lock.setChecked(self.cfg.locked)
        lock.toggled.connect(self._set_locked)
        layer = m.addMenu("Camada")
        for key, text in (("bottom", "Na área de trabalho (atrás das janelas)"), ("normal", "Normal"),
                          ("top", "Sempre visível (acima de tudo)")):
            a = layer.addAction(text)
            a.setCheckable(True)
            a.setChecked(self.cfg.layer == key)
            a.triggered.connect(lambda _=False, k=key: self._set_layer(k))
        m.addSeparator()
        m.addAction("Ocultar", lambda: self.action.emit("hide", self))
        m.addAction("Remover widget", lambda: self.action.emit("remove", self))
        m.addSeparator()
        m.addAction("Abrir PC Control Center", lambda: self.action.emit("open_app", self))
        m.exec(e.globalPos())

    def _set_locked(self, v: bool) -> None:
        self.cfg.locked = v
        self.changed.emit(self.cfg)
        self.update()

    def _set_layer(self, layer: str) -> None:
        self.cfg.layer = layer
        self.apply_layer()
        self.changed.emit(self.cfg)

    def event(self, e):
        if e.type() == e.Type.ToolTip:
            tip = self.renderer.tooltip()
            if tip:
                QToolTip.showText(e.globalPos(), tip, self)
            return True
        return super().event(e)
