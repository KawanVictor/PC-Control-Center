"""Gerenciador de widgets: perfis, layouts, persistência e janelas.

Arquivo: %APPDATA%\\PCControlCenter\\widgets.json
    {"version": 1, "active": "Padrão", "profiles": {"Padrão": [ {config}, ... ], ...}}

Cada perfil é um layout completo (quais widgets, onde, com quais cores). Trocar de perfil
fecha as janelas atuais e abre as do outro perfil.
"""
from __future__ import annotations

import copy
import ctypes
import json
import os
import tempfile

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from ..core.config import Settings
from ..core.logger import get_logger, log_operation
from ..core.paths import data_dir
from .base import WidgetConfig
from .types import REGISTRY
from .window import DesktopWidgetWindow

log = get_logger("widgets")
DEFAULT_PROFILE = "Padrão"

# Layout sugerido (coluna à direita da tela principal)
SUGGESTED = ["clock", "calendar", "cpu", "ram", "netspeed", "media"]


def _file():
    return data_dir() / "widgets.json"


class WidgetManager(QObject):
    changed = Signal()          # lista de widgets/perfis mudou (atualiza a página)
    configure_requested = Signal(object)   # DesktopWidgetWindow
    open_app_requested = Signal()
    _instance: "WidgetManager | None" = None

    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.instance()
        self.profiles: dict[str, list[dict]] = {DEFAULT_PROFILE: []}
        self.active = DEFAULT_PROFILE
        self.windows: dict[str, DesktopWidgetWindow] = {}
        self.hidden_all = False
        self._started = False
        self._load()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_now)
        self._fg_timer = QTimer(self)
        self._fg_timer.timeout.connect(self._watch_desktop)
        self._last_fg_desktop = False

    @classmethod
    def instance(cls) -> "WidgetManager":
        if cls._instance is None:
            cls._instance = WidgetManager()
        return cls._instance

    # ------------------------------------------------------------- persistência
    def _load(self) -> None:
        try:
            with open(_file(), encoding="utf-8") as f:
                data = json.load(f)
            profiles = data.get("profiles") or {}
            if isinstance(profiles, dict) and profiles:
                self.profiles = {str(k): [w for w in v if w.get("type") in REGISTRY] for k, v in profiles.items()}
            self.active = data.get("active", DEFAULT_PROFILE)
            if self.active not in self.profiles:
                self.active = next(iter(self.profiles))
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("widgets.json inválido (%s) — começando vazio; o arquivo antigo foi preservado", e)
            try:
                os.replace(_file(), _file().with_suffix(".json.bak"))
            except OSError:
                pass

    def save(self) -> None:
        self._save_timer.start(400)   # agrupa várias mudanças seguidas (ex.: arrastar)

    def _save_now(self) -> None:
        if not self._started:
            return  # janelas ainda não abertas: gravar agora apagaria o perfil salvo
        self.profiles[self.active] = [w.cfg.to_dict() for w in self.windows.values()]
        data = {"version": 1, "active": self.active, "profiles": self.profiles}
        try:
            fd, tmp = tempfile.mkstemp(dir=data_dir(), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, ensure_ascii=False)
            os.replace(tmp, _file())
        except OSError as e:
            log.error("Falha ao salvar widgets: %s", e)

    # ---------------------------------------------------------------- janelas
    def start(self) -> None:
        """Abre as janelas do perfil ativo (chamado na inicialização do app)."""
        self._open_profile()
        self._started = True
        self.hidden_all = not self.settings.get("widgets.show_on_startup", True)
        for w in self.windows.values():
            if w.cfg.visible and not self.hidden_all:
                w.show()
        self._fg_timer.start(700)
        self.changed.emit()

    def _open_profile(self) -> None:
        for w in list(self.windows.values()):
            w.close()
            w.deleteLater()
        self.windows.clear()
        for d in self.profiles.get(self.active, []):
            try:
                self._create(WidgetConfig.from_dict(d), show=False)
            except Exception:
                log.exception("Widget inválido ignorado: %s", d)

    def _create(self, cfg: WidgetConfig, show: bool = True) -> DesktopWidgetWindow:
        renderer = REGISTRY[cfg.type](cfg)
        self._ensure_on_screen(cfg, renderer.base_size)
        win = DesktopWidgetWindow(renderer, peers=lambda: list(self.windows.values()))
        win.changed.connect(lambda _c: self.save())
        win.action.connect(self._on_action)
        self.windows[cfg.id] = win
        if show and cfg.visible and not self.hidden_all:
            win.show()
        return win

    @staticmethod
    def _ensure_on_screen(cfg: WidgetConfig, base) -> None:
        """Se o monitor onde o widget estava foi desconectado, traz para a tela principal."""
        pt = QPoint(cfg.x + 20, cfg.y + 20)
        if not any(s.availableGeometry().contains(pt) for s in QGuiApplication.screens()):
            area = QGuiApplication.primaryScreen().availableGeometry()
            cfg.x = area.right() - (cfg.width or base[0]) - 24
            cfg.y = area.top() + 24

    def _free_position(self, size: tuple[int, int]) -> tuple[int, int]:
        """Próxima posição livre numa coluna à direita da tela principal."""
        area = QGuiApplication.primaryScreen().availableGeometry()
        w, h = size
        x = area.right() - w - 24
        y = area.top() + 24
        taken = [win.geometry() for win in self.windows.values() if win.isVisible() or win.cfg.visible]
        for _ in range(60):
            rect = (x, y, w, h)
            hit = next((g for g in taken if not (x + w <= g.left() or x >= g.right() or y + h <= g.top()
                                                 or y >= g.bottom())), None)
            if hit is None:
                return x, y
            y = hit.bottom() + 12
            if y + h > area.bottom():
                y = area.top() + 24
                x -= w + 12
        return rect[0], rect[1]

    def add(self, type_id: str, show: bool = True) -> DesktopWidgetWindow:
        cls = REGISTRY[type_id]
        cfg = WidgetConfig(type=type_id, refresh_ms=cls.default_refresh)
        probe = cls(cfg)
        bw, bh = probe.base_size
        cfg.x, cfg.y = self._free_position((int(bw), int(bh)))
        if self.hidden_all:
            self.hidden_all = False
            self.set_all_visible(True)
        win = self._create(cfg, show=show)
        log_operation("widgets.add", f"{cls.title} no perfil {self.active}")
        self.save()
        self.changed.emit()
        return win

    def remove(self, wid: str) -> None:
        win = self.windows.pop(wid, None)
        if win:
            log_operation("widgets.remove", f"{win.renderer.title} do perfil {self.active}")
            win.close()
            win.deleteLater()
            self.save()
            self.changed.emit()

    def set_visible(self, wid: str, visible: bool) -> None:
        win = self.windows.get(wid)
        if not win:
            return
        win.cfg.visible = visible
        if visible and not self.hidden_all:
            win.show()
            win.sink()
        else:
            win.hide()
        self.save()
        self.changed.emit()

    def set_all_visible(self, visible: bool) -> None:
        """Mostrar/ocultar todos (não altera a visibilidade individual salva)."""
        self.hidden_all = not visible
        for w in self.windows.values():
            if visible and w.cfg.visible:
                w.show()
                w.sink()
            else:
                w.hide()
        self.changed.emit()

    def lock_all(self, locked: bool) -> None:
        for w in self.windows.values():
            w.cfg.locked = locked
            w.update()
        self.save()
        self.changed.emit()

    def arrange(self) -> None:
        """Reorganiza todos os visíveis em colunas à direita da tela principal."""
        area = QGuiApplication.primaryScreen().availableGeometry()
        x_right = area.right() - 24
        x, y, col_w = x_right, area.top() + 24, 0
        for w in self.windows.values():
            if not w.cfg.visible:
                continue
            if y + w.height() > area.bottom() - 12:
                x -= col_w + 12
                y, col_w = area.top() + 24, 0
            col_w = max(col_w, w.width())
            w.cfg.x, w.cfg.y = x - w.width(), y
            w.move(w.cfg.x, w.cfg.y)
            y += w.height() + 12
        self.save()

    def apply_suggested(self) -> None:
        for t in SUGGESTED:
            self.add(t)
        self.arrange()

    def refresh_style(self) -> None:
        """Reaplica cores do tema (widgets com 'cor do tema')."""
        for w in self.windows.values():
            w.restyle()

    def _on_action(self, action: str, win: DesktopWidgetWindow) -> None:
        if action == "configure":
            self.configure_requested.emit(win)
        elif action == "hide":
            self.set_visible(win.cfg.id, False)
        elif action == "remove":
            self.remove(win.cfg.id)
        elif action == "open_app":
            self.open_app_requested.emit()

    # ----------------------------------------------------------------- perfis
    def profile_names(self) -> list[str]:
        return list(self.profiles)

    def switch_profile(self, name: str) -> None:
        if name not in self.profiles or name == self.active:
            return
        self._save_now()
        self.active = name
        self._open_profile()
        for w in self.windows.values():
            if w.cfg.visible and not self.hidden_all:
                w.show()
        self._save_now()
        log_operation("widgets.profile", f"perfil ativo: {name}")
        self.changed.emit()

    def create_profile(self, name: str, copy_current: bool) -> None:
        name = name.strip()
        if not name or name in self.profiles:
            raise ValueError("Nome vazio ou já existente.")
        self._save_now()
        items = copy.deepcopy(self.profiles[self.active]) if copy_current else []
        for it in items:
            it.pop("id", None)   # ids novos
            it["id"] = WidgetConfig(type=it["type"]).id
        self.profiles[name] = items
        self.switch_profile(name)

    def rename_profile(self, old: str, new: str) -> None:
        new = new.strip()
        if not new or new in self.profiles:
            raise ValueError("Nome vazio ou já existente.")
        self._save_now()
        self.profiles = {(new if k == old else k): v for k, v in self.profiles.items()}
        if self.active == old:
            self.active = new
        self._save_now()
        self.changed.emit()

    def delete_profile(self, name: str) -> None:
        if len(self.profiles) <= 1:
            raise ValueError("É preciso manter pelo menos um perfil.")
        if name == self.active:
            other = next(k for k in self.profiles if k != name)
            self.switch_profile(other)
        self.profiles.pop(name, None)
        self._save_now()
        self.changed.emit()

    # ------------------------------------------------- área de trabalho em foco
    def _watch_desktop(self) -> None:
        """Quando a área de trabalho fica em primeiro plano (ex.: Win+D ou clique no fundo),
        traz os widgets da camada 'atrás' para cima; quando outro app volta, devolve-os ao fundo."""
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, buf, 64)
            is_desktop = buf.value in ("Progman", "WorkerW")
        except Exception:
            return
        if is_desktop == self._last_fg_desktop:
            return
        self._last_fg_desktop = is_desktop
        for w in self.windows.values():
            if w.cfg.layer != "bottom" or not w.isVisible():
                continue
            if is_desktop:
                w.surface()
            else:
                w.sink()

    def shutdown(self) -> None:
        self._fg_timer.stop()
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._save_now()
        for w in self.windows.values():
            w.close()
        from .media import MediaService
        MediaService.instance().stop()
