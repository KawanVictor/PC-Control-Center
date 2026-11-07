"""Widgets da área de trabalho: galeria, widgets do perfil atual, perfis e opções globais."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from ...core.config import Settings
from ...widgets.base import WidgetConfig
from ...widgets.manager import WidgetManager
from ...widgets.types import REGISTRY
from ...widgets.window import paint_widget
from ..components import GlassCard, ResponsiveGrid, ToggleSwitch, icon_label, label
from ..icons import G
from ..theme import ThemeManager
from .base import Page


class PreviewTile(QWidget):
    """Miniatura ao vivo de um tipo de widget (usa o mesmo código de desenho)."""

    def __init__(self, type_id: str) -> None:
        super().__init__()
        cls = REGISTRY[type_id]
        self.cfg = WidgetConfig(type=type_id)
        self.renderer = cls(self.cfg)
        if type_id == "shortcuts":
            import os
            win = os.environ.get("WINDIR", r"C:\Windows")
            self.cfg.options["items"] = [
                {"name": "Explorador", "path": rf"{win}\explorer.exe"},
                {"name": "Bloco de notas", "path": rf"{win}\System32\notepad.exe"},
                {"name": "Calculadora", "path": rf"{win}\System32\calc.exe"},
                {"name": "Terminal", "path": rf"{win}\System32\cmd.exe"}]
        self.setFixedHeight(150)

    def sizeHint(self) -> QSize:
        return QSize(260, 150)

    def paintEvent(self, _e) -> None:
        bw, bh = self.renderer.base_size
        scale = min((self.width() - 8) / bw, (self.height() - 8) / bh, 1.0)
        w, h = bw * scale, bh * scale
        p = QPainter(self)
        p.translate((self.width() - w) / 2, (self.height() - h) / 2)
        try:
            paint_widget(p, self.renderer, self.cfg, w, h)
        finally:
            p.end()


class WidgetsPage(Page):
    title = "Widgets da área de trabalho"
    subtitle = "Monitores, relógio, clima, player e atalhos direto na sua área de trabalho — estilo Rainmeter"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.mgr = WidgetManager.instance()
        self.settings = Settings.instance()

        # ---- cabeçalho: visibilidade global ----------------------------------------
        self.header_right.addWidget(label("Widgets visíveis", "Muted"))
        self.all_toggle = ToggleSwitch()
        self.all_toggle.setChecked(not self.mgr.hidden_all)
        self.all_toggle.toggled.connect(self.mgr.set_all_visible)
        self.header_right.addWidget(self.all_toggle)

        top = ResponsiveGrid(min_col_width=460, max_cols=2)
        # ---- perfis --------------------------------------------------------------------
        prof = GlassCard("Perfil de widgets", G.PERSONALIZE)
        prof.add(label("Cada perfil guarda um layout completo (quais widgets, posições e cores). "
                       "Ex.: “Trabalho”, “Jogos”, “Minimalista”.", "Muted", wrap=True))
        row = QHBoxLayout()
        self.profile = QComboBox()
        self.profile.setMinimumWidth(180)
        self.profile.activated.connect(lambda _i: self.mgr.switch_profile(self.profile.currentText()))
        row.addWidget(self.profile, 1)
        for text, fn in (("Novo", self._new_profile), ("Duplicar", lambda: self._new_profile(copy=True)),
                         ("Renomear", self._rename_profile), ("Excluir", self._delete_profile)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        prof.add(row)
        top.add(prof)

        # ---- opções -----------------------------------------------------------------
        opts = GlassCard("Opções", G.SETTINGS)
        r1 = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label("Mostrar widgets ao iniciar"))
        col.addWidget(label("Com “Iniciar com o Windows” ligado, os widgets aparecem ao entrar no Windows",
                            "Faint", wrap=True))
        r1.addLayout(col, 1)
        self.startup_toggle = ToggleSwitch()
        self.startup_toggle.setChecked(bool(self.settings.get("widgets.show_on_startup", True)))
        self.startup_toggle.toggled.connect(lambda v: self.settings.set("widgets.show_on_startup", v))
        r1.addWidget(self.startup_toggle)
        opts.add(r1)
        r2 = QHBoxLayout()
        for text, fn in (("Reorganizar à direita", self.mgr.arrange), ("Bloquear todos", lambda: self.mgr.lock_all(True)),
                         ("Desbloquear todos", lambda: self.mgr.lock_all(False))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r2.addWidget(b)
        r2.addStretch(1)
        opts.add(r2)
        top.add(opts)
        self.add(top)

        # ---- widgets do perfil atual -----------------------------------------------
        self.active_card = GlassCard("No perfil atual", G.LIST)
        self.count_badge = label("", "Badge")
        self.active_card.add_header_widget(self.count_badge)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(6)
        self.active_card.add(self.rows_box)
        self.empty = QWidget()
        ev = QHBoxLayout(self.empty)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.addWidget(label("Nenhum widget neste perfil. Adicione pela galeria abaixo ou comece com um layout pronto.",
                           "Muted", wrap=True), 1)
        sug = QPushButton("Aplicar layout sugerido")
        sug.setObjectName("Primary")
        sug.clicked.connect(self.mgr.apply_suggested)
        ev.addWidget(sug)
        self.active_card.add(self.empty)
        self.add(self.active_card)

        # ---- galeria ---------------------------------------------------------------
        gal = GlassCard("Galeria — clique em Adicionar para colocar na área de trabalho", G.WIDGETS)
        grid = ResponsiveGrid(min_col_width=290, max_cols=4, spacing=12)
        self.previews: list[PreviewTile] = []
        for type_id, cls in REGISTRY.items():
            tile = GlassCard()
            pv = PreviewTile(type_id)
            self.previews.append(pv)
            tile.add(pv)
            head = QHBoxLayout()
            head.addWidget(icon_label(cls.glyph, 11))
            head.addWidget(label(cls.title, "Value"), 1)
            add = QPushButton("Adicionar")
            add.setObjectName("Primary")
            add.setCursor(Qt.PointingHandCursor)
            add.clicked.connect(lambda _=False, t=type_id: self.mgr.add(t))
            head.addWidget(add)
            tile.add(head)
            tile.add(label(cls.description, "Faint", wrap=True))
            grid.add(tile)
        gal.add(grid)
        self.add(gal)
        self.add(label("Dicas: arraste um widget para movê-lo (ele encaixa nas bordas e nos outros widgets). "
                       "Use o canto inferior direito ou Ctrl + roda do mouse para redimensionar. "
                       "Botão direito abre o menu; clique duplo abre as configurações.", "Faint", wrap=True))
        self.layout_.addStretch(1)

        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._tick_previews)
        self.mgr.changed.connect(self.refresh)
        ThemeManager.instance().changed.connect(lambda _t: self._tick_previews())
        self.refresh()

    # ------------------------------------------------------------------ dados
    def _tick_previews(self) -> None:
        if not self.isVisible():
            self._preview_timer.stop()
            return
        for pv in self.previews:
            pv.update()

    def on_shown(self) -> None:
        self._preview_timer.start(1000)
        self.refresh()

    def refresh(self) -> None:
        names = self.mgr.profile_names()
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItems(names)
        self.profile.setCurrentText(self.mgr.active)
        self.profile.blockSignals(False)
        self.all_toggle.blockSignals(True)
        self.all_toggle.setChecked(not self.mgr.hidden_all)
        self.all_toggle.blockSignals(False)

        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        wins = list(self.mgr.windows.values())
        self.empty.setVisible(not wins)
        self.count_badge.setText(f"{len(wins)} widget(s) · perfil “{self.mgr.active}”")
        for win in wins:
            r = QWidget()
            h = QHBoxLayout(r)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(icon_label(win.renderer.glyph, 11))
            h.addWidget(label(win.renderer.title), 1)
            info = f"{win.width()}×{win.height()} px · " + {"bottom": "atrás das janelas", "normal": "normal",
                                                            "top": "sempre visível"}[win.cfg.layer]
            if win.cfg.locked:
                info += " · bloqueado"
            h.addWidget(label(info, "Faint"))
            tg = ToggleSwitch()
            tg.setChecked(win.cfg.visible)
            tg.setToolTip("Mostrar/ocultar")
            tg.toggled.connect(lambda v, wid=win.cfg.id: self.mgr.set_visible(wid, v))
            h.addWidget(tg)
            cfg_btn = QPushButton("Configurar")
            cfg_btn.clicked.connect(lambda _=False, w=win: self.mgr.configure_requested.emit(w))
            h.addWidget(cfg_btn)
            rm = QPushButton("Remover")
            rm.setObjectName("Danger")
            rm.clicked.connect(lambda _=False, wid=win.cfg.id: self.mgr.remove(wid))
            h.addWidget(rm)
            self.rows_box.addWidget(r)
        self.relayout()

    # ----------------------------------------------------------------- perfis
    def _new_profile(self, copy: bool = False) -> None:
        name, ok = QInputDialog.getText(self, "Novo perfil", "Nome do perfil:")
        if ok:
            try:
                self.mgr.create_profile(name, copy_current=copy)
            except ValueError as e:
                QMessageBox.warning(self, "Perfil", str(e))

    def _rename_profile(self) -> None:
        old = self.mgr.active
        name, ok = QInputDialog.getText(self, "Renomear perfil", "Novo nome:", text=old)
        if ok and name != old:
            try:
                self.mgr.rename_profile(old, name)
            except ValueError as e:
                QMessageBox.warning(self, "Perfil", str(e))

    def _delete_profile(self) -> None:
        name = self.mgr.active
        if QMessageBox.question(self, "Excluir perfil", f"Excluir o perfil “{name}” e seus widgets?") \
                == QMessageBox.Yes:
            try:
                self.mgr.delete_profile(name)
            except ValueError as e:
                QMessageBox.warning(self, "Perfil", str(e))


__all__ = ["WidgetsPage", "QRectF"]
