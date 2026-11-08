"""Volume e mixer."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt

from ..base import Canvas, Renderer
from ._common import GREEN, RED, no_data


# ===================================================================== 17. Volume
class VolumeWidget(Renderer):
    type_id, title, glyph = "volume", "Volume e mixer", ""
    description = "Volume geral e dos apps que estão tocando, com controles."
    base_size = (280, 150)
    defaults = {"apps": 3}

    def draw(self, c: Canvas) -> None:
        from ...media import audio
        st = audio.cached()
        if st["error"]:
            no_data(c, "Sem dispositivo de áudio")
            return
        vol, muted = st["master"]
        c.ring(46, 48, 30, 0 if muted else vol * 100, 7, RED if muted else None)
        c.text(16, 30, 60, 36, "mudo" if muted else f"{vol * 100:.0f}", 13 if muted else 19, 600, align=Qt.AlignmentFlag.AlignCenter)
        c.text(96, 10, 170, 18, "Volume", 12.5, 600)
        for rect, aid in self.hit_areas():
            g = {"down": "", "mute": "" if muted else "", "up": ""}[aid]   # − / som / +
            c.rounded(rect.x(), rect.y(), rect.width(), rect.height(), 8, c.s.faint)
            c.glyph(rect.x(), rect.y(), rect.width(), rect.height(), g, 11, c.s.text)
        apps = [a for a in st["apps"] if a.key != "#system"][: int(self.opt["apps"])]
        if not apps:
            c.text(16, 96, 250, 20, "Nenhum app tocando som agora", 10.5, color=c.s.muted)
        for i, a in enumerate(apps[:3]):
            y = 92 + i * 18
            c.text(16, y - 1, 110, 16, a.name, 10.5, color=c.s.muted if a.muted else c.s.text)
            c.bar(130, y + 5, 100, 4, 0 if a.muted else a.volume * 100)
            c.bar(236, y + 5, 30, 4, min(100, a.peak * 140), GREEN)

    def hit_areas(self):
        return [(QRectF(96, 40, 50, 30), "down"), (QRectF(152, 40, 50, 30), "mute"),
                (QRectF(208, 40, 58, 30), "up")]

    def on_click(self, area_id: str) -> None:
        from ...media import audio
        if area_id == "mute":
            _v, m = audio.master_volume()
            audio.set_master_mute(not m)
        else:
            audio.change_master_volume(0.05 if area_id == "up" else -0.05)
        audio.cached(max_age=0)
