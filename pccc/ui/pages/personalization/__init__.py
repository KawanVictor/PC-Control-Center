"""Personalização do Windows: aparência, papel de parede, temas, barra de tarefas, área de
trabalho/Explorer, atalhos, aplicativos padrão e histórico (tudo desfazível)."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton

from ....personalization import changes, tweaks
from ...components import GlassCard, Segmented, label
from ...tasks import run_task
from ..common import ask
from ..base import Page
from .tweak_row import TweakRow
from .look import LookTab
from .wallpaper import WallpaperTab
from .themes import ThemesTab
from .explorer import ExplorerTab
from .shortcuts import ShortcutsTab
from .defaults import DefaultsTab
from .history import HistoryTab


class PersonalizationPage(LookTab, WallpaperTab, ThemesTab, ExplorerTab, ShortcutsTab, DefaultsTab, HistoryTab, Page):
    title = "Personalização do Windows"
    subtitle = "Aparência, papel de parede, temas, barra de tarefas e mais — tudo pode ser desfeito"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[TweakRow] = []
        self.tabs = Segmented([("look", "Aparência"), ("wall", "Papel de parede"), ("themes", "Temas"),
                               ("taskbar", "Barra de tarefas"), ("desktop", "Área de trabalho"),
                               ("shortcuts", "Atalhos"), ("defaults", "Apps padrão"), ("history", "Histórico")])
        self.add(self.tabs)

        self.restart_card = GlassCard()
        rh = QHBoxLayout()
        rh.addWidget(label("⟳  Algumas alterações só aparecem depois de reiniciar o Explorer "
                           "(barra de tarefas e área de trabalho piscam por 2 segundos).", "Muted", wrap=True), 1)
        rb = QPushButton("Reiniciar Explorer agora")
        rb.setObjectName("Primary")
        rb.clicked.connect(self._restart_explorer)
        rh.addWidget(rb)
        self.restart_card.add(rh)
        self.restart_card.hide()
        self.add(self.restart_card)

        self.views = {"look": self._build_look(), "wall": self._build_wallpaper(), "themes": self._build_themes(),
                      "taskbar": self._build_taskbar(), "desktop": self._build_desktop(),
                      "shortcuts": self._build_shortcuts(), "defaults": self._build_defaults(),
                      "history": self._build_history()}
        for v in self.views.values():
            self.add(v)
        self.layout_.addStretch(1)
        self.current = "look"
        self._loaded: set[str] = set()
        self.tabs.changed.connect(self.switch)
        self.switch("look")

    # ------------------------------------------------------------- utilidades
    @staticmethod
    def _section(title: str, glyph: str) -> GlassCard:
        return GlassCard(title, glyph)

    def _tweak_rows(self, card: GlassCard, section: str) -> None:
        for t in tweaks.TWEAKS:
            if t.section == section:
                r = TweakRow(t, self)
                self.rows.append(r)
                card.add(r)

    def changed(self, needs_restart: bool = False) -> None:
        if needs_restart:
            self.restart_card.show()
        self._load_history()

    def _restart_explorer(self) -> None:
        if ask(self, "Reiniciar Explorer", "Reiniciar o Explorer agora?",
                "A barra de tarefas e a área de trabalho somem por alguns segundos. Janelas de pastas abertas "
                "serão fechadas (seus programas continuam abertos).", "Reiniciar"):
            run_task(changes.restart_explorer, on_done=lambda _r: self.restart_card.hide())

    def switch(self, key: str) -> None:
        self.current = key
        self.tabs.set_current(key)
        for k, v in self.views.items():
            v.setVisible(k == key)
        if key not in self._loaded:
            self._loaded.add(key)
            {"wall": self._load_wallpapers, "themes": self._load_themes, "defaults": self._load_defaults,
             "history": self._load_history, "shortcuts": self._load_created}.get(key, lambda: None)()
        for r in self.rows:
            r.reload()

    def on_shown(self) -> None:
        for r in self.rows:
            r.reload()
        self._refresh_accent()
