"""Aba Inicialização: programas que abrem com o Windows, com desfazer."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QMenu, QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget

from ....apps import startup as startup_mod
from ....core import regbackup
from ....core.winapi import is_admin, open_folder, relaunch_as_admin, shell_open
from ...components import GlassCard, label
from ...icons import G
from ...tasks import run_task
from ..common import SortItem, ask, file_icon, make_table

if TYPE_CHECKING:
    from . import AppsPage


# ===================================================================== INICIALIZAÇÃO
class StartupView(QWidget):
    def __init__(self, page: AppsPage) -> None:
        super().__init__()
        self.page = page
        self.items: list[startup_mod.StartupItem] = []
        self._loaded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        card = GlassCard("Programas que iniciam com o Windows", G.POWER)
        self.status = label("", "Badge")
        card.add_header_widget(self.status)
        card.add(label("Desativar impede o programa de abrir sozinho ao entrar no Windows, sem desinstalá-lo. "
                       "É o mesmo mecanismo do Gerenciador de Tarefas e pode ser revertido a qualquer momento.",
                       "Muted", wrap=True))
        self.table = make_table(["Nome", "Fabricante", "Status", "Origem", "Comando"], stretch=4)
        self.table.setMinimumHeight(380)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.customContextMenuRequested.connect(self._menu)
        card.add(self.table, 1)
        actions = QHBoxLayout()
        self.btn_toggle = QPushButton("Desativar")
        self.btn_toggle.setObjectName("Primary")
        self.btn_toggle.clicked.connect(self.toggle)
        self.btn_open = QPushButton("Abrir local do arquivo")
        self.btn_open.clicked.connect(self.open_location)
        self.btn_undo = QPushButton("Desfazer última alteração")
        self.btn_undo.clicked.connect(self.undo)
        refresh = QPushButton("Atualizar")
        refresh.clicked.connect(self.load)
        taskmgr = QPushButton("Abrir no Gerenciador de Tarefas")
        taskmgr.clicked.connect(lambda: shell_open("taskmgr.exe", "/0 /startup"))
        for b in (self.btn_toggle, self.btn_open, self.btn_undo):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(refresh)
        actions.addWidget(taskmgr)
        card.add(actions)
        self.admin_note = label("", "Faint", wrap=True)
        card.add(self.admin_note)
        lay.addWidget(card)

        hist = GlassCard("Alterações recentes (com backup)", G.HISTORY)
        self.hist = make_table(["Data", "Alteração", "Situação"], stretch=1)
        self.hist.setMinimumHeight(160)
        self.hist.setSortingEnabled(False)
        hist.add(self.hist)
        lay.addWidget(hist)
        self._update_buttons()

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def load(self) -> None:
        self._loaded = True
        self.status.setText("Carregando...")
        run_task(startup_mod.list_startup, on_done=self._got, on_error=lambda e: self.status.setText("Erro"))

    def _got(self, items) -> None:
        self.items = items
        self.refresh_names()
        on = sum(1 for i in items if i.enabled)
        self.status.setText(f"{on} ativados · {len(items) - on} desativados")
        self.admin_note.setText("" if is_admin() else
                                "Itens de “todos os usuários” exigem administrador para alterar. "
                                "Use Configurações → Reiniciar como administrador, ou o Gerenciador de Tarefas.")
        self._load_history()

    def refresh_names(self) -> None:
        names = getattr(self.page, "store_names", {})
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            disp = it.display_name
            if it.kind == "store":
                fam = it.command.split(" ")[0]
                disp = names.get(fam, disp)
            name = SortItem(disp)
            name.setData(Qt.UserRole + 1, r)
            icon = file_icon(it.exe)
            if icon:
                name.setIcon(icon)
            name.setToolTip(it.command)
            status = SortItem("Ativado" if it.enabled else "Desativado", 0 if it.enabled else 1)
            status.setForeground(QColor("#34d399") if it.enabled else QColor("#94a3b8"))
            cells = [name, SortItem(it.publisher or "—"), status,
                     SortItem(it.source + (" 🛡" if it.needs_admin else "")), SortItem(it.command)]
            for c, item in enumerate(cells):
                t.setItem(r, c, item)
        t.setSortingEnabled(True)
        self._update_buttons()

    def selected(self) -> startup_mod.StartupItem | None:
        row = self.table.currentRow()
        if row < 0 or not self.table.selectedItems():
            return None
        idx = self.table.item(row, 0).data(Qt.UserRole + 1)
        return self.items[idx] if idx is not None and idx < len(self.items) else None

    def _update_buttons(self) -> None:
        it = self.selected()
        self.btn_toggle.setEnabled(bool(it))
        self.btn_toggle.setText("Ativar" if it and not it.enabled else "Desativar")
        self.btn_open.setEnabled(bool(it and it.exe))
        self.btn_undo.setEnabled(bool(regbackup.last_backups(1, "startup:")))

    def _menu(self, pos) -> None:
        it = self.selected()
        if not it:
            return
        m = QMenu(self)
        m.addAction("Ativar" if not it.enabled else "Desativar", self.toggle)
        m.addAction("Abrir local do arquivo", self.open_location).setEnabled(bool(it.exe))
        m.addAction("Copiar comando", lambda: QGuiApplication.clipboard().setText(it.command))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def open_location(self) -> None:
        it = self.selected()
        if it and it.exe:
            open_folder(it.exe)

    def toggle(self) -> None:
        it = self.selected()
        if not it:
            return
        enable = not it.enabled
        try:
            startup_mod.set_enabled(it, enable)
        except PermissionError:
            if ask(self, "Permissão necessária",
                    f"“{it.display_name}” é um item de todos os usuários. Alterá-lo exige administrador.",
                    "Deseja reabrir o PC Control Center como administrador?", "Reabrir como administrador"):
                if relaunch_as_admin():
                    from PySide6.QtWidgets import QApplication
                    QApplication.instance().setProperty("force_quit", True)
                    QApplication.instance().quit()
            return
        except OSError as e:
            QMessageBox.warning(self, "Inicialização", f"Não foi possível alterar: {e}")
            return
        self.status.setText(f"{it.display_name} {'ativado' if enable else 'desativado'}")
        self.refresh_names()
        self._load_history()

    def undo(self) -> None:
        rows = [r for r in regbackup.last_backups(20, "startup:") if not r[6]]
        if not rows:
            QMessageBox.information(self, "Desfazer", "Não há alterações para desfazer.")
            return
        bid, ts, *_rest, reason, _restored = rows[0]
        what = reason.split(":", 1)[1]
        if not ask(self, "Desfazer", f"Desfazer “{what}” ({datetime.fromtimestamp(ts):%d/%m %H:%M})?",
                    "O valor anterior do Registro será restaurado a partir do backup.", "Desfazer"):
            return
        try:
            regbackup.restore(bid)
        except PermissionError:
            QMessageBox.warning(self, "Desfazer", "Esta alteração exige administrador para ser desfeita.")
            return
        self.load()

    def _load_history(self) -> None:
        rows = regbackup.last_backups(15, "startup:")
        self.hist.setRowCount(len(rows))
        for r, (bid, ts, _h, _p, _n, reason, restored) in enumerate(rows):
            for c, text in enumerate([datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M"),
                                      reason.split(":", 1)[1], "desfeita" if restored else f"backup #{bid}"]):
                self.hist.setItem(r, c, QTableWidgetItem(text))
        self._update_buttons()
