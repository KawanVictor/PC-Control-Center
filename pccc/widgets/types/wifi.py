"""Monitor de Wi-Fi."""
from __future__ import annotations

from PySide6.QtCore import Qt

from ...ui.icons import G
from ..base import Canvas, Renderer
from ._common import AMBER, GREEN, RED, hub, no_data


# ================================================================================ 8. Wi-Fi
class WifiWidget(Renderer):
    type_id, title, glyph = "wifi", "Monitor de Wi-Fi", G.NETWORK
    description = "Rede conectada, intensidade do sinal, banda e ping."
    base_size = (250, 112)

    def draw(self, c: Canvas) -> None:
        n = hub().net
        if not n:
            no_data(c)
            return
        w = n.wifi
        bars = 0 if not w.connected else 1 + min(3, w.signal // 25)
        for i in range(4):
            h = 10 + i * 9
            col = c.s.accent if i < bars else c.s.faint
            c.rounded(18 + i * 11, 64 - h, 7, h, 2, col)
        if w.connected:
            c.text(70, 12, 172, 24, w.ssid or "(rede oculta)", 15, 600)
            c.text(70, 36, 172, 18, f"Sinal {w.signal}% · {w.rssi} dBm" if w.rssi is not None else f"Sinal {w.signal}%",
                   11.5, color=c.s.muted)
            c.text(18, 74, 230, 18, f"{w.band} · canal {w.channel} · {w.standard.split(' (')[0]}", 11,
                   color=c.s.muted)
        else:
            name = n.active.name if n.active else "Sem conexão"
            c.text(70, 12, 172, 24, "Wi-Fi desconectado" if w.available else name, 14, 600)
        p = n.ping_internet.last_ms
        status = {"online": ("Online", GREEN), "no_internet": ("Sem internet", AMBER),
                  "offline": ("Offline", RED)}.get(n.status, ("—", c.s.muted))
        c.text(18, 90, 120, 18, f"● {status[0]}", 11, 600, color=status[1])
        c.text(130, 90, 110, 18, f"Ping {p:.0f} ms" if p is not None else "Ping —", 11, color=c.s.muted,
               align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
