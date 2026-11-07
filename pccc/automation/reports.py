"""Relatórios de desempenho a partir do histórico local (SQLite).

``build_report(período)`` devolve um dicionário com estatísticas; ``export_html`` gera um
arquivo único (gráficos em SVG embutido, sem internet) e ``export_csv`` exporta os dados brutos.
"""
from __future__ import annotations

import csv
import ctypes
import html
import os
import platform
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import __version__
from ..core.database import Database
from ..ui.fmt import fmt_bits, fmt_bytes
from . import store

PERIODS = {"24h": (86400, "Últimas 24 horas"), "7d": (7 * 86400, "Últimos 7 dias"),
           "30d": (30 * 86400, "Últimos 30 dias")}
COLS = ("cpu", "ram", "gpu", "cpu_temp", "gpu_temp", "net_down", "net_up", "disk_read", "disk_write")
ALERT_NAMES = {"cpu": "CPU elevada", "ram": "RAM quase cheia", "commit": "Memória virtual", "cpu_temp": "Temp. CPU",
               "gpu_temp": "Temp. GPU", "disk_free": "Pouco espaço", "internet": "Quedas de internet",
               "internet_back": "Internet restabelecida", "app_cpu": "App pesando na CPU",
               "app_ram": "App com muita memória", "battery": "Bateria fraca", "report": "Relatórios",
               "lan_new": "Aparelho novo na rede", "youtube": "Vídeo novo no YouTube"}


def _stats(values: list[float]) -> dict | None:
    v = sorted(x for x in values if x is not None and x == x)
    if not v:
        return None
    return {"avg": sum(v) / len(v), "max": v[-1], "min": v[0], "p95": v[min(len(v) - 1, int(len(v) * 0.95))]}


