"""Aba Histórico: alterações feitas pelo app, com desfazer."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget

from ....personalization import changes
from ...components import label
from ...icons import G
from ...tasks import run_task
from ..common import ask, make_table
from ._tab import PersonalizationTab


class HistoryTab(PersonalizationTab):
    """Parte da PersonalizationPage (usa self.add, self._section, self.changed...)."""

    # ================================================================ HISTÓRICO
    def _build_history(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        card = self._section("Histórico de alterações", G.HISTORY)
        card.add(label("Cada alteração feita por aqui tem cópia de segurança. Selecione e clique em Desfazer para "
                       "voltar ao estado anterior.", "Muted", wrap=True))
        self.hist_table = make_table(["Data", "Alteração", "Situação"], stretch=1)
        self.hist_table.setMinimumHeight(380)
        card.add(self.hist_table)
        btns = QHBoxLayout()
        undo = QPushButton("Desfazer selecionada")
        undo.setObjectName("Primary")
        undo.clicked.connect(self._undo_selected)
        btns.addWidget(undo)
        btns.addStretch(1)
        card.add(btns)
        lay.addWidget(card)
        return w

    def _load_history(self) -> None:
        self._hist = changes.history(200)
        t = self.hist_table
        t.setSortingEnabled(False)
        t.setRowCount(len(self._hist))
        for r, h in enumerate(self._hist):
            state = "desfeita" if h["restored"] else "ativa"
            for c, text in enumerate([datetime.fromtimestamp(h["ts"]).strftime("%d/%m/%Y %H:%M:%S"), h["title"],
                                      state]):
                item = QTableWidgetItem(text)
                if h["restored"]:
                    item.setForeground(QColor("#94a3b8"))
                t.setItem(r, c, item)

    def _undo_selected(self) -> None:
        r = self.hist_table.currentRow()
        if r < 0 or r >= len(getattr(self, "_hist", [])):
            QMessageBox.information(self, "Desfazer", "Selecione uma alteração na lista.")
            return
        h = self._hist[r]
        if h["restored"]:
            QMessageBox.information(self, "Desfazer", "Esta alteração já foi desfeita.")
            return
        detail = "O estado anterior será restaurado."
        if h["kind"] == "shortcut":
            detail = (f"Será apagado exatamente este arquivo de atalho:\n{h['data'].get('path', '')}\n\n"
                      "O programa, a pasta ou o site de destino não são afetados.")
        if not ask(self, "Desfazer", f"Desfazer “{h['title']}”?", detail, "Desfazer"):
            return

        def done(msg):
            self._load_history()
            self.on_shown()
            self._loaded.discard("wall")
            self._loaded.discard("themes")
            if "Explorer" in msg:
                self.restart_card.show()
            QMessageBox.information(self, "Desfazer", msg)

        run_task(changes.undo, h["id"], on_done=done, on_error=lambda e: QMessageBox.warning(self, "Desfazer", e))
