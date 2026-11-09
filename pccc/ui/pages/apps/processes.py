"""Aba Processos: processos em execução, com proteção dos processos do sistema."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ....apps.processes import ProtectedProcessError, check_killable, terminate
from ....core.winapi import open_folder, shell_open
from ....monitoring.models import ProcessEntry, Snapshot
from ...components import GlassCard, ResponsiveGrid, Segmented, label, stat_block
from ...fmt import fmt_bytes, fmt_pct
from ...icons import G
from ...tasks import run_task
from ..common import SortItem, ask, file_icon, make_table


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
        if not ask(self, "Encerrar processo", f"Encerrar {what}?", detail, "Encerrar"):
            return
        self.btn_kill.setEnabled(False)

        def done(result):
            ok, failed = result
            if failed:
                QMessageBox.warning(self, "Encerrar", "Alguns processos não foram encerrados:\n\n" +
                                    "\n".join(failed[:10]))
            self.status.setText(f"{len(ok)} encerrado(s)")

        run_task(terminate, sel, on_done=done)
