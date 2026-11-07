"""Aparelhos conectados à sua rede local (celulares, TVs, consoles, PCs, impressoras...).

Como descobre (sem administrador, só na SUA rede — a faixa da interface ativa, no máximo
1024 endereços):

1. **ARP** (``SendARP``): pergunta "quem tem o IP x?" para cada endereço da rede. Todo aparelho
   conectado precisa responder — é assim que a rede local funciona. Revela IP e MAC.
2. **Nome:** DNS reverso (o roteador costuma saber o nome que cada aparelho informou ao
   pedir IP), NetBIOS (PCs Windows) e UPnP/SSDP (TVs, TV Box, consoles e roteadores anunciam
   nome e modelo).
3. **Fabricante:** pelos 3 primeiros bytes do MAC, na lista pública de fabricantes (IEEE, via
   Wireshark), baixada uma vez para %LOCALAPPDATA%\\PCControlCenter\\cache.

Nada além disso: não há varredura de portas nem tentativa de acesso aos aparelhos.
Celulares modernos usam "endereço privado" (MAC aleatório por rede) — nesse caso o
fabricante não pode ser identificado e o app avisa.
"""
from __future__ import annotations

import ctypes
import ipaddress
import os
import re
import socket
import struct
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

from ..core.logger import get_logger, log_operation

log = get_logger("lan")

MAX_HOSTS = 1024
MANUF_URL = "https://www.wireshark.org/download/automated/data/manuf"
MANUF_MAX_AGE = 120 * 86400
_iphlp = ctypes.windll.iphlpapi


@dataclass
class LanDevice:
    ip: str
    mac: str
    name: str = ""                 # nome informado pelo aparelho (DNS/NetBIOS/UPnP)
    vendor: str = ""
    model: str = ""                # UPnP: modelo/descrição
    kind: str = ""                 # tipo provável (Roteador, Celular, TV...)
    glyph: str = ""
    is_self: bool = False
    is_gateway: bool = False
    randomized: bool = False       # MAC privado/aleatório (celulares)
    online: bool = True
    custom_name: str = ""          # nome dado pelo usuário
    known: bool = False            # marcado pelo usuário como "conhecido"
    first_seen: float = 0.0
    last_seen: float = 0.0
    hints: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.custom_name or self.name or self.model or self.kind or self.ip


# ------------------------------------------------------------------ rede local
@dataclass
class LocalNet:
    iface: str
    ip: str
    network: ipaddress.IPv4Network
    gateway: str
    mac: str
    ssid: str = ""


def local_network() -> LocalNet | None:
    import psutil
    from .adapters import list_interfaces, pick_active
    act = pick_active(list_interfaces())
    if act is None or not act.ipv4:
        return None
    ip = act.ipv4[0]
    mask = None
    for a in psutil.net_if_addrs().get(act.name, []):
        if a.family == socket.AF_INET and a.address == ip:
            mask = a.netmask
    net = ipaddress.IPv4Network(f"{ip}/{mask or '255.255.255.0'}", strict=False)
    if net.num_addresses > MAX_HOSTS:          # redes enormes (empresas): só a /24 em volta deste PC
        net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
    gw = next((g for g in act.gateways if "." in g), "")
    return LocalNet(act.name, ip, net, gw, act.mac.replace(":", "-").upper())


def _mac_str(raw: bytes) -> str:
    return "-".join(f"{b:02X}" for b in raw)


def is_randomized(mac: str) -> bool:
    """Bit "administrado localmente" ligado = MAC privado/aleatório (Android/iOS/Windows)."""
    try:
        return bool(int(mac.split("-")[0], 16) & 0x02)
    except (ValueError, IndexError):
        return False


class _MIB_IPNETROW(ctypes.Structure):
    _fields_ = [("dwIndex", wintypes.DWORD), ("dwPhysAddrLen", wintypes.DWORD), ("bPhysAddr", ctypes.c_ubyte * 8),
                ("dwAddr", wintypes.DWORD), ("dwType", wintypes.DWORD)]


