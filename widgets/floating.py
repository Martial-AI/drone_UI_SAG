from __future__ import annotations

from collections import deque
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.models import SensorData
from core.i18n import UI_TEXTS
from core.utils import clamp
from .map_widget import OfflineMapWidget


class FloatingScienceChartWidget(QWidget):
    SERIES = (
        ("CO2", "co2", QColor("#5ec8f8")),
        ("LPG", "lpg", QColor("#f7c86e")),
        ("HUM", "humidity", QColor("#79e3d8")),
        ("TEMP", "temperature", QColor("#ffb86c")),
        ("RAD", "radiation", QColor("#ff7b72")),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = "dark"
        self._samples = 0
        self._histories: dict[str, deque[float]] = {
            key: deque(maxlen=90)
            for _label, key, _color in self.SERIES
        }
        self.setObjectName("floatingData")
        self.setMinimumHeight(120)

    def set_theme(self, theme: str) -> None:
        self._theme = theme if theme in {"dark", "light"} else "dark"
        self.update()

    def append_data(self, data: SensorData) -> None:
        self._samples += 1
        self._histories["co2"].append(data.co2)
        self._histories["lpg"].append(data.lpg)
        self._histories["humidity"].append(data.humidity)
        self._histories["temperature"].append(data.temperature)
        self._histories["radiation"].append(data.radiation)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        background = QColor("#f6fbff") if self._theme == "light" else QColor("#0d1625")
        grid = QColor("#cfdae6") if self._theme == "light" else QColor("#253c58")
        text = QColor("#32485c") if self._theme == "light" else QColor("#dbe7ff")
        muted = QColor("#6c849c") if self._theme == "light" else QColor("#8ea8d7")

        painter.fillRect(self.rect(), background)
        plot = self.rect().adjusted(34, 8, -8, -22)
        if plot.width() <= 8 or plot.height() <= 8:
            return

        all_values: list[float] = []
        for _label, key, _color in self.SERIES:
            all_values.extend(float(value) for value in self._histories[key])
        if len(all_values) < 2:
            painter.setPen(muted)
            painter.drawText(self.rect(), Qt.AlignCenter, "DATA")
            return

        minimum = min(all_values)
        maximum = max(all_values)
        if minimum == maximum:
            maximum = minimum + 1.0
        padding = (maximum - minimum) * 0.08
        minimum = max(0.0, minimum - padding)
        maximum += padding
        span = max(maximum - minimum, 1.0)

        def format_tick(value: float) -> str:
            if abs(value) >= 100:
                return f"{value:.0f}"
            if abs(value) >= 10:
                return f"{value:.1f}"
            return f"{value:.2f}"

        painter.setFont(QFont("Segoe UI", 6, QFont.Bold))
        for step in range(4):
            ratio = step / 3
            value = maximum - ratio * span
            y = plot.top() + ratio * plot.height()
            painter.setPen(QPen(grid, 1))
            painter.drawLine(plot.left(), int(y), plot.right(), int(y))
            painter.drawLine(plot.left() - 4, int(y), plot.left(), int(y))
            painter.setPen(muted)
            painter.drawText(2, int(y) - 7, plot.left() - 8, 14, Qt.AlignRight | Qt.AlignVCenter, format_tick(value))

        def to_point(index: int, value: float, count: int) -> QPointF:
            x = plot.left() + (index / max(count - 1, 1)) * plot.width()
            ratio = (value - minimum) / span
            y = plot.bottom() - clamp(ratio, 0.0, 1.0) * plot.height()
            return QPointF(float(x), float(y))

        for _label, key, color in self.SERIES:
            values = list(self._histories[key])
            if len(values) < 2:
                continue
            path = QPainterPath()
            path.moveTo(to_point(0, values[0], len(values)))
            for index, value in enumerate(values[1:], start=1):
                path.lineTo(to_point(index, value, len(values)))
            painter.setPen(QPen(color, 1.8))
            painter.drawPath(path)

        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
        legend_x = plot.left()
        legend_y = self.rect().bottom() - 15
        for label, _key, color in self.SERIES:
            painter.setPen(QPen(color, 2))
            painter.drawLine(legend_x, legend_y + 6, legend_x + 10, legend_y + 6)
            painter.setPen(text)
            painter.drawText(legend_x + 13, legend_y, 42, 14, Qt.AlignLeft | Qt.AlignVCenter, label)
            legend_x += 50


class FloatingScreenWidget(QFrame):
    mode_requested = Signal(str, str)
    swap_requested = Signal(str)

    MODES = ("map", "live", "thermal", "data")

    def __init__(self, panel_key: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.panel_key = panel_key
        self._dock_parent = parent
        self.is_detached = False
        self._docked_geometry: QRectF | None = None
        self.mode = "map" if panel_key == "left" else "data"
        self._theme = "dark"
        self._language = "en"
        self._drag_start: QPointF | None = None
        self._resize_start: QPointF | None = None
        self._resize_geometry = QRectF()
        self._last_live_frame: QImage | None = None
        self._last_thermal_frame: QImage | None = None
        self.setObjectName("floatingScreen")
        self.setMinimumSize(260, 170)
        self.resize(330, 220)
        self.setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(5)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("floatingTitle")
        header.addWidget(self.title_label, 1)

        self.detach_button = QPushButton("⧉")
        self.detach_button.setToolTip("Détacher vers écran secondaire (Multi-moniteur) / Ré-ancrer")
        self.detach_button.setMaximumHeight(24)
        self.detach_button.setFixedWidth(28)
        self.detach_button.clicked.connect(self.toggle_dock)
        header.addWidget(self.detach_button)

        self.mode_buttons: dict[str, QPushButton] = {}
        for mode, text in (("map", "Map"), ("live", "Live"), ("thermal", "Therm"), ("data", "DATA")):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setMaximumHeight(24)
            button.clicked.connect(lambda _checked=False, selected=mode: self.mode_requested.emit(self.panel_key, selected))
            self.mode_buttons[mode] = button
            header.addWidget(button)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.map_widget = OfflineMapWidget()
        self.map_widget.controls_visible = False
        self.stack.addWidget(self.map_widget)

        self.live_label = QLabel(self._text("no_signal"))
        self.live_label.setAlignment(Qt.AlignCenter)
        self.live_label.setObjectName("floatingVideo")
        self.stack.addWidget(self.live_label)

        self.thermal_label = QLabel(self._text("no_signal"))
        self.thermal_label.setAlignment(Qt.AlignCenter)
        self.thermal_label.setObjectName("floatingVideo")
        self.stack.addWidget(self.thermal_label)

        self.data_chart = FloatingScienceChartWidget()
        self.stack.addWidget(self.data_chart)
        self.set_mode(self.mode)

    def set_theme(self, theme: str) -> None:
        self._theme = theme if theme in {"dark", "light"} else "dark"
        self.map_widget.set_theme(self._theme)
        self.data_chart.set_theme(self._theme)

    def _text(self, key: str) -> str:
        return UI_TEXTS.get(self._language, UI_TEXTS["en"]).get(key, UI_TEXTS["en"].get(key, key))

    def _screen_title(self) -> str:
        key = "left_screen" if self.panel_key == "left" else "right_screen"
        return self._text(key).upper()

    def set_language(self, language: str) -> None:
        self._language = language if language in UI_TEXTS else "en"
        for mode, button in self.mode_buttons.items():
            button.setText(self._text("therm" if mode == "thermal" else mode))
        for label in (self.live_label, self.thermal_label):
            if not label.pixmap() or label.pixmap().isNull():
                label.setText(self._text("no_signal"))
        self.title_label.setText(self._screen_title())

    def set_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            return
        self.mode = mode
        self.stack.setCurrentIndex(self.MODES.index(mode))
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode)
        self.title_label.setText(self._screen_title())

    def update_sensor_data(self, data: SensorData) -> None:
        self.map_widget.update_from_data(data)
        self.data_chart.append_data(data)

    def update_video_frame(self, mode: str, frame: QImage | None) -> None:
        if mode == "live":
            self._last_live_frame = frame
            label = self.live_label
        elif mode == "thermal":
            self._last_thermal_frame = frame
            label = self.thermal_label
        else:
            return
        if frame is None:
            label.setPixmap(QPixmap())
            label.setText(self._text("no_signal"))
            return
        label.setText("")
        pixmap = QPixmap.fromImage(frame)
        label.setPixmap(pixmap.scaled(label.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.update_video_frame("live", self._last_live_frame)
        self.update_video_frame("thermal", self._last_thermal_frame)

    def toggle_dock(self) -> None:
        if not self.is_detached:
            self._docked_geometry = QRectF(self.geometry())
            self.setParent(None)
            self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
            self.setWindowTitle(f"Spectrum Air Guard - {self.title_label.text()}")
            self.detach_button.setText("⚓")
            self.detach_button.setToolTip("Ré-ancrer dans l'application principale")
            self.is_detached = True
            self.show()
            self.raise_()
        else:
            self.setParent(self._dock_parent)
            self.setWindowFlags(Qt.SubWindow)
            self.detach_button.setText("⧉")
            self.detach_button.setToolTip("Détacher vers écran secondaire (Multi-moniteur)")
            self.is_detached = False
            if self._docked_geometry is not None:
                self.setGeometry(
                    int(self._docked_geometry.x()),
                    int(self._docked_geometry.y()),
                    int(self._docked_geometry.width()),
                    int(self._docked_geometry.height()),
                )
            self.show()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.is_detached:
            self.toggle_dock()
            self.hide()
            event.ignore()
        else:
            super().closeEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.is_detached:
            super().mousePressEvent(event)
            return
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
        if self.is_detached:
            super().mouseMoveEvent(event)
            return
        if self._resize_start is not None:
            delta = event.globalPosition() - self._resize_start
            self.resize(max(self.minimumWidth(), int(self._resize_geometry.width() + delta.x())), max(self.minimumHeight(), int(self._resize_geometry.height() + delta.y())))
            event.accept()
            return
        if self._drag_start is not None:
            new_pos = event.globalPosition() - self._drag_start
            parent = self.parentWidget()
            if parent is not None:
                self.move(max(0, min(int(new_pos.x()), parent.width() - self.width())), max(0, min(int(new_pos.y()), parent.height() - self.height())))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_start = None
        self._resize_start = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if not self.is_detached and event.button() == Qt.LeftButton:
            self.swap_requested.emit(self.panel_key)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
