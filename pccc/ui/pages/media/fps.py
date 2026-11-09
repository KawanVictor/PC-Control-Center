"""Aba FPS: contador de quadros por segundo com o PresentMon."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ....media import fps as fpsmod
from ...components import GlassCard, ResponsiveGrid, label
from ...icons import G
from ...tasks import run_task
from ..common import ask
from ..common import add_desktop_widget
from .charts import Sparkline


# ======================================================================= FPS
class FpsView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.mon = fpsmod.FpsMonitor.instance()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        grid = ResponsiveGrid(min_col_width=440, max_cols=2)

        setup = GlassCard("Contador de FPS", G.GAME)
        setup.add(label("Mede os quadros por segundo de qualquer jogo (DirectX, Vulkan, OpenGL) com o PresentMon, "
                        "ferramenta oficial e gratuita da Intel. O Windows só libera essa medição para "
                        "administradores: ao ligar, aparece UM aviso do Windows (UAC) por sessão.",
                        "Faint", wrap=True))
        self.pm_status = label("", "Muted", wrap=True)
        setup.add(self.pm_status)
        b = QHBoxLayout()
        self.dl_btn = QPushButton("Baixar PresentMon (Intel, ~1 MB)")
        self.dl_btn.clicked.connect(self._download)
        self.start_btn = QPushButton("Ligar contador")
        self.start_btn.setObjectName("Primary")
        self.start_btn.clicked.connect(self._toggle)
        b.addWidget(self.dl_btn)
        b.addWidget(self.start_btn)
        b.addStretch(1)
        setup.add(b)
        overlay = QPushButton("Mostrar FPS por cima do jogo (widget sempre visível)")
        overlay.clicked.connect(lambda: add_desktop_widget("fps", layer="top"))
        setup.add(overlay)
        setup.add(label("O widget aparece sobre jogos em janela ou “tela cheia sem bordas”. Em tela cheia "
                        "exclusiva, nenhum programa externo consegue desenhar por cima.", "Faint", wrap=True))
        grid.add(setup)

        live = GlassCard("Agora", G.PERFORMANCE)
        self.game_lbl = label("—", "Muted")
        live.add(self.game_lbl)
        nums = QHBoxLayout()
        self.fps_lbl = QLabel("--")
        self.fps_lbl.setStyleSheet("font-size: 54px; font-weight: 700;")
        nums.addWidget(self.fps_lbl)
        col = QVBoxLayout()
        self.low_lbl = label("1% mínimo: —", "Value")
        self.ft_lbl = label("Tempo de quadro: —", "Muted")
        col.addWidget(self.low_lbl)
        col.addWidget(self.ft_lbl)
        nums.addLayout(col, 1)
        live.add(nums)
        self.spark = Sparkline()
        live.add(self.spark)
        self.others = label("", "Faint", wrap=True)
        live.add(self.others)
        grid.add(live)
        lay.addWidget(grid)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()
        self._timer.start(500)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    def _download(self) -> None:
        if not ask(self, "Baixar PresentMon",
                    "Baixar o PresentMon do GitHub oficial da Intel?",
                    "Origem: github.com/GameTechDev/PresentMon (versão estável mais recente, ~1 MB).\n"
                    f"Destino: {fpsmod.presentmon_path()}\n\n"
                    "Antes de usar, o app confere a assinatura digital da Intel — se não for válida, o arquivo "
                    "é descartado.", "Baixar"):
            return
        self.dl_btn.setEnabled(False)
        self.pm_status.setText("Baixando...")
        run_task(fpsmod.download, on_done=lambda tag: (self.pm_status.setText(f"✓ PresentMon {tag} instalado e "
                                                                               "assinatura da Intel conferida."),
                                                        self.refresh()),
                 on_error=lambda m: (self.pm_status.setText(f"Falhou: {m}"), self.dl_btn.setEnabled(True)))

    def _toggle(self) -> None:
        if self.mon.running():
            self.mon.stop()
        else:
            try:
                if not self.mon.start():
                    self.pm_status.setText("O aviso do Windows (UAC) foi recusado — o contador não foi ligado.")
            except FileNotFoundError:
                QMessageBox.information(self, "Contador de FPS", "Baixe o PresentMon primeiro.")
        self.refresh()

    def refresh(self) -> None:
        ver = fpsmod.installed_version()
        has = fpsmod.presentmon_path().exists()
        self.dl_btn.setText("Atualizar PresentMon" if has else "Baixar PresentMon (Intel, ~1 MB)")
        self.dl_btn.setEnabled(True)
        game, st = self.mon.current()
        running = bool(st.get("running"))
        self.start_btn.setEnabled(has)
        self.start_btn.setText("Desligar contador" if running or st.get("starting") else "Ligar contador")
        if not self.pm_status.text() or self.pm_status.text().startswith(("PresentMon", "Contador")):
            if st.get("error"):
                self.pm_status.setText(f"Contador: {st['error']}")
            elif running:
                self.pm_status.setText("Contador ligado — abra um jogo.")
            elif st.get("starting"):
                self.pm_status.setText("Contador: iniciando (confirme o aviso do Windows)...")
            else:
                self.pm_status.setText(f"PresentMon {ver} instalado." if has else "PresentMon não instalado.")
        if game:
            col = "#34d399" if game["fps"] >= 55 else "#fbbf24" if game["fps"] >= 30 else "#fb7185"
            self.fps_lbl.setText(f"{game['fps']:.0f}")
            self.fps_lbl.setStyleSheet(f"font-size: 54px; font-weight: 700; color: {col};")
            self.game_lbl.setText(game["name"])
            self.low_lbl.setText(f"1% mínimo: {game['low1']:.0f} FPS")
            self.ft_lbl.setText(f"Tempo de quadro: {game['frame_ms']:.1f} ms".replace(".", ","))
            self.spark.set_values(game.get("history") or [])
        else:
            self.fps_lbl.setText("--")
            self.fps_lbl.setStyleSheet("font-size: 54px; font-weight: 700; color: rgba(148,163,184,0.5);")
            self.game_lbl.setText("Nenhum jogo detectado" if running else "Contador desligado")
        others = [p for p in st.get("procs") or [] if not game or p["pid"] != game["pid"]][:4]
        self.others.setText(("Outros apps desenhando: " + ", ".join(f"{p['name']} {p['fps']:.0f}" for p in others))
                            if others else "")
