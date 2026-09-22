"""Core models and data structures for Spectrum Air Guard."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class SensorData:
    co2: float = 0.0
    lpg: float = 0.0
    co: float = 0.0
    humidity: float = 0.0
    radiation: float = 0.0
    temperature: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    heading: float = 0.0
    gps_speed: float = 0.0
    vertical_speed: float = 0.0
    altitude: float = 0.0
    battery: float = 100.0
    distance: float = 0.0
    latitude: float | None = None
    longitude: float | None = None
    lidar_points: tuple[tuple[float, float], ...] = ()
    position_source: str = "relative"
    heading_source: str = "derived"
    sender: str = "Waiting for WiFi"
    raw_packet: str = "No packet received yet"
    timestamp: str = "--:--:--"


@dataclass
class PositionFix:
    latitude: float
    longitude: float
    speed_kmh: float | None = None
    altitude: float | None = None
    heading: float | None = None
    timestamp: float = 0.0
    source_label: str = "Device GPS"


@dataclass
class AlertEntry:
    message: str
    level: str = "info"       # "info", "warning", "critical"
    auto_dismiss: int = 0     # Seconds before auto-removal (0 = manual)
    timestamp: float = 0.0
    dismissed: bool = False

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()
