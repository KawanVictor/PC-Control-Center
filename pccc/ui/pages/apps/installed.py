"""Aba Instalados: lista de programas e desinstalação pelo desinstalador oficial."""
from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QMenu, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from ....apps.installed import InstalledApp, read_registry_apps, read_store_apps, still_installed, uninstall_plan
from ....core.logger import log_operation
from ....core.winapi import open_folder, shell_execute_wait, shell_open
from ...components import GlassCard, ResponsiveGrid, label, stat_block
from ...fmt import fmt_bytes
from ...icons import G
from ...tasks import run_task
from ..common import SortItem, ask, file_icon, make_table

if TYPE_CHECKING:
    from . import AppsPage


# ====================================================================== INSTALADOS
class InstalledView(QWidget):
    def __init__(self, page: AppsPage) -> None:
        super().__init__()
        self.page = page
        self.apps: list[InstalledApp] = []
        self._loaded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        summary = ResponsiveGrid(min_col_width=220, max_cols=4, spacing=12)
        self.sm = {}
        for key, title in (("total", "Programas instalados"), ("size", "Espaço informado"),
                           ("recent", "Instalados nos últimos 30 dias"), ("store", "Apps da Microsoft Store")):
            c = GlassCard()
            w, v = stat_block(title)
            v.setObjectName("BigValue")
            v.setStyleSheet("font-size: 18pt;")
            c.add(w)
            summary.add(c)
            self.sm[key] = v
        lay.addWidget(summary)

        card = GlassCard("Programas instalados", G.APPS)
        self.status = label("", "Badge")
        card.add_header_widget(self.status)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar por nome ou fabricante...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        bar.addWidget(self.search, 2)
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self.apply_filter)
        bar.addWidget(self.category, 1)
        self.origin = QComboBox()
        self.origin.addItems(["Todas as origens", "Programas (Win32)", "Microsoft Store"])
        self.origin.currentIndexChanged.connect(self.apply_filter)
        bar.addWidget(self.origin, 1)
        self.show_sys = QCheckBox("Componentes do sistema")
        self.show_sys.setToolTip("Mostra entradas marcadas como componente (normalmente ocultas pelo Windows)")
        self.show_sys.toggled.connect(self.apply_filter)
        bar.addWidget(self.show_sys)
        refresh = QPushButton("Atualizar")
        refresh.clicked.connect(self.load)
        bar.addWidget(refresh)
        card.add(bar)

        self.table = make_table(["Nome", "Versão", "Fabricante", "Tamanho", "Instalado em", "Categoria", "Origem"])
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _i: self.open_location())
        self.table.customContextMenuRequested.connect(self._menu)
        card.add(self.table, 1)

        actions = QHBoxLayout()
        self.btn_uninstall = QPushButton("Desinstalar")
        self.btn_uninstall.setObjectName("Danger")
        self.btn_uninstall.clicked.connect(self.uninstall)
        self.btn_open = QPushButton("Abrir local dos arquivos")
        self.btn_open.clicked.connect(self.open_location)
        self.btn_settings = QPushButton("Abrir em Configurações do Windows")
        self.btn_settings.clicked.connect(lambda: shell_open("ms-settings:appsfeatures"))
        actions.addWidget(self.btn_uninstall)
        actions.addWidget(self.btn_open)
        actions.addStretch(1)
        actions.addWidget(self.btn_settings)
        card.add(actions)
        card.add(label("A desinstalação usa sempre o desinstalador oficial do programa (ou MsiExec / "
                       "Remove-AppxPackage). O PC Control Center não apaga arquivos nem chaves do Registro.",
                       "Faint", wrap=True))
        lay.addWidget(card)
        self._update_buttons()

    # ------------------------------------------------------------- carregamento
    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def load(self) -> None:
        self._loaded = True
        self.status.setText("Carregando...")
        # Registro é instantâneo; a Store (PowerShell) leva alguns segundos — chega depois.
        run_task(read_registry_apps, on_done=self._got_registry, on_error=self._error)

    def _got_registry(self, apps: list[InstalledApp]) -> None:
        self.apps = sorted(apps, key=lambda a: a.name.lower())
        self._rebuild_categories()
        self.apply_filter()
        self.status.setText("Carregando apps da Microsoft Store...")
        run_task(read_store_apps, on_done=self._got_store, on_error=self._error)

    def _got_store(self, store: list[InstalledApp]) -> None:
        self.apps = sorted([a for a in self.apps if not a.is_store] + store, key=lambda a: a.name.lower())
        self._rebuild_categories()
        self.apply_filter()
        self.status.setText(f"Atualizado às {datetime.now():%H:%M}")
        self.page.store_names = {a.extra.get("family", ""): a.name for a in store}
        self.page.startup_view.refresh_names()

    def _error(self, msg: str) -> None:
        self.status.setText("Erro ao carregar")
        QMessageBox.warning(self, "Aplicativos", f"Não foi possível listar os programas:\n{msg}")

    def _rebuild_categories(self) -> None:
        current = self.category.currentData()
        cats = sorted({a.category for a in self.apps})
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("Todas as categorias", "")
        self.category.addItem("★ Instalados recentemente (30 dias)", "__recent__")
        for c in cats:
            n = sum(1 for a in self.apps if a.category == c)
            self.category.addItem(f"{c} ({n})", c)
        idx = self.category.findData(current)
        self.category.setCurrentIndex(max(0, idx))
        self.category.blockSignals(False)

    # ------------------------------------------------------------------ filtro
    def _visible(self) -> list[InstalledApp]:
        q = self.search.text().strip().lower()
        cat = self.category.currentData() or ""
        origin = self.origin.currentIndex()
        recent_cut = time.time() - 30 * 86400
        out = []
        for a in self.apps:
            if a.system_component and not self.show_sys.isChecked():
                continue
            if origin == 1 and a.is_store or origin == 2 and not a.is_store:
                continue
            if cat == "__recent__":
                if not a.install_date or a.install_date < recent_cut:
                    continue
            elif cat and a.category != cat:
                continue
            if q and q not in a.name.lower() and q not in a.publisher.lower():
                continue
            out.append(a)
        if cat == "__recent__":
            out.sort(key=lambda a: -(a.install_date or 0))
        return out

    def apply_filter(self) -> None:
        apps = self._visible()
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(apps))
        for r, a in enumerate(apps):
            name = SortItem(a.name)
            name.setData(Qt.ItemDataRole.UserRole + 1, id(a))
            icon = file_icon(a.icon_path) if not a.is_store else None
            if icon:
                name.setIcon(icon)
            name.setToolTip(f"{a.name}\n{a.publisher}\n{a.best_location()}")
            date = datetime.fromtimestamp(a.install_date).strftime("%d/%m/%Y") if a.install_date else "—"
            cells = [name, SortItem(a.version), SortItem(a.publisher or "—"),
                     SortItem(fmt_bytes(a.size) if a.size else "—", a.size),
                     SortItem(date, a.install_date or 0), SortItem(a.category), SortItem(a.source)]
            for c, item in enumerate(cells):
                if c in (3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                t.setItem(r, c, item)
        t.setSortingEnabled(cat_sort := self.category.currentData() != "__recent__")
        if not cat_sort:
            t.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self._by_id = {id(a): a for a in apps}

        visible_all = [a for a in self.apps if not a.system_component]
        recent = [a for a in visible_all if a.install_date and a.install_date > time.time() - 30 * 86400]
        self.sm["total"].setText(str(len(visible_all)))
        self.sm["size"].setText(fmt_bytes(sum(a.size for a in visible_all)))
        self.sm["recent"].setText(str(len(recent)))
        self.sm["store"].setText(str(sum(1 for a in visible_all if a.is_store)))
        self._update_buttons()

    def selected(self) -> InstalledApp | None:
        row = self.table.currentRow()
        if row < 0 or not self.table.selectedItems():
            return None
        item = self.table.item(row, 0)
        return getattr(self, "_by_id", {}).get(item.data(Qt.ItemDataRole.UserRole + 1)) if item else None

    def _update_buttons(self) -> None:
        a = self.selected()
        self.btn_uninstall.setEnabled(bool(a and a.can_uninstall))
        self.btn_open.setEnabled(bool(a and a.best_location()))

    def _menu(self, pos) -> None:
        a = self.selected()
        if not a:
            return
        m = QMenu(self)
        m.addAction("Desinstalar...", self.uninstall).setEnabled(a.can_uninstall)
        m.addAction("Abrir local dos arquivos", self.open_location).setEnabled(bool(a.best_location()))
        m.addSeparator()
        m.addAction("Copiar nome", lambda: QGuiApplication.clipboard().setText(a.name))
        if a.uninstall_cmd:
            m.addAction("Copiar comando de desinstalação",
                        lambda: QGuiApplication.clipboard().setText(a.uninstall_cmd))
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ ações
    def open_location(self) -> None:
        a = self.selected()
        if a and not open_folder(a.best_location()):
            QMessageBox.information(self, "Abrir local", "A pasta deste programa não foi encontrada.")

    def uninstall(self) -> None:
        a = self.selected()
        if not a:
            return
        try:
            exe, args, readable = uninstall_plan(a)
        except ValueError as e:
            QMessageBox.warning(self, "Desinstalar", str(e))
            return
        warnings = []
        if a.is_shared_component:
            warnings.append("⚠ Este parece ser um componente compartilhado (runtime/driver). Outros programas "
                            "podem depender dele e deixar de funcionar.")
        if a.system_component:
            warnings.append("⚠ Marcado pelo fabricante como componente do sistema.")
        detail = (f"Fabricante: {a.publisher or '—'}\nVersão: {a.version or '—'}\n\n"
                  f"Será executado o desinstalador oficial:\n{readable}\n\n"
                  "O desinstalador pode pedir confirmação e permissão de administrador. "
                  "Arquivos pessoais e restos deixados pelo programa não são apagados pelo PC Control Center."
                  + ("\n\n" + "\n".join(warnings) if warnings else ""))
        if not ask(self, "Desinstalar programa", f"Desinstalar “{a.name}”?", detail, "Desinstalar"):
            return
        self.status.setText(f"Desinstalando {a.name}... (aguardando o desinstalador)")
        self.btn_uninstall.setEnabled(False)
        log_operation("app.uninstall.start", f"{a.name} {a.version} — {readable}")

        def work():
            if a.is_store:
                from ....apps.installed import store_uninstall_command
                from ....core.winapi import run_hidden
                out = run_hidden(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                                  store_uninstall_command(a.key)], timeout=300)
                code: int | None = 0
            else:
                code = shell_execute_wait(exe, args)
                out = ""
            # Alguns desinstaladores abrem um processo filho e saem na hora: espera um pouco.
            for _ in range(10):
                if not still_installed(a):
                    return code, False, out
                time.sleep(1)
            return code, True, out

        def done(result):
            code, remains, out = result
            if code is None:
                msg, res = "O desinstalador não foi iniciado (a permissão pode ter sido negada).", "cancelado"
            elif remains:
                msg, res = ("O desinstalador terminou, mas o programa ainda aparece como instalado. "
                            "A desinstalação pode ter sido cancelada ou ainda estar em andamento."), "pendente"
            else:
                msg, res = f"“{a.name}” foi desinstalado.", "ok"
            log_operation("app.uninstall.end", f"{a.name} código={code}", res)
            QMessageBox.information(self, "Desinstalar", msg)
            self.load()

        run_task(work, on_done=done, on_error=lambda e: (self.status.setText("Erro"),
                                                          QMessageBox.warning(self, "Desinstalar", e)))
