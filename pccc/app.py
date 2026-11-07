"""Inicialização do aplicativo: instância única, tema, coletor e janela."""
from __future__ import annotations

import argparse
import ctypes
import getpass
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import __app_name__, __version__
from .core.config import Settings
from .core.database import Database
from .core.logger import get_logger, setup_logging

log = get_logger("app")


def _server_name() -> str:
    return f"PCControlCenter-{getpass.getuser()}"


def _notify_running_instance() -> bool:
    """Se já houver uma instância aberta, pede para ela aparecer e retorna True."""
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def _boot_phase9(settings) -> None:
    """Atalhos, tema automático, papéis de parede vivos, OBS e YouTube (cada um isolado:
    se um falhar, o resto do app abre normalmente)."""
    def step(name, fn):
        try:
            fn()
        except Exception:
            log.exception("Falha ao iniciar %s", name)

    from .personalization.hotkeys import HotkeyManager
    step("atalhos", HotkeyManager.instance().apply)
    from .personalization.autotheme import AutoTheme
    step("tema automático", AutoTheme.instance().boot)
    if settings.get("dynwall.enabled"):
        from .personalization.dynwall import DynamicWallpaper
        step("papel de parede dinâmico", DynamicWallpaper.instance().start)
    if settings.get("livewall.enabled"):
        from .personalization.livewall import LiveWallpaper
        step("papel de parede animado", LiveWallpaper.instance().start)
    if settings.get("media.obs.enabled"):
        from .media.obs import ObsClient
        step("OBS", ObsClient.instance)          # conecta sozinho quando o OBS abrir
    from .media.youtube import YouTubeFeed
    step("YouTube", YouTubeFeed.instance().start)
    if settings.get("network.devices_watch"):
        from PySide6.QtCore import QTimer
        from .network.devices import LanWatcher
        # primeira busca 1 min depois de abrir (a rede costuma demorar a conectar após o login)
        step("vigiar a rede", lambda: QTimer.singleShot(60_000, lambda: LanWatcher.instance().scan(notify=True)))


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pccc")
    parser.add_argument("--minimized", action="store_true", help="inicia oculto na bandeja")
    parser.add_argument("--debug", action="store_true", help="log detalhado")
    args, _ = parser.parse_known_args(argv)

    setup_logging(args.debug)
    log.info("Iniciando %s v%s", __app_name__, __version__)

    # Ícone próprio na barra de tarefas (em vez do ícone do Python).
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PCControlCenter.App")
    except Exception:
        pass

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)  # continua vivo na bandeja
    app.setFont(QFont("Segoe UI", 10))

    if _notify_running_instance():
        log.info("Já existe uma instância aberta — trazendo-a para frente.")
        return 0

    # Sinaliza "app aberto" para o instalador/desinstalador pedir que ele seja fechado antes.
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "PCControlCenter.Running")  # noqa: F841

    # Importações pesadas só depois de garantir instância única.
    from .monitoring.collector import MonitorService
    from .network.monitor import NetworkService
    from .ui.main_window import MainWindow
    from .ui.theme import ThemeManager

    settings = Settings.instance()
    Database.instance()
    from .core import autostart
    autostart.sync()
    ThemeManager.instance().apply()

    service = MonitorService.instance()
    window = MainWindow()

    server = QLocalServer()
    QLocalServer.removeServer(_server_name())
    server.listen(_server_name())

    def _on_connection():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.waitForReadyRead(200)
            window.restore()
            conn.disconnectFromServer()

    server.newConnection.connect(_on_connection)

    service.start()
    net_service = NetworkService.instance()
    net_service.start()
    from .widgets.manager import WidgetManager
    WidgetManager.instance().start()   # abre os widgets do perfil ativo
    from .automation.engine import AlertEngine
    AlertEngine.instance().connect_services()   # alertas, uso por app e relatório semanal
    _boot_phase9(settings)
    if args.minimized or settings.get("general.start_minimized"):
        log.info("Iniciado minimizado na bandeja")
    else:
        window.show()

    recovered = Database.instance().recovered_from
    if recovered:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(None, __app_name__,
                            "O banco de dados do histórico estava danificado (por exemplo, após um "
                            "desligamento forçado) e foi recriado. O arquivo antigo foi guardado em:\n\n"
                            f"{recovered}")

    code = app.exec()
    log.info("Encerrando")
    WidgetManager.instance().shutdown()
    from .ui.tasks import wait_all
    wait_all()          # tarefas em segundo plano (clima, inventário...) terminam antes de sair
    service.stop()
    net_service.stop()
    server.close()
    Database.instance().close()
    return code
