"""Aplicativos e processos: programas instalados, processos em execução e inicialização."""
from __future__ import annotations

from ....monitoring.collector import MonitorService
from ....monitoring.models import Snapshot
from ...components import Segmented
from ..base import Page
from .installed import InstalledView
from .processes import ProcessesView
from .startup import StartupView


# ========================================================================== PÁGINA
class AppsPage(Page):
    title = "Aplicativos e processos"
    subtitle = "Programas instalados, processos em execução e inicialização do Windows"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.store_names: dict[str, str] = {}
        self.tabs = Segmented([("installed", "Instalados"), ("procs", "Processos"), ("startup", "Inicialização")])
        self.header_right.addWidget(self.tabs)
        self.installed_view = InstalledView(self)
        self.processes_view = ProcessesView()
        self.startup_view = StartupView(self)
        self.views = {"installed": self.installed_view, "procs": self.processes_view, "startup": self.startup_view}
        for v in self.views.values():
            self.add(v)
        self.layout_.addStretch(1)
        self.current = "installed"
        self.tabs.changed.connect(self.switch)
        self.switch("installed", load=False)

    def switch(self, key: str, load: bool = True) -> None:
        self.current = key
        self.tabs.set_current(key)
        for k, v in self.views.items():
            v.setVisible(k == key)
        if not load:
            return
        if key == "installed":
            self.installed_view.ensure_loaded()
        elif key == "startup":
            self.startup_view.ensure_loaded()
        elif key == "procs":
            snap = MonitorService.instance().latest
            if snap:
                self.processes_view.update_data(snap, force=True)

    def on_shown(self) -> None:
        # Carrega o inventário só quando a página é aberta pela primeira vez.
        self.switch(self.current)

    def on_snapshot(self, snap: Snapshot) -> None:
        if self.current == "procs":
            self.processes_view.update_data(snap)
