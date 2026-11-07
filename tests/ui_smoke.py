"""Teste de fumaça da interface: abre a janela, percorre todas as páginas e salva capturas.

Execute:  python -m tests.ui_smoke [pasta_de_saida]
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pccc.core.logger import setup_logging  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
    out.mkdir(parents=True, exist_ok=True)
    setup_logging()
    app = QApplication(sys.argv)
    from pccc.monitoring.collector import MonitorService
    from pccc.ui.main_window import MainWindow
    from pccc.ui.theme import ThemeManager

    from pccc.network.monitor import NetworkService

    ThemeManager.instance().apply()
    svc = MonitorService.instance()
    net = NetworkService.instance()
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    svc.start()
    net.start()

    shots = [(0, "dashboard"), (1, "performance"), (2, "network"), (4, "widgets"), (7, "tools"),
             (8, "settings")]
    errors = []

    def step(i=0):
        if i < len(shots):
            idx, name = shots[i]
            win.show_page(idx)
            def shot(idx=idx, name=name):
                win.grab().save(str(out / f"{name}.png"))
                body = getattr(win.stack.widget(idx), "body", None)
                if body is not None and name in ("network", "widgets"):  # página inteira (parte rolada)
                    body.grab().save(str(out / f"{name}_full.png"))
                step(i + 1)
            QTimer.singleShot(2500 if name == "network" else 1500, shot)
        else:
            # sub-abas de desempenho
            perf = win.stack.widget(1)
            win.show_page(1)
            subs = ["mem", "gpu", "disk", "hist"]

            def sub(j=0):
                if j < len(subs):
                    perf._switch(subs[j])
                    QTimer.singleShot(1300, lambda: (win.grab().save(str(out / f"perf_{subs[j]}.png")), sub(j + 1)))
                else:
                    apps_tabs()
            sub()

    def apps_tabs():
        page = win.stack.widget(3)
        win.show_page(3)
        # (aba, espera em ms): a lista da Store leva alguns segundos para carregar
        tabs = [("installed", 11000), ("procs", 3500), ("startup", 2500)]

        def tab(j=0):
            if j < len(tabs):
                key, wait = tabs[j]
                page.switch(key)
                QTimer.singleShot(wait, lambda: (win.grab().save(str(out / f"apps_{key}.png")), tab(j + 1)))
            else:
                pers_tabs()
        tab()

    def pers_tabs():
        page = win.stack.widget(5)
        win.show_page(5)
        tabs = [("look", 1500), ("wall", 4000), ("themes", 4000), ("taskbar", 1200), ("desktop", 1200),
                ("shortcuts", 1200), ("defaults", 2000), ("history", 1000)]

        def tab(j=0):
            if j < len(tabs):
                key, wait = tabs[j]
                page.switch(key)

                def shot():
                    if key == "themes" and os.environ.get("PCCC_DEBUG"):
                        g = page.theme_grid
                        print("DEBUG", len(g._items), g.geometry(), g.isVisible(), g.parentWidget().geometry(),
                              [(w.geometry().height(), w.isVisible()) for w, _ in g._items[:3]])
                    if page.body.minimumSizeHint().width() > page.width():
                        print(f"AVISO: aba {key} mais larga que a página "
                              f"({page.body.minimumSizeHint().width()} > {page.width()})")
                    win.grab().save(str(out / f"pers_{key}.png"))
                    tab(j + 1)
                QTimer.singleShot(wait, shot)
            else:
                alert_tabs()
        tab()

    def alert_tabs():
        page = win.stack.widget(6)
        win.show_page(6)
        tabs = [("center", 1500), ("rules", 1200), ("diag", 7000), ("reports", 3000)]

        def tab(j=0):
            if j < len(tabs):
                key, wait = tabs[j]
                page.switch(key)

                def shot():
                    if page.body.minimumSizeHint().width() > page.width():
                        print(f"AVISO: aba {key} mais larga que a página")
                    win.grab().save(str(out / f"alerts_{key}.png"))
                    tab(j + 1)
                QTimer.singleShot(wait, shot)
            else:
                phase9_tabs()
        tab()

    def phase9_tabs():
        # (página, prefixo, [(aba, espera ms)]) — só exibe; nenhuma ação é executada
        plan = [(2, "network", [("devices", 15000), ("conn", 1500)]),
                (9, "media", [("audio", 2500), ("obs", 1000), ("youtube", 2500), ("fps", 1200)]),
                (10, "scenes", [("scenes", 1200), ("auto", 1000), ("live", 1000), ("display", 2500),
                                ("keys", 1000), ("bundle", 800)])]
        jobs = [(idx, pre, key, wait) for idx, pre, tabs in plan for key, wait in tabs]

        def run(j=0):
            if j >= len(jobs):
                light()
                return
            idx, pre, key, wait = jobs[j]
            page = win.stack.widget(idx)
            win.show_page(idx)
            page.switch(key)

            def shot():
                if page.body.minimumSizeHint().width() > page.width():
                    print(f"AVISO: aba {pre}/{key} mais larga que a página "
                          f"({page.body.minimumSizeHint().width()} > {page.width()})")
                win.grab().save(str(out / f"{pre}_{key}.png"))
                run(j + 1)
            QTimer.singleShot(wait, shot)
        run()

    def light():
        from pccc.core.config import Settings
        s = Settings.instance()
        old = s.get("appearance.mode")
        s.set("appearance.mode", "light")
        win.show_page(0)

        def done():
            win.grab().save(str(out / "dashboard_light.png"))
            s.set("appearance.mode", old)
            app.setProperty("force_quit", True)
            win.quit_app()
        QTimer.singleShot(1500, done)

    QTimer.singleShot(5000, step)
    app.exec()
    from pccc.ui.tasks import wait_all
    from pccc.widgets.media import MediaService
    wait_all()
    MediaService.instance().stop()
    svc.stop()
    net.stop()
    print("capturas em", out.resolve(), "erros:", errors)
    return 0


if __name__ == "__main__":
    sys.exit(main())
