"""Core package for Spectrum Air Guard."""

from core.models import SensorData, PositionFix, AlertEntry
from core.i18n import UI_TEXTS, tr
from core.utils import (
    clamp,
    wrap_longitude,
    longitude_delta,
    bearing_between_coordinates,
    haversine_distance,
    meters_from_gps,
    meters_to_gps,
    slugify_name,
)

__all__ = [
    "SensorData",
    "PositionFix",
    "AlertEntry",
    "UI_TEXTS",
    "tr",
    "clamp",
    "wrap_longitude",
    "longitude_delta",
    "bearing_between_coordinates",
    "haversine_distance",
    "meters_from_gps",
    "meters_to_gps",
    "slugify_name",
]
