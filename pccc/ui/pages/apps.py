"""Aplicativos e processos: programas instalados, processos em execução e inicialização."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QFileInfo, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileIconProvider, QHBoxLayout,
                               QHeaderView, QLineEdit, QMenu, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...apps import startup as startup_mod
from ...apps.installed import InstalledApp, list_installed, read_registry_apps, read_store_apps, \
    still_installed, uninstall_plan
from ...apps.processes import ProtectedProcessError, check_killable, terminate
from ...core import regbackup
from ...core.logger import log_operation
from ...core.winapi import is_admin, open_folder, relaunch_as_admin, shell_execute_wait, shell_open
from ...monitoring.collector import MonitorService
from ...monitoring.models import ProcessEntry, Snapshot
from ..components import GlassCard, ResponsiveGrid, Segmented, label, stat_block
from ..fmt import fmt_bytes, fmt_pct
from ..icons import G
from ..tasks import run_task
from .base import Page

_icon_provider = None
_icon_cache: dict[str, QIcon] = {}


def file_icon(path: str) -> QIcon | None:
    """Ícone do executável/ícone (cache). Retorna None se o arquivo não existe."""
    global _icon_provider
    if not path:
        return None
    path = path.split(",")[0].strip().strip('"')
    if path in _icon_cache:
        return _icon_cache[path]
    info = QFileInfo(path)
    if not info.exists() or info.isDir():
        _icon_cache[path] = None
        return None
    if _icon_provider is None:
        _icon_provider = QFileIconProvider()
    icon = _icon_provider.icon(info)
    _icon_cache[path] = icon
    return icon


class SortItem(QTableWidgetItem):
    """Item que ordena pelo valor numérico (UserRole) em vez do texto."""

    def __init__(self, text: str, sort_value=None) -> None:
        super().__init__(text)
        self.setData(Qt.UserRole, sort_value if sort_value is not None else text.lower())

    def __lt__(self, other) -> bool:
        a, b = self.data(Qt.UserRole), other.data(Qt.UserRole)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def make_table(headers: list[str], stretch: int = 0) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.verticalHeader().setDefaultSectionSize(32)
    t.setSortingEnabled(True)
    t.setWordWrap(False)              # sem quebra: caminhos longos são cortados no fim, não no meio
    t.setTextElideMode(Qt.ElideRight)
    t.sortByColumn(0, Qt.AscendingOrder)
    t.setContextMenuPolicy(Qt.CustomContextMenu)
    hh = t.horizontalHeader()
    hh.setHighlightSections(False)
    hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    for i in range(len(headers)):
        hh.setSectionResizeMode(i, QHeaderView.Stretch if i == stretch else QHeaderView.ResizeToContents)
    t.setMinimumHeight(420)
    return t


def _ask(parent, title: str, text: str, detail: str = "", danger_text: str = "Continuar") -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setInformativeText(detail)
    ok = box.addButton(danger_text, QMessageBox.AcceptRole)
    box.addButton("Cancelar", QMessageBox.RejectRole)
    box.setDefaultButton(box.buttons()[-1])  # padrão = Cancelar
    box.exec()
    return box.clickedButton() is ok


# ====================================================================== INSTALADOS
class InstalledView(QWidget):
    def __init__(self, page: "AppsPage") -> None:
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
            name.setData(Qt.UserRole + 1, id(a))
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
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(r, c, item)
        t.setSortingEnabled(cat_sort := self.category.currentData() != "__recent__")
        if not cat_sort:
            t.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
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
        return getattr(self, "_by_id", {}).get(item.data(Qt.UserRole + 1)) if item else None

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
        if not _ask(self, "Desinstalar programa", f"Desinstalar “{a.name}”?", detail, "Desinstalar"):
            return
        self.status.setText(f"Desinstalando {a.name}... (aguardando o desinstalador)")
        self.btn_uninstall.setEnabled(False)
        log_operation("app.uninstall.start", f"{a.name} {a.version} — {readable}")

        def work():
            if a.is_store:
                from ...apps.installed import store_uninstall_command
                from ...core.winapi import run_hidden
                out = run_hidden(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                                  store_uninstall_command(a.key)], timeout=300)
                code = 0
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


# ====================================================================== PROCESSOS
class ProcessesView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._entries: list[ProcessEntry] = []
        self._rows: list[list[ProcessEntry]] = []
        self._paused = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        summary = ResponsiveGrid(min_col_width=200, max_cols=4, spacing=12)
        self.sm = {}
        for key, title in (("apps", "Aplicativos abertos"), ("bg", "Em segundo plano"),
                           ("win", "Processos do Windows"), ("total", "Total / threads")):
            c = GlassCard()
            w, v = stat_block(title)
            v.setObjectName("BigValue")
            v.setStyleSheet("font-size: 18pt;")
            c.add(w)
            summary.add(c)
            self.sm[key] = v
        lay.addWidget(summary)

        card = GlassCard("Processos em execução", G.PROCESS)
        self.status = label("", "Badge")
        card.add_header_widget(self.status)
        bar = QHBoxLayout()
        self.kind = Segmented([("Aplicativo", "Aplicativos"), ("Segundo plano", "Segundo plano"),
                               ("Windows", "Windows"), ("", "Todos")], "")
        self.kind.changed.connect(lambda _k: self.render())
        bar.addWidget(self.kind)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar por nome, PID ou caminho...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.render())
        bar.addWidget(self.search, 1)
        self.group = QCheckBox("Agrupar por aplicativo")
        self.group.setChecked(True)
        self.group.toggled.connect(lambda _v: self.render())
        bar.addWidget(self.group)
        self.pause = QCheckBox("Pausar atualização")
        self.pause.toggled.connect(lambda v: setattr(self, "_paused", v))
        bar.addWidget(self.pause)
        card.add(bar)

        self.table = make_table(["Nome", "PID / qtd.", "Tipo", "CPU", "Memória", "Threads", "Janela / caminho"],
                                stretch=6)
        self.table.horizontalHeader().setSortIndicator(3, Qt.DescendingOrder)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.customContextMenuRequested.connect(self._menu)
        card.add(self.table, 1)

        actions = QHBoxLayout()
        self.btn_kill = QPushButton("Encerrar")
        self.btn_kill.setObjectName("Danger")
        self.btn_kill.clicked.connect(self.kill)
        self.btn_open = QPushButton("Abrir local do arquivo")
        self.btn_open.clicked.connect(self.open_location)
        actions.addWidget(self.btn_kill)
        actions.addWidget(self.btn_open)
        actions.addStretch(1)
        self.totals = label("", "Muted")
        actions.addWidget(self.totals)
        card.add(actions)
        card.add(label("CPU em % do total da máquina; memória = conjunto de trabalho privado. Processos "
                       "essenciais do Windows são protegidos e não podem ser encerrados por aqui.",
                       "Faint", wrap=True))
        lay.addWidget(card)
        self._update_buttons()

    def update_data(self, snap: Snapshot, force: bool = False) -> None:
        entries = snap.processes.all
        if not entries or (entries is self._entries and not force):
            return  # mesma leitura (processos atualizam a cada 2 s)
        self._entries = entries
        k = {"Aplicativo": 0, "Segundo plano": 0, "Windows": 0}
        apps = set()
        for e in entries:
            k[e.kind] = k.get(e.kind, 0) + 1
            if e.kind == "Aplicativo":
                apps.add(e.name.lower())
        self.sm["apps"].setText(f"{len(apps)}")
        self.sm["bg"].setText(str(k["Segundo plano"]))
        self.sm["win"].setText(str(k["Windows"]))
        self.sm["total"].setText(f"{snap.processes.total} / {snap.processes.threads:,}".replace(",", "."))
        if not self._paused:
            self.render()

    def _key(self, rows: list[ProcessEntry]) -> str:
        return rows[0].name.lower() if len(rows) > 1 or self.group.isChecked() else f"{rows[0].pid}"

    def render(self) -> None:
        kind = self.kind.current()
        q = self.search.text().strip().lower()
        sel = self.selected()
        sel_key = self._key(sel) if sel else None

        filtered = [e for e in self._entries
                    if (not kind or e.kind == kind)
                    and (not q or q in e.name.lower() or q == str(e.pid) or q in e.exe.lower()
                         or q in e.title.lower())]
        if self.group.isChecked():
            groups: dict[str, list[ProcessEntry]] = {}
            for e in filtered:
                groups.setdefault(e.name.lower(), []).append(e)
            rows = list(groups.values())
        else:
            rows = [[e] for e in filtered]
        self._rows = rows

        t = self.table
        sort_col = t.horizontalHeader().sortIndicatorSection()
        sort_order = t.horizontalHeader().sortIndicatorOrder()
        t.setSortingEnabled(False)
        t.setUpdatesEnabled(False)
        t.setRowCount(len(rows))
        cpu_total = mem_total = 0.0
        for r, group in enumerate(rows):
            first = group[0]
            cpu = sum(e.cpu for e in group)
            mem = sum(e.memory for e in group)
            thr = sum(e.threads for e in group)
            cpu_total += cpu
            mem_total += mem
            title = next((e.title for e in group if e.title), "")
            name = SortItem(first.name + (f"  ({len(group)})" if len(group) > 1 else ""), first.name.lower())
            name.setData(Qt.UserRole + 1, r)
            icon = file_icon(first.exe)
            if icon:
                name.setIcon(icon)
            pid_text = str(first.pid) if len(group) == 1 else f"{len(group)} processos"
            cells = [name, SortItem(pid_text, first.pid if len(group) == 1 else 10 ** 9 + len(group)),
                     SortItem(first.kind), SortItem(fmt_pct(cpu, 1), cpu), SortItem(fmt_bytes(mem), mem),
                     SortItem(str(thr), thr), SortItem(title or first.exe or "(protegido)")]
            for c, item in enumerate(cells):
                if c in (1, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 3 and cpu >= 25:
                    item.setForeground(QColor("#fb7185"))
                t.setItem(r, c, item)
        t.setSortingEnabled(True)
        t.sortItems(sort_col, sort_order)
        # restaura a seleção
        if sel_key is not None:
            for r in range(t.rowCount()):
                idx = t.item(r, 0).data(Qt.UserRole + 1)
                if idx is not None and idx < len(rows) and self._key(rows[idx]) == sel_key:
                    t.selectRow(r)
                    break
        t.setUpdatesEnabled(True)
        self.totals.setText(f"{len(filtered)} processos listados · CPU {fmt_pct(cpu_total, 1)} · "
                            f"memória {fmt_bytes(mem_total)}")
        self.status.setText("pausado" if self._paused else "atualiza a cada 2 s")
        self._update_buttons()

    def selected(self) -> list[ProcessEntry] | None:
        row = self.table.currentRow()
        if row < 0 or not self.table.selectedItems():
            return None
        item = self.table.item(row, 0)
        idx = item.data(Qt.UserRole + 1) if item else None
        return self._rows[idx] if idx is not None and idx < len(self._rows) else None

    def _update_buttons(self) -> None:
        sel = self.selected()
        self.btn_kill.setEnabled(bool(sel))
        self.btn_open.setEnabled(bool(sel and sel[0].exe))
        if sel:
            try:
                check_killable(sel[0])
                self.btn_kill.setToolTip("")
            except ProtectedProcessError as e:
                self.btn_kill.setEnabled(False)
                self.btn_kill.setToolTip(str(e))

    def _menu(self, pos) -> None:
        sel = self.selected()
        if not sel:
            return
        m = QMenu(self)
        m.addAction("Encerrar...", self.kill).setEnabled(self.btn_kill.isEnabled())
        m.addAction("Abrir local do arquivo", self.open_location).setEnabled(bool(sel[0].exe))
        m.addSeparator()
        if sel[0].exe:
            m.addAction("Copiar caminho", lambda: QGuiApplication.clipboard().setText(sel[0].exe))
        m.addAction("Pesquisar na web", lambda: shell_open(
            f"https://www.bing.com/search?q={sel[0].name}+processo"))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def open_location(self) -> None:
        sel = self.selected()
        if sel and sel[0].exe:
            open_folder(sel[0].exe)

    def kill(self) -> None:
        sel = self.selected()
        if not sel:
            return
        try:
            warn = check_killable(sel[0])
        except ProtectedProcessError as e:
            QMessageBox.warning(self, "Encerrar", str(e))
            return
        first = sel[0]
        n = len(sel)
        what = f"“{first.name}”" + (f" ({n} processos)" if n > 1 else f" (PID {first.pid})")
        detail = ("Dados não salvos nesse programa serão perdidos.\n\n"
                  + (f"⚠ {warn}\n\n" if warn else "")
                  + f"Memória em uso: {fmt_bytes(sum(e.memory for e in sel))}")
        if not _ask(self, "Encerrar processo", f"Encerrar {what}?", detail, "Encerrar"):
            return
        self.btn_kill.setEnabled(False)

        def done(result):
            ok, failed = result
            if failed:
                QMessageBox.warning(self, "Encerrar", "Alguns processos não foram encerrados:\n\n" +
                                    "\n".join(failed[:10]))
            self.status.setText(f"{len(ok)} encerrado(s)")

        run_task(terminate, sel, on_done=done)


# ===================================================================== INICIALIZAÇÃO
class StartupView(QWidget):
    def __init__(self, page: "AppsPage") -> None:
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
            if _ask(self, "Permissão necessária",
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
        if not _ask(self, "Desfazer", f"Desfazer “{what}” ({datetime.fromtimestamp(ts):%d/%m %H:%M})?",
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


# ========================================================================== PÁGINA
class AppsPage(Page):
    title = "Aplicativos e processos"
    subtitle = "Programas instalados, processos em execução e inicialização do Windows"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.store_names: dict[str, str] = {}
        self.tabs = Segmented([("installed", "Instalados"), ("procs", "Processos"), ("startup", "Inicialização")])
        self.header_right.addWidget(self.tabs)
        self.installed_view = InstalledView(self)
        self.processes_view = ProcessesView()
        self.startup_view = StartupView(self)
        self.views = {"installed": self.installed_view, "procs": self.processes_view, "startup": self.startup_view}
        for v in self.views.values():
            self.add(v)
        self.layout_.addStretch(1)
        self.current = "installed"
        self.tabs.changed.connect(self.switch)
        self.switch("installed", load=False)

    def switch(self, key: str, load: bool = True) -> None:
        self.current = key
        self.tabs.set_current(key)
        for k, v in self.views.items():
            v.setVisible(k == key)
        if not load:
            return
        if key == "installed":
            self.installed_view.ensure_loaded()
        elif key == "startup":
            self.startup_view.ensure_loaded()
        elif key == "procs":
            snap = MonitorService.instance().latest
            if snap:
                self.processes_view.update_data(snap, force=True)

    def on_shown(self) -> None:
        # Carrega o inventário só quando a página é aberta pela primeira vez.
        self.switch(self.current)

    def on_snapshot(self, snap: Snapshot) -> None:
        if self.current == "procs":
            self.processes_view.update_data(snap)
