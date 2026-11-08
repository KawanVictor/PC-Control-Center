"""Cenários e estilo: cenários, tema automático, papel de parede vivo, tela, atalhos e exportar/importar."""
from __future__ import annotations

from ...components import Segmented
from ..base import Page
from .scene_list import ScenesView
from .autotheme import AutoThemeView
from .livewall import LiveWallView
from .display import DisplayView
from .hotkeys import HotkeysView
from .bundle import BundleView


# ================================================================ PÁGINA
class ScenesPage(Page):
    title = "Cenários e estilo"
    subtitle = "Cenários de um clique, tema automático, papel de parede vivo, tela e atalhos de teclado"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tabs = Segmented([("scenes", "Cenários"), ("auto", "Tema automático"), ("live", "Papel de parede vivo"),
                               ("display", "Tela"), ("keys", "Atalhos"), ("bundle", "Exportar / importar")])
        self.add(self.tabs)
        self.views = {"scenes": ScenesView(self), "auto": AutoThemeView(), "live": LiveWallView(),
                      "display": DisplayView(), "keys": HotkeysView(), "bundle": BundleView()}
        for v in self.views.values():
            self.add(v)
        self.layout_.addStretch(1)
        self.tabs.changed.connect(self.switch)
        self.switch("scenes")

    def switch(self, key: str) -> None:
        self.tabs.set_current(key)
        for k, v in self.views.items():
            v.setVisible(k == key)
        view = self.views[key]
        if isinstance(view, (ScenesView, HotkeysView)):
            view.refresh_view()
        elif isinstance(view, AutoThemeView):
            view.refresh()
        self.relayout()

    def on_shown(self) -> None:
        self.switch(self.tabs.current() or "scenes")
