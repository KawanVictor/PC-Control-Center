"""Formatação de valores para exibição (pt-BR)."""
from __future__ import annotations


def fmt_bytes(n: float | None, decimals: int = 1) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            if unit == "B":
                return f"{n:.0f} B"
            return f"{n:.{decimals}f} {unit}".replace(".", ",")
        n /= 1024
    return f"{n:.1f} TB"


def fmt_rate(bps: float | None) -> str:
    """Bytes por segundo → texto (ex.: '1,2 MB/s')."""
    if bps is None:
        return "—"
    return fmt_bytes(bps, 1 if bps >= 1024 else 0) + "/s"


def fmt_bits(bps: float | None) -> str:
    """Bytes por segundo → megabits por segundo (padrão de velocidade de internet)."""
    if bps is None:
        return "—"
    mbps = bps * 8 / 1_000_000
    if mbps < 1:
        return f"{bps * 8 / 1000:.0f} Kbps"
    return f"{mbps:.1f} Mbps".replace(".", ",")


def fmt_pct(v: float | None, decimals: int = 0) -> str:
    return "—" if v is None else f"{v:.{decimals}f}%".replace(".", ",")


def fmt_temp(v: float | None) -> str:
    return "N/D" if v is None else f"{v:.0f} °C"


def fmt_mhz(v: float | None) -> str:
    if not v:
        return "—"
    return f"{v / 1000:.2f} GHz".replace(".", ",") if v >= 1000 else f"{v:.0f} MHz"


def fmt_uptime(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return f"{d}d {h:02d}h {m:02d}min"
    return f"{h:02d}:{m:02d}:{s:02d}"
