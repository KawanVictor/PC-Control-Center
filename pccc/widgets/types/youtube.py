"""YouTube: vídeos novos."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainterPath

from ...core.winapi import shell_open
from ..base import Canvas, Renderer
from ._common import no_data


# ===================================================================== 19. YouTube
class YouTubeWidget(Renderer):
    type_id, title, glyph = "youtube", "YouTube: vídeos novos", ""
    description = "Último vídeo dos seus canais; clique para assistir, setas para os anteriores."
    base_size = (330, 132)
    default_refresh = 5000

    def __init__(self, cfg):
        super().__init__(cfg)
        self.index = 0
        self._img_key, self._img = "", None

    def _videos(self):
        from ...media.youtube import YouTubeFeed
        feed = YouTubeFeed.instance()
        return feed, feed.videos[:8]

    def draw(self, c: Canvas) -> None:
        from ...media.youtube import ago
        feed, vids = self._videos()
        if not vids:
            no_data(c, "Adicione canais em Mídia → YouTube" if not feed.channels() else "Carregando vídeos...")
            return
        self.index %= len(vids)
        v = vids[self.index]
        if self._img_key != v.id:
            data = feed.thumb(v)
            self._img_key, self._img = v.id, QImage.fromData(data) if data else None
        art = QRectF(12, 12, 160, 90)
        path = QPainterPath()
        path.addRoundedRect(art, 10, 10)
        if self._img is not None and not self._img.isNull():
            c.p.save()
            c.p.setClipPath(path)
            c.p.drawImage(art, self._img)
            c.p.restore()
        else:
            c.rounded(art.x(), art.y(), art.width(), art.height(), 10, c.s.faint)
        c.text(182, 10, 138, 56, v.title, 11.5, 600, align=Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)
        c.text(182, 70, 138, 16, v.channel, 10, color=c.s.accent)
        c.text(182, 86, 138, 16, ago(v.published), 10, color=c.s.muted)
        c.text(12, 108, 160, 18, f"{self.index + 1} de {len(vids)}", 9.5, color=c.s.muted, align=Qt.AlignCenter)
        for rect, aid in self.hit_areas()[1:]:
            c.glyph(rect.x(), rect.y(), rect.width(), rect.height(), "" if aid == "prev" else "", 11,
                    c.s.text)

    def hit_areas(self):
        return [(QRectF(12, 12, 160, 90), "open"), (QRectF(12, 106, 30, 22), "prev"), (QRectF(142, 106, 30, 22), "next")]

    def on_click(self, area_id: str) -> None:
        _feed, vids = self._videos()
        if not vids:
            return
        if area_id == "open":
            shell_open(vids[self.index % len(vids)].url)
        else:
            self.index = (self.index + (1 if area_id == "next" else -1)) % len(vids)
