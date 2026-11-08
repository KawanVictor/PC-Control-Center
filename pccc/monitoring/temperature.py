"""Leitura de temperaturas com múltiplas fontes, da mais precisa para a mais genérica.

O Windows não expõe temperatura de CPU de forma padronizada. Ordem de tentativa:

1. LibreHardwareMonitor / OpenHardwareMonitor (se estiverem abertos, publicam sensores
   via WMI) — CPU, GPU e discos com precisão.
2. Zona térmica ACPI via contadores de desempenho — não exige administrador; em notebooks
   normalmente reflete a temperatura do processador.
3. MSFT_StorageReliabilityCounter — temperatura dos discos (exige administrador).
"""
from __future__ import annotations

import time
from typing import Any

from ..core.logger import get_logger
from ..core.winapi import is_admin
from .models import TemperatureSample

log = get_logger("temperature")

THERMAL_PDH = {
    "thermal_zone": r"\Thermal Zone Information(*)\High Precision Temperature",
}


class TemperatureMonitor:
    def __init__(self) -> None:
        import wmi  # importado aqui: precisa de CoInitialize já feito na thread
        self._wmi = wmi
        self._hw_ns: Any = None             # conexão WMI (sem tipos)
        self._hw_source = ""
        self._storage = None
        self._last_hw_probe = 0.0
        self._disk_temps: dict[str, float] = {}
        self._probe_hw_monitor()
        if is_admin():
            try:
                self._storage = wmi.WMI(namespace=r"root\Microsoft\Windows\Storage")
            except Exception as e:
                log.info("Storage WMI indisponível: %s", e)

    def _probe_hw_monitor(self) -> None:
        self._last_hw_probe = time.time()
        for ns, label in ((r"root\LibreHardwareMonitor", "LibreHardwareMonitor"),
                          (r"root\OpenHardwareMonitor", "OpenHardwareMonitor")):
            try:
                conn = self._wmi.WMI(namespace=ns)
                conn.Sensor(SensorType="Temperature")  # valida o acesso
                self._hw_ns, self._hw_source = conn, label
                log.info("Sensores via %s", label)
                return
            except Exception:
                continue
        self._hw_ns = None

    def _read_hw_monitor(self, out: TemperatureSample) -> bool:
        try:
            sensors = self._hw_ns.Sensor(SensorType="Temperature")
        except Exception:
            self._hw_ns = None  # programa foi fechado
            return False
        cpu_vals, gpu_vals = {}, {}
        for s in sensors:
            ident = (s.Identifier or "").lower()
            name = s.Name or ""
            val = float(s.Value or 0)
            if val <= 0:
                continue
            if "cpu" in ident:
                cpu_vals[name] = val
            elif "gpu" in ident:
                gpu_vals[name] = val
            elif any(k in ident for k in ("/hdd", "/nvme", "/ssd", "/storage")):
                out.disks[s.Parent or name] = val
        for pref in ("Core (Tctl/Tdie)", "CPU Package", "Core (Tdie)", "Core (Tctl)", "CPU Cores"):
            if pref in cpu_vals:
                out.cpu = cpu_vals[pref]
                break
        else:
            if cpu_vals:
                out.cpu = max(cpu_vals.values())
        for pref in ("GPU Core", "GPU Hot Spot"):
            if pref in gpu_vals:
                out.gpu = gpu_vals[pref]
                break
        else:
            if gpu_vals:
                out.gpu = max(gpu_vals.values())
        out.source = self._hw_source
        return out.cpu is not None or out.gpu is not None

    def refresh_disks(self) -> None:
        """Temperatura dos discos (cadência lenta; exige administrador)."""
        if self._storage is None:
            return
        try:
            names = {d.DeviceId: d.FriendlyName for d in self._storage.MSFT_PhysicalDisk()}
            temps = {}
            for r in self._storage.MSFT_StorageReliabilityCounter():
                if r.Temperature:
                    temps[names.get(r.DeviceId, r.DeviceId)] = float(r.Temperature)
            self._disk_temps = temps
        except Exception as e:
            log.debug("Temperatura de disco indisponível: %s", e)

    def sample(self, pdh: dict) -> TemperatureSample:
        out = TemperatureSample()
        if self._hw_ns is None and time.time() - self._last_hw_probe > 60:
            self._probe_hw_monitor()  # detecta se o usuário abriu o LibreHardwareMonitor
        if self._hw_ns is not None:
            self._read_hw_monitor(out)

        if out.cpu is None:
            zones = pdh.get("thermal_zone") or {}
            # Valor em décimos de Kelvin. Ignora leituras absurdas.
            temps = [v / 10 - 273.15 for v in zones.values() if v and 2731 < v < 3931]
            if temps:
                out.cpu = max(temps)
                out.source = out.source or "Zona térmica ACPI"

        for k, v in self._disk_temps.items():
            out.disks.setdefault(k, v)

        if out.cpu is None:
            out.hint = ("Temperatura indisponível neste hardware sem sensores dedicados. "
                        "Abra o LibreHardwareMonitor (como administrador) para leituras precisas.")
        elif out.gpu is None:
            out.hint = ("Temperatura da GPU: requer LibreHardwareMonitor aberto (AMD/Intel) "
                        "ou driver NVIDIA com nvidia-smi.")
        return out
