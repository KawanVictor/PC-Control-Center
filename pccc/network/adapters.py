"""Interfaces de rede via GetAdaptersAddresses (iphlpapi) — IPs, gateway, DNS, MAC, DHCP."""
from __future__ import annotations

import ctypes
import socket
from ctypes import wintypes

from ..core.logger import get_logger
from .models import InterfaceInfo

log = get_logger("adapters")

AF_UNSPEC, AF_INET, AF_INET6 = 0, 2, 23
GAA_FLAG_INCLUDE_GATEWAYS = 0x0080
ERROR_BUFFER_OVERFLOW = 111
IP_ADAPTER_DHCP_ENABLED = 0x4

_IFTYPE = {6: "Ethernet", 71: "Wi-Fi", 24: "Loopback", 131: "Túnel", 23: "PPP", 243: "Celular",
           244: "Celular"}


class SOCKET_ADDRESS(ctypes.Structure):
    _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int)]


class _ADDR_NODE(ctypes.Structure):
    """Cabeçalho comum às listas de endereços (unicast, DNS, gateway)."""


_ADDR_NODE._fields_ = [("Length", wintypes.ULONG), ("Flags", wintypes.DWORD),
                       ("Next", ctypes.POINTER(_ADDR_NODE)), ("Address", SOCKET_ADDRESS)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class IP_ADAPTER_ADDRESSES(ctypes.Structure):
    pass


IP_ADAPTER_ADDRESSES._fields_ = [
    ("Length", wintypes.ULONG), ("IfIndex", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
    ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.POINTER(_ADDR_NODE)),
    ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p),
    ("FirstDnsServerAddress", ctypes.POINTER(_ADDR_NODE)),
    ("DnsSuffix", ctypes.c_wchar_p),
    ("Description", ctypes.c_wchar_p),
    ("FriendlyName", ctypes.c_wchar_p),
    ("PhysicalAddress", ctypes.c_ubyte * 8),
    ("PhysicalAddressLength", wintypes.ULONG),
    ("Flags", wintypes.ULONG),
    ("Mtu", wintypes.ULONG),
    ("IfType", wintypes.ULONG),
    ("OperStatus", ctypes.c_int),
    ("Ipv6IfIndex", wintypes.DWORD),
    ("ZoneIndices", wintypes.ULONG * 16),
    ("FirstPrefix", ctypes.c_void_p),
    ("TransmitLinkSpeed", ctypes.c_ulonglong),
    ("ReceiveLinkSpeed", ctypes.c_ulonglong),
    ("FirstWinsServerAddress", ctypes.c_void_p),
    ("FirstGatewayAddress", ctypes.POINTER(_ADDR_NODE)),
    ("Ipv4Metric", wintypes.ULONG),
    ("Ipv6Metric", wintypes.ULONG),
    ("Luid", ctypes.c_ulonglong),
    ("Dhcpv4Server", SOCKET_ADDRESS),
    ("CompartmentId", wintypes.UINT),
    ("NetworkGuid", GUID),
    ("ConnectionType", ctypes.c_int),
    ("TunnelType", ctypes.c_int),
    ("Dhcpv6Server", SOCKET_ADDRESS),
    ("Dhcpv6ClientDuid", ctypes.c_ubyte * 130),
    ("Dhcpv6ClientDuidLength", wintypes.ULONG),
    ("Dhcpv6Iaid", wintypes.ULONG),
    ("FirstDnsSuffix", ctypes.c_void_p),
]

_iphlp = ctypes.WinDLL("iphlpapi")
_iphlp.GetAdaptersAddresses.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.POINTER(wintypes.ULONG)]
_iphlp.GetAdaptersAddresses.restype = wintypes.ULONG


def sockaddr_to_str(sa: SOCKET_ADDRESS) -> str:
    if not sa.lpSockaddr:
        return ""
    family = ctypes.c_ushort.from_address(sa.lpSockaddr).value
    if family == AF_INET:
        raw = ctypes.string_at(sa.lpSockaddr + 4, 4)
        return socket.inet_ntop(socket.AF_INET, raw)
    if family == AF_INET6:
        raw = ctypes.string_at(sa.lpSockaddr + 8, 16)
        scope = ctypes.c_ulong.from_address(sa.lpSockaddr + 24).value
        addr = socket.inet_ntop(socket.AF_INET6, raw)
        return f"{addr}%{scope}" if addr.lower().startswith("fe80") and scope else addr
    return ""


def _walk(node) -> list[str]:
    out: list[str] = []
    while node:
        s = sockaddr_to_str(node.contents.Address)
        if s and s not in out:
            out.append(s)
        node = node.contents.Next
    # IPv4 primeiro (mais legível); IPv6 em seguida
    return sorted(out, key=lambda ip: ":" in ip)


def list_interfaces() -> list[InterfaceInfo]:
    size = wintypes.ULONG(16 * 1024)
    for _ in range(4):
        buf = ctypes.create_string_buffer(size.value)
        rc = _iphlp.GetAdaptersAddresses(AF_UNSPEC, GAA_FLAG_INCLUDE_GATEWAYS, None, buf, ctypes.byref(size))
        if rc == ERROR_BUFFER_OVERFLOW:
            continue
        if rc != 0:
            log.warning("GetAdaptersAddresses falhou: %s", rc)
            return []
        break
    else:
        return []

    result: list[InterfaceInfo] = []
    p = ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_ADDRESSES))
    while p:
        a = p.contents
        desc = a.Description or ""
        kind = _IFTYPE.get(a.IfType, "Outro")
        low = desc.lower()
        if "bluetooth" in low:
            kind = "Bluetooth"
        elif kind in ("Ethernet", "Wi-Fi") and any(
                k in low for k in ("virtual", "hyper-v", "vmware", "virtualbox", "tap-", "wireguard", "vpn",
                                   "loopback", "wsl", "wi-fi direct", "direct virtual")):
            kind = "Virtual"
        unicast = _walk(a.FirstUnicastAddress)
        mac_len = min(a.PhysicalAddressLength, 8)
        info = InterfaceInfo(
            name=a.FriendlyName or "",
            description=desc,
            kind=kind,
            up=a.OperStatus == 1,
            mac="-".join(f"{b:02X}" for b in a.PhysicalAddress[:mac_len]) if mac_len else "",
            ipv4=[ip for ip in unicast if "." in ip and ":" not in ip],
            ipv6=[ip for ip in unicast if ":" in ip],
            gateways=_walk(a.FirstGatewayAddress),
            dns=_walk(a.FirstDnsServerAddress),
            dhcp=bool(a.Flags & IP_ADAPTER_DHCP_ENABLED),
            dhcp_server=sockaddr_to_str(a.Dhcpv4Server),
            dns_suffix=a.DnsSuffix or "",
            link_mbps=(a.ReceiveLinkSpeed / 1e6) if a.ReceiveLinkSpeed and a.ReceiveLinkSpeed < 2 ** 63 else 0.0,
            mtu=a.Mtu,
            metric=a.Ipv4Metric,
        )
        result.append(info)
        p = a.Next
    return result


def pick_active(interfaces: list[InterfaceInfo]) -> InterfaceInfo | None:
    """Interface ativa = ligada, com gateway IPv4 e menor métrica (a rota padrão do Windows)."""
    candidates = [i for i in interfaces if i.up and i.kind != "Loopback" and
                  any("." in g for g in i.gateways)]
    if not candidates:
        candidates = [i for i in interfaces if i.up and i.is_physical and i.ipv4]
    if not candidates:
        return None
    return min(candidates, key=lambda i: (not i.is_physical, i.metric or 9999))
