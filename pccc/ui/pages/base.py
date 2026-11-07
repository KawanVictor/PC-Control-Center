"""Página base: título, subtítulo e área rolável."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ...monitoring.models import Snapshot
from ..components import label


class _Body(QWidget):
    """Conteúdo rolável que usa a altura *preferida* dos filhos (não a mínima).

    Com ``widgetResizable`` o QScrollArea encolhe o conteúdo até o mínimo; aqui o mínimo
    passa a ser a altura preferida, então gráficos e cartões ficam com tamanho confortável.
    """

    def minimumSizeHint(self) -> QSize:
        m = super().minimumSizeHint()
        lay = self.layout()
        if lay is None:
            return m
        h = lay.sizeHint().height()
        return QSize(m.width(), max(m.height(), h))


class Page(QWidget):
    title = ""
    subtitle = ""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        self.body = _Body()
        scroll.setWidget(self.body)
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(28, 24, 28, 28)
        self.layout_.setSpacing(16)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = label(self.title, "PageTitle")
        self.subtitle_label = label(self.subtitle, "PageSubtitle")
        titles.addWidget(self.title_label)
        titles.addWidget(self.subtitle_label)
        head.addLayout(titles)
        head.addStretch(1)
        self.header_right = QHBoxLayout()
        self.header_right.setSpacing(8)
        head.addLayout(self.header_right)
        self.layout_.addLayout(head)

    def add(self, w, stretch: int = 0):
        if isinstance(w, QWidget):
            self.layout_.addWidget(w, stretch)
        else:
            self.layout_.addLayout(w, stretch)
        return w

    def relayout(self) -> None:
        """Recalcula o layout já (após adicionar conteúdo dinamicamente). Sem isso, o Qt às vezes
        adia o cálculo e cartões recém-criados aparecem achatados até o próximo redimensionamento."""
        for lay in self.body.findChildren(QVBoxLayout) + self.body.findChildren(QHBoxLayout):
            lay.invalidate()
        self.layout_.invalidate()
        self.layout_.activate()
        self.body.updateGeometry()
        self.body.adjustSize()

    def on_snapshot(self, snap: Snapshot) -> None:
        """Chamado a cada nova leitura enquanto a página está visível."""

    def on_shown(self) -> None:
        """Chamado quando a página passa a ser exibida."""
