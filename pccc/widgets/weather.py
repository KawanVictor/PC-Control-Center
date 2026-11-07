"""Clima via Open-Meteo (https://open-meteo.com) — gratuito, sem chave e sem cadastro.

A cidade é convertida em coordenadas uma única vez (geocodificação) e o resultado fica
salvo nas opções do widget. A previsão é atualizada a cada 15 minutos.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from ..core.logger import get_logger

log = get_logger("weather")
UA = {"User-Agent": "PCControlCenter/0.5"}

# Códigos WMO → (descrição, emoji dia, emoji noite)
WMO = {
    0: ("Céu limpo", "☀️", "🌙"), 1: ("Predomínio de sol", "🌤️", "🌙"), 2: ("Parcialmente nublado", "⛅", "☁️"),
    3: ("Nublado", "☁️", "☁️"), 45: ("Neblina", "🌫️", "🌫️"), 48: ("Neblina com geada", "🌫️", "🌫️"),
    51: ("Garoa fraca", "🌦️", "🌧️"), 53: ("Garoa", "🌦️", "🌧️"), 55: ("Garoa forte", "🌧️", "🌧️"),
    56: ("Garoa congelante", "🌧️", "🌧️"), 57: ("Garoa congelante", "🌧️", "🌧️"),
    61: ("Chuva fraca", "🌦️", "🌧️"), 63: ("Chuva", "🌧️", "🌧️"), 65: ("Chuva forte", "🌧️", "🌧️"),
    66: ("Chuva congelante", "🌧️", "🌧️"), 67: ("Chuva congelante", "🌧️", "🌧️"),
    71: ("Neve fraca", "🌨️", "🌨️"), 73: ("Neve", "🌨️", "🌨️"), 75: ("Neve forte", "❄️", "❄️"),
    77: ("Granizo fino", "🌨️", "🌨️"), 80: ("Pancadas de chuva", "🌦️", "🌧️"),
    81: ("Pancadas de chuva", "🌧️", "🌧️"), 82: ("Pancadas fortes", "⛈️", "⛈️"),
    85: ("Pancadas de neve", "🌨️", "🌨️"), 86: ("Pancadas de neve", "🌨️", "🌨️"),
    95: ("Trovoada", "⛈️", "⛈️"), 96: ("Trovoada com granizo", "⛈️", "⛈️"), 99: ("Trovoada com granizo", "⛈️", "⛈️"),
}


def describe(code: int | None, is_day: bool = True) -> tuple[str, str]:
    d = WMO.get(int(code) if code is not None else -1, ("—", "🌡️", "🌡️"))
    return d[0], d[1] if is_day else d[2]


def geocode(city: str) -> dict | None:
    q = urllib.parse.urlencode({"name": city, "count": 1, "language": "pt", "format": "json"})
    req = urllib.request.Request("https://geocoding-api.open-meteo.com/v1/search?" + q, headers=UA)
    data = json.load(urllib.request.urlopen(req, timeout=10))
    res = (data.get("results") or [None])[0]
    if not res:
        return None
    label = ", ".join(x for x in (res.get("name"), res.get("admin1")) if x)
    return {"lat": res["latitude"], "lon": res["longitude"], "label": label}


def forecast(lat: float, lon: float) -> dict:
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 5,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,is_day",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
    })
    req = urllib.request.Request("https://api.open-meteo.com/v1/forecast?" + q, headers=UA)
    data = json.load(urllib.request.urlopen(req, timeout=10))
    data["fetched_at"] = time.time()
    return data
