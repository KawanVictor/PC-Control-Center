"""Aba Atalhos: atalhos na área de trabalho e no menu Iniciar."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit, QMessageBox, QPushButton,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ....personalization import changes, shortcuts
from ...components import ResponsiveGrid, label
from ...icons import G
from ..common import ask, make_table


class ShortcutsTab:
    """Parte da PersonalizationPage (usa self.add, self._section, self.changed...)."""

    # =================================================================== ATALHOS
    def _build_shortcuts(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=480, max_cols=2)
        form = self._section("Criar atalho", "")
        g = QGridLayout()
        g.setVerticalSpacing(8)
        self.sc_name = QLineEdit()
        self.sc_name.setPlaceholderText("Nome do atalho")
        self.sc_target = QLineEdit()
        self.sc_target.setPlaceholderText("Programa, pasta ou site (https://...)")
        self.sc_args = QLineEdit()
        self.sc_args.setPlaceholderText("Argumentos (opcional)")
        self.sc_where = QComboBox()
        self.sc_where.addItem("Área de trabalho", "desktop")
        self.sc_where.addItem("Menu Iniciar", "start")
        pick_file = QPushButton("Programa...")
        pick_file.clicked.connect(self._pick_target_file)
        pick_dir = QPushButton("Pasta...")
        pick_dir.clicked.connect(self._pick_target_dir)
        g.addWidget(label("Nome"), 0, 0)
        g.addWidget(self.sc_name, 0, 1, 1, 3)
        g.addWidget(label("Destino"), 1, 0)
        g.addWidget(self.sc_target, 1, 1)
        g.addWidget(pick_file, 1, 2)
        g.addWidget(pick_dir, 1, 3)
        g.addWidget(label("Argumentos"), 2, 0)
        g.addWidget(self.sc_args, 2, 1, 1, 3)
        g.addWidget(label("Criar em"), 3, 0)
        g.addWidget(self.sc_where, 3, 1)
        form.add(g)
        create = QPushButton("Criar atalho")
        create.setObjectName("Primary")
        create.clicked.connect(self._create_custom)
        form.add(create)
        grid.add(form)

        tpl = self._section("Modelos prontos", G.LIST)
        for name, target, args, icon, desc in shortcuts.TEMPLATES:
            r = QHBoxLayout()
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(name))
            col.addWidget(label(desc, "Faint"))
            r.addLayout(col, 1)
            b = QPushButton("Criar na área de trabalho")
            b.clicked.connect(lambda _=False, a=(name, target, args, icon): self._create(*a))
            r.addWidget(b)
            tpl.add(r)
        r = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label("PC Control Center"))
        col.addWidget(label("Atalho para este aplicativo", "Faint"))
        r.addLayout(col, 1)
        b = QPushButton("Criar na área de trabalho")
        b.clicked.connect(lambda: self._create("PC Control Center", *shortcuts.app_target(), ""))
        r.addWidget(b)
        tpl.add(r)
        grid.add(tpl)
        lay.addWidget(grid)

        created = self._section("Atalhos criados pelo PC Control Center", G.HISTORY)
        self.created_table = make_table(["Data", "Atalho", "Destino"], stretch=2)
        self.created_table.setMinimumHeight(170)
        created.add(self.created_table)
        rm = QPushButton("Remover atalho selecionado")
        rm.setObjectName("Danger")
        rm.clicked.connect(self._remove_created)
        created.add(rm)
        lay.addWidget(created)
        return w

    def _pick_target_file(self) -> None:
        start = os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs")
        path, _ = QFileDialog.getOpenFileName(self, "Escolher programa", start, "Programas (*.exe *.lnk *.bat *.cmd);;"
                                                                                "Todos os arquivos (*.*)")
        if path:
            self.sc_target.setText(os.path.normpath(path))
            if not self.sc_name.text():
                self.sc_name.setText(os.path.splitext(os.path.basename(path))[0])

    def _pick_target_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Escolher pasta")
        if path:
            self.sc_target.setText(os.path.normpath(path))
            if not self.sc_name.text():
                self.sc_name.setText(os.path.basename(path))

    def _create_custom(self) -> None:
        target = self.sc_target.text().strip()
        if target and "://" not in target and "." in target and " " not in target and not os.path.exists(target):
            target = "https://" + target   # "google.com" → site
        self._create(self.sc_name.text().strip() or "Atalho", target, self.sc_args.text().strip(), "",
                     self.sc_where.currentData())

    def _create(self, name, target, args, icon, where="desktop") -> None:
        try:
            shortcuts.create_shortcut(name, target, args, where, icon)
        except Exception as e:
            QMessageBox.warning(self, "Criar atalho", str(e))
            return
        self._load_created()
        self.changed()

    def _load_created(self) -> None:
        rows = [h for h in changes.history(300) if h["kind"] == "shortcut" and not h["restored"]
                and os.path.exists(h["data"].get("path", ""))]
        self._created = rows
        t = self.created_table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for r, h in enumerate(rows):
            for c, text in enumerate([datetime.fromtimestamp(h["ts"]).strftime("%d/%m/%Y %H:%M"),
                                      os.path.basename(h["data"]["path"]), h["data"].get("target", "")]):
                t.setItem(r, c, QTableWidgetItem(text))

    def _remove_created(self) -> None:
        r = self.created_table.currentRow()
        if r < 0 or r >= len(getattr(self, "_created", [])):
            return
        h = self._created[r]
        if ask(self, "Remover atalho", f"Remover “{os.path.basename(h['data']['path'])}”?",
                f"Será apagado exatamente este arquivo:\n{h['data']['path']}\n\n"
                "O programa, a pasta ou o site de destino não são afetados.", "Remover"):
            try:
                changes.undo(h["id"])
            except PermissionError as e:
                QMessageBox.warning(self, "Remover atalho", str(e))
            self._load_created()
            self._load_history()
