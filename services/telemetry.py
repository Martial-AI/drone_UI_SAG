"""Telemetry listeners (UDP, TCP, Serial) for drone telemetry reception."""

from __future__ import annotations

import re
import socket
from datetime import datetime

import numpy as np
import serial
from PySide6.QtCore import QThread, Signal

from core.models import SensorData
from core.utils import clamp


class TelemetryListener(QThread):
    telemetry_received = Signal(object)
    telemetry_status = Signal(str)
    telemetry_error = Signal(str)

    def __init__(self, host: str = "0.0.0.0", port: int = 12345) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self._running = True
        self._socket: socket.socket | None = None

    def stop(self) -> None:
        self._running = False
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

    @staticmethod
    def parse_packet(packet: str, sender: str) -> SensorData:
        """Parse one demo/drone packet."""
        values: dict[str, float] = {}
        text_values: dict[str, str] = {}
        for chunk in packet.split(","):
            if ":" not in chunk:
                continue
            key, raw_value = chunk.split(":", 1)
            normalized_key = key.strip().upper()
            raw_value = raw_value.strip()
            try:
                values[normalized_key] = float(raw_value)
            except ValueError:
                text_values[normalized_key] = raw_value

        aliases = {
            "CO2": ("CO2",),
            "LPG": ("LPG", "HCS"),
            "CO": ("CO", "FUM"),
            "HUM": ("HUM", "HUMIDITY"),
            "COUNT": ("COUNT", "CPS", "RADIATION"),
            "TEMP": ("TEMP", "TEMPERATURE"),
            "PITCH": ("PITCH", "PITCH_ORIENTATION"),
            "ROLL": ("ROLL", "ROLL_ORIENTATION"),
            "HEADING": ("HEADING", "AZIMUTH", "YAW"),
            "GPS_SPEED": ("GPS_SPEED", "SPEED", "GROUND_SPEED"),
            "V_SPEED": ("V_SPEED", "VERTICAL_SPEED", "VSPEED"),
            "ALTITUDE": ("ALTITUDE", "ALT", "HEIGHT"),
            "BATTERY": ("BATTERY", "BAT", "BATTERY_PERCENTAGE"),
            "DISTANCE": ("DISTANCE", "DIST", "RANGE"),
            "LATITUDE": ("LATITUDE", "LAT", "GPS_LAT"),
            "LONGITUDE": ("LONGITUDE", "LON", "LONG", "GPS_LON", "GPS_LONG"),
        }

        def pick(name: str) -> float:
            for key in aliases[name]:
                if key in values:
                    return values[key]
            raise KeyError(name)

        def optional(name: str, default: float) -> float:
            for key in aliases[name]:
                if key in values:
                    return values[key]
            return default

        def optional_coord(name: str) -> float | None:
            for key in aliases[name]:
                if key in values:
                    return values[key]
            return None

        lidar_points = TelemetryListener._parse_lidar_points(values, text_values)
        if lidar_points:
            co2 = optional("CO2", 0.0)
            lpg = optional("LPG", 0.0)
            co = optional("CO", 0.0)
            humidity = optional("HUM", 0.0)
            radiation = optional("COUNT", 0.0)
            temperature = optional("TEMP", 0.0)
        else:
            co2 = pick("CO2")
            lpg = pick("LPG")
            co = pick("CO")
            humidity = pick("HUM")
            radiation = pick("COUNT")
            temperature = pick("TEMP")
        has_heading = any(key in values for key in aliases["HEADING"])
        latitude = optional_coord("LATITUDE")
        longitude = optional_coord("LONGITUDE")
        has_position = latitude is not None and longitude is not None

        return SensorData(
            co2=co2,
            lpg=lpg,
            co=co,
            humidity=humidity,
            radiation=radiation,
            temperature=temperature,
            pitch=optional("PITCH", clamp((temperature - 25.0) * 1.2, -45.0, 45.0)),
            roll=optional("ROLL", clamp((humidity - 50.0) * 0.8, -45.0, 45.0)),
            heading=optional("HEADING", (co2 + radiation * 5) % 360),
            gps_speed=optional("GPS_SPEED", clamp(lpg / 40.0, 0.0, 140.0)),
            vertical_speed=optional("V_SPEED", clamp((temperature - 20.0) / 2.0, -25.0, 25.0)),
            altitude=optional("ALTITUDE", clamp(co2 / 4.0, 0.0, 1200.0)),
            battery=optional("BATTERY", clamp(100.0 - radiation * 1.2, 5.0, 100.0)),
            distance=optional("DISTANCE", clamp(humidity * 2.0, 0.0, 500.0)),
            latitude=latitude,
            longitude=longitude,
            lidar_points=lidar_points,
            position_source="drone" if has_position else "relative",
            heading_source="drone" if has_heading else "derived",
            sender=sender,
            raw_packet=packet,
            timestamp=datetime.now().strftime("%H:%M:%S"),
        )

    @staticmethod
    def _parse_lidar_points(values: dict[str, float], text_values: dict[str, str]) -> tuple[tuple[float, float], ...]:
        points: list[tuple[float, float]] = []
        for key in ("LIDAR", "RADAR", "OBSTACLES", "OBSTACLE"):
            raw_value = text_values.get(key)
            if not raw_value:
                continue
            for item in re.split(r"[;|]", raw_value):
                item = item.strip()
                if not item:
                    continue
                parts = re.split(r"[:=/ ]+", item)
                if len(parts) < 2:
                    continue
                try:
                    angle = float(parts[0])
                    distance = float(parts[1])
                except ValueError:
                    continue
                if np.isfinite(angle) and np.isfinite(distance) and distance >= 0:
                    points.append((angle % 360.0, distance))

        angle = values.get("LIDAR_ANGLE", values.get("RADAR_ANGLE"))
        distance = values.get("LIDAR_DISTANCE", values.get("RADAR_DISTANCE", values.get("OBSTACLE_DISTANCE")))
        if angle is not None and distance is not None and np.isfinite(angle) and np.isfinite(distance) and distance >= 0:
            points.append((angle % 360.0, distance))
        return tuple(points[:360])

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket = sock
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        sock.settimeout(1.0)

        try:
            sock.bind((self.host, self.port))
            self.telemetry_status.emit(f"Telemetry UDP {self.host}:{self.port}")
        except OSError as exc:
            self.telemetry_error.emit(f"Unable to bind telemetry socket: {exc}")
            return

        while self._running:
            try:
                payload, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            packet = payload.decode("utf-8", errors="ignore").strip()
            try:
                data = self.parse_packet(packet, addr[0])
            except (ValueError, KeyError) as exc:
                self.telemetry_error.emit(f"Telemetry parse error: {exc}")
                continue

            self.telemetry_status.emit(f"Last telemetry from {addr[0]}")
            self.telemetry_received.emit(data)


