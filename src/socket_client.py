"""Cliente Socket TCP con reconexión automática y heartbeat para el ESP32."""

from __future__ import annotations

import socket
import threading
import time

from config import DEFAULT_HOST, DEFAULT_PORT, HEARTBEAT_INTERVAL_SEC, RECONNECT_INTERVAL_SEC


def format_command(direction: str, pwm_left: int, pwm_right: int) -> str:
    """Genera el paquete de protocolo: CMD:<DIR>,<PWM_L>,<PWM_R>\\n."""
    d = direction if direction in ("F", "B", "L", "R", "S") else "S"
    l_val = max(0, min(255, int(pwm_left)))
    r_val = max(0, min(255, int(pwm_right)))
    return f"CMD:{d},{l_val},{r_val}\n"


class CarSocketClient:
    """Envía comandos al carrito ESP32 sin bloquear el bucle de cámara."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_SEC,
        reconnect_interval: float = RECONNECT_INTERVAL_SEC,
    ) -> None:
        self.host = host
        self.port = port
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_interval = reconnect_interval

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None

        self._connected = False
        self._desired_packet = format_command("S", 0, 0)
        self._last_sent_packet = ""
        self._last_sent_time = 0.0
        self._dirty = True
        self._last_error = ""

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def last_sent_packet(self) -> str:
        with self._lock:
            return self._last_sent_packet.strip()

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def start(self) -> None:
        """Inicia el hilo de conexión y envío."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="CarSocketThread", daemon=True)
        self._thread.start()

    def set_command(self, direction: str, pwm_left: int, pwm_right: int) -> None:
        """Actualiza el comando actual; despierta el hilo de inmediato si cambió."""
        packet = format_command(direction, pwm_left, pwm_right)
        with self._lock:
            if packet != self._desired_packet:
                self._desired_packet = packet
                self._dirty = True
                self._wake_event.set()

    def stop(self) -> None:
        """Envía freno de emergencia (CMD:S,0,0) y cierra limpiamente."""
        self.set_command("S", 0, 0)
        # Pequeña oportunidad para enviar el paquete de STOP antes de cerrar
        self._send_stop_best_effort()
        self._stop_event.set()
        self._wake_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._close_socket()

    def _send_stop_best_effort(self) -> None:
        with self._lock:
            sock = self._sock
        if sock is not None:
            try:
                sock.sendall(format_command("S", 0, 0).encode("ascii"))
            except OSError:
                pass

    def _connect(self) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.5)
        try:
            sock.connect((self.host, self.port))
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(0.8)
            with self._lock:
                self._sock = sock
                self._connected = True
                self._dirty = True
                self._last_error = ""
            return True
        except OSError as exc:
            sock.close()
            with self._lock:
                self._connected = False
                self._last_error = str(exc)
            return False

    def _close_socket(self) -> None:
        with self._lock:
            sock = self._sock
            self._sock = None
            self._connected = False
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _run_loop(self) -> None:
        next_reconnect = 0.0

        while not self._stop_event.is_set():
            if not self.is_connected:
                now = time.monotonic()
                if now >= next_reconnect:
                    if not self._connect():
                        next_reconnect = time.monotonic() + self.reconnect_interval
                self._wake_event.wait(timeout=0.2)
                self._wake_event.clear()
                continue

            now = time.monotonic()
            with self._lock:
                should_send = self._dirty or (now - self._last_sent_time >= self.heartbeat_interval)
                packet = self._desired_packet
                sock = self._sock

            if should_send and sock is not None:
                try:
                    sock.sendall(packet.encode("ascii"))
                    with self._lock:
                        self._last_sent_packet = packet
                        self._last_sent_time = time.monotonic()
                        if packet == self._desired_packet:
                            self._dirty = False
                except OSError as exc:
                    with self._lock:
                        self._last_error = str(exc)
                    self._close_socket()
                    next_reconnect = time.monotonic() + self.reconnect_interval
                    continue

            self._wake_event.wait(timeout=0.04)
            self._wake_event.clear()
