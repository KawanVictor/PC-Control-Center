"""Informações do sistema."""
from __future__ import annotations

import platform

from ...ui.fmt import fmt_bytes, fmt_uptime
from ...ui.icons import G
from ..base import Canvas, Renderer
from ._common import hub, no_data


# ==================================================================== 12. Info do sistema
class SysInfoWidget(Renderer):
    type_id, title, glyph = "sysinfo", "Informações do sistema", G.INFO
    description = "Computador, Windows, processador, GPU, memória e tempo ligado."
    base_size = (300, 160)
    default_refresh = 5000

    def draw(self, c: Canvas) -> None:
        s = hub().sys
        if not s:
            no_data(c)
            return
        from ...monitoring.system import windows_version
        if not hasattr(self, "_os"):
            self._os = windows_version().split(" (")[0]
        g = s.primary_gpu
        c.text(14, 8, 272, 24, platform.node(), 16, 600)
        rows = [("Sistema", self._os), ("CPU", s.cpu.name.replace("with Radeon Graphics", "").strip()),
                ("GPU", g.name if g else "—"), ("Memória", f"{fmt_bytes(s.memory.total, 0)}"),
                ("Ligado há", fmt_uptime(s.uptime_s))]
        for i, (k, v) in enumerate(rows):
            y = 36 + i * 23
            c.text(14, y, 70, 20, k, 11, color=c.s.muted)
            c.text(84, y, 204, 20, v, 11.5, 500)
