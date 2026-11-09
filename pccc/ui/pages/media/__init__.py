"""Mídia e streaming: áudio (saída, mixer por app, visualizador), OBS, YouTube e contador de FPS."""
from __future__ import annotations

from ...components import Segmented
from ..base import Page
from .audio import AudioView
from .obs import ObsView
from .youtube import YouTubeView
from .fps import FpsView


# ===================================================================== PÁGINA
class MediaPage(Page):
    title = "Mídia e streaming"
    subtitle = "Som de cada app, visualizador, OBS, vídeos novos do YouTube e contador de FPS"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MediaPage")
        self.tabs = Segmented([("audio", "Áudio"), ("obs", "OBS"), ("youtube", "YouTube"), ("fps", "FPS")])
        self.add(self.tabs)
        self.views = {"audio": AudioView(), "obs": ObsView(), "youtube": YouTubeView(), "fps": FpsView()}
        for v in self.views.values():
            self.add(v)
        self.layout_.addStretch(1)
        self.tabs.changed.connect(self.switch)
        self.switch("audio")

    def switch(self, key: str) -> None:
        self.tabs.set_current(key)
        for k, v in self.views.items():
            v.setVisible(k == key)
        self.relayout()

    def on_shown(self) -> None:
        self.relayout()