def arp_table(net: ipaddress.IPv4Network) -> dict[str, str]:
    """Vizinhos que o Windows já conhece (sem enviar nada)."""
    size = wintypes.ULONG(0)
    _iphlp.GetIpNetTable(None, ctypes.byref(size), False)
    if not size.value:
        return {}
    buf = ctypes.create_string_buffer(size.value)
    if _iphlp.GetIpNetTable(buf, ctypes.byref(size), False) != 0:
        return {}
    n = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0]
    rows = ctypes.cast(ctypes.addressof(buf) + 4, ctypes.POINTER(_MIB_IPNETROW * n)).contents
    out = {}
    for r in rows:
        ip = socket.inet_ntoa(struct.pack("<I", r.dwAddr))
        mac = _mac_str(bytes(r.bPhysAddr[:r.dwPhysAddrLen]))
        if r.dwType == 3 and _valid(ip, mac, net):       # 3 = dinâmico (aparelho real)
            out[ip] = mac
    return out


def _valid(ip: str, mac: str, net: ipaddress.IPv4Network) -> bool:
    a = ipaddress.IPv4Address(ip)
    return (a in net and a not in (net.network_address, net.broadcast_address) and len(mac) == 17
            and mac not in ("00-00-00-00-00-00", "FF-FF-FF-FF-FF-FF") and not mac.startswith("01-00-5E"))


def send_arp(ip: str) -> str | None:
    mac = (ctypes.c_ulong * 2)()
    ln = wintypes.ULONG(6)
    dest = struct.unpack("<I", socket.inet_aton(ip))[0]
    if _iphlp.SendARP(dest, 0, ctypes.byref(mac), ctypes.byref(ln)) == 0 and ln.value == 6:
        return _mac_str(bytes(mac)[:6])
    return None


# --------------------------------------------------------------- fabricantes
def _cache_dir() -> Path:
    d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PCControlCenter" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


_VENDOR_CLEAN = re.compile(r"[,.]?\s*(co\.?,?\s*ltd\.?|corporation|corporate|corp\.?|inc\.?|incorporated|ltd\.?|"
                           r"limited|ltda\.?|gmbh|s\.?a\.?|technology|technologies|electronics|international|"
                           r"communications?|holding|industria e comercio.*)\s*$", re.I)
_vendors: dict[str, str] | None = None
_vendors_long: list[tuple[int, int, str]] = []      # (prefixo, bits, nome) para faixas /28 e /36


def _clean_vendor(name: str) -> str:
    name = name.strip()
    for _ in range(3):
        new = _VENDOR_CLEAN.sub("", name).strip(" ,.")
        if new == name:
            break
        name = new
    name = re.sub(r"^(Shenzhen|Guangdong|Hangzhou|Beijing|Shanghai)\s+", "", name, flags=re.I)
    return name[:40] or "?"


def manuf_file() -> Path:
    return _cache_dir() / "manuf.txt"


