"""Estruturas de dados trocadas entre o coletor (thread) e a interface."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CpuSample:
    name: str = ""
    cores: int = 0
    threads: int = 0
    percent: float = 0.0
    per_core: list[float] = field(default_factory=list)
    freq_mhz: float = 0.0
    base_mhz: float = 0.0


@dataclass
class MemorySample:
    total: int = 0
    used: int = 0
    available: int = 0
    percent: float = 0.0
    commit_used: int = 0
    commit_limit: int = 0
    cached: int = 0
    swap_total: int = 0
    swap_used: int = 0
    swap_percent: float = 0.0


@dataclass
class GpuSample:
    name: str = ""
    luid: str = ""
    percent: float = 0.0
    engines: dict[str, float] = field(default_factory=dict)  # 3D, Copy, VideoDecode...
    dedicated_used: int = 0
    dedicated_total: int = 0
    shared_used: int = 0
    shared_total: int = 0
    temperature: Optional[float] = None


@dataclass
class PartitionSample:
    mount: str = ""
    label: str = ""
    fstype: str = ""
    total: int = 0
    used: int = 0
    free: int = 0
    percent: float = 0.0


@dataclass
class PhysicalDiskSample:
    name: str = ""
    media: str = ""      # SSD / HDD / Desconhecido
    bus: str = ""
    size: int = 0
    health: str = ""
    temperature: Optional[float] = None


@dataclass
class DiskIoSample:
    read_bps: float = 0.0
    write_bps: float = 0.0
    active_percent: float = 0.0


@dataclass
class NetIoSample:
    down_bps: float = 0.0
    up_bps: float = 0.0
    total_recv: int = 0
    total_sent: int = 0


@dataclass
class TemperatureSample:
    cpu: Optional[float] = None
    gpu: Optional[float] = None
    disks: dict[str, float] = field(default_factory=dict)
    source: str = ""        # de onde vieram as leituras
    hint: str = ""          # explicação quando indisponível


@dataclass
class ProcessEntry:
    pid: int
    name: str
    cpu: float          # % do total da máquina (como o Gerenciador de Tarefas)
    memory: int         # conjunto de trabalho em bytes
    threads: int = 0
    count: int = 1      # nº de processos (quando agrupado por aplicativo)
    ppid: int = 0
    session: int = 0
    create: int = 0     # horário de criação (FILETIME) — identifica o processo junto com o PID
    exe: str = ""       # caminho completo (vazio para processos protegidos)
    kind: str = ""      # Aplicativo | Segundo plano | Windows
    title: str = ""     # título da janela principal (aplicativos)
    handles: int = 0


@dataclass
class ProcessSummary:
    total: int = 0
    threads: int = 0
    top_cpu: list[ProcessEntry] = field(default_factory=list)
    top_memory: list[ProcessEntry] = field(default_factory=list)
    apps: list[ProcessEntry] = field(default_factory=list)   # agrupado por executável
    all: list[ProcessEntry] = field(default_factory=list)    # todos os processos (Fase 4)


@dataclass
class Snapshot:
    ts: float = 0.0
    uptime_s: float = 0.0
    cpu: CpuSample = field(default_factory=CpuSample)
    memory: MemorySample = field(default_factory=MemorySample)
    gpus: list[GpuSample] = field(default_factory=list)
    partitions: list[PartitionSample] = field(default_factory=list)
    physical_disks: list[PhysicalDiskSample] = field(default_factory=list)
    disk_io: DiskIoSample = field(default_factory=DiskIoSample)
    net_io: NetIoSample = field(default_factory=NetIoSample)
    temps: TemperatureSample = field(default_factory=TemperatureSample)
    processes: ProcessSummary = field(default_factory=ProcessSummary)

    @property
    def primary_gpu(self) -> Optional[GpuSample]:
        """GPU principal: a de maior VRAM dedicada (normalmente a dedicada, se houver)."""
        if not self.gpus:
            return None
        return max(self.gpus, key=lambda g: (g.dedicated_total, g.percent))
