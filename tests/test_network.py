"""Teste de integração da rede: roda o serviço por 6 s e, opcionalmente, o teste de velocidade.

Execute:  python -m tests.test_network            (monitoramento)
          python -m tests.test_network --speed    (inclui teste de velocidade, ~16 s e ~150 MB)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

from pccc.core.logger import setup_logging  # noqa: E402
from pccc.network.monitor import NetworkService  # noqa: E402
from pccc.ui.fmt import fmt_bits, fmt_bytes  # noqa: E402


def main() -> int:
    setup_logging()
    app = QCoreApplication(sys.argv)
    svc = NetworkService.instance()
    snaps = []
    svc.snapshot.connect(snaps.append)
    svc.start()
    QTimer.singleShot(6500, app.quit)
    app.exec()
    svc.stop()

    assert snaps, "nenhum snapshot de rede"
    s = snaps[-1]
    w, a = s.wifi, s.active
    print(f"Snapshots: {len(snaps)}  status={s.status}")
    print(f"Wi-Fi : {w.ssid!r} sinal {w.signal}% ({w.rssi} dBm) canal {w.channel} {w.band} {w.standard} "
          f"{w.security} link {w.rx_mbps:.0f} Mbps  erro={w.error!r}")
    if a:
        print(f"Ativa : {a.name} ({a.kind}) {a.description}")
        print(f"        IPv4 {a.ipv4}  IPv6 {a.ipv6[:2]}  GW {a.gateways}  DNS {a.dns}  MAC {a.mac}  DHCP {a.dhcp}")
    print(f"Tráfego: ↓ {fmt_bits(s.down_bps)}  ↑ {fmt_bits(s.up_bps)}")
    pi, pg = s.ping_internet, s.ping_gateway
    print(f"Ping internet ({pi.target}): último {pi.last_ms} média {pi.avg_ms and round(pi.avg_ms, 1)} "
          f"jitter {pi.jitter_ms and round(pi.jitter_ms, 1)} perda {pi.loss_pct:.0f}% ({pi.sent} enviados)")
    print(f"Ping gateway ({pg.target}): último {pg.last_ms} média {pg.avg_ms and round(pg.avg_ms, 1)}")
    print(f"Estabilidade: {s.stability} ({s.stability_label})  quedas 24h: {s.drops_24h}")
    print(f"Consumo hoje: ↓ {fmt_bytes(s.usage.today_rx)} ↑ {fmt_bytes(s.usage.today_tx)}")
    assert s.status in ("online", "no_internet", "offline")
    assert s.interfaces, "nenhuma interface"

    if "--speed" in sys.argv:
        from pccc.network.speedtest import run_speedtest
        import threading
        last = {}
        r = run_speedtest(lambda ph, f, mb: last.update({ph: mb}), threading.Event())
        print(f"Velocidade: ↓ {r.down_mbps and round(r.down_mbps, 1)} Mbps  ↑ {r.up_mbps and round(r.up_mbps, 1)} Mbps  "
              f"latência {r.latency_ms and round(r.latency_ms, 1)} ms  jitter {r.jitter_ms and round(r.jitter_ms, 1)}  "
              f"{r.server}  IP {r.public_ip}  usados {fmt_bytes(r.bytes_used)}  erro={r.error!r}")
        assert not r.error and r.down_mbps and r.up_mbps
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
