"""Constantes e auxiliares usados por vários tipos de widget."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from ..base import Canvas, Renderer
from ..hub import DataHub


MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]
DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
DIAS_CURTOS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
GREEN, AMBER, RED = QColor("#34d399"), QColor("#fbbf24"), QColor("#fb7185")


def heat(v: float | None, warn: float, hot: float) -> QColor:
    if v is None:
        return QColor("#94a3b8")
    return GREEN if v < warn else AMBER if v < hot else RED


def hub() -> DataHub:
    return DataHub.instance()


def no_data(c: Canvas, msg: str = "Aguardando dados...") -> None:
    c.text(0, 0, c.w, c.h, msg, 12, color=c.s.muted, align=Qt.AlignmentFlag.AlignCenter)


# ======================================================== 4–6. CPU / RAM / GPU (anel + gráfico)
class RingWidget(Renderer):
    base_size = (250, 128)
    label = ""
    hist_key = ""
    color: QColor | None = None

    def values(self) -> tuple[float, list[str]] | None:
        raise NotImplementedError

    def draw(self, c: Canvas) -> None:
        v = self.values()
        if v is None:
            no_data(c)
            return
        pct, lines = v
        c.ring(56, 62, 40, pct, 8)
        c.text(16, 42, 80, 30, f"{pct:.0f}%", 20, 600, align=Qt.AlignmentFlag.AlignCenter)
        c.text(16, 66, 80, 18, self.label, 10.5, 600, color=c.s.muted, align=Qt.AlignmentFlag.AlignCenter)
        for i, line in enumerate(lines[:3]):
            c.text(110, 16 + i * 20, 130, 20, line, 12 if i else 13.5, 600 if i == 0 else 400,
                   color=c.s.text if i == 0 else c.s.muted)
        c.spark(110, 80, 126, 36, hub().hist[self.hist_key], vmax=100)