def update_vendor_list(force: bool = False) -> bool:
    """Baixa a lista de fabricantes (≈3 MB) se não existir ou tiver mais de 120 dias."""
    global _vendors
    f = manuf_file()
    if f.exists() and not force and time.time() - f.stat().st_mtime < MANUF_MAX_AGE:
        return True
    req = urllib.request.Request(MANUF_URL, headers={"User-Agent": "Mozilla/5.0 PCControlCenter/1.2"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if urllib.parse.urlparse(r.geturl()).hostname != "www.wireshark.org":
            raise ValueError("Redirecionamento inesperado")
        data = r.read(15_000_000)
    if b"\t" not in data[:5000]:
        raise ValueError("Lista de fabricantes inválida")
    tmp = f.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, f)
    _vendors = None
    log_operation("lan.vendors", f"lista de fabricantes atualizada ({len(data) / 1e6:.1f} MB)")
    return True


def _load_vendors() -> dict[str, str]:
    global _vendors, _vendors_long
    if _vendors is not None:
        return _vendors
    _vendors, _vendors_long = {}, []
    try:
        text = manuf_file().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _vendors
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 2:
            continue
        key, name = parts[0].upper(), parts[2] if len(parts) > 2 and parts[2] else parts[1]
        if "/" in key:
            hexs, bits = key.split("/")
            try:
                _vendors_long.append((int(hexs.replace(":", "").ljust(12, "0"), 16), int(bits), _clean_vendor(name)))
            except ValueError:
                pass
        elif len(key) == 8:
            _vendors[key.replace(":", "-")] = _clean_vendor(name)
    return _vendors


def vendor(mac: str) -> str:
    if is_randomized(mac):
        return ""
    v = _load_vendors()
    if _vendors_long:
        n = int(mac.replace("-", ""), 16)
        for prefix, bits, name in _vendors_long:
            if n >> (48 - bits) == prefix >> (48 - bits):
                return name
    return v.get(mac[:8], "")


# --------------------------------------------------------------------- nomes
def reverse_dns(ip: str) -> str:
    try:
        name = socket.gethostbyaddr(ip)[0]
    except OSError:
        return ""
    return "" if name == ip else name.split(".")[0]


def netbios_name(ip: str, timeout: float = 0.8) -> str:
    q = struct.pack(">HHHHHH", 0x5043, 0, 1, 0, 0, 0) + b"\x20CK" + b"A" * 30 + b"\x00" + struct.pack(">HH", 0x21, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        try:
            s.sendto(q, (ip, 137))
            d, _ = s.recvfrom(2048)
        except OSError:
            return ""
    try:
        n = d[56]
        for i in range(n):
            raw = d[57 + i * 18:57 + i * 18 + 18]
            name, suffix, flags = raw[:15].decode("ascii", "replace").strip(), raw[15], raw[16]
            if suffix == 0 and not flags & 0x80:      # nome do computador (não de grupo)
                return name
    except IndexError:
        pass
    return ""


def _private(ip: str) -> bool:
    try:
        return ipaddress.IPv4Address(ip).is_private
    except ValueError:
        return False


def ssdp_discover(local_ip: str, net: ipaddress.IPv4Network, seconds: float = 3.0) -> dict[str, dict]:
    """UPnP: {ip: {"name", "model", "maker", "type", "server"}} dos aparelhos que se anunciam."""
    found: dict[str, dict] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(0.4)
        try:
            s.bind((local_ip, 0))
            msg = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\n'
                   "MX: 2\r\nST: ssdp:all\r\n\r\n").encode()
            s.sendto(msg, ("239.255.255.250", 1900))
        except OSError:
            return found
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                data, (ip, _port) = s.recvfrom(4096)
            except OSError:
                continue
            if ipaddress.IPv4Address(ip) not in net:
                continue
            info = found.setdefault(ip, {"locations": set(), "server": ""})
            for line in data.decode("utf-8", "replace").split("\r\n"):
                k, _, v = line.partition(":")
                if k.strip().lower() == "location":
                    info["locations"].add(v.strip())
                elif k.strip().lower() == "server":
                    info["server"] = v.strip()[:80]
    for ip, info in found.items():
        for loc in list(info.pop("locations"))[:3]:
            u = urllib.parse.urlparse(loc)
            # só busca a descrição no PRÓPRIO aparelho que respondeu (endereço privado da rede local)
            if u.scheme != "http" or u.hostname != ip or not _private(ip):
                continue
            try:
                with urllib.request.urlopen(loc, timeout=2) as r:
                    server = r.headers.get("Server", "")
                    xml = r.read(65536).decode("utf-8", "replace")
            except Exception:     # noqa: BLE001
                continue
            info["server"] = info["server"] or server[:80]
            for key, tag in (("name", "friendlyName"), ("model", "modelName"), ("maker", "manufacturer"),
                             ("type", "deviceType")):
                m = re.search(rf"<{tag}>\s*([^<]{{1,120}}?)\s*</{tag}>", xml)
                if m and not info.get(key):
                    info[key] = m.group(1)
            if info.get("name"):
                break
    return found


# ------------------------------------------------------------- classificação
_KINDS = [  # (palavras em nome/fabricante/modelo/servidor, tipo, glifo)
    (("playstation", "sony interactive", "nintendo", "xbox"), "Console de videogame", ""),
    (("printer", "impressora", "epson", "brother", "canon", "laserjet", "deskjet", "officejet", "kyocera",
      "xerox", "lexmark"), "Impressora", ""),
    (("nrdp", "netflix", "mediarenderer", "smart tv", "smarttv", "roku", "chromecast", "android tv", "fire tv",
      "skyworth", "tcl", "hisense", "philco", "aoc", "semp", "multilaser", "tv box", "tvbox", "webos", "tizen",
      "bravia", "dial"), "TV / TV Box", ""),
    (("echo", "alexa", "google home", "nest", "sonos", "homepod"), "Assistente / caixa de som", ""),
    (("amazon",), "Amazon (Echo, Fire TV ou Kindle)", ""),
    (("espressif", "tuya", "shelly", "sonoff", "broadlink", "positivo casa", "intelbras mibo", "ezviz", "hikvision",
      "camera", "câmera", "ipcam"), "Casa inteligente / câmera", ""),
    (("iphone", "ipad", "android", "galaxy", "redmi", "xiaomi", "poco", "motorola", "moto ", "samsung",
      "huawei", "oppo", "realme", "oneplus", "vivo mobile", "lg electronics", "nokia", "zte"),
     "Celular / tablet", ""),
    (("apple",), "Apple (iPhone, iPad ou Mac)", ""),
    (("intel", "realtek", "azurewave", "liteon", "lite-on", "hon hai", "foxconn", "qualcomm atheros", "dell",
      "lenovo", "asustek", "hewlett", "hp inc", "acer", "micro-star", "msi", "gigabyte", "desktop", "laptop",
      "notebook", "-pc", "pc-"), "Computador / notebook", ""),
]


def classify(d: LanDevice) -> None:
    if d.is_self:
        d.kind, d.glyph = "Este computador", ""
        return
    if d.is_gateway:
        d.kind, d.glyph = "Roteador / modem", ""
        return
    text = " ".join([d.name, d.vendor, d.model, *d.hints]).lower()
    for words, kind, glyph in _KINDS:
        if any(w in text for w in words):
            d.kind, d.glyph = kind, glyph
            return
    if d.randomized:
        d.kind, d.glyph = "Celular / tablet (endereço privado)", ""
    else:
        d.kind, d.glyph = "Aparelho desconhecido", ""


# --------------------------------------------------------------------- busca
def scan(progress=None) -> tuple[LocalNet, list[LanDevice]]:
    """Procura os aparelhos da rede local. ``progress(texto)`` é chamado durante a busca."""
    from ..core.com import ensure_com
    ensure_com()
    ln = local_network()
    if ln is None:
        raise RuntimeError("Sem conexão de rede local.")
    say = progress or (lambda _t: None)
    try:
        update_vendor_list()
    except Exception as e:     # noqa: BLE001 — sem a lista, só não mostra o fabricante
        log.info("Lista de fabricantes indisponível: %s", e)
    hosts = [str(h) for h in ln.network.hosts()][:MAX_HOSTS]
    say(f"Procurando em {ln.network} ({len(hosts)} endereços)...")
    found = arp_table(ln.network)
    t = time.monotonic()
    # uma "onda" só: cada pergunta ARP sem resposta leva ~3 s, então todas vão ao mesmo tempo
    pool = ThreadPoolExecutor(max_workers=min(256, len(hosts) + 4), thread_name_prefix="pccc-lan")
    ssdp_future = pool.submit(ssdp_discover, ln.ip, ln.network)
    try:
        for ip, mac in zip(hosts, pool.map(send_arp, hosts)):
            if mac and _valid(ip, mac, ln.network):
                found[ip] = mac
        say(f"{len(found)} aparelho(s) respondendo — identificando nomes...")
        ips = list(found)
        fdns = {ip: pool.submit(reverse_dns, ip) for ip in ips}
        fnb = {ip: pool.submit(netbios_name, ip) for ip in ips}
        wait(list(fdns.values()) + list(fnb.values()) + [ssdp_future], timeout=6)

        def got(fut, default):
            return fut.result() if fut.done() and not fut.exception() else default

        dns = {ip: got(f, "") for ip, f in fdns.items()}
        nb = {ip: n for ip, f in fnb.items() if (n := got(f, ""))}
        upnp = got(ssdp_future, {})
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    now = time.time()
    devices = []
    for ip, mac in sorted(found.items(), key=lambda kv: ipaddress.IPv4Address(kv[0])):
        u = upnp.get(ip, {})
        d = LanDevice(ip=ip, mac=mac, randomized=is_randomized(mac), is_self=ip == ln.ip,
                      is_gateway=ip == ln.gateway, last_seen=now, first_seen=now)
        d.name = nb.get(ip) or dns.get(ip) or u.get("name", "")
        d.model = " ".join(x for x in (u.get("maker", ""), u.get("model", "")) if x)[:60]
        d.vendor = vendor(mac)
        d.hints = [u.get("server", ""), u.get("type", "")]
        classify(d)
        devices.append(d)
    log_operation("lan.scan", f"{ln.network}: {len(devices)} aparelho(s) em {time.monotonic() - t:.1f} s")
    return ln, devices


# ----------------------------------------------------------------- histórico
_SCHEMA = """
CREATE TABLE IF NOT EXISTS lan_devices (
    network TEXT NOT NULL,          -- MAC do roteador (separa redes diferentes: casa, trabalho...)
    mac TEXT NOT NULL,
    ip TEXT, name TEXT, vendor TEXT, model TEXT, kind TEXT,
    custom_name TEXT DEFAULT '', known INTEGER DEFAULT 0,
    first_seen REAL, last_seen REAL,
    PRIMARY KEY (network, mac)
);
"""


def _db():
    from ..core.database import Database
    db = Database.instance()
    if not getattr(db, "_lan_ready", False):
        with db._lock:
            db._conn.executescript(_SCHEMA)
            db._conn.commit()
        db._lan_ready = True
    return db


def network_id(ln: LocalNet, devices: list[LanDevice]) -> str:
    gw = next((d.mac for d in devices if d.is_gateway), "")
    return gw or f"{ln.network}"


def merge(ln: LocalNet, devices: list[LanDevice]) -> tuple[list[LanDevice], list[LanDevice]]:
    """Grava a busca no histórico. Retorna (todos os aparelhos já vistos nesta rede, novos)."""
    db = _db()
    net = network_id(ln, devices)
    with db._lock:
        rows = db._conn.execute("SELECT mac, ip, name, vendor, model, kind, custom_name, known, first_seen, last_seen "
                                "FROM lan_devices WHERE network = ?", (net,)).fetchall()
        known = {r[0]: r for r in rows}
        had_history = bool(rows)
        new = []
        for d in devices:
            r = known.get(d.mac)
            if r is None:
                if had_history and not d.is_self:
                    new.append(d)
            else:
                d.first_seen = r[8] or d.first_seen
                d.custom_name, d.known = r[6] or "", bool(r[7])
                d.name = d.name or r[2] or ""
                d.model = d.model or r[4] or ""
            db._conn.execute(
                "INSERT INTO lan_devices (network, mac, ip, name, vendor, model, kind, first_seen, last_seen) "
                "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(network, mac) DO UPDATE SET ip=excluded.ip, "
                "name=CASE WHEN excluded.name <> '' THEN excluded.name ELSE name END, vendor=excluded.vendor, "
                "model=CASE WHEN excluded.model <> '' THEN excluded.model ELSE model END, kind=excluded.kind, "
                "last_seen=excluded.last_seen",
                (net, d.mac, d.ip, d.name, d.vendor, d.model, d.kind, d.first_seen, d.last_seen))
            if d.is_self or d.is_gateway:
                d.known = True
        db._conn.commit()
        online = {d.mac for d in devices}
        out = list(devices)
        for mac, r in known.items():
            if mac not in online:
                off = LanDevice(ip=r[1] or "", mac=mac, name=r[2] or "", vendor=r[3] or "", model=r[4] or "",
                                custom_name=r[6] or "", known=bool(r[7]), first_seen=r[8] or 0, last_seen=r[9] or 0,
                                online=False, randomized=is_randomized(mac))
                classify(off)
                out.append(off)
    return out, new


def set_custom(network: str, mac: str, custom_name: str | None = None, known: bool | None = None) -> None:
    db = _db()
    with db._lock:
        if custom_name is not None:
            db._conn.execute("UPDATE lan_devices SET custom_name = ? WHERE network = ? AND mac = ?",
                             (custom_name.strip()[:60], network, mac))
        if known is not None:
            db._conn.execute("UPDATE lan_devices SET known = ? WHERE network = ? AND mac = ?",
                             (1 if known else 0, network, mac))
        db._conn.commit()
    log_operation("lan.device", f"{mac}: nome={custom_name!r} conhecido={known}")


def forget(network: str, mac: str) -> None:
    db = _db()
    with db._lock:
        db._conn.execute("DELETE FROM lan_devices WHERE network = ? AND mac = ?", (network, mac))
        db._conn.commit()
    log_operation("lan.forget", mac)


# ------------------------------------------------------------ serviço (Qt)
from PySide6.QtCore import QObject, QTimer, Signal  # noqa: E402


class LanWatcher(QObject):
    """Busca sob demanda e, se ligado, a cada N minutos — avisando sobre aparelhos novos."""
    updated = Signal()
    progress = Signal(str)
    _instance: "LanWatcher | None" = None

    def __init__(self) -> None:
        super().__init__()
        self.devices: list[LanDevice] = []
        self.net: LocalNet | None = None
        self.net_id = ""
        self.new: list[LanDevice] = []
        self.busy = False
        self.last_scan = 0.0
        self.error = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto)
        self.apply_settings()

    @classmethod
    def instance(cls) -> "LanWatcher":
        if cls._instance is None:
            cls._instance = LanWatcher()
        return cls._instance

    def apply_settings(self) -> None:
        from ..core.config import Settings
        s = Settings.instance()
        if s.get("network.devices_watch", False):
            self._timer.start(max(5, int(s.get("network.devices_interval_min", 15))) * 60_000)
        else:
            self._timer.stop()

    def _auto(self) -> None:
        self.scan(notify=True)

    def scan(self, notify: bool = False) -> None:
        if self.busy:
            return
        self.busy = True
        self.error = ""
        self.updated.emit()
        from ..ui.tasks import run_task

        def work():
            ln, devs = scan(lambda t: self.progress.emit(t))
            all_devs, new = merge(ln, devs)
            return ln, network_id(ln, devs), all_devs, new

        run_task(work, on_done=lambda r: self._done(r, notify), on_error=self._fail)

    def _done(self, res, notify: bool) -> None:
        self.net, self.net_id, self.devices, self.new = res
        self.busy = False
        self.last_scan = time.time()
        from ..core.config import Settings
        if notify and self.new and Settings.instance().get("network.devices_alert", True):
            from ..automation.engine import AlertEngine
            from ..automation.store import Alert
            d = self.new[0]
            extra = f" (+{len(self.new) - 1})" if len(self.new) > 1 else ""
            AlertEngine.instance().fire(Alert(
                "lan_new", "warning", "Aparelho novo na sua rede",
                f"{d.kind}: {d.label} — IP {d.ip}{', ' + d.vendor if d.vendor else ''}{extra}. "
                "Se não reconhecer, troque a senha do Wi-Fi no roteador.", None, "page:network:devices"))
        self.updated.emit()

    def _fail(self, msg: str) -> None:
        self.busy = False
        self.error = msg
        self.updated.emit()
