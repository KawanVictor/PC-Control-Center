"""Coletor central executado em uma thread própria.

A interface nunca chama psutil/WMI diretamente — ela apenas recebe ``Snapshot``s por
sinal Qt. Isso mantém a janela fluida mesmo quando uma consulta WMI demora.

Cadências (configuráveis em settings.json > monitoring):
* rápida   (refresh_ms, 1 s):  CPU, RAM, GPU, E/S de disco e rede, temperatura
* processos (process_refresh_ms, 2 s)
* lenta    (slow_refresh_ms, 5 s): partições, discos físicos, temperaturas externas
* banco    (db_sample_seconds, 60 s): média gravada no SQLite
"""
from __future__ import annotations

import gc
import time

import pythoncom
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from ..core.config import Settings
from ..core.database import Database
from ..core.logger import get_logger
from .cpu import CpuMonitor
from .gpu import GpuMonitor
from .memory import sample_memory
from .models import Snapshot
from .pdh import PdhQuery
from .processes import ProcessMonitor
from .storage import DiskIoMonitor, NetIoMonitor, sample_partitions, sample_physical_disks
from .system import uptime_seconds
from .temperature import THERMAL_PDH, TemperatureMonitor

log = get_logger("collector")

_BASE_PDH = {
    "cpu_perf": r"\Processor Information(_Total)\% Processor Performance",
    "cpu_freq": r"\Processor Information(_Total)\Processor Frequency",
    "commit_used": r"\Memory\Committed Bytes",
    "commit_limit": r"\Memory\Commit Limit",
    "cache": r"\Memory\Cache Bytes",
    "disk_idle": r"\PhysicalDisk(_Total)\% Idle Time",
}


