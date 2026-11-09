"""Gera as capturas do README em MODO DEMONSTRAÇÃO, sem dados pessoais.

    python -m build_tools.readme_shots            (salva em docs/img/)

O que é trocado por valores fictícios antes de abrir a janela:
* pasta de dados: um %APPDATA% temporário (sem histórico, alertas, nomes ou temas do usuário);
* nome do computador: "MEU-PC";
* Wi-Fi: rede "MinhaRede-5G" e BSSID fictício;
* aparelhos da rede: lista de exemplo (endereços 192.168.0.x e MACs inventados).

CPU, memória, discos e velocidade continuam sendo leituras reais deste PC, que não identificam
ninguém. Nada é alterado no sistema: as páginas só são exibidas e capturadas.
"""
from __future__ import annotations

import ipaddress
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Precisa vir antes de qualquer import do pccc: config, banco e logs leem o APPDATA.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="pccc-demo-")
platform.node = lambda: "MEU-PC"

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPainterPath,  # noqa: E402
                           QRadialGradient)
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = ROOT / "docs" / "img"


# ------------------------------------------------------------ dados fictícios
def _patch_wifi() -> None:
    from pccc.network import wifi
    real_read = wifi.WifiReader.read

    def read(self):
        info = real_read(self)
        if getattr(info, "ssid", ""):
            info.ssid = "MinhaRede-5G"
            info.bssid = "02:00:5E:10:20:30"
        return info
    wifi.WifiReader.read = read


def _patch_lan() -> None:
    from pccc.network import devices as lan
    demo = [  # (ip final, MAC fictício com prefixo público do fabricante, nome, eu, roteador)
        (1, "C8-3A-35-12-34-56", "roteador", False, True),
        (10, "CC-47-40-AA-BB-01", "MEU-PC", True, False),
        (11, "DA-12-34-56-78-9A", "", False, False),
        (12, "90-A8-22-11-22-33", "", False, False),
        (20, "04-EC-D8-44-55-66", "NOTEBOOK-TRABALHO", False, False),
        (30, "04-AB-08-77-88-99", "", False, False),
        (31, "3C-5A-B4-10-20-30", "", False, False),
        (40, "B6-AD-73-00-11-22", "", False, False),
    ]
    customs = {11: "Celular", 12: "Alexa da cozinha", 30: "TV da sala", 31: "Chromecast"}

    def scan(progress=None):
        net = ipaddress.IPv4Network("192.168.0.0/24")
        ln = lan.LocalNet("Wi-Fi", "192.168.0.10", net, "192.168.0.1", "CC-47-40-AA-BB-01", "MinhaRede-5G")
        if progress:
            progress("Procurando em 192.168.0.0/24 (254 endereços)...")
        now = time.time()
        devs = []
        for last, mac, name, me, gw in demo:
            d = lan.LanDevice(ip=f"192.168.0.{last}", mac=mac, name=name, is_self=me, is_gateway=gw,
                              randomized=lan.is_randomized(mac), first_seen=now, last_seen=now)
            d.vendor = lan.vendor(mac)
            lan.classify(d)
            devs.append(d)
        nid = lan.network_id(ln, [d for d in devs if d.is_gateway])
        for last, label in customs.items():
            mac = next(m for i, m, *_ in demo if i == last)
            lan.set_custom(nid, mac, custom_name=label, known=True)
        return ln, devs
    lan.scan = scan


# ------------------------------------------------------------- área de trabalho
def _wallpaper(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor("#0b1026"))
    g.setColorAt(0.55, QColor("#1b1f4b"))
    g.setColorAt(1, QColor("#3a1846"))
    p.fillRect(img.rect(), g)
    for cx, cy, r, col in ((0.78, 0.28, 0.45, "#22d3ee"), (0.18, 0.85, 0.5, "#a78bfa"),
                           (0.55, 0.65, 0.3, "#f472b6")):
        rg = QRadialGradient(QPointF(cx * w, cy * h), r * w)
        c = QColor(col)
        c.setAlpha(70)
        rg.setColorAt(0, c)
        c.setAlpha(0)
        rg.setColorAt(1, c)
        p.fillRect(img.rect(), rg)
    # barra de tarefas simplificada
    p.fillRect(QRectF(0, h - 48, w, 48), QColor(16, 18, 32, 230))
    for i in range(5):
        path = QPainterPath()
        path.addRoundedRect(QRectF(w / 2 - 130 + i * 54, h - 40, 40, 32), 6, 6)
        p.fillPath(path, QColor(255, 255, 255, 30 if i else 60))
    p.end()
    return img


def desktop_shot(path: Path) -> None:
    from pccc.widgets.base import WidgetConfig
    from pccc.widgets.types import REGISTRY
    from pccc.widgets.window import paint_widget
    w, h = 1600, 900
    img = _wallpaper(w, h)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    # (tipo, x, y): coluna da direita como num desktop de verdade, e o visualizador embaixo
    layout = [("clock", 1310, 24), ("weather", 1288, 156), ("cpu", 1330, 330), ("ram", 1330, 472),
              ("netspeed", 1330, 614), ("calendar", 24, 24), ("sysinfo", 24, 290), ("wifi", 24, 464)]
    for type_id, x, y in layout:
        cfg = WidgetConfig(type=type_id)
        r = REGISTRY[type_id](cfg)
        bw, bh = r.base_size
        p.save()
        p.translate(x, y)
        paint_widget(p, r, cfg, bw, bh)
        p.restore()
    p.end()
    img.save(str(path))


# ------------------------------------------------------------------ janela
def main() -> int:
    from pccc.core.logger import setup_logging
    setup_logging()
    app = QApplication(sys.argv)
    _patch_wifi()
    _patch_lan()
    from pccc.monitoring.collector import MonitorService
    from pccc.network.monitor import NetworkService
    from pccc.ui.main_window import MainWindow
    from pccc.ui.theme import ThemeManager
    from pccc.widgets.hub import DataHub

    OUT.mkdir(parents=True, exist_ok=True)
    ThemeManager.instance().apply()
    svc, net = MonitorService.instance(), NetworkService.instance()
    win = MainWindow()
    win.resize(1400, 860)
    win.show()
    svc.start()
    net.start()
    DataHub.instance().weather(-23.5475, -46.63611)   # São Paulo, o padrão do app

    # (página, aba ou None, arquivo, espera em ms)
    plan = [(0, None, "painel.png", 1500), (1, None, "desempenho.png", 1500),
            (2, "devices", "rede-aparelhos.png", 4000), (10, "scenes", "cenarios.png", 1500)]

    def run(i=0):
        if i >= len(plan):
            desktop_shot(OUT / "widgets-desktop.png")
            app.setProperty("force_quit", True)
            win.quit_app()
            return
        idx, tab, name, wait = plan[i]
        win.show_page(idx)
        page = win.stack.widget(idx)
        if tab:
            page.switch(tab)

        def shot():
            win.grab().save(str(OUT / name))
            run(i + 1)
        if tab == "devices":
            # 1ª busca = referência; os nomes dados aos aparelhos aparecem a partir da 2ª
            QTimer.singleShot(wait, page.devices_view.scan_btn.click)
            wait *= 2
        QTimer.singleShot(wait, shot)

    QTimer.singleShot(45000, run)  # tempo para encher os gráficos com leituras reais
    app.exec()
    from pccc.ui.tasks import wait_all
    from pccc.widgets.media import MediaService
    wait_all()
    MediaService.instance().stop()
    svc.stop()
    net.stop()
    print("capturas em", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
