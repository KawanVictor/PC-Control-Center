"""Aba Atalhos: atalhos de teclado globais."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QGridLayout, QKeySequenceEdit, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ....core.config import Settings
from ....personalization import hotkeys
from ...components import GlassCard, ToggleSwitch, label
from ...icons import G
from ..common import setting_row


# ============================================================== ATALHOS
class HotkeysView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        card = GlassCard("Atalhos de teclado globais", G.KEYBOARD)
        en = ToggleSwitch()
        en.setChecked(bool(Settings.instance().get("hotkeys.enabled", True)))
        en.toggled.connect(lambda v: (Settings.instance().set("hotkeys.enabled", v),
                                      hotkeys.HotkeyManager.instance().apply(), self.render()))
        card.add(setting_row("Atalhos ligados", "Funcionam em qualquer programa, mesmo com o app na bandeja. Clique na "
                      "caixa e pressione a combinação (ex.: Ctrl+Alt+J).", en))
        self.form = QGridLayout()
        self.form.setColumnStretch(0, 1)
        card.add(self.form)
        lay.addWidget(card)
        self.render()

    def render(self) -> None:
        while self.form.count():
            w = self.form.takeAt(0).widget()
            if w:
                w.deleteLater()
        mgr = hotkeys.HotkeyManager.instance()
        b = hotkeys.bindings()
        for r, (action, text) in enumerate(hotkeys.actions().items()):
            self.form.addWidget(label(text), r, 0)
            ed = QKeySequenceEdit(QKeySequence(b.get(action, "")))
            if hasattr(ed, "setMaximumSequenceLength"):
                ed.setMaximumSequenceLength(1)
            inner = ed.findChild(QLineEdit)
            if inner is not None:
                inner.setPlaceholderText("Pressione as teclas")
            ed.setFixedWidth(170)
            ed.editingFinished.connect(lambda a=action, e=ed: self._set(a, e))
            self.form.addWidget(ed, r, 1)
            clr = QPushButton("Limpar")
            clr.clicked.connect(lambda _=False, a=action: self._clear(a))
            self.form.addWidget(clr, r, 2)
            err = mgr.errors.get(action, "")
            st = label(f"⚠ {err}" if err else ("✓" if b.get(action) else ""), "Faint")
            self.form.addWidget(st, r, 3)

    def _set(self, action: str, ed: QKeySequenceEdit) -> None:
        text = hotkeys.normalize(ed.keySequence())
        if not text or text == hotkeys.bindings().get(action, ""):
            return
        try:
            err = hotkeys.HotkeyManager.instance().set_binding(action, text)
            if err:
                QMessageBox.warning(self, "Atalho", err)
        except ValueError as e:
            QMessageBox.warning(self, "Atalho", str(e))
        QTimer.singleShot(0, self.render)

    def _clear(self, action: str) -> None:
        hotkeys.HotkeyManager.instance().set_binding(action, "")
        self.render()
