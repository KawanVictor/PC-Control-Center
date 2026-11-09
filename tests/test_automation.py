"""Testes da Fase 7 (alertas, notificações, uso por app, relatórios e sugestões).

O motor roda com RELÓGIO SIMULADO e leituras sintéticas, e o "balão" é capturado por um
receptor falso — nenhuma notificação real aparece. Relatórios usam o histórico real e são
gravados numa pasta temporária. Tudo que o teste grava no banco é removido no final.

Execute:  python -m tests.test_automation
"""
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from pccc.core.logger import setup_logging  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def main() -> int:
    setup_logging()
    app = QCoreApplication(sys.argv)  # noqa: F841 — sinais Qt
    from pccc.automation import advisor, reports, store
    from pccc.automation.engine import AlertEngine
    from pccc.automation.notifier import Notifier, _in_quiet_hours
    from pccc.monitoring.models import PartitionSample, ProcessEntry, Snapshot
    from pccc.network.models import NetworkSnapshot

    d = store.db()
    with d._lock:
        start_alert = d._conn.execute("SELECT COALESCE(MAX(id), 0) FROM alerts").fetchone()[0]
    results = {}
    shown = []
    clock = Clock()
    notifier = Notifier()
    notifier.sink = lambda title, msg, sev: shown.append((title, sev))
    focus = {"state": 5}
    notifier.focus_state = lambda: focus["state"]
    eng = AlertEngine(clock=clock, notifier=notifier)
    eng.usage.flush = lambda now=None: None   # não grava uso fictício no banco real
    fired = []
    eng.fired.connect(fired.append)

    def snap(cpu=10, ram=50, temp=50, free_pct=50, apps=None):
        s = Snapshot()
        s.cpu.percent = cpu
        s.memory.percent = ram
        s.memory.total, s.memory.used = 8 * 2 ** 30, int(8 * 2 ** 30 * ram / 100)
        s.memory.commit_limit, s.memory.commit_used = 16 * 2 ** 30, 4 * 2 ** 30
        s.temps.cpu = temp
        s.partitions = [PartitionSample(mount="Z:\\", total=100, used=int(100 - free_pct),
                                        free=int(free_pct), percent=100 - free_pct)]
        s.processes.apps = list(apps or [ProcessEntry(pid=1, name="PCCC_Normal.exe", cpu=1, memory=10 ** 8)])
        return s

    def run(seconds, step=2, **kw):
        for _ in range(int(seconds / step)):
            clock.t += step
            eng.on_system(snap(**kw))

    def kinds():
        return [a.kind for a in fired]

    # 1. RAM: duração mínima e intervalo entre repetições
    run(100, ram=95)
    results["RAM 95% por 100 s: ainda não alerta (exige 120 s)"] = "ram" not in kinds()
    run(30, ram=95)
    results["RAM 95% por 130 s: alerta"] = kinds().count("ram") == 1
    run(200, ram=95)
    results["RAM continua alta: não repete antes do intervalo (30 min)"] = kinds().count("ram") == 1
    run(10, ram=50)
    clock.t += 30 * 60
    run(130, ram=95)
    results["após o intervalo, alerta de novo"] = kinds().count("ram") == 2

    # 2. pico curto de CPU não alerta
    run(30, cpu=100)
    run(10, cpu=10)
    results["pico de CPU de 30 s: sem alerta"] = "cpu" not in kinds()

    # 3. app com CPU excessiva (por app, independente)
    heavy = lambda: [ProcessEntry(pid=2, name="PCCC_Pesado.exe", cpu=60, memory=10 ** 8)]  # noqa: E731
    for _ in range(155):
        clock.t += 2
        eng.on_system(snap(apps=heavy()))
    results["app com 60% de CPU por 5 min: alerta com o nome do app"] = any(
        a.kind == "app_cpu" and "PCCC_Pesado" in a.title for a in fired)

    # 4. temperatura crítica fura o modo tela cheia; aviso comum não
    focus["state"] = 3   # jogo em tela cheia
    shown.clear()
    run(62, temp=98)
    crit = [a for a in fired if a.kind == "cpu_temp"]
    results["98 °C: alerta CRÍTICO exibido mesmo com jogo em tela cheia"] = bool(crit) and \
        crit[-1].severity == "critical" and any(s == "critical" for _t, s in shown)
    eng._last_fire.clear()
    shown.clear()
    run(130, ram=96)
    results["aviso comum com jogo em tela cheia: só na Central, sem balão"] = not shown and fired[-1].kind == "ram" \
        and not fired[-1].notified
    focus["state"] = 5

    # 5. disco
    run(2, free_pct=5)
    results["5% livre no disco: alerta imediato"] = any(a.kind == "disk_free" for a in fired)

    # 6. internet
    def net(status):
        n = NetworkSnapshot()
        n.status = status
        return n
    for _ in range(5):
        clock.t += 2
        eng.on_network(net("no_internet"))
    results["internet fora por 10 s: ainda não alerta (15 s)"] = "internet" not in kinds()
    for _ in range(4):
        clock.t += 2
        eng.on_network(net("no_internet"))
    clock.t += 60
    eng.on_network(net("online"))
    results["queda de 15 s alerta e a volta avisa"] = "internet" in kinds() and kinds()[-1] == "internet_back"

    # 7. horário de silêncio atravessando a meia-noite
    q = _in_quiet_hours
    results["silêncio 22:00–07:00 (23h sim, 06h sim, 12h não)"] = (
        q("22:00", "07:00", datetime(2026, 1, 1, 23)) and q("22:00", "07:00", datetime(2026, 1, 1, 6))
        and not q("22:00", "07:00", datetime(2026, 1, 1, 12)))

    # 8. uso por app acumulado
    acc = eng.usage._acc.get("PCCC_Pesado")
    results["uso acumulado: ~0,6 s de CPU por segundo para app a 60%"] = bool(acc) and abs(acc[0] / acc[2] - 0.6) < 0.01

    # 9. relatório com dados reais (numa máquina sem histórico, como o CI, usa 1 h de amostras sintéticas)
    tmp = Path(tempfile.mkdtemp())
    from pccc.core.database import Database
    fake_ts = []
    if reports.build_report("24h")["samples"] < 2:
        now = int(datetime.now().timestamp())
        fake_ts = [now - 60 * i for i in range(60, 0, -1)]
        for i, t in enumerate(fake_ts):
            Database.instance().insert_metrics(t, {"cpu": 20 + i % 50, "ram": 55.0, "cpu_temp": 60.0,
                                                   "net_down": 1e5, "net_up": 2e4})
    rep = reports.build_report("24h")
    html = reports.export_html(rep, tmp / "r.html")
    csvp = reports.export_csv(rep, tmp / "r.csv")
    text = Path(html).read_text(encoding="utf-8")
    results[f"relatório 24 h: {rep['samples']} amostras, HTML e CSV gerados"] = (
        "Relatório de desempenho" in text and "<svg" in text and Path(csvp).stat().st_size > 50)
    with Database.instance()._lock:
        Database.instance()._conn.executemany("DELETE FROM metrics_history WHERE ts = ?", [(t,) for t in fake_ts])
        Database.instance()._conn.commit()

    # 10. sugestões com RAM alta
    b, sugg = advisor.analyze(snap(ram=93, apps=[ProcessEntry(pid=3, name="Navegador.exe", cpu=5,
                                                             memory=3 * 2 ** 30)]), None)
    results[f"sugestões: RAM no limite detectada ({len(sugg)} sugestões, gargalo: {b.resource})"] = any(
        "RAM" in x.title for x in sugg)

    with d._lock:   # limpa o que o teste gravou
        d._conn.execute("DELETE FROM alerts WHERE id > ?", (start_alert,))
        d._conn.commit()

    for k, v in results.items():
        print(f"{'OK ' if v else 'FALHOU'}  {k}")
    ok = all(results.values())
    print("OK" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
