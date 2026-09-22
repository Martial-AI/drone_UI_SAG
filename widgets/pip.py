from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
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
from .map_widget import OfflineMapWidget


class PipWindowWidget(QFrame):
    """Floating Picture-in-Picture (PiP) window.

    Allows displaying a mini-map while the main screen displays live video,
    or a mini-video while the main screen displays the tactical map.
    Features drag-and-drop repositioning, content swap button 🔄, and close button.
    """

    swap_requested = Signal()
    close_requested = Signal()

    MODE_MAP = "map"
    MODE_VIDEO = "video"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = self.MODE_MAP
        self._drag_start: QPointF | None = None
        self._resize_start: QPointF | None = None
        self._resize_geometry = QRectF()
        self._current_frame: QImage | None = None

        self.setObjectName("pipWindow")
        self.setMinimumSize(220, 150)
        self.resize(300, 190)
        self.setMouseTracking(True)

        self.setStyleSheet("""
            QFrame#pipWindow {
                background-color: rgba(10, 17, 30, 0.92);
                border: 2px solid #00d4ff;
                border-radius: 8px;
            }
            QLabel#pipTitle {
                color: #00d4ff;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 0.8px;
            }
            QPushButton#pipBtn {
                background-color: rgba(15, 23, 42, 0.8);
                color: #c9d8ec;
                font-size: 11px;
                font-weight: 700;
                border: 1px solid #23354b;
                border-radius: 4px;
                padding: 1px 5px;
            }
            QPushButton#pipBtn:hover {
                background-color: #0077b6;
                color: #ffffff;
                border-color: #00d4ff;
            }
            QLabel#pipVideoLabel {
                background-color: #040810;
                color: #4a6380;
                font-size: 9px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 4, 5, 5)
        layout.setSpacing(3)

        # Header bar
        header = QHBoxLayout()
        header.setSpacing(4)
        header.setContentsMargins(2, 0, 2, 0)

        self.title_label = QLabel("PIP: MAP")
        self.title_label.setObjectName("pipTitle")
        header.addWidget(self.title_label, 1)

        self.swap_btn = QPushButton("🔄")
        self.swap_btn.setObjectName("pipBtn")
        self.swap_btn.setFixedSize(22, 20)
        self.swap_btn.setToolTip("Intervertir avec l'écran principal (Swap)")
        self.swap_btn.clicked.connect(self.swap_requested.emit)
        header.addWidget(self.swap_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("pipBtn")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setToolTip("Fermer Picture-in-Picture (P)")
        self.close_btn.clicked.connect(self.close_requested.emit)
        header.addWidget(self.close_btn)

        layout.addLayout(header)

        # Content stack (Index 0 = Map, Index 1 = Video)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        # Mini Map
        self.map_widget = OfflineMapWidget()
        self.map_widget.controls_visible = False
        self.stack.addWidget(self.map_widget)

        # Mini Video
        self.video_label = QLabel("NO SIGNAL")
        self.video_label.setObjectName("pipVideoLabel")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(self.video_label)

        self.set_content_mode(self.MODE_MAP)

    def set_content_mode(self, mode: str) -> None:
        """Switch between mini-map or mini-video in the PiP container."""
        if mode == self.MODE_VIDEO:
            self._mode = self.MODE_VIDEO
            self.title_label.setText("PIP: FPV LIVE")
            self.stack.setCurrentIndex(1)
        else:
            self._mode = self.MODE_MAP
            self.title_label.setText("PIP: MAP")
            self.stack.setCurrentIndex(0)

    @property
    def content_mode(self) -> str:
        return self._mode

    def update_video_frame(self, frame: QImage | None) -> None:
        self._current_frame = frame
        if frame is None:
            self.video_label.setPixmap(QPixmap())
            self.video_label.setText("NO SIGNAL")
            return
        pix = QPixmap.fromImage(frame)
        self.video_label.setText("")
        self.video_label.setPixmap(pix.scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def update_telemetry(self, data: SensorData) -> None:
        if self._mode == self.MODE_MAP:
            self.map_widget.update_from_data(data)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._mode == self.MODE_VIDEO and self._current_frame is not None:
            self.update_video_frame(self._current_frame)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        local_pos = event.position()
        if local_pos.x() >= self.width() - 16 and local_pos.y() >= self.height() - 16:
            self._resize_start = event.globalPosition()
            self._resize_geometry = QRectF(self.geometry())
        else:
            self._drag_start = event.globalPosition() - QPointF(self.pos())
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._resize_start is not None:
            delta = event.globalPosition() - self._resize_start
            new_w = max(self.minimumWidth(), int(self._resize_geometry.width() + delta.x()))
            new_h = max(self.minimumHeight(), int(self._resize_geometry.height() + delta.y()))
            self.resize(new_w, new_h)
            event.accept()
            return
        if self._drag_start is not None:
            new_pos = event.globalPosition() - self._drag_start
            parent = self.parentWidget()
            if parent is not None:
                max_x = parent.width() - self.width()
                max_y = parent.height() - self.height()
                self.move(
                    max(0, min(int(new_pos.x()), max_x)),
                    max(0, min(int(new_pos.y()), max_y)),
                )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_start = None
        self._resize_start = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.swap_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
