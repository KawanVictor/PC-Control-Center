"""Tela: brilho e filtro de luz quente.

Brilho:
* Tela do notebook — WMI ``WmiMonitorBrightnessMethods`` (o mesmo controle do Windows).
* Monitores externos — DDC/CI (``SetMonitorBrightness``), quando o monitor aceita. Muitos
  monitores têm o DDC/CI desligado no menu deles; nesse caso o app informa.

Luz quente: efeito de cor em tela inteira da API oficial de Lupa do Windows
(``MagSetFullscreenColorEffect``). Ele reduz o azul (e um pouco do verde), como a Luz
noturna. É do próprio processo: se o app fechar, a tela volta ao normal sozinha — nada
fica gravado no sistema.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from ..core.com import ensure_com
from ..core.logger import get_logger, log_operation

log = get_logger("display")


@dataclass
class Display:
    id: str            # "wmi:<instância>" ou "ddc:<índice>"
    name: str
    brightness: int
    kind: str          # "Tela integrada" | "Monitor externo"


# ------------------------------------------------------------------- brilho
def _wmi():
    ensure_com()
    import wmi
    return wmi.WMI(namespace="wmi")


class _PHYS(ctypes.Structure):
    _fields_ = [("h", wintypes.HANDLE), ("desc", wintypes.WCHAR * 128)]


def _physical_monitors():
    """[(handle, descrição)] — o chamador deve destruir com _destroy."""
    user32, dx = ctypes.windll.user32, ctypes.WinDLL("dxva2")
    mons = []
    cb_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                 wintypes.LPARAM)
    def found(h, _dc, _r, _l):
        mons.append(h)
        return True

    cb = cb_type(found)
    user32.EnumDisplayMonitors(None, None, cb, 0)
    out = []
    for hm in mons:
        n = wintypes.DWORD()
        if not dx.GetNumberOfPhysicalMonitorsFromHMONITOR(hm, ctypes.byref(n)) or not n.value:
            continue
        arr = (_PHYS * n.value)()
        if dx.GetPhysicalMonitorsFromHMONITOR(hm, n.value, arr):
            out.append(arr)
    return out


def _destroy(arrays) -> None:
    dx = ctypes.WinDLL("dxva2")
    for arr in arrays:
        dx.DestroyPhysicalMonitors(len(arr), arr)


def displays() -> list[Display]:
    out: list[Display] = []
    try:
        for m in _wmi().WmiMonitorBrightness():
            out.append(Display(f"wmi:{m.InstanceName}", "Tela do notebook", int(m.CurrentBrightness), "Tela integrada"))
    except Exception as e:     # noqa: BLE001 — PCs de mesa não têm este controle
        log.debug("Brilho WMI indisponível: %s", e)
    dx = ctypes.WinDLL("dxva2")
    arrays = _physical_monitors()
    try:
        idx = 0
        for arr in arrays:
            for p in arr:
                mn, cur, mx = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
                if dx.GetMonitorBrightness(p.h, ctypes.byref(mn), ctypes.byref(cur), ctypes.byref(mx)) and mx.value:
                    pct = round((cur.value - mn.value) * 100 / max(1, mx.value - mn.value))
                    name = p.desc if p.desc and "Generic" not in p.desc else f"Monitor externo {idx + 1}"
                    out.append(Display(f"ddc:{idx}", name, pct, "Monitor externo"))
                idx += 1
    finally:
        _destroy(arrays)
    return out


def set_brightness(display_id: str, percent: int) -> None:
    percent = max(0, min(100, int(percent)))
    if display_id.startswith("wmi:"):
        inst = display_id[4:]
        for m in _wmi().WmiMonitorBrightnessMethods():
            if m.InstanceName == inst:
                m.WmiSetBrightness(percent, 0)
                return
        raise ValueError("Tela não encontrada")
    if display_id.startswith("ddc:"):
        want = int(display_id[4:])
        dx = ctypes.WinDLL("dxva2")
        arrays = _physical_monitors()
        try:
            idx = 0
            for arr in arrays:
                for p in arr:
                    if idx == want:
                        mn, cur, mx = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
                        dx.GetMonitorBrightness(p.h, ctypes.byref(mn), ctypes.byref(cur), ctypes.byref(mx))
                        value = mn.value + round((mx.value - mn.value) * percent / 100)
                        if not dx.SetMonitorBrightness(p.h, value):
                            raise OSError("O monitor recusou o comando (ative o DDC/CI no menu do monitor).")
                        return
                    idx += 1
        finally:
            _destroy(arrays)
        raise ValueError("Monitor não encontrado")
    raise ValueError("Tela inválida")


def state() -> dict:
    return {d.id: d.brightness for d in displays()}


def restore(st: dict) -> None:
    for did, pct in (st or {}).items():
        try:
            set_brightness(did, pct)
        except Exception as e:     # noqa: BLE001
            log.info("Brilho de %s não restaurado: %s", did, e)


def set_all_brightness(percent: int) -> list[str]:
    """Aplica em todas as telas. Retorna os erros (telas que recusaram)."""
    errors = []
    for d in displays():
        try:
            set_brightness(d.id, percent)
        except Exception as e:     # noqa: BLE001
            errors.append(f"{d.name}: {e}")
    log_operation("display.brightness", f"{percent}%", "ok" if not errors else "; ".join(errors))
    return errors


# --------------------------------------------------------------- luz quente
class WarmFilter:
    """Filtro de luz quente (0 = desligado, 100 = máximo). Use ``WarmFilter.instance()``."""
    _instance: "WarmFilter | None" = None

    def __init__(self) -> None:
        self.level = 0
        self._mag: ctypes.WinDLL | None = None

    @classmethod
    def instance(cls) -> "WarmFilter":
        if cls._instance is None:
            cls._instance = WarmFilter()
        return cls._instance

    @staticmethod
    def matrix(level: int) -> list[float]:
        """Matriz 5x5 (linhas = canais de entrada). Nível 100 ≈ 3400 K."""
        t = max(0, min(100, level)) / 100
        r, g, b = 1.0, 1.0 - 0.22 * t, 1.0 - 0.58 * t
        m = [0.0] * 25
        m[0], m[6], m[12], m[18], m[24] = r, g, b, 1.0, 1.0
        return m

    def set_level(self, level: int) -> None:
        level = max(0, min(100, int(level)))
        if self._mag is None:
            self._mag = ctypes.WinDLL("Magnification")
            if not self._mag.MagInitialize():
                self._mag = None
                raise OSError("O Windows não permitiu o efeito de cor (Lupa).")
        arr = (ctypes.c_float * 25)(*self.matrix(level))
        if not self._mag.MagSetFullscreenColorEffect(ctypes.byref(arr)):
            raise OSError("O Windows recusou o efeito de cor.")
        if level != self.level:
            log_operation("display.warm", f"{level}%")
        self.level = level
        if level == 0:
            self.shutdown()

    def shutdown(self) -> None:
        """Volta as cores ao normal e libera a API."""
        if self._mag is not None:
            ident = (ctypes.c_float * 25)(*self.matrix(0))
            self._mag.MagSetFullscreenColorEffect(ctypes.byref(ident))
            self._mag.MagUninitialize()
            self._mag = None
        self.level = 0
