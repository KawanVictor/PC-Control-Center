"""Banco SQLite para histórico de desempenho e registro de operações.

O histórico é gravado em amostras agregadas (média de N segundos, padrão 60 s), o que
mantém o arquivo pequeno: 30 dias ≈ 43 mil linhas.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable

from .logger import get_logger
from .paths import database_file

log = get_logger("database")

METRIC_COLUMNS = ("cpu", "ram", "gpu", "cpu_temp", "gpu_temp",
                  "net_down", "net_up", "disk_read", "disk_write")

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS metrics_history (
    ts INTEGER PRIMARY KEY,
    {", ".join(f"{c} REAL" for c in METRIC_COLUMNS)}
);
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    result TEXT
);
CREATE INDEX IF NOT EXISTS idx_operations_ts ON operations(ts);
CREATE TABLE IF NOT EXISTS net_usage (
    day TEXT NOT NULL,          -- AAAA-MM-DD (horário local)
    iface TEXT NOT NULL,
    rx INTEGER NOT NULL DEFAULT 0,
    tx INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, iface)
);
CREATE TABLE IF NOT EXISTS net_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_net_events_ts ON net_events(ts);
CREATE TABLE IF NOT EXISTS speedtests (
    ts INTEGER PRIMARY KEY,
    down_mbps REAL, up_mbps REAL, latency_ms REAL, jitter_ms REAL,
    server TEXT, public_ip TEXT, iface TEXT, ssid TEXT
);
"""


class Database:
    _instance: "Database | None" = None
    _conn: sqlite3.Connection
    recovered_from: str | None
    # Módulos que criam tabelas próprias marcam aqui que já criaram (uma vez por execução)
    _regbackup_ready = False
    _automation_ready = False
    _lan_ready = False
    _perslog_ready = False

    def __init__(self, path=None) -> None:
        self._lock = threading.Lock()
        path = Path(path or database_file())
        try:
            self._open(path)
        except sqlite3.DatabaseError as e:
            # Banco danificado (ex.: desligamento forçado): guarda o arquivo e começa um novo,
            # em vez de impedir o app de abrir.
            log.error("Banco de dados danificado (%s); criando um novo.", e)
            try:
                self._conn.close()
            except Exception:
                pass
            bad = path.with_name(f"{path.stem}.corrompido-{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}")
            for suffix in ("", "-wal", "-shm"):
                src = Path(str(path) + suffix)
                if src.exists():
                    os.replace(src, Path(str(bad) + suffix))
            self._open(path)
            self.recovered_from = str(bad)

    def _open(self, path: Path) -> None:
        self.recovered_from = None
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        row = self._conn.execute("PRAGMA quick_check").fetchone()
        if not row or row[0] != "ok":
            raise sqlite3.DatabaseError(f"quick_check: {row[0] if row else '?'}")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @classmethod
    def instance(cls) -> "Database":
        if cls._instance is None:
            cls._instance = Database()
        return cls._instance

    # ---------------------------------------------------------------- métricas
    def insert_metrics(self, ts: int, values: dict) -> None:
        cols = ", ".join(("ts",) + METRIC_COLUMNS)
        marks = ", ".join("?" * (len(METRIC_COLUMNS) + 1))
        row = [ts] + [values.get(c) for c in METRIC_COLUMNS]
        try:
            with self._lock:
                self._conn.execute(f"INSERT OR REPLACE INTO metrics_history ({cols}) VALUES ({marks})", row)
                self._conn.commit()
        except sqlite3.Error as e:
            log.error("Falha ao gravar histórico: %s", e)

    def query_metrics(self, since_ts: int, columns: Iterable[str] = METRIC_COLUMNS,
                      max_points: int = 600) -> list[tuple]:
        """Retorna (ts, *colunas) desde ``since_ts``, reduzindo para ~max_points linhas."""
        cols = [c for c in columns if c in METRIC_COLUMNS]
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM metrics_history WHERE ts >= ?",
                                       (since_ts,)).fetchone()[0]
            if total == 0:
                return []
            bucket = max(1, total // max_points)
            if bucket == 1:
                sql = f"SELECT ts, {', '.join(cols)} FROM metrics_history WHERE ts >= ? ORDER BY ts"
            else:
                # Agrupa linhas consecutivas e tira a média de cada bloco.
                avg = ", ".join(f"AVG({c})" for c in cols)
                sql = (f"SELECT MIN(ts), {avg} FROM (SELECT *, (ROW_NUMBER() OVER (ORDER BY ts) - 1) / {bucket} AS b "
                       f"FROM metrics_history WHERE ts >= ?) GROUP BY b ORDER BY 1")
            return self._conn.execute(sql, (since_ts,)).fetchall()

    def prune(self, retention_days: int) -> None:
        cutoff = int(time.time()) - retention_days * 86400
        with self._lock:
            self._conn.execute("DELETE FROM metrics_history WHERE ts < ?", (cutoff,))
            self._conn.execute("DELETE FROM operations WHERE ts < ?", (cutoff - 60 * 86400,))
            self._conn.execute("DELETE FROM net_events WHERE ts < ?", (cutoff,))
            # Consumo de dados é guardado por 13 meses (comparação mês a mês).
            self._conn.execute("DELETE FROM net_usage WHERE day < date('now', '-400 days')")
            self._conn.commit()

    # -------------------------------------------------------------- operações
    def log_operation(self, action: str, details: str, result: str) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO operations (ts, action, details, result) VALUES (?, ?, ?, ?)",
                               (int(time.time()), action, details, result))
            self._conn.commit()

    def recent_operations(self, limit: int = 200) -> list[tuple]:
        with self._lock:
            return self._conn.execute(
                "SELECT ts, action, details, result FROM operations ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()

    # ------------------------------------------------------------------- rede
    def add_net_usage(self, day: str, iface: str, rx: int, tx: int) -> None:
        if rx <= 0 and tx <= 0:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO net_usage (day, iface, rx, tx) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(day, iface) DO UPDATE SET rx = rx + excluded.rx, tx = tx + excluded.tx",
                (day, iface, int(rx), int(tx)))
            self._conn.commit()

    def net_usage_by_day(self, since_day: str) -> list[tuple[str, int, int]]:
        with self._lock:
            return self._conn.execute(
                "SELECT day, SUM(rx), SUM(tx) FROM net_usage WHERE day >= ? GROUP BY day ORDER BY day",
                (since_day,)).fetchall()

    def add_net_event(self, ts: int, kind: str, message: str) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO net_events (ts, kind, message) VALUES (?, ?, ?)", (ts, kind, message))
            self._conn.commit()

    def net_events(self, since_ts: int, limit: int = 100) -> list[tuple[int, str, str]]:
        with self._lock:
            return self._conn.execute(
                "SELECT ts, kind, message FROM net_events WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                (since_ts, limit)).fetchall()

    def add_speedtest(self, r: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO speedtests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (int(r["ts"]), r.get("down_mbps"), r.get("up_mbps"), r.get("latency_ms"), r.get("jitter_ms"),
                 r.get("server", ""), r.get("public_ip", ""), r.get("iface", ""), r.get("ssid", "")))
            self._conn.commit()

    def speedtests(self, limit: int = 20) -> list[tuple]:
        with self._lock:
            return self._conn.execute(
                "SELECT ts, down_mbps, up_mbps, latency_ms, jitter_ms, server, public_ip, iface, ssid "
                "FROM speedtests ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
