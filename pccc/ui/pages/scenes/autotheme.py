"""Aba Tema automático: claro/escuro pelo horário ou pelo sol, e papel de parede dinâmico."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QPushButton, QTimeEdit, QVBoxLayout, QWidget

from ....core.config import Settings
from ....personalization import sun
from ....personalization.autotheme import AutoTheme
from ...components import GlassCard, Segmented, ToggleSwitch, label
from ...icons import G
from ...tasks import run_task
from ..common import setting_row


# ========================================================= TEMA AUTOMÁTICO
class AutoThemeView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        s = Settings.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        card = GlassCard("Tema automático", G.SUN)
        self.enabled = ToggleSwitch()
        self.enabled.setChecked(bool(s.get("autotheme.enabled")))
        self.enabled.toggled.connect(self._toggle)
        card.add(setting_row("Claro de dia, escuro à noite", "Ao ligar, o modo atual vai para o Histórico de "
                      "personalização (desfazer volta para ele).", self.enabled))
        self.mode = Segmented([("sun", "Pelo nascer/pôr do sol"), ("fixed", "Em horários fixos")],
                              s.get("autotheme.mode", "sun"))
        self.mode.changed.connect(self._set_mode)
        card.add(self.mode)
        loc = QHBoxLayout()
        self.loc_lbl = label("", "Muted")
        loc.addWidget(self.loc_lbl, 1)
        self.city = QLineEdit()
        self.city.setPlaceholderText("Mudar cidade (ex.: Recife)")
        self.city.returnPressed.connect(self._geocode)
        loc.addWidget(self.city)
        btn = QPushButton("Buscar")
        btn.clicked.connect(self._geocode)
        loc.addWidget(btn)
        self.loc_row = QWidget()
        self.loc_row.setLayout(loc)
        card.add(self.loc_row)
        times = QHBoxLayout()
        self.light_at = QTimeEdit(QTime.fromString(s.get("autotheme.light_at", "07:00"), "HH:mm"))
        self.dark_at = QTimeEdit(QTime.fromString(s.get("autotheme.dark_at", "19:00"), "HH:mm"))
        for te, key in ((self.light_at, "light_at"), (self.dark_at, "dark_at")):
            te.setDisplayFormat("HH:mm")
            te.timeChanged.connect(lambda t, k=key: (Settings.instance().set(f"autotheme.{k}", t.toString("HH:mm")),
                                                     AutoTheme.instance().start() if self.enabled.isChecked() else None,
                                                     self.refresh()))
        times.addWidget(label("Claro às"))
        times.addWidget(self.light_at)
        times.addSpacing(20)
        times.addWidget(label("Escuro às"))
        times.addWidget(self.dark_at)
        times.addStretch(1)
        self.times_row = QWidget()
        self.times_row.setLayout(times)
        card.add(self.times_row)
        for key, text in (("apps", "Mudar o modo dos aplicativos do Windows"),
                          ("system", "Mudar a barra de tarefas e o menu Iniciar"),
                          ("app_theme", "Mudar também o tema do PC Control Center")):
            cb = QCheckBox(text)
            cb.setChecked(bool(s.get(f"autotheme.{key}", True)))
            cb.toggled.connect(lambda v, k=key: Settings.instance().set(f"autotheme.{k}", v))
            card.add(cb)
        self.next_lbl = label("", "Value")
        card.add(self.next_lbl)
        lay.addWidget(card)
        self.refresh()

    def _toggle(self, on: bool) -> None:
        AutoTheme.instance().enable(on)
        self.refresh()

    def _set_mode(self, mode: str) -> None:
        Settings.instance().set("autotheme.mode", mode)
        if self.enabled.isChecked():
            AutoTheme.instance().start()
        self.refresh()

    def _geocode(self) -> None:
        from ....widgets import weather as wx
        name = self.city.text().strip()
        if not name:
            return
        self.loc_lbl.setText("Procurando...")

        def done(res):
            if not res:
                self.loc_lbl.setText("Cidade não encontrada.")
                return
            Settings.instance().set("location", res)
            self.city.clear()
            if self.enabled.isChecked():
                AutoTheme.instance().start()
            self.refresh()

        run_task(wx.geocode, name, on_done=done, on_error=lambda e: self.loc_lbl.setText(f"Sem conexão: {e}"))

    def refresh(self) -> None:
        mode = Settings.instance().get("autotheme.mode", "sun")
        self.loc_row.setVisible(mode == "sun")
        self.times_row.setVisible(mode == "fixed")
        loc = sun.location()
        rise, set_ = sun.sun_times(float(loc["lat"]), float(loc["lon"]))
        self.loc_lbl.setText(f"{loc.get('label', '')} — hoje o sol nasce às {rise:%H:%M} e se põe às {set_:%H:%M}"
                             if rise else f"{loc.get('label', '')}")
        kind, when = AutoTheme.next_change()
        if self.enabled.isChecked() and when:
            day = "hoje" if when.date() == datetime.now().date() else "amanhã"
            self.next_lbl.setText(f"Próxima troca: modo {kind} {day} às {when:%H:%M}")
        else:
            self.next_lbl.setText("Desligado")
