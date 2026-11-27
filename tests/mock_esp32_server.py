"""Simulador local del servidor TCP del ESP32 para probar Python sin hardware físico."""

from __future__ import annotations

import argparse
import socket
import time

COMMAND_NAMES = {
    "F": "ADELANTE  (Izq: + | Der: +)",
    "B": "ATRAS     (Izq: - | Der: -)",
    "L": "IZQUIERDA (Izq: - | Der: +)",
    "R": "DERECHA   (Izq: + | Der: -)",
    "S": "ALTO      (Motores apagados)",
}


def run_mock_server(host: str = "127.0.0.1", port: int = 8888) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    print(f"[MOCK ESP32] Escuchando en {host}:{port} (Ctrl+C para salir)...")

    try:
        while True:
            conn, addr = server.accept()
            print(f"\n[MOCK ESP32] Cliente conectado desde {addr}")
            conn.settimeout(0.55)
            buf = ""
            last_state = ""

            with conn:
                while True:
                    try:
                        chunk = conn.recv(256)
                        if not chunk:
                            print("[MOCK ESP32] Cliente desconectado -> Motores en ALTO.")
                            break
                        buf += chunk.decode("ascii", errors="ignore")
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            line = line.strip()
                            if line.startswith("CMD:"):
                                parts = line[4:].split(",")
                                if len(parts) == 3:
                                    d, pwm_l, pwm_r = parts
                                    desc = COMMAND_NAMES.get(d, "DESCONOCIDO")
                                    state = f"{desc} | PWM Izq={pwm_l:>3} | PWM Der={pwm_r:>3}"
                                    if state != last_state:
                                        ts = time.strftime("%H:%M:%S")
                                        print(f"[{ts}] {state}")
                                        last_state = state
                    except socket.timeout:
                        if last_state and not last_state.startswith("ALTO"):
                            print("[MOCK ESP32] [WATCHDOG >500ms] Sin señal -> Motores en ALTO.")
                            last_state = "ALTO"
    except KeyboardInterrupt:
        print("\n[MOCK ESP32] Simulador detenido.")
    finally:
        server.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simula el carrito ESP32 por Sockets TCP.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8888)
    args = parser.parse_args()
    run_mock_server(args.host, args.port)
