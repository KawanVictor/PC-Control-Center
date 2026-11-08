"""Ping ICMP nativo (IcmpSendEcho) — não abre processos e não exige administrador.

``PingMonitor`` roda em uma thread própria e pinga cada alvo no intervalo configurado,
mantendo uma janela deslizante com latência, perda de pacotes e jitter.
"""
from __future__ import annotations

import ctypes
import math
import socket
import threading
import time
from collections import deque
from ctypes import wintypes

from ..core.logger import get_logger
from .models import PingStats

log = get_logger("ping")


class IP_OPTION_INFORMATION(ctypes.Structure):
    _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte), ("Flags", ctypes.c_ubyte),
                ("OptionsSize", ctypes.c_ubyte), ("OptionsData", ctypes.c_void_p)]


class ICMP_ECHO_REPLY(ctypes.Structure):
    _fields_ = [("Address", wintypes.ULONG), ("Status", wintypes.ULONG), ("RoundTripTime", wintypes.ULONG),
                ("DataSize", wintypes.USHORT), ("Reserved", wintypes.USHORT), ("Data", ctypes.c_void_p),
                ("Options", IP_OPTION_INFORMATION)]


_icmp = ctypes.WinDLL("iphlpapi")
_icmp.IcmpCreateFile.restype = wintypes.HANDLE
_icmp.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
_icmp.IcmpSendEcho.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.WORD,
                               ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
_icmp.IcmpSendEcho.restype = wintypes.DWORD

_PAYLOAD = b"PCControlCenter-ping-32bytes!!!!"


def ping_once(ip: str, timeout_ms: int = 1000) -> float | None:
    """Envia um ICMP echo. Retorna o tempo em ms ou None se não houve resposta."""
    try:
        addr = int.from_bytes(socket.inet_aton(ip), "little")
    except OSError:
        return None
    handle = _icmp.IcmpCreateFile()
    if not handle or handle == wintypes.HANDLE(-1).value:
        return None
    try:
        reply_size = ctypes.sizeof(ICMP_ECHO_REPLY) + len(_PAYLOAD) + 8
        reply = ctypes.create_string_buffer(reply_size)
        data = ctypes.create_string_buffer(_PAYLOAD)
        t0 = time.perf_counter()
        n = _icmp.IcmpSendEcho(handle, addr, data, len(_PAYLOAD), None, reply, reply_size, timeout_ms)
        elapsed = (time.perf_counter() - t0) * 1000
        if n == 0:
            return None
        r = ICMP_ECHO_REPLY.from_buffer(reply)
        if r.Status != 0:
            return None
        # RoundTripTime tem resolução de 1 ms (0 = menos de 1 ms); usamos o medido se menor.
        return float(r.RoundTripTime) if r.RoundTripTime else round(min(elapsed, 1.0), 2)
    finally:
        _icmp.IcmpCloseHandle(handle)


def resolve(host: str) -> str | None:
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


class _Target:
    def __init__(self, window: int) -> None:
        self.host = ""
        self.ip: str | None = None
        self.resolved_at = 0.0
        self.samples: deque = deque(maxlen=window)
        self.sent = 0
        self.thread: threading.Thread | None = None


class PingMonitor:
    """Pinga alvos nomeados ('internet', 'gateway') continuamente.

    Cada alvo tem sua própria thread: um alvo que não responde (timeout de 1 s) não
    atrasa as medições dos outros.
    """

    def __init__(self, interval_s: float = 1.0, window: int = 120) -> None:
        self.interval = interval_s
        self._window = window
        self._targets: dict[str, _Target] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._started = False

    @property
    def running(self) -> bool:
        return self._started and not self._stop.is_set()

    def set_target(self, name: str, host: str) -> None:
        with self._lock:
            t = self._targets.setdefault(name, _Target(self._window))
            if t.host != host:
                t.host = host
                t.ip = None
                t.samples.clear()
                t.sent = 0
            if self._started and t.thread is None:
                self._spawn(name, t)

    def start(self) -> None:
        with self._lock:
            self._started = True
            for name, t in self._targets.items():
                if t.thread is None:
                    self._spawn(name, t)

    def stop(self) -> None:
        self._stop.set()

    def _spawn(self, name: str, t: _Target) -> None:
        t.thread = threading.Thread(target=self._run, args=(t,), name=f"Ping-{name}", daemon=True)
        t.thread.start()

    def _run(self, t: _Target) -> None:
        from ..core.com import ensure_com
        ensure_com()
        while not self._stop.is_set():
            t0 = time.monotonic()
            host = t.host
            if host:
                # Re-resolve o nome a cada 5 min (o IP de um domínio pode mudar).
                if t.ip is None or t0 - t.resolved_at > 300:
                    t.ip = resolve(host)
                    t.resolved_at = t0
                rtt = ping_once(t.ip, timeout_ms=1000) if t.ip else None
                with self._lock:
                    if t.host == host:  # alvo não mudou durante o ping
                        t.samples.append(rtt if rtt is not None else float("nan"))
                        t.sent += 1
            self._stop.wait(max(0.05, self.interval - (time.monotonic() - t0)))

    def stats(self, name: str, recent: int = 60) -> PingStats:
        with self._lock:
            t = self._targets.get(name)
            if t is None:
                return PingStats()
            hist = list(t.samples)
            host = t.host
        out = PingStats(target=host, history=hist, sent=len(hist))
        if not hist:
            return out
        window = hist[-recent:]
        ok = [v for v in window if not math.isnan(v)]
        out.loss_pct = 100.0 * (len(window) - len(ok)) / len(window)
        out.last_ms = None if math.isnan(hist[-1]) else hist[-1]
        if ok:
            out.avg_ms = sum(ok) / len(ok)
            out.min_ms = min(ok)
            out.max_ms = max(ok)
            diffs = [abs(a - b) for a, b in zip(window, window[1:], strict=False) if not (math.isnan(a) or math.isnan(b))]
            out.jitter_ms = sum(diffs) / len(diffs) if diffs else 0.0
        return out

    def consecutive_failures(self, name: str) -> int:
        with self._lock:
            t = self._targets.get(name)
            if t is None:
                return 0
            n = 0
            for v in reversed(t.samples):
                if math.isnan(v):
                    n += 1
                else:
                    break
            return n
