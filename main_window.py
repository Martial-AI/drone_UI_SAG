from __future__ import annotations

import csv
import json
import os
import queue
import re
import socket
import sqlite3
import sys
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import cv2 as cv
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import serial
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    QThread,
    Qt,
    QTimer,
    Signal,
    QUrl,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkDiskCache,
    QNetworkReply,
    QNetworkRequest,
)
from PySide6.QtPositioning import QGeoPositionInfo, QGeoPositionInfoSource
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QTabBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from config import (
    APP_NAME,
    APP_DIR_NAME,
    BASE_DIR,
    DEFAULT_MAP_LATITUDE,
    DEFAULT_MAP_LONGITUDE,
    ENABLE_STARTUP_SPLASH,
    ENABLE_DEMO_TELEMETRY,
    FORCE_TEST_BATTERY_PERCENT,
    MAP_UPDATE_INTERVAL_DAYS,
    app_icon_path,
    splash_logo_path,
    low_battery_audio_path,
    critical_battery_audio_path,
    landing_alert_audio_path,
    autoland_alert_audio_path,
    flight_mode_audio_path,
    ensure_data_dir,
    ensure_air_data_dir,
    ensure_maps_dir,
    ensure_cache_dir,
    make_data_log_path,
    database_file_path,
    video_sources_state_path,
    map_zones_manifest_path,
    map_zone_metadata_path,
    map_update_state_path,
    asset_path,
    DEMO_TELEMETRY_PACKET,
)
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
from services import (
    TelemetryListener,
    TcpTelemetryListener,
    SerialTelemetryListener,
    VideoStreamReceiver,
    ThermalReceiver,
    CommandClient,
)
from widgets import (
    DashboardCard,
    StatusBadge,
    LongPressButton,
    ThemeSwitch,
    StartupSplash,
    MetricCard,
    CircularGaugeWidget,
    ArtificialHorizonWidget,
    CompassWidget,
    TapeGaugeWidget,
    BatteryWidget,
    SparklineWidget,
    TelemetryChartWidget,
    FlightDataChartWidget,
    DataPlotDialog,
    AlertBannerWidget,
    FlightLogWidget,
    Radar360Widget,
    FloatingRadarWidget,
    OfflineMapWidget,
    FloatingScienceChartWidget,
    FloatingScreenWidget,
    ConnectionInterfaceDialog,
    ActionConfirmationDialog,
    TakeoffAltitudeDialog,
    KeyboardShortcutsDialog,
    VideoSourceDialog,
    OfflineMapZoneDialog,
    OfflineMapZoneBrowserDialog,
    OfflineMapDownloadDialog,
    VideoOSDWidget,
    PipWindowWidget,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SPECTRUM AIR GUARD")
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(int(available.width() * 0.96), int(available.height() * 0.94))
        else:
            self.resize(1440, 900)

        icon_file = app_icon_path()
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))

        self.current_data = SensorData()
        self.device_position_fix: PositionFix | None = None
        self.device_position_source: QGeoPositionInfoSource | None = None
        self._telemetry_has_real_gps = False
        self.live_frame: QImage | None = None
        self.thermal_frame: QImage | None = None
        self.active_video_mode = "live"
        self.radiation_history: deque[float] = deque(maxlen=180)
        self.data_histories = {
            "x": deque(maxlen=240),
            "co2": deque(maxlen=240),
            "lpg": deque(maxlen=240),
            "co": deque(maxlen=240),
            "humidity": deque(maxlen=240),
            "radiation": deque(maxlen=240),
            "temp": deque(maxlen=240),
        }
        self.sample_index = 0
        self.data_dir = ensure_data_dir()
        self.air_data_dir = ensure_air_data_dir()
        self.maps_dir = ensure_maps_dir()
        self.map_zones_manifest = map_zones_manifest_path(self.maps_dir)
        self.offline_map_zones = self._load_offline_map_zones()
        self.map_update_state_file = map_update_state_path(self.maps_dir)
        self.map_last_updated_at = self._load_map_update_timestamp()
        self.map_update_banner_dismissed = False
        self.map_update_refresh_pending = False
        self.primary_view = "map"
        self.floating_panels: dict[str, QWidget] = {}
        self.active_map_download_name: str | None = None
        self.map_download_dialog: OfflineMapDownloadDialog | None = None
        self.map_download_cancelled = False
        self.log_file_path = make_data_log_path(directory=self.air_data_dir)
        self.database_path = database_file_path(self.data_dir)
        self.log_handle = open(self.log_file_path, "w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.log_handle)
        self.csv_writer.writerow(
            [
                "Time",
                "CO2",
                "LPG",
                "CO",
                "Hum",
                "Count",
                "Temp",
                "Pitch",
                "Roll",
                "Heading",
                "Speed",
                "Altitude",
                "Battery",
                "Latitude",
                "Longitude",
            ]
        )
        self.database = sqlite3.connect(self.database_path)
        self._initialize_database()
        self.session_id = self._create_log_session()

        self.telemetry_listener = TelemetryListener()
        self.thermal_receiver = ThermalReceiver()
        self.command_client = CommandClient()
        self.live_stream_worker: VideoStreamReceiver | None = None
        self.thermal_stream_worker: VideoStreamReceiver | None = None
        self.video_sources_state_file = video_sources_state_path()
        saved_video_sources = self._load_video_sources()
        live_source = saved_video_sources.get("live", {})
        thermal_source = saved_video_sources.get("thermal", {})
        self.live_stream_protocol = str(live_source.get("protocol", "RTSP"))
        self.live_stream_address = str(live_source.get("address", ""))
        self.thermal_stream_protocol = str(thermal_source.get("protocol", "RTSP"))
        self.thermal_stream_address = str(thermal_source.get("address", ""))
        self.link_worker: QThread | None = None
        self.network_connected = False
        self.network_mode = "UDP"
        self.main_menu_popup: QMenu | None = None
        self.main_menu_anchor_pos = QPoint()
        self.keep_main_menu_open = False
        self.sounds_enabled = True
        self.connection_profiles = {
            "UDP": f"{self.telemetry_listener.host}:{self.telemetry_listener.port}",
            "TCP": f"{self.command_client.host}:{self.command_client.port}",
            "SERIAL": "COM3@115200",
        }
        self.low_battery_alert_active = False
        self.low_battery_land_acknowledged = False
        self.low_battery_alert_alpha = 0.0
        self.low_battery_alert_direction = 1.0
        self.battery_alert_state = "normal"
        self.low_battery_audio_mode = "idle"
        self.low_battery_warning_file = low_battery_audio_path()
        self.critical_battery_audio_file = critical_battery_audio_path()
        self.autoland_alert_audio_file = autoland_alert_audio_path()
        self.landing_alert_audio_file = landing_alert_audio_path()
        self.flight_mode_audio_files = {
            "Scan": flight_mode_audio_path("Scan.mp3"),
            "Hold": flight_mode_audio_path("Hold.mp3"),
            "Stabilize": flight_mode_audio_path("Stab.mp3"),
        }
        self.low_battery_audio_output = QAudioOutput(self)
        self.low_battery_audio_output.setVolume(0.85)
        self.low_battery_player = QMediaPlayer(self)
        self.low_battery_player.setAudioOutput(self.low_battery_audio_output)
        self.low_battery_player.mediaStatusChanged.connect(self._handle_low_battery_media_status)
        self.low_battery_audio_timer = QTimer(self)
        self.low_battery_audio_timer.setInterval(15000)
        self.low_battery_audio_timer.timeout.connect(self._play_low_battery_audio)
        self.low_battery_flash_timer = QTimer(self)
        self.low_battery_flash_timer.setInterval(16)
        self.low_battery_flash_timer.timeout.connect(self._update_low_battery_alert_visuals)
        self.radiation_spectrum_phase = 0.0
        self.radiation_spectrum_timer = QTimer(self)
        self.radiation_spectrum_timer.setInterval(160)
        self.radiation_spectrum_timer.timeout.connect(self._animate_radiation_spectrum)
        self.current_theme = "dark"
        self.current_language = "en"

        self._build_ui()
        self._position_battery_alert_card()
        self._setup_device_gps_fallback()
        self._connect_signals()
        self._refresh_map_update_banner()
        if FORCE_TEST_BATTERY_PERCENT is not None:
            self.current_data = replace(self.current_data, battery=FORCE_TEST_BATTERY_PERCENT)
            battery_percent = int(round(FORCE_TEST_BATTERY_PERCENT))
            if battery_percent <= 30:
                batt_text = f'<span style="color:#ff4d4f;">BATT {battery_percent}</span>'
            else:
                batt_text = f"BATT {battery_percent}"
            self.flight_gps_label.setText("GPS 00")
            self.flight_batt_label.setText(batt_text)
            self.flight_signal_label.setText("SIGNAL 0")
            self._update_battery_alert_state(battery_percent, landed=False)
        if ENABLE_DEMO_TELEMETRY:
            self._apply_demo_telemetry_data()
        self._start_workers()

        self.record_timer = QTimer(self)
        self.record_timer.timeout.connect(self._record_current_data)
        self.record_timer.start(1000)
        self.radiation_spectrum_timer.start()

    def _make_scroll_column(self) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setStyleSheet("QScrollArea { background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        area.setWidget(container)
        return area, container, layout

    def _build_summary_strip(self, caption: str, value_label: QLabel) -> QFrame:
        panel = QFrame()
        panel.setObjectName("summaryStrip")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        caption_label = QLabel(caption)
        caption_label.setObjectName("summaryCaption")
        value_label.setObjectName("summaryValue")
        value_label.setWordWrap(True)

        layout.addWidget(caption_label)
        layout.addWidget(value_label)
        return panel

    @staticmethod
    def _parse_host_port(value: str, default_host: str, default_port: int) -> tuple[str, int]:
        text = value.strip()
        if not text:
            return default_host, default_port

        if ":" not in text:
            return text, default_port

        host, raw_port = text.rsplit(":", 1)
        host = host.strip() or default_host
        try:
            port = int(raw_port.strip())
        except ValueError:
            port = default_port
        return host, port

    def _initialize_database(self) -> None:
        cursor = self.database.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                csv_path TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                recorded_at TEXT NOT NULL,
                time_label TEXT NOT NULL,
                co2 REAL NOT NULL,
                lpg REAL NOT NULL,
                co REAL NOT NULL,
                humidity REAL NOT NULL,
                radiation REAL NOT NULL,
                temperature REAL NOT NULL,
                pitch REAL NOT NULL,
                roll REAL NOT NULL,
                heading REAL NOT NULL,
                speed REAL NOT NULL,
                altitude REAL NOT NULL,
                battery REAL NOT NULL,
                latitude REAL,
                longitude REAL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_session_time ON telemetry_samples(session_id, recorded_at)")
        self.database.commit()

    def _create_log_session(self) -> int:
        cursor = self.database.cursor()
        cursor.execute(
            "INSERT INTO sessions(started_at, csv_path) VALUES(?, ?)",
            (datetime.now().isoformat(timespec="seconds"), os.path.basename(self.log_file_path)),
        )
        self.database.commit()
        return int(cursor.lastrowid)

    def _load_video_sources(self) -> dict[str, dict[str, str]]:
        if not hasattr(self, "video_sources_state_file") or not os.path.exists(self.video_sources_state_file):
            return {}
        try:
            with open(self.video_sources_state_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}

        sources: dict[str, dict[str, str]] = {}
        if not isinstance(payload, dict):
            return sources
        for mode in ("live", "thermal"):
            source = payload.get(mode)
            if not isinstance(source, dict):
                continue
            protocol = str(source.get("protocol", "RTSP")).strip().upper()
            address = str(source.get("address", "")).strip()
            if protocol and address:
                sources[mode] = {"protocol": protocol, "address": address}
        return sources

    def _save_video_sources(self) -> None:
        payload = {
            "live": {
                "protocol": self.live_stream_protocol,
                "address": self.live_stream_address,
            },
            "thermal": {
                "protocol": self.thermal_stream_protocol,
                "address": self.thermal_stream_address,
            },
        }
        try:
            with open(self.video_sources_state_file, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
        except OSError:
            self.last_command_label.setText("Video source save failed")

    def _load_offline_map_zones(self) -> list[dict[str, object]]:
        cleaned: list[dict[str, object]] = []
        if os.path.exists(self.map_zones_manifest):
            try:
                with open(self.map_zones_manifest, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                zones = payload.get("zones", [])
                if isinstance(zones, list):
                    for zone in zones:
                        if isinstance(zone, dict) and str(zone.get("name", "")).strip():
                            cleaned.append(zone)
            except (OSError, json.JSONDecodeError):
                cleaned = []

        if not cleaned:
            for entry in sorted(os.listdir(self.maps_dir)):
                if not entry.lower().endswith(".json") or entry == os.path.basename(self.map_zones_manifest):
                    continue
                zone_path = os.path.join(self.maps_dir, entry)
                try:
                    with open(zone_path, "r", encoding="utf-8") as handle:
                        zone = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(zone, dict) and str(zone.get("name", "")).strip():
                    cleaned.append(zone)
            if cleaned:
                cleaned.sort(key=lambda item: str(item.get("name", "")).lower())
                self.offline_map_zones = cleaned
                self._save_offline_map_zones()

        cleaned.sort(key=lambda item: str(item.get("name", "")).lower())
        return cleaned

    def _save_offline_map_zones(self) -> None:
        payload = {"zones": self.offline_map_zones}
        with open(self.map_zones_manifest, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)

    def _load_map_update_timestamp(self) -> datetime | None:
        if not os.path.exists(self.map_update_state_file):
            return None
        try:
            with open(self.map_update_state_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            updated_at = payload.get("updated_at")
            if isinstance(updated_at, str):
                return datetime.fromisoformat(updated_at)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return None

    def _map_update_available(self) -> bool:
        if self.map_last_updated_at is None:
            return True
        return datetime.now() - self.map_last_updated_at >= timedelta(days=MAP_UPDATE_INTERVAL_DAYS)

    def _mark_map_updated(self) -> None:
        self.map_last_updated_at = datetime.now()
        payload = {"updated_at": self.map_last_updated_at.isoformat(timespec="seconds")}
        try:
            with open(self.map_update_state_file, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
        except OSError:
            self.last_command_label.setText("MAP update state save failed")
        self.map_update_banner_dismissed = False
        self._refresh_map_update_banner()

    def _refresh_map_update_banner(self) -> None:
        if not hasattr(self, "map_update_banner"):
            return
        visible = self._map_update_available() and not self.map_update_banner_dismissed
        self.map_update_banner.setVisible(visible)
        if visible:
            self._position_map_update_banner()

    def _dismiss_map_update_banner(self) -> None:
        self.map_update_banner_dismissed = True
        self._refresh_map_update_banner()

    def _position_map_update_banner(self) -> None:
        if not hasattr(self, "map_update_banner") or self.centralWidget() is None:
            return
        banner_width = min(self.map_update_banner.maximumWidth(), max(440, self.centralWidget().width() - 40))
        banner_height = self.map_update_banner.maximumHeight()
        x = (self.centralWidget().width() - banner_width) // 2
        y = 12
        self.map_update_banner.setGeometry(x, y, banner_width, banner_height)
        self.map_update_banner.raise_()

    def _upsert_offline_map_zone(self, zone: dict[str, object]) -> None:
        zone_name = str(zone.get("name", "")).strip()
        if not zone_name:
            return

        zone_copy = dict(zone)
        zone_copy["name"] = zone_name
        zone_copy["slug"] = slugify_name(zone_name)

        replaced = False
        for index, existing in enumerate(self.offline_map_zones):
            if str(existing.get("name", "")).strip().lower() == zone_name.lower():
                self.offline_map_zones[index] = zone_copy
                replaced = True
                break
        if not replaced:
            self.offline_map_zones.append(zone_copy)
        self.offline_map_zones.sort(key=lambda item: str(item.get("name", "")).lower())
        self._save_offline_map_zones()
        zone_file_path = map_zone_metadata_path(zone_name, self.maps_dir)
        with open(zone_file_path, "w", encoding="utf-8") as handle:
            json.dump(zone_copy, handle, indent=2, ensure_ascii=False)

    def _delete_offline_map_zone(self, zone_name: str) -> bool:
        normalized = zone_name.strip().lower()
        original_count = len(self.offline_map_zones)
        removed_zone: dict[str, object] | None = None
        kept: list[dict[str, object]] = []
        for zone in self.offline_map_zones:
            if str(zone.get("name", "")).strip().lower() == normalized and removed_zone is None:
                removed_zone = zone
                continue
            kept.append(zone)
        if removed_zone is None:
            return False

        self.offline_map_zones = kept
        self._save_offline_map_zones()
        zone_file_path = map_zone_metadata_path(str(removed_zone.get("name", "")), self.maps_dir)
        if os.path.exists(zone_file_path):
            os.remove(zone_file_path)
        return len(self.offline_map_zones) != original_count

    def _rename_offline_map_zone(self, old_name: str, new_name: str) -> bool:
        old_normalized = old_name.strip().lower()
        target_name = new_name.strip()
        if not target_name:
            return False
        if any(str(zone.get("name", "")).strip().lower() == target_name.lower() for zone in self.offline_map_zones if str(zone.get("name", "")).strip().lower() != old_normalized):
            return False

        for zone in self.offline_map_zones:
            if str(zone.get("name", "")).strip().lower() == old_normalized:
                old_file = map_zone_metadata_path(str(zone.get("name", "")), self.maps_dir)
                zone["name"] = target_name
                zone["slug"] = slugify_name(target_name)
                zone["updated_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_offline_map_zones()
                new_file = map_zone_metadata_path(target_name, self.maps_dir)
                with open(new_file, "w", encoding="utf-8") as handle:
                    json.dump(zone, handle, indent=2, ensure_ascii=False)
                if os.path.exists(old_file) and os.path.abspath(old_file) != os.path.abspath(new_file):
                    os.remove(old_file)
                return True
        return False

    def _setup_device_gps_fallback(self) -> None:
        source = QGeoPositionInfoSource.createDefaultSource(self)
        if source is None:
            return

        self.device_position_source = source
        self.device_position_source.setPreferredPositioningMethods(QGeoPositionInfoSource.PositioningMethod.AllPositioningMethods)
        self.device_position_source.setUpdateInterval(1000)
        self.device_position_source.positionUpdated.connect(self._handle_device_position_update)
        self.device_position_source.errorOccurred.connect(self._handle_device_position_error)

        try:
            last_known = self.device_position_source.lastKnownPosition()
        except TypeError:
            last_known = None
        if last_known is not None and last_known.isValid():
            self._handle_device_position_update(last_known)

        self.device_position_source.startUpdates()

    def _handle_device_position_update(self, info: QGeoPositionInfo) -> None:
        coordinate = info.coordinate()
        if not coordinate.isValid():
            return

        latitude = float(coordinate.latitude())
        longitude = float(coordinate.longitude())
        speed_kmh: float | None = None
        altitude: float | None = None
        heading: float | None = None

        if info.hasAttribute(QGeoPositionInfo.Attribute.GroundSpeed):
            speed_value = float(info.attribute(QGeoPositionInfo.Attribute.GroundSpeed))
            if np.isfinite(speed_value):
                speed_kmh = max(0.0, speed_value * 3.6)

        altitude_value = float(coordinate.altitude())
        if np.isfinite(altitude_value):
            altitude = altitude_value

        if info.hasAttribute(QGeoPositionInfo.Attribute.Direction):
            direction_value = float(info.attribute(QGeoPositionInfo.Attribute.Direction))
            if np.isfinite(direction_value):
                heading = direction_value % 360.0

        if heading is None and self.device_position_fix is not None:
            distance_hint = np.hypot(latitude - self.device_position_fix.latitude, longitude - self.device_position_fix.longitude)
            if distance_hint > 1e-6:
                heading = bearing_between_coordinates(
                    self.device_position_fix.latitude,
                    self.device_position_fix.longitude,
                    latitude,
                    longitude,
                )

        self.device_position_fix = PositionFix(
            latitude=latitude,
            longitude=longitude,
            speed_kmh=speed_kmh,
            altitude=altitude,
            heading=heading,
            timestamp=time.monotonic(),
        )

        if not self._telemetry_has_real_gps:
            self._apply_device_gps_to_map()

    def _handle_device_position_error(self, error) -> None:
        if self._telemetry_has_real_gps:
            return
        error_name = getattr(error, "name", str(error))
        if self.device_position_fix is None:
            self.last_command_label.setText(f"Device GPS: {error_name}")

    def _merge_device_position(self, data: SensorData) -> SensorData:
        if data.latitude is not None and data.longitude is not None:
            return data
        if self.device_position_fix is None:
            return data

        merged = replace(
            data,
            latitude=self.device_position_fix.latitude,
            longitude=self.device_position_fix.longitude,
            position_source="device",
        )
        if self.device_position_fix.speed_kmh is not None:
            merged.gps_speed = self.device_position_fix.speed_kmh
        if self.device_position_fix.altitude is not None and merged.altitude <= 0.0:
            merged.altitude = self.device_position_fix.altitude
        if data.heading_source != "drone" and self.device_position_fix.heading is not None:
            merged.heading = self.device_position_fix.heading
            merged.heading_source = "device"
        return merged

    def _apply_device_gps_to_map(self) -> None:
        if self.device_position_fix is None:
            return

        map_data = self._merge_device_position(self.current_data)
        if map_data.latitude is None or map_data.longitude is None:
            return
        self.map_widget.update_from_data(map_data)
        self._update_sender_label(map_data)

    def _update_sender_label(self, data: SensorData) -> None:
        if data.latitude is None or data.longitude is None:
            self.sender_label.setText(data.sender)
            return

        if data.position_source == "device":
            self.sender_label.setText(f"{data.sender}  |  Device GPS  {data.latitude:.5f}, {data.longitude:.5f}")
            return

        self.sender_label.setText(f"{data.sender}  |  {data.latitude:.5f}, {data.longitude:.5f}")

    def _open_offline_zone_dialog(
        self,
        *,
        selected_name: str | None = None,
        center_latitude: float | None = None,
        center_longitude: float | None = None,
        current_zoom: int | None = None,
    ) -> dict[str, object] | None:
        dialog = OfflineMapZoneDialog(
            self.offline_map_zones,
            current_zoom=current_zoom if current_zoom is not None else self.map_widget.zoom_level,
            center_latitude=center_latitude if center_latitude is not None else self.map_widget.center_latitude,
            center_longitude=center_longitude if center_longitude is not None else self.map_widget.center_longitude,
            selected_name=selected_name,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.zone_spec()

    def _queue_offline_zone_download(
        self,
        *,
        zone_name: str,
        center_latitude: float,
        center_longitude: float,
        display_zoom: int,
        zoom_min: int,
        zoom_max: int,
        padding_tiles: int,
        refresh_cache: bool = False,
        global_map_update: bool = False,
        save_zone: bool = True,
    ) -> bool:
        self._show_map_screen()
        self.map_widget.focus_on_coordinates(center_latitude, center_longitude, display_zoom)
        if refresh_cache:
            if global_map_update and not self._map_update_available():
                self._show_map_already_updated_notice()
                return False
            invalidated = self.map_widget.invalidate_visible_tiles(
                padding_tiles=padding_tiles,
                min_zoom=zoom_min,
                max_zoom=zoom_max,
                center_latitude=center_latitude,
                center_longitude=center_longitude,
            )
            self.map_update_refresh_pending = global_map_update
            update_label = "MAP update" if global_map_update else "MAP zone update"
            self.last_command_label.setText(f"{update_label}: {invalidated} tiles refreshed")
        self.active_map_download_name = zone_name
        self.map_download_cancelled = False
        total = self.map_widget.prefetch_visible_tiles(
            padding_tiles=padding_tiles,
            min_zoom=zoom_min,
            max_zoom=zoom_max,
            center_latitude=center_latitude,
            center_longitude=center_longitude,
        )
        if total <= 0:
            self.last_command_label.setText("MAP offline unavailable")
            self.map_download_bar.hide()
            QMessageBox.information(
                self,
                "Aucune zone telechargee",
                "Impossible de telecharger cette zone. Verifier la carte, le zoom ou la connexion.",
                QMessageBox.Ok,
            )
            self.active_map_download_name = None
            return False

        if save_zone:
            self._upsert_offline_map_zone(
                {
                    "name": zone_name,
                    "center_latitude": center_latitude,
                    "center_longitude": center_longitude,
                    "display_zoom": display_zoom,
                    "zoom_min": zoom_min,
                    "zoom_max": zoom_max,
                    "padding_tiles": padding_tiles,
                    "tile_count": total,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
        self.map_download_bar.setRange(0, total)
        self.map_download_bar.setValue(0)
        self.map_download_bar.show()
        self.last_command_label.setText(f"MAP offline {zone_name}: {total} tiles")
        return True

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)

        self.fullscreen_stack = QStackedWidget(central)
        self.fullscreen_stack.setObjectName("fullscreenStack")
        self.fullscreen_stack.lower()

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        self.map_update_banner = QFrame(central)
        self.map_update_banner.setObjectName("mapUpdateBanner")
        self.map_update_banner.setMinimumSize(440, 46)
        self.map_update_banner.setMaximumSize(520, 46)
        map_update_layout = QHBoxLayout(self.map_update_banner)
        map_update_layout.setContentsMargins(12, 6, 8, 6)
        map_update_layout.setSpacing(10)
        self.map_update_label = QLabel("Nouvelles mises a jour de carte disponibles")
        self.map_update_label.setObjectName("mapUpdateLabel")
        self.map_update_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.map_update_button = QPushButton("Update Map")
        self.map_update_button.setObjectName("mapUpdateButton")
        self.map_update_close_button = QPushButton("X")
        self.map_update_close_button.setObjectName("mapUpdateCloseButton")
        self.map_update_close_button.setFixedSize(28, 28)
        map_update_layout.addWidget(self.map_update_label, 1)
        map_update_layout.addWidget(self.map_update_button)
        map_update_layout.addWidget(self.map_update_close_button)
        self.map_update_banner.hide()
        self.map_update_banner.raise_()

        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)
        root_layout.addLayout(top_bar)

        top_left = QHBoxLayout()
        top_left.setContentsMargins(0, 0, 0, 0)
        top_left.setSpacing(0)
        top_center = QVBoxLayout()
        top_center.setContentsMargins(0, 0, 0, 0)
        top_center.setSpacing(4)
        top_right = QHBoxLayout()
        top_right.setContentsMargins(0, 0, 0, 0)
        top_right.setSpacing(0)

        self.network_panel = DashboardCard("", compact=True)
        self.network_panel.setMinimumWidth(250)
        self.network_panel.setMaximumWidth(285)
        self.network_panel.setMinimumHeight(76)
        self.network_panel.setMaximumHeight(88)
        network_layout = self.network_panel.layout
        network_layout.setContentsMargins(6, 6, 6, 4)
        network_layout.setSpacing(2)

        network_actions = QHBoxLayout()
        network_actions.setSpacing(6)
        self.network_apply_button = QPushButton("Connect")
        self.network_apply_button.setMinimumWidth(120)
        self.network_apply_button.setMinimumHeight(28)
        self.menu_button = QPushButton("Menu")
        self.menu_button.setMinimumSize(56, 28)
        self.menu_button.setMaximumHeight(28)
        network_actions.addWidget(self.network_apply_button, 1)
        network_actions.addWidget(self.menu_button)
        network_layout.addLayout(network_actions)

        # Ligne d'état : Nom appareil / GPS + horodatage
        status_row = QHBoxLayout()
        status_row.setContentsMargins(1, 1, 1, 0)
        status_row.setSpacing(4)
        self.sender_label = QLabel("Waiting")
        self.sender_label.setObjectName("metricHint")
        self.sender_label.setStyleSheet("font-size: 9px; font-weight: 700; color: #38bdf8;")
        self.last_update_label = QLabel("--:--:--")
        self.last_update_label.setObjectName("metricHint")
        self.last_update_label.setStyleSheet("font-size: 9px; color: #64748b;")
        self.last_update_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_row.addWidget(self.sender_label, 1)
        status_row.addWidget(self.last_update_label)
        network_layout.addLayout(status_row)

        # Ligne de retour de commande / hint
        self.last_command_label = QLabel("Hold 2s on gauge / DATA / Map")
        self.last_command_label.setObjectName("metricHint")
        self.last_command_label.setStyleSheet("font-size: 9px; color: #94a3b8; padding: 0 1px;")
        self.last_command_label.setWordWrap(False)
        self.last_command_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        network_layout.addWidget(self.last_command_label)

        self.log_label = QLabel(f"{os.path.basename(self.database_path)} | {os.path.basename(self.log_file_path)}")
        self.log_label.hide()
        self.network_panel.setToolTip(f"DB: {os.path.basename(self.database_path)}  |  Log: {os.path.basename(self.log_file_path)}")

        top_left.addWidget(self.network_panel, 0, Qt.AlignLeft)

        self.is_armed = False
        self.flight_mode_panel = DashboardCard("Flight Mode", compact=True)
        self.flight_mode_panel.setMinimumWidth(380)
        self.flight_mode_panel.setMaximumWidth(440)
        flight_mode_layout = self.flight_mode_panel.layout

        # Flight Modes Row
        mode_block = QHBoxLayout()
        mode_block.setSpacing(4)
        self.scan_mode_button = QPushButton("Scan")
        self.hold_mode_button = QPushButton("Hold")
        self.stabilize_mode_button = QPushButton("Stab")
        self.rtl_mode_button = QPushButton("RTL")
        self.land_mode_button = QPushButton("Land")
        for button in (self.scan_mode_button, self.hold_mode_button, self.stabilize_mode_button, self.rtl_mode_button, self.land_mode_button):
            button.setCheckable(True)
            mode_block.addWidget(button)
        flight_mode_layout.addLayout(mode_block)

        # Critical Flight Actions Row
        crit_block = QHBoxLayout()
        crit_block.setSpacing(5)
        self.arm_button = QPushButton("DISARMED")
        self.arm_button.setObjectName("armButton")
        self.arm_button.setToolTip("Armer / Désarmer les moteurs (Ctrl+A)")
        self.arm_button.setStyleSheet("background-color: #064e3b; color: #10b981; font-weight: 800; border: 1px solid #10b981; border-radius: 4px; padding: 3px 8px;")

        self.takeoff_button = QPushButton("TAKEOFF")
        self.takeoff_button.setObjectName("takeoffButton")
        self.takeoff_button.setToolTip("Décollage assisté avec altitude (Ctrl+T)")
        self.takeoff_button.setStyleSheet("background-color: #083344; color: #06b6d4; font-weight: 700; border: 1px solid #06b6d4; border-radius: 4px; padding: 3px 8px;")

        self.kill_button = QPushButton("KILL")
        self.kill_button.setObjectName("killButton")
        self.kill_button.setToolTip("ARRÊT D'URGENCE MOTEURS (Ctrl+Shift+K)")
        self.kill_button.setStyleSheet("background-color: #450a0a; color: #ef4444; font-weight: 800; border: 1px solid #ef4444; border-radius: 4px; padding: 3px 8px;")

        self.shortcuts_btn = QPushButton("?")
        self.shortcuts_btn.setToolTip("Aide raccourcis clavier (F1)")
        self.shortcuts_btn.setFixedWidth(26)
        self.shortcuts_btn.setStyleSheet("background-color: #1e293b; color: #94a3b8; font-weight: 700; border-radius: 4px;")

        crit_block.addWidget(self.arm_button, 2)
        crit_block.addWidget(self.takeoff_button, 2)
        crit_block.addWidget(self.kill_button, 2)
        crit_block.addWidget(self.shortcuts_btn, 1)
        flight_mode_layout.addLayout(crit_block)

        top_center.addWidget(self.flight_mode_panel, 0, Qt.AlignHCenter)

        self.battery_alert_card = DashboardCard("", compact=False)
        self.battery_alert_card.setParent(central)
        self.battery_alert_card.setMinimumWidth(380)
        self.battery_alert_card.setMaximumWidth(440)
        self.battery_alert_card.setMinimumHeight(50)
        self.battery_alert_card.setMaximumHeight(50)
        self.battery_alert_card.layout.setContentsMargins(8, 10, 8, 8)
        self.battery_alert_label = QLabel("LOW BATTERY")
        self.battery_alert_label.setAlignment(Qt.AlignCenter)
        self.battery_alert_label.setStyleSheet("color: #ff4d4f; font-size: 15px; font-weight: 900;")
        self.battery_alert_card.layout.addWidget(self.battery_alert_label, 1, Qt.AlignCenter)
        self.battery_alert_effect = QGraphicsOpacityEffect(self.battery_alert_card)
        self.battery_alert_effect.setOpacity(0.0)
        self.battery_alert_card.setGraphicsEffect(self.battery_alert_effect)
        self.battery_alert_card.raise_()

        self.flight_panel = DashboardCard("Flight", compact=True)
        self.flight_panel.setMinimumWidth(250)
        self.flight_panel.setMaximumWidth(250)
        flight_info_row = QHBoxLayout()
        flight_info_row.setContentsMargins(6, 0, 6, 0)
        flight_info_row.setSpacing(4)
        self.flight_gps_label = QLabel("GPS 00")
        self.flight_batt_label = QLabel("BATT 100")
        self.flight_signal_label = QLabel("SIGNAL 8")
        for label in (
            self.flight_gps_label,
            self.flight_batt_label,
            self.flight_signal_label,
        ):
            label.setObjectName("summaryValue")
            label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.flight_batt_label.setTextFormat(Qt.RichText)
        self.flight_batt_effect = QGraphicsOpacityEffect(self.flight_batt_label)
        self.flight_batt_effect.setOpacity(1.0)
        self.flight_batt_label.setGraphicsEffect(self.flight_batt_effect)
        flight_info_row.addWidget(self.flight_gps_label, 1)
        flight_info_row.addWidget(self.flight_batt_label, 1)
        flight_info_row.addWidget(self.flight_signal_label, 1)
        self.flight_panel.layout.addLayout(flight_info_row)
        top_right.addWidget(self.flight_panel, 0, Qt.AlignRight)
        top_bar.addLayout(top_left, 1)
        top_bar.addLayout(top_center, 1)
        top_bar.addLayout(top_right, 1)
        self.flight_mode_group = QButtonGroup(self)
        self.flight_mode_group.setExclusive(True)
        self.flight_mode_group.addButton(self.scan_mode_button)
        self.flight_mode_group.addButton(self.hold_mode_button)
        self.flight_mode_group.addButton(self.stabilize_mode_button)
        self.flight_mode_group.addButton(self.rtl_mode_button)
        self.flight_mode_group.addButton(self.land_mode_button)
        self.stabilize_mode_button.setChecked(True)

        body_layout = QHBoxLayout()
        body_layout.setSpacing(10)
        root_layout.addLayout(body_layout, 1)

        left_column = QVBoxLayout()
        left_column.setSpacing(10)
        center_column = QVBoxLayout()
        center_column.setSpacing(10)
        right_column = QVBoxLayout()
        right_column.setSpacing(10)

        body_layout.addLayout(left_column, 23)
        body_layout.addLayout(center_column, 54)
        body_layout.addLayout(right_column, 23)

        left_panel_height = 250
        left_panel_width = 285

        self.attitude_card = DashboardCard("Attitude")
        self.attitude_card.setMinimumWidth(left_panel_width)
        self.attitude_card.setMaximumWidth(left_panel_width)
        self.attitude_card.setMinimumHeight(left_panel_height)
        self.attitude_card.setMaximumHeight(left_panel_height)
        left_column.addWidget(self.attitude_card, 4)
        attitude_row = QHBoxLayout()
        attitude_row.setSpacing(4)
        self.attitude_card.layout.addLayout(attitude_row, 1)
        self.speed_tape = TapeGaugeWidget("SPD", "km/h", 0.0, 160.0, "#5ec8f8")
        self.horizon_widget = ArtificialHorizonWidget()
        self.altitude_tape = TapeGaugeWidget("ALT", "m", 0.0, 1500.0, "#f7c86e")
        attitude_row.addWidget(self.speed_tape)
        attitude_row.addWidget(self.horizon_widget, 1)
        attitude_row.addWidget(self.altitude_tape)
        self.nav_card = DashboardCard("Nav")
        self.nav_card.setMinimumWidth(left_panel_width)
        self.nav_card.setMaximumWidth(left_panel_width)
        self.nav_card.setMinimumHeight(left_panel_height)
        self.nav_card.setMaximumHeight(left_panel_height)
        left_column.addWidget(self.nav_card, 4)
        self.compass_widget = CompassWidget()
        self.compass_widget.setMinimumSize(180, 180)
        self.compass_widget.setMaximumSize(360, 340)
        self.nav_card.layout.addWidget(self.compass_widget, 1)
        self.nav_left_info_label = QLabel("DIST 50")
        self.nav_left_info_label.setObjectName("metricHint")
        self.nav_left_info_label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self.nav_right_info_label = QLabel("VS 2")
        self.nav_right_info_label.setObjectName("metricHint")
        self.nav_right_info_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        nav_footer = QHBoxLayout()
        nav_footer.setSpacing(6)
        nav_footer.addWidget(self.nav_left_info_label, 1)
        nav_footer.addWidget(self.nav_right_info_label, 1)
        self.nav_card.layout.addLayout(nav_footer)

        self.display_card = DashboardCard("Display")
        center_column.addWidget(self.display_card, 10)
        self.display_stack = QStackedWidget()
        self.display_card.layout.addWidget(self.display_stack, 1)

        # ── Vue DATA : QTabWidget 3 onglets ────────────────────────────────
        self.data_tab_widget = QTabWidget()
        self.data_tab_widget.setObjectName("dataTabs")
        self.data_tab_widget.setStyleSheet("""
            QTabWidget#dataTabs::pane {
                border: none;
                background: transparent;
            }
            QTabWidget#dataTabs > QTabBar::tab {
                background: #0d1926;
                color: #5a7ea8;
                font-size: 10px;
                font-weight: 700;
                padding: 5px 16px;
                border: 1px solid #1e2d45;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabWidget#dataTabs > QTabBar::tab:selected {
                background: #102035;
                color: #67e8f9;
                border-color: #2a4a6a;
            }
            QTabWidget#dataTabs > QTabBar::tab:hover:!selected {
                background: #152233;
                color: #94c5e8;
            }
        """)

        # Onglet 1 — FLIGHT (graphiques de vol)
        self.flight_data_chart = FlightDataChartWidget()
        self.data_tab_widget.addTab(self.flight_data_chart, "✈ FLIGHT")

        # Onglet 2 — AIR (données capteurs chimiques)
        self.data_chart = TelemetryChartWidget()
        self.data_tab_widget.addTab(self.data_chart, "🌡 AIR")

        # Onglet 3 — LOG (journal de mission)
        self.flight_log_inline = FlightLogWidget()
        self.data_tab_widget.addTab(self.flight_log_inline, "📋 LOG")

        self.display_stack.addWidget(self.data_tab_widget)
        self.display_stack.setCurrentWidget(self.data_tab_widget)

        self.fullscreen_empty_page = QWidget()
        self.fullscreen_empty_page.setObjectName("fullscreenEmptyPage")
        self.fullscreen_stack.addWidget(self.fullscreen_empty_page)

        self.fullscreen_video_page = QWidget()
        fullscreen_video_layout = QVBoxLayout(self.fullscreen_video_page)
        fullscreen_video_layout.setContentsMargins(0, 0, 0, 0)
        fullscreen_video_layout.setSpacing(0)
        self.video_osd = VideoOSDWidget(self.fullscreen_video_page)
        self.video_label = QLabel()
        self.video_label.hide()
        fullscreen_video_layout.addWidget(self.video_osd, 1)

        self.video_overlay = QLabel(central)
        self.video_overlay.setAlignment(Qt.AlignCenter)
        self.video_overlay.setObjectName("videoOverlay")
        self.video_overlay.setText("NO SIGNAL")
        self.video_overlay.setStyleSheet(
            "color: #ff4d4f; font-size: 28px; font-weight: 800;"
        )
        self.video_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.video_overlay_effect = QGraphicsOpacityEffect(self.video_overlay)
        self.video_overlay.setGraphicsEffect(self.video_overlay_effect)
        self.video_overlay_alpha = 0.0
        self.video_overlay_direction = 1.0
        self.video_overlay_effect.setOpacity(self.video_overlay_alpha)
        self.video_overlay_timer = QTimer(self)
        self.video_overlay_timer.setInterval(16)
        self.video_overlay_timer.timeout.connect(self._update_video_overlay_fade)
        self.video_overlay.hide()
        self.video_overlay.raise_()
        self.fullscreen_stack.addWidget(self.fullscreen_video_page)

        self.map_widget = OfflineMapWidget()
        self.map_widget.controls_visible = False
        self.fullscreen_stack.addWidget(self.map_widget)
        self.fullscreen_stack.setCurrentWidget(self.fullscreen_empty_page)

        self.pip_window = PipWindowWidget(central)
        self.pip_window.swap_requested.connect(self._handle_pip_swap)
        self.pip_window.close_requested.connect(lambda: self.pip_window.hide())
        self.pip_window.hide()

        self.map_view_button = LongPressButton("Map")
        self.live_view_button = LongPressButton("Live")
        self.thermal_view_button = LongPressButton("Thermal")
        for button in (self.map_view_button, self.live_view_button, self.thermal_view_button):
            button.setCheckable(True)
        self.display_mode_group = QButtonGroup(self)
        self.display_mode_group.setExclusive(True)
        self.display_mode_group.addButton(self.map_view_button)
        self.display_mode_group.addButton(self.live_view_button)
        self.display_mode_group.addButton(self.thermal_view_button)
        self.live_view_button.setChecked(True)

        self.data_button = LongPressButton("DATA")
        self._set_placeholder_thermal()
        self.map_download_bar = QProgressBar()
        self.map_download_bar.setObjectName("mapDownloadBar")
        self.map_download_bar.setTextVisible(False)
        self.map_download_bar.setRange(0, 100)
        self.map_download_bar.setValue(0)
        self.map_download_bar.hide()
        self.display_card.layout.addWidget(self.map_download_bar)

        self.map_center_button = QPushButton()
        self.map_zones_button = QPushButton()
        for button, icon_name, fallback_text in (
            (self.map_center_button, "centrage.png", "C"),
            (self.map_zones_button, "zone.png", "Z"),
        ):
            icon_path = asset_path("img", icon_name)
            if os.path.exists(icon_path):
                button.setIcon(QIcon(icon_path))
                button.setIconSize(QSize(16, 16))
            else:
                button.setText(fallback_text)
            button.setMinimumSize(28, 28)
            button.setMaximumSize(28, 28)
        self.map_actions_row = QHBoxLayout()
        self.map_actions_row.setSpacing(4)
        self.map_actions_row.addWidget(self.map_center_button)
        self.map_actions_row.addWidget(self.map_zones_button)
        center_column.addStretch(1)
        center_column.addLayout(self.map_actions_row, 0)
        self.map_center_button.hide()
        self.map_zones_button.hide()

        self.mission_card = DashboardCard("VIEW", compact=True)
        self.mission_card.setMaximumHeight(60)
        center_column.addWidget(self.mission_card, 0)
        view_buttons = QHBoxLayout()
        view_buttons.setSpacing(6)
        for button in (self.map_view_button, self.live_view_button, self.thermal_view_button, self.data_button):
            view_buttons.addWidget(button)
        self.mission_card.layout.addLayout(view_buttons)

        self.science_card = DashboardCard("Air Data")
        self.science_card.setMaximumWidth(285)
        self.science_card.setMaximumHeight(250)
        right_column.addWidget(self.science_card, 5)
        self.science_grid = QGridLayout()
        self.science_grid.setSpacing(4)
        self.science_card.layout.addLayout(self.science_grid)

        self.co2_gauge = CircularGaugeWidget("CO2", "ppm", "#5ec8f8", 10000.0)
        self.lpg_gauge = CircularGaugeWidget("LPG", "ppm", "#f7c86e", 10000.0)
        self.humidity_gauge = CircularGaugeWidget("Hum", "%", "#79e3d8", 100.0)
        self.temperature_gauge = CircularGaugeWidget("Temp", "C", "#ffb86c", 100.0, threshold=40.0)

        self._relayout_science_gauges()

        self.radiation_card = DashboardCard("Radiation")
        self.radiation_card.setMaximumWidth(285)
        self.radiation_card.setMaximumHeight(170)
        right_column.addWidget(self.radiation_card, 3)

        self.sparkline = SparklineWidget("#ff7b72")
        self.radiation_card.layout.addWidget(self.sparkline, 1)
        radiation_row = QHBoxLayout()
        radiation_row.setSpacing(10)
        self.radiation_info_label = QLabel("0 CPS")
        self.radiation_info_label.setObjectName("metricHint")
        self.radiation_info_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.radiation_dose_label = QLabel("0 uSv/h")
        self.radiation_dose_label.setObjectName("metricHint")
        self.radiation_dose_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        radiation_row.addWidget(self.radiation_info_label, 1)
        radiation_row.addWidget(self.radiation_dose_label, 1)
        self.radiation_card.layout.addLayout(radiation_row)

        self.sensor_states = {"gas": False, "dht": False, "geiger": False}
        for widget in (self.co2_gauge, self.lpg_gauge):
            widget.hold_activated.connect(lambda key="gas": self._toggle_sensor(key))
        for widget in (self.humidity_gauge, self.temperature_gauge):
            widget.hold_activated.connect(lambda key="dht": self._toggle_sensor(key))

        # ── Panneau Alertes contextuelles ────────────────────────────────────
        self.alert_card = DashboardCard("Alertes de vol")
        self.alert_card.setMaximumWidth(285)
        self.alert_card.setMaximumHeight(180)
        right_column.addWidget(self.alert_card, 3)
        self.alert_banner = AlertBannerWidget()
        self.alert_card.layout.addWidget(self.alert_banner, 1)

        # ── Journal de mission ───────────────────────────────────────────────
        self.flight_log_card = DashboardCard("Journal de mission")
        self.flight_log_card.setMaximumWidth(285)
        right_column.addWidget(self.flight_log_card, 5)
        self.flight_log = FlightLogWidget()
        self.flight_log_card.layout.addWidget(self.flight_log, 1)
        # Connexion : double-clic sur événement → centrer carte
        self.flight_log.event_clicked.connect(
            lambda lat, lon: self.map_widget.center_on(lat, lon)
            if hasattr(self.map_widget, 'center_on') else None
        )

        self.last_command_label.setText(self._tr("last_command_hint"))
        self._update_network_button()

        self.floating_panels = {
            "left": FloatingScreenWidget("left", "LEFT SCREEN", central),
            "right": FloatingScreenWidget("right", "RIGHT SCREEN", central),
            "radar": FloatingRadarWidget(central),
        }
        for panel in self.floating_panels.values():
            panel.hide()
            if isinstance(panel, FloatingScreenWidget):
                panel.mode_requested.connect(self._set_floating_panel_mode)
                panel.swap_requested.connect(self._swap_floating_panel_with_primary)

        self._apply_language()
        self._apply_theme(self.current_theme)
        self._apply_responsive_layout()
        left_column.addStretch(1)
        right_column.addStretch(1)

    def _theme_stylesheet(self, theme: str) -> str:
        if theme == "light":
            return """
            /* ═══ LIGHT THEME ═══════════════════════════════════════════════ */
            QWidget#root {
                background: transparent;
                color: #1a2e42;
                font-family: 'Segoe UI', sans-serif;
            }
            QStackedWidget#fullscreenStack, QWidget#fullscreenEmptyPage {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #d6e9f8, stop:0.5 #e4f0fb, stop:1 #eef5fb);
            }
            /* ── Inputs & Dialogs ── */
            QDialog {
                background: #f0f7fd;
                color: #1a2e42;
                border: 1px solid #b8d0e8;
                border-radius: 12px;
            }
            QListWidget, QComboBox, QSpinBox, QLineEdit {
                background: #ffffff;
                color: #1a2e42;
                border: 1px solid #c0d6ea;
                border-radius: 8px;
                selection-background-color: #cce5ff;
                selection-color: #0d2136;
                padding: 3px 6px;
            }
            QLineEdit {
                padding: 6px 10px;
                border-radius: 9px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #4aa3d8;
                background: #f5faff;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            /* ── Labels ── */
            QLabel#pageTitle {
                font-size: 26px;
                font-weight: 800;
                color: #122438;
            }
            QLabel#pageSubtitle { color: #5a7490; font-size: 13px; }
            QLabel#cardTitle    { color: #1a2e42; font-size: 11px; font-weight: 700; }
            QLabel#cardSubtitle { color: #5a7490; font-size: 10px; }
            QLabel#metricValue  { color: #0e1f30; font-size: 18px; font-weight: 800; }
            QLabel#metricHint   { color: #5a7490; font-size: 10px; }
            QLabel#sectionLabel { color: #223650; font-size: 10px; font-weight: 700; }
            QLabel#summaryCaption { color: #5a7490; font-size: 10px; font-weight: 700; }
            QLabel#summaryValue   { color: #0e1f30; font-size: 11px; font-weight: 700; }
            QLabel#videoLabel     { background: transparent; border-radius: 12px; border: 1px solid #c0d6ea; }
            QLabel#videoOverlay   { color: #5a7490; font-size: 11px; padding: 6px 0 8px 0; }
            QLabel#floatingTitle  { color: #0e1f30; font-size: 10px; font-weight: 900; }
            QLabel#mapUpdateLabel { color: #0e1f30; font-size: 11px; font-weight: 800; }
            /* ── Frames ── */
            QFrame#summaryStrip {
                background: rgba(255,255,255,0.82);
                border: 1px solid #c8dcea;
                border-radius: 12px;
            }
            QFrame#mapUpdateBanner {
                background: rgba(240,247,253,0.95);
                border: 1px solid #b8d0e8;
                border-radius: 10px;
            }
            QFrame#floatingScreen {
                background: rgba(245,251,255,0.95);
                border: 1px solid #c0d6ea;
                border-radius: 10px;
            }
            QLabel#floatingVideo, QWidget#floatingData {
                background: #e8f3fc;
                color: #0e1f30;
                border: 1px solid #c0d6ea;
                border-radius: 8px;
            }
            /* ── Buttons ── */
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #e8f3fc);
                border: 1px solid #b8d0e8;
                border-radius: 9px;
                color: #1a2e42;
                font-size: 11px;
                font-weight: 700;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e8f5ff, stop:1 #d0eafc);
                border-color: #78b8df;
            }
            QPushButton:pressed {
                background: #c8e4f8;
                border-color: #4a9acc;
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #cce8ff, stop:1 #b0d8f8);
                border-color: #3d9fd8;
                color: #0d2136;
            }
            QPushButton#mapUpdateButton, QPushButton#mapUpdateCloseButton {
                padding: 5px 10px;
                border-radius: 8px;
            }
            /* ── Scrollbars ultra-fines ── */
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #a8c8e0;
                border-radius: 3px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover { background: #78aacf; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal {
                background: transparent;
                height: 6px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #a8c8e0;
                border-radius: 3px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover { background: #78aacf; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            /* ── Menus ── */
            QMenu {
                background: #f2f8fd;
                border: 1px solid #b8d0e8;
                border-radius: 10px;
                padding: 4px;
                color: #1a2e42;
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background: #d0eafc;
                color: #0d2136;
            }
            QMenu::separator {
                height: 1px;
                background: #c8dcea;
                margin: 3px 8px;
            }
            /* ── ProgressBar ── */
            QProgressBar#mapDownloadBar {
                min-height: 7px; max-height: 7px;
                border-radius: 3px;
                border: 1px solid #c0d6ea;
                background: #e0eef8;
            }
            QProgressBar#mapDownloadBar::chunk {
                border-radius: 3px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4ab8f0, stop:1 #78d8ff);
            }
            """
        # ═══ DARK THEME (Cockpit Tactique / HUD) ═════════════════════════════
        return """
        /* ── Base ── */
        QWidget#root {
            background: transparent;
            color: #d8e8ff;
            font-family: 'Segoe UI', sans-serif;
        }
        QStackedWidget#fullscreenStack, QWidget#fullscreenEmptyPage {
            background: qlineargradient(x1:0, y1:0, x2:0.6, y2:1,
                stop:0 #060d18, stop:0.5 #09121e, stop:1 #0b1628);
        }
        /* ── Inputs & Dialogs ── */
        QDialog {
            background: #0b1525;
            color: #d8e8ff;
            border: 1px solid #1e3a58;
            border-radius: 12px;
        }
        QListWidget, QComboBox, QSpinBox, QLineEdit {
            background: #0a1422;
            color: #d8e8ff;
            border: 1px solid #1e3a58;
            border-radius: 8px;
            selection-background-color: #0f3a58;
            selection-color: #e8f4ff;
            padding: 3px 6px;
        }
        QLineEdit {
            padding: 6px 10px;
            border-radius: 9px;
        }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
            border: 1px solid #00b4d8;
            background: #0c1a30;
        }
        QComboBox::drop-down {
            border: none;
            width: 20px;
        }
        QComboBox QAbstractItemView {
            background: #0b1525;
            color: #d8e8ff;
            border: 1px solid #1e3a58;
            border-radius: 8px;
            selection-background-color: #0f3a58;
        }
        /* ── Labels ── */
        QLabel#pageTitle {
            font-size: 26px;
            font-weight: 800;
            color: #e8f4ff;
        }
        QLabel#pageSubtitle { color: #6a9abf; font-size: 13px; }
        QLabel#cardTitle    { color: #e0eeff; font-size: 11px; font-weight: 700; }
        QLabel#cardSubtitle { color: #6a9abf; font-size: 10px; }
        QLabel#metricValue  { color: #f0f8ff; font-size: 18px; font-weight: 800; }
        QLabel#metricHint   { color: #6a9abf; font-size: 10px; }
        QLabel#sectionLabel { color: #c8deff; font-size: 10px; font-weight: 700; }
        QLabel#summaryCaption { color: #5e8ab0; font-size: 10px; font-weight: 700; }
        QLabel#summaryValue   { color: #d8e8ff; font-size: 11px; font-weight: 700; }
        QLabel#videoLabel     { background: transparent; border-radius: 12px; border: 1px solid #1c3850; }
        QLabel#videoOverlay   { color: #6a9abf; font-size: 11px; padding: 6px 0 8px 0; }
        QLabel#floatingTitle  { color: #d8e8ff; font-size: 10px; font-weight: 900; }
        QLabel#mapUpdateLabel { color: #d8e8ff; font-size: 11px; font-weight: 800; }
        /* ── Frames ── */
        QFrame#summaryStrip {
            background: rgba(8, 18, 34, 0.80);
            border: 1px solid #1e3a58;
            border-radius: 12px;
        }
        QFrame#mapUpdateBanner {
            background: rgba(8, 16, 30, 0.95);
            border: 1px solid #1e4060;
            border-radius: 10px;
        }
        QFrame#floatingScreen {
            background: rgba(8, 16, 30, 0.95);
            border: 1px solid #1e4060;
            border-radius: 10px;
        }
        QFrame#floatingRadar {
            background: rgba(6, 13, 26, 0.82);
            border: 1px solid #1e4868;
            border-radius: 10px;
        }
        QLabel#floatingVideo, QWidget#floatingData {
            background: #080f1e;
            color: #d8e8ff;
            border: 1px solid #1a3450;
            border-radius: 8px;
        }
        /* ── Buttons — base ── */
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #142238, stop:1 #0c1826);
            border: 1px solid #1e3858;
            border-radius: 9px;
            color: #c8dcf8;
            font-size: 11px;
            font-weight: 700;
            padding: 6px 12px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #1c3050, stop:1 #142844);
            border-color: #2e80b8;
            color: #e0f0ff;
        }
        QPushButton:pressed {
            background: #0d1e34;
            border-color: #1e6090;
        }
        /* ── Buttons — modes de vol colorés par état ── */
        QPushButton:checked {
            border-color: #00bfea;
            color: #e8f8ff;
            font-weight: 800;
        }
        /* Scan → vert radar */
        QPushButton[text="Scan"]:checked, QPushButton[text="SCAN"]:checked {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #054028, stop:1 #032a1a);
            border-color: #00e676;
            color: #a0ffca;
        }
        /* Hold → ambre / pause */
        QPushButton[text="Hold"]:checked, QPushButton[text="HOLD"]:checked {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3d2600, stop:1 #261800);
            border-color: #ffab00;
            color: #ffe082;
        }
        /* Stab → cyan / stabilisé */
        QPushButton[text="Stab"]:checked, QPushButton[text="STAB"]:checked {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #003a5c, stop:1 #002540);
            border-color: #00bfea;
            color: #80e8ff;
        }
        /* Land → rouge alerte */
        QPushButton[text="Land"]:checked, QPushButton[text="LAND"]:checked {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4a0016, stop:1 #30000e);
            border-color: #ff3366;
            color: #ff99b4;
        }
        /* Boutons de vue (Map/Live/Thermal/DATA) */
        QPushButton[text="Map"]:checked, QPushButton[text="Live"]:checked,
        QPushButton[text="Thermal"]:checked, QPushButton[text="DATA"]:checked {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #0a2a48, stop:1 #062038);
            border-color: #00bfea;
            color: #a0e8ff;
        }
        QPushButton#mapUpdateButton, QPushButton#mapUpdateCloseButton {
            padding: 5px 10px;
            border-radius: 8px;
        }
        /* ── Scrollbars ultra-fines ── */
        QScrollBar:vertical {
            background: transparent;
            width: 6px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background: rgba(50, 100, 160, 0.6);
            border-radius: 3px;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover {
            background: rgba(0, 190, 230, 0.7);
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal {
            background: transparent;
            height: 6px;
            margin: 0;
        }
        QScrollBar::handle:horizontal {
            background: rgba(50, 100, 160, 0.6);
            border-radius: 3px;
            min-width: 20px;
        }
        QScrollBar::handle:horizontal:hover {
            background: rgba(0, 190, 230, 0.7);
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        /* ── Menus ── */
        QMenu {
            background: #09131f;
            border: 1px solid #1c3858;
            border-radius: 10px;
            padding: 4px;
            color: #d8e8ff;
        }
        QMenu::item {
            padding: 6px 14px;
            border-radius: 6px;
        }
        QMenu::item:selected {
            background: rgba(0, 160, 220, 0.18);
            color: #a8e8ff;
        }
        QMenu::separator {
            height: 1px;
            background: #1a3450;
            margin: 3px 8px;
        }
        /* ── ProgressBar ── */
        QProgressBar#mapDownloadBar {
            min-height: 7px; max-height: 7px;
            border-radius: 3px;
            border: 1px solid #1a3450;
            background: #080f1e;
        }
        QProgressBar#mapDownloadBar::chunk {
            border-radius: 3px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #00a8d8, stop:1 #00e5ff);
        }
        """

    def _apply_theme(self, theme: str) -> None:
        self.current_theme = theme if theme in {"dark", "light"} else "dark"
        self.setStyleSheet(self._theme_stylesheet(self.current_theme))
        for panel in self.findChildren(DashboardCard):
            panel.set_theme(self.current_theme)
        self.map_widget.set_theme(self.current_theme)
        self.data_chart.set_theme(self.current_theme)
        if hasattr(self, "flight_data_chart"):
            self.flight_data_chart.set_theme(self.current_theme)
        for widget in (
            self.speed_tape,
            self.horizon_widget,
            self.altitude_tape,
            self.compass_widget,
            self.co2_gauge,
            self.lpg_gauge,
            self.humidity_gauge,
            self.temperature_gauge,
            self.sparkline,
        ):
            widget.set_theme(self.current_theme)
        for panel in self.floating_panels.values():
            panel.set_theme(self.current_theme)

    def _set_card_bounds(
        self,
        card: QWidget,
        *,
        width: int | None = None,
        max_width: int | None = None,
        height: int | None = None,
        max_height: int | None = None,
    ) -> None:
        if width is not None:
            card.setMinimumWidth(width)
            card.setMaximumWidth(width)
        elif max_width is not None:
            card.setMinimumWidth(0)
            card.setMaximumWidth(max_width)
        else:
            card.setMinimumWidth(0)
            card.setMaximumWidth(16_777_215)

        if height is not None:
            card.setMinimumHeight(height)
            card.setMaximumHeight(height)
        elif max_height is not None:
            card.setMinimumHeight(0)
            card.setMaximumHeight(max_height)
        else:
            card.setMinimumHeight(0)
            card.setMaximumHeight(16_777_215)

    def _apply_responsive_layout(self) -> None:
        if self.centralWidget() is None or not hasattr(self, "attitude_card"):
            return

        width = max(self.centralWidget().width(), self.width())
        phone = width < 760
        tablet = 760 <= width < 1180

        side_visible = not phone
        for widget in (self.attitude_card, self.nav_card, self.science_card, self.radiation_card):
            widget.setVisible(side_visible)
        if not hasattr(self, "_user_panel_visibility"):
            self._user_panel_visibility = {"flight_alerts": True, "flight_log": True}
        if hasattr(self, "alert_card"):
            self.alert_card.setVisible(side_visible and self._user_panel_visibility.get("flight_alerts", True))
        if hasattr(self, "flight_log_card"):
            self.flight_log_card.setVisible(side_visible and self._user_panel_visibility.get("flight_log", True))

        if phone:
            self._set_card_bounds(self.network_panel, max_width=180, max_height=80)
            self._set_card_bounds(self.flight_mode_panel, max_width=320, max_height=66)
            self._set_card_bounds(self.flight_panel, max_width=185, max_height=52)
            self._set_card_bounds(self.battery_alert_card, width=320, height=46)
            self.mission_card.setMaximumHeight(54)
            self.display_card.setMinimumHeight(360)
            self.map_widget.setMinimumHeight(260)
            self.network_apply_button.setMinimumWidth(92)
            self.menu_button.setMinimumWidth(54)
            for button in (self.scan_mode_button, self.hold_mode_button, self.stabilize_mode_button, self.rtl_mode_button, self.land_mode_button):
                button.setMinimumWidth(0)
                button.setMaximumHeight(26)
            return

        if tablet:
            side_width = 220
            side_height = 210
            self._set_card_bounds(self.network_panel, width=220, max_height=82)
            self._set_card_bounds(self.flight_mode_panel, width=370, max_height=70)
            self._set_card_bounds(self.flight_panel, width=220, max_height=56)
            self._set_card_bounds(self.battery_alert_card, width=370, height=48)
            self._set_card_bounds(self.attitude_card, width=side_width, height=side_height)
            self._set_card_bounds(self.nav_card, width=side_width, height=side_height)
            self._set_card_bounds(self.science_card, width=side_width, max_height=220)
            self._set_card_bounds(self.radiation_card, width=side_width, max_height=150)
            self.compass_widget.setMinimumSize(145, 145)
            self.compass_widget.setMaximumSize(240, 220)
            self.mission_card.setMaximumHeight(58)
            self.display_card.setMinimumHeight(420)
            self.map_widget.setMinimumHeight(300)
            self.network_apply_button.setMinimumWidth(112)
            self.menu_button.setMinimumWidth(58)
            for button in (self.scan_mode_button, self.hold_mode_button, self.stabilize_mode_button, self.rtl_mode_button, self.land_mode_button):
                button.setMinimumWidth(0)
                button.setMaximumHeight(28)
            return

        side_width = 285
        side_height = 250
        self._set_card_bounds(self.network_panel, width=280, max_height=16_777_215)
        self._set_card_bounds(self.flight_mode_panel, width=420, max_height=16_777_215)
        self._set_card_bounds(self.flight_panel, width=250, max_height=16_777_215)
        self._set_card_bounds(self.battery_alert_card, width=420, height=50)
        self._set_card_bounds(self.attitude_card, width=side_width, height=side_height)
        self._set_card_bounds(self.nav_card, width=side_width, height=side_height)
        self._set_card_bounds(self.science_card, width=side_width, max_height=250)
        self._set_card_bounds(self.radiation_card, width=side_width, max_height=170)
        self.compass_widget.setMinimumSize(180, 180)
        self.compass_widget.setMaximumSize(360, 340)
        self.mission_card.setMaximumHeight(60)
        self.display_card.setMinimumHeight(0)
        self.map_widget.setMinimumHeight(320)
        self.network_apply_button.setMinimumWidth(130)
        self.menu_button.setMinimumWidth(58)
        for button in (self.scan_mode_button, self.hold_mode_button, self.stabilize_mode_button, self.rtl_mode_button, self.land_mode_button):
            button.setMinimumWidth(0)
            button.setMaximumHeight(16_777_215)

    def _ensure_map_download_dialog(self) -> OfflineMapDownloadDialog:
        if self.map_download_dialog is None:
            self.map_download_dialog = OfflineMapDownloadDialog(self)
            self.map_download_dialog.cancel_requested.connect(self._cancel_map_download)
        self.map_download_dialog.set_language(self.current_language)
        return self.map_download_dialog

    def _populate_main_menu(self, menu: QMenu) -> None:
        menu.aboutToHide.connect(self._handle_main_menu_hidden)
        # Écrans secondaires & radar
        menu.addAction(self._menu_toggle_action(menu, self._tr("right_screen"), "right"))
        menu.addAction(self._menu_toggle_action(menu, self._tr("left_screen"), "left"))
        menu.addAction(self._menu_toggle_action(menu, self._tr("radar_360"), "radar"))
        # Panneaux télémétrie de vol (Alertes & Journal)
        menu.addAction(self._menu_toggle_action(menu, self._tr("flight_alerts"), "flight_alerts"))
        menu.addAction(self._menu_toggle_action(menu, self._tr("flight_log"), "flight_log"))
        menu.addAction(self._menu_toggle_action(menu, "PiP (Picture-in-Picture) (P)", "pip"))
        menu.addAction(self._menu_toggle_action(menu, "OSD Telemetrie (O)", "osd"))
        menu.addSeparator()
        # Raccourcis clavier (F1)
        shortcuts_action = menu.addAction(f"⌨  {self._tr('shortcuts')} (F1)")
        shortcuts_action.triggered.connect(self._show_shortcuts_dialog)
        menu.addSeparator()
        # Paramètres (Langues, Sons)
        self._add_settings_submenu(menu)

    def _show_main_menu(self) -> None:
        if self.main_menu_popup is not None and self.main_menu_popup.isVisible():
            self.main_menu_popup.close()
            return

        menu = QMenu(self)
        self.main_menu_popup = menu
        self._populate_main_menu(menu)
        self.main_menu_anchor_pos = self.menu_button.mapToGlobal(self.menu_button.rect().bottomLeft())
        menu.popup(self.main_menu_anchor_pos)

    def _handle_main_menu_hidden(self) -> None:
        self.main_menu_popup = None
        if not self.keep_main_menu_open:
            return
        self.keep_main_menu_open = False
        QTimer.singleShot(0, self._reopen_main_menu)

    def _reopen_main_menu(self) -> None:
        if self.main_menu_popup is not None and self.main_menu_popup.isVisible():
            return
        menu = QMenu(self)
        self.main_menu_popup = menu
        self._populate_main_menu(menu)
        menu.popup(self.main_menu_anchor_pos)

    def _schedule_main_menu_reopen(self) -> None:
        self.keep_main_menu_open = True
        QTimer.singleShot(120, self._reopen_main_menu)

    def _tr(self, key: str, **values: object) -> str:
        text = UI_TEXTS.get(self.current_language, UI_TEXTS["en"]).get(key, UI_TEXTS["en"].get(key, key))
        return text.format(**values) if values else text

    def _set_card_title(self, card: DashboardCard, key: str) -> None:
        card.title = self._tr(key)
        card.update()

    def _set_language(self, language: str) -> None:
        if language not in UI_TEXTS:
            return
        self.current_language = language
        self._apply_language()

    def _apply_language(self) -> None:
        self.menu_button.setText(self._tr("menu"))
        self.map_update_label.setText(self._tr("map_updates_available"))
        self.map_update_button.setText(self._tr("update_map"))
        self._set_card_title(self.flight_mode_panel, "flight_mode")
        self._set_card_title(self.flight_panel, "flight")
        self._set_card_title(self.attitude_card, "attitude")
        self._set_card_title(self.nav_card, "nav")
        self._set_card_title(self.display_card, "display")
        self._set_card_title(self.mission_card, "view")
        self._set_card_title(self.science_card, "air_data")
        self._set_card_title(self.radiation_card, "radiation")
        if hasattr(self, "alert_card"):
            self._set_card_title(self.alert_card, "flight_alerts")
        if hasattr(self, "flight_log_card"):
            self._set_card_title(self.flight_log_card, "flight_log")
        self.scan_mode_button.setText(self._tr("scan"))
        self.hold_mode_button.setText(self._tr("hold"))
        self.stabilize_mode_button.setText(self._tr("stab"))
        self.rtl_mode_button.setText(self._tr("rtl"))
        self.land_mode_button.setText(self._tr("land"))
        self.takeoff_button.setText(self._tr("takeoff"))
        self.kill_button.setText(self._tr("kill_motors"))
        self._update_arm_button_visual()
        self.map_view_button.setText(self._tr("map"))
        self.live_view_button.setText(self._tr("live"))
        self.thermal_view_button.setText(self._tr("thermal"))
        self.data_button.setText(self._tr("data"))
        self.video_overlay.setText(self._tr("no_signal"))
        self.data_chart.set_language(self.current_language)
        if self.sender_label.text() in {"Waiting", "Attente"}:
            self.sender_label.setText(self._tr("waiting"))
        if self.last_command_label.text() in {
            UI_TEXTS["en"]["last_command_hint"],
            UI_TEXTS["fr"]["last_command_hint"],
        }:
            self.last_command_label.setText(self._tr("last_command_hint"))
        elif self.last_command_label.text() in {
            UI_TEXTS["en"]["data_live"],
            UI_TEXTS["fr"]["data_live"],
        }:
            self.last_command_label.setText(self._tr("data_live"))
        self.battery_alert_label.setText(
            self._tr("auto_landing")
            if self.battery_alert_state in {"critical", "landing"} or self.low_battery_land_acknowledged
            else self._tr("low_battery")
        )
        if hasattr(self, "floating_panels"):
            for panel in self.floating_panels.values():
                panel.set_language(self.current_language)
        if self.map_download_dialog is not None:
            self.map_download_dialog.set_language(self.current_language)
        self._update_network_button()

    def _add_language_submenu(self, menu: QMenu) -> None:
        language_menu = menu.addMenu(self._tr("languages"))
        for language, key in (("fr", "french"), ("en", "english")):
            action = language_menu.addAction(self._tr(key))
            action.setCheckable(True)
            action.setChecked(self.current_language == language)
            action.triggered.connect(lambda _checked=False, selected=language: self._handle_menu_language_change(selected))

    def _add_settings_submenu(self, menu: QMenu) -> None:
        settings_menu = menu.addMenu(self._tr("settings"))
        self._add_language_submenu(settings_menu)
        sounds_action = settings_menu.addAction(self._tr("sounds"))
        sounds_action.setCheckable(True)
        sounds_action.setChecked(self.sounds_enabled)
        sounds_action.triggered.connect(self._handle_menu_sounds_change)

    def _handle_menu_language_change(self, language: str) -> None:
        self._schedule_main_menu_reopen()
        self._set_language(language)

    def _handle_menu_sounds_change(self, enabled: bool) -> None:
        self._schedule_main_menu_reopen()
        self._set_sounds_enabled(enabled)

    def _set_sounds_enabled(self, enabled: bool) -> None:
        self.sounds_enabled = enabled
        if enabled:
            if self.battery_alert_state == "low" and self.low_battery_warning_file:
                self._play_low_battery_audio()
                self.low_battery_audio_timer.start()
            elif self.battery_alert_state == "critical" or self.low_battery_land_acknowledged:
                self._start_landing_audio_sequence()
            return
        self.low_battery_audio_mode = "idle"
        self.low_battery_audio_timer.stop()
        if self.low_battery_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.low_battery_player.stop()

    def _is_panel_visible(self, panel_key: str) -> bool:
        if panel_key in self.floating_panels:
            return self.floating_panels[panel_key].isVisible()
        if panel_key == "flight_alerts":
            card = getattr(self, "alert_card", None)
            return card.isVisible() if card is not None else False
        if panel_key == "flight_log":
            card = getattr(self, "flight_log_card", None)
            return card.isVisible() if card is not None else False
        if panel_key == "pip":
            return self.pip_window.isVisible() if hasattr(self, "pip_window") else False
        if panel_key == "osd":
            return (self.video_osd.osd_mode != "OFF") if hasattr(self, "video_osd") else False
        return False

    def _menu_toggle_action(self, menu: QMenu, label: str, panel_key: str) -> QWidgetAction:
        action = QWidgetAction(menu)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)
        text = QLabel(label)
        is_visible = self._is_panel_visible(panel_key)
        button = QPushButton(self._tr("on") if is_visible else self._tr("off"))
        button.setCheckable(True)
        button.setChecked(is_visible)
        button.setMinimumWidth(54)
        button.clicked.connect(lambda checked, key=panel_key, toggle_button=button: self._handle_menu_toggle_click(toggle_button, key, checked))
        layout.addWidget(text, 1)
        layout.addWidget(button)
        action.setDefaultWidget(row)
        return action

    def _handle_menu_toggle_click(self, button: QPushButton, panel_key: str, visible: bool) -> None:
        button.setText(self._tr("on") if visible else self._tr("off"))
        if panel_key in self.floating_panels:
            self._toggle_floating_panel(panel_key, visible)
        elif panel_key == "flight_alerts":
            card = getattr(self, "alert_card", None)
            if card is not None:
                card.setVisible(visible)
                if not hasattr(self, "_user_panel_visibility"):
                    self._user_panel_visibility = {}
                self._user_panel_visibility["flight_alerts"] = visible
        elif panel_key == "flight_log":
            card = getattr(self, "flight_log_card", None)
            if card is not None:
                card.setVisible(visible)
                if not hasattr(self, "_user_panel_visibility"):
                    self._user_panel_visibility = {}
                self._user_panel_visibility["flight_log"] = visible
        elif panel_key == "pip":
            if hasattr(self, "pip_window"):
                self.pip_window.setVisible(visible)
                if visible:
                    self._reposition_pip_window()
                    self.pip_window.raise_()
        elif panel_key == "osd":
            if hasattr(self, "video_osd"):
                self.video_osd.set_osd_mode("FULL" if visible else "OFF")

    def _toggle_floating_panel(self, panel_key: str, visible: bool) -> None:
        panel = self.floating_panels.get(panel_key)
        if panel is None:
            return
        panel.setVisible(visible)
        if visible:
            if isinstance(panel, FloatingScreenWidget):
                self._set_floating_panel_mode(panel_key, panel.mode)
            panel.update_sensor_data(self.current_data)
            panel.update_video_frame("live", self.live_frame)
            panel.update_video_frame("thermal", self.thermal_frame)
            self._position_floating_panels()
            panel.raise_()

    def _other_floating_panel_key(self, panel_key: str) -> str:
        return "right" if panel_key == "left" else "left"

    def _set_floating_panel_mode(self, panel_key: str, mode: str) -> None:
        panel = self.floating_panels.get(panel_key)
        if not isinstance(panel, FloatingScreenWidget):
            return
        other = self.floating_panels.get(self._other_floating_panel_key(panel_key))
        if isinstance(other, FloatingScreenWidget) and other.isVisible() and other.mode == mode:
            other.set_mode(panel.mode)
        panel.set_mode(mode)
        self._refresh_floating_panels()

    def _show_primary_view(self, mode: str) -> None:
        if mode == "map":
            self._show_map_screen()
        elif mode == "live":
            self._show_live_screen()
        elif mode == "thermal":
            self._show_thermal_screen()
        elif mode == "data":
            self._show_live_data_screen()

    def _swap_floating_panel_with_primary(self, panel_key: str) -> None:
        panel = self.floating_panels.get(panel_key)
        if not isinstance(panel, FloatingScreenWidget) or not panel.isVisible():
            return
        old_primary = self.primary_view
        old_panel_mode = panel.mode
        other = self.floating_panels.get(self._other_floating_panel_key(panel_key))
        if isinstance(other, FloatingScreenWidget) and other.isVisible() and other.mode == old_primary:
            other.set_mode(old_panel_mode)
        panel.set_mode(old_primary)
        self._show_primary_view(old_panel_mode)
        self._refresh_floating_panels()

    def _position_floating_panels(self) -> None:
        left_panel = self.floating_panels.get("left")
        right_panel = self.floating_panels.get("right")
        radar_panel = self.floating_panels.get("radar")
        if left_panel is not None and left_panel.isVisible():
            anchor = self.nav_card.geometry()
            x = max(10, anchor.left())
            y = min(self.centralWidget().height() - left_panel.height() - 10, anchor.bottom() + 8)
            left_panel.move(x, max(10, y))
            left_panel.raise_()
        if right_panel is not None and right_panel.isVisible():
            anchor = self.radiation_card.geometry()
            x = max(10, anchor.right() - right_panel.width())
            y = min(self.centralWidget().height() - right_panel.height() - 10, anchor.bottom() + 8)
            right_panel.move(x, max(10, y))
            right_panel.raise_()
        if radar_panel is not None and radar_panel.isVisible():
            x = max(10, (self.centralWidget().width() - radar_panel.width()) // 2)
            y = max(10, min(self.centralWidget().height() - radar_panel.height() - 10, self.flight_panel.geometry().bottom() + 8))
            radar_panel.move(x, y)
            radar_panel.raise_()

    def _refresh_floating_panels(self) -> None:
        for panel in self.floating_panels.values():
            if not panel.isVisible():
                continue
            panel.update_sensor_data(self.current_data)
            panel.update_video_frame("live", self.live_frame)
            panel.update_video_frame("thermal", self.thermal_frame)

    def _connect_signals(self) -> None:
        self.scan_mode_button.clicked.connect(lambda: self._request_flight_mode_change("Scan"))
        self.hold_mode_button.clicked.connect(lambda: self._request_flight_mode_change("Hold"))
        self.stabilize_mode_button.clicked.connect(lambda: self._request_flight_mode_change("Stabilize"))
        self.rtl_mode_button.clicked.connect(lambda: self._request_flight_mode_change("RTL"))
        self.land_mode_button.clicked.connect(lambda: self._request_flight_mode_change("Land"))
        self.arm_button.clicked.connect(self._handle_arm_request)
        self.takeoff_button.clicked.connect(self._handle_takeoff_request)
        self.kill_button.clicked.connect(self._handle_emergency_kill_request)
        self.shortcuts_btn.clicked.connect(self._show_shortcuts_dialog)
        self.network_apply_button.clicked.connect(self._toggle_network_interface)
        self.menu_button.clicked.connect(self._show_main_menu)
        self.map_view_button.short_clicked.connect(self._show_map_screen)
        self.map_view_button.long_clicked.connect(self._download_visible_map_area)
        self.map_center_button.clicked.connect(self._recenter_map_on_position)
        self.map_zones_button.clicked.connect(self._show_saved_map_zones)
        self.map_update_button.clicked.connect(self._handle_map_update_banner_action)
        self.map_update_close_button.clicked.connect(self._dismiss_map_update_banner)
        self.live_view_button.short_clicked.connect(self._show_live_screen)
        self.live_view_button.long_clicked.connect(lambda: self._configure_video_source("live"))
        self.thermal_view_button.short_clicked.connect(self._show_thermal_screen)
        self.thermal_view_button.long_clicked.connect(lambda: self._configure_video_source("thermal"))
        self.data_button.short_clicked.connect(self._show_live_data_screen)
        self.data_button.long_clicked.connect(self._show_saved_data_screen)
        self._set_flight_mode("Stabilize")
        self._show_map_screen()
        self._connect_background_services()

        self.map_widget.offline_download_started.connect(self._show_map_download_started)
        self.map_widget.offline_download_progress.connect(self._show_map_download_progress)
        self.map_widget.offline_download_finished.connect(self._show_map_download_finished)
        self.map_widget.center_requested.connect(self._handle_map_center_button)
        self.map_widget.zones_requested.connect(self._show_saved_map_zones)
        self.map_widget.follow_state_changed.connect(lambda on: self.last_command_label.setText("Follow Drone: " + ("ON" if on else "OFF")))
        self.map_widget.waypoints_changed.connect(lambda wps: self.last_command_label.setText(f"Waypoints: {len(wps)} active"))
        self._setup_keyboard_shortcuts()
        QTimer.singleShot(0, self._restore_saved_video_streams)

    def _connect_background_services(self) -> None:
        self.thermal_receiver.frame_received.connect(self._update_thermal_frame)
        self.thermal_receiver.thermal_status.connect(self._show_thermal_status)
        self.command_client.command_logged.connect(self.last_command_label.setText)

    def _update_network_button(self) -> None:
        if self.network_connected:
            self.network_apply_button.setText(self._tr("connected", mode=self.network_mode))
        else:
            self.network_apply_button.setText(self._tr("connect"))

    def _parse_serial_profile(self, value: str) -> tuple[str, int]:
        text = value.strip()
        if "@" not in text:
            return text or "COM3", 115200
        port_name, raw_baud = text.split("@", 1)
        try:
            baudrate = int(raw_baud.strip())
        except ValueError:
            baudrate = 115200
        return port_name.strip() or "COM3", baudrate

    def _build_link_worker(self, mode: str, profile: str) -> QThread:
        if mode == "UDP":
            host, port = self._parse_host_port(profile, "0.0.0.0", 12345)
            return TelemetryListener(host=host, port=port)
        if mode == "TCP":
            host, port = self._parse_host_port(profile, "127.0.0.1", 12345)
            return TcpTelemetryListener(host=host, port=port)
        port_name, baudrate = self._parse_serial_profile(profile)
        return SerialTelemetryListener(port_name=port_name, baudrate=baudrate)

    def _attach_link_worker(self, worker: QThread) -> None:
        worker.telemetry_received.connect(self._apply_sensor_data)  # type: ignore[attr-defined]
        worker.telemetry_status.connect(self._handle_link_status)  # type: ignore[attr-defined]
        worker.telemetry_error.connect(self._handle_link_error)  # type: ignore[attr-defined]

    def _connect_selected_interface(self, mode: str, profile: str) -> None:
        self._disconnect_selected_interface()
        self.connection_profiles[mode] = profile
        self.network_mode = mode
        self.link_worker = self._build_link_worker(mode, profile)
        self._attach_link_worker(self.link_worker)
        self.network_apply_button.setText(self._tr("connecting", mode=mode))
        self.link_worker.start()
        self.network_connected = True
        self._update_network_button()
        self.last_command_label.setText(f"{mode} connect requested: {profile}")

    def _disconnect_selected_interface(self) -> None:
        if self.link_worker is not None:
            self.link_worker.stop()  # type: ignore[attr-defined]
            self.link_worker.wait(1500)
            self.link_worker = None
        self.network_connected = False
        self._update_network_button()

    def _toggle_network_interface(self) -> None:
        if self.network_connected:
            self._disconnect_selected_interface()
            self.last_command_label.setText("Network disconnected")
            return

        dialog = ConnectionInterfaceDialog(self.network_mode, self.connection_profiles, self)
        if dialog.exec() != QDialog.Accepted:
            return

        mode, profile = dialog.connection_profile()
        if not profile:
            self.last_command_label.setText("Connection cancelled: missing address")
            return
        self._connect_selected_interface(mode, profile)

    def _handle_link_status(self, message: str) -> None:
        self.network_connected = True
        self._update_network_button()
        self.last_command_label.setText(message)

    def _handle_link_error(self, message: str) -> None:
        self.last_command_label.setText(message)
        self.network_connected = False
        self._update_network_button()

    def _relayout_science_gauges(self) -> None:
        while self.science_grid.count():
            item = self.science_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        self.science_grid.addWidget(self.co2_gauge, 0, 0)
        self.science_grid.addWidget(self.lpg_gauge, 0, 1)
        self.science_grid.addWidget(self.humidity_gauge, 1, 0)
        self.science_grid.addWidget(self.temperature_gauge, 1, 1)

    @staticmethod
    def _normalize_video_source(protocol: str, address: str) -> str:
        text = address.strip()
        protocol_lower = protocol.lower()
        if not text:
            return ""
        if text.lower().startswith((f"{protocol_lower}://", "rtsp://", "udp://", "http://", "https://")):
            return text
        return f"{protocol_lower}://{text}"

    def _stop_video_stream(self, mode: str) -> None:
        worker = self.live_stream_worker if mode == "live" else self.thermal_stream_worker
        if worker is None:
            return
        worker.stop()
        worker.wait(1500)
        if mode == "live":
            self.live_stream_worker = None
        else:
            self.thermal_stream_worker = None

    def _start_video_stream(self, mode: str, protocol: str, address: str) -> None:
        source_url = self._normalize_video_source(protocol, address)
        if not source_url:
            self.last_command_label.setText(f"{mode.title()} source missing")
            return

        self._stop_video_stream(mode)
        worker = VideoStreamReceiver(source_url, mode.title())
        worker.frame_received.connect(lambda frame, current_mode=mode: self._update_video_stream_frame(current_mode, frame))
        worker.stream_status.connect(self.last_command_label.setText)
        worker.stream_error.connect(lambda message, current_mode=mode: self._handle_video_stream_error(current_mode, message))
        worker.start()

        if mode == "live":
            self.live_stream_protocol = protocol
            self.live_stream_address = address
            self.live_stream_worker = worker
        else:
            self.thermal_stream_protocol = protocol
            self.thermal_stream_address = address
            self.thermal_stream_worker = worker
        self._save_video_sources()

    def _restore_saved_video_streams(self) -> None:
        if self.live_stream_address:
            self._start_video_stream("live", self.live_stream_protocol, self.live_stream_address)
        if self.thermal_stream_address:
            self._start_video_stream("thermal", self.thermal_stream_protocol, self.thermal_stream_address)

    def _configure_video_source(self, mode: str) -> None:
        current_protocol = self.live_stream_protocol if mode == "live" else self.thermal_stream_protocol
        current_address = self.live_stream_address if mode == "live" else self.thermal_stream_address
        dialog = VideoSourceDialog(f"{mode.title()} video source", current_protocol, current_address, self)
        if dialog.exec() != QDialog.Accepted:
            return

        protocol, address = dialog.source_profile()
        if not address:
            self.last_command_label.setText(f"{mode.title()} source cancelled")
            return

        self._start_video_stream(mode, protocol, address)
        if mode == "live":
            self._show_live_screen()
        else:
            self._show_thermal_screen()

    def _show_centered_notice(self, title: str, message: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(252, 128)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(10)

        content_row = QHBoxLayout()
        content_row.setSpacing(10)

        icon_label = QLabel()
        icon = dialog.style().standardIcon(QStyle.SP_MessageBoxWarning)
        icon_label.setPixmap(icon.pixmap(22, 22))
        icon_label.setAlignment(Qt.AlignCenter)

        label = QLabel(message)
        label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        label.setWordWrap(True)
        label.setObjectName("sectionLabel")

        layout.addStretch(1)
        content_row.addWidget(icon_label, 0, Qt.AlignVCenter)
        content_row.addWidget(label, 1)
        layout.addLayout(content_row)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons, 0, Qt.AlignRight)
        dialog.exec()

    def _update_video_stream_frame(self, mode: str, frame: QImage) -> None:
        if mode == "live":
            self.live_frame = frame
        else:
            self.thermal_frame = frame

        if self.fullscreen_stack.currentWidget() is self.fullscreen_video_page and self.active_video_mode == mode:
            self.video_overlay.hide()
            self._render_current_frame()
        self._refresh_floating_panels()

    def _handle_video_stream_error(self, mode: str, message: str) -> None:
        self.last_command_label.setText(message)
        if mode == "live":
            self.live_frame = None
            if self.live_stream_worker is not None and not self.live_stream_worker.isRunning():
                self.live_stream_worker = None
        else:
            self.thermal_frame = None
            if self.thermal_stream_worker is not None and not self.thermal_stream_worker.isRunning():
                self.thermal_stream_worker = None

        if self.fullscreen_stack.currentWidget() is self.fullscreen_video_page and self.active_video_mode == mode:
            self._refresh_display_panel()

    def _set_flight_mode(self, mode: str) -> None:
        self.flight_mode = mode
        button_map = {
            "Scan": self.scan_mode_button,
            "Hold": self.hold_mode_button,
            "Stabilize": self.stabilize_mode_button,
            "RTL": self.rtl_mode_button,
            "Land": self.land_mode_button,
        }
        active_button = button_map.get(mode)
        if active_button is not None and not active_button.isChecked():
            active_button.setChecked(True)
        self.last_command_label.setText(f"Flight mode: {mode}")

    def _flight_mode_label(self, mode: str) -> str:
        labels = {
            "Scan": self._tr("scan"),
            "Hold": self._tr("hold"),
            "Stabilize": self._tr("stab"),
            "RTL": self._tr("rtl"),
            "Land": self._tr("land"),
        }
        return labels.get(mode, mode)

    def _request_flight_mode_change(self, mode: str) -> None:
        previous_mode = getattr(self, "flight_mode", "Scan")
        if mode == previous_mode:
            self._set_flight_mode(previous_mode)
            return

        level = "warning" if mode in {"Land", "RTL"} else "info"
        title = self._tr("flight_mode_confirm_title")
        msg = self._tr("flight_mode_confirm_message", mode=self._flight_mode_label(mode))
        confirm_txt = "VALIDER" if self.current_language == "fr" else "CONFIRM"
        confirmed = ActionConfirmationDialog.confirm(self, title, msg, level=level, confirm_text=confirm_txt)
        if not confirmed:
            self._set_flight_mode(previous_mode)
            return

        if mode == "Land":
            self._handle_land_mode_request()
            return
        if mode == "RTL":
            self._handle_rtl_mode_request()
            return

        if self.low_battery_land_acknowledged and self.battery_alert_state != "critical":
            self._stop_low_battery_alert()
        self._set_flight_mode(mode)
        self._play_flight_mode_audio(mode)

    def _handle_rtl_mode_request(self) -> None:
        self._set_flight_mode("RTL")
        self.command_client.send_command("RTL")
        self.last_command_label.setText("Flight mode: RTL (Return to Base)")
        for log in (getattr(self, 'flight_log', None), getattr(self, 'flight_log_inline', None)):
            if log is not None:
                log.log_event("rtl", "Retour base RTL",
                              lat=self.current_data.latitude or None,
                              lon=self.current_data.longitude or None)
        if hasattr(self, 'flight_data_chart'):
            self.flight_data_chart.add_event_marker("🏠 RTL", "#a78bfa")

    def _handle_arm_request(self) -> None:
        is_fr = self.current_language == "fr"
        if not self.is_armed:
            title = "ARMEMENT DES MOTEURS" if is_fr else "ARM DRONE MOTORS"
            msg = (
                "ATTENTION : L'armement active les moteurs et fait tourner les h\u00e9lices. "
                "Assurez-vous que l'espace imm\u00e9diat autour du drone est enti\u00e8rement d\u00e9gag\u00e9."
                if is_fr
                else "WARNING: Arming activates motor output and spins propellers. Ensure operating perimeter is completely clear."
            )
            if ActionConfirmationDialog.confirm(self, title, msg, level="warning", confirm_text="ARMER" if is_fr else "ARM MOTORS"):
                self.is_armed = True
                self.command_client.send_command("ARM")
                self._update_arm_button_visual()
                self.last_command_label.setText("Drone: MOTORS ARMED")
                # Journal de mission
                for log in (getattr(self, 'flight_log', None), getattr(self, 'flight_log_inline', None)):
                    if log is not None:
                        log.start_mission()
                        log.log_event("arm", "Moteurs ARM\u00c9S",
                                      lat=self.current_data.latitude or None,
                                      lon=self.current_data.longitude or None)
                if hasattr(self, 'flight_data_chart'):
                    self.flight_data_chart.reset()
                self._flight_log_events_seen.clear()
        else:
            title = "D\u00c9SARMEMENT DES MOTEURS" if is_fr else "DISARM DRONE MOTORS"
            msg = "Couper l'armement des moteurs maintenant ?" if is_fr else "Disarm motors now?"
            if ActionConfirmationDialog.confirm(self, title, msg, level="info", confirm_text="D\u00c9SARMER" if is_fr else "DISARM"):
                self.is_armed = False
                self.command_client.send_command("DISARM")
                self._update_arm_button_visual()
                self.last_command_label.setText("Drone: MOTORS DISARMED")
                for log in (getattr(self, 'flight_log', None), getattr(self, 'flight_log_inline', None)):
                    if log is not None:
                        log.log_event("disarm", "Moteurs D\u00c9SARM\u00c9S")


    def _update_arm_button_visual(self) -> None:
        is_fr = self.current_language == "fr"
        if self.is_armed:
            self.arm_button.setText("ARMÉ" if is_fr else "ARMED")
            self.arm_button.setStyleSheet(
                "background-color: #581c87; color: #f43f5e; font-weight: 800; border: 2px solid #f43f5e; border-radius: 4px; padding: 3px 8px;"
            )
        else:
            self.arm_button.setText("DÉSARMÉ" if is_fr else "DISARMED")
            self.arm_button.setStyleSheet(
                "background-color: #064e3b; color: #10b981; font-weight: 800; border: 1px solid #10b981; border-radius: 4px; padding: 3px 8px;"
            )

    def _handle_takeoff_request(self) -> None:
        alt = TakeoffAltitudeDialog.get_altitude(self, default_alt=5.0)
        if alt is not None:
            if not self.is_armed:
                self.is_armed = True
                self.command_client.send_command("ARM")
                self._update_arm_button_visual()
            self.command_client.send_command(f"TAKEOFF {alt:.1f}")
            self.last_command_label.setText(f"Takeoff ordered: {alt:.1f} m")
            for log in (getattr(self, 'flight_log', None), getattr(self, 'flight_log_inline', None)):
                if log is not None:
                    log.log_event("takeoff", f"D\u00e9collage → {alt:.1f}m",
                                  lat=self.current_data.latitude or None,
                                  lon=self.current_data.longitude or None)
            if hasattr(self, 'flight_data_chart'):
                self.flight_data_chart.add_event_marker("\ud83d\udef3 TKF", "#06b6d4")


    def _handle_emergency_kill_request(self) -> None:
        is_fr = self.current_language == "fr"
        title = "ARRÊT D'URGENCE (KILL MOTORS)" if is_fr else "EMERGENCY STOP (KILL MOTORS)"
        msg = (
            "DANGER CRITIQUE : Cette action coupe instantanément l'alimentation de TOUS les moteurs. "
            "Le drone va chuter immédiatement s'il est en vol !"
            if is_fr
            else "CRITICAL DANGER: This immediately cuts power to ALL motors. The drone will fall out of the sky if airborne!"
        )
        if ActionConfirmationDialog.confirm(self, title, msg, level="danger", confirm_text="COUPER LES MOTEURS" if is_fr else "KILL MOTORS NOW"):
            self.command_client.send_command("KILL")
            self.is_armed = False
            self._update_arm_button_visual()
            self.last_command_label.setText("EMERGENCY KILL SWITCH TRIGGERED")
            for log in (getattr(self, 'flight_log', None), getattr(self, 'flight_log_inline', None)):
                if log is not None:
                    log.log_event("kill", "💥 KILL SWITCH ACTIVÉ")
            if hasattr(self, 'alert_banner'):
                self.alert_banner.push_alert("💥 KILL SWITCH activé !", "critical", auto_dismiss=30)

    def _show_shortcuts_dialog(self) -> None:
        dlg = KeyboardShortcutsDialog(self)
        dlg.exec()

    def _toggle_fullscreen_mode(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _setup_keyboard_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+A"), self, self._handle_arm_request)
        QShortcut(QKeySequence("Ctrl+T"), self, self._handle_takeoff_request)
        QShortcut(QKeySequence("Ctrl+R"), self, lambda: self._request_flight_mode_change("RTL"))
        QShortcut(QKeySequence("Ctrl+L"), self, lambda: self._request_flight_mode_change("Land"))
        QShortcut(QKeySequence("Space"), self, lambda: self._request_flight_mode_change("Hold"))
        QShortcut(QKeySequence("Ctrl+Shift+K"), self, self._handle_emergency_kill_request)
        QShortcut(QKeySequence("1"), self, lambda: self._request_flight_mode_change("Scan"))
        QShortcut(QKeySequence("2"), self, lambda: self._request_flight_mode_change("Hold"))
        QShortcut(QKeySequence("3"), self, lambda: self._request_flight_mode_change("Stabilize"))
        QShortcut(QKeySequence("4"), self, lambda: self._request_flight_mode_change("RTL"))
        QShortcut(QKeySequence("5"), self, lambda: self._request_flight_mode_change("Land"))
        QShortcut(QKeySequence("C"), self, self.map_widget.recenter_on_current_position)
        QShortcut(QKeySequence("F"), self, self.map_widget.toggle_follow_drone)
        QShortcut(QKeySequence("W"), self, self.map_widget.toggle_add_waypoint_mode)
        QShortcut(QKeySequence("Delete"), self, self.map_widget.clear_waypoints)
        QShortcut(QKeySequence("F1"), self, self._show_shortcuts_dialog)
        QShortcut(QKeySequence("F11"), self, self._toggle_fullscreen_mode)
        QShortcut(QKeySequence("M"), self, self._show_map_screen)
        QShortcut(QKeySequence("V"), self, self._show_live_screen)
        QShortcut(QKeySequence("T"), self, self._show_thermal_screen)
        QShortcut(QKeySequence("D"), self, self._show_live_data_screen)
        QShortcut(QKeySequence("O"), self, self._toggle_osd_mode)
        QShortcut(QKeySequence("P"), self, self._toggle_pip_window)

    def _handle_land_mode_request(self) -> None:
        if self.battery_alert_state == "critical":
            self._engage_automatic_landing()
            return
        self.low_battery_land_acknowledged = True
        self.land_mode_button.setStyleSheet("")
        self._set_flight_mode("Land")
        self.command_client.send_command("LAND")
        self._start_landing_visual_alert()
        self._start_landing_audio_sequence()
        self.last_command_label.setText("Flight mode: Land")
        for log in (getattr(self, 'flight_log', None), getattr(self, 'flight_log_inline', None)):
            if log is not None:
                log.log_event("land", "Atterrissage ordonn\u00e9",
                              lat=self.current_data.latitude or None,
                              lon=self.current_data.longitude or None)
        if hasattr(self, 'flight_data_chart'):
            self.flight_data_chart.add_event_marker("\ud83d\udeec LND", "#f59e0b")


    def _engage_automatic_landing(self) -> None:
        self.low_battery_land_acknowledged = True
        self._set_flight_mode("Land")
        self.command_client.send_command("LAND")
        if not self.low_battery_alert_active:
            self._start_landing_visual_alert()
        if self.low_battery_audio_mode not in {"autoland_once", "landing_loop"}:
            self._start_landing_audio_sequence()
        self.last_command_label.setText("Critical battery: auto landing")

    def _set_flight_mode_buttons_enabled(self, enabled: bool) -> None:
        for button in (
            self.scan_mode_button,
            self.hold_mode_button,
            self.stabilize_mode_button,
            self.rtl_mode_button,
            self.land_mode_button,
            self.arm_button,
            self.takeoff_button,
        ):
            button.setEnabled(enabled)

    def _play_flight_mode_audio(self, mode: str) -> None:
        audio_path = self.flight_mode_audio_files.get(mode, "")
        if audio_path:
            self._play_audio_file(audio_path, f"flight_mode_{mode.lower()}", loops=QMediaPlayer.Loops.Once)

    def _play_audio_file(self, audio_path: str, mode: str, *, loops: int = 1) -> None:
        if not self.sounds_enabled or not audio_path:
            return
        if self.low_battery_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.low_battery_player.stop()
        self.low_battery_audio_mode = mode
        self.low_battery_player.setLoops(loops)
        self.low_battery_player.setSource(QUrl.fromLocalFile(audio_path))
        self.low_battery_player.setPosition(0)
        self.low_battery_player.play()

    def _start_landing_audio_sequence(self) -> None:
        self.low_battery_audio_timer.stop()
        if self.autoland_alert_audio_file:
            self._play_audio_file(
                self.autoland_alert_audio_file,
                "autoland_once",
                loops=QMediaPlayer.Loops.Once,
            )
            return
        if self.landing_alert_audio_file:
            self._play_audio_file(
                self.landing_alert_audio_file,
                "landing_loop",
                loops=QMediaPlayer.Loops.Infinite,
            )

    def _handle_low_battery_media_status(self, status) -> None:
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if self.low_battery_audio_mode in {"autoland_once", "critical_once"} and self.low_battery_land_acknowledged and self.landing_alert_audio_file:
            self._play_audio_file(
                self.landing_alert_audio_file,
                "landing_loop",
                loops=QMediaPlayer.Loops.Infinite,
            )

    def _play_low_battery_audio(self) -> None:
        if self.battery_alert_state != "low" or not self.low_battery_warning_file:
            return
        self._play_audio_file(self.low_battery_warning_file, "low", loops=QMediaPlayer.Loops.Once)

    def _start_landing_visual_alert(self) -> None:
        entering_new_state = self.battery_alert_state != "landing"
        self.low_battery_alert_active = True
        self.battery_alert_state = "landing"
        if entering_new_state:
            self.low_battery_alert_alpha = 0.0
            self.low_battery_alert_direction = 1.0
            self.flight_batt_effect.setOpacity(1.0)
        self.battery_alert_label.setText(self._tr("auto_landing"))
        self.low_battery_flash_timer.start()
        self._update_low_battery_alert_visuals()

    def _start_low_battery_alert(self, *, critical: bool = False) -> None:
        entering_new_state = self.battery_alert_state != ("critical" if critical else "low")
        self.low_battery_alert_active = True
        self.battery_alert_state = "critical" if critical else "low"
        if entering_new_state:
            self.low_battery_alert_alpha = 0.0
            self.low_battery_alert_direction = 1.0
            self.flight_batt_effect.setOpacity(self.low_battery_alert_alpha)
        self.battery_alert_label.setText(self._tr("auto_landing") if critical else self._tr("low_battery"))
        self.low_battery_flash_timer.start()
        self._update_low_battery_alert_visuals()
        if critical:
            self._set_flight_mode_buttons_enabled(False)
            self.low_battery_audio_timer.stop()
            if self.low_battery_audio_mode == "low":
                self.low_battery_audio_mode = "idle"
                if self.low_battery_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
                    self.low_battery_player.stop()
            self._engage_automatic_landing()
        else:
            self._set_flight_mode_buttons_enabled(True)
            self.low_battery_land_acknowledged = False
            if entering_new_state:
                self.last_command_label.setText("Low battery")
            if self.sounds_enabled and self.low_battery_warning_file:
                if entering_new_state:
                    self._play_low_battery_audio()
                self.low_battery_audio_timer.start()

    def _stop_low_battery_alert(self) -> None:
        if not self.low_battery_alert_active and self.battery_alert_state == "normal" and not self.low_battery_land_acknowledged:
            return
        self.low_battery_alert_active = False
        self.battery_alert_state = "normal"
        self.low_battery_audio_mode = "idle"
        self.low_battery_land_acknowledged = False
        self.low_battery_audio_timer.stop()
        self.low_battery_flash_timer.stop()
        self.low_battery_alert_alpha = 0.0
        self.low_battery_alert_direction = 1.0
        self.flight_batt_effect.setOpacity(1.0)
        self.battery_alert_effect.setOpacity(0.0)
        self.battery_alert_label.setText(self._tr("low_battery"))
        self._set_flight_mode_buttons_enabled(True)
        self.land_mode_button.setStyleSheet("")
        if self.low_battery_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.low_battery_player.stop()

    def _update_battery_alert_state(self, battery_percent: int, landed: bool) -> None:
        if landed and (self.battery_alert_state == "critical" or self.low_battery_land_acknowledged):
            self._stop_low_battery_alert()
            self.last_command_label.setText("Landing successful")
            return
        if self.low_battery_land_acknowledged:
            if self.battery_alert_state != "critical":
                self._start_landing_visual_alert()
            return
        if battery_percent <= 20:
            self._start_low_battery_alert(critical=True)
            return
        if battery_percent <= 30:
            self._start_low_battery_alert(critical=False)
            return
        self._stop_low_battery_alert()

    def _start_low_battery_alert_legacy(self) -> None:
        if self.low_battery_warning_file:
            self._play_low_battery_audio()

    def _update_low_battery_alert_visuals(self) -> None:
        if not self.low_battery_alert_active:
            self.flight_batt_effect.setOpacity(1.0)
            self.battery_alert_effect.setOpacity(0.0)
            self.land_mode_button.setStyleSheet("")
            return
        fade_step = 5.0 / 255.0
        self.low_battery_alert_alpha += fade_step * self.low_battery_alert_direction
        if self.low_battery_alert_alpha >= 1.0:
            self.low_battery_alert_alpha = 1.0
            self.low_battery_alert_direction = -1.0
        elif self.low_battery_alert_alpha <= 0.0:
            self.low_battery_alert_alpha = 0.0
            self.low_battery_alert_direction = 1.0
        if self.battery_alert_state == "landing":
            self.flight_batt_effect.setOpacity(1.0)
        else:
            self.flight_batt_effect.setOpacity(self.low_battery_alert_alpha)
        self.battery_alert_effect.setOpacity(self.low_battery_alert_alpha)
        if self.battery_alert_state == "critical":
            if self.low_battery_alert_alpha >= 0.5:
                self.land_mode_button.setStyleSheet(
                    "background: #86161f; border: 1px solid #ff616d; color: #fff5f5;"
                )
            else:
                self.land_mode_button.setStyleSheet(
                    "background: #5f1118; border: 1px solid #d84e58; color: #ffeaea;"
                )
            return
        if self.battery_alert_state == "landing" or self.low_battery_land_acknowledged:
            if self.low_battery_alert_alpha >= 0.5:
                self.land_mode_button.setStyleSheet(
                    "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #145071, stop:1 #1a7a9d);"
                    "border: 1px solid #73d2f2; color: #f7fcff;"
                )
            else:
                self.land_mode_button.setStyleSheet(
                    "background: #10243d; border: 1px solid #3d78a8; color: #dcefff;"
                )
            return
        if self.low_battery_alert_alpha >= 0.5:
            self.land_mode_button.setStyleSheet(
                "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #145071, stop:1 #1a7a9d);"
                "border: 1px solid #73d2f2; color: #f7fcff;"
            )
        else:
            self.land_mode_button.setStyleSheet("")

    @staticmethod
    def _is_landing_successful(data: SensorData) -> bool:
        return data.altitude <= 1.5 and abs(data.vertical_speed) <= 0.5 and data.gps_speed <= 1.5

    def _show_map_screen(self) -> None:
        self.primary_view = "map"
        self.map_view_button.setChecked(True)
        self.map_center_button.show()
        self.map_zones_button.show()
        self.video_overlay.hide()
        self.video_overlay_timer.stop()
        self.display_card.hide()
        self.fullscreen_stack.setCurrentWidget(self.map_widget)
        self.last_command_label.setText("MAP satellite")

    def _handle_map_center_button(self, success: bool) -> None:
        self._show_map_screen()
        if success:
            self.last_command_label.setText("MAP centered on current position")
        else:
            self.last_command_label.setText("MAP center unavailable")

    def _recenter_map_on_position(self) -> None:
        self._show_map_screen()
        if self.map_widget.recenter_on_current_position():
            self.last_command_label.setText("MAP centered on current position")
        else:
            self.last_command_label.setText("MAP center unavailable")

    def _download_visible_map_area(self) -> None:
        self._show_map_screen()
        center_latitude = self.map_widget.center_latitude
        center_longitude = self.map_widget.center_longitude
        if center_latitude is None or center_longitude is None:
            self.last_command_label.setText("MAP offline unavailable")
            QMessageBox.information(
                self,
                "Telechargement impossible",
                "Aucune zone telechargee. Position de carte indisponible.",
                QMessageBox.Ok,
            )
            return

        zone_spec = self._open_offline_zone_dialog(
            center_latitude=center_latitude,
            center_longitude=center_longitude,
            current_zoom=self.map_widget.zoom_level,
        )
        if zone_spec is None:
            return

        self._queue_offline_zone_download(
            zone_name=str(zone_spec["name"]),
            center_latitude=float(center_latitude),
            center_longitude=float(center_longitude),
            display_zoom=self.map_widget.zoom_level,
            zoom_min=int(zone_spec["zoom_min"]),
            zoom_max=int(zone_spec["zoom_max"]),
            padding_tiles=int(zone_spec["padding_tiles"]),
            refresh_cache=str(zone_spec.get("action", "download")) == "update",
            global_map_update=str(zone_spec.get("action", "download")) == "update",
        )

    def _show_map_already_updated_notice(self) -> None:
        QMessageBox.information(
            self,
            "Map update",
            "La carte est deja a jour.",
            QMessageBox.Ok,
        )
        self.last_command_label.setText("MAP already up to date")
        self._refresh_map_update_banner()

    def _handle_map_update_banner_action(self) -> None:
        if not self._map_update_available():
            self._show_map_already_updated_notice()
            return

        self._show_map_screen()
        center_latitude = self.map_widget.center_latitude
        center_longitude = self.map_widget.center_longitude
        if center_latitude is None or center_longitude is None:
            QMessageBox.information(
                self,
                "Map update",
                "Position de carte indisponible.",
                QMessageBox.Ok,
            )
            return

        current_zoom = self.map_widget.zoom_level
        self._queue_offline_zone_download(
            zone_name="Map Update",
            center_latitude=float(center_latitude),
            center_longitude=float(center_longitude),
            display_zoom=current_zoom,
            zoom_min=max(OfflineMapWidget.MIN_ZOOM, current_zoom - 1),
            zoom_max=min(OfflineMapWidget.MAX_ZOOM, current_zoom + 1),
            padding_tiles=1,
            refresh_cache=True,
            global_map_update=True,
            save_zone=False,
        )

    def _cancel_map_download(self) -> None:
        dialog = self._ensure_map_download_dialog()
        dialog.mark_cancelling()
        self.map_download_cancelled = True
        self.last_command_label.setText("MAP offline cancelling...")
        self.map_widget.cancel_prefetch()

    def _show_map_download_started(self, total: int) -> None:
        if total > 0:
            self.map_download_bar.hide()
            self.map_download_cancelled = False
            self._ensure_map_download_dialog().begin(self.active_map_download_name, total)
            prefix = f"{self.active_map_download_name} " if self.active_map_download_name else ""
            self.last_command_label.setText(f"MAP offline {prefix}0/{total}")

    def _show_map_download_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.map_download_bar.hide()
            self._ensure_map_download_dialog().update_progress(done, total)
            prefix = f"{self.active_map_download_name} " if self.active_map_download_name else ""
            self.last_command_label.setText(f"MAP offline {prefix}{done}/{total}")

    def _show_map_download_finished(self, success: int, total: int) -> None:
        prefix = f"{self.active_map_download_name} " if self.active_map_download_name else ""
        if total <= 0:
            self.last_command_label.setText("MAP offline: nothing to download")
            self.active_map_download_name = None
            self.map_update_refresh_pending = False
            self.map_download_bar.hide()
            QMessageBox.information(
                self,
                "Aucune zone telechargee",
                "Aucune tuile n'a ete telechargee pour cette demande.",
                QMessageBox.Ok,
            )
            return
        self.map_download_bar.hide()
        dialog = self._ensure_map_download_dialog()
        if self.map_download_cancelled:
            self.last_command_label.setText(f"MAP offline {prefix}cancelled: {success}/{total}")
            dialog.finish(f"Telechargement annule - {prefix.strip() or 'Zone offline'}", success, total, cancelled=True)
        elif success == total:
            self.last_command_label.setText(f"MAP offline {prefix}complete: {success} tiles")
            dialog.finish(f"Telechargement termine - {prefix.strip() or 'Zone offline'}", success, total)
        else:
            self.last_command_label.setText(f"MAP offline {prefix}partial: {success}/{total}")
            dialog.finish(f"Telechargement partiel - {prefix.strip() or 'Zone offline'}", success, total)
        if self.map_update_refresh_pending and not self.map_download_cancelled and success > 0:
            self._mark_map_updated()
        self.map_update_refresh_pending = False
        self.map_download_cancelled = False
        self.active_map_download_name = None

    def _show_live_screen(self) -> None:
        self.primary_view = "live"
        self.active_video_mode = "live"
        self.live_view_button.setChecked(True)
        self.map_center_button.hide()
        self.map_zones_button.hide()
        self.display_card.hide()
        self.fullscreen_stack.setCurrentWidget(self.fullscreen_video_page)
        self._refresh_display_panel()

    def _show_thermal_screen(self) -> None:
        self.primary_view = "thermal"
        self.active_video_mode = "thermal"
        self.thermal_view_button.setChecked(True)
        self.map_center_button.hide()
        self.map_zones_button.hide()
        self.display_card.hide()
        self.fullscreen_stack.setCurrentWidget(self.fullscreen_video_page)
        self._refresh_display_panel()

    def _show_live_data_screen(self) -> None:
        self.primary_view = "data"
        self.map_center_button.hide()
        self.map_zones_button.hide()
        self.video_overlay.hide()
        self.video_overlay_timer.stop()
        self.display_card.show()
        self.display_stack.setCurrentWidget(self.data_tab_widget)
        # Rafraîchir l'onglet AIR avec les données en direct
        self.data_chart.show_live_data(self.data_histories)
        self.last_command_label.setText(self._tr("data_live"))

    def _show_saved_data_screen(self) -> None:
        start_dir = self.air_data_dir
        current_log = self.log_file_path
        if os.path.exists(current_log):
            start_dir = os.path.dirname(current_log)

        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choisir un fichier de donnees",
            start_dir,
            "Fichiers donnees (*.csv *.db *.sqlite);;Fichiers CSV (*.csv);;Bases SQLite (*.db *.sqlite)",
        )
        if not selected_path:
            return

        try:
            extension = os.path.splitext(selected_path)[1].lower()
            if extension in {".db", ".sqlite"}:
                self.data_chart.show_logged_sqlite(selected_path)
            else:
                self.data_chart.show_logged_csv(selected_path)
            self.map_center_button.hide()
            self.map_zones_button.hide()
            self.video_overlay.hide()
            self.video_overlay_timer.stop()
            self.display_card.show()
            self.display_stack.setCurrentWidget(self.data_tab_widget)
            self.data_tab_widget.setCurrentWidget(self.data_chart)
            self.last_command_label.setText(f"DATA saved: {os.path.basename(selected_path)}")
        except Exception as exc:
            self.last_command_label.setText(f"DATA error: {exc}")

    def _toggle_sensor(self, sensor_key: str) -> None:
        command_map = {
            "gas": ("ON", "OFF"),
            "dht": ("ON1", "OFF1"),
            "geiger": ("ON2", "OFF2"),
        }
        self.sensor_states[sensor_key] = not self.sensor_states[sensor_key]
        command = command_map[sensor_key][0] if self.sensor_states[sensor_key] else command_map[sensor_key][1]
        self.command_client.send_command(command)
        state = "ON" if self.sensor_states[sensor_key] else "OFF"
        self.last_command_label.setText(f"{sensor_key.upper()} {state}")
        self._apply_sensor_visual_state(sensor_key)

    def _apply_sensor_visual_state(self, sensor_key: str) -> None:
        active = self.sensor_states[sensor_key]
        if sensor_key == "gas":
            for widget in (self.co2_gauge, self.lpg_gauge):
                widget.set_active_state(active)
        elif sensor_key == "dht":
            for widget in (self.humidity_gauge, self.temperature_gauge):
                widget.set_active_state(active)

    def _start_workers(self) -> None:
        self.thermal_receiver.start()
        self.command_client.start()

    def _set_placeholder_thermal(self) -> None:
        self.thermal_frame = None
        self._refresh_display_panel()
        if hasattr(self, "floating_panels"):
            self._refresh_floating_panels()

    def _show_no_signal_overlay(self) -> None:
        self.video_label.setPixmap(QPixmap())
        self.video_label.setText("")
        self.video_overlay.setText(self._tr("no_signal"))
        if not self.video_overlay_timer.isActive():
            self.video_overlay_timer.start()
        self.video_overlay.show()

    def _update_video_overlay_fade(self) -> None:
        fade_step = 3.0 / 255.0
        self.video_overlay_alpha += fade_step * self.video_overlay_direction
        if self.video_overlay_alpha >= 1.0:
            self.video_overlay_alpha = 1.0
            self.video_overlay_direction = -1.0
        elif self.video_overlay_alpha <= 0.0:
            self.video_overlay_alpha = 0.0
            self.video_overlay_direction = 1.0
        self.video_overlay_effect.setOpacity(self.video_overlay_alpha)

    def _refresh_display_panel(self) -> None:
        if self.fullscreen_stack.currentWidget() is not self.fullscreen_video_page:
            return
        if self.active_video_mode == "live":
            if self.live_frame is None:
                self._show_no_signal_overlay()
            else:
                self._render_current_frame()
                self.video_overlay.hide()
            return

        if self.thermal_frame is None:
            self._show_no_signal_overlay()
        else:
            self._render_current_frame()
            self.video_overlay.hide()

    def _show_thermal_status(self, message: str) -> None:
        self.last_command_label.setText(message)

    def _show_telemetry_error(self, message: str) -> None:
        self.network_apply_button.setText(f"Error {self.network_mode}")
        self.last_command_label.setText(message)

    def _apply_demo_telemetry_data(self) -> None:
        try:
            demo_data = TelemetryListener.parse_packet(DEMO_TELEMETRY_PACKET, "Demo telemetry")
        except (ValueError, KeyError):
            return
        self._apply_sensor_data(demo_data)
        self._seed_demo_radiation_spectrum(demo_data.radiation)
        self.last_command_label.setText("Demo telemetry loaded")

    def _seed_demo_radiation_spectrum(self, cps: float) -> None:
        cps = max(0.0, float(cps))
        samples = self._build_radiation_spectrum_samples(cps)
        self.sparkline.set_values(samples)
        self.radiation_history.clear()
        self.radiation_history.extend(samples)

    def _build_radiation_spectrum_samples(self, cps: float) -> list[float]:
        cps = max(0.0, float(cps))
        samples: list[float] = []
        for index in range(32):
            wave = 0.55 + 0.28 * np.sin(index * 0.65 + self.radiation_spectrum_phase)
            shimmer = 0.12 * np.sin(index * 1.9 - self.radiation_spectrum_phase * 1.7)
            spike_seed = int((self.radiation_spectrum_phase * 3.0) + index) % 11
            spike = 0.32 if spike_seed == 0 else 0.0
            samples.append(max(0.0, cps * (wave + shimmer + spike)))
        if samples:
            samples[-1] = cps
        return samples

    def _animate_radiation_spectrum(self) -> None:
        self.radiation_spectrum_phase = (self.radiation_spectrum_phase + 0.22) % (2 * np.pi)
        samples = self._build_radiation_spectrum_samples(self.current_data.radiation)
        self.sparkline.set_values(samples)
        self.radiation_history.clear()
        self.radiation_history.extend(samples)
        self._refresh_radiation_table()

    def _refresh_radiation_table(self) -> None:
        history = list(self.radiation_history)
        current = self.current_data.radiation
        dose_rate = current * 0.0058
        self.radiation_info_label.setText(f"{current:.0f} CPS")
        self.radiation_dose_label.setText(f"{dose_rate:.2f} uSv/h")

    @staticmethod
    def _packet_has_main_telemetry_fields(packet: str) -> bool:
        main_keys = {
            "CO2", "LPG", "HCS", "CO", "FUM", "HUM", "HUMIDITY", "COUNT", "CPS", "RADIATION", "TEMP", "TEMPERATURE",
            "PITCH", "PITCH_ORIENTATION", "ROLL", "ROLL_ORIENTATION", "HEADING", "AZIMUTH", "YAW",
            "GPS_SPEED", "SPEED", "GROUND_SPEED", "V_SPEED", "VERTICAL_SPEED", "VSPEED",
            "ALTITUDE", "ALT", "HEIGHT", "BATTERY", "BAT", "BATTERY_PERCENTAGE",
            "DISTANCE", "DIST", "RANGE", "LATITUDE", "LAT", "GPS_LAT", "LONGITUDE", "LON", "LONG", "GPS_LON", "GPS_LONG",
        }
        for chunk in packet.split(","):
            if ":" not in chunk:
                continue
            key, _value = chunk.split(":", 1)
            if key.strip().upper() in main_keys:
                return True
        return False

    def _position_battery_alert_card(self) -> None:
        if not hasattr(self, "battery_alert_card") or not hasattr(self, "flight_mode_panel"):
            return
        panel_geometry = self.flight_mode_panel.geometry()
        card_width = self.battery_alert_card.maximumWidth()
        card_height = self.battery_alert_card.maximumHeight()
        x = panel_geometry.center().x() - card_width // 2
        y = panel_geometry.bottom() + 6
        x = max(0, min(x, self.centralWidget().width() - card_width))
        y = max(0, min(y, self.centralWidget().height() - card_height))
        self.battery_alert_card.setGeometry(x, y, card_width, card_height)
        self.battery_alert_card.raise_()

    def _apply_sensor_data(self, data: SensorData) -> None:
        if data.lidar_points and not self._packet_has_main_telemetry_fields(data.raw_packet):
            self.current_data = replace(
                self.current_data,
                lidar_points=data.lidar_points,
                sender=data.sender,
                raw_packet=data.raw_packet,
                timestamp=data.timestamp,
            )
            self._refresh_floating_panels()
            return

        self._telemetry_has_real_gps = data.latitude is not None and data.longitude is not None
        display_data = self._merge_device_position(data)
        if FORCE_TEST_BATTERY_PERCENT is not None:
            display_data = replace(display_data, battery=FORCE_TEST_BATTERY_PERCENT)
        self.current_data = display_data
        self.radiation_history.append(display_data.radiation)
        self.map_widget.update_from_data(display_data)
        self.sample_index += 1
        self.data_histories["x"].append(self.sample_index)
        self.data_histories["co2"].append(display_data.co2)
        self.data_histories["lpg"].append(display_data.lpg)
        self.data_histories["co"].append(display_data.co)
        self.data_histories["humidity"].append(display_data.humidity)
        self.data_histories["radiation"].append(display_data.radiation)
        self.data_histories["temp"].append(display_data.temperature)

        self.co2_gauge.set_value(display_data.co2)
        self.lpg_gauge.set_value(display_data.lpg)
        self.humidity_gauge.set_value(display_data.humidity)
        self.temperature_gauge.set_value(display_data.temperature)
        self.sparkline.append_value(display_data.radiation)
        self._refresh_radiation_table()

        self.horizon_widget.set_attitude(display_data.pitch, display_data.roll)
        self.compass_widget.set_heading(display_data.heading, display_data.distance)
        self.speed_tape.set_value(display_data.gps_speed)
        self.altitude_tape.set_value(display_data.altitude)
        gps_value = "01" if display_data.latitude is not None and display_data.longitude is not None else "00"
        signal_value = "8" if self.network_connected else "0"
        battery_percent = int(round(display_data.battery))
        if battery_percent <= 30:
            batt_text = f'<span style="color:#ff4d4f;">BATT {battery_percent}</span>'
        else:
            batt_text = f"BATT {battery_percent}"
        self.flight_gps_label.setText(f"GPS {gps_value}")
        self.flight_batt_label.setText(batt_text)
        self.flight_signal_label.setText(f"SIGNAL {signal_value}")
        self.nav_left_info_label.setText(f"DIST {display_data.distance:.0f}")
        self.nav_right_info_label.setText(f"VS {display_data.vertical_speed:.0f}")

        landed = self._is_landing_successful(display_data)
        self._update_battery_alert_state(battery_percent, landed)

        self.last_update_label.setText(display_data.timestamp)
        self._update_sender_label(display_data)
        if hasattr(self, "video_osd"):
            self.video_osd.update_telemetry(display_data)
        if hasattr(self, "pip_window") and self.pip_window.isVisible():
            self.pip_window.update_telemetry(display_data)
        self._refresh_floating_panels()

        if self.display_card.isVisible() and self.display_stack.currentWidget() is self.data_chart:
            self.data_chart.show_live_data(self.data_histories)

    def _show_saved_map_zones(self) -> None:
        self._show_map_screen()
        if not self.offline_map_zones:
            self.last_command_label.setText("MAP offline: no saved zones")
            self._show_centered_notice("Exploration zone", "No exploration zone saved")
            return

        while True:
            dialog = OfflineMapZoneBrowserDialog(self.offline_map_zones, parent=self)
            if dialog.exec() != QDialog.Accepted:
                return

            zone = dialog.selected_zone()
            if zone is None:
                self.last_command_label.setText("MAP offline: no zone selected")
                return

            zone_name = str(zone.get("name", "Zone")).strip() or "Zone"
            action = getattr(dialog, "action", "open")

            if action == "open":
                latitude = zone.get("center_latitude")
                longitude = zone.get("center_longitude")
                if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
                    self.last_command_label.setText("MAP offline: invalid zone")
                    return
                display_zoom = zone.get("display_zoom", zone.get("zoom_min", self.map_widget.zoom_level))
                if not isinstance(display_zoom, (int, float)):
                    display_zoom = self.map_widget.zoom_level
                self.map_widget.focus_on_coordinates(float(latitude), float(longitude), int(display_zoom))
                self.last_command_label.setText(f"MAP zone: {zone_name}")
                return

            if action == "delete":
                answer = QMessageBox.question(
                    self,
                    "Supprimer la zone",
                    f"Supprimer la zone offline '{zone_name}' ?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer == QMessageBox.Yes and self._delete_offline_map_zone(zone_name):
                    self.last_command_label.setText(f"MAP zone deleted: {zone_name}")
                continue

            if action == "rename":
                new_name, accepted = QInputDialog.getText(self, "Renommer la zone", "Nouveau nom", text=zone_name)
                if not accepted:
                    continue
                new_name = new_name.strip()
                if not new_name:
                    self.last_command_label.setText("MAP zone rename cancelled")
                    continue
                if self._rename_offline_map_zone(zone_name, new_name):
                    self.last_command_label.setText(f"MAP zone renamed: {new_name}")
                else:
                    self.last_command_label.setText("MAP zone rename failed")
                continue

            if action == "update":
                latitude = zone.get("center_latitude")
                longitude = zone.get("center_longitude")
                display_zoom = zone.get("display_zoom", zone.get("zoom_min", self.map_widget.zoom_level))
                if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
                    self.last_command_label.setText("MAP offline: invalid zone")
                    return
                if not isinstance(display_zoom, (int, float)):
                    display_zoom = self.map_widget.zoom_level
                zone_spec = self._open_offline_zone_dialog(
                    selected_name=zone_name,
                    center_latitude=float(latitude),
                    center_longitude=float(longitude),
                    current_zoom=int(display_zoom),
                )
                if zone_spec is None:
                    continue
                self._queue_offline_zone_download(
                    zone_name=str(zone_spec["name"]),
                    center_latitude=float(latitude),
                    center_longitude=float(longitude),
                    display_zoom=int(display_zoom),
                    zoom_min=int(zone_spec["zoom_min"]),
                    zoom_max=int(zone_spec["zoom_max"]),
                    padding_tiles=int(zone_spec["padding_tiles"]),
                    refresh_cache=False,
                    global_map_update=False,
                )
                return

    def _update_thermal_frame(self, frame: QImage) -> None:
        if self.thermal_stream_worker is not None:
            return
        self.thermal_frame = frame
        if self.fullscreen_stack.currentWidget() is self.fullscreen_video_page and self.active_video_mode == "thermal":
            self.video_overlay.hide()
            self._render_current_frame()
        self._refresh_floating_panels()

    def _render_current_frame(self) -> None:
        current_frame = self.live_frame if self.active_video_mode == "live" else self.thermal_frame
        if hasattr(self, "video_osd"):
            self.video_osd.update_frame(current_frame)
            self.video_osd.update_telemetry(self.current_data)
        if hasattr(self, "pip_window") and self.pip_window.isVisible():
            self.pip_window.update_video_frame(current_frame)
            self.pip_window.update_telemetry(self.current_data)
        if self.fullscreen_stack.currentWidget() is not self.fullscreen_video_page:
            return
        if current_frame is None:
            return
        self.video_overlay_timer.stop()
        if hasattr(self, "video_label") and not self.video_label.isHidden():
            pixmap = QPixmap.fromImage(current_frame)
            scaled = pixmap.scaled(self.video_label.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self.video_label.setPixmap(scaled)
            self.video_label.setText("")

    def _record_current_data(self) -> None:
        time_label = datetime.now().strftime("%H:%M:%S")
        self.csv_writer.writerow(
            [
                time_label,
                self.current_data.co2,
                self.current_data.lpg,
                self.current_data.co,
                self.current_data.humidity,
                self.current_data.radiation,
                self.current_data.temperature,
                self.current_data.pitch,
                self.current_data.roll,
                self.current_data.heading,
                self.current_data.gps_speed,
                self.current_data.altitude,
                self.current_data.battery,
                self.current_data.latitude,
                self.current_data.longitude,
            ]
        )
        self.log_handle.flush()
        self.database.execute(
            """
            INSERT INTO telemetry_samples(
                session_id, recorded_at, time_label, co2, lpg, co, humidity,
                radiation, temperature, pitch, roll, heading, speed, altitude,
                battery, latitude, longitude
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.session_id,
                datetime.now().isoformat(timespec="seconds"),
                time_label,
                self.current_data.co2,
                self.current_data.lpg,
                self.current_data.co,
                self.current_data.humidity,
                self.current_data.radiation,
                self.current_data.temperature,
                self.current_data.pitch,
                self.current_data.roll,
                self.current_data.heading,
                self.current_data.gps_speed,
                self.current_data.altitude,
                self.current_data.battery,
                self.current_data.latitude,
                self.current_data.longitude,
            ),
        )
        self.database.commit()

        # ── Graphique de vol temps réel ───────────────────────────────────────
        if hasattr(self, "flight_data_chart"):
            self.flight_data_chart.push(
                altitude=self.current_data.altitude,
                speed=self.current_data.gps_speed,
                heading=self.current_data.heading,
            )

        # ── Évaluation des alertes de vol ─────────────────────────────────────
        if hasattr(self, "alert_banner"):
            self._update_flight_alerts()

    # Seuils d'alerte de vol (modifiables)
    ALERT_THRESHOLDS: dict[str, float] = {
        "battery_warning": 30.0,   # %
        "battery_critical": 15.0,  # %
        "altitude_max": 120.0,     # m (règlement civil)
        "speed_max": 100.0,        # km/h
        "gps_sats_min": 6.0,       # satellites (utilisé si champ disponible)
        "temp_max": 50.0,          # °C moteur / AMB
    }

    def _update_flight_alerts(self) -> None:
        """Évalue les seuils et met à jour le panneau d'alertes."""
        ab = self.alert_banner
        d = self.current_data

        # Batterie
        batt = int(round(d.battery))
        if batt <= int(self.ALERT_THRESHOLDS["battery_critical"]):
            ab.push_alert(f"🔴 BATTERIE CRITIQUE {batt}%", "critical")
            self._log_flight_event_once("alert", f"Batterie critique {batt}%")
        elif batt <= int(self.ALERT_THRESHOLDS["battery_warning"]):
            ab.push_alert(f"⚡ Batterie faible {batt}%", "warning")
            self._log_flight_event_once("alert", f"Batterie faible {batt}%")
        else:
            ab.dismiss_alert(f"🔴 BATTERIE CRITIQUE {batt}%")
            # Dismiss stale battery warnings (battery recovered or different %)
            for a in list(ab._alerts):
                if "Batterie" in a.message and a.level in ("warning", "critical") and not a.dismissed:
                    if batt > int(self.ALERT_THRESHOLDS["battery_warning"]):
                        a.dismissed = True

        # Altitude max
        alt = d.altitude
        if alt > self.ALERT_THRESHOLDS["altitude_max"]:
            ab.push_alert(f"⚠ Altitude max dépassée {alt:.0f}m", "warning")
            self._log_flight_event_once("alert", f"Altitude {alt:.0f}m > {int(self.ALERT_THRESHOLDS['altitude_max'])}m")
        else:
            ab.dismiss_alert(f"⚠ Altitude max dépassée {alt:.0f}m")

        # Vitesse max
        spd = d.gps_speed
        if spd > self.ALERT_THRESHOLDS["speed_max"]:
            ab.push_alert(f"⚡ Vitesse élevée {spd:.0f} km/h", "warning", auto_dismiss=15)
        # Température capteur
        if d.temperature > self.ALERT_THRESHOLDS["temp_max"]:
            ab.push_alert(f"🌡 Temp. capteur {d.temperature:.0f}°C", "warning")

        ab._refresh()

    # Évite les doublons dans le FlightLog pour les alertes périodiques
    _flight_log_events_seen: set[str] = set()

    def _log_flight_event_once(self, event_type: str, detail: str) -> None:
        """Enregistre un événement dans le FlightLog une seule fois (pas de spam)."""
        key = f"{event_type}:{detail}"
        if key not in self._flight_log_events_seen:
            self._flight_log_events_seen.add(key)
            if hasattr(self, "flight_log"):
                self.flight_log.log_event(event_type, detail)
            if hasattr(self, "flight_log_inline"):
                self.flight_log_inline.log_event(event_type, detail)



    def _reposition_pip_window(self) -> None:
        if hasattr(self, "pip_window") and self.centralWidget() is not None:
            cw = self.centralWidget()
            pw = self.pip_window.width()
            ph = self.pip_window.height()
            self.pip_window.move(max(10, cw.width() - pw - 20), max(10, cw.height() - ph - 20))
            self.pip_window.raise_()

    def _toggle_osd_mode(self) -> None:
        if hasattr(self, "video_osd"):
            new_mode = self.video_osd.cycle_osd_mode()
            self.last_command_label.setText(f"OSD: {new_mode}")

    def _toggle_pip_window(self) -> None:
        if hasattr(self, "pip_window"):
            is_vis = self.pip_window.isVisible()
            self.pip_window.setVisible(not is_vis)
            if not is_vis:
                self._reposition_pip_window()
                self.pip_window.raise_()
            self.last_command_label.setText("PiP: " + ("ON" if not is_vis else "OFF"))

    def _handle_pip_swap(self) -> None:
        if self.primary_view in ("live", "thermal"):
            self._show_map_screen()
            if hasattr(self, "pip_window"):
                self.pip_window.set_content_mode("video")
                current_frame = self.live_frame if self.active_video_mode == "live" else self.thermal_frame
                self.pip_window.update_video_frame(current_frame)
        else:
            self._show_live_screen()
            if hasattr(self, "pip_window"):
                self.pip_window.set_content_mode("map")
                self.pip_window.update_telemetry(self.current_data)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_responsive_layout()
        self.fullscreen_stack.setGeometry(self.centralWidget().rect())
        self.video_overlay.setGeometry(self.centralWidget().rect())
        self.video_overlay.raise_()
        self._position_battery_alert_card()
        self._position_map_update_banner()
        self._position_floating_panels()
        self._reposition_pip_window()
        self._relayout_science_gauges()
        if self.fullscreen_stack.currentWidget() is self.fullscreen_video_page:
            self._refresh_display_panel()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._position_battery_alert_card)
        QTimer.singleShot(0, self._position_map_update_banner)
        QTimer.singleShot(0, self._position_floating_panels)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.record_timer.stop()
        self.radiation_spectrum_timer.stop()
        self.low_battery_flash_timer.stop()
        self.low_battery_audio_timer.stop()
        if self.low_battery_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.low_battery_player.stop()
        if self.device_position_source is not None:
            self.device_position_source.stopUpdates()
        self._stop_video_stream("live")
        self._stop_video_stream("thermal")
        if self.link_worker is not None:
            self.link_worker.stop()  # type: ignore[attr-defined]
        self.thermal_receiver.stop()
        self.command_client.stop()

        if self.link_worker is not None:
            self.link_worker.wait(1500)
        self.thermal_receiver.wait(1500)
        self.command_client.wait(1500)

        self.log_handle.close()
        self.database.close()
        super().closeEvent(event)


