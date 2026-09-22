"""Math, geometry, and utility helper functions."""

from __future__ import annotations

import re
import numpy as np


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp value between minimum and maximum."""
    return max(minimum, min(value, maximum))


def wrap_longitude(longitude: float) -> float:
    """Wrap longitude to [-180, 180] range."""
    return ((longitude + 180.0) % 360.0) - 180.0


def longitude_delta(start: float, end: float) -> float:
    """Compute shortest delta between two longitudes."""
    return ((end - start + 540.0) % 360.0) - 180.0


def bearing_between_coordinates(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Calculate forward azimuth bearing in degrees [0, 360)."""
    lat_a = np.deg2rad(latitude_a)
    lat_b = np.deg2rad(latitude_b)
    delta_lon = np.deg2rad(longitude_b - longitude_a)
    x = np.sin(delta_lon) * np.cos(lat_b)
    y = np.cos(lat_a) * np.sin(lat_b) - np.sin(lat_a) * np.cos(lat_b) * np.cos(delta_lon)
    return float((np.rad2deg(np.arctan2(x, y)) + 360.0) % 360.0)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate spherical distance in meters between two lat/lon pairs."""
    r = 6371000.0  # Earth radius in meters
    phi1 = np.deg2rad(lat1)
    phi2 = np.deg2rad(lat2)
    dphi = np.deg2rad(lat2 - lat1)
    dlambda = np.deg2rad(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    return float(2.0 * r * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a)))


def meters_from_gps(
    latitude: float,
    longitude: float,
    home_latitude: float,
    home_longitude: float,
) -> tuple[float, float]:
    """Convert GPS coordinates to relative planar offset (x, y) in meters from home."""
    lat_rad = np.deg2rad(home_latitude)
    meters_per_deg_lat = 111_132.0
    meters_per_deg_lon = 111_320.0 * np.cos(lat_rad)
    x = (longitude - home_longitude) * meters_per_deg_lon
    y = (latitude - home_latitude) * meters_per_deg_lat
    return (float(x), float(y))


def meters_to_gps(
    x_meters: float,
    y_meters: float,
    home_latitude: float,
    home_longitude: float,
) -> tuple[float, float]:
    """Convert relative planar meters (x, y) back to GPS coordinates."""
    lat_rad = np.deg2rad(home_latitude)
    meters_per_deg_lat = 111_132.0
    meters_per_deg_lon = 111_320.0 * np.cos(lat_rad)
    lat = home_latitude + (y_meters / meters_per_deg_lat)
    lon = home_longitude + (x_meters / max(meters_per_deg_lon, 1e-6))
    return (float(lat), float(lon))


def slugify_name(value: str) -> str:
    """Sanitize string for filename or ID usage."""
    cleaned = re.sub(r"[^\w\s-]", "", value.strip().lower())
    return re.sub(r"[-\s]+", "_", cleaned).strip("_")
