"""Calendário do mês com feriados nacionais."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor

from ..base import Canvas, Renderer
from ._common import MESES, RED


# =========================================================================== 2. Calendário
def _easter(y: int) -> date:
    a, b, cc = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = cc // 4, cc % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def br_holidays(y: int) -> dict[date, str]:
    """Feriados nacionais do Brasil (fixos + móveis)."""
    e = _easter(y)
    h = {date(y, 1, 1): "Confraternização Universal", date(y, 4, 21): "Tiradentes",
         date(y, 5, 1): "Dia do Trabalho", date(y, 9, 7): "Independência", date(y, 10, 12): "Nossa Senhora Aparecida",
         date(y, 11, 2): "Finados", date(y, 11, 15): "Proclamação da República",
         date(y, 11, 20): "Consciência Negra", date(y, 12, 25): "Natal",
         e - timedelta(days=47): "Carnaval", e - timedelta(days=48): "Carnaval",
         e - timedelta(days=2): "Sexta-feira Santa", e: "Páscoa", e + timedelta(days=60): "Corpus Christi"}
    return h


class CalendarWidget(Renderer):
    type_id, title, glyph = "calendar", "Calendário", ""
    description = "Mês atual com destaque para hoje e feriados nacionais."
    base_size = (262, 252)
    default_refresh = 60_000
    defaults = {"holidays": True, "week_start": "dom"}

    def __init__(self, cfg):
        super().__init__(cfg)
        self.offset = 0  # navegação de meses (não é salva)

    def _month(self) -> tuple[int, int]:
        t = date.today()
        m = t.month - 1 + self.offset
        return t.year + m // 12, m % 12 + 1

    def draw(self, c: Canvas) -> None:
        y, m = self._month()
        today = date.today()
        c.text(16, 10, 180, 26, f"{MESES[m - 1].capitalize()} {y}", 17, 600)
        c.glyph(200, 10, 24, 26, "", 11, c.s.muted)   # anterior
        c.glyph(228, 10, 24, 26, "", 11, c.s.muted)   # próximo
        sun_first = self.opt["week_start"] == "dom"
        heads = ["D", "S", "T", "Q", "Q", "S", "S"] if sun_first else ["S", "T", "Q", "Q", "S", "S", "D"]
        cw, x0, top = 33, 15, 44
        for i, hd in enumerate(heads):
            c.text(x0 + i * cw, top, cw, 18, hd, 11, 600, color=c.s.muted, align=Qt.AlignCenter)
        cal = calendar.Calendar(firstweekday=6 if sun_first else 0)
        hol = br_holidays(y) if self.opt["holidays"] else {}
        for r, week in enumerate(cal.monthdatescalendar(y, m)):
            for i, d in enumerate(week):
                cx, cy = x0 + i * cw, top + 22 + r * 30
                if d == today:
                    c.rounded(cx + 3, cy + 1, cw - 6, 26, 13, c.s.accent)
                color = c.s.text if d.month == m else c.s.faint
                if d == today:
                    color = QColor("#0b1020")
                elif d in hol and d.month == m:
                    color = RED
                c.text(cx, cy, cw, 28, str(d.day), 12.5, 600 if d == today else 400, color=color,
                       align=Qt.AlignCenter)
        nxt = sorted((d, n) for d, n in hol.items() if d.month == m and d >= today)
        if nxt and self.offset == 0:
            d, n = nxt[0]
            c.text(16, 226, 240, 20, f"● {d.day:02d}/{d.month:02d} — {n}", 10.5, color=RED)

    def hit_areas(self):
        return [(QRectF(200, 10, 24, 26), "prev"), (QRectF(228, 10, 24, 26), "next"),
                (QRectF(16, 10, 170, 26), "today")]

    def on_click(self, area_id: str) -> None:
        self.offset += {"prev": -1, "next": 1}.get(area_id, -self.offset)
