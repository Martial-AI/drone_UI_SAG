# Spectrum Air Guard — Drone UI

Modular Python/PySide6 drone ground control station.

## Architecture

```
main.py              ← Application entrypoint (~110 lines)
main_window.py       ← MainWindow class (extracted from monolithic)
config.py            ← Constants, paths, asset helpers
core/
  __init__.py
  models.py          ← SensorData, PositionFix, AlertEntry
  i18n.py            ← EN/FR bilingual dictionaries + tr()
  utils.py           ← Math, geo, clamp, slugify_name
services/
  __init__.py
  telemetry.py       ← TelemetryListener, TcpTelemetryListener, SerialTelemetryListener
  commands.py        ← CommandClient
  video_stream.py    ← VideoStreamReceiver, ThermalReceiver
widgets/
  __init__.py
  cards.py           ← DashboardCard, StatusBadge, LongPressButton, ThemeSwitch, StartupSplash, MetricCard
  gauges.py          ← CircularGauge, ArtificialHorizon, Compass, TapeGauge, Battery, Sparkline
  charts.py          ← TelemetryChartWidget, FlightDataChartWidget, DataPlotDialog
  flight_log.py      ← AlertBannerWidget, FlightLogWidget
  radar.py           ← Radar360Widget, FloatingRadarWidget
  map_widget.py      ← OfflineMapWidget (satellite/relative)
  floating.py        ← FloatingScienceChartWidget, FloatingScreenWidget
  dialogs.py         ← All dialogs (Connection, Shortcuts, Video Source, Map zones, etc.)
  video_osd.py       ← VideoOSDWidget — Tactical HUD overlay (FULL/MIN/OFF, key O)
  pip.py             ← PipWindowWidget — Picture-in-Picture (key P, 🔄 swap)
SpectrumAirGuard.spec ← PyInstaller build spec
```

## Features

- **Live video + OSD**: Tactical HUD overlay (pitch/roll ladder, reticle, speed/alt tapes, top banner, compass ribbon). Cycle modes with `O`.
- **Picture-in-Picture**: Mini-map while video is primary (or mini-video while map is primary). Toggle with `P`, swap with 🔄.
- **Offline Maps**: Satellite tile caching, zone management, download with progress dialog.
- **Telemetry**: UDP/TCP/Serial listeners, live plotting, CSV + SQLite logging.
- **Flight Alerts & Log**: Inline alert banner and scrollable flight log in main panel.
- **Menu**: Toggle right/left screens, radar, PiP, OSD, flight alerts, flight log. Keyboard shortcuts (F1), language switch (EN/FR), sounds toggle.

## Requirements

```
PySide6
cv2 (opencv-python)
numpy
pandas
matplotlib
pyserial
```

## Run

```bash
py -3.11 main.py
```

## Build (PyInstaller)

```bash
pyinstaller SpectrumAirGuard.spec
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `O` | Cycle OSD mode (FULL → MIN → OFF) |
| `P` | Toggle Picture-in-Picture |
| `M` | Map view |
| `V` | Live video view |
| `T` | Thermal view |
| `D` | Telemetry data view |
| `F` | Follow drone toggle |
| `C` | Recenter map |
| `W` | Waypoint mode |
| `F1` | Keyboard shortcuts help |
| `F11` | Fullscreen toggle |
| `Ctrl+A` | Arm / Disarm |
| `Ctrl+T` | Takeoff |
| `Ctrl+R` | RTL |
| `Ctrl+L` | Land |
| `Space` | Hold |
| `1-5` | Flight mode selection |
| `Ctrl+Shift+K` | Emergency kill |
