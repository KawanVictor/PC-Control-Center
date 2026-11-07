"""Nascer e pôr do sol calculados localmente (algoritmo da NOAA), sem internet."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from ..core.config import Settings

DEFAULT_LOCATION = {"lat": -23.5475, "lon": -46.63611, "label": "São Paulo, SP"}


def location() -> dict:
    """Local usado pelo tema automático: o escolhido nas configurações ou o do widget de clima."""
    loc = Settings.instance().get("location")
    if isinstance(loc, dict) and "lat" in loc and "lon" in loc:
        return loc
    try:
        from ..widgets.manager import WidgetManager
        for prof in WidgetManager.instance().profiles.values():
            for w in prof:
                o = w.get("options") or {}
                if w.get("type") == "weather" and "lat" in o:
                    return {"lat": o["lat"], "lon": o["lon"], "label": o.get("label", "")}
    except Exception:
        pass
    return DEFAULT_LOCATION


def sun_times(lat: float, lon: float, day: date | None = None) -> tuple[datetime | None, datetime | None]:
    """(nascer, pôr) no horário local. None em dia polar."""
    day = day or date.today()
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    lat_r = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(lat_r) * math.cos(decl))
              - math.tan(lat_r) * math.tan(decl))
    if not -1 <= cos_ha <= 1:
        return None, None
    ha = math.degrees(math.acos(cos_ha))
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)

    def at(minutes: float) -> datetime:
        return (base + timedelta(minutes=minutes)).astimezone().replace(tzinfo=None)

    return at(720 - 4 * (lon + ha) - eqtime), at(720 - 4 * (lon - ha) - eqtime)


def is_daytime(now: datetime | None = None, loc: dict | None = None) -> bool:
    now = now or datetime.now()
    loc = loc or location()
    rise, set_ = sun_times(float(loc["lat"]), float(loc["lon"]), now.date())
    if rise is None:
        # sol da meia-noite ou noite polar: decide pela estação
        return 3 < now.month < 10 if float(loc["lat"]) > 0 else not (3 < now.month < 10)
    return rise <= now < set_
