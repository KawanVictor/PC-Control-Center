"""Aba Temas: temas instalados do Windows."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ....core.winapi import shell_open
from ....personalization import themes
from ...components import GlassCard, ResponsiveGrid, label
from ...icons import G
from ...tasks import run_task
from ..common import ask
from .wallpaper import _thumbs
from ._tab import PersonalizationTab


class ThemesTab(PersonalizationTab):
    """Parte da PersonalizationPage (usa self.add, self._section, self.changed...)."""

    # =================================================================== TEMAS
    def _build_themes(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        card = self._section("Temas instalados", G.PERSONALIZE)
        card.add(label("Um tema troca papel de parede, cores, sons e cursores de uma vez. O Windows aplica o tema e "
                       "pode abrir a página de Personalização. Para voltar, use o Histórico.", "Muted", wrap=True))
        self.theme_grid = ResponsiveGrid(min_col_width=250, max_cols=4, spacing=12)
        card.add(self.theme_grid)
        more = QPushButton("Mais temas na Microsoft Store")
        more.clicked.connect(lambda: shell_open("ms-windows-store://collection?CollectionId=Themes"))
        card.add(more)
        lay.addWidget(card)
        return w

    def _load_themes(self) -> None:
        items = themes.list_themes()
        for _w, _s in list(self.theme_grid._items):
            _w.deleteLater()
        self.theme_grid._items.clear()
        pics: dict[str, list[QLabel]] = {}   # vários temas podem usar a mesma imagem
        # Os cartões aparecem na hora; as miniaturas (imagens 4K) chegam depois.
        for t in items:
            tile = GlassCard()
            pic = QLabel("carregando...")
            pic.setObjectName("Faint")
            pic.setFixedHeight(130)
            pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if t.wallpaper:
                pics.setdefault(t.wallpaper, []).append(pic)
            else:
                pic.setText("(sem papel de parede)")
            tile.add(pic)
            head = QHBoxLayout()
            head.addWidget(label(t.name, "Value"), 1)
            if t.mode:
                head.addWidget(label(t.mode, "Badge"))
            tile.add(head)
            btn = QPushButton("Em uso" if t.current else "Aplicar tema")
            btn.setObjectName("" if t.current else "Primary")
            btn.setEnabled(not t.current)
            btn.clicked.connect(lambda _=False, th=t: self._apply_theme(th))
            tile.add(btn)
            self.theme_grid.add(tile)
        self.relayout()

        def done(thumbs):
            for path, img in thumbs:
                pm = QPixmap.fromImage(img)
                for pic in pics.get(path, []):
                    pic.setPixmap(pm)

        run_task(_thumbs, list(pics), 230, 130, on_done=done)

    def _apply_theme(self, t: themes.ThemeInfo) -> None:
        if not ask(self, "Aplicar tema", f"Aplicar o tema “{t.name}”?",
                    "Papel de parede, cores e sons serão trocados pelo Windows. Você pode voltar ao tema atual "
                    "pela aba Histórico.", "Aplicar"):
            return
        try:
            themes.apply_theme(t.path)
        except Exception as e:
            QMessageBox.warning(self, "Tema", str(e))
            return
        self.changed()
        self._loaded.discard("themes")
