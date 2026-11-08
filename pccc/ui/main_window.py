"""Janela principal: barra lateral, área de páginas, fundo e bandeja do sistema."""
from __future__ import annotations

import os

from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                            QParallelAnimationGroup)
from PySide6.QtGui import QAction, QColor, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QMainWindow, QMenu, QPushButton, QStackedWidget, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..core.config import Settings
from ..core.logger import get_logger
from ..core.winapi import apply_window_effects
from ..monitoring.collector import MonitorService
from ..monitoring.models import Snapshot
from .components import icon_label, label
from .fmt import fmt_pct, fmt_temp
from .history import History
from .pages.base import Page
from .qtutil import qapp
from .icons import G, make_app_icon
from ..network.monitor import NetworkService
from ..automation.engine import AlertEngine
from ..automation.notifier import Notifier
from .pages.alerts import AlertsPage
from .pages.apps import AppsPage
from .pages.dashboard import DashboardPage
from .pages.media import MediaPage
from .pages.scenes import ScenesPage
from .pages.network import NetworkPage
from .pages.personalization import PersonalizationPage
from .pages.performance import PerformancePage
from .pages.settings import SettingsPage
from .pages.tools import ToolsPage
from .pages.widgets import WidgetsPage
from ..widgets.manager import WidgetManager
from .theme import ThemeManager

log = get_logger("ui")

EXPANDED_W = 236
COLLAPSED_W = 72


