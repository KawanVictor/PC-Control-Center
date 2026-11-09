"""OBS Studio."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor

from ..base import Canvas, Renderer
from ._common import RED


# ======================================================================== 18. OBS
class ObsWidget(Renderer):
    type_id, title, glyph = "obs", "OBS Studio", ""
    description = "Ao vivo/gravando, tempo, cena atual e bitrate, com botão de gravar."
    base_size = (280, 128)
    default_refresh = 1000

    def draw(self, c: Canvas) -> None:
        from ...media.obs import ObsClient
        st = ObsClient.instance().status
        c.glyph(12, 8, 22, 22, "", 12)
        c.text(36, 8, 160, 22, "OBS Studio", 12.5, 600)
        if st.state != "connected":
            c.text(14, 42, 252, 20, "Desconectado" if st.state != "connecting" else "Conectando...", 14, 600,
                   color=c.s.muted)
            c.text(14, 64, 252, 34, "Ative em Mídia → OBS no PC Control Center", 10.5, color=c.s.muted)
            return
        live_c = RED if st.streaming else c.s.faint
        c.rounded(14, 38, 112, 30, 8, live_c)
        c.text(14, 38, 112, 30, f"AO VIVO {st.stream_time}" if st.streaming else "Offline", 11.5, 700,
               QColor("white") if st.streaming else c.s.muted, align=Qt.AlignCenter)
        rec = self.hit_areas()[0][0]
        c.rounded(rec.x(), rec.y(), rec.width(), rec.height(), 8, RED if st.recording else c.s.faint)
        c.text(rec.x(), rec.y(), rec.width(), rec.height(),
               f"● REC {st.record_time}" if st.recording else "● Gravar", 11.5, 700,
               QColor("white") if st.recording else c.s.text, align=Qt.AlignCenter)
        c.text(14, 76, 252, 18, f"Cena: {st.scene or '—'}", 11.5)
        info = f"CPU do OBS {st.obs_cpu:.0f}%"
        if st.streaming:
            info = (f"{st.bitrate_kbps:.0f} kbps · perdidos {st.dropped_pct:.1f}%".replace(".", ",")
                    + " · " + info)
        c.text(14, 98, 252, 18, info, 10, color=c.s.muted)

    def hit_areas(self):
        return [(QRectF(134, 38, 132, 30), "record")]

    def on_click(self, area_id: str) -> None:
        from ...media.obs import ObsClient
        if area_id == "record":
            ObsClient.instance().toggle_record()
