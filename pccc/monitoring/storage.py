"""Monitor de armazenamento: partições, discos físicos e velocidade de leitura/gravação."""
from __future__ import annotations

import ctypes
import time

import psutil

from ..core.logger import get_logger
from .models import DiskIoSample, PartitionSample, PhysicalDiskSample

log = get_logger("storage")

_MEDIA = {3: "HDD", 4: "SSD", 5: "SCM"}
_BUS = {1: "SCSI", 3: "ATA", 7: "USB", 8: "RAID", 10: "SAS", 11: "SATA", 12: "SD",
        13: "MMC", 17: "NVMe"}
_HEALTH = {0: "Saudável", 1: "Atenção", 2: "Não saudável", 5: "Desconhecido"}


def _volume_label(mount: str) -> str:
    buf = ctypes.create_unicode_buffer(261)
    try:
        if ctypes.windll.kernel32.GetVolumeInformationW(mount, buf, 261, None, None, None, None, 0):
            return buf.value
    except Exception:
        pass
    return ""


def sample_partitions() -> list[PartitionSample]:
    parts = []
    for p in psutil.disk_partitions(all=False):
        if "cdrom" in p.opts or not p.fstype:
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except (PermissionError, OSError):
            continue  # unidade removível sem mídia, etc.
        parts.append(PartitionSample(mount=p.mountpoint, label=_volume_label(p.mountpoint),
                                     fstype=p.fstype, total=u.total, used=u.used,
                                     free=u.free, percent=u.percent))
    return parts


_storage_wmi = None   # conexão reaproveitada (sempre usada na thread do coletor)


def sample_physical_disks() -> list[PhysicalDiskSample]:
    """Discos físicos via WMI (não exige administrador). Chame em thread com COM iniciado."""
    global _storage_wmi
    disks = []
    try:
        import wmi
        if _storage_wmi is None:
            _storage_wmi = wmi.WMI(namespace=r"root\Microsoft\Windows\Storage")
        conn = _storage_wmi
        for d in conn.MSFT_PhysicalDisk():
            disks.append(PhysicalDiskSample(
                name=(d.FriendlyName or "Disco").strip(),
                media=_MEDIA.get(d.MediaType, "Desconhecido"),
                bus=_BUS.get(d.BusType, ""),
                size=int(d.Size or 0),
                health=_HEALTH.get(d.HealthStatus, "Desconhecido"),
            ))
    except Exception as e:
        log.info("Discos físicos indisponíveis: %s", e)
    return disks


class DiskIoMonitor:
    def __init__(self) -> None:
        self._last = psutil.disk_io_counters()
        self._t = time.monotonic()

    def sample(self, idle_percent: float | None) -> DiskIoSample:
        now = time.monotonic()
        cur = psutil.disk_io_counters()
        dt = max(now - self._t, 1e-3)
        out = DiskIoSample()
        if cur and self._last:
            out.read_bps = max(0.0, (cur.read_bytes - self._last.read_bytes) / dt)
            out.write_bps = max(0.0, (cur.write_bytes - self._last.write_bytes) / dt)
        if idle_percent is not None:
            out.active_percent = max(0.0, min(100.0, 100.0 - idle_percent))
        self._last, self._t = cur, now
        return out


class NetIoMonitor:
    """Taxa total de rede (o detalhamento completo fica no módulo de rede, Fase 3)."""

    def __init__(self) -> None:
        self._last = psutil.net_io_counters()
        self._t = time.monotonic()

    def sample(self):
        from .models import NetIoSample
        now = time.monotonic()
        cur = psutil.net_io_counters()
        dt = max(now - self._t, 1e-3)
        out = NetIoSample(total_recv=cur.bytes_recv, total_sent=cur.bytes_sent)
        out.down_bps = max(0.0, (cur.bytes_recv - self._last.bytes_recv) / dt)
        out.up_bps = max(0.0, (cur.bytes_sent - self._last.bytes_sent) / dt)
        self._last, self._t = cur, now
        return out
