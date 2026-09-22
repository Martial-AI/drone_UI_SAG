"""Card and button container widgets with glassmorphism and technical styling."""

from __future__ import annotations

import os
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from config import splash_logo_path
from core.utils import clamp


class DashboardCard(QFrame):
    """Futuristic HUD card with technical corner ticks, top glow, and header LED."""

    def __init__(self, title: str, subtitle: str | None = None, *, compact: bool = False) -> None:
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.title = title
        self.subtitle = subtitle
        self.compact = compact
        self.theme = "dark"

        self.layout = QVBoxLayout(self)
        if compact:
            self.layout.setContentsMargins(5, 10, 5, 5)
            self.layout.setSpacing(3)
            self.setMaximumHeight(52)
        else:
            self.layout.setContentsMargins(9, 20, 9, 10)
            self.layout.setSpacing(7)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("cardSubtitle")
            subtitle_label.setWordWrap(True)
            self.layout.addWidget(subtitle_label)

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in {"dark", "light"} else "dark"
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        radius = 13 if not self.compact else 10
        top_offset = 7 if self.compact else 9
        outer = self.rect().adjusted(1, top_offset, -1, -1)

        if self.theme == "light":
            bg_top = QColor(248, 252, 255, 242)
            bg_bottom = QColor(230, 241, 252, 230)
            border_col = QColor(180, 210, 235, 180)
            shine_col = QColor(255, 255, 255, 120)
            glow_col = QColor(100, 170, 220, 18)
            title_bg = QColor(220, 235, 248, 220)
            title_border = QColor(160, 200, 235, 200)
            title_fg = QColor("#1b3045")
            led_col = QColor("#2196a8")
            corner_col = QColor(160, 200, 235, 140)
        else:
            bg_top = QColor(14, 24, 42, 220)
            bg_bottom = QColor(7, 13, 26, 230)
            border_col = QColor(38, 88, 138, 160)
            shine_col = QColor(80, 160, 220, 22)
            glow_col = QColor(0, 180, 255, 12)
            title_bg = QColor(10, 20, 38, 200)
            title_border = QColor(30, 80, 130, 200)
            title_fg = QColor("#7ec8f0")
            led_col = QColor("#00e5ff")
            corner_col = QColor(30, 90, 150, 120)

        # Ambient glow
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow_col)
        painter.drawRoundedRect(outer.adjusted(-1, 1, 1, 3), radius + 1, radius + 1)

        # Gradient body
        grad = QLinearGradient(0, outer.top(), 0, outer.bottom())
        grad.setColorAt(0.0, bg_top)
        grad.setColorAt(1.0, bg_bottom)
        painter.setBrush(grad)
        painter.drawRoundedRect(outer, radius, radius)

        # Top specular shine
        shine_rect = outer.adjusted(radius, 0, -radius, -outer.height() + 3)
        painter.setBrush(shine_col)
        painter.drawRoundedRect(shine_rect, 2, 2)

        # Border
        painter.setPen(QPen(border_col, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(outer, radius, radius)

        # Corner ticks
        tick_len = 7
        tick_pen = QPen(corner_col, 1.5)
        tick_pen.setCapStyle(Qt.FlatCap)
        painter.setPen(tick_pen)
        x0, y0 = outer.left() + 1, outer.top() + 1
        painter.drawLine(x0, y0 + tick_len, x0, y0)
        painter.drawLine(x0, y0, x0 + tick_len, y0)
        x1, y1 = outer.right() - 1, outer.bottom() - 1
        painter.drawLine(x1, y1 - tick_len, x1, y1)
        painter.drawLine(x1, y1, x1 - tick_len, y1)

        # Header badge with LED
        title_text = self.title.strip()
        if title_text:
            title_font = QFont("Segoe UI", 6 if self.compact else 7, QFont.DemiBold)
            painter.setFont(title_font)
            metrics = painter.fontMetrics()
            text_w = metrics.horizontalAdvance(title_text)
            text_h = metrics.height()
            led_d = 4
            pad_x = 5
            badge_w = led_d + pad_x + text_w + pad_x
            badge_x = 10.0
            badge_y = -text_h * 0.5 + top_offset - 2
            badge_rect = QRectF(badge_x, badge_y, badge_w, text_h + 2)

            painter.setPen(QPen(title_border, 0.8))
            painter.setBrush(title_bg)
            painter.drawRoundedRect(badge_rect, 4, 4)

            led_cx = badge_x + pad_x + led_d * 0.5
            led_cy = badge_y + (text_h + 2) * 0.5
            led_glow = QColor(led_col)
            led_glow.setAlpha(50)
            painter.setPen(Qt.NoPen)
            painter.setBrush(led_glow)
            painter.drawEllipse(QPointF(led_cx, led_cy), led_d, led_d)
            painter.setBrush(led_col)
            painter.drawEllipse(QPointF(led_cx, led_cy), led_d * 0.5, led_d * 0.5)

            text_x = badge_x + pad_x + led_d + pad_x
            text_rect = QRectF(text_x, badge_y, text_w + 2, text_h + 2)
            painter.setPen(title_fg)
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, title_text.upper())


class StatusBadge(QLabel):
    COLORS = {
        "good": ("#1f8f61", "#d4ffe9"),
        "neutral": ("#415a77", "#edf6ff"),
        "bad": ("#8f2d3d", "#ffe8ec"),
        "warn": ("#8a6c1d", "#fff4d6"),
    }
    LIGHT_COLORS = {
        "good": ("#dff7ea", "#176748", "#b7e2cb"),
        "neutral": ("#eaf2fb", "#35506d", "#c7d7ea"),
        "bad": ("#fde8eb", "#8d2f3d", "#efc1c8"),
        "warn": ("#fff2d9", "#8a6619", "#efd49b"),
    }

    def __init__(self, label: str, text: str = "Idle", tone: str = "neutral") -> None:
        super().__init__()
        self.prefix = label
        self.theme = "dark"
        self.current_text = text
        self.current_tone = tone
        self.set_status(text, tone)

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in {"dark", "light"} else "dark"
        self._apply_style()

    def set_status(self, text: str, tone: str) -> None:
        self.current_text = text
        self.current_tone = tone
        self._apply_style()

    def _apply_style(self) -> None:
        palette = self.LIGHT_COLORS if self.theme == "light" else self.COLORS
        colors = palette.get(self.current_tone, palette["neutral"])
        if self.theme == "light":
            bg_color, fg_color, border_color = colors
        else:
            bg_color, fg_color = colors
            border_color = bg_color
        self.setText(f"{self.prefix}: {self.current_text}")
        self.setStyleSheet(
            f"""
            QLabel {{
                background: {bg_color};
                color: {fg_color};
                border: 1px solid {border_color};
                border-radius: 7px;
                padding: 2px 6px;
                font-weight: 600;
                font-size: 9px;
            }}
            """
        )


class LongPressButton(QPushButton):
    short_clicked = Signal()
    long_clicked = Signal()

    def __init__(self, text: str, hold_ms: int = 2000) -> None:
        super().__init__(text)
        self._long_press_triggered = False
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(hold_ms)
        self._hold_timer.timeout.connect(self._emit_long_click)

    def _emit_long_click(self) -> None:
        self._long_press_triggered = True
        self.long_clicked.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._long_press_triggered = False
            self._hold_timer.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        was_active = self._hold_timer.isActive()
        self._hold_timer.stop()
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and was_active and not self._long_press_triggered:
            self.short_clicked.emit()


class ThemeSwitch(QPushButton):
    def __init__(self) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(48, 24)
        self.theme = "dark"

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme in {"dark", "light"} else "dark"
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        if self.isChecked():
            track = QColor("#8fdcff") if self.theme == "light" else QColor("#3fb6ff")
            thumb = QColor("#ffffff")
            border = QColor("#63b8e8") if self.theme == "light" else QColor("#74d0ff")
            glow = QColor("#c7ecff") if self.theme == "light" else QColor("#1d6f9a")
        else:
            track = QColor("#d7e2ee") if self.theme == "light" else QColor("#1a2740")
            thumb = QColor("#ffffff") if self.theme == "light" else QColor("#d6deef")
            border = QColor("#bdd0e1") if self.theme == "light" else QColor("#324b73")
            glow = QColor("#eef4fb") if self.theme == "light" else QColor("#101b31")

        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawRoundedRect(rect.adjusted(0, 0, 0, 0), rect.height() / 2, rect.height() / 2)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(track)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        thumb_diameter = rect.height() - 6
        thumb_x = rect.right() - thumb_diameter - 3 if self.isChecked() else rect.left() + 3
        thumb_rect = QRectF(thumb_x, rect.top() + 3, thumb_diameter, thumb_diameter)
        painter.setPen(Qt.NoPen)
        painter.setBrush(thumb)
        painter.drawEllipse(thumb_rect)
        painter.setPen(QPen(QColor("#6d7f94") if self.theme == "light" else QColor("#365074"), 1))
        painter.drawEllipse(thumb_rect)

        icon_center = thumb_rect.center()
        if self.isChecked():
            painter.setPen(QPen(QColor("#59acd8"), 1.2))
            painter.setBrush(QColor("#ffeaa0"))
            painter.drawEllipse(icon_center, 4.2, 4.2)
            for angle in range(0, 360, 45):
                radians = np.deg2rad(angle)
                outer_x = icon_center.x() + np.cos(radians) * 6.8
                outer_y = icon_center.y() + np.sin(radians) * 6.8
                inner_x = icon_center.x() + np.cos(radians) * 5.3
                inner_y = icon_center.y() + np.sin(radians) * 5.3
                painter.drawLine(QPointF(inner_x, inner_y), QPointF(outer_x, outer_y))
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#9fb7d8") if self.theme == "light" else QColor("#c4d4ef"))
            painter.drawEllipse(icon_center, 4.8, 4.8)
            painter.setBrush(track)
            painter.drawEllipse(QPointF(icon_center.x() + 2.2, icon_center.y() - 1.2), 4.6, 4.6)


class StartupSplash(QDialog):
    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setObjectName("startupSplash")
        self.setModal(False)
        self.setFixedSize(420, 320)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        shell = QFrame()
        shell.setObjectName("startupSplashShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(26, 24, 26, 24)
        shell_layout.setSpacing(12)

        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setFixedHeight(136)
        logo_file = splash_logo_path()
        if os.path.exists(logo_file):
            pixmap = QPixmap(logo_file)
            self.logo_label.setPixmap(
                pixmap.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

        self.title_label = QLabel("SPECTRUM AIR GUARD")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setObjectName("startupTitle")

        self.status_label = QLabel("Initialisation...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setObjectName("startupStatus")

        progress_block = QVBoxLayout()
        progress_block.setContentsMargins(0, 0, 0, 0)
        progress_block.setSpacing(6)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setObjectName("startupProgress")

        self.percent_label = QLabel("0%")
        self.percent_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.percent_label.setObjectName("startupPercent")

        progress_block.addWidget(self.progress_bar)
        progress_block.addWidget(self.percent_label, 0, Qt.AlignHCenter)

        shell_layout.addStretch(1)
        shell_layout.addWidget(self.logo_label)
        shell_layout.addWidget(self.title_label)
        shell_layout.addWidget(self.status_label)
        shell_layout.addSpacing(4)
        shell_layout.addLayout(progress_block)
        shell_layout.addStretch(1)

        outer_layout.addWidget(shell)

        self.setStyleSheet(
            """
            QDialog#startupSplash {
                background: transparent;
            }
            QFrame#startupSplashShell {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #0c1424,
                    stop: 0.55 #111a2e,
                    stop: 1 #08111f
                );
                border: 1px solid #2f587a;
                border-radius: 0px;
            }
            QLabel#startupTitle {
                color: #f4fbff;
                font-size: 24px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#startupStatus {
                color: #8fb4d1;
                font-size: 12px;
                padding-top: 2px;
            }
            QLabel#startupPercent {
                color: #eaf8ff;
                font-size: 14px;
                font-weight: 700;
            }
            QProgressBar#startupProgress {
                background: rgba(5, 14, 24, 0.9);
                border: 1px solid #2c4f70;
                border-radius: 8px;
                min-height: 16px;
            }
            QProgressBar#startupProgress::chunk {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #43c4ff,
                    stop: 1 #7ce6ff
                );
                border-radius: 7px;
            }
            """
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        self.setWindowOpacity(1.0)
        geometry = screen.availableGeometry()
        self.move(
            geometry.center().x() - self.width() // 2,
            geometry.center().y() - self.height() // 2,
        )

    def set_progress(self, value: int, status: str | None = None) -> None:
        value = max(0, min(100, int(value)))
        self.progress_bar.setValue(value)
        self.percent_label.setText(f"{value}%")
        if status:
            self.status_label.setText(status)


class MetricCard(DashboardCard):
    def __init__(self, title: str, unit: str, accent: str, max_value: float) -> None:
        super().__init__(title)
        self.unit = unit
        self.max_value = max_value

        self.value_label = QLabel(f"0.0 {unit}")
        self.value_label.setObjectName("metricValue")
        self.layout.addWidget(self.value_label)

        self.status_label = QLabel("Waiting for telemetry")
        self.status_label.setObjectName("metricHint")
        self.layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            f"""
            QProgressBar {{
                background: #11182a;
                border-radius: 8px;
                min-height: 12px;
            }}
            QProgressBar::chunk {{
                background: {accent};
                border-radius: 8px;
            }}
            """
        )
        self.layout.addWidget(self.progress)

    def set_value(self, value: float) -> None:
        self.value_label.setText(f"{value:.1f} {self.unit}")
        ratio = clamp(value / max(self.max_value, 1.0), 0.0, 1.0)
        self.progress.setValue(int(ratio * 1000))
        self.status_label.setText(f"{ratio * 100:.0f}% of configured range")
