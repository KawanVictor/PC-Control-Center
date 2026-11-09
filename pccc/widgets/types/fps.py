"""Contador de FPS."""
from __future__ import annotations

from PySide6.QtCore import Qt

from ..base import Canvas, Renderer
from ._common import AMBER, GREEN, RED


# ========================================================================= 20. FPS
class FpsWidget(Renderer):
    type_id, title, glyph = "fps", "Contador de FPS", ""
    description = "FPS do jogo em foco, 1% mínimo e gráfico. Use a camada 'Sempre visível'."
    base_size = (220, 112)
    default_refresh = 500

    def draw(self, c: Canvas) -> None:
        from ...media.fps import FpsMonitor
        game, st = FpsMonitor.instance().current()
        if not st.get("running"):
            c.glyph(12, 8, 22, 22, "", 12)
            c.text(36, 8, 170, 22, "FPS", 12.5, 600)
            msg = "Iniciando..." if st.get("starting") else (st.get("error") or "Ligue em Mídia → FPS")
            c.text(14, 36, 192, 64, msg, 10.5, color=c.s.muted, align=Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)
            return
        if game is None:
            c.text(14, 10, 192, 30, "FPS", 12.5, 600)
            c.text(14, 40, 192, 40, "Abra um jogo...", 13, color=c.s.muted)
            return
        fps = game["fps"]
        col = GREEN if fps >= 55 else AMBER if fps >= 30 else RED
        c.text(12, 2, 120, 56, f"{fps:.0f}", 44, 700, col)
        c.text(120, 10, 90, 16, "FPS", 11, 600, color=c.s.muted, align=Qt.AlignRight | Qt.AlignVCenter)
        c.text(110, 26, 100, 16, f"1% mín {game['low1']:.0f}", 10.5, align=Qt.AlignRight | Qt.AlignVCenter)
        c.text(110, 42, 100, 16, f"{game['frame_ms']:.1f} ms".replace(".", ","), 10.5, color=c.s.muted,
               align=Qt.AlignRight | Qt.AlignVCenter)
        c.spark(12, 62, 196, 30, game.get("history") or [], col, capacity=60)
        c.text(12, 92, 196, 16, game["name"].removesuffix(".exe"), 9.5, color=c.s.muted)
