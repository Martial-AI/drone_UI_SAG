"""Command client for sending commands to the drone flight controller."""

from __future__ import annotations

import queue
import socket
import time
from PySide6.QtCore import QThread, Signal


class CommandClient(QThread):
    connection_changed = Signal(str, str)
    command_logged = Signal(str)

    def __init__(self, host: str = "192.168.0.147", port: int = 12347) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self._running = True
        self._socket: socket.socket | None = None
        self._commands: queue.Queue[str] = queue.Queue()

    def send_command(self, command: str) -> None:
        self._commands.put(command)

    def stop(self) -> None:
        self._running = False
        self._commands.put("__STOP__")
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

    def _close_socket(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        self._socket = None

    def run(self) -> None:
        while self._running:
            if self._socket is None:
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(4)
                try:
                    client.connect((self.host, self.port))
                    self._socket = client
                    self.connection_changed.emit("Connected", "good")
                except OSError:
                    client.close()
                    self.connection_changed.emit("Connecting...", "neutral")
                    time.sleep(3)
                    continue

            try:
                command = self._commands.get(timeout=1.0)
            except queue.Empty:
                continue

            if command == "__STOP__":
                break

            try:
                assert self._socket is not None
                self._socket.sendall(command.encode("utf-8"))
                self.command_logged.emit(f"Command sent: {command}")
            except OSError as exc:
                self.command_logged.emit(f"Send failed: {exc}")
                self.connection_changed.emit("Connection lost", "bad")
                self._close_socket()
                self._commands.put(command)
                time.sleep(2)

        self._close_socket()
