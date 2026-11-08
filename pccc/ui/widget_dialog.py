"""Diálogo de configuração de um widget, com pré-visualização ao vivo no próprio widget.

As mudanças aparecem na hora; "Cancelar" restaura a configuração anterior.
"""
from __future__ import annotations

import copy
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from ..widgets import weather as wx
from ..widgets.base import WidgetConfig
from ..widgets.window import DesktopWidgetWindow
from .tasks import run_task
from .theme import ACCENTS, ThemeManager

REFRESH = [(500, "0,5 s"), (1000, "1 s"), (2000, "2 s"), (5000, "5 s"), (10_000, "10 s"),
           (30_000, "30 s"), (60_000, "1 min")]
LAYERS = [("bottom", "Na área de trabalho (atrás das janelas)"), ("normal", "Normal"),
          ("top", "Sempre visível (acima de tudo)")]


class ColorButton(QPushButton):
    def __init__(self, color: str, allow_theme: bool = False, on_change=None) -> None:
        super().__init__()
        self._allow_theme = allow_theme
        self._on_change = on_change
        self.setFixedWidth(130)
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, color: str) -> None:
        self.color = color
        if not color:
            self.setText("Cor do tema")
            t = ThemeManager.instance().theme
            self.setStyleSheet(f"QPushButton {{ border-left: 14px solid {t.accent}; }}")
        else:
            self.setText(color.upper())
            self.setStyleSheet(f"QPushButton {{ border-left: 14px solid {color}; }}")

    def _pick(self) -> None:
        start = QColor(self.color or ThemeManager.instance().theme.accent)
        c = QColorDialog.getColor(start, self, "Escolher cor")
        if c.isValid():
            self.set_color(c.name())
            if self._on_change:
                self._on_change(self.color)


