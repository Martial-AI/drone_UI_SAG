"""Spectrum Air Guard - Main Application Entrypoint.

Refactored modular architecture:
  - config.py: Centralized configuration, paths, audio/icon helpers
  - core/: Models, i18n, utilities
  - services/: Network & hardware communication (Telemetry, Commands, Video)
  - widgets/: UI cards, gauges, charts, logs, radar, map, dialogs, OSD & PiP
  - main_window.py: Main application window and business orchestration
"""

from __future__ import annotations

import os
import sys
import time

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from config import (
    ENABLE_STARTUP_SPLASH,
    app_icon_path,
    ensure_data_dir,
    ensure_maps_dir,
)
from widgets.cards import StartupSplash
from main_window import MainWindow


def build_app() -> QApplication:
    app = QApplication(sys.argv)
    app.setApplicationName("Spectrum Air Guard")
    app.setStyle("Fusion")
    icon_file = app_icon_path()
    if os.path.exists(icon_file):
        app.setWindowIcon(QIcon(icon_file))
    return app


def _pump_startup_events(
    app: QApplication,
    duration_ms: int,
) -> None:
    if duration_ms <= 0:
        return
    deadline = time.monotonic() + duration_ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def update_startup_splash(
    app: QApplication,
    splash: StartupSplash,
    value: int,
    status: str,
    pause_ms: int = 55,
) -> None:
    splash.set_progress(value, status)
    app.processEvents()
    _pump_startup_events(app, pause_ms)


def animate_startup_splash(
    app: QApplication,
    splash: StartupSplash,
    start_value: int,
    end_value: int,
    status: str,
    duration_ms: int,
) -> None:
    duration_ms = max(0, int(duration_ms))
    if duration_ms == 0:
        update_startup_splash(app, splash, end_value, status, 0)
        return

    steps = max(int(duration_ms / 20), abs(end_value - start_value), 1)
    step_duration = duration_ms / steps
    for index in range(steps + 1):
        ratio = index / steps
        value = round(start_value + (end_value - start_value) * ratio)
        splash.set_progress(value, status)
        app.processEvents()
        if index < steps:
            time.sleep(step_duration / 1000.0)


def main() -> int:
    app = build_app()
    if not ENABLE_STARTUP_SPLASH:
        window = MainWindow()
        window.show()
        return app.exec()

    splash = StartupSplash()
    splash.show()
    update_startup_splash(app, splash, 0, "Demarrage...", 0)
    _pump_startup_events(app, 2000)
    animate_startup_splash(app, splash, 0, 18, "Initialisation des modules...", 900)
    ensure_data_dir()
    ensure_maps_dir()
    animate_startup_splash(app, splash, 18, 36, "Chargement des ressources...", 900)
    animate_startup_splash(app, splash, 36, 52, "Preparation de l'interface...", 800)
    window = MainWindow()
    animate_startup_splash(app, splash, 52, 76, "Connexion des services...", 900)
    window.show()
    animate_startup_splash(app, splash, 76, 100, "Finalisation...", 1500)
    update_startup_splash(app, splash, 100, "Pret", 120)
    splash.close()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
