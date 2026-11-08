"""Integração com o OBS Studio pelo obs-websocket v5 (embutido no OBS 28 ou mais recente).

No OBS: Ferramentas → Configurações do servidor WebSocket → Ativar. A conexão é local
(127.0.0.1:4455 por padrão) e a senha fica guardada com DPAPI (core.secrets).

Mostra: ao vivo/gravando, tempo, cena atual, bitrate, quadros perdidos e uso de CPU do OBS.
Comandos: iniciar/parar transmissão e gravação, trocar de cena. Iniciar/parar transmissão
sempre pede confirmação na interface.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import psutil
from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from ..core.config import Settings
from ..core.logger import get_logger, log_operation
from ..core.secrets import unprotect

log = get_logger("obs")

EVENTS = 1 | 4 | 64          # General, Scenes, Outputs
OBS_PROCESSES = {"obs64.exe", "obs32.exe", "obs.exe"}


def auth_string(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def obs_running() -> bool:
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() in OBS_PROCESSES:
            return True
    return False


@dataclass
class ObsStatus:
    state: str = "disconnected"   # disconnected | connecting | connected | error
    error: str = ""
    version: str = ""
    scene: str = ""
    scenes: list[str] = field(default_factory=list)
    streaming: bool = False
    stream_time: str = ""
    recording: bool = False
    record_paused: bool = False
    record_time: str = ""
    bitrate_kbps: float = 0.0
    dropped_pct: float = 0.0
    congestion: float = 0.0
    obs_cpu: float = 0.0
    fps: float = 0.0


class ObsClient(QObject):
    status_changed = Signal(object)    # ObsStatus
    _instance: "ObsClient | None" = None

    def __init__(self) -> None:
        super().__init__()
        from PySide6.QtWebSockets import QWebSocket
        self.ws = QWebSocket()
        self.ws.connected.connect(lambda: log.info("OBS: conectado, aguardando Hello"))
        self.ws.disconnected.connect(self._on_disconnected)
        self.ws.textMessageReceived.connect(self._on_message)
        self.ws.errorOccurred.connect(self._on_error)
        self.status = ObsStatus()
        self._pending: dict[str, Callable[[dict, bool, str], None]] = {}
        self._password = ""
        self._last_bytes: tuple[float, int] | None = None
        self._manual_disconnect = False
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._refresh)
        self._retry = QTimer(self)
        self._retry.timeout.connect(self._auto_connect)
        self._retry.start(10_000)

    @classmethod
    def instance(cls) -> "ObsClient":
        if cls._instance is None:
            cls._instance = ObsClient()
        return cls._instance

    # ------------------------------------------------------------- conexão
    def connect_obs(self, host: str | None = None, port: int | None = None, password: str | None = None) -> None:
        s = Settings.instance()
        host = host or s.get("media.obs.host", "127.0.0.1")
        port = int(port or s.get("media.obs.port", 4455))
        self._password = password if password is not None else unprotect(s.get("media.obs.password", ""))
        self._manual_disconnect = False
        self.ws.abort()
        self._set(state="connecting", error="")
        self.ws.open(QUrl(f"ws://{host}:{port}"))

    def disconnect_obs(self) -> None:
        self._manual_disconnect = True
        self.ws.close()
        self._poll.stop()
        self._set(state="disconnected", error="")

    def _auto_connect(self) -> None:
        s = Settings.instance()
        if (self.status.state in ("disconnected", "error") and not self._manual_disconnect
                and s.get("media.obs.autoconnect", True) and s.get("media.obs.enabled", False) and obs_running()):
            self.connect_obs()

    def _on_disconnected(self) -> None:
        self._poll.stop()
        if self.status.state != "error":
            self._set(state="disconnected", streaming=False, recording=False)

    def _on_error(self, _err) -> None:
        msg = self.ws.errorString()
        if "refused" in msg.lower() or "recusad" in msg.lower():
            msg = "OBS fechado ou servidor WebSocket desligado (OBS → Ferramentas → Configurações do servidor WebSocket)."
        self._set(state="error", error=msg)

    # ------------------------------------------------------------ protocolo
    def _send(self, op: int, d: dict) -> None:
        self.ws.sendTextMessage(json.dumps({"op": op, "d": d}))

    def request(self, rtype: str, data: dict | None = None, callback=None) -> None:
        if self.status.state != "connected":
            return
        rid = uuid.uuid4().hex[:12]
        if callback is not None:
            self._pending[rid] = callback
        self._send(6, {"requestType": rtype, "requestId": rid, "requestData": data or {}})

    def _on_message(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except ValueError:
            return
        op, d = msg.get("op"), msg.get("d") or {}
        if op == 0:                                   # Hello
            ident: dict[str, object] = {"rpcVersion": 1, "eventSubscriptions": EVENTS}
            auth = d.get("authentication")
            if auth:
                if not self._password:
                    self._set(state="error", error="O OBS pede senha. Digite a senha do servidor WebSocket.")
                    self.ws.close()
                    return
                ident["authentication"] = auth_string(self._password, auth["salt"], auth["challenge"])
            self.status.version = d.get("obsWebSocketVersion", "")
            self._send(1, ident)
        elif op == 2:                                 # Identified
            self._set(state="connected", error="")
            log_operation("obs.connect", self.ws.requestUrl().toString())
            self._last_bytes = None
            self.request("GetSceneList", callback=self._on_scenes)
            self._refresh()
            self._poll.start(2000)
        elif op == 5:                                 # evento
            self._on_event(d.get("eventType", ""), d.get("eventData") or {})
        elif op == 7:                                 # resposta
            cb = self._pending.pop(d.get("requestId", ""), None)
            st = d.get("requestStatus") or {}
            if cb is not None:
                cb(d.get("responseData") or {}, bool(st.get("result")), st.get("comment", ""))

    def _on_event(self, etype: str, data: dict) -> None:
        if etype == "CurrentProgramSceneChanged":
            self._set(scene=data.get("sceneName", ""))
        elif etype in ("SceneListChanged", "SceneNameChanged", "SceneCreated", "SceneRemoved"):
            self.request("GetSceneList", callback=self._on_scenes)
        elif etype == "StreamStateChanged":
            self._set(streaming=bool(data.get("outputActive")))
        elif etype == "RecordStateChanged":
            self._set(recording=bool(data.get("outputActive")))
        elif etype == "ExitStarted":
            self.ws.close()

    # ---------------------------------------------------------------- status
    def _refresh(self) -> None:
        self.request("GetStreamStatus", callback=self._on_stream)
        self.request("GetRecordStatus", callback=self._on_record)
        self.request("GetStats", callback=self._on_stats)

    def _on_scenes(self, data: dict, ok: bool, _c: str) -> None:
        if ok:
            # o OBS devolve a lista de baixo para cima
            names = [s.get("sceneName", "") for s in reversed(data.get("scenes") or [])]
            self._set(scenes=names, scene=data.get("currentProgramSceneName", self.status.scene))

    def _on_stream(self, data: dict, ok: bool, _c: str) -> None:
        if not ok:
            return
        active = bool(data.get("outputActive"))
        kbps = self.status.bitrate_kbps if active else 0.0
        now, total = time.monotonic(), int(data.get("outputBytes") or 0)
        if not active:
            self._last_bytes = None
        elif self._last_bytes is None or total < self._last_bytes[1]:
            self._last_bytes = (now, total)
        elif now - self._last_bytes[0] >= 1.0:
            # mede só com ≥ 1 s entre leituras (pedidos extras após um comando não distorcem)
            kbps = (total - self._last_bytes[1]) * 8 / 1000 / (now - self._last_bytes[0])
            self._last_bytes = (now, total)
        tot = int(data.get("outputTotalFrames") or 0)
        skip = int(data.get("outputSkippedFrames") or 0)
        self._set(streaming=active, stream_time=(data.get("outputTimecode") or "")[:8],
                  bitrate_kbps=kbps, dropped_pct=(skip / tot * 100) if tot else 0.0,
                  congestion=float(data.get("outputCongestion") or 0.0))

    def _on_record(self, data: dict, ok: bool, _c: str) -> None:
        if ok:
            self._set(recording=bool(data.get("outputActive")), record_paused=bool(data.get("outputPaused")),
                      record_time=(data.get("outputTimecode") or "")[:8])

    def _on_stats(self, data: dict, ok: bool, _c: str) -> None:
        if ok:
            self._set(obs_cpu=float(data.get("cpuUsage") or 0.0), fps=float(data.get("activeFps") or 0.0))

    def _set(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self.status, k, v)
        self.status_changed.emit(self.status)

    # -------------------------------------------------------------- comandos
    def _command(self, rtype: str, data: dict | None = None, label: str = "") -> None:
        def done(_d, ok, comment):
            log_operation(f"obs.{rtype}", label, "ok" if ok else f"erro: {comment}")
            if not ok:
                self._set(error=comment or f"O OBS recusou: {rtype}")
            self._refresh()
        self.request(rtype, data, done)

    def set_scene(self, name: str) -> None:
        self._command("SetCurrentProgramScene", {"sceneName": name}, name)

    def toggle_stream(self) -> None:
        self._command("StopStream" if self.status.streaming else "StartStream")

    def toggle_record(self) -> None:
        self._command("StopRecord" if self.status.recording else "StartRecord")

    def shutdown(self) -> None:
        self._retry.stop()
        self._poll.stop()
        self.ws.abort()
