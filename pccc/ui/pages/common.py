"""Auxiliares compartilhados pelas páginas: tabelas, confirmação, linhas de ajuste e ícones."""
from __future__ import annotations

from PySide6.QtCore import QFileInfo, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QAbstractItemView, QFileIconProvider, QHBoxLayout, QHeaderView, QMessageBox, QSlider,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..components import label


_icon_provider = None
_icon_cache: dict[str, QIcon | None] = {}


def file_icon(path: str) -> QIcon | None:
    """Ícone do executável/ícone (cache). Retorna None se o arquivo não existe."""
    global _icon_provider
    if not path:
        return None
    path = path.split(",")[0].strip().strip('"')
    if path in _icon_cache:
        return _icon_cache[path]
    info = QFileInfo(path)
    if not info.exists() or info.isDir():
        _icon_cache[path] = None
        return None
    if _icon_provider is None:
        _icon_provider = QFileIconProvider()
    icon = _icon_provider.icon(info)
    _icon_cache[path] = icon
    return icon


class SortItem(QTableWidgetItem):
    """Item que ordena pelo valor numérico (UserRole) em vez do texto."""

    def __init__(self, text: str, sort_value=None) -> None:
        super().__init__(text)
        self.setData(Qt.ItemDataRole.UserRole, sort_value if sort_value is not None else text.lower())

    def __lt__(self, other) -> bool:
        a, b = self.data(Qt.ItemDataRole.UserRole), other.data(Qt.ItemDataRole.UserRole)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def make_table(headers: list[str], stretch: int = 0) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.verticalHeader().setDefaultSectionSize(32)
    t.setSortingEnabled(True)
    t.setWordWrap(False)              # sem quebra: caminhos longos são cortados no fim, não no meio
    t.setTextElideMode(Qt.TextElideMode.ElideRight)
    t.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    hh = t.horizontalHeader()
    hh.setHighlightSections(False)
    hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for i in range(len(headers)):
        hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i == stretch else QHeaderView.ResizeMode.ResizeToContents)
    t.setMinimumHeight(420)
    return t


def ask(parent, title: str, text: str, detail: str = "", danger_text: str = "Continuar") -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setInformativeText(detail)
    ok = box.addButton(danger_text, QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)  # padrão = Cancelar
    box.exec()
    return box.clickedButton() is ok


def setting_row(title: str, desc: str, control: QWidget) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 4, 0, 4)
    col = QVBoxLayout()
    col.setSpacing(1)
    col.addWidget(label(title))
    if desc:
        col.addWidget(label(desc, "Faint", wrap=True))
    h.addLayout(col, 1)
    h.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return w


def labeled_slider(value: int, on_release, lo: int = 0, hi: int = 100, width: int = 220) -> tuple[QWidget, QSlider]:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    s.setFixedWidth(width)
    lbl = label(f"{value}%", "Value")
    lbl.setFixedWidth(46)
    s.valueChanged.connect(lambda v: lbl.setText(f"{v}%"))
    s.sliderReleased.connect(lambda: on_release(s.value()))
    s.valueChanged.connect(lambda v: None if s.isSliderDown() else on_release(v))
    h.addWidget(s)
    h.addWidget(lbl)
    return w, s


def add_desktop_widget(type_id: str, layer: str | None = None) -> None:
    from ...widgets.manager import WidgetManager
    wm = WidgetManager.instance()
    win = wm.add(type_id)
    if layer:
        win.cfg.layer = layer
        win.apply_layer()
        wm.save()
