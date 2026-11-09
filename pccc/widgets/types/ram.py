"""Monitor de RAM."""
from __future__ import annotations

from ...ui.fmt import fmt_bytes
from ...ui.icons import G
from ._common import RingWidget, hub


class RamWidget(RingWidget):
    type_id, title, glyph, label, hist_key = "ram", "Monitor de RAM", G.MEMORY, "RAM", "ram"
    description = "Memória em uso, disponível e histórico."

    def values(self):
        s = hub().sys
        if not s:
            return None
        m = s.memory
        return m.percent, [f"{fmt_bytes(m.used)} / {fmt_bytes(m.total)}", f"{fmt_bytes(m.available)} livre",
                           f"Virtual {fmt_bytes(m.commit_used, 0)}"]
