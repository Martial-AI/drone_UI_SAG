"""Video stream receivers for RGB and thermal cameras via OpenCV/UDP."""

from __future__ import annotations

import os
import socket
import time

import cv2 as cv
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage


class VideoStreamReceiver(QThread):
    frame_received = Signal(object)
    stream_status = Signal(str)
    stream_error = Signal(str)

    def __init__(self, source_url: str, label: str) -> None:
        super().__init__()
        self.source_url = source_url
        self.label = label
        self._running = True
        self._capture: cv.VideoCapture | None = None

    def _source_protocol(self) -> str:
        text = self.source_url.strip().lower()
        if text.startswith("rtsp://"):
            return "rtsp"
        if text.startswith("udp://"):
            return "udp"
        if text.startswith("http://") or text.startswith("https://"):
            return "http"
        return "file"

    def _backend_attempts(self, protocol: str) -> list[tuple[int | None, str]]:
        if protocol == "http":
            return [
                (None, "AUTO"),
                (cv.CAP_FFMPEG, "FFMPEG"),
            ]
        if protocol in {"rtsp", "udp"}:
            return [
                (cv.CAP_FFMPEG, "FFMPEG"),
                (None, "AUTO"),
            ]
        return [(None, "AUTO")]

    @staticmethod
    def _set_ffmpeg_options(options: str | None) -> str | None:
        previous = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
        if options:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = options
        elif "OPENCV_FFMPEG_CAPTURE_OPTIONS" in os.environ:
            del os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]
        return previous

    def _open_capture(self) -> tuple[cv.VideoCapture | None, str]:
        protocol = self._source_protocol()
        ffmpeg_options = None
        if protocol == "rtsp":
            ffmpeg_options = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay"
        elif protocol == "udp":
            ffmpeg_options = "fflags;nobuffer|flags;low_delay"

        for backend, backend_name in self._backend_attempts(protocol):
            previous_options = self._set_ffmpeg_options(ffmpeg_options if backend == cv.CAP_FFMPEG else None)
            try:
                capture = cv.VideoCapture(self.source_url) if backend is None else cv.VideoCapture(self.source_url, backend)
            finally:
                self._set_ffmpeg_options(previous_options)
            self._configure_capture(capture, protocol)
            if capture.isOpened():
                return capture, backend_name
            capture.release()
        return None, ""

    @staticmethod
    def _configure_capture(capture: cv.VideoCapture, protocol: str) -> None:
        if not capture:
            return
        capture.set(cv.CAP_PROP_BUFFERSIZE, 1)
        if protocol in {"rtsp", "udp"}:
            capture.set(cv.CAP_PROP_OPEN_TIMEOUT_MSEC, 2500)
            capture.set(cv.CAP_PROP_READ_TIMEOUT_MSEC, 1200)
        elif protocol == "http":
            capture.set(cv.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
            capture.set(cv.CAP_PROP_READ_TIMEOUT_MSEC, 2000)

    def stop(self) -> None:
        self._running = False
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def run(self) -> None:
        while self._running:
            capture, backend_name = self._open_capture()
            if capture is None:
                self.stream_error.emit(f"{self.label} stream unavailable - retrying")
                self.msleep(2000)
                continue

            self._capture = capture
            self.stream_status.emit(f"{self.label} stream connected ({backend_name})")
            failed_reads = 0
            last_emit_time = 0.0
            emit_interval = 1.0 / 20.0
            while self._running:
                ok, frame = capture.read()
                if not ok or frame is None:
                    failed_reads += 1
                    if failed_reads >= 60:
                        self.stream_error.emit(f"{self.label} stream lost - reconnecting")
                        break
                    self.msleep(25)
                    continue
                failed_reads = 0

                now = time.monotonic()
                if now - last_emit_time < emit_interval:
                    continue
                last_emit_time = now

                rgb_frame = cv.cvtColor(frame, cv.COLOR_BGR2RGB)
                height, width, channels = rgb_frame.shape
                bytes_per_line = channels * width
                qt_image = QImage(
                    rgb_frame.data,
                    width,
                    height,
                    bytes_per_line,
                    QImage.Format_RGB888,
                ).copy()
                self.frame_received.emit(qt_image)

            capture.release()
            self._capture = None
            if self._running:
                self.msleep(1200)


class ThermalReceiver(QThread):
    frame_received = Signal(object)
    thermal_status = Signal(str)

    def __init__(self, host: str = "0.0.0.0", port: int = 5005) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self._running = True
        self._enabled = False
        self._socket: socket.socket | None = None

    def stop(self) -> None:
        self._running = False
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket = sock
        sock.settimeout(1.0)

        try:
            sock.bind((self.host, self.port))
            self.thermal_status.emit(f"Thermal UDP {self.host}:{self.port}")
        except OSError as exc:
            self.thermal_status.emit(f"Thermal bind error: {exc}")
            return

        chunk_size = 2048
        data_buffer = b""

        while self._running:
            try:
                chunk, _addr = sock.recvfrom(chunk_size)
            except socket.timeout:
                continue
            except OSError:
                break

            data_buffer += chunk
            if len(chunk) == chunk_size:
                continue

            if not self._enabled:
                data_buffer = b""
                continue

            if data_buffer.startswith(b"\xFF\xD8") and data_buffer.endswith(b"\xFF\xD9"):
                np_arr = np.frombuffer(data_buffer, dtype=np.uint8)
                image = cv.imdecode(np_arr, cv.IMREAD_COLOR)
                if image is not None:
                    rgb_image = cv.cvtColor(image, cv.COLOR_BGR2RGB)
                    height, width, channels = rgb_image.shape
                    bytes_per_line = channels * width
                    qt_image = QImage(
                        rgb_image.data,
                        width,
                        height,
                        bytes_per_line,
                        QImage.Format_RGB888,
                    ).copy()
                    self.frame_received.emit(qt_image)
            data_buffer = b""
