from __future__ import annotations

from collections import deque
import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from config import asset_path
from core.utils import clamp


class CircularGaugeWidget(QWidget):
    hold_activated = Signal()

    def __init__(
        self,
        title: str,
        unit: str,
        accent: str,
        max_value: float,
        threshold: float | None = None,
        dynamic_scale: bool = False,
    ) -> None:
        super().__init__()
        self.title = title
        self.unit = unit
        self.accent = QColor(accent)
        self.max_value = max_value
        self.threshold = threshold
        self.dynamic_scale = dynamic_scale
        self.value = 0.0
        self.sensor_active = False
        self.theme = "dark"
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self.hold_activated.emit)
        self.setMinimumSize(84, 84)

    def set_value(self, value: float) -> None:
        self.value = value
        if self.dynamic_scale:
            self.max_value = max(50.0, value * 1.25, self.max_value)
        self.update()

    def set_active_state(self, active: bool) -> None:
        self.sensor_active = active
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in {"dark", "light"} else "dark"
        self.update()

    def _theme_colors(self) -> dict[str, QColor]:
        if self.theme == "light":
            return {
                "track": QColor("#d7e2ee"),
                "value": QColor("#203246"),
                "subtext": QColor("#6b8198"),
                "active": QColor("#1f9d60"),
            }
        return {
            "track": QColor("#1d2740"),
            "value": QColor("#f4f8ff"),
            "subtext": QColor("#8ba5d6"),
            "active": QColor("#6de28c"),
        }

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._hold_timer.start(2000)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._hold_timer.stop()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = self._theme_colors()

        rect = self.rect().adjusted(8, 8, -8, -8)
        side = min(rect.width(), rect.height())
        square = rect.adjusted(
            (rect.width() - side) // 2,
            (rect.height() - side) // 2,
            -(rect.width() - side) // 2,
            -(rect.height() - side) // 2,
        )

        pen_width = 10
        painter.setPen(QPen(colors["track"], pen_width))
        painter.drawArc(square, 225 * 16, -270 * 16)

        color = self.accent
        if self.threshold is not None and self.value >= self.threshold:
            color = QColor("#ff7b72")

        ratio = clamp(self.value / max(self.max_value, 1.0), 0.0, 1.0)
        painter.setPen(QPen(color, pen_width))
        painter.drawArc(square, 225 * 16, int(-270 * ratio * 16))

        value_color = colors["active"] if self.sensor_active else colors["value"]
        painter.setPen(value_color)
        painter.setFont(QFont("Segoe UI", 15, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, f"{self.value:.0f}")

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(colors["subtext"])
        painter.drawText(self.rect().adjusted(0, 30, 0, 0), Qt.AlignCenter, self.unit)
        painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        painter.drawText(self.rect().adjusted(0, 0, 0, -4), Qt.AlignBottom | Qt.AlignHCenter, self.title)


class ArtificialHorizonWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.pitch = 0.0
        self.roll = 0.0
        self.theme = "dark"
        self.setMinimumSize(118, 118)
        self.interior_pixmap = self._load_first_available("Interior.png", "Interior3.png")
        self.ring_pixmap = self._load_first_available("Ring.png", "Ring3.png")

    def _load_first_available(self, *names: str) -> QPixmap:
        for name in names:
            pixmap = QPixmap(asset_path("img", name))
            if not pixmap.isNull():
                return pixmap
        return QPixmap()

    def set_attitude(self, pitch: float, roll: float) -> None:
        self.pitch = clamp(pitch, -45.0, 45.0)
        self.roll = clamp(roll, -60.0, 60.0)
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in {"dark", "light"} else "dark"
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(10, 10, -10, -10)
        side = min(rect.width(), rect.height())
        circle_rect = rect.adjusted(
            (rect.width() - side) // 2,
            (rect.height() - side) // 2,
            -(rect.width() - side) // 2,
            -(rect.height() - side) // 2,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#eff5fb") if self.theme == "light" else QColor("#0e1626"))
        painter.drawEllipse(circle_rect.adjusted(-2, -2, 2, 2))
        if not self.interior_pixmap.isNull() and not self.ring_pixmap.isNull():
            center = circle_rect.center()
            pitch_offset = (self.pitch / 45.0) * (circle_rect.height() * 0.10)

            interior = self.interior_pixmap.scaled(
                circle_rect.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            ring = self.ring_pixmap.scaled(
                circle_rect.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )

            painter.save()
            clip = QPainterPath()
            clip.addEllipse(circle_rect)
            painter.setClipPath(clip)
            painter.translate(center.x(), center.y() + pitch_offset)
            painter.rotate(-self.roll)
            painter.drawPixmap(-interior.width() // 2, -interior.height() // 2, interior)
            painter.restore()

            painter.drawPixmap(
                center.x() - ring.width() // 2,
                center.y() - ring.height() // 2,
                ring,
            )
            return

        painter.setPen(QPen(QColor("#2b4259") if self.theme == "light" else QColor("#dbe7ff"), 2))
        painter.drawEllipse(circle_rect)


class CompassWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.heading = 0.0
        self.displayed_heading = 0.0
        self.distance = 0.0
        self.theme = "dark"
        self.setMinimumSize(98, 98)
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._animate_heading)
        self._animation_timer.start(16)

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in {"dark", "light"} else "dark"
        self.update()

    def _theme_colors(self) -> dict[str, QColor]:
        if self.theme == "light":
            return {
                "ring": QColor("#bfd1e4"),
                "body": QColor("#f7fbff"),
                "tick": QColor("#68829f"),
                "north": QColor("#203246"),
                "label": QColor("#5f7891"),
                "center_text": QColor("#203246"),
                "center_fill": QColor("#edf5fd"),
                "distance": QColor("#607890"),
            }
        return {
            "ring": QColor("#213252"),
            "body": QColor("#0f1728"),
            "tick": QColor("#9bb4db"),
            "north": QColor("#f4f8ff"),
            "label": QColor("#8ea8d7"),
            "center_text": QColor("#dbe7ff"),
            "center_fill": QColor("#13213a"),
            "distance": QColor("#8ea8d7"),
        }

    def set_heading(self, heading: float, distance: float) -> None:
        self.heading = heading % 360
        self.distance = distance
        self.update()

    def _animate_heading(self) -> None:
        delta = (self.heading - self.displayed_heading + 540.0) % 360.0 - 180.0
        if abs(delta) < 0.15:
            self.displayed_heading = self.heading
        else:
            self.displayed_heading = (self.displayed_heading + delta * 0.14) % 360.0
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = self._theme_colors()

        rect = self.rect().adjusted(12, 18, -12, -12)
        side = min(rect.width(), rect.height())
        circle_rect = rect.adjusted(
            (rect.width() - side) // 2,
            (rect.height() - side) // 2,
            -(rect.width() - side) // 2,
            -(rect.height() - side) // 2,
        )
        center = circle_rect.center()
        radius = circle_rect.width() / 2

        painter.setPen(QPen(colors["ring"], 3))
        painter.setBrush(colors["body"])
        painter.drawEllipse(circle_rect)

        painter.translate(center)
        painter.rotate(-self.displayed_heading)
        painter.setPen(QPen(colors["tick"], 2))
        for degree in range(0, 360, 10):
            tick_length = 14 if degree % 30 == 0 else 8
            painter.drawLine(0, -int(radius - 12), 0, -int(radius - 12 - tick_length))
            painter.rotate(10)
        painter.resetTransform()

        directions = [("N", 0), ("E", 90), ("S", 180), ("W", 270)]
        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
        for label, angle in directions:
            radians = np.deg2rad(angle - self.displayed_heading - 90)
            x = center.x() + np.cos(radians) * (radius - 48)
            y = center.y() + np.sin(radians) * (radius - 48)
            painter.setPen(colors["north"] if label == "N" else colors["label"])
            painter.drawText(int(x - 6), int(y + 4), label)

        arrow_tip_y = center.y() - int(radius - 26)
        arrow_base_y = arrow_tip_y + 22
        arrow_half_width = 12
        notch_depth = 9
        arrow = [
            QPointF(center.x(), arrow_tip_y),
            QPointF(center.x() - arrow_half_width, arrow_base_y),
            QPointF(center.x(), arrow_base_y - notch_depth),
            QPointF(center.x() + arrow_half_width, arrow_base_y),
        ]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ff3b30"))
        painter.drawPolygon(arrow)

        painter.setPen(colors["center_text"])
        painter.setFont(QFont("Segoe UI", 13, QFont.Bold))
        heading_box = self.rect().adjusted(self.width() // 2 - 26, self.height() // 2 - 12, -(self.width() // 2 - 26), -(self.height() // 2 - 12))
        painter.drawText(heading_box, Qt.AlignCenter, f"{self.displayed_heading:.0f}°")


class TapeGaugeWidget(QWidget):
    def __init__(self, title: str, unit: str, minimum: float, maximum: float, accent: str) -> None:
        super().__init__()
        self.title = title
        self.unit = unit
        self.minimum = minimum
        self.maximum = maximum
        self.accent = QColor(accent)
        self.value = 0.0
        self.theme = "dark"
        self.major_step = 10.0 if maximum <= 200 else 100.0
        self.minor_step = self.major_step / 5.0
        self.setMinimumSize(36, 132)

    def set_value(self, value: float) -> None:
        self.value = value
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in {"dark", "light"} else "dark"
        self.update()

    def _theme_colors(self) -> dict[str, QColor]:
        if self.theme == "light":
            return {
                "outer": QColor("#f7fbff"),
                "border": QColor("#ccd9e8"),
                "track": QColor("#edf4fb"),
                "tick": QColor("#a3b5c8"),
                "major": QColor("#2a4057"),
                "window": QColor("#ffffff"),
                "value": QColor("#203246"),
                "label": QColor("#607890"),
            }
        return {
            "outer": QColor("#0f1728"),
            "border": QColor("#243453"),
            "track": QColor("#0a1220"),
            "tick": QColor("#314566"),
            "major": QColor("#dbe7ff"),
            "window": QColor("#13213a"),
            "value": QColor("#f4f8ff"),
            "label": QColor("#8ea8d7"),
        }

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = self._theme_colors()

        outer = self.rect().adjusted(6, 6, -6, -6)
        painter.fillRect(outer, colors["outer"])
        painter.setPen(QPen(colors["border"], 2))
        painter.drawRoundedRect(outer, 10, 10)

        tape_rect = outer.adjusted(4, 18, -4, -18)
        painter.fillRect(tape_rect, colors["track"])

        center_y = tape_rect.center().y()
        pixels_per_minor = 10.0
        first_tick = int(self.value / self.minor_step) - 12
        last_tick = int(self.value / self.minor_step) + 12

        painter.setPen(QPen(colors["tick"], 1))
        for tick_index in range(first_tick, last_tick + 1):
            tick_value = tick_index * self.minor_step
            offset = (tick_value - self.value) / self.minor_step * pixels_per_minor
            y = center_y - offset
            if y < tape_rect.top() or y > tape_rect.bottom():
                continue

            is_major = abs((tick_value / self.major_step) - round(tick_value / self.major_step)) < 1e-6
            line_length = 16 if is_major else 8
            painter.drawLine(tape_rect.right() - line_length, int(y), tape_rect.right(), int(y))

            if is_major:
                painter.setPen(colors["major"])
                painter.setFont(QFont("Segoe UI", 6, QFont.Bold))
                painter.drawText(tape_rect.left(), int(y) - 7, tape_rect.width() - 18, 14, Qt.AlignRight | Qt.AlignVCenter, f"{tick_value:.0f}")
                painter.setPen(QPen(colors["tick"], 1))

        window_rect = outer.adjusted(2, outer.height() // 2 - 12, -2, -(outer.height() // 2 - 12))
        painter.setPen(QPen(self.accent, 2))
        painter.setBrush(colors["window"])
        painter.drawRoundedRect(window_rect, 8, 8)
        painter.setPen(colors["value"])
        painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        painter.drawText(window_rect, Qt.AlignCenter, f"{self.value:.0f}")

        painter.setPen(colors["label"])
        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
        painter.drawText(outer.adjusted(0, 0, 0, -2), Qt.AlignBottom | Qt.AlignHCenter, self.title)


class BatteryWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.level = 100.0
        self.theme = "dark"
        self.setMinimumHeight(70)

    def set_level(self, level: float) -> None:
        self.level = clamp(level, 0.0, 100.0)
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in {"dark", "light"} else "dark"
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        outline = QColor("#2b4259") if self.theme == "light" else QColor("#dbe7ff")
        text = QColor("#203246") if self.theme == "light" else QColor("#dbe7ff")

        body = self.rect().adjusted(18, 28, -34, -18)
        terminal = self.rect().adjusted(self.width() - 34, self.height() // 2 - 18, -18, -(self.height() // 2 - 18))

        painter.setPen(QPen(outline, 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(body, 12, 12)
        painter.drawRoundedRect(terminal, 4, 4)

        padding = 8
        level_rect = body.adjusted(padding, padding, -padding, -padding)
        fill_width = int(level_rect.width() * (self.level / 100.0))
        fill_rect = level_rect.adjusted(0, 0, -(level_rect.width() - fill_width), 0)

        color = QColor("#6de28c") if self.level >= 35 else QColor("#f7c86e") if self.level >= 15 else QColor("#ff7b72")
        painter.fillRect(fill_rect, color)

        painter.setPen(text)
        painter.setFont(QFont("Segoe UI", 13, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, f"{self.level:.0f}%")


class SparklineWidget(QWidget):
    def __init__(self, accent: str, max_points: int = 90) -> None:
        super().__init__()
        self.accent = QColor(accent)
        self.values: deque[float] = deque(maxlen=max_points)
        self.theme = "dark"
        self.setMinimumHeight(82)

    def append_value(self, value: float) -> None:
        self.values.append(value)
        self.update()

    def set_values(self, values: list[float]) -> None:
        self.values.clear()
        self.values.extend(values)
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in {"dark", "light"} else "dark"
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        background = QColor("#f6fbff") if self.theme == "light" else QColor("#101728")
        empty_text = QColor("#617b95") if self.theme == "light" else QColor("#7488b5")
        grid = QColor("#cfdae6") if self.theme == "light" else QColor("#28334f")

        plot_rect = self.rect().adjusted(8, 8, -8, -8)
        painter.fillRect(self.rect(), background)

        if not self.values:
            painter.setPen(empty_text)
            painter.drawText(self.rect(), Qt.AlignCenter, "spectre")
            return

        painter.setPen(QPen(grid, 1))
        for step in range(5):
            y = plot_rect.top() + step * plot_rect.height() / 4
            painter.drawLine(plot_rect.left(), int(y), plot_rect.right(), int(y))

        sample_size = min(32, len(self.values))
        samples = list(self.values)[-sample_size:]
        maximum = max(max(samples), 100.0)
        bar_width = max(plot_rect.width() / max(sample_size, 1), 2)
        painter.setPen(Qt.NoPen)
        for index, value in enumerate(samples):
            ratio = value / maximum
            height = max(3, int(plot_rect.height() * ratio))
            x = plot_rect.left() + index * bar_width
            bar_rect = plot_rect.adjusted(int(x - plot_rect.left()), plot_rect.height() - height, -int(plot_rect.width() - (index + 1) * bar_width), 0)
            alpha = 110 + int(145 * (index / max(sample_size - 1, 1)))
            color = QColor(self.accent)
            color.setAlpha(alpha)
            painter.fillRect(bar_rect, color)
