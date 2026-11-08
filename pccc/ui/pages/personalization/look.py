"""Aba Aparência: modo claro/escuro, transparência e cor de destaque."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from ....personalization import accent, tweaks
from ...components import ResponsiveGrid, ToggleSwitch, label
from ...icons import G
from ...tasks import run_task
from ._tab import PersonalizationTab


class LookTab(PersonalizationTab):
    """Parte da PersonalizationPage (usa self.add, self._section, self.changed...)."""

    # ============================================================== APARÊNCIA
    def _build_look(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=480, max_cols=2)

        mode = self._section("Modo claro / escuro", G.PERSONALIZE)
        quick = QHBoxLayout()
        for text, val in (("Tudo escuro", 0), ("Tudo claro", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, v=val: self._all_mode(v))
            quick.addWidget(b)
        quick.addStretch(1)
        mode.add(quick)
        self._tweak_rows(mode, "appearance")
        grid.add(mode)

        acc = self._section("Cor de destaque", G.PERSONALIZE)
        top = QHBoxLayout()
        self.accent_swatch = QLabel()
        self.accent_swatch.setFixedSize(46, 46)
        top.addWidget(self.accent_swatch)
        self.accent_label = label("", "Value")
        top.addWidget(self.accent_label, 1)
        custom = QPushButton("Personalizada...")
        custom.clicked.connect(self._custom_accent)
        top.addWidget(custom)
        acc.add(top)
        sw = QGridLayout()
        sw.setSpacing(6)
        for i, c in enumerate(accent.PRESETS):
            b = QPushButton()
            b.setFixedSize(34, 34)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(c)
            b.setStyleSheet(f"QPushButton {{ background: {c}; border-radius: 6px; border: 2px solid transparent; }}"
                            f"QPushButton:hover {{ border-color: white; }}")
            b.clicked.connect(lambda _=False, col=c: self._set_accent(col))
            sw.addWidget(b, i // 11, i % 11)
        acc.add(sw)
        auto_row = QHBoxLayout()
        auto_row.addWidget(label("Escolher automaticamente pelo papel de parede"), 1)
        self.auto_accent = ToggleSwitch()
        self.auto_accent.toggled.connect(
            lambda on: run_task(accent.set_auto_from_wallpaper, on, on_done=lambda _r: self._refresh_accent()))
        auto_row.addWidget(self.auto_accent)
        acc.add(auto_row)
        grid.add(acc)

        fx = self._section("Efeitos visuais", G.PERFORMANCE)
        anim = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label("Efeitos de animação"))
        col.addWidget(label("Animações ao abrir, minimizar e rolar. Desligar deixa PCs mais lentos mais ágeis.",
                            "Faint", wrap=True))
        anim.addLayout(col, 1)
        self.anim_toggle = ToggleSwitch()
        self.anim_toggle.setChecked(tweaks.get_animations())
        self.anim_toggle.toggled.connect(lambda on: run_task(tweaks.set_animations, on, on_done=lambda _r: self.changed()))
        anim.addWidget(self.anim_toggle)
        fx.add(anim)
        grid.add(fx)
        lay.addWidget(grid)
        self._refresh_accent()
        return w

    def _refresh_accent(self) -> None:
        cur = accent.current()
        self.accent_swatch.setStyleSheet(f"background: {cur['color']}; border-radius: 10px;")
        self.accent_label.setText(f"{cur['color']}" + ("  · automática" if cur["auto"] else ""))
        self.auto_accent.blockSignals(True)
        self.auto_accent.setChecked(cur["auto"])
        self.auto_accent.blockSignals(False)

    def _set_accent(self, color: str) -> None:
        run_task(accent.set_accent, color, on_done=lambda _r: (self._refresh_accent(), self.changed()),
                 on_error=lambda e: QMessageBox.warning(self, "Cor de destaque", e))

    def _custom_accent(self) -> None:
        c = QColorDialog.getColor(QColor(accent.current()["color"]), self, "Cor de destaque")
        if c.isValid():
            self._set_accent(c.name().upper())

    def _all_mode(self, light: int) -> None:
        def work():
            tweaks.TWEAK_BY_ID["apps_mode"].apply(light)
            tweaks.TWEAK_BY_ID["system_mode"].apply(light)
        run_task(work, on_done=lambda _r: (self.on_shown(), self.changed()))
