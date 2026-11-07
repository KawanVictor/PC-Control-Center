"""Histórico recente em memória (últimos N pontos) usado pelos gráficos em tempo real."""
from __future__ import annotations

from collections import deque

from ..core.config import Settings
from ..monitoring.models import Snapshot


class History:
    _instance: "History | None" = None

    def __init__(self) -> None:
        self.size = int(Settings.instance().get("monitoring.history_points", 120))
        self.series: dict[str, deque] = {}
        self.cores: list[deque] = []

    @classmethod
    def instance(cls) -> "History":
        if cls._instance is None:
            cls._instance = History()
        return cls._instance

    def _push(self, key: str, value) -> None:
        d = self.series.get(key)
        if d is None:  # sem preenchimento inicial: o gráfico mostra só leituras reais
            d = self.series[key] = deque(maxlen=self.size)
        d.append(float(value) if value is not None else float("nan"))

    def get(self, key: str) -> list[float]:
        return list(self.series.get(key, []))

    def add(self, s: Snapshot) -> None:
        self._push("cpu", s.cpu.percent)
        self._push("ram", s.memory.percent)
        self._push("ram_used", s.memory.used)
        self._push("commit", s.memory.commit_used)
        self._push("freq", s.cpu.freq_mhz)
        g = s.primary_gpu
        self._push("gpu", g.percent if g else 0)
        self._push("vram", g.dedicated_used if g else 0)
        for i, gpu in enumerate(s.gpus):
            self._push(f"gpu{i}", gpu.percent)
            self._push(f"gpu{i}_vram", gpu.dedicated_used)
        self._push("disk_read", s.disk_io.read_bps)
        self._push("disk_write", s.disk_io.write_bps)
        self._push("disk_active", s.disk_io.active_percent)
        self._push("net_down", s.net_io.down_bps)
        self._push("net_up", s.net_io.up_bps)
        self._push("cpu_temp", s.temps.cpu)
        self._push("gpu_temp", s.temps.gpu)

        if len(self.cores) != len(s.cpu.per_core):
            self.cores = [deque(maxlen=self.size) for _ in s.cpu.per_core]
        for d, v in zip(self.cores, s.cpu.per_core):
            d.append(v)
