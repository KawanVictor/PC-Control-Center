"""Ícones: glifos da fonte nativa do Windows (Segoe Fluent Icons / MDL2) e o ícone do app.

Usar a fonte do sistema dispensa arquivos de imagem e mantém o visual do Windows 11.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap)


class G:
    """Códigos dos glifos (comuns ao Segoe MDL2 Assets e Segoe Fluent Icons)."""
    HOME = ""
    PERFORMANCE = ""
    CPU = ""
    MEMORY = ""
    GPU = ""
    DISK = ""
    NETWORK = ""
    APPS = ""
    WIDGETS = ""
    PERSONALIZE = ""
    ALERTS = ""
    TOOLS = ""
    SETTINGS = ""
    TEMP = ""
    CLOCK = ""
    UP = ""
    DOWN = ""
    INFO = ""
    SHIELD = ""
    MENU = ""
    REFRESH = ""
    FOLDER = ""
    TERMINAL = ""
    TASKS = ""
    DEVICES = ""
    SERVICES = ""
    HISTORY = ""
    LIST = ""
    POWER = ""
    CHECK = ""
    WARNING = ""
    PROCESS = ""
    # Fase 9 (mídia e cenários)
    MEDIA = ""        # áudio
    VOLUME = ""
    VIDEO = ""
    GAME = ""
    SCENES = ""       # camadas
    SUN = ""
    MOON = ""
    IMAGE = ""
    KEYBOARD = ""
    EXPORT = ""
    BRIGHTNESS = ""


def make_app_icon(c1: str = "#22d3ee", c2: str = "#6366f1") -> QIcon:
    """Desenha o ícone do app: quadrado arredondado com gradiente e um 'pulso' de monitor."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, size, size).adjusted(size * .04, size * .04, -size * .04, -size * .04)
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0, QColor(c1))
        grad.setColorAt(1, QColor(c2))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(r, size * .24, size * .24)

        pen = QPen(QColor("white"), max(1.4, size * .085), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        s = size
        path = QPainterPath(QPointF(s * .20, s * .55))
        for x, y in ((.36, .55), (.45, .30), (.56, .74), (.64, .48), (.80, .48)):
            path.lineTo(QPointF(s * x, s * y))
        p.drawPath(path)
        p.end()
        icon.addPixmap(pm)
    return icon
