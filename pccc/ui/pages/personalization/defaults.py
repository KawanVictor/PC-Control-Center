"""Aba Apps padrão: aplicativos padrão por tipo de arquivo."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget

from ....core.winapi import shell_open
from ....personalization import defaults
from ...components import label
from ...icons import G
from ...tasks import run_task
from ..common import make_table
from ._tab import PersonalizationTab


class DefaultsTab(PersonalizationTab):
    """Parte da PersonalizationPage (usa self.add, self._section, self.changed...)."""

    # ============================================================= APPS PADRÃO
    def _build_defaults(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        card = self._section("Aplicativos padrão", G.APPS)
        card.add(label("O Windows protege os aplicativos padrão contra alterações por outros programas — por "
                       "segurança, a troca é feita na tela oficial do Windows (botão abaixo).", "Muted", wrap=True))
        self.def_table = make_table(["Tipo", "Extensão / protocolo", "Aplicativo atual"], stretch=2)
        self.def_table.setMinimumHeight(380)
        card.add(self.def_table)
        btns = QHBoxLayout()
        ch = QPushButton("Alterar aplicativos padrão no Windows")
        ch.setObjectName("Primary")
        ch.clicked.connect(lambda: shell_open("ms-settings:defaultapps"))
        btns.addWidget(ch)
        rf = QPushButton("Atualizar")
        rf.clicked.connect(self._load_defaults)
        btns.addWidget(rf)
        btns.addStretch(1)
        card.add(btns)
        lay.addWidget(card)
        return w

    def _load_defaults(self) -> None:
        def done(items):
            t = self.def_table
            t.setSortingEnabled(False)
            t.setRowCount(len(items))
            for r, d in enumerate(items):
                for c, text in enumerate([d.category, d.kind, d.app_name]):
                    t.setItem(r, c, QTableWidgetItem(text))
        run_task(defaults.list_defaults, on_done=done)