class Background(QWidget):
    """Fundo com gradiente e brilhos suaves da cor de destaque (dá profundidade ao vidro)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cache: QPixmap | None = None
        ThemeManager.instance().changed.connect(self._invalidate)

    def _invalidate(self, *_a) -> None:
        self._cache = None
        self.update()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._cache = None

    def paintEvent(self, e) -> None:
        # O fundo é renderizado uma vez em cache: os cartões translúcidos repintam a
        # região de trás a cada atualização, e gradientes radiais são caros.
        if self._cache is None or self._cache.size() != self.size() * self.devicePixelRatioF():
            dpr = self.devicePixelRatioF()
            self._cache = QPixmap(self.size() * dpr)
            self._cache.setDevicePixelRatio(dpr)
            self._render(self._cache)
        r, dpr = e.rect(), self.devicePixelRatioF()
        p = QPainter(self)
        p.drawPixmap(QRectF(r), self._cache, QRectF(r.x() * dpr, r.y() * dpr, r.width() * dpr, r.height() * dpr))
        p.end()

    def _render(self, pm: QPixmap) -> None:
        t = ThemeManager.instance().theme
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        g = QLinearGradient(0, 0, r.width(), r.height())
        g.setColorAt(0, QColor(t.p["bg0"]))
        g.setColorAt(1, QColor(t.p["bg1"]))
        p.fillRect(r, g)
        for color, cx, cy, rad, alpha in ((t.accent, 0.85, 0.05, 0.55, 46 if t.dark else 40),
                                          (t.accent2, 0.15, 0.95, 0.60, 38 if t.dark else 30)):
            c = QColor(color)
            c.setAlpha(alpha)
            c2 = QColor(color)
            c2.setAlpha(0)
            radius = max(r.width(), r.height()) * rad
            rg = QRadialGradient(QPointF(r.width() * cx, r.height() * cy), radius)
            rg.setColorAt(0, c)
            rg.setColorAt(1, c2)
            p.fillRect(r, rg)
        p.end()


class NavButton(QPushButton):
    def __init__(self, glyph: str, text: str) -> None:
        super().__init__()
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(text)
        self.setMinimumHeight(42)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 10, 0)
        lay.setSpacing(14)
        self.icon_lbl = icon_label(glyph, 12.5, obj="")
        self.text_lbl = QLabel(text)
        for w in (self.icon_lbl, self.text_lbl):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(w)
        lay.addStretch(1)
        self.toggled.connect(self._restyle)
        ThemeManager.instance().changed.connect(lambda _t: self._restyle(self.isChecked()))
        self._restyle(False)

    def _restyle(self, checked: bool) -> None:
        t = ThemeManager.instance().theme
        self.icon_lbl.setStyleSheet(f"color: {t.accent if checked else t.p['muted']};")
        self.text_lbl.setStyleSheet(f"color: {t.p['text'] if checked else t.p['muted']};"
                                    f"font-weight: {600 if checked else 400};")

    def set_collapsed(self, collapsed: bool) -> None:
        self.text_lbl.setVisible(not collapsed)


class Sidebar(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(EXPANDED_W)
        self.collapsed = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 16, 12, 14)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(6, 0, 0, 10)
        self.logo_icon = QLabel()
        self._paint_logo(ThemeManager.instance().theme)
        head.addWidget(self.logo_icon)
        self.logo_text = QWidget()
        tl = QVBoxLayout(self.logo_text)
        tl.setContentsMargins(4, 0, 0, 0)
        tl.setSpacing(0)
        tl.addWidget(label("PC Control Center", "Logo"))
        tl.addWidget(label(f"Central do Windows · v{__version__}", "LogoSub"))
        head.addWidget(self.logo_text, 1)
        lay.addLayout(head)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[NavButton] = []
        self.top = QVBoxLayout()
        self.top.setSpacing(3)
        lay.addLayout(self.top)
        lay.addStretch(1)
        self.bottom = QVBoxLayout()
        self.bottom.setSpacing(3)
        lay.addLayout(self.bottom)

        self.toggle = QPushButton()
        self.toggle.setObjectName("NavButton")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setToolTip("Recolher / expandir menu")
        tlay = QHBoxLayout(self.toggle)
        tlay.setContentsMargins(14, 0, 10, 0)
        ic = icon_label(G.MENU, 12, obj="Muted")
        ic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        tlay.addWidget(ic)
        tlay.addStretch(1)
        self.toggle.setMinimumHeight(40)
        self.toggle.clicked.connect(self.toggle_collapsed)
        lay.addWidget(self.toggle)
        ThemeManager.instance().changed.connect(self._paint_logo)

    def _paint_logo(self, t) -> None:
        self.logo_icon.setPixmap(make_app_icon(t.accent, t.accent2).pixmap(QSize(34, 34)))

    def add_button(self, glyph: str, text: str, index: int, bottom: bool = False,
                   position: int | None = None) -> NavButton:
        b = NavButton(glyph, text)
        b.setProperty("page_index", index)
        self.group.addButton(b)
        lay = self.bottom if bottom else self.top
        if position is None:
            lay.addWidget(b)
        else:
            lay.insertWidget(position, b)
        self.buttons.append(b)      # buttons[i] = página i (a posição visual pode ser outra)
        return b

    def toggle_collapsed(self) -> None:
        self.collapsed = not self.collapsed
        target = COLLAPSED_W if self.collapsed else EXPANDED_W
        self._anims = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            a = QPropertyAnimation(self, prop)
            a.setDuration(220)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
            a.setStartValue(self.width())
            a.setEndValue(target)
            self._anims.addAnimation(a)
        if self.collapsed:
            self.logo_text.hide()
            for b in self.buttons:
                b.set_collapsed(True)
        else:
            self._anims.finished.connect(self._show_texts)
        self._anims.start()

    def _show_texts(self) -> None:
        self.logo_text.show()
        for b in self.buttons:
            b.set_collapsed(False)


def _hotkey_for(action: str) -> str:
    from ..personalization.hotkeys import bindings
    return bindings().get(action, "")


def _stop_livewall() -> None:
    from ..personalization.livewall import LiveWallpaper
    if LiveWallpaper._instance is not None:
        LiveWallpaper.instance().stop()


def _stop_warm() -> None:
    from ..personalization.display import WarmFilter
    if WarmFilter._instance is not None:
        WarmFilter.instance().shutdown()


def _stop_hotkeys() -> None:
    from ..personalization.hotkeys import HotkeyManager
    if HotkeyManager._instance is not None:
        HotkeyManager.instance().unregister_all()


def _stop_obs() -> None:
    from ..media.obs import ObsClient
    if ObsClient._instance is not None:
        ObsClient.instance().shutdown()


def _stop_fps() -> None:
    from ..media.fps import FpsMonitor
    if FpsMonitor._instance is not None:
        FpsMonitor.instance().stop()


def _stop_visualizer() -> None:
    from ..media.visualizer import AudioVisualizer
    if AudioVisualizer._instance is not None:
        AudioVisualizer.instance().stop()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.instance()
        self.setWindowTitle("PC Control Center")
        theme = ThemeManager.instance().theme
        self.setWindowIcon(make_app_icon(theme.accent, theme.accent2))
        self.resize(int(self.settings.get("window.width", 1360)), int(self.settings.get("window.height", 860)))
        self.setMinimumSize(900, 600)

        bg = Background()
        self.setCentralWidget(bg)
        root = QHBoxLayout(bg)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.sidebar = Sidebar()
        root.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # (glifo, texto, página, fica embaixo?, posição visual no menu)
        # Os índices das páginas 0–8 não mudam (usados por alertas e bandeja); as páginas da
        # Fase 9 entram no fim da lista, mas aparecem logo depois de "Widgets" no menu.
        pages = [
            (G.HOME, "Painel", DashboardPage(), False, None),
            (G.PERFORMANCE, "Desempenho", PerformancePage(), False, None),
            (G.NETWORK, "Rede e Wi-Fi", NetworkPage(), False, None),
            (G.APPS, "Aplicativos", AppsPage(), False, None),
            (G.WIDGETS, "Widgets", WidgetsPage(), False, None),
            (G.PERSONALIZE, "Personalização", PersonalizationPage(), False, None),
            (G.ALERTS, "Alertas", AlertsPage(), False, None),
            (G.TOOLS, "Ferramentas", ToolsPage(), False, None),
            (G.SETTINGS, "Configurações", SettingsPage(), True, None),
            (G.MEDIA, "Mídia e streaming", MediaPage(), False, 5),
            (G.SCENES, "Cenários e estilo", ScenesPage(), False, 6),
        ]
        for i, (glyph, text, page, bottom, pos) in enumerate(pages):
            self.stack.addWidget(page)
            self.sidebar.add_button(glyph, text, i, bottom, pos)
        self.sidebar.group.buttonClicked.connect(lambda b: self.show_page(b.property("page_index")))
        self.sidebar.buttons[0].setChecked(True)

        ThemeManager.instance().changed.connect(self._on_theme)
        self._setup_tray()
        MonitorService.instance().snapshot.connect(self._on_snapshot)
        NetworkService.instance().snapshot.connect(self._on_net_snapshot)

        # Alertas: balão na bandeja e contador de não lidos no menu
        Notifier.instance().sink = self._show_balloon
        eng = AlertEngine.instance()
        eng.unread_changed.connect(self._set_alert_badge)
        from ..automation.store import unread_count
        self._set_alert_badge(unread_count())
        if self.tray is not None:
            self.tray.messageClicked.connect(lambda: (self.restore(), self.show_page(6)))

        from ..personalization.hotkeys import HotkeyManager
        HotkeyManager.instance().triggered.connect(self.on_hotkey)

        wm = WidgetManager.instance()
        wm.configure_requested.connect(self._configure_widget)
        wm.open_app_requested.connect(lambda: (self.restore(), self.show_page(4)))
        wm.changed.connect(self._update_tray_widgets_action)

    # ----------------------------------------------------------------- alertas
    def _show_balloon(self, title: str, message: str, severity: str) -> None:
        if self.tray is None:
            raise RuntimeError("bandeja indisponível")
        icon = {"critical": QSystemTrayIcon.MessageIcon.Critical, "warning": QSystemTrayIcon.MessageIcon.Warning}.get(
            severity, QSystemTrayIcon.MessageIcon.Information)
        self.tray.showMessage(title, message, icon, 10_000)

    def _set_alert_badge(self, n: int) -> None:
        btn = self.sidebar.buttons[6]
        btn.text_lbl.setText(f"Alertas  ({n})" if n else "Alertas")
        btn.setToolTip(f"Alertas — {n} não lido(s)" if n else "Alertas")

    def navigate(self, action: str) -> None:
        """Ações vindas de alertas/sugestões: 'apps:procs', 'performance:mem', 'network',
        'page:...', 'shell:<alvo>', 'open:<arquivo>'."""
        from ..core.winapi import shell_open
        if action.startswith("shell:"):
            shell_open(action[6:])
            return
        if action.startswith("open:"):
            if os.path.exists(action[5:]):
                os.startfile(action[5:])
            return
        action = action.removeprefix("page:")
        page_key, _, sub = action.partition(":")
        index = {"dashboard": 0, "performance": 1, "network": 2, "apps": 3, "widgets": 4, "personalization": 5,
                 "alerts": 6, "tools": 7, "settings": 8, "media": 9, "scenes": 10}.get(page_key)
        if index is None:
            return
        self.restore()
        self.show_page(index)
        page = self._page(index)
        if sub:
            if hasattr(page, "switch"):
                page.switch(sub)
            elif hasattr(page, "_switch"):
                page._switch(sub)

    def _configure_widget(self, win) -> None:
        from .widget_dialog import WidgetConfigDialog
        # Sem pai: o diálogo aparece mesmo com a janela principal oculta na bandeja.
        dlg = WidgetConfigDialog(win)
        dlg.exec()
        WidgetManager.instance().save()
        WidgetManager.instance().changed.emit()

    def _update_tray_widgets_action(self) -> None:
        act = getattr(self, "_tray_widgets_action", None)
        if act is not None:
            act.setText("Ocultar widgets" if not WidgetManager.instance().hidden_all else "Mostrar widgets")

    def _on_net_snapshot(self, snap) -> None:
        # Páginas com on_net_snapshot recebem sempre (mantêm seus próprios buffers);
        # cada uma decide se redesenha conforme estiver visível.
        for i in range(self.stack.count()):
            page = self._page(i)
            if hasattr(page, "on_net_snapshot"):
                try:
                    page.on_net_snapshot(snap)
                except Exception:
                    log.exception("Erro ao atualizar rede em %s", type(page).__name__)

    # ---------------------------------------------------------- atalhos/cenários
    def on_hotkey(self, action: str) -> None:
        from ..media import audio
        from ..personalization import scenes
        try:
            if action == "open_app":
                self.restore()
            elif action == "toggle_widgets":
                wm = WidgetManager.instance()
                wm.set_all_visible(wm.hidden_all)
            elif action.startswith("scene:"):
                errors = scenes.activate(action[6:])
                sc = scenes.get(action[6:]) or {}
                if errors:
                    msg = "Alguns itens falharam: " + "; ".join(errors)
                else:
                    back = _hotkey_for("scene_off")
                    msg = f"Para voltar: {back}" if back else "Para voltar: bandeja → Cenários → Voltar ao normal"
                self._toast(f"Cenário “{sc.get('name', '')}” ativado", msg)
            elif action == "scene_off":
                if scenes.active():
                    scenes.deactivate()
                    self._toast("Cenário desativado", "Configurações anteriores restauradas.")
            elif action == "mute":
                _v, m = audio.master_volume()
                audio.set_master_mute(not m)
            elif action in ("vol_up", "vol_down"):
                audio.change_master_volume(0.05 if action == "vol_up" else -0.05)
            elif action.startswith("media_"):
                from ..widgets.media import MediaService
                MediaService.instance().ensure_started()
                MediaService.instance().command({"media_play": "play_pause", "media_next": "next",
                                                 "media_prev": "previous"}[action])
            elif action == "livewall":
                from ..personalization.livewall import LiveWallpaper
                lw = LiveWallpaper.instance()
                lw.stop() if lw.running else lw.start()
                self.settings.set("livewall.enabled", lw.running)
            elif action == "fps":
                from ..media.fps import FpsMonitor
                fps = FpsMonitor.instance()
                fps.stop() if fps.running() else fps.start()
            elif action == "obs_record":
                from ..media.obs import ObsClient
                ObsClient.instance().toggle_record()
            elif action == "warm":
                from ..personalization.display import WarmFilter
                wf = WarmFilter.instance()
                wf.set_level(0 if wf.level else int(self.settings.get("display.warm_level", 50)))
        except Exception as e:     # noqa: BLE001 — atalho nunca derruba o app
            log.warning("Atalho %s falhou: %s", action, e)
            self._toast("Atalho", str(e))
        page = self._page(10)
        if self.stack.currentIndex() == 10 and hasattr(page, "on_shown"):
            page.on_shown()

    def _toast(self, title: str, msg: str) -> None:
        if self.tray is not None:
            self.tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 3000)

    def _fill_scenes_menu(self) -> None:
        from ..personalization import scenes
        m = self._scenes_menu
        m.clear()
        act = scenes.active().get("id")
        for sc in scenes.scenes():
            a = m.addAction(("✓ " if sc["id"] == act else "") + sc["name"])
            a.triggered.connect(lambda _=False, sid=sc["id"]: self.on_hotkey(f"scene:{sid}"))
        m.addSeparator()
        off = m.addAction("Voltar ao normal")
        off.setEnabled(bool(act))
        off.triggered.connect(lambda: self.on_hotkey("scene_off"))

    def shutdown_pages(self) -> None:
        # Fase 9: nada pode ficar "preso" na tela ou no sistema ao sair
        for stop in (_stop_livewall, _stop_warm, _stop_hotkeys, _stop_obs, _stop_fps, _stop_visualizer):
            try:
                stop()
            except Exception:
                log.exception("Erro ao encerrar %s", stop.__name__)
        WidgetManager.instance().shutdown()
        AlertEngine.instance().shutdown()   # grava o uso por app acumulado
        for i in range(self.stack.count()):
            page = self._page(i)
            if hasattr(page, "shutdown"):
                page.shutdown()

    # ------------------------------------------------------------- navegação
    def _page(self, index: int) -> Page:
        page = self.stack.widget(index)
        assert isinstance(page, Page), f"página {index} não existe"
        return page

    def show_page(self, index: int) -> None:
        if index == self.stack.currentIndex():
            return
        page = self._page(index)
        self.stack.setCurrentIndex(index)
        self.sidebar.buttons[index].setChecked(True)
        snap = MonitorService.instance().latest
        if snap is not None:
            page.on_snapshot(snap)
        page.on_shown()
        if self.settings.get("appearance.animations", True):
            eff = QGraphicsOpacityEffect(page)
            page.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", page)
            anim.setDuration(200)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            # Remove o efeito no fim: efeitos gráficos deixam a pintura mais lenta.
            anim.finished.connect(lambda: page.setGraphicsEffect(None))  # type: ignore[arg-type]  # None tira o efeito
            anim.start()

    # ---------------------------------------------------------------- dados
    def _on_snapshot(self, snap: Snapshot) -> None:
        History.instance().add(snap)
        if self.tray is not None:
            gpu = snap.primary_gpu
            net = NetworkService.instance().latest
            net_line = ""
            if net is not None:
                name = net.wifi.ssid if net.wifi.connected and net.wifi.ssid else (
                    net.active.name if net.active else "sem rede")
                ping = net.ping_internet.last_ms
                net_line = f"\n{name}" + (f" · ping {ping:.0f} ms" if ping is not None else "")
            # A dica da bandeja aceita no máximo ~127 caracteres.
            self.tray.setToolTip(
                (f"PC Control Center\nCPU {fmt_pct(snap.cpu.percent)} · RAM {fmt_pct(snap.memory.percent)}"
                 f"{f' · GPU {fmt_pct(gpu.percent)}' if gpu else ''}\nTemp. CPU {fmt_temp(snap.temps.cpu)}"
                 f"{net_line}")[:127])
        if self.isVisible() and not self.isMinimized():
            page = self._page(self.stack.currentIndex())
            try:
                page.on_snapshot(snap)
            except Exception:
                log.exception("Erro ao atualizar página %s", type(page).__name__)

    # ----------------------------------------------------------- aparência
    def _on_theme(self, t) -> None:
        apply_window_effects(int(self.winId()), t.dark)
        WidgetManager.instance().refresh_style()
        icon = make_app_icon(t.accent, t.accent2)
        self.setWindowIcon(icon)
        if self.tray is not None:
            self.tray.setIcon(icon)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        apply_window_effects(int(self.winId()), ThemeManager.instance().theme.dark)

    # --------------------------------------------------------------- bandeja
    def _setup_tray(self) -> None:
        self.tray = None
        self._tray_hint_shown = False
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        for text, idx in (("Abrir painel", 0), ("Desempenho", 1), ("Ferramentas", 7), ("Configurações", 8)):
            act = QAction(text, menu)
            act.triggered.connect(lambda _=False, i=idx: (self.restore(), self.show_page(i)))
            menu.addAction(act)
        menu.addSeparator()
        self._scenes_menu = menu.addMenu("Cenários")
        self._scenes_menu.aboutToShow.connect(self._fill_scenes_menu)
        self._fill_scenes_menu()
        wact = QAction("Ocultar widgets", menu)
        wact.triggered.connect(lambda: WidgetManager.instance().set_all_visible(WidgetManager.instance().hidden_all))
        menu.addAction(wact)
        self._tray_widgets_action = wact
        menu.addSeparator()
        quit_act = QAction("Sair", menu)
        quit_act.triggered.connect(self.quit_app)
        menu.addAction(quit_act)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.restore()

    def restore(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        snap = MonitorService.instance().latest
        if snap is not None:
            self._page(self.stack.currentIndex()).on_snapshot(snap)

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if (e.type() == e.Type.WindowStateChange and self.isMinimized() and self.tray is not None
                and self.settings.get("general.minimize_to_tray", True)):
            QTimer.singleShot(0, self.hide)

    def closeEvent(self, e) -> None:
        app = qapp()
        if (self.tray is not None and self.settings.get("general.close_to_tray", True)
                and not app.property("force_quit")):
            e.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage("PC Control Center",
                                      "Continuo monitorando na bandeja. Clique com o botão direito para sair.",
                                      QSystemTrayIcon.MessageIcon.Information, 4000)
            return
        self._save_geometry()
        self.shutdown_pages()
        e.accept()
        app.quit()

    def _save_geometry(self) -> None:
        if not self.isMaximized():
            self.settings.set("window.width", self.width(), save=False)
            self.settings.set("window.height", self.height(), save=False)
            self.settings.save()

    def quit_app(self) -> None:
        self._save_geometry()
        self.shutdown_pages()
        app = qapp()
        app.setProperty("force_quit", True)
        if self.tray is not None:
            self.tray.hide()
        app.quit()