class TcpTelemetryListener(QThread):
    telemetry_received = Signal(object)
    telemetry_status = Signal(str)
    telemetry_error = Signal(str)

    def __init__(self, host: str, port: int) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self._running = True
        self._socket: socket.socket | None = None

    def stop(self) -> None:
        self._running = False
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

    def run(self) -> None:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket = client
        client.settimeout(1.0)

        try:
            client.connect((self.host, self.port))
            self.telemetry_status.emit(f"TCP {self.host}:{self.port}")
        except OSError as exc:
            self.telemetry_error.emit(f"TCP connect error: {exc}")
            return

        buffer = ""
        while self._running:
            try:
                payload = client.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            if not payload:
                break

            buffer += payload.decode("utf-8", errors="ignore")
            while "\n" in buffer:
                packet, buffer = buffer.split("\n", 1)
                packet = packet.strip()
                if not packet:
                    continue
                try:
                    data = TelemetryListener.parse_packet(packet, self.host)
                except (ValueError, KeyError) as exc:
                    self.telemetry_error.emit(f"TCP parse error: {exc}")
                    continue
                self.telemetry_status.emit(f"TCP data from {self.host}")
                self.telemetry_received.emit(data)


class SerialTelemetryListener(QThread):
    telemetry_received = Signal(object)
    telemetry_status = Signal(str)
    telemetry_error = Signal(str)

    def __init__(self, port_name: str, baudrate: int = 115200) -> None:
        super().__init__()
        self.port_name = port_name
        self.baudrate = baudrate
        self._running = True
        self._serial_port: serial.Serial | None = None

    def stop(self) -> None:
        self._running = False
        if self._serial_port is not None:
            try:
                self._serial_port.close()
            except Exception:
                pass

    def run(self) -> None:
        try:
            serial_port = serial.Serial(self.port_name, self.baudrate, timeout=1)
            self._serial_port = serial_port
            self.telemetry_status.emit(f"SERIAL {self.port_name}@{self.baudrate}")
        except Exception as exc:
            self.telemetry_error.emit(f"Serial open error: {exc}")
            return

        while self._running:
            try:
                raw_line = serial_port.readline()
            except Exception as exc:
                self.telemetry_error.emit(f"Serial read error: {exc}")
                break

            if not raw_line:
                continue

            packet = raw_line.decode("utf-8", errors="ignore").strip()
            if not packet:
                continue

            try:
                data = TelemetryListener.parse_packet(packet, self.port_name)
            except (ValueError, KeyError) as exc:
                self.telemetry_error.emit(f"Serial parse error: {exc}")
                continue

            self.telemetry_status.emit(f"Serial data from {self.port_name}")
            self.telemetry_received.emit(data)
