"""Aba Papel de parede vivo: vídeo ou GIF atrás dos ícones."""
from __future__ import annotations

import os

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QMessageBox, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from ....core.config import Settings
from ....personalization import dynwall, wallpaper
from ....personalization.livewall import GIF_EXT, VIDEO_EXT, LiveWallpaper
from ...components import GlassCard, ResponsiveGrid, ToggleSwitch, label
from ...icons import G
from ..common import setting_row


# ===================================================== PAPEL DE PAREDE VIVO
class LiveWallView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        s = Settings.instance()
        self.dyn = dynwall.DynamicWallpaper.instance()
        self.live = LiveWallpaper.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=460, max_cols=2)

        d = GlassCard("Papel de parede dinâmico", G.IMAGE)
        self.dyn_on = ToggleSwitch()
        self.dyn_on.setChecked(bool(s.get("dynwall.enabled")))
        self.dyn_on.toggled.connect(self._dyn_toggle)
        d.add(setting_row("Trocar automaticamente", "Ao ligar, a imagem atual vai para o Histórico (desfazer volta "
                   "para ela).", self.dyn_on))
        self.dyn_mode = QComboBox()
        for k, t in dynwall.MODES.items():
            self.dyn_mode.addItem(t, k)
        self.dyn_mode.setCurrentIndex(max(0, self.dyn_mode.findData(s.get("dynwall.mode", "bing"))))
        self.dyn_mode.currentIndexChanged.connect(self._dyn_mode)
        d.add(setting_row("Fonte das imagens", "", self.dyn_mode))
        # pasta
        self.folder_box = QWidget()
        fb = QVBoxLayout(self.folder_box)
        fb.setContentsMargins(0, 0, 0, 0)
        fr = QHBoxLayout()
        self.folder_lbl = label(s.get("dynwall.folder", "") or "Nenhuma pasta escolhida", "Muted")
        fr.addWidget(self.folder_lbl, 1)
        pick = QPushButton("Escolher pasta...")
        pick.clicked.connect(self._pick_folder)
        fr.addWidget(pick)
        fb.addLayout(fr)
        ir = QHBoxLayout()
        ir.addWidget(label("Trocar a cada"))
        self.interval = QSpinBox()
        self.interval.setRange(1, 1440)
        self.interval.setSuffix(" min")
        self.interval.setValue(int(s.get("dynwall.interval_min", 30)))
        self.interval.valueChanged.connect(lambda v: Settings.instance().set("dynwall.interval_min", v))
        ir.addWidget(self.interval)
        shuffle = QCheckBox("Ordem aleatória")
        shuffle.setChecked(bool(s.get("dynwall.shuffle", True)))
        shuffle.toggled.connect(lambda v: Settings.instance().set("dynwall.shuffle", v))
        ir.addWidget(shuffle)
        ir.addStretch(1)
        fb.addLayout(ir)
        d.add(self.folder_box)
        # períodos
        self.period_box = QWidget()
        pb = QFormLayout(self.period_box)
        pb.setContentsMargins(0, 0, 0, 0)
        self.period_btns = {}
        for key, text, _h in dynwall.PERIODS:
            b = QPushButton(os.path.basename((s.get("dynwall.periods") or {}).get(key, "")) or "Escolher imagem...")
            b.clicked.connect(lambda _=False, k=key: self._pick_period(k))
            self.period_btns[key] = b
            pb.addRow(text, b)
        d.add(self.period_box)
        st = QComboBox()
        for k, t in wallpaper.STYLE_LABELS.items():
            st.addItem(t, k)
        st.setCurrentIndex(max(0, st.findData(s.get("dynwall.style", "fill"))))
        st.currentIndexChanged.connect(lambda _i: Settings.instance().set("dynwall.style", st.currentData()))
        d.add(setting_row("Ajuste da imagem", "", st))
        nb = QHBoxLayout()
        nxt = QPushButton("Trocar agora")
        nxt.clicked.connect(self.dyn.next_now)
        nb.addWidget(nxt)
        opn = QPushButton("Abrir pasta das imagens baixadas")
        opn.clicked.connect(lambda: os.startfile(dynwall.daily_dir()))
        nb.addWidget(opn)
        nb.addStretch(1)
        d.add(nb)
        self.dyn_status = label("", "Muted", wrap=True)
        d.add(self.dyn_status)
        grid.add(d)

        lv = GlassCard("Papel de parede animado", G.VIDEO)
        lv.add(label("Um vídeo ou GIF toca atrás dos ícones da área de trabalho, sem som. Pausa sozinho em jogos "
                     "e vídeos em tela cheia para não pesar.", "Faint", wrap=True))
        self.live_on = ToggleSwitch()
        self.live_on.setChecked(self.live.running)
        self.live_on.toggled.connect(self._live_toggle)
        lv.add(setting_row("Ligado", "", self.live_on))
        fr2 = QHBoxLayout()
        self.video_lbl = label(os.path.basename(s.get("livewall.path", "")) or "Nenhum vídeo escolhido", "Muted")
        fr2.addWidget(self.video_lbl, 1)
        pv = QPushButton("Escolher vídeo ou GIF...")
        pv.clicked.connect(self._pick_video)
        fr2.addWidget(pv)
        lv.add(fr2)
        for key, text, default in (("all_screens", "Em todos os monitores", True),
                                   ("pause_when_covered", "Pausar quando uma janela maximizada cobrir a tela", True),
                                   ("pause_on_battery", "Pausar quando estiver na bateria", True)):
            cb = QCheckBox(text)
            cb.setChecked(bool(s.get(f"livewall.{key}", default)))
            cb.toggled.connect(lambda v, k=key: self._live_opt(k, v))
            lv.add(cb)
        self.live_status = label("", "Muted")
        lv.add(self.live_status)
        grid.add(lv)
        lay.addWidget(grid)

        self.dyn.changed.connect(lambda _p, cap: self.dyn_status.setText(f"✓ {cap}"))
        self.dyn.failed.connect(lambda m: self.dyn_status.setText(f"⚠ {m}"))
        self.live.state_changed.connect(self._live_state)
        self._dyn_mode_visibility()
        self._live_state("playing" if self.live.running else "stopped")

    # dinâmico
    def _dyn_toggle(self, on: bool) -> None:
        self.dyn.enable(on)
        self.dyn_status.setText("Buscando a imagem..." if on else "Desligado")

    def _dyn_mode(self, _i) -> None:
        Settings.instance().set("dynwall.mode", self.dyn_mode.currentData())
        self._dyn_mode_visibility()
        if self.dyn_on.isChecked():
            self.dyn.next_now()

    def _dyn_mode_visibility(self) -> None:
        m = self.dyn_mode.currentData()
        self.folder_box.setVisible(m == "folder")
        self.period_box.setVisible(m == "timeofday")

    def _pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Pasta com imagens")
        if d:
            n = len(dynwall.folder_images(d))
            Settings.instance().set("dynwall.folder", os.path.normpath(d))
            self.folder_lbl.setText(f"{os.path.normpath(d)}  ({n} imagens)")

    def _pick_period(self, key: str) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Imagem", "", "Imagens (*.jpg *.jpeg *.png *.bmp *.webp)")
        if f:
            s = Settings.instance()
            per = dict(s.get("dynwall.periods") or {})
            per[key] = os.path.normpath(f)
            s.set("dynwall.periods", per)
            self.period_btns[key].setText(os.path.basename(f))

    # animado
    def _pick_video(self) -> None:
        exts = " ".join(f"*{e}" for e in VIDEO_EXT + GIF_EXT)
        f, _ = QFileDialog.getOpenFileName(self, "Vídeo ou GIF", "", f"Vídeos e GIFs ({exts})")
        if f:
            Settings.instance().set("livewall.path", os.path.normpath(f))
            self.video_lbl.setText(os.path.basename(f))
            if self.live.running:
                self._start_live()

    def _live_opt(self, key: str, value: bool) -> None:
        Settings.instance().set(f"livewall.{key}", value)
        if key == "all_screens" and self.live.running:
            self._start_live()

    def _start_live(self) -> bool:
        try:
            self.live.start()
            Settings.instance().set("livewall.enabled", True)
            return True
        except Exception as e:     # noqa: BLE001
            QMessageBox.warning(self, "Papel de parede animado", str(e))
            return False

    def _live_toggle(self, on: bool) -> None:
        if on:
            if not self._start_live():
                self.live_on.blockSignals(True)
                self.live_on.setChecked(False)
                self.live_on.blockSignals(False)
        else:
            self.live.stop()
            Settings.instance().set("livewall.enabled", False)

    def _live_state(self, st: str) -> None:
        text = {"playing": "▶ Tocando", "stopped": "Desligado"}.get(st, "")
        if st.startswith("paused"):
            text = f"⏸ Pausado ({st.split(':', 1)[1].strip()})"
        self.live_status.setText(text)
        self.live_on.blockSignals(True)
        self.live_on.setChecked(self.live.running)
        self.live_on.blockSignals(False)
