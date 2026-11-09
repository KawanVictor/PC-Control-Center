"""Aba Papel de parede: imagens do Windows e da pasta Imagens."""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from ....core.winapi import open_folder
from ....personalization import wallpaper
from ...components import ResponsiveGrid, label
from ...icons import G
from ...tasks import run_task


def _thumbs(paths: list[str], w: int = 240, h: int = 135) -> list[tuple[str, QImage]]:
    """Carrega miniaturas fora da thread da interface (QImage é seguro em outras threads)."""
    out = []
    for p in paths:
        img = QImage(p)
        if not img.isNull():
            out.append((p, img.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                        .copy(0, 0, w, h)))
    return out


class WallpaperTab:
    """Parte da PersonalizationPage (usa self.add, self._section, self.changed...)."""

    # ========================================================== PAPEL DE PAREDE
    def _build_wallpaper(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        cur = self._section("Papel de parede atual", "")
        row = QHBoxLayout()
        self.wp_preview = QLabel()
        self.wp_preview.setFixedSize(320, 180)
        self.wp_preview.setStyleSheet("border-radius: 10px; background: rgba(255,255,255,0.05);")
        row.addWidget(self.wp_preview)
        col = QVBoxLayout()
        self.wp_path = label("", "Muted", wrap=True)
        col.addWidget(self.wp_path)
        style_row = QHBoxLayout()
        style_row.addWidget(label("Ajuste:"))
        self.wp_style = QComboBox()
        for k, text in wallpaper.STYLE_LABELS.items():
            self.wp_style.addItem(text, k)
        self.wp_style.activated.connect(lambda _i: self._apply_wallpaper(wallpaper.current_path()))
        style_row.addWidget(self.wp_style)
        style_row.addStretch(1)
        col.addLayout(style_row)
        choose = QPushButton("Escolher imagem do computador...")
        choose.setObjectName("Primary")
        choose.clicked.connect(self._choose_wallpaper)
        col.addWidget(choose, 0, Qt.AlignLeft)
        folder = QPushButton("Abrir pasta das imagens anteriores")
        folder.clicked.connect(lambda: open_folder(str(wallpaper.backup_dir())))
        col.addWidget(folder, 0, Qt.AlignLeft)
        col.addStretch(1)
        row.addLayout(col, 1)
        cur.add(row)
        lay.addWidget(cur)

        self.wp_gallery_card = self._section("Imagens do Windows — clique para aplicar", G.WIDGETS)
        self.wp_gallery = ResponsiveGrid(min_col_width=200, max_cols=5, spacing=10)
        self.wp_gallery_card.add(self.wp_gallery)
        lay.addWidget(self.wp_gallery_card)
        self.wp_prev_card = self._section("Papéis de parede anteriores (cópias de segurança)", G.HISTORY)
        self.wp_prev = ResponsiveGrid(min_col_width=200, max_cols=5, spacing=10)
        self.wp_prev_card.add(self.wp_prev)
        lay.addWidget(self.wp_prev_card)
        return w

    def _thumb_button(self, path: str, img: QImage, on_click) -> QPushButton:
        b = QPushButton()
        b.setFixedHeight(118)
        b.setIcon(QPixmap.fromImage(img))
        b.setIconSize(QSize(200, 112))
        b.setToolTip(os.path.basename(path))
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet("QPushButton { padding: 2px; border-radius: 10px; }")
        b.clicked.connect(lambda _=False, p=path: on_click(p))
        return b

    def _load_wallpapers(self) -> None:
        path = wallpaper.current_path()
        self.wp_path.setText(path or "(cor sólida ou nenhum)")
        self.wp_style.setCurrentIndex(max(0, self.wp_style.findData(wallpaper.current_style())))
        if path and os.path.isfile(path):
            run_task(_thumbs, [path], 320, 180,
                     on_done=lambda r: r and self.wp_preview.setPixmap(QPixmap.fromImage(r[0][1])))
        self._fill_grid(self.wp_gallery, wallpaper.builtin_wallpapers())
        prev = wallpaper.previous_wallpapers()
        self.wp_prev_card.setVisible(bool(prev))
        self._fill_grid(self.wp_prev, prev)

    def _fill_grid(self, grid: ResponsiveGrid, paths: list[str]) -> None:
        def done(items):
            for _w, _s in list(grid._items):
                _w.deleteLater()
            grid._items.clear()
            for p, img in items:
                grid.add(self._thumb_button(p, img, self._apply_wallpaper))
            self.relayout()
        run_task(_thumbs, paths, 200, 112, on_done=done)

    def _choose_wallpaper(self) -> None:
        start = os.path.join(os.path.expanduser("~"), "Pictures")
        path, _ = QFileDialog.getOpenFileName(self, "Escolher papel de parede", start,
                                              "Imagens (*.jpg *.jpeg *.png *.bmp *.gif *.webp *.jfif *.tif)")
        if path:
            self._apply_wallpaper(path)

    def _apply_wallpaper(self, path: str) -> None:
        style = self.wp_style.currentData()

        def done(_cid):
            self._load_wallpapers()
            self.changed()

        run_task(wallpaper.set_wallpaper, path, style, on_done=done,
                 on_error=lambda e: QMessageBox.warning(self, "Papel de parede", e))
