"""Testes dos widgets (Fase 5), sem tocar no layout real do usuário.

1. Desenha os 15 tipos com dados reais em imagens (tamanho normal e 2x) → pasta de saída.
2. Gerenciador: adicionar, mover, perfis, ocultar e salvar/recarregar — usando um
   widgets.json temporário e a plataforma "offscreen" (nenhuma janela aparece na tela).

Execute:  python -m tests.test_widgets [pasta_de_saida]
"""
import os
import sys
import tempfile
from pathlib import Path

# "--render-only": desenha em imagens com as fontes reais do Windows (nenhuma janela é
# aberta). Sem a opção, usa a plataforma "offscreen" para testar o gerenciador sem
# mostrar janelas — nela o texto aparece como caixinhas porque as fontes do sistema não carregam.
RENDER_ONLY = "--render-only" in sys.argv
if RENDER_ONLY:
    sys.argv.remove("--render-only")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pccc.core.logger import setup_logging  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "widget_shots")
    out.mkdir(parents=True, exist_ok=True)
    setup_logging()
    app = QApplication(sys.argv)

    from pccc.monitoring.collector import MonitorService
    from pccc.network.monitor import NetworkService
    from pccc.ui.theme import ThemeManager
    from pccc.widgets import manager as mgr_mod
    from pccc.widgets.base import WidgetConfig
    from pccc.widgets.hub import DataHub
    from pccc.widgets.types import REGISTRY
    from pccc.widgets.window import paint_widget

    ThemeManager.instance().apply()
    MonitorService.instance().start()
    NetworkService.instance().start()
    hub = DataHub.instance()
    hub.weather(-23.5475, -46.63611)     # já dispara a busca do clima (São Paulo, padrão)
    errors: list[str] = []

    def render_all():
        for type_id, cls in REGISTRY.items():
            cfg = WidgetConfig(type=type_id)
            r = cls(cfg)
            if type_id == "shortcuts":
                win = os.environ.get("WINDIR", r"C:\Windows")
                cfg.options["items"] = [{"name": "Explorador", "path": rf"{win}\explorer.exe"},
                                        {"name": "Notas", "path": rf"{win}\System32\notepad.exe"},
                                        {"name": "Site", "path": "https://example.com"}]
            for scale in (1, 2):
                bw, bh = r.base_size
                img = QImage(int(bw * scale), int(bh * scale), QImage.Format.Format_ARGB32_Premultiplied)
                img.fill(QColor("#1e293b"))   # simula um papel de parede
                p = QPainter(img)
                try:
                    paint_widget(p, r, cfg, bw * scale, bh * scale)
                except Exception as e:
                    errors.append(f"{type_id}: {e!r}")
                finally:
                    p.end()
                img.save(str(out / f"w_{type_id}_{scale}x.png"))
        print(f"desenho: {len(REGISTRY)} tipos × 2 tamanhos, erros: {errors}")
        if RENDER_ONLY:
            app.quit()
        else:
            test_manager()

    def test_manager():
        tmp = Path(tempfile.mkdtemp()) / "widgets.json"
        mgr_mod._file = lambda: tmp           # isola do arquivo real do usuário
        m = mgr_mod.WidgetManager()
        m.start()
        w1 = m.add("clock")
        w2 = m.add("cpu")
        assert len(m.windows) == 2
        # o segundo foi posicionado sem sobrepor o primeiro
        assert not w1.geometry().intersects(w2.geometry()), (w1.geometry(), w2.geometry())
        w1.cfg.x, w1.cfg.y, w1.cfg.width = 300, 200, 400
        w1.apply_geometry()
        m.set_visible(w2.cfg.id, False)
        m.create_profile("Jogos", copy_current=True)
        assert m.active == "Jogos" and len(m.windows) == 2
        m.add("netspeed")
        m.switch_profile("Padrão")
        assert len(m.windows) == 2
        m._save_now()
        # recarrega do disco como se o app tivesse reiniciado
        m2 = mgr_mod.WidgetManager()
        assert set(m2.profile_names()) == {"Padrão", "Jogos"}, m2.profile_names()
        assert len(m2.profiles["Jogos"]) == 3
        clock = next(d for d in m2.profiles["Padrão"] if d["type"] == "clock")
        assert (clock["x"], clock["y"], clock["width"]) == (300, 200, 400), clock
        assert next(d for d in m2.profiles["Padrão"] if d["type"] == "cpu")["visible"] is False
        m.rename_profile("Jogos", "Games")
        m.delete_profile("Games")
        assert m.profile_names() == ["Padrão"]
        m.shutdown()
        print("gerenciador: adicionar, posição livre, perfis, ocultar, salvar/recarregar  OK")
        app.quit()

    QTimer.singleShot(6000, render_all)   # espera dados reais (sistema, rede, clima)
    app.exec()
    from pccc.ui.tasks import wait_all
    from pccc.widgets.media import MediaService
    wait_all()
    MediaService.instance().stop()
    MonitorService.instance().stop()
    NetworkService.instance().stop()
    if errors:
        print("FALHOU")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
