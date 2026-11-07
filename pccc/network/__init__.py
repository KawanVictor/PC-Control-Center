"""Monitoramento de rede e Wi-Fi (Fase 3).

Fontes (todas nativas, sem programas externos e sem administrador):
* wlanapi.dll           — rede Wi-Fi conectada, sinal, RSSI, canal, padrão, segurança
* GetAdaptersAddresses  — interfaces, IPv4/IPv6, gateway, DNS, MAC, DHCP, velocidade do link
* IcmpSendEcho          — ping (latência, perda de pacotes, jitter)
* psutil                — tráfego por interface
* speed.cloudflare.com  — teste de velocidade (somente quando o usuário pede)
"""
