"""Monitor de processos."""
from __future__ import annotations

from PySide6.QtCore import Qt

from ...ui.fmt import fmt_bytes
from ...ui.icons import G
from ..base import Canvas, Renderer
from ._common import hub, no_data


# ================================================================ 15. Monitor de processos
class ProcessWidget(Renderer):
    type_id, title, glyph = "processes", "Monitor de processos", G.PROCESS
    description = "Os 5 aplicativos que mais usam CPU ou memória agora."
    base_size = (262, 168)
    default_refresh = 2000
    defaults = {"sort": "cpu"}

    def draw(self, c: Canvas) -> None:
        s = hub().sys
        if not s or not s.processes.apps:
            no_data(c)
            return
        by_cpu = self.opt["sort"] == "cpu"
        apps = sorted(s.processes.apps, key=lambda a: a.cpu if by_cpu else a.memory, reverse=True)[:5]
        c.glyph(12, 8, 22, 22, G.PROCESS, 12)
        c.text(36, 8, 220, 22, "Processos · " + ("CPU" if by_cpu else "Memória"), 12.5, 600)
        top = max((a.cpu if by_cpu else a.memory) for a in apps) or 1
        for i, a in enumerate(apps):
            y = 36 + i * 26
            val = a.cpu if by_cpu else a.memory
            c.text(14, y, 150, 16, a.name.replace(".exe", "")[:20], 11.5)
            c.text(160, y, 88, 16, f"{a.cpu:.1f}%".replace(".", ",") if by_cpu else fmt_bytes(a.memory), 11, 600,
                   align=Qt.AlignRight | Qt.AlignVCenter)
            c.bar(14, y + 17, 234, 3.5, (val / top * 100) if by_cpu and top < 100 else (val / top * 100))
