"""Aba Áudio: saída de som, volume por app e visualizador."""
from __future__ import annotations

import time

from PySide6.QtCore import QFileInfo, QSize, Qt, QTimer
from PySide6.QtWidgets import (QFileIconProvider, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

from ....media import audio
from ...components import GlassCard, ResponsiveGrid, label
from ...icons import G
from ..common import add_desktop_widget
from .charts import LevelMeter, SpectrumView


# =============================================================== componentes
def _mute_button() -> QPushButton:
    from PySide6.QtGui import QFont
    from ...theme import icon_font_family
    b = QPushButton()
    b.setCheckable(True)
    b.setFixedWidth(44)
    f = QFont(icon_font_family())
    f.setPixelSize(15)
    b.setFont(f)
    _mute_glyph(b, False)
    return b


def _mute_glyph(b: QPushButton, muted: bool) -> None:
    b.setText("" if muted else "")       # alto-falante cortado / alto-falante
    b.setToolTip("Ativar o som" if muted else "Silenciar")


# ===================================================================== ÁUDIO
class AppRow(QWidget):
    def __init__(self, app: audio.AppAudio) -> None:
        super().__init__()
        self.key = app.key
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 3, 0, 3)
        h.setSpacing(10)
        ic = QLabel()
        ic.setFixedSize(22, 22)
        if app.exe:
            ic.setPixmap(QFileIconProvider().icon(QFileInfo(app.exe)).pixmap(QSize(20, 20)))
        h.addWidget(ic)
        self.name = label(app.name)
        self.name.setMinimumWidth(150)
        h.addWidget(self.name, 1)
        self.meter = LevelMeter()
        h.addWidget(self.meter)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFixedWidth(200)
        self.slider.valueChanged.connect(lambda v: audio.set_app_volume(self.key, v / 100))
        h.addWidget(self.slider)
        self.pct = label("", "Muted")
        self.pct.setFixedWidth(40)
        h.addWidget(self.pct)
        self.mute = _mute_button()
        self.mute.setToolTip("Silenciar este aplicativo")
        self.mute.toggled.connect(lambda on: (audio.set_app_mute(self.key, on), self._mute_icon(on)))
        h.addWidget(self.mute)
        self.update_from(app)

    def _mute_icon(self, on: bool) -> None:
        _mute_glyph(self.mute, on)

    def update_from(self, a: audio.AppAudio) -> None:
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(round(a.volume * 100))
            self.slider.blockSignals(False)
        self.pct.setText(f"{round(a.volume * 100)}%")
        self.mute.blockSignals(True)
        self.mute.setChecked(a.muted)
        self.mute.blockSignals(False)
        self._mute_icon(a.muted)
        self.meter.set_value(0 if a.muted else a.peak)
        self.name.setObjectName("Muted" if not a.active else "")


class AudioView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=440, max_cols=2)

        out = GlassCard("Saída de som", G.VOLUME)
        out.add(label("Para onde vai o som do PC. A troca vale para jogos, música, chamadas e sons do sistema.",
                      "Faint", wrap=True))
        self.dev_box = QVBoxLayout()
        self.dev_box.setSpacing(6)
        out.add(self.dev_box)
        mv = QHBoxLayout()
        mv.addWidget(label("Volume geral"))
        self.master = QSlider(Qt.Horizontal)
        self.master.setRange(0, 100)
        self.master.valueChanged.connect(self._set_master)
        mv.addWidget(self.master, 1)
        self.master_pct = label("", "Value")
        self.master_pct.setFixedWidth(48)
        mv.addWidget(self.master_pct)
        self.master_mute = _mute_button()
        self.master_mute.toggled.connect(lambda on: (audio.set_master_mute(on), _mute_glyph(self.master_mute, on)))
        mv.addWidget(self.master_mute)
        out.add(mv)
        out.add(QWidget(), 1)          # empurra o conteúdo para cima quando o cartão vizinho é mais alto
        grid.add(out)

        vis = GlassCard("Visualizador", G.MEDIA)
        vis.add(label("O som que está tocando agora, em tempo real (nada é gravado).", "Faint", wrap=True))
        self.spectrum = SpectrumView()
        vis.add(self.spectrum)
        add_w = QPushButton("Colocar o visualizador na área de trabalho")
        add_w.clicked.connect(lambda: add_desktop_widget("visualizer"))
        vis.add(add_w)
        grid.add(vis)
        lay.addWidget(grid)

        mix = GlassCard("Volume por aplicativo", G.APPS)
        mix.add(label("Cada programa com som tem seu próprio volume — igual ao Mixer de Volume do Windows. "
                      "Apps em cinza estão abertos mas em silêncio agora.", "Faint", wrap=True))
        self.apps_box = QVBoxLayout()
        self.apps_box.setSpacing(2)
        mix.add(self.apps_box)
        self.apps_empty = label("Nenhum aplicativo está usando o som agora.", "Muted")
        mix.add(self.apps_empty)
        add_v = QPushButton("Colocar o mixer na área de trabalho")
        add_v.clicked.connect(lambda: add_desktop_widget("volume"))
        mix.add(add_v, 0)
        lay.addWidget(mix)
        self.rows: dict[str, AppRow] = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._dev_ids: list[str] = []

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh(devices=True)
        self._timer.start(700)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    def _set_master(self, v: int) -> None:
        audio.set_master_volume(v / 100)
        self.master_pct.setText(f"{v}%")

    def refresh(self, devices: bool = False) -> None:
        try:
            vol, muted = audio.master_volume()
            apps = audio.app_sessions()
        except Exception as e:     # noqa: BLE001
            self.apps_empty.setText(f"Sem dispositivo de áudio: {e}")
            self.apps_empty.show()
            return
        if not self.master.isSliderDown():
            self.master.blockSignals(True)
            self.master.setValue(round(vol * 100))
            self.master.blockSignals(False)
            self.master_pct.setText(f"{round(vol * 100)}%")
        self.master_mute.blockSignals(True)
        self.master_mute.setChecked(muted)
        _mute_glyph(self.master_mute, muted)
        self.master_mute.blockSignals(False)
        keys = [a.key for a in apps]
        if keys != list(self.rows):
            for r in self.rows.values():
                r.setParent(None)
                r.deleteLater()
            self.rows = {}
            for a in apps:
                row = AppRow(a)
                self.rows[a.key] = row
                self.apps_box.addWidget(row)
        else:
            for a in apps:
                self.rows[a.key].update_from(a)
        self.apps_empty.setVisible(not apps)
        if devices or int(time.time()) % 5 == 0:
            self._load_devices()

    def _load_devices(self) -> None:
        try:
            devs = audio.output_devices()
        except Exception:
            devs = []
        ids = [f"{d.id}{d.default}" for d in devs]
        if ids == self._dev_ids:
            return
        self._dev_ids = ids
        while self.dev_box.count():
            w = self.dev_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        for d in devs:
            b = QPushButton(("✓  " if d.default else "     ") + d.name)
            b.setObjectName("Primary" if d.default else "")
            b.setStyleSheet("text-align: left; padding: 8px 12px;")
            b.clicked.connect(lambda _=False, dev=d: self._choose(dev))
            self.dev_box.addWidget(b)
        if not devs:
            self.dev_box.addWidget(label("Nenhuma saída de som ativa.", "Muted"))

    def _choose(self, d: audio.OutputDevice) -> None:
        if d.default:
            return
        try:
            audio.set_default_output(d.id)
        except Exception as e:     # noqa: BLE001
            QMessageBox.warning(self, "Saída de som", str(e))
        self._dev_ids = []
        self._load_devices()
