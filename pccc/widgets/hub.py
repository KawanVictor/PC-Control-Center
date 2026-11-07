"""Central de dados dos widgets.

Os widgets não consultam o sistema: leem daqui na hora de desenhar. A central reaproveita
os serviços que já existem (coletor de sistema e monitor de rede), guarda um histórico
curto para os mini gráficos e busca clima/bateria/mídia apenas quando algum widget precisa.
"""
from __future__ import annotations

import time
from collections import deque

import psutil
from PySide6.QtCore import QObject, QTimer

from ..core.logger import get_logger
from ..monitoring.collector import MonitorService
from ..monitoring.models import Snapshot
from ..network.models import NetworkSnapshot
from ..network.monitor import NetworkService
from . import weather
from .media import MediaService

log = get_logger("widgets.hub")
HIST = 60
WEATHER_TTL = 15 * 60


class DataHub(QObject):
    _instance: "DataHub | None" = None

    def __init__(self) -> None:
        super().__init__()
        self.sys: Snapshot | None = MonitorService.instance().latest
        self.net: NetworkSnapshot | None = NetworkService.instance().latest
        self.hist: dict[str, deque] = {k: deque(maxlen=HIST) for k in
                                       ("cpu", "ram", "gpu", "down", "up", "cpu_temp", "gpu_temp")}
        self.battery = None
        self._weather: dict[tuple, dict] = {}
        self._weather_pending: set[tuple] = set()
        self._weather_error: dict[tuple, str] = {}
        MonitorService.instance().snapshot.connect(self._on_sys)
        NetworkService.instance().snapshot.connect(self._on_net)
        self._bat_timer = QTimer(self)
        self._bat_timer.timeout.connect(self._read_battery)
        self._bat_timer.start(30_000)
        self._read_battery()

    @classmethod
    def instance(cls) -> "DataHub":
        if cls._instance is None:
            cls._instance = DataHub()
        return cls._instance

    # ----------------------------------------------------------------- sistema
    def _on_sys(self, s: Snapshot) -> None:
        self.sys = s
        g = s.primary_gpu
        self.hist["cpu"].append(s.cpu.percent)
        self.hist["ram"].append(s.memory.percent)
        self.hist["gpu"].append(g.percent if g else 0.0)
        self.hist["cpu_temp"].append(s.temps.cpu if s.temps.cpu is not None else float("nan"))
        self.hist["gpu_temp"].append(s.temps.gpu if s.temps.gpu is not None else float("nan"))

    def _on_net(self, n: NetworkSnapshot) -> None:
        self.net = n
        self.hist["down"].append(n.down_bps)
        self.hist["up"].append(n.up_bps)

    def _read_battery(self) -> None:
        try:
            self.battery = psutil.sensors_battery()
        except Exception:
            self.battery = None

    # ------------------------------------------------------------------- mídia
    @property
    def media(self):
        svc = MediaService.instance()
        svc.ensure_started()
        return svc.snapshot()

    # -------------------------------------------------------------------- clima
    def weather(self, lat: float, lon: float) -> tuple[dict | None, str]:
        """Previsão em cache; dispara atualização em segundo plano se estiver velha."""
        key = (round(lat, 3), round(lon, 3))
        data = self._weather.get(key)
        stale = data is None or time.time() - data.get("fetched_at", 0) > WEATHER_TTL
        err_msg, err_ts = self._weather_error.get(key, ("", 0.0))
        backoff = time.time() - err_ts < 120   # sem internet: tenta de novo a cada 2 min
        if stale and key not in self._weather_pending and not backoff:
            self._weather_pending.add(key)
            from ..ui.tasks import run_task

            def ok(d, key=key):
                self._weather[key] = d
                self._weather_error.pop(key, None)
                self._weather_pending.discard(key)

            def err(msg, key=key):
                self._weather_error[key] = (msg, time.time())
                self._weather_pending.discard(key)

            run_task(weather.forecast, lat, lon, on_done=ok, on_error=err)
        return data, err_msg
