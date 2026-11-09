"""Monitor de GPU."""
from __future__ import annotations

from ...ui.fmt import fmt_bytes
from ...ui.icons import G
from ._common import RingWidget, hub


class GpuWidget(RingWidget):
    type_id, title, glyph, label, hist_key = "gpu", "Monitor de GPU", G.GPU, "GPU", "gpu"
    description = "Uso da placa de vídeo, VRAM e temperatura."

    def values(self):
        s = hub().sys
        g = s.primary_gpu if s else None
        if not g:
            return None
        name = g.name.replace("(TM)", "").replace("(R)", "").replace("Graphics", "").strip()
        return g.percent, [name[:22], f"VRAM {fmt_bytes(g.dedicated_used, 0)} / {fmt_bytes(g.dedicated_total, 0)}",
                           f"{g.temperature:.0f} °C" if g.temperature is not None else "Temp. N/D"]
