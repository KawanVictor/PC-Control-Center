"""Teste de integração do coletor: roda 4 segundos e valida que os dados são reais.

Execute:  python -m tests.test_collector
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

from pccc.core.logger import setup_logging  # noqa: E402
from pccc.monitoring.collector import MonitorService  # noqa: E402


def main() -> int:
    setup_logging()
    app = QCoreApplication(sys.argv)
    svc = MonitorService.instance()
    snaps = []
    svc.snapshot.connect(snaps.append)
    svc.start()
    QTimer.singleShot(4500, app.quit)
    app.exec()
    svc.stop()

    assert snaps, "nenhum snapshot recebido"
    s = snaps[-1]
    print(f"Snapshots: {len(snaps)}")
    print(f"CPU   : {s.cpu.name} | {s.cpu.percent:.1f}% | {s.cpu.freq_mhz:.0f} MHz | núcleos={len(s.cpu.per_core)}")
    print(f"RAM   : {s.memory.used / 2**30:.2f}/{s.memory.total / 2**30:.2f} GB ({s.memory.percent}%) | "
          f"confirmada {s.memory.commit_used / 2**30:.1f}/{s.memory.commit_limit / 2**30:.1f} GB")
    for g in s.gpus:
        print(f"GPU   : {g.name} | {g.percent:.1f}% | VRAM {g.dedicated_used >> 20}/{g.dedicated_total >> 20} MB | temp {g.temperature}")
    print(f"Temp  : CPU={s.temps.cpu} GPU={s.temps.gpu} fonte={s.temps.source!r} discos={s.temps.disks}")
    for p in s.partitions:
        print(f"Disco : {p.mount} {p.label!r} {p.free / 2**30:.1f} GB livres de {p.total / 2**30:.1f} GB")
    for d in s.physical_disks:
        print(f"Físico: {d.name} {d.media} {d.bus} {d.health}")
    print(f"E/S   : leitura {s.disk_io.read_bps / 1024:.0f} KB/s gravação {s.disk_io.write_bps / 1024:.0f} KB/s ativo {s.disk_io.active_percent:.0f}%")
    print(f"Rede  : ↓ {s.net_io.down_bps / 1024:.1f} KB/s ↑ {s.net_io.up_bps / 1024:.1f} KB/s")
    print(f"Proc  : {s.processes.total} processos, {s.processes.threads} threads")
    for e in s.processes.top_cpu[:5]:
        print(f"        {e.name:<28} CPU {e.cpu:5.1f}%  RAM {e.memory >> 20} MB")
    print(f"Uptime: {s.uptime_s / 3600:.1f} h")

    assert s.cpu.per_core and s.memory.total > 0 and s.partitions and s.processes.total > 10
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
