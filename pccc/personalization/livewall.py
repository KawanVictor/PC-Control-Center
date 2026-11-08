"""Papel de parede animado (vídeo ou GIF atrás dos ícones da área de trabalho).

Como funciona: o Explorer desenha o papel de parede numa janela "WorkerW". Enviando a
mensagem 0x052C ao "Progman", o Windows separa essa camada; colocamos uma janela de vídeo
dentro dela — fica atrás dos ícones e de todas as janelas. É a mesma técnica de apps como
Lively Wallpaper e Wallpaper Engine. Nada é gravado no sistema: ao desligar (ou fechar o app)
a janela some e o papel de parede normal volta.

Economia: pausa sozinho durante jogos/vídeos em tela cheia, quando uma janela maximizada
cobre a área de trabalho e (opcional) na bateria. O vídeo toca sem som.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

import psutil
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..core.config import Settings
from ..core.logger import get_logger, log_operation

log = get_logger("livewall")

VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".wmv", ".m4v")
GIF_EXT = (".gif",)
user32 = ctypes.windll.user32
GWL_STYLE, WS_CHILD, WS_POPUP, WS_VISIBLE = -16, 0x40000000, 0x80000000, 0x10000000


_GetWindowLongPtr = user32.GetWindowLongPtrW
_GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
_GetWindowLongPtr.restype = ctypes.c_ssize_t
_SetWindowLongPtr = user32.SetWindowLongPtrW
_SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_SetWindowLongPtr.restype = ctypes.c_ssize_t


def _get_style(hwnd: int) -> int:
    return _GetWindowLongPtr(hwnd, GWL_STYLE) & 0xFFFFFFFF


def _set_style(hwnd: int, style: int) -> None:
    style &= 0xFFFFFFFF
    _SetWindowLongPtr(hwnd, GWL_STYLE, style - (1 << 32) if style & 0x80000000 else style)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def monitors() -> list[tuple[int, int, int, int, bool]]:
    """[(x, y, largura, altura, principal)] em pixels físicos."""
    out = []
    cb_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                 wintypes.LPARAM)

    def cb(hm, _dc, _r, _l):
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        user32.GetMonitorInfoW(hm, ctypes.byref(mi))
        r = mi.rcMonitor
        out.append((r.left, r.top, r.right - r.left, r.bottom - r.top, bool(mi.dwFlags & 1)))
        return True

    user32.EnumDisplayMonitors(None, None, cb_type(cb), 0)
    out.sort(key=lambda m: not m[4])
    return out


def wallpaper_host() -> int:
    """Janela WorkerW onde o papel de parede é desenhado (atrás dos ícones)."""
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return 0
    res = ctypes.c_size_t()
    user32.SendMessageTimeoutW(progman, 0x052C, 0xD, 0x1, 0, 1000, ctypes.byref(res))
    # Windows 11 24H2 ou mais novo: o WorkerW é filho do Progman, atrás dos ícones.
    w = user32.FindWindowExW(progman, None, "WorkerW", None)
    if w:
        return w
    # Versões anteriores: o WorkerW é a janela logo após a que contém os ícones (SHELLDLL_DefView).
    found = []
    cb_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _l):
        if user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
            ww = user32.FindWindowExW(None, hwnd, "WorkerW", None)
            if ww:
                found.append(ww)
        return True

    user32.EnumWindows(cb_type(cb), 0)
    return found[0] if found else 0


def _covered(rect) -> bool:
    """Uma janela maximizada (ou do tamanho da tela) cobre este monitor?"""
    fg = user32.GetForegroundWindow()
    if not fg or not user32.IsWindowVisible(fg):
        return False
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(fg, cls, 64)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
        return False
    r = wintypes.RECT()
    user32.GetWindowRect(fg, ctypes.byref(r))
    x, y, w, h, _p = rect
    overlap_w = max(0, min(r.right, x + w) - max(r.left, x))
    overlap_h = max(0, min(r.bottom, y + h) - max(r.top, y))
    return bool(user32.IsZoomed(fg)) and overlap_w * overlap_h > w * h * 0.6


class _Surface(QWidget):
    """Janela de um monitor: vídeo (QVideoWidget) ou GIF (QMovie)."""

    def __init__(self, path: str, rect, host: int) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("background: black;")
        self.rect_ = rect
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.player = None
        self.movie = None
        if path.lower().endswith(GIF_EXT):
            from PySide6.QtCore import QSize
            from PySide6.QtGui import QMovie
            self.label = QLabel()
            self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.movie = QMovie(path)
            self.movie.jumpToFrame(0)
            fs = self.movie.currentImage().size()
            if fs.width() and fs.height():
                s = max(rect[2] / fs.width(), rect[3] / fs.height())
                self.movie.setScaledSize(QSize(int(fs.width() * s), int(fs.height() * s)))
            self.label.setMovie(self.movie)
            lay.addWidget(self.label)
        else:
            from PySide6.QtMultimedia import QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget
            self.video = QVideoWidget()
            self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatioByExpanding)
            lay.addWidget(self.video)
            self.player = QMediaPlayer(self)
            self.player.setVideoOutput(self.video)        # sem saída de áudio = sem som
            self.player.setLoops(QMediaPlayer.Loops.Infinite)
            self.player.setSource(QUrl.fromLocalFile(path))
        hwnd = int(self.winId())
        style = _get_style(hwnd)
        _set_style(hwnd, (style & ~WS_POPUP) | WS_CHILD)
        user32.SetParent(hwnd, host)
        hr = wintypes.RECT()
        user32.GetWindowRect(host, ctypes.byref(hr))
        x, y, w, h, _p = rect
        self.show()
        user32.MoveWindow(hwnd, x - hr.left, y - hr.top, w, h, True)
        user32.ShowWindow(hwnd, 4)          # SW_SHOWNOACTIVATE: o Qt não exibe janelas "adotadas"

    def is_visible_native(self) -> bool:
        return bool(user32.IsWindowVisible(int(self.winId())))

    def play(self) -> None:
        if self.player is not None:
            self.player.play()
        if self.movie is not None:
            self.movie.setPaused(False) if self.movie.state() == self.movie.MovieState.Paused else self.movie.start()

    def pause(self) -> None:
        if self.player is not None:
            self.player.pause()
        if self.movie is not None:
            self.movie.setPaused(True)

    def dispose(self) -> None:
        if self.player is not None:
            self.player.stop()
        if self.movie is not None:
            self.movie.stop()
        user32.SetParent(int(self.winId()), 0)
        self.hide()
        self.deleteLater()


class LiveWallpaper(QObject):
    state_changed = Signal(str)       # "playing" | "paused: motivo" | "stopped" | "error: ..."
    _instance: "LiveWallpaper | None" = None

    def __init__(self) -> None:
        super().__init__()
        self.surfaces: list[_Surface] = []
        self.path = ""
        self.paused_reason = ""
        self._watch = QTimer(self)
        self._watch.timeout.connect(self._check_pause)

    @classmethod
    def instance(cls) -> "LiveWallpaper":
        if cls._instance is None:
            cls._instance = LiveWallpaper()
        return cls._instance

    @property
    def running(self) -> bool:
        return bool(self.surfaces)

    def start(self, path: str | None = None) -> None:
        s = Settings.instance()
        path = path or s.get("livewall.path", "")
        if not path or not os.path.isfile(path):
            raise FileNotFoundError("Escolha um vídeo ou GIF.")
        if not path.lower().endswith(VIDEO_EXT + GIF_EXT):
            raise ValueError("Formato não suportado. Use MP4, WEBM, MKV, MOV, AVI, WMV ou GIF.")
        self.stop(refresh=False)
        host = wallpaper_host()
        if not host:
            raise OSError("Não foi possível encontrar a camada do papel de parede do Windows.")
        mons = monitors()
        if not s.get("livewall.all_screens", True):
            mons = mons[:1]
        self.surfaces = [_Surface(path, m, host) for m in mons]
        self.path = path
        s.set("livewall.path", path)
        self.paused_reason = ""
        for sf in self.surfaces:
            sf.play()
        self._watch.start(1500)
        log_operation("livewall.start", os.path.basename(path))
        self.state_changed.emit("playing")

    def stop(self, refresh: bool = True) -> None:
        self._watch.stop()
        was = bool(self.surfaces)
        for sf in self.surfaces:
            sf.dispose()
        self.surfaces = []
        if was:
            log_operation("livewall.stop")
            if refresh:
                # redesenha o papel de parede normal (senão o último quadro pode ficar na tela)
                from .wallpaper import _spi_set_wallpaper, current_path
                cur = current_path()
                if cur:
                    _spi_set_wallpaper(cur)
            self.state_changed.emit("stopped")

    def _pause_reason(self) -> str:
        s = Settings.instance()
        from ..automation.notifier import windows_focus_state
        if windows_focus_state() in (2, 3, 4):     # tela cheia, jogo Direct3D, apresentação
            return "tela cheia"
        if s.get("livewall.pause_on_battery", True):
            try:
                b = psutil.sensors_battery()
                if b is not None and not b.power_plugged:
                    return "na bateria"
            except Exception:
                pass
        if s.get("livewall.pause_when_covered", True) and self.surfaces and \
                all(_covered(sf.rect_) for sf in self.surfaces):
            return "janela maximizada"
        return ""

    def _check_pause(self) -> None:
        reason = self._pause_reason()
        if reason == self.paused_reason:
            return
        self.paused_reason = reason
        for sf in self.surfaces:
            sf.pause() if reason else sf.play()
        self.state_changed.emit(f"paused: {reason}" if reason else "playing")
