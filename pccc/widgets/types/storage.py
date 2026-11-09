"""Monitor de armazenamento."""
from __future__ import annotations

from PySide6.QtCore import Qt

from ...ui.fmt import fmt_bytes
from ...ui.icons import G
from ..base import Canvas, Renderer, fmt_rate_short
from ._common import AMBER, RED, hub, no_data


# ========================================================================= 10. Armazenamento
class StorageWidget(Renderer):
    type_id, title, glyph = "storage", "Monitor de armazenamento", G.DISK
    description = "Espaço livre de cada unidade e atividade do disco."
    base_size = (260, 150)

    def draw(self, c: Canvas) -> None:
        s = hub().sys
        if not s or not s.partitions:
            no_data(c)
            return
        c.glyph(12, 8, 22, 22, G.DISK, 12)
        c.text(36, 8, 120, 22, "Armazenamento", 12.5, 600)
        c.text(150, 8, 96, 22, f"↓{fmt_rate_short(s.disk_io.read_bps, False)}", 9.5, color=c.s.muted,
               align=Qt.AlignRight | Qt.AlignVCenter)
        parts = s.partitions[:3]
        for i, p in enumerate(parts):
            y = 36 + i * 36
            col = RED if p.percent >= 90 else AMBER if p.percent >= 80 else None
            c.text(14, y, 140, 16, f"{p.label or 'Disco'} ({p.mount.rstrip(chr(92))})", 11.5, 600)
            c.text(120, y, 126, 16, f"{fmt_bytes(p.free)} livres", 10.5, color=c.s.muted,
                   align=Qt.AlignRight | Qt.AlignVCenter)
            c.bar(14, y + 20, 232, 6, p.percent, col)
