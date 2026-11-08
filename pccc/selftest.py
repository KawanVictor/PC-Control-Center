"""Autoteste sem interface: ``PC Control Center.exe --selftest`` (ou ``python main.py --selftest``).

Confere em ~5 segundos se todas as partes do app funcionam neste computador — principalmente
útil para validar o .EXE, onde um módulo esquecido no empacotamento só apareceria em uso.
Nenhuma janela é aberta e nada no sistema é alterado.

O resultado vai para ``%APPDATA%\\PCControlCenter\\logs\\selftest.txt`` (e para o console,
quando existir). Código de saída 0 = tudo certo.
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import __app_name__, __version__
from .core.logger import get_logger, setup_logging
from .core.paths import is_frozen, log_dir

log = get_logger("selftest")


def _check_modules() -> str:
    import pccc
    names = [m.name for m in pkgutil.walk_packages(pccc.__path__, "pccc.")]
    failed = []
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as e:      # noqa: BLE001
            failed.append(f"{name}: {e}")
    if failed:
        raise RuntimeError("; ".join(failed))
    return f"{len(names)} módulos carregados"


def _check_settings() -> str:
    from .core.config import Settings
    from .core.paths import resource_path
    path = resource_path("config", "default_settings.json")
    assert path.exists(), f"padrões não encontrados em {path}"
    s = Settings.instance()
    assert s.get("monitoring.refresh_ms"), "chave monitoring.refresh_ms ausente"
    return f"padrões em {path.parent}"


def _check_data_dir() -> str:
    from .core.paths import data_dir
    probe = data_dir() / f".selftest-{os.getpid()}"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return str(data_dir())


def _check_database() -> str:
    from .core.database import Database
    db = Database.instance()
    with db._lock:
        ok = db._conn.execute("PRAGMA quick_check").fetchone()[0]
        n = db._conn.execute("SELECT COUNT(*) FROM metrics_history").fetchone()[0]
    assert ok == "ok", ok
    return f"íntegro, {n} minutos de histórico"


def _check_wmi() -> str:
    from .core.com import ensure_com
    ensure_com()
    import wmi
    os_ = wmi.WMI().Win32_OperatingSystem()[0]
    return f"{os_.Caption.strip()} (build {os_.BuildNumber})"


def _check_charts() -> str:
    import pyqtgraph as pg
    w = pg.PlotWidget()
    w.plot([0, 1, 2, 3], [1, 3, 2, 4])
    w.resize(200, 120)
    img = w.grab()
    assert not img.isNull()
    return f"pyqtgraph {pg.__version__}"


def _check_widgets() -> str:
    from PySide6.QtGui import QColor, QImage, QPainter
    from .widgets.base import WidgetConfig
    from .widgets.types import REGISTRY
    from .widgets.window import paint_widget
    for type_id, cls in REGISTRY.items():
        cfg = WidgetConfig(type=type_id)
        r = cls(cfg)
        bw, bh = r.base_size
        img = QImage(int(bw), int(bh), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor("#1e293b"))
        p = QPainter(img)
        try:
            paint_widget(p, r, cfg, bw, bh)
        finally:
            p.end()
    return f"{len(REGISTRY)} tipos desenhados"


def _check_window() -> str:
    """Monta a janela principal (sem exibir) e desenha cada página fora da tela."""
    from PySide6.QtWidgets import QSystemTrayIcon
    from .ui.main_window import MainWindow
    from .ui.theme import ThemeManager
    QSystemTrayIcon.show = lambda self: None  # type: ignore[method-assign]  # sem ícone na bandeja no teste
    ThemeManager.instance().apply()
    win = MainWindow()
    win.resize(1280, 800)
    n = win.stack.count()
    for i in range(n):
        page = win.stack.widget(i)
        assert page is not None, f"página {i} não existe"
        page.resize(1000, 760)
        assert not page.grab().isNull(), f"página {i} não desenhou"
    if win.tray is not None:
        win.tray.hide()
    win.deleteLater()
    return f"{n} páginas montadas"


def _check_media() -> str:
    from winrt.windows.media.control import \
        GlobalSystemMediaTransportControlsSessionManager as Manager  # noqa: F401
    from winrt.windows.storage.streams import DataReader  # noqa: F401
    return "controles de mídia do Windows disponíveis"


def _check_audio() -> str:
    from .media import audio
    devs = audio.output_devices()
    vol, _m = audio.master_volume()
    apps = audio.app_sessions()
    return f"{len(devs)} saída(s), volume {vol * 100:.0f}%, {len(apps)} app(s) com som"


def _check_visualizer() -> str:
    from .media.visualizer import AudioVisualizer
    v = AudioVisualizer()
    t = time.monotonic()
    while time.monotonic() - t < 1.5:
        bands, _p, _l = v.snapshot()
        time.sleep(0.05)
    alive = v._thread is not None and v._thread.is_alive()
    v.stop()
    if v.error:
        raise RuntimeError(v.error)
    assert alive, "captura não iniciou"
    return f"captura do som ok ({len(bands)} faixas)"


def _check_multimedia() -> str:
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget  # noqa: F401
    from PySide6.QtWebSockets import QWebSocket  # noqa: F401
    from PySide6.QtMultimedia import QVideoSink
    from PySide6.QtWidgets import QApplication
    import glob
    from .personalization.livewall import wallpaper_host
    # reproduz de verdade (fora da tela, sem som) um vídeo que vem com o Windows
    videos = glob.glob(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "SystemApps", "*", "media", "*.mp4"))
    decoded = "sem vídeo de exemplo para testar"
    if videos:
        from PySide6.QtCore import QUrl
        p = QMediaPlayer()
        sink = QVideoSink()
        frames = []
        sink.videoFrameChanged.connect(lambda f: frames.append(f.isValid()))
        p.setVideoOutput(sink)
        p.setSource(QUrl.fromLocalFile(videos[0]))
        p.play()
        t = time.monotonic()
        while time.monotonic() - t < 4 and not frames:
            QApplication.processEvents()
            time.sleep(0.02)
        p.stop()
        if p.error() != QMediaPlayer.Error.NoError:
            raise RuntimeError(f"vídeo não reproduziu: {p.errorString()}")
        assert frames, "nenhum quadro de vídeo decodificado"
        decoded = "vídeo decodificado"
    host = "camada do papel de parede ok" if wallpaper_host() else "camada do papel de parede NÃO encontrada"
    return f"{decoded}, WebSocket ok, {host}"


def _check_lan() -> str:
    from .network import devices as lan
    ln = lan.local_network()
    if ln is None:
        return "sem rede local agora"
    known = lan.arp_table(ln.network)
    assert lan.send_arp(ln.gateway) if ln.gateway else True, "o roteador não respondeu ao ARP"
    return f"faixa {ln.network}, {len(known)} vizinho(s) conhecidos, roteador respondeu"


def _check_report() -> str:
    from .automation import reports
    rep = reports.build_report("24h")
    out = Path(tempfile.mkdtemp(prefix="pccc-selftest-"))
    try:
        html = Path(reports.export_html(rep, out / "r.html"))
        csv = Path(reports.export_csv(rep, out / "r.csv"))
        assert html.stat().st_size > 1000 and csv.stat().st_size > 50
    finally:
        for f in out.iterdir():
            f.unlink()
        out.rmdir()
    return "HTML e CSV gerados"


def _check_safety() -> str:
    from .core.safety import is_protected_path, ps_quote, safe_delete_file
    win = os.environ.get("SystemRoot", r"C:\Windows")
    assert is_protected_path(win) and is_protected_path(os.path.join(win, "System32", "x.lnk"))
    assert is_protected_path("C:\\")
    assert ps_quote("a'b") == "'a''b'"
    try:
        safe_delete_file(os.path.join(win, "notepad.exe"), "selftest")
    except PermissionError:
        pass
    else:
        raise AssertionError("exclusão de .exe não foi bloqueada")
    from .apps.processes import CRITICAL
    assert {"csrss.exe", "lsass.exe", "winlogon.exe"} <= {c.lower() for c in CRITICAL}
    return "proteções ativas"


def main() -> int:
    setup_logging()
    lines = [f"{__app_name__} v{__version__} — autoteste {time.strftime('%d/%m/%Y %H:%M:%S')}",
             f"Executável: {sys.executable} ({'empacotado' if is_frozen() else 'Python'})", ""]
    app = QApplication(sys.argv)
    from .monitoring.collector import MonitorService
    from .network.monitor import NetworkService
    snaps: list = []
    nets: list = []
    MonitorService.instance().snapshot.connect(snaps.append)
    NetworkService.instance().snapshot.connect(nets.append)
    MonitorService.instance().start()
    NetworkService.instance().start()
    results: list[tuple[str, bool, str]] = []

    def run(name, fn):
        t = time.perf_counter()
        try:
            detail = fn()
            results.append((name, True, f"{detail} ({(time.perf_counter() - t) * 1000:.0f} ms)"))
        except Exception as e:      # noqa: BLE001
            log.error("autoteste %s: %s", name, traceback.format_exc())
            results.append((name, False, f"{type(e).__name__}: {e}"))

    def monitoring() -> str:
        assert snaps, "nenhuma leitura recebida"
        s = snaps[-1]
        assert s.cpu.per_core and s.memory.total > 0 and s.partitions and s.processes.total > 10
        return (f"CPU {s.cpu.percent:.0f}% ({len(s.cpu.per_core)} núcleos), RAM {s.memory.percent:.0f}%, "
                f"{len(s.gpus)} GPU(s), {s.processes.total} processos")

    def network() -> str:
        assert nets, "nenhuma leitura de rede recebida"
        n = nets[-1]
        return f"{len(n.interfaces)} interfaces, ativa: {n.active.name if n.active else 'nenhuma'}"

    def go():
        for name, fn in (("Módulos", _check_modules), ("Configurações", _check_settings),
                         ("Pasta de dados", _check_data_dir), ("Banco de dados", _check_database),
                         ("Monitoramento", monitoring), ("Rede", network), ("Rede local", _check_lan),
                         ("WMI/COM", _check_wmi),
                         ("Gráficos", _check_charts), ("Interface", _check_window), ("Widgets", _check_widgets),
                         ("Player (WinRT)", _check_media), ("Áudio (mixer)", _check_audio),
                         ("Visualizador", _check_visualizer), ("Vídeo/OBS", _check_multimedia),
                         ("Relatórios", _check_report),
                         ("Segurança", _check_safety)):
            run(name, fn)
        app.quit()

    QTimer.singleShot(4000, go)
    app.exec()
    from .ui.tasks import wait_all
    wait_all()
    MonitorService.instance().stop()
    NetworkService.instance().stop()

    for name, ok, detail in results:
        lines.append(f"[{'OK ' if ok else 'ERRO'}] {name:<16} {detail}")
    failed = sum(not ok for _, ok, _ in results)
    lines += ["", "RESULTADO: " + ("tudo certo" if not failed else f"{failed} verificação(ões) falharam")]
    text = "\n".join(lines)
    (log_dir() / "selftest.txt").write_text(text, encoding="utf-8")
    if sys.stdout is not None:
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", "replace").decode())
    return 1 if failed else 0