class WidgetConfigDialog(QDialog):
    def __init__(self, win: DesktopWidgetWindow, parent=None) -> None:
        super().__init__(parent)
        self.win = win
        self.cfg: WidgetConfig = win.cfg
        self._backup = copy.deepcopy(self.cfg.to_dict())
        self.setWindowTitle(f"Configurar — {win.renderer.title}")
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        title = QLabel(win.renderer.title)
        title.setObjectName("SectionTitle")
        lay.addWidget(title)
        desc = QLabel(win.renderer.description)
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        # cor de destaque: tema ou personalizada
        accent_row = QHBoxLayout()
        self.accent_btn = ColorButton(self.cfg.accent, True, lambda c: self._set("accent", c))
        accent_row.addWidget(self.accent_btn)
        for _key, (c1, _c2) in list(ACCENTS.items())[:5]:
            b = QPushButton()
            b.setFixedSize(22, 22)
            b.setStyleSheet(f"QPushButton {{ background: {c1}; border-radius: 11px; border: none; }}")
            b.clicked.connect(lambda _=False, c=c1: (self.accent_btn.set_color(c), self._set("accent", c)))
            accent_row.addWidget(b)
        theme_btn = QPushButton("Tema")
        theme_btn.clicked.connect(lambda: (self.accent_btn.set_color(""), self._set("accent", "")))
        accent_row.addWidget(theme_btn)
        accent_row.addStretch(1)
        form.addRow("Cor de destaque", self._wrap(accent_row))

        self.bg_btn = ColorButton(self.cfg.bg, on_change=lambda c: self._set("bg", c))
        form.addRow("Cor do fundo", self.bg_btn)
        self.opacity = self._slider(0, 100, int(self.cfg.bg_opacity * 100),
                                    lambda v: self._set("bg_opacity", v / 100), "%")
        form.addRow("Opacidade do fundo", self.opacity)
        self.text_btn = ColorButton(self.cfg.text, on_change=lambda c: self._set("text", c))
        form.addRow("Cor do texto", self.text_btn)

        bw, _bh = win.renderer.base_size
        self.size_slider = self._slider(50, 300, int(round((self.cfg.width or bw) / bw * 100)),
                                        lambda v: self._set("width", int(bw * v / 100)), "%")
        form.addRow("Tamanho", self.size_slider)
        self.font_slider = self._slider(70, 150, int(self.cfg.font_scale * 100),
                                        lambda v: self._set("font_scale", v / 100), "%")
        form.addRow("Tamanho da fonte", self.font_slider)

        self.refresh = QComboBox()
        for ms, text in REFRESH:
            self.refresh.addItem(text, ms)
        idx = min(range(len(REFRESH)), key=lambda i: abs(REFRESH[i][0] - self.cfg.refresh_ms))
        self.refresh.setCurrentIndex(idx)
        self.refresh.currentIndexChanged.connect(lambda _i: self._set("refresh_ms", self.refresh.currentData()))
        form.addRow("Atualizar a cada", self.refresh)

        self.layer = QComboBox()
        for k, text in LAYERS:
            self.layer.addItem(text, k)
        self.layer.setCurrentIndex(max(0, self.layer.findData(self.cfg.layer)))
        self.layer.currentIndexChanged.connect(self._set_layer)
        form.addRow("Camada", self.layer)

        self.locked = QCheckBox("Impedir mover e redimensionar")
        self.locked.setChecked(self.cfg.locked)
        self.locked.toggled.connect(lambda v: self._set("locked", v))
        form.addRow("Bloquear", self.locked)
        lay.addLayout(form)

        specific = self._specific_options()
        if specific is not None:
            sec = QLabel("Opções deste widget")
            sec.setObjectName("SectionTitle")
            lay.addWidget(sec)
            lay.addWidget(specific)

        tip = QLabel("Dicas: arraste para mover · canto inferior direito ou Ctrl + roda do mouse para redimensionar "
                     "· clique duplo abre esta janela.")
        tip.setObjectName("Faint")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Salvar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    def _slider(self, lo, hi, value, on_change, suffix="") -> QWidget:
        row = QHBoxLayout()
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(max(lo, min(hi, value)))
        lbl = QLabel(f"{s.value()}{suffix}")
        lbl.setFixedWidth(46)
        s.valueChanged.connect(lambda v: (lbl.setText(f"{v}{suffix}"), on_change(v)))
        row.addWidget(s, 1)
        row.addWidget(lbl)
        return self._wrap(row)

    def _set(self, key: str, value) -> None:
        setattr(self.cfg, key, value)
        self.win.restyle()

    def _opt(self, key: str, value) -> None:
        self.cfg.options[key] = value
        self.win.restyle()

    def _set_layer(self, _i) -> None:
        self.cfg.layer = self.layer.currentData()
        self.win.apply_layer()

    # ---------------------------------------------------- opções específicas
    def _check(self, form: QFormLayout, key: str, text: str) -> None:
        cb = QCheckBox(text)
        cb.setChecked(bool(self.cfg.options.get(key)))
        cb.toggled.connect(lambda v: self._opt(key, v))
        form.addRow("", cb)

    def _choice(self, form: QFormLayout, key: str, label: str, choices: list[tuple]) -> None:
        cb = QComboBox()
        for v, text in choices:
            cb.addItem(text, v)
        cb.setCurrentIndex(max(0, cb.findData(self.cfg.options.get(key))))
        cb.currentIndexChanged.connect(lambda _i: self._opt(key, cb.currentData()))
        form.addRow(label, cb)

    def _specific_options(self) -> QWidget | None:
        t = self.cfg.type
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if t == "clock":
            self._check(form, "h24", "Formato 24 horas")
            self._check(form, "seconds", "Mostrar segundos")
            self._check(form, "show_date", "Mostrar data")
        elif t == "calendar":
            self._check(form, "holidays", "Destacar feriados nacionais")
            self._choice(form, "week_start", "Semana começa", [("dom", "Domingo"), ("seg", "Segunda-feira")])
        elif t == "netspeed":
            self._choice(form, "bits", "Unidade", [(True, "Megabits (Mbps) — padrão de internet"),
                                                    (False, "Megabytes (MB/s) — padrão de downloads")])
        elif t == "processes":
            self._choice(form, "sort", "Ordenar por", [("cpu", "Uso de CPU"), ("mem", "Uso de memória")])
        elif t == "temps":
            for key, label in (("warn", "Alerta (âmbar) a partir de"), ("hot", "Crítico (vermelho) a partir de")):
                sp = QSpinBox()
                sp.setRange(30, 110)
                sp.setSuffix(" °C")
                sp.setValue(int(self.cfg.options.get(key, 70)))
                sp.valueChanged.connect(lambda v, k=key: self._opt(k, v))
                form.addRow(label, sp)
        elif t == "weather":
            row = QHBoxLayout()
            self.city = QLineEdit(self.cfg.options.get("city", ""))
            self.city.setPlaceholderText("Ex.: Recife, Curitiba, Lisboa")
            btn = QPushButton("Buscar")
            btn.clicked.connect(self._geocode)
            self.city.returnPressed.connect(self._geocode)
            row.addWidget(self.city, 1)
            row.addWidget(btn)
            form.addRow("Cidade", self._wrap(row))
            self.city_status = QLabel(self.cfg.options.get("label", ""))
            self.city_status.setObjectName("Muted")
            form.addRow("", self.city_status)
        elif t == "shortcuts":
            form.addRow(self._shortcuts_editor())
        elif t == "visualizer":
            self._choice(form, "style", "Estilo", [("bars", "Barras"), ("mirror", "Espelhado (centro)")])
            self._choice(form, "bands", "Quantidade de barras", [(16, "16"), (24, "24"), (32, "32"), (48, "48")])
        elif t == "volume":
            self._choice(form, "apps", "Apps na lista", [(0, "Nenhum"), (1, "1"), (2, "2"), (3, "3")])
        else:
            return None
        return box

    def _geocode(self) -> None:
        name = self.city.text().strip()
        if not name:
            return
        self.city_status.setText("Procurando...")

        def done(res):
            if not res:
                self.city_status.setText("Cidade não encontrada.")
                return
            self.cfg.options.update({"city": name, **res})
            self.city_status.setText(f"✓ {res['label']}")
            self.win.restyle()

        run_task(wx.geocode, name, on_done=done,
                 on_error=lambda e: self.city_status.setText(f"Sem conexão: {e}"))

    def _shortcuts_editor(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        self.sc_list = QListWidget()
        self.sc_list.setMinimumHeight(150)
        self._fill_shortcuts()
        v.addWidget(self.sc_list)
        row = QHBoxLayout()
        for text, fn in (("Adicionar programa...", self._add_program), ("Adicionar pasta...", self._add_folder),
                         ("Adicionar site...", self._add_site), ("Remover", self._remove_sc),
                         ("↑", lambda: self._move_sc(-1)), ("↓", lambda: self._move_sc(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        cols = QSpinBox()
        cols.setRange(2, 8)
        cols.setPrefix("Colunas: ")
        cols.setValue(int(self.cfg.options.get("columns", 4)))
        cols.valueChanged.connect(lambda n: self._opt("columns", n))
        v.addWidget(cols)
        return w

    def _fill_shortcuts(self) -> None:
        self.sc_list.clear()
        for it in self.cfg.options.get("items", []):
            item = QListWidgetItem(f"{it.get('name')}  —  {it.get('path')}")
            self.sc_list.addItem(item)

    def _items(self) -> list:
        return self.cfg.options.setdefault("items", [])

    def _shortcuts_changed(self) -> None:
        self._fill_shortcuts()
        self.win.restyle()

    def _add_program(self) -> None:
        start = os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs")
        path, _ = QFileDialog.getOpenFileName(self, "Escolher programa ou atalho", start,
                                              "Programas e atalhos (*.exe *.lnk *.url *.bat);;Todos (*.*)")
        if path:
            self._items().append({"name": os.path.splitext(os.path.basename(path))[0], "path": os.path.normpath(path)})
            self._shortcuts_changed()

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Escolher pasta")
        if path:
            self._items().append({"name": os.path.basename(path) or path, "path": os.path.normpath(path)})
            self._shortcuts_changed()

    def _add_site(self) -> None:
        url, ok = QInputDialog.getText(self, "Adicionar site", "Endereço (https://...):")
        url = url.strip()
        if ok and url:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            name = url.split("//", 1)[1].split("/")[0].replace("www.", "")
            self._items().append({"name": name, "path": url})
            self._shortcuts_changed()

    def _remove_sc(self) -> None:
        r = self.sc_list.currentRow()
        if 0 <= r < len(self._items()):
            self._items().pop(r)
            self._shortcuts_changed()

    def _move_sc(self, d: int) -> None:
        r = self.sc_list.currentRow()
        items = self._items()
        if 0 <= r < len(items) and 0 <= r + d < len(items):
            items[r], items[r + d] = items[r + d], items[r]
            self._shortcuts_changed()
            self.sc_list.setCurrentRow(r + d)

    # ----------------------------------------------------------------- fim
    def reject(self) -> None:
        restored = WidgetConfig.from_dict(self._backup)
        for k in self._backup:
            setattr(self.cfg, k, getattr(restored, k))
        self.win.apply_layer()
        self.win.restyle()
        super().reject()
