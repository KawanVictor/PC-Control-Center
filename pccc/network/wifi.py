"""Informações do Wi-Fi via Native Wifi API (wlanapi.dll).

Observação: a partir do Windows 11 24H2, ler o nome da rede (SSID) exige que
"Permitir que aplicativos da área de trabalho acessem sua localização" esteja ligado.
Sem isso o Windows responde ACCESS_DENIED — detectamos e explicamos ao usuário.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from ..core.logger import get_logger
from .models import WifiInfo

log = get_logger("wifi")

ERROR_SUCCESS = 0
ERROR_ACCESS_DENIED = 5
ERROR_NOT_READY = 21

OPCODE_CURRENT_CONNECTION = 7
OPCODE_CHANNEL_NUMBER = 8
OPCODE_RSSI = 0x10000102

_STATES = {0: "Não pronto", 1: "Conectado", 2: "Ad hoc", 3: "Desconectando", 4: "Desconectado",
           5: "Associando", 6: "Descobrindo", 7: "Autenticando"}
_PHY = {1: "FHSS", 2: "DSSS", 3: "IR", 4: "802.11a", 5: "802.11b", 6: "802.11g",
        7: "Wi-Fi 4 (802.11n)", 8: "Wi-Fi 5 (802.11ac)", 9: "802.11ad",
        10: "Wi-Fi 6 (802.11ax)", 11: "Wi-Fi 7 (802.11be)"}
_AUTH = {1: "Aberta", 2: "WEP", 3: "WPA-Enterprise", 4: "WPA-Personal", 5: "WPA",
         6: "WPA2-Enterprise", 7: "WPA2-Personal", 8: "WPA3-Enterprise 192", 9: "WPA3-Personal",
         10: "OWE (aberta criptografada)", 11: "WPA3-Enterprise"}


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [("InterfaceGuid", GUID), ("strInterfaceDescription", wintypes.WCHAR * 256),
                ("isState", wintypes.DWORD)]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD),
                ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)]


class DOT11_SSID(ctypes.Structure):
    _fields_ = [("uSSIDLength", wintypes.ULONG), ("ucSSID", ctypes.c_ubyte * 32)]


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("dot11Ssid", DOT11_SSID), ("dot11BssType", wintypes.DWORD),
                ("dot11Bssid", ctypes.c_ubyte * 6), ("dot11PhyType", wintypes.DWORD),
                ("uDot11PhyIndex", wintypes.ULONG), ("wlanSignalQuality", wintypes.ULONG),
                ("ulRxRate", wintypes.ULONG), ("ulTxRate", wintypes.ULONG)]


class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("bSecurityEnabled", wintypes.BOOL), ("bOneXEnabled", wintypes.BOOL),
                ("dot11AuthAlgorithm", wintypes.DWORD), ("dot11CipherAlgorithm", wintypes.DWORD)]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("isState", wintypes.DWORD), ("wlanConnectionMode", wintypes.DWORD),
                ("strProfileName", wintypes.WCHAR * 256),
                ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
                ("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES)]


def _band(channel: int | None, phy: int) -> str:
    if not channel:
        return ""
    if channel <= 14:
        return "2,4 GHz"
    return "5 GHz" if channel <= 177 else "6 GHz"


class WifiReader:
    def __init__(self) -> None:
        self._handle = None
        self._dll: ctypes.WinDLL | None
        try:
            self._dll = ctypes.WinDLL("wlanapi")
        except OSError:
            self._dll = None
            return
        d = self._dll
        d.WlanOpenHandle.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                     ctypes.POINTER(wintypes.HANDLE)]
        d.WlanEnumInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.POINTER(WLAN_INTERFACE_INFO_LIST))]
        d.WlanQueryInterface.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p,
                                         ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_void_p),
                                         ctypes.c_void_p]
        d.WlanFreeMemory.argtypes = [ctypes.c_void_p]
        d.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        negotiated = wintypes.DWORD()
        handle = wintypes.HANDLE()
        if d.WlanOpenHandle(2, None, ctypes.byref(negotiated), ctypes.byref(handle)) == ERROR_SUCCESS:
            self._handle = handle
        else:
            log.info("Serviço WLAN indisponível (sem placa Wi-Fi ou serviço WlanSvc parado)")

    def _query(self, guid: GUID, opcode: int):
        size = wintypes.DWORD()
        data = ctypes.c_void_p()
        if self._dll is None:
            return ERROR_NOT_READY, data
        rc = self._dll.WlanQueryInterface(self._handle, ctypes.byref(guid), opcode, None,
                                          ctypes.byref(size), ctypes.byref(data), None)
        return rc, data

    def read(self) -> WifiInfo:
        info = WifiInfo()
        if self._dll is None or self._handle is None:
            return info
        ilist = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        if self._dll.WlanEnumInterfaces(self._handle, None, ctypes.byref(ilist)) != ERROR_SUCCESS:
            return info
        try:
            n = ilist.contents.dwNumberOfItems
            if n == 0:
                return info
            items = ctypes.cast(ctypes.byref(ilist.contents.InterfaceInfo),
                                ctypes.POINTER(WLAN_INTERFACE_INFO * n)).contents
            # Prefere a interface conectada.
            iface = next((it for it in items if it.isState == 1), items[0])
            info.available = True
            info.adapter = iface.strInterfaceDescription
            info.state = _STATES.get(iface.isState, str(iface.isState))
            info.connected = iface.isState == 1
            if not info.connected:
                return info
            guid = GUID()
            ctypes.memmove(ctypes.byref(guid), ctypes.byref(iface.InterfaceGuid), ctypes.sizeof(GUID))

            rc, data = self._query(guid, OPCODE_CURRENT_CONNECTION)
            if rc == ERROR_SUCCESS:
                try:
                    attrs = ctypes.cast(data, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES)).contents
                    assoc = attrs.wlanAssociationAttributes
                    ssid = bytes(assoc.dot11Ssid.ucSSID[: assoc.dot11Ssid.uSSIDLength])
                    info.ssid = ssid.decode("utf-8", "replace")
                    info.profile = attrs.strProfileName
                    info.bssid = ":".join(f"{b:02X}" for b in assoc.dot11Bssid)
                    info.signal = int(assoc.wlanSignalQuality)
                    info.rx_mbps = assoc.ulRxRate / 1000
                    info.tx_mbps = assoc.ulTxRate / 1000
                    info.standard = _PHY.get(assoc.dot11PhyType, "")
                    sec = attrs.wlanSecurityAttributes
                    info.security = _AUTH.get(sec.dot11AuthAlgorithm, "") if sec.bSecurityEnabled else "Aberta"
                    phy = assoc.dot11PhyType
                finally:
                    self._dll.WlanFreeMemory(data)
            elif rc == ERROR_ACCESS_DENIED:
                phy = 0
                info.error = ("O Windows bloqueou a leitura do nome da rede. Ative 'Permitir que aplicativos "
                              "da área de trabalho acessem sua localização' em Privacidade > Localização.")
            else:
                phy = 0
                info.error = f"Falha ao consultar a conexão Wi-Fi (código {rc})."

            rc, data = self._query(guid, OPCODE_RSSI)
            if rc == ERROR_SUCCESS:
                info.rssi = ctypes.cast(data, ctypes.POINTER(ctypes.c_long)).contents.value
                self._dll.WlanFreeMemory(data)
            rc, data = self._query(guid, OPCODE_CHANNEL_NUMBER)
            if rc == ERROR_SUCCESS:
                info.channel = ctypes.cast(data, ctypes.POINTER(wintypes.ULONG)).contents.value
                self._dll.WlanFreeMemory(data)
            info.band = _band(info.channel, phy)
            if not info.signal and info.rssi is not None:
                # Aproximação usada pelo próprio Windows: -100 dBm = 0%, -50 dBm = 100%.
                info.signal = max(0, min(100, 2 * (info.rssi + 100)))
        finally:
            self._dll.WlanFreeMemory(ilist)
        return info

    def close(self) -> None:
        if self._dll is not None and self._handle is not None:
            self._dll.WlanCloseHandle(self._handle, None)
            self._handle = None
