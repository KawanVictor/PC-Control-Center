"""Cenários: um clique aplica várias configurações de uma vez ("Jogo", "Trabalho", "Live", "Noite"...).

Cada cenário é uma lista de ações opcionais (só as preenchidas são aplicadas):

    power            modo de energia: efficiency | balanced | performance
    windows_mode     dark | light  (Windows e o próprio app)
    accent           cor de destaque do Windows (#RRGGBB)
    wallpaper        imagem do papel de parede
    livewall         on | off  (papel de parede animado)
    widgets_profile  perfil de widgets
    widgets_visible  true | false
    audio_device     saída de som (id)
    volume           0–100
    mute             true | false
    brightness       0–100 (todas as telas)
    warm             0–100 (luz quente; 0 desliga)
    silence_alerts   true = alertas do PC Control Center viram só registro (críticos continuam)
    obs_scene        cena do OBS (se conectado)
    fps_counter      true = liga o contador de FPS (pede o UAC)
    launch           [programas/sites para abrir]

Antes de aplicar, o estado atual de cada item é guardado. "Voltar ao normal" restaura o
estado de ANTES do primeiro cenário (trocar de um cenário para outro não perde o original).
"""
from __future__ import annotations

import copy
import os
import time
import uuid

from ..core.config import Settings
from ..core.logger import get_logger, log_operation

log = get_logger("scenes")

ACTION_LABELS = {
    "power": "Modo de energia", "windows_mode": "Tema do Windows", "accent": "Cor de destaque",
    "wallpaper": "Papel de parede", "livewall": "Papel de parede animado", "widgets_profile": "Perfil de widgets",
    "widgets_visible": "Widgets na tela", "audio_device": "Saída de som", "volume": "Volume", "mute": "Som mudo",
    "brightness": "Brilho", "warm": "Luz quente", "silence_alerts": "Silenciar alertas",
    "obs_scene": "Cena do OBS", "fps_counter": "Contador de FPS", "launch": "Abrir programas",
}

DEFAULT_SCENES = [
    {"id": "game", "name": "Jogo", "glyph": "", "color": "#f43f5e",
     "description": "Desempenho máximo, sem distrações.",
     "actions": {"power": "performance", "widgets_visible": False, "silence_alerts": True, "livewall": "off"}},
    {"id": "work", "name": "Trabalho", "glyph": "", "color": "#38bdf8",
     "description": "Equilibrado, widgets à vista e tema claro.",
     "actions": {"power": "balanced", "widgets_visible": True, "windows_mode": "light", "silence_alerts": False}},
    {"id": "live", "name": "Live", "glyph": "", "color": "#a855f7",
     "description": "Para transmitir: desempenho e alertas silenciosos.",
     "actions": {"power": "performance", "silence_alerts": True, "widgets_visible": False}},
    {"id": "night", "name": "Noite", "glyph": "", "color": "#f59e0b",
     "description": "Tema escuro, tela mais fraca e luz quente.",
     "actions": {"windows_mode": "dark", "brightness": 40, "warm": 55, "volume": 30}},
]


def scenes() -> list[dict]:
    lst = Settings.instance().get("scenes.list")
    if not isinstance(lst, list) or not lst:
        return copy.deepcopy(DEFAULT_SCENES)
    return lst


def save_scenes(lst: list[dict]) -> None:
    Settings.instance().set("scenes.list", lst)


def get(scene_id: str) -> dict | None:
    return next((s for s in scenes() if s.get("id") == scene_id), None)


def new_scene(name: str) -> dict:
    return {"id": uuid.uuid4().hex[:8], "name": name or "Novo cenário", "glyph": "", "color": "#22d3ee",
            "description": "", "actions": {}}


def upsert(scene: dict) -> None:
    lst = scenes()
    for i, s in enumerate(lst):
        if s.get("id") == scene["id"]:
            lst[i] = scene
            break
    else:
        lst.append(scene)
    save_scenes(lst)


