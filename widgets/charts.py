from __future__ import annotations

from collections import deque
import os
import sqlite3
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
import matplotlib.dates as mdates
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from core.i18n import UI_TEXTS


class TelemetryChartWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.figure = Figure(figsize=(8, 5), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self._theme = "dark"
        self._language = "en"
        self.ax.set_facecolor("#0f1728")
        self.figure.patch.set_facecolor("#0f1728")
        self._pinch_total_scale = 1.0
        self._is_panning = False
        self._last_pan_point: tuple[float, float] | None = None
        self._default_xlim: tuple[float, float] | None = None
        self._default_ylim: tuple[float, float] | None = None
        self._data_xlim: tuple[float, float] | None = None
        self._data_ylim: tuple[float, float] | None = None

        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.grabGesture(Qt.PinchGesture)
        self.canvas.installEventFilter(self)
        self.canvas.mpl_connect("scroll_event", self._on_scroll_event)
        self.canvas.mpl_connect("button_press_event", self._on_button_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("button_release_event", self._on_button_release)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

    def set_theme(self, theme: str) -> None:
        self._theme = theme if theme in {"dark", "light"} else "dark"
        self._apply_existing_theme()

    def _text(self, key: str) -> str:
        return UI_TEXTS.get(self._language, UI_TEXTS["en"]).get(key, UI_TEXTS["en"].get(key, key))

    def set_language(self, language: str) -> None:
        self._language = language if language in UI_TEXTS else "en"

    def _theme_colors(self) -> dict[str, str]:
        if self._theme == "light":
            return {
                "bg": "#f7fbff",
                "grid": "#b5c9df",
                "text": "#24364d",
                "spine": "#b9c8d8",
            }
        return {
            "bg": "#0f1728",
            "grid": "#35507d",
            "text": "#8ea8d7",
            "spine": "#22324f",
        }

    def _apply_existing_theme(self) -> None:
        colors = self._theme_colors()
        self.ax.set_facecolor(colors["bg"])
        self.figure.patch.set_facecolor(colors["bg"])
        self.ax.tick_params(colors=colors["text"], labelsize=8)
        for spine in self.ax.spines.values():
            spine.set_color(colors["spine"])
        self.ax.grid(alpha=0.18, color=colors["grid"])
        title = self.ax.title
        title.set_color("#dbe7ff" if self._theme == "dark" else "#1f2f45")
        legend = self.ax.get_legend()
        if legend is not None:
            legend.get_frame().set_facecolor("#101728" if self._theme == "dark" else "#ffffff")
            legend.get_frame().set_edgecolor(colors["spine"])
            for text in legend.get_texts():
                text.set_color("#dbe7ff" if self._theme == "dark" else "#24364d")
        self.canvas.draw_idle()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.canvas and event.type() == QEvent.Gesture:
            pinch = event.gesture(Qt.PinchGesture)
            if pinch is not None:
                state = pinch.state()
                if state == Qt.GestureStarted:
                    self._pinch_total_scale = 1.0

                current_scale = max(pinch.totalScaleFactor(), 0.01)
                zoom_factor = self._pinch_total_scale / current_scale
                self._pinch_total_scale = current_scale

                center = pinch.centerPoint()
                if abs(zoom_factor - 1.0) > 0.001:
                    self._zoom_from_widget_point(center, zoom_factor)
                return True

        return super().eventFilter(watched, event)

    def _zoom_from_widget_point(self, point: QPointF, zoom_factor: float) -> None:
        display_x = point.x()
        display_y = self.canvas.height() - point.y()
        if not self.ax.bbox.contains(display_x, display_y):
            return

        x_data, y_data = self.ax.transData.inverted().transform((display_x, display_y))
        self._zoom_axes(float(x_data), float(y_data), zoom_factor)

    def _zoom_axes(self, x_center: float, y_center: float, zoom_factor: float) -> None:
        x_left, x_right = self.ax.get_xlim()
        y_bottom, y_top = self.ax.get_ylim()
        if x_left == x_right or y_bottom == y_top:
            return

        new_xlim = (
            x_center - (x_center - x_left) * zoom_factor,
            x_center + (x_right - x_center) * zoom_factor,
        )
        new_ylim = (
            y_center - (y_center - y_bottom) * zoom_factor,
            y_center + (y_top - y_center) * zoom_factor,
        )

        new_xlim = self._constrain_interval(new_xlim, self._data_xlim)
        new_ylim = self._constrain_interval(new_ylim, self._data_ylim)
        self.ax.set_xlim(*new_xlim)
        self.ax.set_ylim(*new_ylim)
        self.canvas.draw_idle()

    @staticmethod
    def _build_axis_bounds(values: list[float], clamp_to_zero: bool = True) -> tuple[float, float]:
        cleaned = [float(value) for value in values if pd.notna(value)]
        if not cleaned:
            return (0.0, 1.0)

        minimum = min(cleaned)
        maximum = max(cleaned)
        if clamp_to_zero:
            minimum = max(0.0, minimum)

        if minimum == maximum:
            padding = max(abs(maximum) * 0.08, 1.0)
        else:
            padding = (maximum - minimum) * 0.06

        lower = minimum - padding
        upper = maximum + padding
        if clamp_to_zero:
            lower = max(0.0, lower)
        if lower == upper:
            upper = lower + 1.0
        return (lower, upper)

    @staticmethod
    def _constrain_interval(
        interval: tuple[float, float],
        bounds: tuple[float, float] | None,
    ) -> tuple[float, float]:
        left, right = sorted((float(interval[0]), float(interval[1])))
        if bounds is None:
            if left == right:
                return (left, left + 1.0)
            return (left, right)

        bound_left, bound_right = bounds
        full_span = bound_right - bound_left
        span = right - left
        if span <= 0:
            span = max(full_span * 0.05, 1.0)
            center = (left + right) / 2
            left = center - span / 2
            right = center + span / 2

        if span >= full_span:
            return (bound_left, bound_right)

        if left < bound_left:
            right += bound_left - left
            left = bound_left
        if right > bound_right:
            left -= right - bound_right
            right = bound_right

        left = max(bound_left, left)
        right = min(bound_right, right)
        return (left, right)

    def _store_default_view(self) -> None:
        self._default_xlim = tuple(float(value) for value in self.ax.get_xlim())
        self._default_ylim = tuple(float(value) for value in self.ax.get_ylim())

    def reset_view(self) -> None:
        if self._default_xlim is None or self._default_ylim is None:
            return

        self.ax.set_xlim(*self._default_xlim)
        self.ax.set_ylim(*self._default_ylim)
        self.canvas.draw_idle()

    def _on_scroll_event(self, event) -> None:
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return

        zoom_factor = 0.85 if event.button == "up" else 1.18
        self._zoom_axes(float(event.xdata), float(event.ydata), zoom_factor)

    def _on_button_press(self, event) -> None:
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return
        if event.button != 1:
            return
        if getattr(event, "dblclick", False):
            self.reset_view()
            return

        self._is_panning = True
        self._last_pan_point = (float(event.xdata), float(event.ydata))

    def _on_mouse_move(self, event) -> None:
        if not self._is_panning or self._last_pan_point is None:
            return
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return

        last_x, last_y = self._last_pan_point
        delta_x = float(event.xdata) - last_x
        delta_y = float(event.ydata) - last_y
        x_left, x_right = self.ax.get_xlim()
        y_bottom, y_top = self.ax.get_ylim()
        new_xlim = self._constrain_interval((x_left - delta_x, x_right - delta_x), self._data_xlim)
        new_ylim = self._constrain_interval((y_bottom - delta_y, y_top - delta_y), self._data_ylim)
        self.ax.set_xlim(*new_xlim)
        self.ax.set_ylim(*new_ylim)
        self._last_pan_point = (float(event.xdata), float(event.ydata))
        self.canvas.draw_idle()

    def _on_button_release(self, event) -> None:
        if event.button == 1:
            self._is_panning = False
            self._last_pan_point = None

    def _style_axes(self, title: str) -> None:
        colors = self._theme_colors()
        self.ax.clear()
        self.ax.set_facecolor(colors["bg"])
        self.figure.patch.set_facecolor(colors["bg"])
        self.ax.tick_params(colors=colors["text"], labelsize=8)
        for spine in self.ax.spines.values():
            spine.set_color(colors["spine"])
        self.ax.grid(alpha=0.18, color=colors["grid"])
        self.ax.set_title(title, color="#dbe7ff" if self._theme == "dark" else "#1f2f45", fontsize=10)

    def show_live_data(self, histories: dict[str, deque[float]]) -> None:
        self._style_axes(self._text("live_data"))
        colors = self._theme_colors()
        x_values = list(histories["x"])
        if len(x_values) < 2:
            self._data_xlim = (0.0, 1.0)
            self._data_ylim = (0.0, 1.0)
            self.ax.set_xlim(*self._data_xlim)
            self.ax.set_ylim(*self._data_ylim)
            self.ax.text(0.5, 0.5, self._text("waiting_for_data"), color=colors["text"], ha="center", va="center", transform=self.ax.transAxes)
            self._store_default_view()
            self.canvas.draw_idle()
            return

        series = [
            ("Rad", "radiation", "#ff7b72"),
            ("Temp", "temp", "#ffb86c"),
            ("Hum", "humidity", "#79e3d8"),
            ("CO2", "co2", "#5ec8f8"),
            ("LPG", "lpg", "#f7c86e"),
            ("CO", "co", "#6de28c"),
        ]
        for label, key, color in series:
            self.ax.plot(x_values, list(histories[key]), label=label, color=color, linewidth=1.5)

        y_values: list[float] = []
        for _label, key, _color in series:
            y_values.extend(float(value) for value in histories[key] if pd.notna(value))
        self._data_xlim = self._build_axis_bounds(x_values)
        self._data_ylim = self._build_axis_bounds(y_values)
        self.ax.set_xlim(*self._data_xlim)
        self.ax.set_ylim(*self._data_ylim)
        legend = self.ax.legend(loc="upper right", fontsize=7)
        if legend is not None:
            legend.get_frame().set_facecolor("#101728" if self._theme == "dark" else "#ffffff")
            legend.get_frame().set_edgecolor(colors["spine"])
            for text in legend.get_texts():
                text.set_color("#dbe7ff" if self._theme == "dark" else "#24364d")
        self._store_default_view()
        self.canvas.draw_idle()

    def show_logged_csv(self, csv_path: str) -> None:
        self._style_axes(f"Saved DATA - {os.path.basename(csv_path)}")
        colors = self._theme_colors()
        df = pd.read_csv(csv_path)
        if "Time" not in df.columns:
            raise ValueError("Selected log does not contain a Time column.")

        x_values = list(range(len(df)))
        series = [
            ("Rad", "Count", "#ff7b72"),
            ("Temp", "Temp", "#ffb86c"),
            ("Hum", "Hum", "#79e3d8"),
            ("CO2", "CO2", "#5ec8f8"),
            ("LPG", "LPG", "#f7c86e"),
            ("CO", "CO", "#6de28c"),
        ]
        for label, column, color in series:
            if column in df.columns:
                self.ax.plot(x_values, df[column], label=label, color=color, linewidth=1.5)

        y_values: list[float] = []
        for _label, column, _color in series:
            if column in df.columns:
                y_values.extend(float(value) for value in df[column].tolist() if pd.notna(value))
        self._data_xlim = self._build_axis_bounds(x_values)
        self._data_ylim = self._build_axis_bounds(y_values)
        self.ax.set_xlim(*self._data_xlim)
        self.ax.set_ylim(*self._data_ylim)
        legend = self.ax.legend(loc="upper right", fontsize=7)
        if legend is not None:
            legend.get_frame().set_facecolor("#101728" if self._theme == "dark" else "#ffffff")
            legend.get_frame().set_edgecolor(colors["spine"])
            for text in legend.get_texts():
                text.set_color("#dbe7ff" if self._theme == "dark" else "#24364d")
        self._store_default_view()
        self.canvas.draw_idle()

    def show_logged_sqlite(self, database_path: str) -> None:
        self._style_axes(f"Saved DATA - {os.path.basename(database_path)}")
        colors = self._theme_colors()
        with sqlite3.connect(database_path) as connection:
            session_df = pd.read_sql_query(
                "SELECT id FROM sessions ORDER BY started_at DESC LIMIT 1",
                connection,
            )
            if session_df.empty:
                raise ValueError("Selected database does not contain any session.")
            session_id = int(session_df.iloc[0]["id"])
            df = pd.read_sql_query(
                """
                SELECT time_label AS Time, co2 AS CO2, lpg AS LPG, co AS CO,
                       humidity AS Hum, radiation AS Count, temperature AS Temp
                FROM telemetry_samples
                WHERE session_id = ?
                ORDER BY recorded_at ASC
                """,
                connection,
                params=(session_id,),
            )
        if df.empty:
            raise ValueError("Selected database does not contain telemetry samples.")

        x_values = list(range(len(df)))
        series = [
            ("Rad", "Count", "#ff7b72"),
            ("Temp", "Temp", "#ffb86c"),
            ("Hum", "Hum", "#79e3d8"),
            ("CO2", "CO2", "#5ec8f8"),
            ("LPG", "LPG", "#f7c86e"),
            ("CO", "CO", "#6de28c"),
        ]
        for label, column, color in series:
            if column in df.columns:
                self.ax.plot(x_values, df[column], label=label, color=color, linewidth=1.5)

        y_values: list[float] = []
        for _label, column, _color in series:
            if column in df.columns:
                y_values.extend(float(value) for value in df[column].tolist() if pd.notna(value))
        self._data_xlim = self._build_axis_bounds(x_values)
        self._data_ylim = self._build_axis_bounds(y_values)
        self.ax.set_xlim(*self._data_xlim)
        self.ax.set_ylim(*self._data_ylim)
        legend = self.ax.legend(loc="upper right", fontsize=7)
        if legend is not None:
            legend.get_frame().set_facecolor("#101728" if self._theme == "dark" else "#ffffff")
            legend.get_frame().set_edgecolor(colors["spine"])
            for text in legend.get_texts():
                text.set_color("#dbe7ff" if self._theme == "dark" else "#24364d")
        self._store_default_view()
        self.canvas.draw_idle()


class FlightDataChartWidget(QWidget):
    """Graphiques temps réel des données de vol : altitude, vitesse sol, cap."""

    WINDOW_SECONDS = 90

    def __init__(self) -> None:
        super().__init__()
        self._theme = "dark"

        self.figure = Figure(figsize=(8, 4), dpi=100)
        self.figure.subplots_adjust(left=0.07, right=0.93, top=0.88, bottom=0.18)
        self.canvas = FigureCanvasQTAgg(self.figure)

        self.ax1 = self.figure.add_subplot(111)
        self.ax2 = self.ax1.twinx()

        self._apply_theme_style()

        (self.line_alt,) = self.ax1.plot([], [], color="#06b6d4", linewidth=2.0, label="Alt (m)")
        (self.line_spd,) = self.ax1.plot([], [], color="#fbbf24", linewidth=1.6, label="Spd (km/h)", linestyle="--")
        (self.line_hdg,) = self.ax2.plot([], [], color="#a78bfa", linewidth=1.2, label="Cap (°)", alpha=0.75)

        lines = [self.line_alt, self.line_spd, self.line_hdg]
        labels = [ln.get_label() for ln in lines]
        self.ax1.legend(lines, labels, loc="upper left", fontsize=7,
                        facecolor="#101728", edgecolor="#22324f",
                        labelcolor="#dbe7ff")

        self._event_vlines: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        self._times: deque[float] = deque(maxlen=self.WINDOW_SECONDS)
        self._alts: deque[float] = deque(maxlen=self.WINDOW_SECONDS)
        self._spds: deque[float] = deque(maxlen=self.WINDOW_SECONDS)
        self._hdgs: deque[float] = deque(maxlen=self.WINDOW_SECONDS)
        self._t0: float | None = None

    def set_theme(self, theme: str) -> None:
        self._theme = theme if theme in {"dark", "light"} else "dark"
        self._apply_theme_style()
        self.canvas.draw_idle()

    def _apply_theme_style(self) -> None:
        if self._theme == "dark":
            bg, grid, text, spine = "#0f1728", "#35507d", "#8ea8d7", "#22324f"
        else:
            bg, grid, text, spine = "#f7fbff", "#b5c9df", "#24364d", "#b9c8d8"

        self.figure.patch.set_facecolor(bg)
        for ax in (self.ax1, self.ax2):
            ax.set_facecolor(bg)
            ax.tick_params(colors=text, labelsize=7)
            for sp in ax.spines.values():
                sp.set_color(spine)
        self.ax1.grid(alpha=0.18, color=grid, linestyle=":")
        title_color = "#dbe7ff" if self._theme == "dark" else "#1f2f45"
        self.ax1.set_title("Flight Data — Live", color=title_color, fontsize=9, pad=6)
        self.ax1.set_ylabel("Alt / Spd", color=text, fontsize=7)
        self.ax2.set_ylabel("Cap °", color="#a78bfa", fontsize=7)
        self.ax2.tick_params(colors="#a78bfa", labelsize=7)

    def push(self, altitude: float, speed: float, heading: float) -> None:
        import time as _time
        now = _time.monotonic()
        if self._t0 is None:
            self._t0 = now
        elapsed = now - self._t0

        self._times.append(elapsed)
        self._alts.append(altitude)
        self._spds.append(speed)
        self._hdgs.append(heading)

        xs = list(self._times)
        self.line_alt.set_data(xs, list(self._alts))
        self.line_spd.set_data(xs, list(self._spds))
        self.line_hdg.set_data(xs, list(self._hdgs))

        if len(xs) >= 2:
            x_min = max(0.0, elapsed - self.WINDOW_SECONDS)
            self.ax1.set_xlim(x_min, max(x_min + 1, elapsed))
            all_y1 = list(self._alts) + list(self._spds)
            y1_min = max(0.0, min(all_y1) - 5)
            y1_max = max(max(all_y1) + 5, y1_min + 10)
            self.ax1.set_ylim(y1_min, y1_max)
            h_vals = list(self._hdgs)
            self.ax2.set_ylim(min(h_vals) - 10, max(h_vals) + 10)

        def _fmt_x(val, _pos=None):
            m, s = divmod(int(val), 60)
            return f"{m:02d}:{s:02d}"

        self.ax1.xaxis.set_major_formatter(_fmt_x)
        self.canvas.draw_idle()

    def add_event_marker(self, label: str, color: str = "#f97316") -> None:
        if not self._times:
            return
        x_val = self._times[-1]
        vl = self.ax1.axvline(x=x_val, color=color, linewidth=1.0, linestyle="--", alpha=0.8)
        self.ax1.text(x_val, self.ax1.get_ylim()[1] * 0.92, label,
                      color=color, fontsize=6, rotation=90, va="top",
                      ha="right", alpha=0.9)
        self._event_vlines.append(vl)
        self.canvas.draw_idle()

    def reset(self) -> None:
        self._t0 = None
        self._times.clear()
        self._alts.clear()
        self._spds.clear()
        self._hdgs.clear()
        for vl in self._event_vlines:
            try:
                vl.remove()
            except Exception:
                pass
        self._event_vlines.clear()
        self.line_alt.set_data([], [])
        self.line_spd.set_data([], [])
        self.line_hdg.set_data([], [])
        self.canvas.draw_idle()


class DataPlotDialog(QDialog):
    def __init__(self, csv_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Telemetry chart - {os.path.basename(csv_path)}")
        self.resize(1200, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        figure = Figure(figsize=(11, 7), dpi=100)
        canvas = FigureCanvasQTAgg(figure)
        layout.addWidget(canvas)

        df = pd.read_csv(csv_path)
        if "Time" not in df.columns:
            raise ValueError("Selected file does not contain a 'Time' column.")

        df["Time"] = pd.to_datetime(df["Time"], format="%H:%M:%S")

        ax = figure.add_subplot(111)
        ax.plot(df["Time"], df["Count"], label="Radiation", color="#ff7b72", linewidth=2)
        ax.plot(df["Time"], df["CO2"], label="CO2", color="#5ec8f8", linewidth=2)
        ax.plot(df["Time"], df["CO"], label="CO", color="#6de28c", linewidth=2)
        ax.plot(df["Time"], df["LPG"], label="LPG", color="#f7c86e", linewidth=2)
        ax.plot(df["Time"], df["Hum"], label="Humidity", color="#79e3d8", linewidth=2)
        ax.plot(df["Time"], df["Temp"], label="Temp", color="#ffb86c", linewidth=2)

        ax.set_xlabel("Time")
        ax.set_ylabel("Values")
        ax.set_title("Logged drone telemetry")
        ax.grid(alpha=0.2)
        ax.legend()
        ax.xaxis.set_major_locator(mdates.SecondLocator(interval=60))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        figure.autofmt_xdate()
        canvas.draw()
