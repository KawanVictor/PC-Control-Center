"""Clima atual e previsão de 4 dias."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt

from .. import weather as wx
from ..base import Canvas, Renderer
from ._common import DIAS_CURTOS, hub, no_data


# ================================================================================ 3. Clima
class WeatherWidget(Renderer):
    type_id, title, glyph = "weather", "Clima", ""
    description = "Tempo agora e previsão de 4 dias (Open-Meteo, sem cadastro)."
    base_size = (292, 160)
    default_refresh = 30_000
    defaults = {"city": "São Paulo", "lat": -23.5475, "lon": -46.63611, "label": "São Paulo, São Paulo"}

    def draw(self, c: Canvas) -> None:
        o = self.opt
        if o.get("lat") is None:
            no_data(c, "Configure a cidade (botão direito → Configurar)")
            return
        data, err = hub().weather(o["lat"], o["lon"])
        c.text(16, 8, 260, 20, o.get("label") or o.get("city", ""), 12, 600, color=c.s.muted)
        if not data:
            no_data(c, "Sem conexão com o serviço de clima" if err else "Carregando clima...")
            return
        cur = data["current"]
        desc, emoji = wx.describe(cur.get("weather_code"), bool(cur.get("is_day", 1)))
        c.text(12, 26, 64, 60, emoji, 40, family="Segoe UI Emoji", align=Qt.AlignmentFlag.AlignCenter)
        c.text(80, 24, 110, 46, f"{cur['temperature_2m']:.0f}°", 40, 600)
        c.text(80, 66, 200, 18, desc, 12, 500, color=c.s.muted)
        c.text(180, 30, 100, 16, f"Sensação {cur['apparent_temperature']:.0f}°", 10.5, color=c.s.muted,
               align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        c.text(180, 46, 100, 16, f"Umidade {cur['relative_humidity_2m']}%", 10.5, color=c.s.muted,
               align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        c.text(180, 62, 100, 16, f"Vento {cur['wind_speed_10m']:.0f} km/h", 10.5, color=c.s.muted,
               align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        d = data["daily"]
        for i in range(1, min(5, len(d["time"]))):
            x = 14 + (i - 1) * 68
            dt = date.fromisoformat(d["time"][i])
            _desc, em = wx.describe(d["weather_code"][i])
            c.text(x, 92, 62, 16, DIAS_CURTOS[dt.weekday()], 10.5, 600, color=c.s.muted, align=Qt.AlignmentFlag.AlignCenter)
            c.text(x, 106, 62, 24, em, 15, family="Segoe UI Emoji", align=Qt.AlignmentFlag.AlignCenter)
            c.text(x, 130, 62, 16, f"{d['temperature_2m_max'][i]:.0f}° / {d['temperature_2m_min'][i]:.0f}°",
                   10.5, align=Qt.AlignmentFlag.AlignCenter)
            pp = (d.get("precipitation_probability_max") or [None] * 9)[i]
            if pp:
                c.text(x, 144, 62, 14, f"💧{pp}%", 9, color=c.s.muted, align=Qt.AlignmentFlag.AlignCenter)