def remove(scene_id: str) -> None:
    save_scenes([s for s in scenes() if s.get("id") != scene_id])


def active() -> dict:
    return Settings.instance().get("scenes.active") or {}


# ----------------------------------------------------------- estado/aplicação
def _capture(key: str):
    """Valor atual de um item (para poder voltar)."""
    if key == "power":
        from . import power
        return power.current_overlay()
    if key == "windows_mode":
        from .autotheme import windows_light
        apps, system = windows_light()
        return {"apps": apps, "system": system, "app": Settings.instance().get("appearance.mode")}
    if key == "accent":
        from . import accent
        return accent.current()["color"]
    if key == "wallpaper":
        from . import wallpaper
        return wallpaper.current_path()
    if key == "livewall":
        from .livewall import LiveWallpaper
        return "on" if LiveWallpaper.instance().running else "off"
    if key == "widgets_profile":
        from ..widgets.manager import WidgetManager
        return WidgetManager.instance().active
    if key == "widgets_visible":
        from ..widgets.manager import WidgetManager
        return not WidgetManager.instance().hidden_all
    if key in ("audio_device", "volume", "mute"):
        from ..media import audio
        st = audio.state()
        return {"audio_device": st["device"], "volume": round(st["volume"] * 100),
                "mute": st["muted"]}[key]
    if key == "brightness":
        from . import display
        return display.state()
    if key == "warm":
        from .display import WarmFilter
        return WarmFilter.instance().level
    if key == "silence_alerts":
        return bool(Settings.instance().get("notifications.silenced_by_scene"))
    if key == "obs_scene":
        from ..media.obs import ObsClient
        c = ObsClient.instance()
        return c.status.scene if c.status.state == "connected" else None
    if key == "fps_counter":
        from ..media.fps import FpsMonitor
        return FpsMonitor.instance().running()
    return None


def _apply(key: str, value, scene_name: str, restoring: bool = False) -> None:
    if key == "power":
        from . import power
        power.set_overlay(value)
    elif key == "windows_mode":
        from .autotheme import apply
        if isinstance(value, dict):          # restaurando o estado salvo
            import winreg
            from ..core import regbackup
            from . import changes
            from .tweaks import PERSONALIZE
            g = regbackup.new_group()
            regbackup.set_value(winreg.HKEY_CURRENT_USER, PERSONALIZE, "AppsUseLightTheme", winreg.REG_DWORD,
                                int(value["apps"]), "scene:restaurar", g)
            regbackup.set_value(winreg.HKEY_CURRENT_USER, PERSONALIZE, "SystemUsesLightTheme", winreg.REG_DWORD,
                                int(value["system"]), "scene:restaurar", g)
            changes.broadcast("ImmersiveColorSet")
            if value.get("app"):
                Settings.instance().set("appearance.mode", value["app"])
        else:
            apply(value == "light", {"apps": True, "system": True, "app_theme": True}, f"scene:{scene_name}")
    elif key == "accent":
        from . import accent
        accent.set_accent(value)
    elif key == "wallpaper":
        if value and os.path.isfile(value):
            from .dynwall import set_image
            set_image(value)
    elif key == "livewall":
        from .livewall import LiveWallpaper
        lw = LiveWallpaper.instance()
        if value == "on" and not lw.running:
            lw.start()
        elif value == "off" and lw.running:
            lw.stop()
    elif key == "widgets_profile":
        from ..widgets.manager import WidgetManager
        wm = WidgetManager.instance()
        if value in wm.profile_names() and value != wm.active:
            wm.switch_profile(value)
    elif key == "widgets_visible":
        from ..widgets.manager import WidgetManager
        WidgetManager.instance().set_all_visible(bool(value))
    elif key == "audio_device":
        from ..media import audio
        if value and value != audio.default_output_id():
            audio.set_default_output(value)
    elif key == "volume":
        from ..media import audio
        audio.set_master_volume(int(value) / 100)
    elif key == "mute":
        from ..media import audio
        audio.set_master_mute(bool(value))
    elif key == "brightness":
        from . import display
        if isinstance(value, dict):
            display.restore(value)
        else:
            errors = display.set_all_brightness(int(value))
            if errors and len(errors) == len(display.displays()):
                raise OSError("; ".join(errors))
    elif key == "warm":
        from .display import WarmFilter
        WarmFilter.instance().set_level(int(value))
    elif key == "silence_alerts":
        Settings.instance().set("notifications.silenced_by_scene", scene_name if value else "")
    elif key == "obs_scene":
        from ..media.obs import ObsClient
        c = ObsClient.instance()
        if value and c.status.state == "connected" and value in c.status.scenes:
            c.set_scene(value)
    elif key == "fps_counter":
        from ..media.fps import FpsMonitor, presentmon_path
        m = FpsMonitor.instance()
        if value and not m.running() and presentmon_path().exists():
            m.start()
        elif not value and m.running():
            m.stop()
    elif key == "launch" and not restoring:
        from ..core.winapi import shell_open
        for target in value or []:
            if isinstance(target, str) and target.strip():
                shell_open(target.strip())


