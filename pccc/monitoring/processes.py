"""Monitor de processos: maiores consumidores de CPU/RAM e consumo agrupado por aplicativo.

Usa uma única chamada a ``NtQuerySystemInformation(SystemProcessInformation)`` — a mesma
fonte do Gerenciador de Tarefas. Ela devolve todos os processos (inclusive os protegidos)
com tempos de CPU e memória em ~5 ms, enquanto consultar processo a processo com psutil
leva segundos por causa dos processos com acesso negado.
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

import psutil

from ..core.logger import get_logger
from .models import ProcessEntry, ProcessSummary
from .winproc import current_session, image_path, visible_windows

log = get_logger("processes")

_STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
_SystemProcessInformation = 5


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                ("Buffer", ctypes.c_void_p)]


class _SYSTEM_PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("NextEntryOffset", wintypes.ULONG),
        ("NumberOfThreads", wintypes.ULONG),
        ("WorkingSetPrivateSize", ctypes.c_longlong),
        ("HardFaultCount", wintypes.ULONG),
        ("NumberOfThreadsHighWatermark", wintypes.ULONG),
        ("CycleTime", ctypes.c_ulonglong),
        ("CreateTime", ctypes.c_longlong),
        ("UserTime", ctypes.c_longlong),
        ("KernelTime", ctypes.c_longlong),
        ("ImageName", _UNICODE_STRING),
        ("BasePriority", wintypes.LONG),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
        ("HandleCount", wintypes.ULONG),
        ("SessionId", wintypes.ULONG),
        ("UniqueProcessKey", ctypes.c_void_p),
        ("PeakVirtualSize", ctypes.c_size_t),
        ("VirtualSize", ctypes.c_size_t),
        ("PageFaultCount", wintypes.ULONG),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivatePageCount", ctypes.c_size_t),
    ]


_ntdll = ctypes.WinDLL("ntdll")
_ntdll.NtQuerySystemInformation.argtypes = [wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG,
                                            ctypes.POINTER(wintypes.ULONG)]
_ntdll.NtQuerySystemInformation.restype = ctypes.c_ulong


def query_processes() -> list[dict]:
    """Lista crua de processos: pid, ppid, nome, threads, cpu_time (s), memória privada."""
    size = 1 << 20
    for _ in range(8):
        buf = ctypes.create_string_buffer(size)
        needed = wintypes.ULONG(0)
        status = _ntdll.NtQuerySystemInformation(_SystemProcessInformation, buf, size,
                                                 ctypes.byref(needed))
        if status == _STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, needed.value + 65536)
            continue
        if status != 0:
            raise OSError(f"NtQuerySystemInformation falhou: 0x{status:08X}")
        break
    else:
        raise OSError("Buffer de processos insuficiente")

    out = []
    base = ctypes.addressof(buf)
    offset = 0
    while True:
        spi = _SYSTEM_PROCESS_INFORMATION.from_address(base + offset)
        name_len = spi.ImageName.Length // 2
        name = ctypes.wstring_at(spi.ImageName.Buffer, name_len) if spi.ImageName.Buffer else ""
        out.append({
            "pid": spi.UniqueProcessId or 0,
            "ppid": spi.InheritedFromUniqueProcessId or 0,
            "name": name,
            "threads": spi.NumberOfThreads,
            "handles": spi.HandleCount,
            "session": spi.SessionId,
            "create": spi.CreateTime,
            "cpu_time": (spi.UserTime + spi.KernelTime) / 1e7,   # unidades de 100 ns
            "private_ws": spi.WorkingSetPrivateSize,               # coluna "Memória" do Ger. Tarefas
            "working_set": spi.WorkingSetSize,
            "private_bytes": spi.PrivatePageCount,
        })
        if spi.NextEntryOffset == 0:
            break
        offset += spi.NextEntryOffset
    return out


_WINDOWS_DIR = os.environ.get("WINDIR", r"C:\Windows").lower()
# Processos do sistema que não têm caminho acessível ou que sempre são "Windows".
_SYSTEM_NAMES = {"system", "registry", "memory compression", "secure system", "smss.exe", "csrss.exe",
                 "wininit.exe", "services.exe", "lsass.exe", "winlogon.exe", "svchost.exe", "fontdrvhost.exe",
                 "dwm.exe", "lsaiso.exe", "vmmem", "vmmemwsl", "msmpeng.exe", "nissrv.exe", "sihost.exe",
                 "ctfmon.exe", "taskhostw.exe", "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
                 "textinputhost.exe", "shellexperiencehost.exe", "explorer.exe", "spoolsv.exe", "audiodg.exe",
                 "conhost.exe", "dllhost.exe", "wmiprvse.exe", "smartscreen.exe", "securityhealthservice.exe",
                 "securityhealthsystray.exe", "lockapp.exe", "widgets.exe", "searchindexer.exe", "wudfhost.exe"}


class ProcessMonitor:
    def __init__(self, top_n: int = 15) -> None:
        self.top_n = top_n
        self._ncpu = psutil.cpu_count() or 1
        self._prev: dict[tuple, float] = {}
        self._prev_t = time.monotonic()
        self._paths: dict[tuple, str] = {}   # (pid, create) → caminho (cache)
        self._session = current_session()
        self.last_raw: list[dict] = []

    def _classify(self, entries: list[ProcessEntry]) -> None:
        """Aplicativo / Segundo plano / Windows (mesma ideia do Gerenciador de Tarefas)."""
        windows = visible_windows()
        app_names = set()
        for e in entries:
            title = windows.get(e.pid)
            if title:
                e.title = title
                app_names.add(e.name.lower())
        for e in entries:
            low = e.name.lower()
            exe = e.exe.lower()
            if low in app_names and low not in ("explorer.exe", "applicationframehost.exe"):
                e.kind = "Aplicativo"
            elif e.title and low == "applicationframehost.exe":
                e.kind = "Aplicativo"   # janela de app da Store
            elif (e.session == 0 or low in _SYSTEM_NAMES or e.pid in (4,) or
                  (exe.startswith(_WINDOWS_DIR) and "\\systemapps\\" not in exe) or (not exe and e.session != self._session)):
                e.kind = "Windows"
            else:
                e.kind = "Segundo plano"

    def sample(self) -> ProcessSummary:
        now = time.monotonic()
        dt = max(now - self._prev_t, 1e-3)
        raw = query_processes()

        entries: list[ProcessEntry] = []
        cur: dict[tuple, float] = {}
        paths: dict[tuple, str] = {}
        total_threads = 0
        for p in raw:
            total_threads += p["threads"]
            if p["pid"] == 0:  # "Processo ocioso do sistema"
                continue
            key = (p["pid"], p["create"])
            cur[key] = p["cpu_time"]
            prev = self._prev.get(key)
            cpu = 0.0
            if prev is not None:
                cpu = max(0.0, (p["cpu_time"] - prev) / dt / self._ncpu * 100.0)
            # O caminho só é consultado uma vez por processo (cache por PID + horário de criação).
            exe = self._paths.get(key)
            if exe is None:
                exe = image_path(p["pid"]) if p["pid"] > 4 else ""
            paths[key] = exe
            name = p["name"] or ("System" if p["pid"] == 4 else "?")
            entries.append(ProcessEntry(pid=p["pid"], name=name, cpu=min(cpu, 100.0),
                                        memory=p["private_ws"], threads=p["threads"], ppid=p["ppid"],
                                        session=p["session"], create=p["create"], exe=exe,
                                        handles=p["handles"]))
        self._prev, self._prev_t = cur, now
        self._paths = paths
        self.last_raw = raw
        try:
            self._classify(entries)
        except Exception:
            log.exception("Falha ao classificar processos")

        apps: dict[str, ProcessEntry] = {}
        for e in entries:
            key = e.name.lower()
            a = apps.get(key)
            if a is None:
                apps[key] = ProcessEntry(pid=e.pid, name=e.name, cpu=e.cpu, memory=e.memory,
                                         threads=e.threads, count=1)
            else:
                a.cpu += e.cpu
                a.memory += e.memory
                a.threads += e.threads
                a.count += 1

        # Ordena por "peso": CPU tem prioridade, depois memória.
        app_list = sorted(apps.values(), key=lambda a: (a.cpu * 4e9) + a.memory, reverse=True)
        return ProcessSummary(
            total=len(raw),
            threads=total_threads,
            top_cpu=sorted(entries, key=lambda e: e.cpu, reverse=True)[: self.top_n],
            top_memory=sorted(entries, key=lambda e: e.memory, reverse=True)[: self.top_n],
            apps=app_list[:60],
            all=entries,
        )