def documents_dir() -> Path:
    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:   # CSIDL_PERSONAL (Documentos)
        base = Path(buf.value)
    else:
        base = Path.home() / "Documents"
    d = base / "PC Control Center" / "Relatórios"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_report(period: str = "7d") -> dict:
    seconds, label = PERIODS[period]
    now = time.time()
    since = now - seconds
    db = Database.instance()
    rows = db.query_metrics(int(since), COLS, max_points=10_000)
    series = {c: [r[i + 1] for r in rows] for i, c in enumerate(COLS)}
    ts = [r[0] for r in rows]
    minutes = len(rows)   # cada linha ≈ 1 minuto (se o período for curto)
    stats = {c: _stats(series[c]) for c in COLS}

    def pct_above(col, limit):
        vals = [x for x in series[col] if x is not None]
        return 100 * sum(1 for x in vals if x >= limit) / len(vals) if vals else 0.0

    since_day = (date.today() - timedelta(days=max(0, seconds // 86400 - 1))).isoformat()
    net_days = db.net_usage_by_day(since_day)
    with db._lock:
        drops = db._conn.execute("SELECT COUNT(*) FROM net_events WHERE ts >= ? AND kind IN "
                                 "('internet_down', 'wifi_down')", (int(since),)).fetchone()[0]
        speed = db._conn.execute("SELECT ts, down_mbps, up_mbps, latency_ms FROM speedtests WHERE ts >= ? "
                                 "ORDER BY ts", (int(since),)).fetchall()
    return {
        "period": period, "label": label, "generated": now, "since": since,
        "samples": minutes, "hours_monitored": minutes / 60,
        "stats": stats, "series": series, "ts": ts,
        "above": {"cpu80": pct_above("cpu", 80), "ram90": pct_above("ram", 90),
                  "cpu_temp85": pct_above("cpu_temp", 85)},
        "net": {"rx": sum(r[1] or 0 for r in net_days), "tx": sum(r[2] or 0 for r in net_days),
                "days": net_days},
        "drops": drops, "speedtests": speed,
        "alerts": store.alert_counts(since),
        "top_cpu": store.top_apps(since_day, 10, "cpu"),
        "top_mem": store.top_apps(since_day, 10, "mem"),
        "host": platform.node(),
    }


# ---------------------------------------------------------------------- HTML
def _svg_chart(ts: list, series: list[tuple[str, list, str]], height: int = 160, vmax: float | None = None,
               unit: str = "%") -> str:
    if len(ts) < 2:
        return "<p class='muted'>Sem dados suficientes neste período.</p>"
    w, h, pad = 900, height, 32
    t0, t1 = ts[0], ts[-1] or ts[0] + 1
    allv = [v for _n, vals, _c in series for v in vals if v is not None]
    top = vmax or (max(allv) * 1.15 if allv else 1) or 1

    def x(t):
        return pad + (w - pad - 8) * (t - t0) / max(1, t1 - t0)

    def y(v):
        return h - 20 - (h - 30) * min(1, max(0, v / top))

    parts = [f"<svg viewBox='0 0 {w} {h}' class='chart' role='img'>"]
    for frac in (0, 0.5, 1):
        yy = y(top * frac)
        parts.append(f"<line x1='{pad}' x2='{w - 8}' y1='{yy:.1f}' y2='{yy:.1f}' class='grid'/>"
                     f"<text x='2' y='{yy + 4:.1f}' class='axis'>{top * frac:.0f}{unit}</text>")
    for frac in (0, 0.5, 1):
        t = t0 + (t1 - t0) * frac
        anchor = "start" if frac == 0 else "end" if frac == 1 else "middle"
        parts.append(f"<text x='{x(t):.1f}' y='{h - 4}' text-anchor='{anchor}' class='axis'>"
                     f"{datetime.fromtimestamp(t):%d/%m %H:%M}</text>")
    for _name, vals, color in series:
        # Quebra a linha onde não há dados por mais de 10 min (app fechado / PC desligado),
        # para não desenhar uma reta inventada sobre o intervalo.
        segments, cur, prev_t = [], [], None
        for t, v in zip(ts, vals):
            if v is None:
                continue
            if prev_t is not None and t - prev_t > 600 and cur:
                segments.append(cur)
                cur = []
            cur.append(f"{x(t):.1f},{y(v):.1f}")
            prev_t = t
        if cur:
            segments.append(cur)
        for seg in segments:
            if len(seg) == 1:
                cx, cy = seg[0].split(",")
                parts.append(f"<circle cx='{cx}' cy='{cy}' r='1.8' fill='{color}'/>")
            else:
                parts.append(f"<polyline points='{' '.join(seg)}' fill='none' stroke='{color}' stroke-width='1.6' "
                             "stroke-linejoin='round'/>")
    parts.append("</svg><div class='legend'>" + "".join(
        f"<span><i style='background:{c}'></i>{html.escape(n)}</span>" for n, _v, c in series) + "</div>")
    return "".join(parts)


def _fmt(st, key, unit="%", dec=0):
    s = st.get(key) if st else None
    return "—" if s is None else f"{s:.{dec}f}{unit}".replace(".", ",")


def export_html(rep: dict, path: Path | None = None) -> str:
    st = rep["stats"]
    e = html.escape
    hours = rep["hours_monitored"]
    cards = []
    for title, col, unit in (("CPU", "cpu", "%"), ("Memória RAM", "ram", "%"), ("GPU", "gpu", "%"),
                             ("Temp. CPU", "cpu_temp", " °C"), ("Temp. GPU", "gpu_temp", " °C")):
        s = st[col]
        cards.append(f"<div class='card'><h3>{title}</h3><div class='big'>{_fmt(s, 'avg', unit)}</div>"
                     f"<div class='muted'>média · pico {_fmt(s, 'max', unit)} · 95% do tempo abaixo de "
                     f"{_fmt(s, 'p95', unit)}</div></div>")
    net = rep["net"]
    cards.append(f"<div class='card'><h3>Internet</h3><div class='big'>{fmt_bytes(net['rx'])}</div>"
                 f"<div class='muted'>baixados · {fmt_bytes(net['tx'])} enviados · {rep['drops']} queda(s)</div></div>")

    def app_rows(rows, by):
        if not rows:
            return "<tr><td colspan='3' class='muted'>Sem dados ainda (acumulados enquanto o app está aberto).</td></tr>"
        out = []
        for app, cpu_s, mem, secs in rows:
            cpu_h = f"{cpu_s / 3600:.2f}".replace(".", ",")
            open_h = f"{secs / 3600:.1f}".replace(".", ",")
            out.append(f"<tr><td>{e(app)}</td><td>{cpu_h} h de CPU</td>"
                       f"<td>{fmt_bytes(mem)} em média · aberto {open_h} h</td></tr>")
        return "".join(out)

    alerts = "".join(f"<tr><td>{e(ALERT_NAMES.get(k, k))}</td><td>{n}</td></tr>"
                     for k, n in sorted(rep["alerts"].items(), key=lambda kv: -kv[1])) or \
        "<tr><td colspan='2' class='muted'>Nenhum alerta no período. 👍</td></tr>"
    speeds = "".join(f"<tr><td>{datetime.fromtimestamp(t):%d/%m %H:%M}</td><td>{d:.0f} Mbps</td><td>{u:.0f} Mbps</td>"
                     f"<td>{lat:.0f} ms</td></tr>" for t, d, u, lat in rep["speedtests"] if d) or \
        "<tr><td colspan='4' class='muted'>Nenhum teste de velocidade no período.</td></tr>"
    s = rep["series"]
    charts = [
        ("Uso de CPU, RAM e GPU", _svg_chart(rep["ts"], [("CPU", s["cpu"], "#22d3ee"), ("RAM", s["ram"], "#a78bfa"),
                                                          ("GPU", s["gpu"], "#34d399")], vmax=100)),
        ("Temperaturas", _svg_chart(rep["ts"], [("CPU", s["cpu_temp"], "#fb7185"), ("GPU", s["gpu_temp"], "#fbbf24")],
                                     unit="°")),
        ("Rede (média por minuto)", _svg_chart(rep["ts"], [("Download", [v * 8 / 1e6 if v else None for v in s["net_down"]], "#38bdf8"),
                                                             ("Upload", [v * 8 / 1e6 if v else None for v in s["net_up"]], "#f472b6")],
                                                unit=" Mb")),
    ]
    doc = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relatório de desempenho — {e(rep['host'])}</title>
<style>
:root {{ color-scheme: light dark; --bg:#f6f8fb; --card:#fff; --text:#111827; --muted:#6b7280; --line:#e5e7eb; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0b1020; --card:#131a2e; --text:#e6eaf2; --muted:#8b96ab; --line:#243049; }} }}
body {{ font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 28px; }}
main {{ max-width: 1000px; margin: auto; }}
h1 {{ margin: 0 0 4px; }} h2 {{ margin-top: 32px; font-size: 18px; }} h3 {{ margin: 0 0 6px; font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .4px; }}
.muted {{ color: var(--muted); font-size: 13px; }}
.grid4 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
.card {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px; }}
.big {{ font-size: 28px; font-weight: 650; }}
table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 12px; overflow: hidden; border: 1px solid var(--line); }}
td, th {{ padding: 9px 12px; border-bottom: 1px solid var(--line); text-align: left; font-size: 14px; }}
.chart {{ width: 100%; height: auto; background: var(--card); border: 1px solid var(--line); border-radius: 12px; }}
.chart .grid {{ stroke: var(--line); }} .chart .axis {{ fill: var(--muted); font-size: 11px; }}
.legend span {{ margin-right: 14px; font-size: 13px; }} .legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 5px; margin-right: 5px; }}
footer {{ margin-top: 36px; }}
</style></head><body><main>
<h1>Relatório de desempenho</h1>
<div class="muted">{e(rep['host'])} · {e(rep['label'])} · gerado em {datetime.fromtimestamp(rep['generated']):%d/%m/%Y às %H:%M}
· {f"{hours:.1f}".replace(".", ",")} h monitoradas</div>
<h2>Resumo</h2><div class="grid4">{''.join(cards)}</div>
<p class="muted">CPU acima de 80%: {rep['above']['cpu80']:.0f}% do tempo · RAM acima de 90%: {rep['above']['ram90']:.0f}% do tempo ·
CPU acima de 85 °C: {rep['above']['cpu_temp85']:.0f}% do tempo</p>
{''.join(f"<h2>{t}</h2>{c}" for t, c in charts)}
<h2>Programas que mais usaram CPU</h2><table>{app_rows(rep['top_cpu'], 'cpu')}</table>
<h2>Programas que mais usaram memória</h2><table>{app_rows(rep['top_mem'], 'mem')}</table>
<h2>Alertas</h2><table>{alerts}</table>
<h2>Testes de velocidade</h2><table><tr><th>Data</th><th>Download</th><th>Upload</th><th>Latência</th></tr>{speeds}</table>
<footer class="muted">Gerado pelo PC Control Center v{__version__}. Dados coletados localmente neste computador;
nada foi enviado para a internet.</footer>
</main></body></html>"""
    if path is None:
        path = documents_dir() / f"Relatorio_{rep['period']}_{datetime.now():%Y-%m-%d_%H%M}.html"
    Path(path).write_text(doc, encoding="utf-8")
    return str(path)


def export_csv(rep: dict, path: Path | None = None) -> str:
    if path is None:
        path = documents_dir() / f"Historico_{rep['period']}_{datetime.now():%Y-%m-%d_%H%M}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # BOM: abre certo no Excel
        w = csv.writer(f, delimiter=";")
        w.writerow(["data_hora", "cpu_%", "ram_%", "gpu_%", "temp_cpu_C", "temp_gpu_C", "download_Mbps",
                    "upload_Mbps", "leitura_disco_MBs", "gravacao_disco_MBs"])
        s = rep["series"]
        for i, t in enumerate(rep["ts"]):
            def v(col, f=1.0, dec=1):
                x = s[col][i]
                return "" if x is None else f"{x * f:.{dec}f}".replace(".", ",")
            w.writerow([datetime.fromtimestamp(t).strftime("%d/%m/%Y %H:%M"), v("cpu"), v("ram"), v("gpu"),
                        v("cpu_temp"), v("gpu_temp"), v("net_down", 8 / 1e6, 2), v("net_up", 8 / 1e6, 2),
                        v("disk_read", 1 / 2 ** 20, 2), v("disk_write", 1 / 2 ** 20, 2)])
    return str(path)


__all__ = ["build_report", "export_html", "export_csv", "documents_dir", "fmt_bits", "os"]
