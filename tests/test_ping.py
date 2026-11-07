"""Testa detecção de perda de pacotes e a nota de estabilidade sem derrubar a rede real.

Execute:  python -m tests.test_ping
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pccc.network.monitor import stability_score  # noqa: E402
from pccc.network.ping import PingMonitor  # noqa: E402


def main() -> int:
    pm = PingMonitor(interval_s=0.5)
    pm.set_target("ok", "1.1.1.1")
    pm.set_target("dead", "10.255.255.1")   # endereço privado sem rota: nunca responde
    pm.start()
    time.sleep(6)
    pm.stop()
    ok, dead = pm.stats("ok"), pm.stats("dead")
    print(f"alvo ok   : perda {ok.loss_pct:.0f}%  média {ok.avg_ms}  enviados {ok.sent}")
    print(f"alvo morto: perda {dead.loss_pct:.0f}%  falhas seguidas {pm.consecutive_failures('dead')}")
    assert ok.loss_pct < 50 and ok.avg_ms is not None
    assert dead.loss_pct == 100 and pm.consecutive_failures("dead") >= 3

    for args, expect in (((0, 2, 15, 0), "Excelente"), ((5, 20, 80, 1), "Regular"),
                         ((20, 50, 200, 5), "Ruim")):
        s, label = stability_score(*args)
        print(f"estabilidade{args} = {s} {label}")
        assert label == expect, (args, s, label)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
