"""Teste das janelas reais dos widgets (mouse, encaixe, redimensionar, propriedades da janela).

Usa um widgets.json TEMPORÁRIO — o layout do usuário não é alterado. Os widgets aparecem
por ~3 segundos no canto da tela e são fechados.

Execute:  python -m tests.test_widget_windows [pasta_de_saida]
"""
import ctypes
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pccc.core.logger import setup_logging  # noqa: E402

GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_LAYERED = -20, 0x80, 0x40000, 0x80000


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "widget_shots")
    out.mkdir(parents=True, exist_ok=True)
    setup_logging()
    app = QApplication(sys.argv)
    from pccc.monitoring.collector import MonitorService
    from pccc.network.monitor import NetworkService
    from pccc.ui.tasks import wait_all
    from pccc.ui.theme import ThemeManager
    from pccc.widgets import manager as mgr_mod
    from pccc.widgets.media import MediaService

    ThemeManager.instance().apply()
    MonitorService.instance().start()
    NetworkService.instance().start()
    tmp = Path(tempfile.mkdtemp()) / "widgets.json"
    mgr_mod._file = lambda: tmp
    m = mgr_mod.WidgetManager()
    m.start()
    results = {}

    def run():
        cal = m.add("calendar")
        cpu = m.add("cpu")
        clock = m.add("clock")
        app.processEvents()
        user32 = ctypes.windll.user32
        ex = user32.GetWindowLongW(int(cpu.winId()), GWL_EXSTYLE)
        results["fora da barra de tarefas (TOOLWINDOW)"] = bool(ex & WS_EX_TOOLWINDOW) and not ex & WS_EX_APPWINDOW
        results["fundo translúcido (LAYERED)"] = bool(ex & WS_EX_LAYERED)
        results["não rouba o foco"] = user32.GetForegroundWindow() not in (int(w.winId()) for w in m.windows.values())

        # arrastar o widget de CPU 300 px para a esquerda
        before = cpu.pos()
        QTest.mousePress(cpu, Qt.LeftButton, Qt.NoModifier, QPoint(30, 30))
        for dx in range(0, -301, -30):
            QTest.mouseMove(cpu, QPoint(30 + dx, 30))
            app.processEvents()
        QTest.mouseRelease(cpu, Qt.LeftButton, Qt.NoModifier, QPoint(-270, 30))
        results["arrastar move e salva posição"] = cpu.x() < before.x() - 200 and cpu.cfg.x == cpu.x()

        # encaixe na borda direita da tela
        area = QGuiApplication.primaryScreen().availableGeometry()
        snapped = cpu._snap(QPoint(area.right() - cpu.width() - 5, 300))
        results["encaixa na borda da tela"] = snapped.x() == area.right() + 1 - cpu.width()

        # Ctrl + roda do mouse aumenta
        w0 = clock.width()
        ev = QWheelEvent(QPointF(10, 10), QPointF(clock.mapToGlobal(QPoint(10, 10))), QPoint(0, 0),
                         QPoint(0, 120), Qt.NoButton, Qt.ControlModifier, Qt.ScrollUpdate, False)
        QApplication.sendEvent(clock, ev)
        results["Ctrl+roda redimensiona mantendo proporção"] = (
            clock.width() > w0 and abs(clock.height() / clock.width() - 118 / 270) < 0.02)

        # clique no botão "próximo mês" do calendário
        s = cal.width() / 262
        QTest.mouseClick(cal, Qt.LeftButton, Qt.NoModifier, QPoint(int(240 * s), int(23 * s)))
        results["clique em botão do widget (calendário → próximo mês)"] = cal.renderer.offset == 1

        # bloquear impede arrastar
        cal.cfg.locked = True
        p0 = cal.pos()
        QTest.mousePress(cal, Qt.LeftButton, Qt.NoModifier, QPoint(100, 120))
        QTest.mouseMove(cal, QPoint(20, 120))
        QTest.mouseRelease(cal, Qt.LeftButton, Qt.NoModifier, QPoint(20, 120))
        results["bloqueado não se move"] = cal.pos() == p0

        for w in (cal, cpu, clock):
            w.grab().save(str(out / f"real_{w.cfg.type}.png"))
        QTimer.singleShot(2500, finish)

    def finish():
        m._save_now()
        import json
        saved = json.loads(tmp.read_text(encoding="utf-8"))["profiles"]["Padrão"]
        results["layout gravado em disco"] = len(saved) == 3
        m.shutdown()
        app.quit()

    QTimer.singleShot(2500, run)
    app.exec()
    wait_all()
    MediaService.instance().stop()
    MonitorService.instance().stop()
    NetworkService.instance().stop()
    ok = all(results.values())
    for k, v in results.items():
        print(f"{'OK ' if v else 'FALHOU'}  {k}")
    print("OK" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
