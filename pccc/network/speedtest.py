"""Teste de velocidade usando a infraestrutura pública da Cloudflare (speed.cloudflare.com).

Etapas: latência (handshake TCP, 12 amostras) → download (4 conexões, ~7 s) → upload (4 conexões, ~7 s).
O primeiro segundo de cada etapa é descartado (aceleração inicial do TCP), como fazem os
medidores profissionais. Só roda quando o usuário clica em "Iniciar teste".
"""
from __future__ import annotations

import http.client
import os
import socket
import ssl
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

from ..core.logger import get_logger, log_operation

log = get_logger("speedtest")

HOST = "speed.cloudflare.com"
UA = "PCControlCenter/0.3 (+speedtest)"
STREAMS = 4
PHASE_SECONDS = 7.0
WARMUP_SECONDS = 1.0


@dataclass
class SpeedResult:
    ts: float = 0.0
    latency_ms: float | None = None
    jitter_ms: float | None = None
    down_mbps: float | None = None
    up_mbps: float | None = None
    server: str = ""
    public_ip: str = ""
    bytes_used: int = 0
    error: str = ""
    extra: dict = field(default_factory=dict)


def _conn(timeout: float = 15) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(HOST, timeout=timeout, context=ssl.create_default_context())


def _trace() -> dict:
    c = _conn(10)
    try:
        c.request("GET", "/cdn-cgi/trace", headers={"User-Agent": UA})
        body = c.getresponse().read().decode("utf-8", "replace")
        return dict(line.split("=", 1) for line in body.splitlines() if "=" in line)
    finally:
        c.close()


def _latency(samples: int = 12) -> tuple[float, float]:
    """RTT medido pelo handshake TCP (SYN → SYN-ACK) até o servidor de teste.

    Medir por requisição HTTP inclui processamento do servidor e atrasos do TCP
    (delayed ACK), o que inflava a latência; o tempo de conexão é o RTT puro.
    """
    addr = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)[0][4]
    times = []
    for _ in range(samples):
        t0 = time.perf_counter()
        try:
            s = socket.create_connection((str(addr[0]), int(addr[1])), timeout=3)
        except OSError:
            continue
        times.append((time.perf_counter() - t0) * 1000)
        s.close()
        time.sleep(0.05)
    if not times:
        raise OSError("servidor de teste não respondeu")
    jitter = statistics.mean(abs(a - b) for a, b in zip(times, times[1:], strict=False)) if len(times) > 1 else 0.0
    return statistics.median(times), jitter


class _Meter:
    """Contador de bytes compartilhado pelas conexões paralelas."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.total = 0
        self.counted = 0      # bytes após o aquecimento
        self.start = time.perf_counter()
        self.measure_start = self.start + WARMUP_SECONDS
        self.deadline = self.start + PHASE_SECONDS

    def add(self, n: int) -> None:
        now = time.perf_counter()
        with self.lock:
            self.total += n
            if now >= self.measure_start:
                self.counted += n

    def mbps(self) -> float:
        now = min(time.perf_counter(), self.deadline)
        dt = now - self.measure_start
        if dt <= 0.05:
            dt = max(now - self.start, 0.05)
            return self.total * 8 / dt / 1e6
        return self.counted * 8 / dt / 1e6

    def done(self) -> bool:
        return time.perf_counter() >= self.deadline


def _download_worker(m: _Meter, cancel: threading.Event) -> None:
    c = _conn()
    try:
        while not m.done() and not cancel.is_set():
            c.request("GET", "/__down?bytes=50000000", headers={"User-Agent": UA})
            r = c.getresponse()
            while not m.done() and not cancel.is_set():
                chunk = r.read(65536)
                if not chunk:
                    break
                m.add(len(chunk))
            if m.done() or cancel.is_set():
                break
    except Exception as e:
        log.debug("download stream: %s", e)
    finally:
        c.close()


def _upload_worker(m: _Meter, cancel: threading.Event, payload: bytes) -> None:
    c = _conn()
    try:
        while not m.done() and not cancel.is_set():
            c.putrequest("POST", "/__up")
            c.putheader("User-Agent", UA)
            c.putheader("Content-Type", "application/octet-stream")
            c.putheader("Content-Length", str(len(payload)))
            c.endheaders()
            view = memoryview(payload)
            for i in range(0, len(payload), 65536):
                if cancel.is_set():
                    return
                part = view[i:i + 65536]
                c.send(part)
                m.add(len(part))
            c.getresponse().read()
    except Exception as e:
        log.debug("upload stream: %s", e)
    finally:
        c.close()


def _run_phase(worker, args, progress: Callable[[str, float, float], None], phase: str,
               cancel: threading.Event) -> _Meter:
    m = _Meter()

    def target(*a):
        from ..core.com import ensure_com
        ensure_com()
        worker(*a)

    threads = [threading.Thread(target=target, args=(m, cancel, *args), daemon=True) for _ in range(STREAMS)]
    for t in threads:
        t.start()
    while not m.done() and not cancel.is_set():
        time.sleep(0.2)
        elapsed = time.perf_counter() - m.start
        progress(phase, min(1.0, elapsed / PHASE_SECONDS), m.mbps())
    for t in threads:
        t.join(timeout=5)
    return m


def run_speedtest(progress: Callable[[str, float, float], None], cancel: threading.Event) -> SpeedResult:
    res = SpeedResult(ts=time.time())
    try:
        progress("Conectando ao servidor", 0.0, 0.0)
        tr = _trace()
        res.server = f"Cloudflare {tr.get('colo', '?')} ({tr.get('loc', '?')})"
        res.public_ip = tr.get("ip", "")

        progress("Latência", 0.0, 0.0)
        res.latency_ms, res.jitter_ms = _latency()
        if cancel.is_set():
            raise InterruptedError

        m = _run_phase(_download_worker, (), progress, "Download", cancel)
        res.down_mbps = m.mbps()
        res.bytes_used += m.total
        if cancel.is_set():
            raise InterruptedError

        payload = os.urandom(4 * 1024 * 1024)   # dados aleatórios: não comprimem
        m = _run_phase(_upload_worker, (payload,), progress, "Upload", cancel)
        res.up_mbps = m.mbps()
        res.bytes_used += m.total
        log_operation("network.speedtest",
                      f"down={res.down_mbps:.1f} up={res.up_mbps:.1f} ping={res.latency_ms:.1f} {res.server}")
    except InterruptedError:
        res.error = "Teste cancelado."
    except Exception as e:
        log.warning("Teste de velocidade falhou: %s", e)
        res.error = f"Não foi possível concluir o teste: {e}"
    return res


class SpeedTestRunner(QThread):
    """Executa o teste em segundo plano e informa o progresso à interface.

    Os sinais são entregues na thread da interface automaticamente (conexão enfileirada).
    """

    progress = Signal(str, float, float)   # etapa, fração 0–1, Mbps atual
    result = Signal(object)                # SpeedResult

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancel = threading.Event()

    def begin(self) -> None:
        if self.isRunning():
            return
        self._cancel.clear()
        self.start()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:  # executado na thread de segundo plano
        from ..core.com import ensure_com
        ensure_com()
        res = run_speedtest(lambda *a: self.progress.emit(*a), self._cancel)
        self.result.emit(res)
