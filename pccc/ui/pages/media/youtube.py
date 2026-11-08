"""Aba YouTube: vídeos novos dos canais acompanhados."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ....core.config import Settings
from ....core.winapi import shell_open
from ....media import youtube as yt
from ...components import GlassCard, ResponsiveGrid, label
from ...icons import G
from ...tasks import run_task
from ..base import Page
from ..common import add_desktop_widget


# =================================================================== YOUTUBE
class VideoCard(QFrame):
    def __init__(self, v: yt.Video, thumb: bytes) -> None:
        super().__init__()
        self.setObjectName("VideoCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.url = v.url
        self.setToolTip(v.title)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(4)
        img = QLabel()
        img.setFixedHeight(124)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qi = QImage.fromData(thumb) if thumb else QImage()
        if not qi.isNull():
            img.setPixmap(QPixmap.fromImage(qi.scaled(220, 124, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                      Qt.TransformationMode.SmoothTransformation)))
        img.setStyleSheet("border-radius: 8px; background: rgba(255,255,255,0.05);")
        lay.addWidget(img)
        t = label(v.title, wrap=True)
        t.setMaximumHeight(40)
        lay.addWidget(t)
        lay.addWidget(label(f"{v.channel} · {yt.ago(v.published)}", "Faint"))
        if v.views:
            lay.addWidget(label(yt.fmt_views(v.views), "Faint"))

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            shell_open(self.url)


class YouTubeView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.feed = yt.YouTubeFeed.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        ch = GlassCard("Seus canais", G.VIDEO)
        ch.add(label("Cole o link do canal (ex.: youtube.com/@nome) ou só o @nome. Os vídeos vêm do feed público "
                     "do YouTube — sem login.", "Faint", wrap=True))
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("https://www.youtube.com/@canal")
        self.input.returnPressed.connect(self._add)
        self.add_btn = QPushButton("Adicionar canal")
        self.add_btn.setObjectName("Primary")
        self.add_btn.clicked.connect(self._add)
        row.addWidget(self.input, 1)
        row.addWidget(self.add_btn)
        ch.add(row)
        self.status = label("", "Muted", wrap=True)
        ch.add(self.status)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        ch.add(self.chips)
        opts = QHBoxLayout()
        self.notify = QCheckBox("Avisar quando sair vídeo novo")
        self.notify.setChecked(bool(Settings.instance().get("media.youtube.notify", True)))
        self.notify.toggled.connect(lambda v: Settings.instance().set("media.youtube.notify", v))
        opts.addWidget(self.notify)
        opts.addStretch(1)
        refresh = QPushButton("Atualizar agora")
        refresh.clicked.connect(self.feed.refresh)
        opts.addWidget(refresh)
        addw = QPushButton("Widget na área de trabalho")
        addw.clicked.connect(lambda: add_desktop_widget("youtube"))
        opts.addWidget(addw)
        ch.add(opts)
        lay.addWidget(ch)

        vids = GlassCard("Vídeos mais recentes", G.VIDEO)
        self.grid = ResponsiveGrid(min_col_width=220, max_cols=5, spacing=12)
        vids.add(self.grid)
        self.empty = label("Adicione um canal para ver os vídeos novos aqui.", "Muted")
        vids.add(self.empty)
        lay.addWidget(vids)
        self.cards: list[VideoCard] = []
        self.feed.updated.connect(self._render)
        self._render()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self.feed.channels() and time.time() - self.feed.last_update > 600:
            self.feed.refresh()

    def _add(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.add_btn.setEnabled(False)
        self.status.setText("Procurando o canal...")

        def done(res):
            cid, name = res
            s = Settings.instance()
            chans = [c for c in (s.get("media.youtube.channels") or []) if isinstance(c, dict)]
            if any(c.get("id") == cid for c in chans):
                self.status.setText(f"“{name}” já está na lista.")
            else:
                chans.append({"id": cid, "name": name})
                s.set("media.youtube.channels", chans)
                self.status.setText(f"✓ “{name}” adicionado.")
                self.feed.start()
                self.feed.refresh()
            self.input.clear()
            self.add_btn.setEnabled(True)
            self._render()

        def fail(msg):
            self.status.setText(msg)
            self.add_btn.setEnabled(True)

        run_task(yt.resolve_channel, text, on_done=done, on_error=fail)

    def _remove(self, cid: str) -> None:
        s = Settings.instance()
        s.set("media.youtube.channels", [c for c in (s.get("media.youtube.channels") or []) if c.get("id") != cid])
        self.feed.videos = [v for v in self.feed.videos if v.channel_id != cid]
        yt.save_cache(self.feed.videos)
        self._render()

    def _render(self) -> None:
        while self.chips.count():
            w = self.chips.takeAt(0).widget()
            if w:
                w.deleteLater()
        for c in self.feed.channels():
            b = QPushButton(f"{c.get('name', c['id'])}  ✕")
            b.setToolTip("Remover canal")
            b.clicked.connect(lambda _=False, cid=c["id"]: self._remove(cid))
            self.chips.addWidget(b)
        self.chips.addStretch(1)
        self.grid.clear()
        self.cards = []
        for v in self.feed.videos[:20]:
            card = VideoCard(v, self.feed.thumb(v))
            self.grid.add(card)
            self.cards.append(card)
        self.empty.setVisible(not self.cards)
        if self.feed.loading:
            self.empty.setText("Carregando vídeos...")
            self.empty.show()
        elif self.feed.errors:
            self.status.setText("Alguns canais não carregaram: " + "; ".join(self.feed.errors[:3]))
        page = self.window().findChild(Page, "MediaPage") if self.window() else None
        if page is not None:
            page.relayout()
