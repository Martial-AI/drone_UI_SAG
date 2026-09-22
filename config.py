"""Global configuration, constants, directory paths, and asset resolvers for Spectrum Air Guard."""

from __future__ import annotations

import os
import re
import sys

APP_NAME = "Spectrum Air Guard"
APP_DIR_NAME = "SpectrumAirGuard"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_MAP_LATITUDE = -18.915526156892348
DEFAULT_MAP_LONGITUDE = 47.521632233713056
ENABLE_STARTUP_SPLASH = False
ENABLE_DEMO_TELEMETRY = True
FORCE_TEST_BATTERY_PERCENT: float | None = 100.0
MAP_UPDATE_INTERVAL_DAYS = 21

ALERT_THRESHOLDS: dict[str, float] = {
    "battery_warning": 30.0,   # %
    "battery_critical": 15.0,  # %
    "altitude_max": 120.0,     # m (règlementation civile)
    "speed_max": 100.0,        # km/h
    "gps_sats_min": 6.0,       # satellites
    "temp_max": 50.0,          # °C
}


def runtime_root_dir() -> str:
    if getattr(sys, "frozen", False):
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return os.path.join(local_appdata, APP_DIR_NAME)
        return os.path.join(os.path.expanduser("~"), "AppData", "Local", APP_DIR_NAME)
    return BASE_DIR


RUNTIME_ROOT_DIR = runtime_root_dir()
DATA_DIR = os.path.join(RUNTIME_ROOT_DIR, "DATA")
AIR_DATA_DIR = os.path.join(DATA_DIR, "AIR DATA")
MAPS_DIR = os.path.join(DATA_DIR, "maps")
CACHE_DIR = os.path.join(RUNTIME_ROOT_DIR, "cache")

DEMO_TELEMETRY_PACKET = (
    "CO2:420,LPG:30,CO:20,HUM:58,COUNT:150,TEMP:57,"
    "PITCH:0,ROLL:0,HEADING:230,GPS_SPEED:8,ALTITUDE:15,BATTERY:82,"
    "LATITUDE:-18.91552,LONGITUDE:47.52163,"
    "LIDAR:0=2.5;45=1.2;90=0.7;180=3.0;270=1.5"
)


def asset_path(*parts: str) -> str:
    return os.path.join(BASE_DIR, *parts)


def app_icon_path() -> str:
    candidates = [
        asset_path("img", "droneP.ico"),
        asset_path("img", "droneP.png"),
        asset_path("img", "droneIcon.ico"),
        asset_path("img", "drone_app_icon.png"),
        asset_path("img", "SAG.png"),
        asset_path("img", "drone.ico"),
        asset_path("img", "logo.ico"),
        asset_path("img", "SAG.ico"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def splash_logo_path() -> str:
    candidates = [
        asset_path("img", "droneP.png"),
        asset_path("img", "iconLogo.png"),
        asset_path("img", "SAG.png"),
        app_icon_path(),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""


def low_battery_audio_path() -> str:
    path = asset_path("audio", "lowbat.mp3")
    return path if os.path.exists(path) else ""


def critical_battery_audio_path() -> str:
    path = asset_path("audio", "lowbat1.mp3")
    return path if os.path.exists(path) else ""


def landing_alert_audio_path() -> str:
    path = asset_path("audio", "alert.mp3")
    return path if os.path.exists(path) else ""


def autoland_alert_audio_path() -> str:
    path = asset_path("audio", "autoland_alert.mp3")
    return path if os.path.exists(path) else ""


def flight_mode_audio_path(file_name: str) -> str:
    path = asset_path("audio", file_name)
    return path if os.path.exists(path) else ""


def ensure_data_dir() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


def ensure_air_data_dir() -> str:
    os.makedirs(AIR_DATA_DIR, exist_ok=True)
    return AIR_DATA_DIR


def ensure_maps_dir() -> str:
    os.makedirs(MAPS_DIR, exist_ok=True)
    return MAPS_DIR


def ensure_cache_dir() -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return CACHE_DIR


def make_data_log_path(prefix: str = "data_log_time", ext: str = ".csv", directory: str | None = None) -> str:
    target_dir = directory or BASE_DIR
    os.makedirs(target_dir, exist_ok=True)
    file_name = f"{prefix}{ext}"
    index = 1
    file_path = os.path.join(target_dir, file_name)
    while os.path.exists(file_path):
        file_name = f"{prefix}_{index}{ext}"
        file_path = os.path.join(target_dir, file_name)
        index += 1
    return file_path


def database_file_path(directory: str | None = None) -> str:
    target_dir = directory or ensure_data_dir()
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, "telemetry_store.db")


def video_sources_state_path(directory: str | None = None) -> str:
    target_dir = directory or ensure_data_dir()
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, "video_sources.json")


def map_zones_manifest_path(directory: str | None = None) -> str:
    target_dir = directory or ensure_maps_dir()
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, "offline_zones.json")


def slugify_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "zone"


def map_zone_metadata_path(zone_name: str, directory: str | None = None) -> str:
    target_dir = directory or ensure_maps_dir()
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, f"{slugify_name(zone_name)}.json")


def map_update_state_path(directory: str | None = None) -> str:
    target_dir = directory or ensure_maps_dir()
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, "map_update_state.json")
