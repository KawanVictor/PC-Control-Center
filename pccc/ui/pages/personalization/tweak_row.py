"""Linha de ajuste da personalização: um controle por ajuste do Registro, com desfazer."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from ....personalization import tweaks
from ...components import ToggleSwitch, label
from ...tasks import run_task

if TYPE_CHECKING:
    from . import PersonalizationPage


class TweakRow(QWidget):
    """Linha de ajuste: título, descrição e interruptor/lista. Aplica em segundo plano."""

    def __init__(self, tweak: tweaks.Tweak, page: PersonalizationPage) -> None:
        super().__init__()
        self.t, self.page = tweak, page
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 6, 0, 6)
        col = QVBoxLayout()
        col.setSpacing(1)
        title = tweak.title + ("  🛡" if tweak.admin else "")
        col.addWidget(label(title))
        desc = tweak.description
        if not tweak.supported:
            desc = f"Requer Windows build {tweak.min_build} ou mais recente. " + desc
        if tweak.explorer_restart:
            desc += " (aplicado após reiniciar o Explorer)"
        if desc:
            col.addWidget(label(desc, "Faint", wrap=True))
        h.addLayout(col, 1)
        if tweak.toggle:
            self.ctrl = ToggleSwitch()
            self.ctrl.setChecked(tweak.current_index() == 1)
            self.ctrl.toggled.connect(lambda on: self._apply(tweak.options[1 if on else 0][0]))
        else:
            self.ctrl = QComboBox()
            for v, text in tweak.options:
                self.ctrl.addItem(text, v)
            self.ctrl.setCurrentIndex(max(0, tweak.current_index()))
            self.ctrl.activated.connect(lambda _i: self._apply(self.ctrl.currentData()))
        self.ctrl.setEnabled(tweak.supported)
        h.addWidget(self.ctrl, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def reload(self) -> None:
        self.ctrl.blockSignals(True)
        if self.t.toggle:
            self.ctrl.setChecked(self.t.current_index() == 1)
        else:
            self.ctrl.setCurrentIndex(max(0, self.t.current_index()))
        self.ctrl.blockSignals(False)

    def _apply(self, value) -> None:
        self.ctrl.setEnabled(False)

        def done(_cid):
            self.ctrl.setEnabled(True)
            self.page.changed(self.t.explorer_restart)

        def fail(msg):
            self.ctrl.setEnabled(True)
            self.reload()
            if "Acesso negado" in msg or "WinError 5" in msg:
                msg = ("O Windows bloqueou esta alteração por aplicativos externos (proteção do sistema). "
                       "Use o app Configurações para este item.") if not self.t.admin else \
                    "Este ajuste exige executar como administrador (Configurações → Reiniciar como administrador)."
            QMessageBox.warning(self, self.t.title, msg)

        run_task(self.t.apply, value, on_done=done, on_error=fail)
