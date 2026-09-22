from __future__ import annotations

import time
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from core.models import SensorData
from core.utils import clamp


class VideoOSDWidget(QWidget):
    """Tactical On-Screen Display (OSD) overlay for live FPV video feed.

    Renders flight telemetry directly over the video stream:
      - Pitch & Roll artificial horizon ladder with reticle
      - Left speed tape & Right altitude tape
      - Top tactical bar: Flight Mode, Armed status, Battery %, GPS sats, Flight time
      - Bottom compass ribbon with Home direction pointer
      - Modes: FULL (all elements), MINIMAL (reticle + basic stats), OFF (video only)
    """

    MODE_FULL = "FULL"
    MODE_MINIMAL = "MIN"
    MODE_OFF = "OFF"
    MODES = [MODE_FULL, MODE_MINIMAL, MODE_OFF]

    mode_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode_index = 0
        self._osd_mode = self.MODES[self._mode_index]
        self._theme = "dark"
        self._language = "en"

        # Telemetry cache
        self.pitch = 0.0
        self.roll = 0.0
        self.heading = 0.0
        self.altitude = 0.0
        self.speed = 0.0
        self.battery_level = 100.0
        self.satellites = 0
        self.flight_mode = "MANUAL"
        self.is_armed = False
        self.home_bearing: float | None = None
        self.flight_start_time: float | None = None

        # Video frame cache
        self._current_frame: QImage | None = None
        self._current_pixmap: QPixmap | None = None
        self._no_signal_text = "NO VIDEO SIGNAL"

        # Blink/pulse phase for tactical indicators
        self._pulse_phase = 0.0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)  # ~30 fps
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_timer.start()

        self.setMinimumSize(320, 240)
        self.setFocusPolicy(Qt.StrongFocus)

    def cycle_osd_mode(self) -> str:
        """Cycle through FULL -> MIN -> OFF -> FULL."""
        self._mode_index = (self._mode_index + 1) % len(self.MODES)
        self._osd_mode = self.MODES[self._mode_index]
        self.mode_changed.emit(self._osd_mode)
        self.update()
        return self._osd_mode

    def set_osd_mode(self, mode: str) -> None:
        if mode in self.MODES:
            self._osd_mode = mode
            self._mode_index = self.MODES.index(mode)
            self.mode_changed.emit(self._osd_mode)
            self.update()

    @property
    def osd_mode(self) -> str:
        return self._osd_mode

    def set_theme(self, theme: str) -> None:
        self._theme = theme if theme in {"dark", "light"} else "dark"
        self.update()

    def set_language(self, language: str) -> None:
        self._language = language

    def update_frame(self, frame: QImage | None) -> None:
        self._current_frame = frame
        if frame is not None:
            self._current_pixmap = QPixmap.fromImage(frame)
        else:
            self._current_pixmap = None
        self.update()

    def update_telemetry(self, data: SensorData) -> None:
        self.pitch = clamp(getattr(data, "pitch", 0.0), -90.0, 90.0)
        self.roll = clamp(getattr(data, "roll", 0.0), -180.0, 180.0)
        self.heading = getattr(data, "heading", 0.0) % 360.0
        self.altitude = max(0.0, getattr(data, "altitude", 0.0))
        self.speed = max(0.0, getattr(data, "gps_speed", 0.0))
        battery_val = getattr(data, "battery", getattr(data, "battery_level", 100.0))
        self.battery_level = clamp(battery_val, 0.0, 100.0)
        self.satellites = getattr(data, "satellites", 12 if data.latitude is not None else 0)
        flight_mode_val = getattr(data, "flight_mode", None)
        if flight_mode_val:
            self.flight_mode = flight_mode_val
        self.is_armed = getattr(data, "is_armed", self.is_armed)
        self.update()

    def set_flight_mode(self, mode: str) -> None:
        self.flight_mode = mode
        self.update()

    def set_armed(self, armed: bool) -> None:
        self.is_armed = armed
        self.update()

    def set_home_bearing(self, bearing: float | None) -> None:
        self.home_bearing = bearing
        self.update()

    def set_flight_start(self, start_time: float | None) -> None:
        self.flight_start_time = start_time
        self.update()

    def _on_anim_tick(self) -> None:
        self._pulse_phase = (self._pulse_phase + 0.1) % (2 * np.pi)
        if self._osd_mode != self.MODE_OFF:
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # Clicking the top-right OSD button area toggles mode
        top_right_btn = QRectF(self.width() - 85, 10, 75, 26)
        if top_right_btn.contains(event.position()):
            self.cycle_osd_mode()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_O:
            self.cycle_osd_mode()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        rect = self.rect()

        # 1. Background / Video frame
        if self._current_pixmap is not None and not self._current_pixmap.isNull():
            # Scale video preserving aspect ratio, letterbox centered
            scaled = self._current_pixmap.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x_pos = (rect.width() - scaled.width()) // 2
            y_pos = (rect.height() - scaled.height()) // 2
            painter.fillRect(rect, QColor("#000000"))
            painter.drawPixmap(x_pos, y_pos, scaled)
        else:
            # Standby tactical grid
            painter.fillRect(rect, QColor("#060a12"))
            self._draw_standby_grid(painter, rect)

        # If OSD is OFF, only show a tiny discreet mode badge at top right
        if self._osd_mode == self.MODE_OFF:
            self._draw_mode_toggle_badge(painter, rect)
            return

        # 2. Central Artificial Horizon & Reticle
        center_x = rect.width() / 2.0
        center_y = rect.height() / 2.0

        if self._osd_mode == self.MODE_FULL:
            self._draw_pitch_ladder(painter, center_x, center_y)

        self._draw_aircraft_reticle(painter, center_x, center_y)

        # 3. Side Tapes (Speed left, Altitude right) in FULL mode
        if self._osd_mode == self.MODE_FULL:
            self._draw_speed_tape(painter, rect)
            self._draw_altitude_tape(painter, rect)
            self._draw_compass_ribbon(painter, rect)

        # 4. Top Header Banner (Mode, Arm, Battery, Sats, Clock)
        self._draw_top_banner(painter, rect)

        # 5. OSD Mode Switcher Badge (top-right click target)
        self._draw_mode_toggle_badge(painter, rect)

    def _draw_standby_grid(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor(16, 40, 70, 70), 1, Qt.DotLine))
        step = 40
        for x in range(0, int(rect.width()), step):
            painter.drawLine(x, 0, x, int(rect.height()))
        for y in range(0, int(rect.height()), step):
            painter.drawLine(0, y, int(rect.width()), y)

        # Warning text
        pulse_alpha = int(170 + 85 * np.sin(self._pulse_phase))
        painter.setPen(QColor(0, 212, 255, pulse_alpha))
        painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
        painter.drawText(rect, Qt.AlignCenter, f"⚡ {self._no_signal_text} ⚡")

    def _draw_aircraft_reticle(self, painter: QPainter, cx: float, cy: float) -> None:
        """Fixed aircraft reticle (center crosshair & wings)."""
        color = QColor("#00f5ff")
        painter.setPen(QPen(color, 2))

        # Center dot
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy), 3, 3)

        # Left wing
        painter.drawLine(int(cx - 36), int(cy), int(cx - 14), int(cy))
        painter.drawLine(int(cx - 14), int(cy), int(cx - 14), int(cy + 6))

        # Right wing
        painter.drawLine(int(cx + 14), int(cy), int(cx + 36), int(cy))
        painter.drawLine(int(cx + 14), int(cy), int(cx + 14), int(cy + 6))

    def _draw_pitch_ladder(self, painter: QPainter, cx: float, cy: float) -> None:
        """Dynamic pitch ladder rotating with roll and shifting with pitch."""
        painter.save()
        # Clip to central area
        clip_w = min(self.width() * 0.65, 360)
        clip_h = min(self.height() * 0.65, 300)
        clip_rect = QRectF(cx - clip_w / 2, cy - clip_h / 2, clip_w, clip_h)
        painter.setClipRect(clip_rect)

        # Translate to aircraft center, rotate with roll
        painter.translate(cx, cy)
        painter.rotate(-self.roll)

        pixels_per_deg = 4.5
        pitch_offset = self.pitch * pixels_per_deg

        hud_color = QColor(0, 245, 255, 200)
        painter.setPen(QPen(hud_color, 1.5))
        painter.setFont(QFont("Consolas", 8, QFont.Bold))

        # Draw pitch rungs (-30° to +30° in 10° steps)
        for deg in range(-30, 35, 10):
            if deg == 0:
                # Horizon line
                y = -pitch_offset
                painter.setPen(QPen(QColor(16, 185, 129, 230), 2))
                painter.drawLine(-70, int(y), -20, int(y))
                painter.drawLine(20, int(y), 70, int(y))
                continue

            y = -(deg * pixels_per_deg + pitch_offset)
            rung_width = 38 if abs(deg) % 10 == 0 else 24

            painter.setPen(QPen(hud_color, 1.5))
            if deg > 0:
                # Positive pitch: solid ladder
                painter.drawLine(-rung_width, int(y), -14, int(y))
                painter.drawLine(-rung_width, int(y), -rung_width, int(y + 5))
                painter.drawLine(14, int(y), rung_width, int(y))
                painter.drawLine(rung_width, int(y), rung_width, int(y + 5))
            else:
                # Negative pitch: dashed ladder
                pen = QPen(hud_color, 1.5, Qt.DashLine)
                painter.setPen(pen)
                painter.drawLine(-rung_width, int(y), -14, int(y))
                painter.drawLine(14, int(y), rung_width, int(y))
                painter.setPen(QPen(hud_color, 1.5))
                painter.drawLine(-rung_width, int(y), -rung_width, int(y - 5))
                painter.drawLine(rung_width, int(y), rung_width, int(y - 5))

            # Pitch number label
            painter.drawText(rung_width + 5, int(y + 4), f"{abs(deg)}")
            painter.drawText(-rung_width - 20, int(y + 4), f"{abs(deg)}")

        painter.restore()

    def _draw_speed_tape(self, painter: QPainter, rect: QRectF) -> None:
        """Left-side vertical speed tape (km/h)."""
        tape_w = 54
        tape_h = min(220, int(rect.height() * 0.6))
        x = 18
        y = (rect.height() - tape_h) / 2

        # Background glass box
        box_rect = QRectF(x, y, tape_w, tape_h)
        painter.setPen(QPen(QColor(0, 212, 255, 100), 1))
        painter.setBrush(QColor(6, 15, 28, 175))
        painter.drawRoundedRect(box_rect, 6, 6)

        # Center readout window
        center_y = y + tape_h / 2
        window_rect = QRectF(x + 2, center_y - 12, tape_w - 4, 24)
        painter.setPen(QPen(QColor("#00f5ff"), 1.5))
        painter.setBrush(QColor(0, 119, 182, 210))
        painter.drawRoundedRect(window_rect, 4, 4)

        # Current speed text
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        painter.drawText(window_rect, Qt.AlignCenter, f"{self.speed:.1f}")

        # Label title
        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
        painter.setPen(QColor(0, 212, 255, 220))
        painter.drawText(QRectF(x, y + 4, tape_w, 14), Qt.AlignCenter, "SPD km/h")

        # Ticks along the right edge of tape
        pixels_per_unit = 5.0
        step = 5.0
        painter.setPen(QPen(QColor(0, 212, 255, 160), 1))
        for spd_val in range(int(self.speed - 25), int(self.speed + 25)):
            if spd_val < 0 or spd_val % int(step) != 0:
                continue
            offset = (spd_val - self.speed) * pixels_per_unit
            tick_y = center_y - offset
            if y + 18 <= tick_y <= y + tape_h - 18:
                painter.drawLine(int(x + tape_w - 8), int(tick_y), int(x + tape_w - 2), int(tick_y))

    def _draw_altitude_tape(self, painter: QPainter, rect: QRectF) -> None:
        """Right-side vertical altitude tape (m) with VSI indicator."""
        tape_w = 56
        tape_h = min(220, int(rect.height() * 0.6))
        x = rect.width() - tape_w - 18
        y = (rect.height() - tape_h) / 2

        # Background glass box
        box_rect = QRectF(x, y, tape_w, tape_h)
        painter.setPen(QPen(QColor(0, 212, 255, 100), 1))
        painter.setBrush(QColor(6, 15, 28, 175))
        painter.drawRoundedRect(box_rect, 6, 6)

        # Center readout window
        center_y = y + tape_h / 2
        window_rect = QRectF(x + 2, center_y - 12, tape_w - 4, 24)
        painter.setPen(QPen(QColor("#00f5ff"), 1.5))
        painter.setBrush(QColor(0, 119, 182, 210))
        painter.drawRoundedRect(window_rect, 4, 4)

        # Current altitude text
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        painter.drawText(window_rect, Qt.AlignCenter, f"{self.altitude:.1f}")

        # Label title
        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
        painter.setPen(QColor(0, 212, 255, 220))
        painter.drawText(QRectF(x, y + 4, tape_w, 14), Qt.AlignCenter, "ALT m")

        # Ticks along the left edge of tape
        pixels_per_unit = 5.0
        step = 5.0
        painter.setPen(QPen(QColor(0, 212, 255, 160), 1))
        for alt_val in range(int(self.altitude - 25), int(self.altitude + 25)):
            if alt_val < 0 or alt_val % int(step) != 0:
                continue
            offset = (alt_val - self.altitude) * pixels_per_unit
            tick_y = center_y - offset
            if y + 18 <= tick_y <= y + tape_h - 18:
                painter.drawLine(int(x + 2), int(tick_y), int(x + 8), int(tick_y))

    def _draw_compass_ribbon(self, painter: QPainter, rect: QRectF) -> None:
        """Bottom tactical compass ribbon showing 360° heading tape and home bearing."""
        ribbon_w = min(rect.width() * 0.65, 340)
        ribbon_h = 32
        x = (rect.width() - ribbon_w) / 2
        y = rect.height() - ribbon_h - 10

        # Frame
        box_rect = QRectF(x, y, ribbon_w, ribbon_h)
        painter.setPen(QPen(QColor(0, 212, 255, 120), 1))
        painter.setBrush(QColor(6, 15, 28, 190))
        painter.drawRoundedRect(box_rect, 6, 6)

        center_x = x + ribbon_w / 2
        pixels_per_deg = 2.4

        painter.save()
        painter.setClipRect(box_rect)

        # Center marker needle
        painter.setPen(QPen(QColor("#00f5ff"), 2))
        painter.drawLine(int(center_x), int(y), int(center_x), int(y + 10))

        # Home pointer indicator (if set)
        if self.home_bearing is not None:
            home_diff = (self.home_bearing - self.heading + 540.0) % 360.0 - 180.0
            home_x = center_x + home_diff * pixels_per_deg
            if x <= home_x <= x + ribbon_w:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("#10b981"))
                home_poly = [
                    QPointF(home_x, y + 2),
                    QPointF(home_x - 5, y + 9),
                    QPointF(home_x + 5, y + 9),
                ]
                painter.drawPolygon(home_poly)
                painter.setFont(QFont("Segoe UI", 6, QFont.Bold))
                painter.setPen(QColor("#ffffff"))
                painter.drawText(QRectF(home_x - 10, y + 10, 20, 10), Qt.AlignCenter, "H")

        cardinals = {0: "N", 45: "NE", 90: "E", 135: "SE", 180: "S", 225: "SW", 270: "W", 315: "NW"}

        for deg in range(0, 360, 5):
            diff = (deg - self.heading + 540.0) % 360.0 - 180.0
            tick_x = center_x + diff * pixels_per_deg
            if not (x - 20 <= tick_x <= x + ribbon_w + 20):
                continue

            is_cardinal = deg in cardinals
            is_major = deg % 15 == 0

            tick_len = 10 if is_cardinal or is_major else 5
            pen_color = QColor("#00f5ff") if is_cardinal else QColor(0, 212, 255, 120)
            painter.setPen(QPen(pen_color, 1.5 if is_cardinal else 1.0))
            painter.drawLine(int(tick_x), int(y + ribbon_h - tick_len), int(tick_x), int(y + ribbon_h))

            if is_cardinal:
                painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                painter.setPen(QColor("#ff3b30" if deg == 0 else "#00f5ff"))
                painter.drawText(QRectF(tick_x - 12, y + 2, 24, 14), Qt.AlignCenter, cardinals[deg])
            elif is_major:
                painter.setFont(QFont("Segoe UI", 6))
                painter.setPen(QColor(180, 220, 255, 180))
                painter.drawText(QRectF(tick_x - 12, y + 5, 24, 12), Qt.AlignCenter, f"{deg}")

        painter.restore()

        # Center readout bubble
        readout_w = 40
        readout_rect = QRectF(center_x - readout_w / 2, y - 18, readout_w, 16)
        painter.setPen(QPen(QColor("#00f5ff"), 1))
        painter.setBrush(QColor(0, 119, 182, 220))
        painter.drawRoundedRect(readout_rect, 3, 3)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        painter.drawText(readout_rect, Qt.AlignCenter, f"{int(self.heading)}°")

    def _draw_top_banner(self, painter: QPainter, rect: QRectF) -> None:
        """Top tactical HUD banner with Flight Mode, Armed status, Battery, GPS, Clock."""
        banner_h = 28
        banner_rect = QRectF(10, 10, min(rect.width() - 105, 560), banner_h)

        painter.setPen(QPen(QColor(0, 212, 255, 80), 1))
        painter.setBrush(QColor(6, 15, 28, 200))
        painter.drawRoundedRect(banner_rect, 6, 6)

        # 1. Armed Badge
        arm_color = QColor("#ef4444") if self.is_armed else QColor("#10b981")
        arm_text = "ARMED" if self.is_armed else "DISARMED"
        arm_rect = QRectF(banner_rect.left() + 6, banner_rect.top() + 4, 74, 20)
        painter.setPen(QPen(arm_color, 1))
        painter.setBrush(QColor(arm_color.red(), arm_color.green(), arm_color.blue(), 45))
        painter.drawRoundedRect(arm_rect, 4, 4)
        painter.setPen(arm_color)
        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
        painter.drawText(arm_rect, Qt.AlignCenter, arm_text)

        # 2. Flight Mode
        mode_rect = QRectF(arm_rect.right() + 6, banner_rect.top() + 4, 66, 20)
        painter.setPen(QPen(QColor(0, 212, 255, 120), 1))
        painter.setBrush(QColor(0, 119, 182, 60))
        painter.drawRoundedRect(mode_rect, 4, 4)
        painter.setPen(QColor("#00f5ff"))
        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
        painter.drawText(mode_rect, Qt.AlignCenter, self.flight_mode)

        # 3. Battery gauge
        bat_color = QColor("#10b981") if self.battery_level >= 35 else QColor("#f59e0b") if self.battery_level >= 15 else QColor("#ef4444")
        bat_x = mode_rect.right() + 10
        painter.setPen(QColor("#c5d7ed"))
        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        painter.drawText(QRectF(bat_x, banner_rect.top(), 80, banner_h), Qt.AlignVCenter | Qt.AlignLeft, f"🔋 {self.battery_level:.0f}%")

        # 4. GPS Sats
        sat_x = bat_x + 75
        painter.setPen(QColor("#00e5ff"))
        painter.drawText(QRectF(sat_x, banner_rect.top(), 80, banner_h), Qt.AlignVCenter | Qt.AlignLeft, f"🛰 {self.satellites} SAT")

        # 5. Flight Clock
        if self.flight_start_time is not None:
            elapsed = int(time.monotonic() - self.flight_start_time)
            m, s = divmod(elapsed, 60)
            clock_text = f"⏱ {m:02d}:{s:02d}"
        else:
            clock_text = "⏱ 00:00"
        clock_x = sat_x + 85
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(clock_x, banner_rect.top(), 80, banner_h), Qt.AlignVCenter | Qt.AlignLeft, clock_text)

    def _draw_mode_toggle_badge(self, painter: QPainter, rect: QRectF) -> None:
        """Clickable badge at top-right to toggle OSD mode (FULL / MIN / OFF)."""
        btn_rect = QRectF(rect.width() - 85, 10, 75, 26)

        color_map = {
            self.MODE_FULL: ("#00d4ff", "#07263b"),
            self.MODE_MINIMAL: ("#f59e0b", "#3b2607"),
            self.MODE_OFF: ("#64748b", "#141c2b"),
        }
        border_col, bg_col = color_map.get(self._osd_mode, color_map[self.MODE_FULL])

        painter.setPen(QPen(QColor(border_col), 1))
        painter.setBrush(QColor(bg_col))
        painter.drawRoundedRect(btn_rect, 5, 5)

        painter.setPen(QColor(border_col))
        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
        painter.drawText(btn_rect, Qt.AlignCenter, f"OSD: {self._osd_mode}")
