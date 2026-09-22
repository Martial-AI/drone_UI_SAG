from __future__ import annotations

import time
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.models import SensorData
from core.i18n import UI_TEXTS
from core.utils import clamp


class Radar360Widget(QWidget):
    obstacle_count_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = "dark"
        self._language = "en"
        self.points: tuple[tuple[float, float], ...] = ()
        self._point_distances: dict[int, float] = {}
        self._point_timestamps: dict[int, float] = {}
        self.max_range_m = 8.0
        self.point_ttl_seconds = 8.0
        self.sweep_angle = 0.0
        self.sweep_timer = QTimer(self)
        self.sweep_timer.setInterval(33)
        self.sweep_timer.timeout.connect(self._advance_sweep)
        self.sweep_timer.start()
        self.setMinimumSize(190, 190)

    def set_theme(self, theme: str) -> None:
        self._theme = theme if theme in {"dark", "light"} else "dark"
        self.update()
        self.obstacle_count_changed.emit(len(self.points))

    def set_language(self, language: str) -> None:
        self._language = language if language in UI_TEXTS else "en"
        self.update()

    def _text(self, key: str) -> str:
        return UI_TEXTS.get(self._language, UI_TEXTS["en"]).get(key, UI_TEXTS["en"].get(key, key))

    def set_points(self, points: tuple[tuple[float, float], ...]) -> None:
        now = time.monotonic()
        for angle, distance in points:
            angle_key = int(round(angle)) % 360
            if distance <= 0:
                self._point_distances.pop(angle_key, None)
                self._point_timestamps.pop(angle_key, None)
                continue
            self._point_distances[angle_key] = distance
            self._point_timestamps[angle_key] = now

        self._expire_old_points(now)

        self.points = tuple((float(angle), distance) for angle, distance in sorted(self._point_distances.items()))
        if self.points:
            farthest = max(distance for _angle, distance in self.points)
            self.max_range_m = max(2.0, min(50.0, farthest * 1.15))
        self.update()
        self.obstacle_count_changed.emit(len(self.points))

    def _advance_sweep(self) -> None:
        self.sweep_angle = (self.sweep_angle + 2.4) % 360.0
        before_count = len(self.points)
        self._expire_old_points(time.monotonic())
        if len(self.points) != before_count:
            self.obstacle_count_changed.emit(len(self.points))
        self.update()

    def _expire_old_points(self, now: float) -> None:
        expired_angles = [
            angle
            for angle, timestamp in self._point_timestamps.items()
            if now - timestamp > self.point_ttl_seconds
        ]
        for angle in expired_angles:
            self._point_distances.pop(angle, None)
            self._point_timestamps.pop(angle, None)
        if expired_angles:
            self.points = tuple((float(angle), distance) for angle, distance in sorted(self._point_distances.items()))

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)
        size = min(rect.width(), rect.height())
        radar_rect = QRectF(
            rect.center().x() - size / 2,
            rect.center().y() - size / 2,
            size,
            size,
        )
        center = radar_rect.center()
        radius = radar_rect.width() / 2

        if self._theme == "light":
            ring = QColor("#8aa5bd")
            grid = QColor("#cbd9e5")
            sweep = QColor("#1686a8")
            dot = QColor("#ff4f5e")
            text = QColor("#32485c")
        else:
            ring = QColor("#3a5a78")
            grid = QColor("#213853")
            sweep = QColor("#5ec8f8")
            dot = QColor("#ff6572")
            text = QColor("#dbe7ff")

        painter.setPen(QPen(grid, 1))
        painter.setBrush(Qt.NoBrush)
        for scale in (0.25, 0.5, 0.75, 1.0):
            r = radius * scale
            painter.drawEllipse(center, r, r)
        painter.setPen(QPen(ring, 1))
        painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - radius), QPointF(center.x(), center.y() + radius))

        sweep_rad = np.deg2rad(self.sweep_angle)
        sweep_end = QPointF(
            float(center.x() + np.sin(sweep_rad) * radius),
            float(center.y() - np.cos(sweep_rad) * radius),
        )
        painter.setPen(QPen(sweep, 2))
        painter.drawLine(center, sweep_end)
        painter.setBrush(sweep)
        painter.drawEllipse(center, 4, 4)

        painter.setPen(Qt.NoPen)
        painter.setBrush(dot)
        for angle, distance in self.points:
            normalized = clamp(distance / max(self.max_range_m, 0.1), 0.0, 1.0)
            angle_rad = np.deg2rad(angle)
            x = center.x() + np.sin(angle_rad) * radius * normalized
            y = center.y() - np.cos(angle_rad) * radius * normalized
            painter.drawEllipse(QPointF(float(x), float(y)), 4, 4)

        painter.setPen(text)
        painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        painter.drawText(radar_rect.adjusted(4, 4, -4, -4), Qt.AlignTop | Qt.AlignHCenter, f"{self.max_range_m:.0f} m")

    def obstacle_count(self) -> int:
        return len(self.points)


class FloatingRadarWidget(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._language = "en"
        self._drag_start: QPointF | None = None
        self._resize_start: QPointF | None = None
        self._resize_geometry = QRectF()
        self.setObjectName("floatingRadar")
        self.setMinimumSize(220, 245)
        self.resize(260, 285)
        self.setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.title_label = QLabel("OBS AVOIDER")
        self.title_label.setObjectName("floatingTitle")
        self.obstacle_count_label = QLabel("0 OBS")
        self.obstacle_count_label.setObjectName("floatingTitle")
        self.obstacle_count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.obstacle_count_label, 0)
        layout.addLayout(header)
        self.radar = Radar360Widget(self)
        self.radar.obstacle_count_changed.connect(self._update_obstacle_count)
        layout.addWidget(self.radar, 1)

    def _text(self, key: str) -> str:
        return UI_TEXTS.get(self._language, UI_TEXTS["en"]).get(key, UI_TEXTS["en"].get(key, key))

    def set_language(self, language: str) -> None:
        self._language = language if language in UI_TEXTS else "en"
        self.title_label.setText("OBS AVOIDER")
        self.radar.set_language(self._language)

    def set_theme(self, theme: str) -> None:
        self.radar.set_theme(theme)

    def update_sensor_data(self, data: SensorData) -> None:
        self.radar.set_points(data.lidar_points)

    def _update_obstacle_count(self, count: int) -> None:
        self.obstacle_count_label.setText(f"{count} OBS")

    def update_video_frame(self, _mode: str, _frame: QImage | None) -> None:
        return

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        local_pos = event.position()
        if local_pos.x() >= self.width() - 18 and local_pos.y() >= self.height() - 18:
            self._resize_start = event.globalPosition()
            self._resize_geometry = QRectF(self.geometry())
        else:
            self._drag_start = event.globalPosition() - QPointF(self.pos())
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._resize_start is not None:
            delta = event.globalPosition() - self._resize_start
            self.resize(
                max(self.minimumWidth(), int(self._resize_geometry.width() + delta.x())),
                max(self.minimumHeight(), int(self._resize_geometry.height() + delta.y())),
            )
            event.accept()
            return
        if self._drag_start is not None:
            new_pos = event.globalPosition() - self._drag_start
            parent = self.parentWidget()
            if parent is not None:
                self.move(
                    max(0, min(int(new_pos.x()), parent.width() - self.width())),
                    max(0, min(int(new_pos.y()), parent.height() - self.height())),
                )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_start = None
        self._resize_start = None
        super().mouseReleaseEvent(event)
