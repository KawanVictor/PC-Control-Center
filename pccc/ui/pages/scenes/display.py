"""Aba Tela: brilho e luz quente."""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget

from ....core.config import Settings
from ....personalization import display
from ....personalization.autotheme import AutoTheme
from ....personalization.display import WarmFilter
from ...components import GlassCard, ResponsiveGrid, ToggleSwitch, label
from ...icons import G
from ...tasks import run_task
from ..common import labeled_slider, setting_row


# ================================================================ TELA
class DisplayView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        s = Settings.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=460, max_cols=2)
        self.bright = GlassCard("Brilho", G.BRIGHTNESS)
        self.bright_box = QVBoxLayout()
        self.bright.add(self.bright_box)
        self.bright.add(label("Monitores externos só aceitam se o DDC/CI estiver ligado no menu do próprio monitor.",
                              "Faint", wrap=True))
        grid.add(self.bright)

        warm = GlassCard("Luz quente", G.MOON)
        warm.add(label("Deixa a tela mais amarelada para cansar menos a vista à noite. Se o app fechar, a tela "
                       "volta ao normal na hora. Se você usa a “Luz noturna” do Windows, prefira uma das duas.",
                       "Faint", wrap=True))
        w, self.warm_slider = labeled_slider(WarmFilter.instance().level, self._set_warm)
        warm.add(setting_row("Intensidade agora", "0% = desligado", w))
        self.warm_auto = ToggleSwitch()
        self.warm_auto.setChecked(bool(s.get("display.warm_auto")))
        self.warm_auto.toggled.connect(self._toggle_auto)
        warm.add(setting_row("Ligar sozinho ao anoitecer", "Usa o nascer/pôr do sol do local do tema automático",
                      self.warm_auto))
        w2, self.warm_level = labeled_slider(int(s.get("display.warm_level", 50)),
                                      lambda v: Settings.instance().set("display.warm_level", v))
        warm.add(setting_row("Intensidade à noite", "", w2))
        self.warm_status = label("", "Muted")
        warm.add(self.warm_status)
        grid.add(warm)
        lay.addWidget(grid)
        self._loaded = False

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._loaded:
            self._loaded = True
            run_task(display.displays, on_done=self._fill)
        self.warm_slider.blockSignals(True)
        self.warm_slider.setValue(WarmFilter.instance().level)
        self.warm_slider.blockSignals(False)

    def _fill(self, ds) -> None:
        if not ds:
            self.bright_box.addWidget(label("Nenhuma tela com controle de brilho encontrada.", "Muted"))
            return
        for d in ds:
            w, _s = labeled_slider(d.brightness, lambda v, did=d.id: self._set_bright(did, v))
            self.bright_box.addWidget(setting_row(d.name, d.kind, w))

    def _set_bright(self, did: str, v: int) -> None:
        try:
            display.set_brightness(did, v)
        except Exception as e:     # noqa: BLE001
            QMessageBox.warning(self, "Brilho", str(e))

    def _set_warm(self, v: int) -> None:
        try:
            WarmFilter.instance().set_level(v)
            self.warm_status.setText("" if v else "Desligado")
        except Exception as e:     # noqa: BLE001
            self.warm_status.setText(str(e))

    def _toggle_auto(self, on: bool) -> None:
        Settings.instance().set("display.warm_auto", on)
        AutoTheme.instance().warm_tick(force=True)
        self.warm_slider.setValue(WarmFilter.instance().level)