def activate(scene_id: str) -> list[str]:
    """Aplica o cenário. Retorna a lista de itens que falharam (vazia = tudo certo)."""
    sc = get(scene_id)
    if sc is None:
        raise KeyError(scene_id)
    s = Settings.instance()
    cur = active()
    restore = dict(cur.get("restore") or {})
    errors = []
    for key, value in (sc.get("actions") or {}).items():
        if value is None or value == "" or key not in ACTION_LABELS:
            continue
        if key != "launch" and key not in restore:
            try:
                restore[key] = _capture(key)
            except Exception as e:     # noqa: BLE001
                log.debug("captura %s: %s", key, e)
        try:
            _apply(key, value, sc["name"])
        except Exception as e:     # noqa: BLE001 — um item com problema não impede os outros
            errors.append(f"{ACTION_LABELS[key]}: {e}")
    s.set("scenes.active", {"id": scene_id, "name": sc["name"], "since": time.time(), "restore": restore})
    log_operation("scene.activate", sc["name"], "ok" if not errors else "; ".join(errors))
    return errors


def deactivate() -> list[str]:
    """Volta ao estado de antes do(s) cenário(s)."""
    cur = active()
    if not cur:
        return []
    errors = []
    for key, value in (cur.get("restore") or {}).items():
        if value is None:
            continue
        try:
            _apply(key, value, "", restoring=True)
        except Exception as e:     # noqa: BLE001
            errors.append(f"{ACTION_LABELS.get(key, key)}: {e}")
    Settings.instance().set("scenes.active", {})
    Settings.instance().set("notifications.silenced_by_scene", "")
    log_operation("scene.deactivate", cur.get("name", ""), "ok" if not errors else "; ".join(errors))
    return errors


def describe(scene: dict) -> list[str]:
    """Texto curto de cada ação (para os cartões)."""
    from .power import OVERLAYS
    out = []
    for k, v in (scene.get("actions") or {}).items():
        if v is None or v == "" or k not in ACTION_LABELS:
            continue
        if k == "power":
            v = OVERLAYS.get(v, ("", v))[1]
        elif k == "windows_mode":
            v = "escuro" if v == "dark" else "claro"
        elif isinstance(v, bool):
            v = "sim" if v else "não"
        elif k in ("volume", "brightness", "warm"):
            v = f"{v}%"
        elif k == "livewall":
            v = "ligado" if v == "on" else "desligado"
        elif k in ("wallpaper",):
            v = os.path.basename(str(v))
        elif k == "audio_device":
            v = "definida"
        elif k == "launch":
            v = f"{len(v)} item(ns)"
        out.append(f"{ACTION_LABELS[k]}: {v}")
    return out
