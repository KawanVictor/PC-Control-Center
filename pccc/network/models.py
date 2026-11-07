"""Estruturas de dados do módulo de rede."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WifiInfo:
    available: bool = False          # existe placa Wi-Fi?
    connected: bool = False
    state: str = ""                  # Conectado, Desconectado, Associando...
    ssid: str = ""
    bssid: str = ""
    profile: str = ""
    signal: int = 0                  # 0–100 (%)
    rssi: Optional[int] = None       # dBm
    channel: Optional[int] = None
    band: str = ""                   # 2,4 GHz / 5 GHz / 6 GHz
    standard: str = ""               # Wi-Fi 4/5/6/7
    security: str = ""
    rx_mbps: float = 0.0             # taxa do link negociada
    tx_mbps: float = 0.0
    adapter: str = ""
    error: str = ""                  # motivo quando algo não pôde ser lido


@dataclass
class InterfaceInfo:
    name: str                        # nome amigável ("Wi-Fi", "Ethernet")
    description: str = ""
    kind: str = ""                   # Wi-Fi, Ethernet, Virtual, Loopback...
    up: bool = False
    mac: str = ""
    ipv4: list[str] = field(default_factory=list)
    ipv6: list[str] = field(default_factory=list)
    gateways: list[str] = field(default_factory=list)
    dns: list[str] = field(default_factory=list)
    dhcp: bool = False
    dhcp_server: str = ""
    dns_suffix: str = ""
    link_mbps: float = 0.0
    mtu: int = 0
    metric: int = 0
    down_bps: float = 0.0
    up_bps: float = 0.0
    total_recv: int = 0
    total_sent: int = 0

    @property
    def is_physical(self) -> bool:
        return self.kind in ("Wi-Fi", "Ethernet")


@dataclass
class PingStats:
    target: str = ""
    last_ms: Optional[float] = None
    avg_ms: Optional[float] = None
    min_ms: Optional[float] = None
    max_ms: Optional[float] = None
    jitter_ms: Optional[float] = None
    loss_pct: float = 0.0
    sent: int = 0
    history: list[float] = field(default_factory=list)   # NaN = pacote perdido


@dataclass
class NetEvent:
    ts: float
    kind: str        # wifi_down, wifi_up, internet_down, internet_up, ip_change
    message: str


@dataclass
class UsageTotals:
    today_rx: int = 0
    today_tx: int = 0
    week_rx: int = 0
    week_tx: int = 0
    month_rx: int = 0
    month_tx: int = 0
    daily: list[tuple[str, int, int]] = field(default_factory=list)  # (dia, rx, tx)


@dataclass
class NetworkSnapshot:
    ts: float = 0.0
    status: str = "unknown"          # online, no_internet, offline
    active: Optional[InterfaceInfo] = None
    interfaces: list[InterfaceInfo] = field(default_factory=list)
    wifi: WifiInfo = field(default_factory=WifiInfo)
    ping_internet: PingStats = field(default_factory=PingStats)
    ping_gateway: PingStats = field(default_factory=PingStats)
    stability: int = 100             # 0–100
    stability_label: str = ""
    drops_24h: int = 0
    events: list[NetEvent] = field(default_factory=list)
    usage: UsageTotals = field(default_factory=UsageTotals)
    down_bps: float = 0.0            # tráfego total (todas as interfaces físicas)
    up_bps: float = 0.0
