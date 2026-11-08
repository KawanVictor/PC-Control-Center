"""Atalhos para aplicativos."""
from __future__ import annotations

import math
import os

from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileIconProvider

from ...core.winapi import shell_open
from ...ui.icons import G
from ..base import Canvas, Renderer
from ._common import no_data


# ============================================================================ 14. Atalhos
_icon_provider: QFileIconProvider | None = None


_icon_cache: dict[str, QPixmap] = {}


def _icon_for(path: str) -> QPixmap | None:
    global _icon_provider
    if path in _icon_cache:
        return _icon_cache[path]
    info = QFileInfo(path)
    pm = None
    if info.exists():
        if _icon_provider is None:
            _icon_provider = QFileIconProvider()
        pm = _icon_provider.icon(info).pixmap(QSize(64, 64))
    _icon_cache[path] = pm
    return pm


class ShortcutsWidget(Renderer):
    type_id, title, glyph = "shortcuts", "Atalhos para aplicativos", G.APPS
    description = "Ícones que abrem seus programas, pastas ou sites favoritos."
    default_refresh = 10_000
    defaults = {"items": [], "columns": 4}

    @property
    def base_size(self):  # cresce conforme a quantidade de atalhos
        cols = max(2, min(8, int(self.opt.get("columns", 4))))
        n = max(1, len(self.opt.get("items", [])))
        rows = min(4, math.ceil(n / cols))
        return (cols * 66 + 16, rows * 74 + 14)

    def _cells(self):
        cols = max(2, min(8, int(self.opt.get("columns", 4))))
        for i, it in enumerate(self.opt.get("items", [])[: cols * 4]):
            r, col = divmod(i, cols)
            yield QRectF(8 + col * 66, 8 + r * 74, 66, 74), it, i

    def draw(self, c: Canvas) -> None:
        items = self.opt.get("items", [])
        if not items:
            no_data(c, "Botão direito → Configurar\npara adicionar atalhos")
            return
        for rect, it, _i in self._cells():
            pm = _icon_for(it.get("path", "")) if not it.get("path", "").startswith("http") else None
            ir = QRectF(rect.center().x() - 20, rect.y() + 6, 40, 40)
            if pm is not None and not pm.isNull():
                c.p.drawPixmap(ir, pm, QRectF(pm.rect()))
            else:
                c.rounded(ir.x(), ir.y(), 40, 40, 10, c.s.faint)
                c.glyph(ir.x(), ir.y(), 40, 40, "" if it.get("path", "").startswith("http") else G.APPS, 16)
            c.text(rect.x() + 2, rect.y() + 48, rect.width() - 4, 22, it.get("name", "")[:14], 10,
                   align=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

    def hit_areas(self):
        return [(rect, str(i)) for rect, _it, i in self._cells()]

    def on_click(self, area_id: str) -> None:
        items = self.opt.get("items", [])
        i = int(area_id)
        if 0 <= i < len(items):
            path = items[i].get("path", "")
            if path.startswith("http") or os.path.exists(path):
                shell_open(path, items[i].get("args", ""))

    def tooltip(self) -> str:
        return ""
