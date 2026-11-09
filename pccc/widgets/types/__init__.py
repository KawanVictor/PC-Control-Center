"""Os 20 tipos de widget, um por módulo. Cada um desenha em seu canvas virtual (``base_size``)."""
from __future__ import annotations

from ..base import Renderer
from .clock import ClockWidget
from .calendar import CalendarWidget
from .weather import WeatherWidget
from .cpu import CpuWidget
from .ram import RamWidget
from .gpu import GpuWidget
from .temps import TempWidget
from .wifi import WifiWidget
from .netspeed import NetSpeedWidget
from .storage import StorageWidget
from .media import MediaWidget
from .sysinfo import SysInfoWidget
from .battery import BatteryWidget
from .shortcuts import ShortcutsWidget
from .processes import ProcessWidget
from .visualizer import VisualizerWidget
from .volume import VolumeWidget
from .obs import ObsWidget
from .youtube import YouTubeWidget
from .fps import FpsWidget

REGISTRY: dict[str, type[Renderer]] = {cls.type_id: cls for cls in (
    ClockWidget, CalendarWidget, WeatherWidget, CpuWidget, RamWidget, GpuWidget, TempWidget, WifiWidget,
    NetSpeedWidget, StorageWidget, MediaWidget, SysInfoWidget, BatteryWidget, ShortcutsWidget, ProcessWidget,
    VisualizerWidget, VolumeWidget, ObsWidget, YouTubeWidget, FpsWidget)}
