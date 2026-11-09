"""Abas Barra de tarefas e Área de trabalho: ajustes do Explorer."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ....core.winapi import is_admin, shell_open
from ....personalization import tweaks
from ...components import ResponsiveGrid, ToggleSwitch, label
from ...icons import G
from ...tasks import run_task


class ExplorerTab:
    """Parte da PersonalizationPage (usa self.add, self._section, self.changed...)."""

    # ======================================================== BARRA DE TAREFAS
    def _build_taskbar(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        card = self._section("Barra de tarefas", "")
        self._tweak_rows(card, "taskbar")
        ah = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label("Ocultar a barra de tarefas automaticamente"))
        col.addWidget(label("A barra aparece ao levar o mouse até a borda da tela.", "Faint"))
        ah.addLayout(col, 1)
        self.autohide = ToggleSwitch()
        self.autohide.setChecked(tweaks.taskbar_autohide())
        self.autohide.toggled.connect(lambda on: (tweaks.set_taskbar_autohide(on), self.changed()))
        ah.addWidget(self.autohide)
        card.add(ah)
        more = QPushButton("Mais opções da barra de tarefas no Windows")
        more.clicked.connect(lambda: shell_open("ms-settings:taskbar"))
        card.add(more)
        lay.addWidget(card)
        return w

    # ============================================== ÁREA DE TRABALHO E EXPLORER
    def _build_desktop(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        grid = ResponsiveGrid(min_col_width=460, max_cols=2)
        icons = self._section("Ícones da área de trabalho", "")
        self._tweak_rows(icons, "desktop")
        grid.add(icons)
        exp = self._section("Explorador de Arquivos", G.FOLDER)
        self._tweak_rows(exp, "explorer")
        cm = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label("Menu de contexto clássico (botão direito completo)"))
        col.addWidget(label("Mostra o menu completo do Windows 10 sem precisar de “Mostrar mais opções”. "
                            "Aplicado após reiniciar o Explorer.", "Faint", wrap=True))
        cm.addLayout(col, 1)
        self.classic = ToggleSwitch()
        self.classic.setChecked(tweaks.classic_menu_enabled())
        self.classic.setEnabled(tweaks.BUILD >= 22000)
        self.classic.toggled.connect(lambda on: run_task(tweaks.set_classic_menu, on,
                                                         on_done=lambda _r: self.changed(True)))
        cm.addWidget(self.classic)
        exp.add(cm)
        grid.add(exp)
        sysc = self._section("Inicialização do sistema", G.POWER)
        self._tweak_rows(sysc, "system")
        go = QPushButton("Gerenciar programas que iniciam com o Windows")
        go.clicked.connect(self._go_startup)
        sysc.add(go)
        if not is_admin():
            sysc.add(label("🛡 = exige executar o PC Control Center como administrador.", "Faint"))
        grid.add(sysc)
        lay.addWidget(grid)
        return w

    def _go_startup(self) -> None:
        win = self.window()
        if hasattr(win, "show_page"):
            win.show_page(3)
            page = win.stack.widget(3)
            if hasattr(page, "switch"):
                page.switch("startup")
