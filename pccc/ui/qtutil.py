"""Pequenos auxiliares do Qt usados em várias telas."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLayout


def qapp() -> QApplication:
    """O QApplication em execução (o app sempre cria um antes de abrir qualquer janela)."""
    app = QApplication.instance()
    assert isinstance(app, QApplication), "QApplication ainda não foi criado"
    return app


def clear_layout(layout: QLayout) -> None:
    """Remove todos os itens do layout e apaga os widgets que estavam nele."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget() if item is not None else None
        if w is not None:
            w.deleteLater()
