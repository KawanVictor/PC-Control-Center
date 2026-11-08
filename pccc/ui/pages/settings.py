"""Configurações: aparência, comportamento, monitoramento, segurança e dados."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QMessageBox, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from ... import __version__
from ...core import autostart
from ...core.config import Settings
from ...core.database import Database
from ...core.logger import log_operation
from ...core.paths import data_dir
from ...core.winapi import is_admin, relaunch_as_admin
from ...monitoring.collector import MonitorService
from ..components import DataTable, GlassCard, ResponsiveGrid, Segmented, ToggleSwitch, label
from ..icons import G
from ..theme import ACCENT_LABELS, ACCENTS
from .base import Page
from ..qtutil import qapp


def _row(title: str, desc: str, control: QWidget) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 6, 0, 6)
    col = QVBoxLayout()
    col.setSpacing(1)
    col.addWidget(label(title))
    if desc:
        col.addWidget(label(desc, "Faint", wrap=True))
    h.addLayout(col, 1)
    h.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return w


class SettingsPage(Page):
    title = "Configurações"
    subtitle = "Personalize a aparência e o comportamento do PC Control Center"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.s = Settings.instance()
        grid = ResponsiveGrid(min_col_width=460, max_cols=2)

        # ------------------------------------------------------------ Aparência
        ap = GlassCard("Aparência", G.PERSONALIZE)
        mode = Segmented([("dark", "Escuro"), ("light", "Claro")], self.s.get("appearance.mode"))
        mode.changed.connect(lambda k: self.s.set("appearance.mode", k))
        ap.add(_row("Tema", "Modo escuro é o padrão", mode))

        sw = QWidget()
        sl = QHBoxLayout(sw)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        for key, (c1, c2) in ACCENTS.items():
            b = QPushButton()
            b.setObjectName("Swatch")
            b.setToolTip(ACCENT_LABELS[key])
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"QPushButton#Swatch {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                            f"stop:0 {c1}, stop:1 {c2}); border: 2px solid transparent; }}"
                            f"QPushButton#Swatch:hover {{ border-color: white; }}")
            b.clicked.connect(lambda _=False, k=key: self.s.set("appearance.accent", k))
            sl.addWidget(b)
        ap.add(_row("Cor de destaque", "", sw))

        self.transp = QSlider(Qt.Orientation.Horizontal)
        self.transp.setRange(0, 100)
        self.transp.setFixedWidth(200)
        self.transp.setValue(int(float(self.s.get("appearance.transparency", 0.7)) * 100))
        self.transp.valueChanged.connect(lambda v: self.s.set("appearance.transparency", v / 100))
        ap.add(_row("Transparência dos cartões", "Efeito de vidro (glassmorphism)", self.transp))

        anim = self._check("appearance.animations")
        ap.add(_row("Animações", "Transições de página e medidores animados", anim))
        grid.add(ap)

        # ---------------------------------------------------------- Comportamento
        gen = GlassCard("Inicialização e bandeja", G.POWER)
        self.autostart_cb = ToggleSwitch()
        self.autostart_cb.setChecked(autostart.is_enabled())
        self.autostart_cb.toggled.connect(self._toggle_autostart)
        gen.add(_row("Iniciar com o Windows", "Abre minimizado na bandeja ao entrar no Windows",
                     self.autostart_cb))
        gen.add(_row("Iniciar minimizado", "Ao abrir manualmente, ir direto para a bandeja",
                     self._check("general.start_minimized")))
        gen.add(_row("Minimizar para a bandeja", "O botão minimizar esconde a janela na bandeja",
                     self._check("general.minimize_to_tray")))
        gen.add(_row("Fechar para a bandeja", "O botão X mantém o monitoramento em segundo plano",
                     self._check("general.close_to_tray")))
        grid.add(gen)

        # ----------------------------------------------------------- Monitoramento
        mon = GlassCard("Monitoramento", G.PERFORMANCE)
        self.refresh = QComboBox()
        self._refresh_opts = [(500, "0,5 s"), (1000, "1 s"), (2000, "2 s"), (5000, "5 s")]
        for ms, text in self._refresh_opts:
            self.refresh.addItem(text, ms)
        cur = int(self.s.get("monitoring.refresh_ms", 1000))
        self.refresh.setCurrentIndex(next((i for i, (ms, _) in enumerate(self._refresh_opts) if ms == cur), 1))
        self.refresh.currentIndexChanged.connect(self._set_refresh)
        mon.add(_row("Intervalo de atualização", "Menor intervalo = mais preciso, mais uso de CPU", self.refresh))

        self.retention = QComboBox()
        for d in (7, 30, 90, 365):
            self.retention.addItem(f"{d} dias", d)
        self.retention.setCurrentIndex(max(0, self.retention.findData(int(self.s.get("monitoring.db_retention_days", 30)))))
        self.retention.currentIndexChanged.connect(
            lambda _i: self.s.set("monitoring.db_retention_days", self.retention.currentData()))
        mon.add(_row("Guardar histórico por", "Médias por minuto no banco SQLite local", self.retention))
        grid.add(mon)

        # -------------------------------------------------------------------- Rede
        net = GlassCard("Rede", G.NETWORK)
        net.add(_row("Monitorar latência continuamente",
                     "Envia 1 ping por segundo (~60 bytes) para medir latência, perda e quedas",
                     self._check("network.ping_enabled")))
        self.ping_host = QComboBox()
        self.ping_host.setEditable(True)
        self.ping_host.setMinimumWidth(170)
        for host, desc in (("1.1.1.1", "Cloudflare"), ("8.8.8.8", "Google"), ("208.67.222.222", "OpenDNS")):
            self.ping_host.addItem(host)
            self.ping_host.setItemData(self.ping_host.count() - 1, desc, Qt.ItemDataRole.ToolTipRole)
        self.ping_host.setCurrentText(self.s.get("network.ping_host", "1.1.1.1"))
        edit = self.ping_host.lineEdit()
        if edit is not None:
            edit.editingFinished.connect(self._set_ping_host)
        self.ping_host.activated.connect(lambda _i: self._set_ping_host())
        net.add(_row("Servidor de referência", "IP ou domínio usado para medir a internet", self.ping_host))
        grid.add(net)

        # --------------------------------------------------------------- Segurança
        sec = GlassCard("Permissões", G.SHIELD)
        admin = is_admin()
        status = label("Executando como administrador" if admin else "Executando como usuário padrão",
                       "BadgeAccent" if admin else "Badge")
        sec.add(_row("Nível de acesso", "O app só pede administrador quando uma ação exige", status))
        btn = QPushButton("Reiniciar como administrador")
        btn.setEnabled(not admin)
        btn.clicked.connect(self._elevate)
        sec.add(_row("Leituras avançadas", "Habilita temperatura dos discos e sensores ACPI restritos", btn))
        grid.add(sec)
        self.add(grid)

        # ----------------------------------------------------------- Operações
        ops = GlassCard("Registro de operações", G.LIST)
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.clicked.connect(self._load_ops)
        ops.add_header_widget(refresh_btn)
        self.ops_table = DataTable(["Data/hora", "Ação", "Detalhes", "Resultado"], stretch_col=2)
        self.ops_table.setMinimumHeight(200)
        ops.add(self.ops_table)
        self.add(ops)

        # --------------------------------------------------------------- Dados
        data = GlassCard("Dados e sobre", G.INFO)
        h = QHBoxLayout()
        open_btn = QPushButton("Abrir pasta de dados e logs")
        open_btn.clicked.connect(lambda: os.startfile(data_dir()))
        reset_btn = QPushButton("Restaurar configurações padrão")
        reset_btn.setObjectName("Danger")
        reset_btn.clicked.connect(self._reset)
        h.addWidget(open_btn)
        h.addWidget(reset_btn)
        h.addStretch(1)
        data.add(h)
        data.add(label(f"PC Control Center v{__version__}  ·  Dados em {data_dir()}", "Faint", wrap=True))
        self.add(data)
        self.layout_.addStretch(1)

    def _check(self, key: str) -> QCheckBox:
        cb = ToggleSwitch()
        cb.setChecked(bool(self.s.get(key)))
        cb.toggled.connect(lambda v: self.s.set(key, v))
        return cb

    def _toggle_autostart(self, enabled: bool) -> None:
        if autostart.set_enabled(enabled):
            self.s.set("general.start_with_windows", enabled)
        else:
            QMessageBox.warning(self, "Inicialização", "Não foi possível alterar a inicialização automática.")
            self.autostart_cb.blockSignals(True)
            self.autostart_cb.setChecked(autostart.is_enabled())
            self.autostart_cb.blockSignals(False)

    def _set_ping_host(self) -> None:
        host = self.ping_host.currentText().strip()
        # Aceita apenas IP/domínio simples (letras, números, ponto, hífen).
        if host and all(c.isalnum() or c in ".-" for c in host) and len(host) <= 253:
            self.s.set("network.ping_host", host)
        else:
            self.ping_host.setCurrentText(self.s.get("network.ping_host", "1.1.1.1"))

    def _set_refresh(self, _i: int) -> None:
        ms = self.refresh.currentData()
        self.s.set("monitoring.refresh_ms", ms)
        MonitorService.instance().set_interval(ms)

    def _elevate(self) -> None:
        res = QMessageBox.question(self, "Administrador",
                                   "O app será reaberto com permissão de administrador (o Windows pedirá "
                                   "confirmação). Continuar?")
        if res == QMessageBox.StandardButton.Yes and relaunch_as_admin():
            app = qapp()
            app.setProperty("force_quit", True)
            app.quit()

    def _reset(self) -> None:
        res = QMessageBox.question(self, "Restaurar padrões",
                                   "Todas as configurações voltarão ao padrão. O histórico não será apagado. Continuar?")
        if res == QMessageBox.StandardButton.Yes:
            self.s.reset()
            log_operation("settings.reset")
            QMessageBox.information(self, "Restaurar padrões",
                                    "Configurações restauradas. Algumas opções exibidas nesta página "
                                    "serão atualizadas na próxima abertura.")

    def _load_ops(self) -> None:
        try:
            rows = Database.instance().recent_operations(200)
        except Exception:
            rows = []
        self.ops_table.set_rows([[datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S"), a, d or "", r or ""]
                                 for ts, a, d, r in rows], align_right_from=99)

    def on_shown(self) -> None:
        self._load_ops()
