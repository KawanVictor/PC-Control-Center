"""Download e upload."""
from __future__ import annotations

from PySide6.QtGui import QColor

from ...ui.icons import G
from ..base import Canvas, Renderer, fmt_rate_short
from ._common import hub, no_data


# ===================================================================== 9. Download/Upload
class NetSpeedWidget(Renderer):
    type_id, title, glyph = "netspeed", "Download e upload", G.DOWN
    description = "Velocidade da rede em tempo real com gráfico."
    base_size = (250, 118)
    defaults = {"bits": True}

    def draw(self, c: Canvas) -> None:
        n = hub().net
        if not n:
            no_data(c)
            return
        down_c, up_c = QColor("#38bdf8"), QColor("#f472b6")
        c.text(14, 8, 110, 16, "↓ Download", 10.5, 600, color=down_c)
        c.text(126, 8, 110, 16, "↑ Upload", 10.5, 600, color=up_c)
        c.text(14, 22, 110, 30, fmt_rate_short(n.down_bps, self.opt["bits"]), 19, 600)
        c.text(126, 22, 110, 30, fmt_rate_short(n.up_bps, self.opt["bits"]), 19, 600)
        h = hub().hist
        top = max(max(h["down"], default=1), max(h["up"], default=1), 1024) * 1.15
        c.spark(14, 60, 222, 50, h["down"], down_c, vmax=top)
        c.spark(14, 60, 222, 50, h["up"], up_c, vmax=top, fill=False)
