"""Uso acumulado de CPU e memória por aplicativo (base dos relatórios "quem mais pesou").

A cada nova leitura de processos (2 s) soma, por aplicativo: CPU% × tempo e memória × tempo.
Grava no SQLite a cada 5 minutos (uma linha por dia e aplicativo).
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date

from ..monitoring.models import ProcessEntry, Snapshot
from . import store

FLUSH_SECONDS = 300
IGNORE = {"system", "registry", "memory compression", "secure system", "idle"}


class UsageTracker:
    def __init__(self) -> None:
        self._acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        self._last_list: list[ProcessEntry] | None = None
        self._last_t: float | None = None
        self._last_flush = time.time()

    def on_snapshot(self, snap: Snapshot, now: float | None = None) -> None:
        apps = snap.processes.apps
        if not apps or apps is self._last_list:
            return   # a lista de processos só muda a cada 2 s
        now = now or time.time()
        if self._last_t is not None:
            dt = min(now - self._last_t, 10.0)   # ignora lacunas (PC em suspensão)
            for a in apps:
                name = a.name.lower().removesuffix(".exe")
                if name in IGNORE:
                    continue
                acc = self._acc[a.name.removesuffix(".exe")]
                acc[0] += a.cpu / 100.0 * dt
                acc[1] += a.memory * dt
                acc[2] += dt
        self._last_list, self._last_t = apps, now
        if now - self._last_flush >= FLUSH_SECONDS:
            self.flush(now)

    def flush(self, now: float | None = None) -> None:
        if self._acc:
            store.add_app_usage(date.today().isoformat(), {k: (v[0], v[1], v[2]) for k, v in self._acc.items()})
            self._acc.clear()
        self._last_flush = now or time.time()
