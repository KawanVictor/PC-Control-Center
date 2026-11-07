"""Monitor de CPU: uso total, por núcleo e frequência real."""
from __future__ import annotations

import winreg

import psutil

from .models import CpuSample


def _registry_cpu() -> tuple[str, float]:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            name = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
            mhz = float(winreg.QueryValueEx(k, "~MHz")[0])
            return " ".join(name.split()), mhz
    except OSError:
        return "Processador", 0.0


class CpuMonitor:
    def __init__(self) -> None:
        self.name, reg_mhz = _registry_cpu()
        self.cores = psutil.cpu_count(logical=False) or 0
        self.threads = psutil.cpu_count(logical=True) or 0
        freq = psutil.cpu_freq()
        self.base_mhz = (freq.max if freq and freq.max else 0) or reg_mhz
        # Primeira chamada apenas inicializa a referência de tempo do psutil.
        psutil.cpu_percent(percpu=True)

    def sample(self, perf_percent: float | None, pdh_freq: float | None) -> CpuSample:
        per_core = psutil.cpu_percent(percpu=True)
        total = sum(per_core) / len(per_core) if per_core else 0.0

        # Frequência real = base × "% Processor Performance" (igual ao Gerenciador de
        # Tarefas). psutil sozinho retorna apenas o clock base no Windows.
        base = pdh_freq or self.base_mhz
        if perf_percent and base:
            freq = base * perf_percent / 100.0
        else:
            f = psutil.cpu_freq()
            freq = f.current if f else 0.0

        return CpuSample(name=self.name, cores=self.cores, threads=self.threads,
                         percent=total, per_core=per_core, freq_mhz=freq, base_mhz=base)
