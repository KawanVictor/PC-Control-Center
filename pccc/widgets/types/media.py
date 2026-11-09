"""Player de música (controles de mídia do Windows)."""
from __future__ import annotations

import hashlib

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainterPath

from ..base import Canvas, Renderer
from ._common import hub, no_data


# ============================================================================ 11. Player
class MediaWidget(Renderer):
    type_id, title, glyph = "media", "Player de música", ""
    description = "O que está tocando (Spotify, navegador, Media Player) com controles."
    base_size = (310, 122)
    needs = {"media"}

    def __init__(self, cfg):
        super().__init__(cfg)
        self._thumb_key = b""
        self._thumb: QImage | None = None

    def draw(self, c: Canvas) -> None:
        m = hub().media
        if not m.available and m.error:
            no_data(c, "Controle de mídia indisponível")
            return
        art = QRectF(14, 14, 94, 94)
        if m.thumbnail:
            key = hashlib.md5(m.thumbnail).digest()
            if key != self._thumb_key:
                self._thumb_key, self._thumb = key, QImage.fromData(m.thumbnail)
        else:
            self._thumb = None
        path = QPainterPath()
        path.addRoundedRect(art, 12, 12)
        if self._thumb is not None and not self._thumb.isNull():
            c.p.save()
            c.p.setClipPath(path)
            c.p.drawImage(art, self._thumb)
            c.p.restore()
        else:
            c.rounded(art.x(), art.y(), art.width(), art.height(), 12, c.s.faint)
            c.glyph(art.x(), art.y(), art.width(), art.height(), "", 30, c.s.muted)
        if not m.active:
            c.text(122, 30, 180, 24, "Nada tocando", 15, 600)
            c.text(122, 54, 180, 20, "Abra o Spotify, o navegador ou outro player", 10.5, color=c.s.muted)
            return
        c.text(122, 12, 180, 22, m.title or "—", 14, 600)
        c.text(122, 33, 180, 18, m.artist or m.album or "", 11.5, color=c.s.muted)
        c.text(122, 50, 180, 16, m.app, 9.5, color=c.s.accent)
        pos, dur = m.live_position(), m.duration
        if dur > 0:
            c.bar(122, 72, 176, 4, pos / dur * 100)
            c.text(122, 76, 60, 14, f"{int(pos) // 60}:{int(pos) % 60:02d}", 9, color=c.s.muted)
            c.text(238, 76, 60, 14, f"{int(dur) // 60}:{int(dur) % 60:02d}", 9, color=c.s.muted,
                   align=Qt.AlignRight | Qt.AlignVCenter)
        for rect, aid in self.hit_areas():
            g = {"previous": "", "play_pause": "" if m.playing else "", "next": ""}[aid]
            if aid == "play_pause":
                c.rounded(rect.x(), rect.y(), rect.width(), rect.height(), rect.height() / 2, c.s.accent)
                c.glyph(rect.x(), rect.y(), rect.width(), rect.height(), g, 12, QColor("#0b1020"))
            else:
                c.glyph(rect.x(), rect.y(), rect.width(), rect.height(), g, 12, c.s.text)

    def hit_areas(self):
        return [(QRectF(170, 92, 28, 26), "previous"), (QRectF(204, 91, 30, 28), "play_pause"),
                (QRectF(240, 92, 28, 26), "next")]

    def on_click(self, area_id: str) -> None:
        from ..media import MediaService
        MediaService.instance().command(area_id)
