"""Monitor de GPU independente de fabricante (AMD, Intel, NVIDIA).

* Lista de placas, nome e VRAM total: DXGI (a mesma API usada pelos jogos).
* Uso por engine e VRAM em uso: contadores "GPU Engine" e "GPU Adapter Memory" —
  exatamente o método do Gerenciador de Tarefas.
* Temperatura: nvidia-smi (NVIDIA) ou sensores externos (ver temperature.py).
"""
from __future__ import annotations

import ctypes
import re
import shutil
from collections import defaultdict
from ctypes import wintypes

from ..core.logger import get_logger
from ..core.winapi import run_hidden
from .models import GpuSample

log = get_logger("gpu")


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.UINT), ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", _LUID),
        ("Flags", wintypes.UINT),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


# IID_IDXGIFactory1 = {770aae78-f26f-4dba-a829-253c83d1b387}
_IID_FACTORY1 = _GUID(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))


def _vcall(obj, index, restype, *argtypes):
    """Chama o método ``index`` da vtable de um objeto COM."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn


def enumerate_adapters() -> list[dict]:
    """Lista placas de vídeo físicas via DXGI (ignora o 'Microsoft Basic Render')."""
    adapters: list[dict] = []
    try:
        dxgi = ctypes.windll.dxgi
        factory = ctypes.c_void_p()
        if dxgi.CreateDXGIFactory1(ctypes.byref(_IID_FACTORY1), ctypes.byref(factory)) != 0:
            return adapters
        i = 0
        while True:
            adapter = ctypes.c_void_p()
            # IDXGIFactory1::EnumAdapters1 = índice 12 da vtable
            hr = _vcall(factory, 12, ctypes.c_long, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(
                factory, i, ctypes.byref(adapter))
            if hr != 0:
                break
            desc = _DXGI_ADAPTER_DESC1()
            # IDXGIAdapter1::GetDesc1 = índice 10
            _vcall(adapter, 10, ctypes.c_long, ctypes.POINTER(_DXGI_ADAPTER_DESC1))(adapter, ctypes.byref(desc))
            _vcall(adapter, 2, ctypes.c_ulong)(adapter)  # Release
            if not desc.Flags & 0x2:  # DXGI_ADAPTER_FLAG_SOFTWARE
                luid = f"luid_0x{desc.AdapterLuid.HighPart & 0xFFFFFFFF:08x}_0x{desc.AdapterLuid.LowPart:08x}"
                adapters.append({
                    "name": desc.Description.strip(),
                    "luid": luid,
                    "dedicated": int(desc.DedicatedVideoMemory),
                    "shared": int(desc.SharedSystemMemory),
                    "vendor": desc.VendorId,
                })
            i += 1
        _vcall(factory, 2, ctypes.c_ulong)(factory)
    except Exception as e:
        log.warning("DXGI indisponível: %s", e)
    return adapters


_ENGINE_RE = re.compile(r"(luid_0x[0-9a-f]+_0x[0-9a-f]+)_phys_(\d+)_eng_(\d+)_engtype_(.*)$", re.I)
_LUID_RE = re.compile(r"(luid_0x[0-9a-f]+_0x[0-9a-f]+)", re.I)


class GpuMonitor:
    PDH_COUNTERS = {
        "gpu_engine": r"\GPU Engine(*)\Utilization Percentage",
        "gpu_dedicated": r"\GPU Adapter Memory(*)\Dedicated Usage",
        "gpu_shared": r"\GPU Adapter Memory(*)\Shared Usage",
    }

    def __init__(self) -> None:
        self.adapters = enumerate_adapters()
        self._nvidia_smi = shutil.which("nvidia-smi")
        self._nv_temps: dict[str, float] = {}

    def refresh_nvidia(self) -> None:
        """Lê temperaturas NVIDIA (chamado na cadência lenta, é um processo externo)."""
        if not self._nvidia_smi:
            return
        try:
            out = run_hidden([self._nvidia_smi, "--query-gpu=name,temperature.gpu",
                              "--format=csv,noheader,nounits"], timeout=5)
            temps = {}
            for line in out.strip().splitlines():
                name, _, temp = line.rpartition(",")
                temps[name.strip().lower()] = float(temp)
            self._nv_temps = temps
        except Exception as e:
            log.debug("nvidia-smi falhou: %s", e)

    def sample(self, pdh: dict) -> list[GpuSample]:
        engines = pdh.get("gpu_engine") or {}
        dedicated = pdh.get("gpu_dedicated") or {}
        shared = pdh.get("gpu_shared") or {}

        # Soma o uso de todos os processos por engine física; o uso da GPU é o da engine
        # mais ocupada (mesma regra do Gerenciador de Tarefas).
        per_engine: dict[tuple, float] = defaultdict(float)
        for inst, val in engines.items():
            m = _ENGINE_RE.search(inst)
            if m:
                per_engine[(m.group(1).lower(), m.group(2), m.group(3), m.group(4))] += val

        def by_luid(table: dict) -> dict[str, float]:
            out: dict[str, float] = defaultdict(float)
            for inst, val in table.items():
                m = _LUID_RE.search(inst)
                if m:
                    out[m.group(1).lower()] += val
            return out

        ded_by = by_luid(dedicated)
        sh_by = by_luid(shared)

        samples = []
        for a in self.adapters:
            types: dict[str, float] = defaultdict(float)
            for (luid, _phys, _eng, etype), val in per_engine.items():
                if luid == a["luid"]:
                    types[etype] = max(types[etype], min(val, 100.0))
            temp = None
            for nv_name, t in self._nv_temps.items():
                if nv_name in a["name"].lower() or a["name"].lower() in nv_name:
                    temp = t
            samples.append(GpuSample(
                name=a["name"], luid=a["luid"],
                percent=max(types.values()) if types else 0.0,
                engines=dict(types),
                dedicated_used=int(ded_by.get(a["luid"], 0)),
                dedicated_total=a["dedicated"],
                shared_used=int(sh_by.get(a["luid"], 0)),
                shared_total=a["shared"],
                temperature=temp,
            ))
        return samples
