"""Monitor de memória física e virtual."""
from __future__ import annotations

import psutil

from .models import MemorySample


def sample_memory(pdh: dict) -> MemorySample:
    vm = psutil.virtual_memory()
    try:
        sw = psutil.swap_memory()
        swap_total, swap_used, swap_pct = sw.total, sw.used, sw.percent
    except Exception:
        swap_total = swap_used = 0
        swap_pct = 0.0
    return MemorySample(
        total=vm.total,
        used=vm.total - vm.available,
        available=vm.available,
        percent=vm.percent,
        commit_used=int(pdh.get("commit_used") or 0),
        commit_limit=int(pdh.get("commit_limit") or 0),
        cached=int(pdh.get("cache") or 0),
        swap_total=swap_total,
        swap_used=swap_used,
        swap_percent=swap_pct,
    )
