"""Áudio do Windows: dispositivo de saída, volume geral e volume por aplicativo.

Usa as mesmas APIs do Mixer de Volume do Windows (Core Audio / WASAPI, via pycaw):
* ``IMMDeviceEnumerator``     — lista as saídas e qual é a padrão
* ``IPolicyConfig``           — troca a saída padrão (o mesmo que o ícone de som da bandeja faz)
* ``IAudioEndpointVolume``    — volume geral e mudo
* ``ISimpleAudioVolume``      — volume/mudo de cada aplicativo (sessão de áudio)
* ``IAudioMeterInformation``  — nível do som de cada aplicativo (para as barrinhas)

Nada é gravado no Registro: o próprio Windows guarda essas preferências. As chamadas COM
devem ser feitas na thread da interface (STA) — todas são rápidas (< 50 ms).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..core.logger import get_logger, log_operation

log = get_logger("audio")

SYSTEM_SOUNDS = "Sons do sistema"


@dataclass
class OutputDevice:
    id: str
    name: str
    default: bool = False


@dataclass
class AppAudio:
    key: str                       # nome do executável em minúsculas (agrupa várias sessões)
    name: str                      # nome amigável
    exe: str = ""
    pids: list[int] = field(default_factory=list)
    volume: float = 1.0            # 0–1
    muted: bool = False
    peak: float = 0.0              # 0–1 (nível atual do som)
    active: bool = False           # tocando agora


def _au():
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities


# ----------------------------------------------------------------- dispositivos
def output_devices() -> list[OutputDevice]:
    """Saídas de som ativas (alto-falantes, fones, monitor HDMI...)."""
    from pycaw.constants import DEVICE_STATE, EDataFlow
    au = _au()
    try:
        default_id = au.GetSpeakers().id
    except Exception:
        default_id = ""
    out = []
    for d in au.GetAllDevices(EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value):
        out.append(OutputDevice(id=d.id, name=d.FriendlyName or "Dispositivo de áudio", default=d.id == default_id))
    out.sort(key=lambda d: (not d.default, d.name.lower()))
    return out


def default_output_id() -> str:
    try:
        return _au().GetSpeakers().id
    except Exception:
        return ""


def set_default_output(device_id: str) -> None:
    """Troca a saída padrão para todos os usos (jogos/música, comunicação e sons do sistema)."""
    from pycaw.constants import ERole
    devices = {d.id: d.name for d in output_devices()}
    if device_id not in devices:
        raise ValueError("Dispositivo de áudio não encontrado ou desconectado.")
    _au().SetDefaultDevice(device_id, [ERole.eConsole, ERole.eMultimedia, ERole.eCommunications])
    log_operation("audio.output", devices[device_id])


# ----------------------------------------------------------------- volume geral
def _endpoint():
    return _au().GetSpeakers().EndpointVolume


def master_volume() -> tuple[float, bool]:
    """(volume 0–1, mudo) da saída padrão."""
    ep = _endpoint()
    return float(ep.GetMasterVolumeLevelScalar()), bool(ep.GetMute())


def set_master_volume(volume: float) -> None:
    _endpoint().SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(volume))), None)


def set_master_mute(muted: bool) -> None:
    _endpoint().SetMute(1 if muted else 0, None)


def change_master_volume(delta: float) -> float:
    vol, _ = master_volume()
    new = max(0.0, min(1.0, vol + delta))
    set_master_volume(new)
    return new


# ------------------------------------------------------------- volume por app
_names: dict[str, str] = {}


def _friendly(exe_path: str, exe_name: str) -> str:
    key = exe_path or exe_name
    if key not in _names:
        name = ""
        if exe_path:
            from ..core.fileinfo import version_info
            info = version_info(exe_path)
            name = info.get("product") or info.get("description") or ""
            # "Microsoft Edge", "Spotify"... nomes de produto muito longos ficam com a descrição
            if len(name) > 28 and info.get("description"):
                name = info["description"]
        _names[key] = name or os.path.splitext(exe_name)[0].capitalize()
    return _names[key]


def _sessions():
    """Sessões de áudio da saída padrão: [(chave, nome, exe, pid, sessão_pycaw)]."""
    out = []
    for s in _au().GetAllSessions():
        try:
            pid = s.ProcessId
            if not pid:
                out.append(("#system", SYSTEM_SOUNDS, "", 0, s))
                continue
            proc = s.Process
            if proc is None:
                continue
            exe_name = proc.name()
            try:
                exe = proc.exe()
            except Exception:
                exe = ""
            out.append((exe_name.lower(), _friendly(exe, exe_name), exe, pid, s))
        except Exception:     # processo terminou durante a leitura
            continue
    return out


def _peak(session) -> float:
    try:
        from pycaw.pycaw import IAudioMeterInformation
        return float(session._ctl.QueryInterface(IAudioMeterInformation).GetPeakValue())
    except Exception:
        return 0.0


def app_sessions() -> list[AppAudio]:
    """Aplicativos com áudio agora, agrupados por programa (ex.: as várias abas do navegador)."""
    apps: dict[str, AppAudio] = {}
    for key, name, exe, pid, s in _sessions():
        vol = s.SimpleAudioVolume
        try:
            level, muted = float(vol.GetMasterVolume()), bool(vol.GetMute())
        except Exception:
            continue
        a = apps.get(key)
        if a is None:
            a = apps[key] = AppAudio(key=key, name=name, exe=exe, volume=level, muted=muted)
        a.pids.append(pid)
        a.peak = max(a.peak, _peak(s))
        a.active = a.active or s.State == 1      # AudioSessionStateActive
    order = sorted(apps.values(), key=lambda a: (a.key == "#system", not a.active, a.name.lower()))
    return order


def set_app_volume(key: str, volume: float) -> int:
    """Ajusta o volume de todas as sessões do programa. Retorna quantas foram ajustadas."""
    volume = max(0.0, min(1.0, float(volume)))
    n = 0
    for k, _name, _exe, _pid, s in _sessions():
        if k == key:
            s.SimpleAudioVolume.SetMasterVolume(volume, None)
            n += 1
    return n


def set_app_mute(key: str, muted: bool) -> int:
    n = 0
    for k, _name, _exe, _pid, s in _sessions():
        if k == key:
            s.SimpleAudioVolume.SetMute(1 if muted else 0, None)
            n += 1
    return n


_cache: dict = {"ts": 0.0, "master": (0.0, False), "apps": [], "error": ""}


def cached(max_age: float = 1.0) -> dict:
    """Volume geral e apps (lido no máximo 1x por segundo — usado pelos widgets)."""
    import time
    if time.monotonic() - _cache["ts"] > max_age:
        try:
            _cache.update(master=master_volume(), apps=app_sessions(), error="")
        except Exception as e:     # noqa: BLE001 — sem dispositivo de áudio
            _cache.update(error=str(e) or "Sem dispositivo de áudio")
        _cache["ts"] = time.monotonic()
    return _cache


def state() -> dict:
    """Estado atual (para os cenários poderem voltar ao que era antes)."""
    vol, muted = master_volume()
    return {"device": default_output_id(), "volume": round(vol, 3), "muted": muted}


def restore(st: dict) -> None:
    if st.get("device") and st["device"] != default_output_id():
        try:
            set_default_output(st["device"])
        except ValueError:
            log.info("Saída de áudio anterior não está mais conectada")
    if "volume" in st:
        set_master_volume(st["volume"])
    if "muted" in st:
        set_master_mute(bool(st["muted"]))