class _Accumulator:
    """Acumula leituras para gravar médias no banco."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.sums: dict[str, float] = {}
        self.counts: dict[str, int] = {}

    def add(self, key: str, value) -> None:
        if value is None:
            return
        self.sums[key] = self.sums.get(key, 0.0) + float(value)
        self.counts[key] = self.counts.get(key, 0) + 1

    def averages(self) -> dict:
        return {k: self.sums[k] / self.counts[k] for k in self.sums}


class MonitorWorker(QObject):
    snapshot = Signal(object)   # Snapshot
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._settings = Settings.instance()
        self._snap = Snapshot()
        self._acc = _Accumulator()
        self._ready = False

    @Slot()
    def start(self) -> None:
        """Executado já dentro da thread do coletor."""
        pythoncom.CoInitialize()  # WMI exige COM inicializado por thread
        try:
            self._pdh = PdhQuery({**_BASE_PDH, **GpuMonitor.PDH_COUNTERS, **THERMAL_PDH})
            self._cpu = CpuMonitor()
            self._gpu = GpuMonitor()
            self._disk_io = DiskIoMonitor()
            self._net_io = NetIoMonitor()
            self._procs = ProcessMonitor()
            self._temps: TemperatureMonitor | None
            try:
                self._temps = TemperatureMonitor()
            except Exception as e:
                log.warning("Monitor de temperatura indisponível: %s", e)
                self._temps = None
            self._db = Database.instance()
        except Exception as e:
            log.exception("Falha ao iniciar monitores")
            self.error.emit(str(e))
            return

        s = self._settings
        self._fast = QTimer(self)
        self._fast.timeout.connect(self._tick_fast)
        self._fast.start(int(s.get("monitoring.refresh_ms", 1000)))

        self._proc_timer = QTimer(self)
        self._proc_timer.timeout.connect(self._tick_processes)
        self._proc_timer.start(int(s.get("monitoring.process_refresh_ms", 2000)))

        self._slow = QTimer(self)
        self._slow.timeout.connect(self._tick_slow)
        self._slow.start(int(s.get("monitoring.slow_refresh_ms", 5000)))

        self._db_timer = QTimer(self)
        self._db_timer.timeout.connect(self._flush_db)
        self._db_timer.start(int(s.get("monitoring.db_sample_seconds", 60)) * 1000)

        self._tick_slow()
        self._tick_processes()
        self._db.prune(int(s.get("monitoring.db_retention_days", 30)))
        self._ready = True
        log.info("Coletor iniciado")

    @Slot(int)
    def set_interval(self, ms: int) -> None:
        if self._ready:
            self._fast.setInterval(max(250, ms))

    # ------------------------------------------------------------------ ticks
    def _tick_fast(self) -> None:
        try:
            pdh = self._pdh.collect()
            snap = self._snap
            snap.ts = time.time()
            snap.uptime_s = uptime_seconds()
            snap.cpu = self._cpu.sample(pdh.get("cpu_perf"), pdh.get("cpu_freq"))
            snap.memory = sample_memory(pdh)
            snap.gpus = self._gpu.sample(pdh)
            snap.disk_io = self._disk_io.sample(pdh.get("disk_idle"))
            snap.net_io = self._net_io.sample()
            if self._temps is not None:
                snap.temps = self._temps.sample(pdh)
                gpu = snap.primary_gpu
                if gpu is not None:
                    if gpu.temperature is None:
                        gpu.temperature = snap.temps.gpu
                    else:
                        snap.temps.gpu = gpu.temperature

            gpu = snap.primary_gpu
            acc = self._acc
            acc.add("cpu", snap.cpu.percent)
            acc.add("ram", snap.memory.percent)
            acc.add("gpu", gpu.percent if gpu else None)
            acc.add("cpu_temp", snap.temps.cpu)
            acc.add("gpu_temp", snap.temps.gpu)
            acc.add("net_down", snap.net_io.down_bps)
            acc.add("net_up", snap.net_io.up_bps)
            acc.add("disk_read", snap.disk_io.read_bps)
            acc.add("disk_write", snap.disk_io.write_bps)

            # Envia uma cópia rasa: a UI não deve ver o objeto mudando no meio da pintura.
            self.snapshot.emit(Snapshot(**snap.__dict__))
        except Exception:
            log.exception("Erro na coleta rápida")

    def _tick_processes(self) -> None:
        try:
            self._snap.processes = self._procs.sample()
        except Exception:
            log.exception("Erro na coleta de processos")

    def _tick_slow(self) -> None:
        try:
            self._snap.partitions = sample_partitions()
            # Discos físicos quase nunca mudam e a consulta WMI custa ~150 ms: a cada 60 s.
            now = time.time()
            if now - getattr(self, "_phys_t", 0) > 60:
                self._phys_t = now
                self._snap.physical_disks = sample_physical_disks()
            self._gpu.refresh_nvidia()
            if self._temps is not None:
                self._temps.refresh_disks()
                temps = self._snap.temps.disks
                for d in self._snap.physical_disks:
                    d.temperature = temps.get(d.name)
        except Exception:
            log.exception("Erro na coleta lenta")
        # Libera aqui (thread que criou os objetos WMI) os objetos COM presos em ciclos,
        # em vez de deixar o coletor de lixo fazer isso em outra thread (ver core/com.py).
        gc.collect()

    def _flush_db(self) -> None:
        avg = self._acc.averages()
        self._acc.reset()
        if avg:
            self._db.insert_metrics(int(time.time()), avg)

    @Slot()
    def stop(self) -> None:
        if self._ready:
            for t in (self._fast, self._proc_timer, self._slow, self._db_timer):
                t.stop()
            self._flush_db()
            self._pdh.close()
        pythoncom.CoUninitialize()


class MonitorService(QObject):
    """Dono da thread do coletor. Use ``MonitorService.instance().snapshot.connect(...)``."""

    snapshot = Signal(object)
    _instance: "MonitorService | None" = None
    _stop_requested = Signal()
    _interval_changed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.latest: Snapshot | None = None
        self._thread = QThread()
        self._thread.setObjectName("MonitorThread")
        self._worker = MonitorWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self._worker.snapshot.connect(self._on_snapshot)
        self._stop_requested.connect(self._worker.stop)
        self._interval_changed.connect(self._worker.set_interval)

    @classmethod
    def instance(cls) -> "MonitorService":
        if cls._instance is None:
            cls._instance = MonitorService()
        return cls._instance

    def start(self) -> None:
        self._thread.start()

    def set_interval(self, ms: int) -> None:
        self._interval_changed.emit(ms)

    def _on_snapshot(self, snap: Snapshot) -> None:
        self.latest = snap
        self.snapshot.emit(snap)

    def stop(self) -> None:
        self._stop_requested.emit()
        self._thread.quit()
        self._thread.wait(3000)
