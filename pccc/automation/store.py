"""Persistência da Fase 7: histórico de alertas e uso acumulado por aplicativo."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..core.database import Database

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,       -- info | warning | critical
    title TEXT NOT NULL,
    message TEXT,
    value REAL,
    action TEXT,                  -- página/ação sugerida
    notified INTEGER NOT NULL DEFAULT 0,
    read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);
CREATE TABLE IF NOT EXISTS app_usage (
    day TEXT NOT NULL,
    app TEXT NOT NULL,
    cpu_s REAL NOT NULL DEFAULT 0,     -- "segundos de máquina inteira" (CPU% total × tempo)
    mem_bs REAL NOT NULL DEFAULT 0,    -- bytes × segundos (para média de memória)
    seconds REAL NOT NULL DEFAULT 0,   -- tempo em que o app esteve aberto e foi medido
    PRIMARY KEY (day, app)
);
"""


@dataclass
class Alert:
    kind: str
    severity: str
    title: str
    message: str
    value: float | None = None
    action: str = ""
    ts: float = field(default_factory=time.time)
    id: int | None = None
    read: bool = False
    notified: bool = False


def db() -> Database:
    d = Database.instance()
    if not getattr(d, "_automation_ready", False):
        with d._lock:
            d._conn.executescript(_SCHEMA)
            d._conn.commit()
        d._automation_ready = True
    return d


def save_alert(a: Alert) -> int:
    d = db()
    with d._lock:
        cur = d._conn.execute(
            "INSERT INTO alerts (ts, kind, severity, title, message, value, action, notified) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (int(a.ts), a.kind, a.severity, a.title, a.message, a.value, a.action, int(a.notified)))
        d._conn.commit()
        a.id = cur.lastrowid
        return a.id


def list_alerts(limit: int = 200, since: float = 0) -> list[Alert]:
    d = db()
    with d._lock:
        rows = d._conn.execute("SELECT id, ts, kind, severity, title, message, value, action, notified, read "
                               "FROM alerts WHERE ts >= ? ORDER BY id DESC LIMIT ?", (int(since), limit)).fetchall()
    return [Alert(id=r[0], ts=r[1], kind=r[2], severity=r[3], title=r[4], message=r[5] or "", value=r[6],
                  action=r[7] or "", notified=bool(r[8]), read=bool(r[9])) for r in rows]


def unread_count() -> int:
    d = db()
    with d._lock:
        return d._conn.execute("SELECT COUNT(*) FROM alerts WHERE read = 0").fetchone()[0]


def mark_all_read() -> None:
    d = db()
    with d._lock:
        d._conn.execute("UPDATE alerts SET read = 1 WHERE read = 0")
        d._conn.commit()


def clear_alerts() -> None:
    d = db()
    with d._lock:
        d._conn.execute("DELETE FROM alerts")
        d._conn.commit()


def alert_counts(since: float) -> dict[str, int]:
    d = db()
    with d._lock:
        rows = d._conn.execute("SELECT kind, COUNT(*) FROM alerts WHERE ts >= ? GROUP BY kind",
                               (int(since),)).fetchall()
    return dict(rows)


def add_app_usage(day: str, rows: dict[str, tuple[float, float, float]]) -> None:
    d = db()
    with d._lock:
        d._conn.executemany(
            "INSERT INTO app_usage (day, app, cpu_s, mem_bs, seconds) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(day, app) DO UPDATE SET cpu_s = cpu_s + excluded.cpu_s, "
            "mem_bs = mem_bs + excluded.mem_bs, seconds = seconds + excluded.seconds",
            [(day, app, c, m, s) for app, (c, m, s) in rows.items()])
        d._conn.commit()


def top_apps(since_day: str, limit: int = 10, by: str = "cpu") -> list[tuple[str, float, float, float]]:
    """[(app, cpu_s, memória média em bytes, segundos)] desde ``since_day`` (inclusive)."""
    order = "SUM(cpu_s)" if by == "cpu" else "SUM(mem_bs) / MAX(SUM(seconds), 1)"
    d = db()
    with d._lock:
        return d._conn.execute(
            f"SELECT app, SUM(cpu_s), SUM(mem_bs) / MAX(SUM(seconds), 1), SUM(seconds) FROM app_usage "
            f"WHERE day >= ? GROUP BY app ORDER BY {order} DESC LIMIT ?", (since_day, limit)).fetchall()


def prune(days: int = 90) -> None:
    d = db()
    cutoff = time.time() - days * 86400
    with d._lock:
        d._conn.execute("DELETE FROM alerts WHERE ts < ?", (int(cutoff),))
        d._conn.execute("DELETE FROM app_usage WHERE day < date('now', ?)", (f"-{days} days",))
        d._conn.commit()
