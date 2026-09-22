from __future__ import annotations

import time
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.models import AlertEntry


class AlertBannerWidget(QFrame):
    """Panneau compact affichant les alertes de vol actives (max 4 visibles)."""

    MAX_VISIBLE = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("alertBannerPanel")
        self._alerts: list[AlertEntry] = []
        self._rows: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        header = QLabel("⚠ ALERTS")
        header.setObjectName("sectionLabel")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        self._list_layout = QVBoxLayout()
        self._list_layout.setSpacing(2)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._list_layout)

        for _ in range(self.MAX_VISIBLE):
            row = QLabel("")
            row.setWordWrap(True)
            row.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            row.setStyleSheet("font-size: 9px; font-weight: 700; border-radius: 4px; padding: 2px 5px;")
            row.hide()
            self._list_layout.addWidget(row)
            self._rows.append(row)

        self._no_alert_label = QLabel("Aucune alerte active")
        self._no_alert_label.setObjectName("metricHint")
        self._no_alert_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._no_alert_label)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setInterval(1000)
        self._dismiss_timer.timeout.connect(self._check_auto_dismiss)
        self._dismiss_timer.start()

    def push_alert(self, message: str, level: str = "info", auto_dismiss: int = 0) -> None:
        """Ajoute une alerte. Si elle existe déjà (même message), la rafraîchit."""
        for existing in self._alerts:
            if existing.message == message and not existing.dismissed:
                existing.timestamp = time.monotonic()
                self._refresh()
                return
        entry = AlertEntry(message, level, auto_dismiss)
        self._alerts.append(entry)
        self._refresh()

    def dismiss_alert(self, message: str) -> None:
        """Supprime une alerte par son message."""
        for a in self._alerts:
            if a.message == message:
                a.dismissed = True
        self._refresh()

    def clear_all(self) -> None:
        for a in self._alerts:
            a.dismissed = True
        self._refresh()

    def _check_auto_dismiss(self) -> None:
        now = time.monotonic()
        changed = False
        for a in self._alerts:
            if not a.dismissed and a.auto_dismiss > 0:
                if now - a.timestamp >= a.auto_dismiss:
                    a.dismissed = True
                    changed = True
        if changed:
            self._refresh()

    def _refresh(self) -> None:
        active = [a for a in self._alerts if not a.dismissed]
        active.sort(key=lambda x: x.timestamp, reverse=True)

        self._alerts = [a for a in self._alerts if not a.dismissed][-50:] + \
                       [a for a in self._alerts if a.dismissed]
        self._alerts = self._alerts[-100:]

        self._no_alert_label.setVisible(len(active) == 0)

        for i, row in enumerate(self._rows):
            if i < len(active):
                alert = active[i]
                row.setText(f"● {alert.message}")
                row.setStyleSheet(
                    f"font-size: 9px; font-weight: 700; border-radius: 4px; padding: 2px 5px;"
                    f"background: {alert.bg_color}; color: {alert.fg_color};"
                )
                row.show()
            else:
                row.hide()


class FlightLogWidget(QFrame):
    """Journal de bord de mission : liste horodatée des événements de vol."""

    event_clicked = Signal(float, float)  # lat, lon

    ICONS = {
        "arm":       "🔴",
        "disarm":    "🟢",
        "takeoff":   "🛫",
        "land":      "🛬",
        "rtl":       "🏠",
        "waypoint":  "📍",
        "alert":     "⚠",
        "mode":      "✈",
        "kill":      "💀",
        "info":      "ℹ",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("flightLogPanel")
        self._mission_start: float | None = None
        self._entries: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        header_row = QHBoxLayout()
        title = QLabel("📋 FLIGHT LOG")
        title.setObjectName("sectionLabel")
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedSize(42, 20)
        self._clear_btn.setStyleSheet(
            "font-size: 9px; background: #1e293b; color: #64748b; border: 1px solid #334155; border-radius: 4px;"
        )
        self._clear_btn.clicked.connect(self.clear)
        header_row.addWidget(title, 1)
        header_row.addWidget(self._clear_btn)
        layout.addLayout(header_row)

        self._list = QListWidget()
        self._list.setObjectName("flightLogList")
        self._list.setSpacing(1)
        self._list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                font-size: 10px;
            }
            QListWidget::item {
                background: rgba(15, 23, 42, 0.6);
                color: #cbd5e1;
                border-radius: 4px;
                padding: 3px 5px;
                margin: 1px 0;
            }
            QListWidget::item:selected {
                background: rgba(30, 58, 138, 0.8);
                color: #bfdbfe;
            }
            QListWidget::item:hover {
                background: rgba(30, 41, 59, 0.8);
            }
        """)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list, 1)

        self._count_label = QLabel("0 événements")
        self._count_label.setObjectName("metricHint")
        self._count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._count_label)

    def log_event(self, event_type: str, detail: str = "",
                  lat: float | None = None, lon: float | None = None) -> None:
        """Enregistre un événement dans le journal."""
        now = time.monotonic()
        if self._mission_start is None:
            self._mission_start = now

        elapsed = now - self._mission_start
        m, s = divmod(int(elapsed), 60)
        timestamp = f"{m:02d}:{s:02d}"

        icon = self.ICONS.get(event_type, "ℹ")
        text = f"{timestamp}  {icon}  {detail}" if detail else f"{timestamp}  {icon}  {event_type.upper()}"

        entry = {"text": text, "lat": lat, "lon": lon, "type": event_type}
        self._entries.append(entry)

        item = QListWidgetItem(text)
        color_map = {
            "arm": "#fcd34d",
            "disarm": "#6ee7b7",
            "takeoff": "#67e8f9",
            "land": "#a5f3fc",
            "rtl": "#c4b5fd",
            "waypoint": "#86efac",
            "alert": "#fca5a5",
            "kill": "#f87171",
            "mode": "#93c5fd",
        }
        fg = color_map.get(event_type, "#cbd5e1")
        item.setForeground(QColor(fg))
        item.setData(Qt.UserRole, entry)

        self._list.addItem(item)
        self._list.scrollToBottom()
        self._count_label.setText(f"{len(self._entries)} événement(s)")

    def start_mission(self) -> None:
        """Démarre le chronomètre de mission."""
        self._mission_start = time.monotonic()

    def clear(self) -> None:
        self._entries.clear()
        self._list.clear()
        self._mission_start = None
        self._count_label.setText("0 événements")

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.UserRole)
        if entry and entry.get("lat") is not None and entry.get("lon") is not None:
            self.event_clicked.emit(float(entry["lat"]), float(entry["lon"]))
