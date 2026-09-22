from __future__ import annotations

from collections import deque
import os
import time
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QWidget

from config import (
    DEFAULT_MAP_LATITUDE,
    DEFAULT_MAP_LONGITUDE,
    ensure_cache_dir,
    asset_path,
)
from core.models import SensorData
from core.utils import clamp, wrap_longitude, longitude_delta


class OfflineMapWidget(QWidget):
    offline_download_started = Signal(int)
    offline_download_progress = Signal(int, int)
    offline_download_finished = Signal(int, int)
    center_requested = Signal(bool)
    zones_requested = Signal()
    waypoints_changed = Signal(list)
    follow_state_changed = Signal(bool)
    TILE_SIZE = 256
    MIN_ZOOM = 1
    MAX_ZOOM = 19
    MAX_CONCURRENT_TILE_REQUESTS = 12
    TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

    def __init__(self) -> None:
        super().__init__()
        self.theme = "dark"
        self.controls_visible = True
        self.waypoints: list[dict[str, float | str]] = []
        self.add_waypoint_mode: bool = False
        self.drone_altitude: float = 0.0
        self.drone_speed: float = 0.0
        self.drone_satellites: int = 12
        self._pulse_phase: float = 0.0
        self.follow_btn_rect = QRectF()
        self.add_wp_btn_rect = QRectF()
        self.clear_wp_btn_rect = QRectF()
        self.fit_all_btn_rect = QRectF()
        self._follow_btn_hovered = False
        self._add_wp_btn_hovered = False
        self._clear_wp_btn_hovered = False
        self._fit_all_btn_hovered = False
        self.relative_track: deque[tuple[float, float]] = deque(maxlen=720)
        self.gps_track: deque[tuple[float, float]] = deque(maxlen=720)
        self.current_point = (0.0, 0.0)
        self.home_point = (0.0, 0.0)
        self.heading = 0.0
        self.displayed_heading = 0.0
        self.map_mode = "relative"
        self.latitude: float | None = None
        self.longitude: float | None = None
        self.home_latitude: float | None = DEFAULT_MAP_LATITUDE
        self.home_longitude: float | None = DEFAULT_MAP_LONGITUDE
        self.center_latitude: float | None = DEFAULT_MAP_LATITUDE
        self.center_longitude: float | None = DEFAULT_MAP_LONGITUDE
        self.display_latitude: float | None = DEFAULT_MAP_LATITUDE
        self.display_longitude: float | None = DEFAULT_MAP_LONGITUDE
        self.display_center_latitude: float | None = DEFAULT_MAP_LATITUDE
        self.display_center_longitude: float | None = DEFAULT_MAP_LONGITUDE
        self._has_real_home = False
        self.zoom_level = 17
        self.display_zoom_level = 17.0
        self.follow_drone = True
        self._last_update_time: float | None = None
        self._drag_start: QPointF | None = None
        self._drag_start_tile: tuple[float, float] | None = None
        self.tile_pixmaps: dict[tuple[int, int, int], QPixmap] = {}
        self.pending_tiles: set[tuple[int, int, int]] = set()
        self.active_replies: dict[tuple[int, int, int], QNetworkReply] = {}
        self.queued_tiles: set[tuple[int, int, int]] = set()
        self.tile_request_queue: deque[tuple[int, int, int]] = deque()
        self.prefetch_targets: set[tuple[int, int, int]] = set()
        self.prefetch_total = 0
        self.prefetch_completed = 0
        self.prefetch_success = 0
        self.prefetch_active = False
        self.tile_manager = QNetworkAccessManager(self)
        self.tile_manager.finished.connect(self._handle_tile_reply)
        self.tile_cache = QNetworkDiskCache(self)
        cache_dir = os.path.join(ensure_cache_dir(), "satellite_tiles")
        os.makedirs(cache_dir, exist_ok=True)
        self.tile_cache.setCacheDirectory(cache_dir)
        self.tile_cache.setMaximumCacheSize(2_000_000_000)
        self.tile_manager.setCache(self.tile_cache)
        self.tile_file_cache_dir = os.path.join(ensure_cache_dir(), "satellite_tile_files")
        os.makedirs(self.tile_file_cache_dir, exist_ok=True)
        self.setMinimumHeight(320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.center_icon = QPixmap(asset_path("img", "centrage.png"))
        self.zones_icon = QPixmap(asset_path("img", "zone.png"))
        self.center_icon_rect = QRectF()
        self._center_hovered = False
        self.zones_button_rect = QRectF()
        self._zones_hovered = False
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(33)
        self._animation_timer.timeout.connect(self._animate_map_state)
        self._map_refresh_timer = QTimer(self)
        self._map_refresh_timer.setSingleShot(True)
        self._map_refresh_timer.setInterval(40)
        self._map_refresh_timer.timeout.connect(self.update)

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in {"dark", "light"} else "dark"
        self.update()

    def _theme_colors(self) -> dict[str, QColor]:
        if self.theme == "light":
            return {
                "bg": QColor("#f7fbff"),
                "panel": QColor("#edf4fb"),
                "border": QColor("#d2deea"),
                "grid_minor": QColor("#dce7f1"),
                "grid_major": QColor("#c1d1e0"),
                "track": QColor("#2f95ff"),
                "current": QColor("#ff6a3d"),
                "home": QColor("#1f9d60"),
                "text": QColor("#21364b"),
                "muted": QColor("#627b93"),
                "placeholder": QColor("#dde8f2"),
            }
        return {
            "bg": QColor("#0d1525"),
            "panel": QColor("#101a2d"),
            "border": QColor("#263754"),
            "grid_minor": QColor("#1a2940"),
            "grid_major": QColor("#314a6d"),
            "track": QColor("#5ec8f8"),
            "current": QColor("#ff8b5d"),
            "home": QColor("#6de28c"),
            "text": QColor("#dbe7ff"),
            "muted": QColor("#8ea8d7"),
            "placeholder": QColor("#162238"),
        }

    @staticmethod
    def _meters_from_gps(
        latitude: float,
        longitude: float,
        home_latitude: float,
        home_longitude: float,
    ) -> tuple[float, float]:
        lat_rad = np.deg2rad(home_latitude)
        meters_per_deg_lat = 111_132.0
        meters_per_deg_lon = 111_320.0 * np.cos(lat_rad)
        x = (longitude - home_longitude) * meters_per_deg_lon
        y = (latitude - home_latitude) * meters_per_deg_lat
        return (x, y)

    @staticmethod
    def _meters_to_gps(
        x_meters: float,
        y_meters: float,
        home_latitude: float,
        home_longitude: float,
    ) -> tuple[float, float]:
        lat_rad = np.deg2rad(home_latitude)
        meters_per_deg_lat = 111_132.0
        meters_per_deg_lon = 111_320.0 * max(np.cos(lat_rad), 1e-6)
        latitude = home_latitude + (y_meters / meters_per_deg_lat)
        longitude = home_longitude + (x_meters / meters_per_deg_lon)
        return (float(latitude), float(longitude))

    @classmethod
    def _gps_to_tile(cls, latitude: float, longitude: float, zoom: int) -> tuple[float, float]:
        lat = clamp(latitude, -85.0511, 85.0511)
        lon = ((longitude + 180.0) % 360.0) - 180.0
        lat_rad = np.deg2rad(lat)
        n = 2.0 ** zoom
        x = (lon + 180.0) / 360.0 * n
        y = (1.0 - np.log(np.tan(lat_rad) + (1.0 / np.cos(lat_rad))) / np.pi) / 2.0 * n
        return (float(x), float(y))

    @classmethod
    def _tile_to_gps(cls, tile_x: float, tile_y: float, zoom: int) -> tuple[float, float]:
        n = 2.0 ** zoom
        lon = tile_x / n * 360.0 - 180.0
        lat_rad = np.arctan(np.sinh(np.pi * (1 - 2 * tile_y / n)))
        lat = np.rad2deg(lat_rad)
        return (float(lat), float(lon))

    def update_from_data(self, data: SensorData) -> None:
        self.heading = data.heading % 360.0
        now = time.monotonic()
        previous_latitude = self.latitude
        previous_longitude = self.longitude

        if data.latitude is not None and data.longitude is not None:
            self.latitude = data.latitude
            self.longitude = data.longitude
            self.map_mode = "gps"
            if not self._has_real_home:
                self.home_latitude = data.latitude
                self.home_longitude = data.longitude
                self._has_real_home = True
            if self.follow_drone or self.center_latitude is None or self.center_longitude is None:
                self.center_latitude = data.latitude
                self.center_longitude = data.longitude
            if previous_latitude is None or previous_longitude is None:
                self.display_latitude = data.latitude
                self.display_longitude = data.longitude
            if self.display_center_latitude is None or self.display_center_longitude is None:
                self.display_center_latitude = self.center_latitude
                self.display_center_longitude = self.center_longitude

            self.current_point = self._meters_from_gps(
                data.latitude,
                data.longitude,
                self.home_latitude,
                self.home_longitude,
            )
            if not self.gps_track:
                self.gps_track.append((data.latitude, data.longitude))
            else:
                last_lat, last_lon = self.gps_track[-1]
                if abs(last_lat - data.latitude) > 1e-7 or abs(last_lon - data.longitude) > 1e-7:
                    self.gps_track.append((data.latitude, data.longitude))
        else:
            self.map_mode = "relative"
            self.latitude = None
            self.longitude = None
            if self.home_latitude is None or self.home_longitude is None:
                self.home_latitude = DEFAULT_MAP_LATITUDE
                self.home_longitude = DEFAULT_MAP_LONGITUDE
            if self.center_latitude is None or self.center_longitude is None:
                self.center_latitude = self.home_latitude
                self.center_longitude = self.home_longitude
            if self._last_update_time is None:
                self.current_point = (0.0, 0.0)
            else:
                dt = clamp(now - self._last_update_time, 0.0, 2.5)
                distance_m = max(0.0, data.gps_speed) * dt / 3.6
                heading_rad = np.deg2rad(self.heading)
                dx = np.sin(heading_rad) * distance_m
                dy = np.cos(heading_rad) * distance_m
                self.current_point = (self.current_point[0] + dx, self.current_point[1] + dy)

            if not self.relative_track:
                self.relative_track.append(self.current_point)
            else:
                last_x, last_y = self.relative_track[-1]
                delta = np.hypot(self.current_point[0] - last_x, self.current_point[1] - last_y)
                if delta >= 0.8:
                    self.relative_track.append(self.current_point)
                else:
                    self.relative_track[-1] = self.current_point

        self._last_update_time = now
        self._start_animation()
        self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.center_latitude is None or self.center_longitude is None:
            super().wheelEvent(event)
            return

        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        new_zoom = int(clamp(self.zoom_level + (1 if delta > 0 else -1), self.MIN_ZOOM, self.MAX_ZOOM))
        if new_zoom != self.zoom_level:
            self.zoom_level = new_zoom
            self._start_animation()
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if self.controls_visible:
            if self.follow_btn_rect.contains(pos):
                self.toggle_follow_drone()
                event.accept()
                return
            if self.add_wp_btn_rect.contains(pos):
                self.toggle_add_waypoint_mode()
                event.accept()
                return
            if self.clear_wp_btn_rect.contains(pos):
                self.clear_waypoints()
                event.accept()
                return
            if self.fit_all_btn_rect.contains(pos):
                self.fit_all_points()
                event.accept()
                return
            if self.center_icon_rect.contains(pos):
                success = self.recenter_on_current_position()
                self.center_requested.emit(success)
                event.accept()
                return
            if self.zones_button_rect.contains(pos):
                self.zones_requested.emit()
                event.accept()
                return

        plot = self._current_plot_rect()
        is_waypoint_click = (event.button() == Qt.RightButton) or (self.add_waypoint_mode and event.button() == Qt.LeftButton)
        if is_waypoint_click and plot.contains(pos):
            render_center_lat = self.display_center_latitude if self.display_center_latitude is not None else self.center_latitude
            render_center_lon = self.display_center_longitude if self.display_center_longitude is not None else self.center_longitude
            if render_center_lat is not None and render_center_lon is not None:
                source_zoom = int(clamp(round(self.display_zoom_level), self.MIN_ZOOM, self.MAX_ZOOM))
                render_tile_size = self.TILE_SIZE * (2 ** (self.display_zoom_level - source_zoom))
                center_tile_x, center_tile_y = self._gps_to_tile(render_center_lat, render_center_lon, source_zoom)
                center_world_x = center_tile_x * render_tile_size
                center_world_y = center_tile_y * render_tile_size
                left_world = center_world_x - plot.width() / 2
                top_world = center_world_y - plot.height() / 2
                click_world_x = left_world + (pos.x() - plot.left())
                click_world_y = top_world + (pos.y() - plot.top())
                tile_x = click_world_x / render_tile_size
                tile_y = click_world_y / render_tile_size
                wp_lat, wp_lon = self._tile_to_gps(tile_x, tile_y, source_zoom)
                wp_num = len(self.waypoints) + 1
                self.waypoints.append({"lat": float(wp_lat), "lon": float(wp_lon), "alt": 20.0, "name": f"WP{wp_num}"})
                self.waypoints_changed.emit(self.waypoints)
                self.update()
                event.accept()
                return

        if event.button() == Qt.LeftButton and self.center_latitude is not None and self.center_longitude is not None:
            self._drag_start = pos
            self._drag_start_tile = self._gps_to_tile(self.center_latitude, self.center_longitude, self.zoom_level)
            if self.follow_drone:
                self.follow_drone = False
                self.follow_state_changed.emit(False)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if self.controls_visible:
            hovered = self.center_icon_rect.contains(pos)
            if hovered != self._center_hovered:
                self._center_hovered = hovered
                self.update()
            zones_hovered = self.zones_button_rect.contains(pos)
            if zones_hovered != self._zones_hovered:
                self._zones_hovered = zones_hovered
                self.update()
            f_hov = self.follow_btn_rect.contains(pos)
            if f_hov != self._follow_btn_hovered:
                self._follow_btn_hovered = f_hov
                self.update()
            w_hov = self.add_wp_btn_rect.contains(pos)
            if w_hov != self._add_wp_btn_hovered:
                self._add_wp_btn_hovered = w_hov
                self.update()
            c_hov = self.clear_wp_btn_rect.contains(pos)
            if c_hov != self._clear_wp_btn_hovered:
                self._clear_wp_btn_hovered = c_hov
                self.update()
            fit_hov = self.fit_all_btn_rect.contains(pos)
            if fit_hov != self._fit_all_btn_hovered:
                self._fit_all_btn_hovered = fit_hov
                self.update()

        if self._drag_start is None or self._drag_start_tile is None:
            super().mouseMoveEvent(event)
            return

        delta = pos - self._drag_start
        start_x, start_y = self._drag_start_tile
        new_tile_x = start_x - (delta.x() / self.TILE_SIZE)
        new_tile_y = start_y - (delta.y() / self.TILE_SIZE)
        max_tile = 2 ** self.zoom_level - 1
        new_tile_y = clamp(new_tile_y, 0.0, max_tile)
        self.center_latitude, self.center_longitude = self._tile_to_gps(new_tile_x, new_tile_y, self.zoom_level)
        self.display_center_latitude = self.center_latitude
        self.display_center_longitude = self.center_longitude
        self.update()
        event.accept()

    def toggle_follow_drone(self) -> None:
        self.follow_drone = not self.follow_drone
        if self.follow_drone:
            self.recenter_on_current_position()
        self.follow_state_changed.emit(self.follow_drone)
        self.update()

    def toggle_add_waypoint_mode(self) -> None:
        self.add_waypoint_mode = not self.add_waypoint_mode
        self.update()

    def clear_waypoints(self) -> None:
        self.waypoints.clear()
        self.waypoints_changed.emit([])
        self.update()

    def fit_all_points(self) -> None:
        points = []
        curr_lat, curr_lon = self._current_display_coordinates()
        if curr_lat is not None and curr_lon is not None:
            points.append((curr_lat, curr_lon))
        if self.home_latitude is not None and self.home_longitude is not None:
            points.append((self.home_latitude, self.home_longitude))
        for wp in self.waypoints:
            points.append((float(wp["lat"]), float(wp["lon"])))
        if not points:
            return
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        center_lat = (min(lats) + max(lats)) / 2.0
        center_lon = (min(lons) + max(lons)) / 2.0
        self.center_latitude = center_lat
        self.center_longitude = center_lon
        self.display_center_latitude = center_lat
        self.display_center_longitude = center_lon
        span_lat = max(lats) - min(lats)
        span_lon = max(lons) - min(lons)
        max_span = max(span_lat, span_lon)
        if max_span < 0.001:
            self.zoom_level = 18
        elif max_span < 0.004:
            self.zoom_level = 16
        elif max_span < 0.015:
            self.zoom_level = 14
        elif max_span < 0.06:
            self.zoom_level = 12
        else:
            self.zoom_level = 10
        self._start_animation()
        self.update()

    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000.0
        phi1, phi2 = np.deg2rad(lat1), np.deg2rad(lat2)
        dphi = np.deg2rad(lat2 - lat1)
        dlam = np.deg2rad(lon2 - lon1)
        a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2.0) ** 2
        c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
        return float(r * c)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_start = None
        self._drag_start_tile = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.recenter_on_current_position():
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _current_display_coordinates(self) -> tuple[float | None, float | None]:
        if self.latitude is not None and self.longitude is not None:
            return (self.latitude, self.longitude)
        if self.home_latitude is not None and self.home_longitude is not None:
            return self._meters_to_gps(
                self.current_point[0],
                self.current_point[1],
                self.home_latitude,
                self.home_longitude,
            )
        if self.center_latitude is not None and self.center_longitude is not None:
            return (self.center_latitude, self.center_longitude)
        return (None, None)

    def recenter_on_current_position(self) -> bool:
        latitude, longitude = self._current_display_coordinates()
        if latitude is None or longitude is None:
            return False
        self.follow_drone = True
        self.zoom_level = self.MAX_ZOOM
        self.center_latitude = latitude
        self.center_longitude = longitude
        self._start_animation()
        self.update()
        return True

    def focus_on_coordinates(self, latitude: float, longitude: float, zoom: int | None = None) -> None:
        self.follow_drone = False
        self.center_latitude = latitude
        self.center_longitude = longitude
        self.display_center_latitude = latitude
        self.display_center_longitude = longitude
        if zoom is not None:
            self.zoom_level = int(clamp(zoom, self.MIN_ZOOM, self.MAX_ZOOM))
        self._start_animation()
        self.update()

    def _start_animation(self) -> None:
        if not self._animation_timer.isActive():
            self._animation_timer.start()

    @staticmethod
    def _blend_scalar(current: float | None, target: float | None, factor: float = 0.18) -> tuple[float | None, bool]:
        if target is None:
            return (current, False)
        if current is None:
            return (target, True)
        delta = target - current
        if abs(delta) < 1e-7:
            return (target, current != target)
        if abs(delta) < 1e-5:
            return (target, True)
        return (current + delta * factor, True)

    @staticmethod
    def _blend_longitude(current: float | None, target: float | None, factor: float = 0.18) -> tuple[float | None, bool]:
        if target is None:
            return (current, False)
        if current is None:
            return (wrap_longitude(target), True)
        delta = longitude_delta(current, target)
        if abs(delta) < 1e-7:
            wrapped = wrap_longitude(target)
            return (wrapped, current != wrapped)
        if abs(delta) < 1e-5:
            return (wrap_longitude(target), True)
        return (wrap_longitude(current + delta * factor), True)

    def _animate_map_state(self) -> None:
        changed = False

        marker_latitude, marker_longitude = self._current_display_coordinates()
        next_latitude, latitude_changed = self._blend_scalar(self.display_latitude, marker_latitude, factor=0.24)
        next_longitude, longitude_changed = self._blend_longitude(self.display_longitude, marker_longitude, factor=0.24)
        self.display_latitude = next_latitude
        self.display_longitude = next_longitude
        changed = changed or latitude_changed or longitude_changed

        next_center_latitude, center_latitude_changed = self._blend_scalar(
            self.display_center_latitude,
            self.center_latitude,
            factor=0.18,
        )
        next_center_longitude, center_longitude_changed = self._blend_longitude(
            self.display_center_longitude,
            self.center_longitude,
            factor=0.18,
        )
        self.display_center_latitude = next_center_latitude
        self.display_center_longitude = next_center_longitude
        changed = changed or center_latitude_changed or center_longitude_changed

        zoom_delta = float(self.zoom_level) - float(self.display_zoom_level)
        if abs(zoom_delta) < 0.01:
            next_zoom = float(self.zoom_level)
        else:
            next_zoom = float(self.display_zoom_level + zoom_delta * 0.22)
        if abs(next_zoom - self.display_zoom_level) > 1e-4:
            changed = True
        self.display_zoom_level = next_zoom

        delta_heading = (self.heading - self.displayed_heading + 540.0) % 360.0 - 180.0
        if abs(delta_heading) < 0.2:
            next_heading = self.heading
        else:
            next_heading = (self.displayed_heading + delta_heading * 0.18) % 360.0
        if abs(((next_heading - self.displayed_heading + 540.0) % 360.0) - 180.0) > 1e-4:
            changed = True
        self.displayed_heading = next_heading

        if changed:
            self.update()
            return
        self._animation_timer.stop()

    def _request_tile(self, zoom: int, x: int, y: int) -> None:
        key = (zoom, x, y)
        if key in self.tile_pixmaps:
            return
        if self._load_tile_from_disk(key):
            self._schedule_map_refresh()
            return
        if key in self.pending_tiles:
            existing_reply = self.active_replies.get(key)
            if existing_reply is not None and existing_reply.isRunning():
                return
            self.pending_tiles.discard(key)
            self.active_replies.pop(key, None)
        if key in self.queued_tiles:
            return
        if len(self.active_replies) >= self.MAX_CONCURRENT_TILE_REQUESTS:
            self.queued_tiles.add(key)
            self.tile_request_queue.append(key)
            return
        self._dispatch_tile_request(key)

    def _dispatch_tile_request(self, key: tuple[int, int, int]) -> None:
        zoom, x, y = key
        self.pending_tiles.add(key)
        self.queued_tiles.discard(key)
        request = QNetworkRequest(QUrl(self.TILE_URL.format(z=zoom, x=x, y=y)))
        request.setRawHeader(b"User-Agent", b"SpectrumAirGuard/1.0")
        reply = self.tile_manager.get(request)
        reply.setProperty("tile_key", f"{zoom}:{x}:{y}")
        self.active_replies[key] = reply

    def _tile_file_path(self, key: tuple[int, int, int]) -> str:
        zoom, x, y = key
        return os.path.join(self.tile_file_cache_dir, str(zoom), str(x), f"{y}.jpg")

    def _load_tile_from_disk(self, key: tuple[int, int, int]) -> bool:
        if key in self.tile_pixmaps:
            return True

        tile_path = self._tile_file_path(key)
        if not os.path.exists(tile_path):
            return False

        pixmap = QPixmap(tile_path)
        if pixmap.isNull():
            return False

        self.tile_pixmaps[key] = pixmap
        return True

    def _store_tile_to_disk(self, key: tuple[int, int, int], tile_data) -> None:
        tile_path = self._tile_file_path(key)
        try:
            os.makedirs(os.path.dirname(tile_path), exist_ok=True)
            with open(tile_path, "wb") as handle:
                handle.write(bytes(tile_data))
        except OSError:
            pass

    def _drain_tile_request_queue(self) -> None:
        while self.tile_request_queue and len(self.active_replies) < self.MAX_CONCURRENT_TILE_REQUESTS:
            key = self.tile_request_queue.popleft()
            if key in self.tile_pixmaps or self._load_tile_from_disk(key) or key in self.pending_tiles:
                self.queued_tiles.discard(key)
                continue
            self._dispatch_tile_request(key)

    def _schedule_map_refresh(self) -> None:
        if not self._map_refresh_timer.isActive():
            self._map_refresh_timer.start()

    def _current_plot_rect(self):
        outer = self.rect().adjusted(8, 8, -8, -8)
        return outer.adjusted(16, 20, -16, -44)

    def _build_prefetch_keys(
        self,
        *,
        padding_tiles: int,
        min_zoom: int,
        max_zoom: int,
        center_latitude: float | None = None,
        center_longitude: float | None = None,
    ) -> set[tuple[int, int, int]]:
        latitude = center_latitude if center_latitude is not None else self.center_latitude
        longitude = center_longitude if center_longitude is not None else self.center_longitude
        if latitude is None or longitude is None:
            return set()

        plot = self._current_plot_rect()
        requested_keys: set[tuple[int, int, int]] = set()
        for zoom in range(max(self.MIN_ZOOM, min_zoom), min(self.MAX_ZOOM, max_zoom) + 1):
            center_tile_x, center_tile_y = self._gps_to_tile(latitude, longitude, zoom)
            center_world_x = center_tile_x * self.TILE_SIZE
            center_world_y = center_tile_y * self.TILE_SIZE
            left_world = center_world_x - plot.width() / 2
            top_world = center_world_y - plot.height() / 2
            max_tile = 2 ** zoom
            first_x = int(np.floor(left_world / self.TILE_SIZE)) - padding_tiles
            last_x = int(np.floor((left_world + plot.width()) / self.TILE_SIZE)) + padding_tiles
            first_y = int(np.floor(top_world / self.TILE_SIZE)) - padding_tiles
            last_y = int(np.floor((top_world + plot.height()) / self.TILE_SIZE)) + padding_tiles

            for tile_x in range(first_x, last_x + 1):
                wrapped_x = tile_x % max_tile
                for tile_y in range(first_y, last_y + 1):
                    if 0 <= tile_y < max_tile:
                        requested_keys.add((zoom, wrapped_x, tile_y))
        return requested_keys

    def prefetch_visible_tiles(
        self,
        padding_tiles: int = 1,
        zoom_span: int = 1,
        min_zoom: int | None = None,
        max_zoom: int | None = None,
        center_latitude: float | None = None,
        center_longitude: float | None = None,
    ) -> int:
        requested_keys = self._build_prefetch_keys(
            padding_tiles=padding_tiles,
            min_zoom=min_zoom if min_zoom is not None else self.zoom_level - zoom_span,
            max_zoom=max_zoom if max_zoom is not None else self.zoom_level + zoom_span,
            center_latitude=center_latitude,
            center_longitude=center_longitude,
        )
        if not requested_keys:
            return 0

        if self.prefetch_active:
            self.cancel_prefetch(emit_finished=False)

        self.prefetch_targets = set(requested_keys)
        self.prefetch_total = len(requested_keys)
        self.prefetch_completed = 0
        self.prefetch_success = 0
        self.prefetch_active = True
        self.offline_download_started.emit(self.prefetch_total)

        for key in list(requested_keys):
            if key in self.tile_pixmaps or self._load_tile_from_disk(key):
                self.prefetch_targets.discard(key)
                self.prefetch_completed += 1
                self.prefetch_success += 1
            else:
                self._request_tile(*key)

        self.offline_download_progress.emit(self.prefetch_completed, self.prefetch_total)
        if self.prefetch_completed >= self.prefetch_total:
            self.prefetch_active = False
            self.offline_download_finished.emit(self.prefetch_success, self.prefetch_total)
        return self.prefetch_total

    def invalidate_visible_tiles(
        self,
        *,
        padding_tiles: int = 1,
        min_zoom: int | None = None,
        max_zoom: int | None = None,
        center_latitude: float | None = None,
        center_longitude: float | None = None,
    ) -> int:
        keys = self._build_prefetch_keys(
            padding_tiles=padding_tiles,
            min_zoom=min_zoom if min_zoom is not None else self.zoom_level - 1,
            max_zoom=max_zoom if max_zoom is not None else self.zoom_level + 1,
            center_latitude=center_latitude,
            center_longitude=center_longitude,
        )
        if not keys:
            return 0

        for key in keys:
            zoom, x, y = key
            self.tile_pixmaps.pop(key, None)
            self.queued_tiles.discard(key)
            self.pending_tiles.discard(key)
            reply = self.active_replies.pop(key, None)
            if reply is not None and reply.isRunning():
                reply.setProperty("tile_key", "")
                reply.abort()
            tile_url = QUrl(self.TILE_URL.format(z=zoom, x=x, y=y))
            self.tile_cache.remove(tile_url)
            tile_path = self._tile_file_path(key)
            if os.path.exists(tile_path):
                try:
                    os.remove(tile_path)
                except OSError:
                    pass

        self.tile_request_queue = deque(key for key in self.tile_request_queue if key not in keys)
        self._schedule_map_refresh()
        return len(keys)

    def cancel_prefetch(self, emit_finished: bool = True) -> tuple[int, int]:
        if not self.prefetch_active and self.prefetch_total <= 0:
            return (0, 0)

        success = self.prefetch_success
        total = self.prefetch_total
        keys_to_abort = list(self.prefetch_targets)
        self.prefetch_targets.clear()
        self.prefetch_active = False
        if keys_to_abort:
            cancelled_keys = set(keys_to_abort)
            self.tile_request_queue = deque(key for key in self.tile_request_queue if key not in cancelled_keys)
            self.queued_tiles.difference_update(cancelled_keys)
        for key in keys_to_abort:
            reply = self.active_replies.get(key)
            if reply is not None and reply.isRunning():
                reply.abort()
            self.pending_tiles.discard(key)
            self.active_replies.pop(key, None)
        self._drain_tile_request_queue()
        if emit_finished:
            self.offline_download_finished.emit(success, total)
        return (success, total)

    def _handle_tile_reply(self, reply: QNetworkReply) -> None:
        key_text = reply.property("tile_key")
        if not key_text:
            reply.deleteLater()
            return

        zoom_str, x_str, y_str = str(key_text).split(":")
        key = (int(zoom_str), int(x_str), int(y_str))
        self.pending_tiles.discard(key)
        self.active_replies.pop(key, None)

        success = False
        if reply.error() == QNetworkReply.NoError:
            tile_data = reply.readAll()
            pixmap = QPixmap()
            if pixmap.loadFromData(tile_data):
                self.tile_pixmaps[key] = pixmap
                self._store_tile_to_disk(key, tile_data)
                success = True

        if key in self.prefetch_targets:
            self.prefetch_targets.discard(key)
            self.prefetch_completed += 1
            if success:
                self.prefetch_success += 1
            self.offline_download_progress.emit(self.prefetch_completed, self.prefetch_total)
            if self.prefetch_completed >= self.prefetch_total:
                self.prefetch_active = False
                self.offline_download_finished.emit(self.prefetch_success, self.prefetch_total)

        reply.deleteLater()
        self._drain_tile_request_queue()
        self._schedule_map_refresh()

    @staticmethod
    def _nice_step(raw_step: float) -> float:
        if raw_step <= 0:
            return 10.0
        exponent = 10 ** np.floor(np.log10(raw_step))
        fraction = raw_step / exponent
        if fraction <= 1:
            nice = 1
        elif fraction <= 2:
            nice = 2
        elif fraction <= 5:
            nice = 5
        else:
            nice = 10
        return float(nice * exponent)

    def _paint_relative_map(self, painter: QPainter, outer, plot, colors: dict[str, QColor]) -> None:
        points = list(self.relative_track) or [self.current_point]
        xs = [point[0] for point in points] + [self.home_point[0]]
        ys = [point[1] for point in points] + [self.home_point[1]]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span = max(max_x - min_x, max_y - min_y, 120.0)
        half_span = span * 0.6
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        min_x = center_x - half_span
        max_x = center_x + half_span
        min_y = center_y - half_span
        max_y = center_y + half_span

        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)

        def to_screen(point: tuple[float, float]) -> QPointF:
            x_ratio = (point[0] - min_x) / width
            y_ratio = (point[1] - min_y) / height
            screen_x = plot.left() + x_ratio * plot.width()
            screen_y = plot.bottom() - y_ratio * plot.height()
            return QPointF(screen_x, screen_y)

        grid_step = self._nice_step(width / 5.0)
        start_x = np.floor(min_x / grid_step) * grid_step
        start_y = np.floor(min_y / grid_step) * grid_step

        painter.setFont(QFont("Segoe UI", 7))
        x_tick = start_x
        while x_tick <= max_x + grid_step:
            screen_x = to_screen((x_tick, min_y)).x()
            is_axis = abs(x_tick) < 0.1
            painter.setPen(QPen(colors["grid_major"] if is_axis else colors["grid_minor"], 1))
            painter.drawLine(int(screen_x), plot.top(), int(screen_x), plot.bottom())
            if plot.left() <= screen_x <= plot.right():
                painter.setPen(colors["muted"])
                painter.drawText(int(screen_x) + 3, plot.bottom() + 16, f"{x_tick:.0f}m")
            x_tick += grid_step

        y_tick = start_y
        while y_tick <= max_y + grid_step:
            screen_y = to_screen((min_x, y_tick)).y()
            is_axis = abs(y_tick) < 0.1
            painter.setPen(QPen(colors["grid_major"] if is_axis else colors["grid_minor"], 1))
            painter.drawLine(plot.left(), int(screen_y), plot.right(), int(screen_y))
            if plot.top() <= screen_y <= plot.bottom():
                painter.setPen(colors["muted"])
                painter.drawText(plot.left() + 4, int(screen_y) - 3, f"{y_tick:.0f}")
            y_tick += grid_step

        if len(points) >= 2:
            trail = QPainterPath()
            trail.moveTo(to_screen(points[0]))
            for point in points[1:]:
                trail.lineTo(to_screen(point))
            painter.setPen(QPen(colors["track"], 3))
            painter.drawPath(trail)

        home_screen = to_screen(self.home_point)
        painter.setPen(Qt.NoPen)
        painter.setBrush(colors["home"])
        painter.drawEllipse(home_screen, 5, 5)

        current_screen = to_screen(self.current_point)
        self._draw_heading_arrow(painter, current_screen, self.displayed_heading)

    def _paint_satellite_map(self, painter: QPainter, outer, plot, colors: dict[str, QColor]) -> None:
        render_center_latitude = self.display_center_latitude if self.display_center_latitude is not None else self.center_latitude
        render_center_longitude = self.display_center_longitude if self.display_center_longitude is not None else self.center_longitude
        if render_center_latitude is None or render_center_longitude is None:
            self._paint_relative_map(painter, outer, plot, colors)
            return

        painter.save()
        painter.setClipRect(plot)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        render_zoom = float(clamp(self.display_zoom_level, self.MIN_ZOOM, self.MAX_ZOOM))
        source_zoom = int(clamp(round(render_zoom), self.MIN_ZOOM, self.MAX_ZOOM))
        render_tile_size = self.TILE_SIZE * (2 ** (render_zoom - source_zoom))
        center_tile_x, center_tile_y = self._gps_to_tile(render_center_latitude, render_center_longitude, source_zoom)
        center_world_x = center_tile_x * render_tile_size
        center_world_y = center_tile_y * render_tile_size
        left_world = center_world_x - plot.width() / 2
        top_world = center_world_y - plot.height() / 2
        max_tile = 2 ** source_zoom
        painter.fillRect(plot, colors["placeholder"])

        first_x = int(np.floor(left_world / render_tile_size))
        last_x = int(np.floor((left_world + plot.width()) / render_tile_size))
        first_y = int(np.floor(top_world / render_tile_size))
        last_y = int(np.floor((top_world + plot.height()) / render_tile_size))

        for tile_x in range(first_x, last_x + 1):
            wrapped_x = tile_x % max_tile
            for tile_y in range(first_y, last_y + 1):
                if tile_y < 0 or tile_y >= max_tile:
                    continue
                dest_x = plot.left() + tile_x * render_tile_size - left_world
                dest_y = plot.top() + tile_y * render_tile_size - top_world
                seam_overlap = max(0.6, render_tile_size * 0.0025)
                target_rect = QRectF(
                    dest_x - seam_overlap,
                    dest_y - seam_overlap,
                    render_tile_size + seam_overlap * 2,
                    render_tile_size + seam_overlap * 2,
                )
                key = (source_zoom, wrapped_x, tile_y)
                pixmap = self.tile_pixmaps.get(key)
                if pixmap is None:
                    painter.fillRect(target_rect, colors["placeholder"])
                    self._request_tile(source_zoom, wrapped_x, tile_y)
                else:
                    painter.drawPixmap(target_rect, pixmap, QRectF(0, 0, pixmap.width(), pixmap.height()))

        if self.gps_track:
            track_list = list(self.gps_track)
            n_pts = len(track_list)
            if n_pts >= 2:
                for i in range(0, n_pts - 1):
                    p1 = track_list[i]
                    p2 = track_list[i + 1]
                    tx1, ty1 = self._gps_to_tile(p1[0], p1[1], source_zoom)
                    tx2, ty2 = self._gps_to_tile(p2[0], p2[1], source_zoom)
                    pt1 = QPointF(plot.left() + tx1 * render_tile_size - left_world, plot.top() + ty1 * render_tile_size - top_world)
                    pt2 = QPointF(plot.left() + tx2 * render_tile_size - left_world, plot.top() + ty2 * render_tile_size - top_world)
                    alpha = int(clamp(50 + 205 * (i / max(n_pts - 1, 1)), 50, 255))
                    pen = QPen(QColor(0, 212, 255, alpha), 3 if i > n_pts - 20 else 2)
                    painter.setPen(pen)
                    painter.drawLine(pt1, pt2)
        elif self.relative_track and self.home_latitude is not None and self.home_longitude is not None:
            path = QPainterPath()
            first = True
            for x_meters, y_meters in self.relative_track:
                latitude, longitude = self._meters_to_gps(x_meters, y_meters, self.home_latitude, self.home_longitude)
                tile_x, tile_y = self._gps_to_tile(latitude, longitude, source_zoom)
                screen_x = plot.left() + tile_x * render_tile_size - left_world
                screen_y = plot.top() + tile_y * render_tile_size - top_world
                point = QPointF(screen_x, screen_y)
                if first:
                    path.moveTo(point)
                    first = False
                else:
                    path.lineTo(point)
            painter.setPen(QPen(QColor(colors["track"]), 3))
            painter.drawPath(path)

        current_screen: QPointF | None = None
        current_latitude = self.display_latitude if self.display_latitude is not None else self.latitude
        current_longitude = self.display_longitude if self.display_longitude is not None else self.longitude
        if (current_latitude is None or current_longitude is None) and self.home_latitude is not None and self.home_longitude is not None:
            current_latitude, current_longitude = self._meters_to_gps(
                self.current_point[0],
                self.current_point[1],
                self.home_latitude,
                self.home_longitude,
            )

        if current_latitude is not None and current_longitude is not None:
            current_tile_x, current_tile_y = self._gps_to_tile(current_latitude, current_longitude, source_zoom)
            current_screen = QPointF(
                plot.left() + current_tile_x * render_tile_size - left_world,
                plot.top() + current_tile_y * render_tile_size - top_world,
            )

        # Draw Waypoints and Mission Line
        if self.waypoints:
            wp_pts: list[QPointF] = []
            for wp in self.waypoints:
                w_tx, w_ty = self._gps_to_tile(float(wp["lat"]), float(wp["lon"]), source_zoom)
                w_pt = QPointF(plot.left() + w_tx * render_tile_size - left_world, plot.top() + w_ty * render_tile_size - top_world)
                wp_pts.append(w_pt)

            mission_path = QPainterPath()
            if current_screen is not None:
                mission_path.moveTo(current_screen)
                for wp_pt in wp_pts:
                    mission_path.lineTo(wp_pt)
            elif wp_pts:
                mission_path.moveTo(wp_pts[0])
                for wp_pt in wp_pts[1:]:
                    mission_path.lineTo(wp_pt)

            dash_pen = QPen(QColor("#00f5ff"), 2, Qt.DashLine)
            dash_pen.setDashPattern([6, 4])
            painter.setPen(dash_pen)
            painter.drawPath(mission_path)

            for idx, (wp, wp_pt) in enumerate(zip(self.waypoints, wp_pts), 1):
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 245, 255, 55))
                painter.drawEllipse(wp_pt, 16, 16)
                painter.setPen(QPen(QColor("#00f5ff"), 2))
                painter.setBrush(QColor("#061526"))
                painter.drawEllipse(wp_pt, 11, 11)
                painter.setPen(QColor("#ffffff"))
                painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                painter.drawText(QRectF(wp_pt.x() - 11, wp_pt.y() - 11, 22, 22), Qt.AlignCenter, str(idx))
                alt_val = float(wp.get("alt", 20.0))
                lbl_rect = QRectF(wp_pt.x() - 22, wp_pt.y() - 26, 44, 14)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(5, 16, 28, 220))
                painter.drawRoundedRect(lbl_rect, 3, 3)
                painter.setPen(QColor("#00e5ff"))
                painter.setFont(QFont("Segoe UI", 7, QFont.DemiBold))
                painter.drawText(lbl_rect, Qt.AlignCenter, f"{alt_val:.0f}m")

        # Tactical Home Marker with safety distance rings
        if self.home_latitude is not None and self.home_longitude is not None:
            home_tile_x, home_tile_y = self._gps_to_tile(self.home_latitude, self.home_longitude, source_zoom)
            home_screen = QPointF(
                plot.left() + home_tile_x * render_tile_size - left_world,
                plot.top() + home_tile_y * render_tile_size - top_world,
            )
            lat_rad = np.deg2rad(self.home_latitude)
            m_per_px = 156543.03392 * np.cos(lat_rad) / (2 ** render_zoom)
            if m_per_px > 0:
                r50 = 50.0 / m_per_px
                r100 = 100.0 / m_per_px
                if r50 < plot.width():
                    ring_pen = QPen(QColor(16, 185, 129, 65), 1, Qt.DotLine)
                    painter.setPen(ring_pen)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(home_screen, r50, r50)
                    if r100 < plot.width():
                        painter.drawEllipse(home_screen, r100, r100)

            painter.setPen(QPen(QColor("#10b981"), 2))
            painter.setBrush(QColor("#062418"))
            painter.drawEllipse(home_screen, 12, 12)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.drawText(QRectF(home_screen.x() - 12, home_screen.y() - 12, 24, 24), Qt.AlignCenter, "H")

        # Drone heading arrow with radar pulse effect
        if current_screen is not None:
            pulse_radius = 16.0 + 7.0 * np.sin(self._pulse_phase)
            p_alpha = int(clamp(130 - 8 * pulse_radius, 25, 120))
            painter.setPen(QPen(QColor(0, 212, 255, p_alpha), 1.5))
            painter.setBrush(QColor(0, 212, 255, max(8, p_alpha // 4)))
            painter.drawEllipse(current_screen, pulse_radius, pulse_radius)
            self._draw_heading_arrow(painter, current_screen, self.displayed_heading)

        painter.restore()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = self._theme_colors()

        outer = self.rect().adjusted(8, 8, -8, -8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(colors["panel"])
        painter.drawRoundedRect(outer, 16, 16)
        plot = outer.adjusted(16, 20, -16, -44)
        painter.fillRect(plot, colors["bg"])

        if self.center_latitude is not None and self.center_longitude is not None:
            self._paint_satellite_map(painter, outer, plot, colors)
        else:
            self._paint_relative_map(painter, outer, plot, colors)

        self._draw_hud_overlay(painter, plot, colors)

        if self.controls_visible:
            self._draw_zones_control(painter, outer, colors)
            self._draw_center_control(painter, outer, colors)

    def _draw_hud_overlay(self, painter: QPainter, plot, colors: dict[str, QColor]) -> None:
        curr_lat, curr_lon = self._current_display_coordinates()

        # 1. Scale Bar (Bottom-Left)
        ref_lat = curr_lat if curr_lat is not None else DEFAULT_MAP_LATITUDE
        m_per_px = 156543.03392 * np.cos(np.deg2rad(ref_lat)) / (2 ** float(self.display_zoom_level))
        target_dist = 100.0
        scale_steps = [10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0]
        for step in scale_steps:
            px_w = step / max(m_per_px, 0.0001)
            if px_w >= 60.0:
                target_dist = step
                break
        bar_len_px = target_dist / max(m_per_px, 0.0001)
        scale_x = plot.left() + 12
        scale_y = plot.bottom() - 14
        if bar_len_px < plot.width() - 40:
            scale_bg = QRectF(scale_x - 4, scale_y - 18, bar_len_px + 8, 22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(4, 11, 21, 190))
            painter.drawRoundedRect(scale_bg, 4, 4)

            painter.setPen(QPen(QColor("#00f5ff"), 2))
            painter.drawLine(int(scale_x), int(scale_y), int(scale_x + bar_len_px), int(scale_y))
            painter.drawLine(int(scale_x), int(scale_y - 4), int(scale_x), int(scale_y + 4))
            painter.drawLine(int(scale_x + bar_len_px), int(scale_y - 4), int(scale_x + bar_len_px), int(scale_y + 4))

            lbl_dist = f"{target_dist:.0f} m" if target_dist < 1000 else f"{target_dist/1000:.1f} km"
            painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRectF(scale_x, scale_y - 17, bar_len_px, 14), Qt.AlignCenter, lbl_dist)

        # 3. Tactical HUD Action Buttons (Top-Right)
        if self.controls_visible:
            btn_y = plot.top() + 10
            right_edge = plot.right() - 10

            follow_w = 90
            self.follow_btn_rect = QRectF(right_edge - follow_w, btn_y, follow_w, 26)
            right_edge -= (follow_w + 6)
            f_bg = QColor("#0d281e" if self.follow_drone else "#291d09")
            if self._follow_btn_hovered:
                f_bg = f_bg.lighter(130)
            f_border = QColor("#10b981" if self.follow_drone else "#f59e0b")
            painter.setPen(QPen(f_border, 1))
            painter.setBrush(f_bg)
            painter.drawRoundedRect(self.follow_btn_rect, 5, 5)
            painter.setPen(Qt.NoPen)
            painter.setBrush(f_border)
            painter.drawEllipse(QPointF(self.follow_btn_rect.left() + 10, self.follow_btn_rect.center().y()), 3.5, 3.5)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            f_txt = "FOLLOW ON" if self.follow_drone else "FOLLOW OFF"
            painter.drawText(self.follow_btn_rect.adjusted(12, 0, 0, 0), Qt.AlignCenter, f_txt)

            fit_w = 60
            self.fit_all_btn_rect = QRectF(right_edge - fit_w, btn_y, fit_w, 26)
            right_edge -= (fit_w + 6)
            fit_bg = QColor("#142236" if not self._fit_all_btn_hovered else "#203656")
            painter.setPen(QPen(QColor("#2c4a70"), 1))
            painter.setBrush(fit_bg)
            painter.drawRoundedRect(self.fit_all_btn_rect, 5, 5)
            painter.setPen(QColor("#c5d7ed"))
            painter.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
            painter.drawText(self.fit_all_btn_rect, Qt.AlignCenter, "FIT ALL")

            add_w = 54
            self.add_wp_btn_rect = QRectF(right_edge - add_w, btn_y, add_w, 26)
            right_edge -= (add_w + 6)
            add_bg = QColor("#0077b6" if self.add_waypoint_mode else "#142236")
            if self._add_wp_btn_hovered:
                add_bg = add_bg.lighter(130)
            add_border = QColor("#00d4ff" if self.add_waypoint_mode else "#2c4a70")
            painter.setPen(QPen(add_border, 1))
            painter.setBrush(add_bg)
            painter.drawRoundedRect(self.add_wp_btn_rect, 5, 5)
            painter.setPen(QColor("#ffffff" if self.add_waypoint_mode else "#c5d7ed"))
            painter.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
            painter.drawText(self.add_wp_btn_rect, Qt.AlignCenter, "+ WP")

            if self.waypoints:
                clr_w = 70
                self.clear_wp_btn_rect = QRectF(right_edge - clr_w, btn_y, clr_w, 26)
                clr_bg = QColor("#2a1216" if not self._clear_wp_btn_hovered else "#451a22")
                painter.setPen(QPen(QColor("#ef4444"), 1))
                painter.setBrush(clr_bg)
                painter.drawRoundedRect(self.clear_wp_btn_rect, 5, 5)
                painter.setPen(QColor("#ff99a8"))
                painter.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
                painter.drawText(self.clear_wp_btn_rect, Qt.AlignCenter, "CLEAR WP")
            else:
                self.clear_wp_btn_rect = QRectF()

    def _draw_heading_arrow(self, painter: QPainter, position: QPointF, heading: float) -> None:
        painter.save()
        painter.translate(position)
        painter.rotate(heading)
        arrow = [
            QPointF(0, -16),
            QPointF(-10, 8),
            QPointF(0, 0),
            QPointF(10, 8),
        ]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ff3b30"))
        painter.drawPolygon(arrow)
        painter.restore()

    def _draw_center_control(self, painter: QPainter, outer, colors: dict[str, QColor]) -> None:
        diameter = 46
        margin = 2
        x = outer.right() - diameter - margin
        y = outer.bottom() - diameter - margin
        self.center_icon_rect = QRectF(x, y, diameter, diameter)

        glow = QColor("#d7edf9") if self.theme == "light" else QColor("#13314d")
        glow.setAlpha(136 if self._center_hovered else 86)
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(self.center_icon_rect.adjusted(6, 9, -6, -2))

        if not self.center_icon.isNull():
            icon_size = 34
            icon_rect = QRectF(
                self.center_icon_rect.center().x() - icon_size / 2,
                self.center_icon_rect.center().y() - icon_size / 2,
                icon_size,
                icon_size,
            )
            painter.drawPixmap(icon_rect, self.center_icon, QRectF(0, 0, self.center_icon.width(), self.center_icon.height()))

    def _draw_zones_control(self, painter: QPainter, outer, colors: dict[str, QColor]) -> None:
        width = 42
        height = 42
        margin = 2
        x = outer.left() + margin
        y = outer.bottom() - height - margin
        self.zones_button_rect = QRectF(x, y, width, height)

        glow = QColor("#d7edf9") if self.theme == "light" else QColor("#13314d")
        glow.setAlpha(132 if self._zones_hovered else 88)
        text_color = colors["text"]

        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(self.zones_button_rect.adjusted(5, 8, -5, -3))
        if not self.zones_icon.isNull():
            icon_size = 30
            icon_rect = QRectF(
                self.zones_button_rect.center().x() - icon_size / 2,
                self.zones_button_rect.center().y() - icon_size / 2,
                icon_size,
                icon_size,
            )
            painter.drawPixmap(icon_rect, self.zones_icon, QRectF(0, 0, self.zones_icon.width(), self.zones_icon.height()))
        else:
            painter.setPen(text_color)
            painter.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
            painter.drawText(self.zones_button_rect, Qt.AlignCenter, "Z")
