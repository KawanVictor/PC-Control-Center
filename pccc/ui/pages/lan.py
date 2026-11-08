"""Aba "Dispositivos na rede" da página Rede e Wi-Fi."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QMenu, QPushButton,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...core.config import Settings
from ...core.winapi import shell_open
from ...network import devices as lan
from ..components import GlassCard, ResponsiveGrid, ToggleSwitch, label, stat_block
from ..icons import G
from .common import ask, make_table


def _ago(ts: float) -> str:
    if not ts:
        return "—"
    d = time.time() - ts
    if d < 120:
        return "agora"
    if d < 3600:
        return f"há {int(d // 60)} min"
    if d < 86400:
        return f"há {int(d // 3600)} h"
    return datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")


class _Item(QTableWidgetItem):
    """Item com chave de ordenação própria (IP numérico, data...)."""

    def __init__(self, text: str, key=None) -> None:
        super().__init__(text)
        self.key = key if key is not None else text.lower()

    def __lt__(self, other) -> bool:
        try:
            return self.key < other.key
        except TypeError:
            return str(self.key) < str(other.key)


class DevicesView(QWidget):
    COLS = ["", "Nome", "Tipo provável", "IP", "Fabricante", "MAC", "Visto", "Situação"]

    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        self.w = lan.LanWatcher.instance()
        s = Settings.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        top = ResponsiveGrid(min_col_width=440, max_cols=2)
        info = GlassCard("Sua rede", G.NETWORK)
        self.net_lbl = label("Clique em “Procurar aparelhos”.", "Value", wrap=True)
        info.add(self.net_lbl)
        stats = QHBoxLayout()
        b1, self.n_online = stat_block("Conectados agora")
        b2, self.n_known = stat_block("Conhecidos")
        b3, self.n_unknown = stat_block("Não identificados")
        for b in (b1, b2, b3):
            stats.addWidget(b)
        info.add(stats)
        row = QHBoxLayout()
        self.scan_btn = QPushButton("Procurar aparelhos")
        self.scan_btn.setObjectName("Primary")
        self.scan_btn.clicked.connect(lambda: self.w.scan())
        row.addWidget(self.scan_btn)
        self.router_btn = QPushButton("Abrir página do roteador")
        self.router_btn.setToolTip("Onde se troca a senha do Wi-Fi e se bloqueiam aparelhos")
        self.router_btn.clicked.connect(self._open_router)
        row.addWidget(self.router_btn)
        row.addStretch(1)
        info.add(row)
        self.status = label("", "Muted", wrap=True)
        info.add(self.status)
        top.add(info)

        watch = GlassCard("Vigiar a rede", G.SHIELD)
        self.watch = ToggleSwitch()
        self.watch.setChecked(bool(s.get("network.devices_watch", False)))
        self.watch.toggled.connect(self._toggle_watch)
        wr = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label("Avisar quando um aparelho novo entrar na rede"))
        col.addWidget(label("Procura de tempos em tempos enquanto o app estiver aberto (inclusive na bandeja). "
                            "O aviso vem pela Central de alertas.", "Faint", wrap=True))
        wr.addLayout(col, 1)
        wr.addWidget(self.watch)
        watch.add(wr)
        ir = QHBoxLayout()
        ir.addWidget(label("Procurar a cada"))
        self.interval = QComboBox()
        for m in (5, 15, 30, 60):
            self.interval.addItem(f"{m} minutos", m)
        self.interval.setCurrentIndex(max(0, self.interval.findData(int(s.get("network.devices_interval_min", 15)))))
        self.interval.currentIndexChanged.connect(self._set_interval)
        ir.addWidget(self.interval)
        ir.addStretch(1)
        watch.add(ir)
        watch.add(label("Dica: marque seus aparelhos como “Conhecido” (botão direito na lista). Um aparelho "
                        "“Não identificado” que você não reconhece pode ser alguém usando o seu Wi-Fi — nesse caso, "
                        "troque a senha na página do roteador.", "Faint", wrap=True))
        top.add(watch)
        lay.addWidget(top)

        card = GlassCard("Aparelhos", G.DEVICES)
        self.table = make_table(self.COLS, stretch=1)
        self.table.setMinimumHeight(360)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.cellDoubleClicked.connect(lambda r, _c: self._rename(r))
        card.add(self.table)
        card.add(label("Aparelhos em modo de economia (celular com a tela apagada, por exemplo) às vezes não "
                       "respondem — procure de novo em alguns minutos. “Endereço privado” significa que o "
                       "aparelho (geralmente um celular) esconde o fabricante usando um endereço aleatório. "
                       "Clique duas vezes para dar um nome.", "Faint", wrap=True))
        lay.addWidget(card)

        self.w.updated.connect(self.render)
        self.w.progress.connect(self.status.setText)
        self._rows: list[lan.LanDevice] = []
        self.render()

    # ----------------------------------------------------------------- ações
    def on_shown(self) -> None:
        if not self.w.devices and not self.w.busy and not self.w.error:
            self.w.scan()
        self.render()

    def _toggle_watch(self, on: bool) -> None:
        Settings.instance().set("network.devices_watch", on)
        self.w.apply_settings()
        if on and not self.w.devices:
            self.w.scan()

    def _set_interval(self, _i) -> None:
        Settings.instance().set("network.devices_interval_min", self.interval.currentData())
        self.w.apply_settings()

    def _open_router(self) -> None:
        gw = self.w.net.gateway if self.w.net else ""
        if gw:
            shell_open(f"http://{gw}")

    def _selected(self, row: int) -> lan.LanDevice | None:
        it = self.table.item(row, 0)
        if it is None:
            return None
        mac = it.data(Qt.ItemDataRole.UserRole)
        return next((d for d in self._rows if d.mac == mac), None)

    def _rename(self, row: int) -> None:
        d = self._selected(row)
        if d is None:
            return
        name, ok = QInputDialog.getText(self, "Nome do aparelho", f"Nome para {d.ip} ({d.mac}):",
                                        text=d.custom_name or d.name)
        if ok:
            lan.set_custom(self.w.net_id, d.mac, custom_name=name, known=True if name.strip() else None)
            d.custom_name = name.strip()
            if name.strip():
                d.known = True
            self.render()

    def _menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        d = self._selected(row)
        if d is None:
            return
        m = QMenu(self)
        m.addAction("Dar um nome...", lambda: self._rename(row))
        if not (d.is_self or d.is_gateway):
            m.addAction("Marcar como desconhecido" if d.known else "Marcar como conhecido",
                        lambda: self._set_known(d, not d.known))
        m.addSeparator()
        m.addAction("Copiar IP", lambda: QGuiApplication.clipboard().setText(d.ip))
        m.addAction("Copiar MAC", lambda: QGuiApplication.clipboard().setText(d.mac))
        if d.online and not d.is_self:
            m.addAction("Abrir no navegador (http://IP)", lambda: shell_open(f"http://{d.ip}"))
        if not d.online:
            m.addSeparator()
            m.addAction("Esquecer este aparelho", lambda: self._forget(d))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _set_known(self, d: lan.LanDevice, known: bool) -> None:
        lan.set_custom(self.w.net_id, d.mac, known=known)
        d.known = known
        self.render()

    def _forget(self, d: lan.LanDevice) -> None:
        if ask(self, "Esquecer aparelho", f"Remover “{d.label}” do histórico desta rede?",
                "Só a anotação no PC Control Center é apagada. Se o aparelho voltar, aparece como novo.",
                "Esquecer"):
            lan.forget(self.w.net_id, d.mac)
            self.w.devices = [x for x in self.w.devices if x.mac != d.mac]
            self.render()

    # --------------------------------------------------------------- desenho
    def render(self) -> None:
        w = self.w
        self.scan_btn.setEnabled(not w.busy)
        self.scan_btn.setText("Procurando..." if w.busy else "Procurar aparelhos")
        self.router_btn.setEnabled(bool(w.net and w.net.gateway))
        if w.error:
            self.status.setText(f"Não foi possível procurar: {w.error}")
        elif not w.busy and w.last_scan:
            novos = f" · {len(w.new)} novo(s) desde a última busca" if w.new else ""
            self.status.setText(f"Última busca: {datetime.fromtimestamp(w.last_scan):%H:%M:%S}{novos}")
        if w.net:
            self.net_lbl.setText(f"{w.net.iface} · faixa {w.net.network} · roteador {w.net.gateway or '—'} · "
                                 f"este PC {w.net.ip}")
        devs = sorted(w.devices, key=lambda d: (not d.online, not d.is_gateway, not d.is_self,
                                                [int(x) for x in d.ip.split(".")] if d.ip else [999]))
        self._rows = devs
        online = [d for d in devs if d.online]
        self.n_online.setText(str(len(online)))
        self.n_known.setText(str(sum(d.known for d in online)))
        unknown = sum(not d.known for d in online)
        self.n_unknown.setText(str(unknown))
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(devs))
        muted = QColor(148, 163, 184)
        for r, d in enumerate(devs):
            situ = ("Este PC" if d.is_self else "Roteador" if d.is_gateway else
                    "Conhecido" if d.known else "Não identificado")
            if not d.online:
                situ += " (fora da rede)"
            ipkey = tuple(int(x) for x in d.ip.split(".")) if d.ip else (999,)
            name = d.custom_name or d.name or d.model
            cells = [
                _Item("●" if d.online else "○", (not d.online,)),
                _Item(name or "—"),
                _Item(d.kind),
                _Item(d.ip, ipkey),
                _Item(d.vendor or ("Endereço privado" if d.randomized else "—")),
                _Item(d.mac),
                _Item("agora" if d.online else _ago(d.last_seen), -(d.last_seen or 0)),
                _Item(situ),
            ]
            cells[0].setData(Qt.ItemDataRole.UserRole, d.mac)
            cells[0].setForeground(QColor("#34d399") if d.online else muted)
            cells[0].setToolTip("Conectado agora" if d.online else "Não respondeu na última busca")
            if not d.online:
                for c in cells[1:]:
                    c.setForeground(muted)
            elif not d.known:
                cells[7].setForeground(QColor("#fbbf24"))
            if d.model and name != d.model:
                cells[1].setToolTip(d.model)
            for c, it in enumerate(cells):
                t.setItem(r, c, it)
        t.setSortingEnabled(True)
        if not devs and not w.busy:
            self.status.setText(self.status.text() or "Nenhum aparelho encontrado ainda.")
