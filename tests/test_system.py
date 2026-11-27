"""Pruebas automatizadas de calibración, filtro de gestos, sockets y carga del modelo."""

from __future__ import annotations

import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from config import MODEL_PATH, CalibrationProfile
from src.gesture_controller import GestureStabilityFilter
from src.socket_client import CarSocketClient, format_command


class TestCalibrationProfile(unittest.TestCase):
    def test_pwm_trim_and_precision(self) -> None:
        profile = CalibrationProfile(
            forward_pwm=200,
            backward_pwm=180,
            left_turn_pwm=160,
            right_turn_pwm=150,
            trim_balance=10,
            precision_scale=0.5,
        )
        # Adelante normal: base 200, trim +10 -> izq 195, der 205
        self.assertEqual(profile.compute_pwms("F", precision_mode=False), (195, 205))
        # Adelante precisión (50%): base 100, trim +10 -> izq 95, der 105
        self.assertEqual(profile.compute_pwms("F", precision_mode=True), (95, 105))
        # Giros
        self.assertEqual(profile.compute_pwms("L", precision_mode=False), (160, 160))
        self.assertEqual(profile.compute_pwms("R", precision_mode=True), (75, 75))
        # Alto siempre 0,0
        self.assertEqual(profile.compute_pwms("S", precision_mode=False), (0, 0))

    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cal.json"
            original = CalibrationProfile(forward_pwm=210, backward_pwm=175, trim_balance=-12)
            original.save(path)
            loaded = CalibrationProfile.load(path)
            self.assertEqual(loaded, original)


class TestGestureStabilityFilter(unittest.TestCase):
    def test_debounce_and_immediate_stop(self) -> None:
        flt = GestureStabilityFilter(min_confidence=0.65, stability_frames=3, no_hand_stop_frames=2)

        # 2 frames de Thumb_Up no bastan aún para arrancar
        self.assertEqual(flt.update("Thumb_Up", 0.90, True, now=1.0).command, "S")
        self.assertEqual(flt.update("Thumb_Up", 0.90, True, now=1.1).command, "S")
        # 3er frame confirma Adelante
        self.assertEqual(flt.update("Thumb_Up", 0.90, True, now=1.2).command, "F")

        # Puño cerrado detiene en 1 solo frame por seguridad
        self.assertEqual(flt.update("Closed_Fist", 0.85, True, now=1.3).command, "S")

    def test_precision_mode_toggle_with_hand(self) -> None:
        flt = GestureStabilityFilter(precision_hold_sec=1.0, precision_cooldown_sec=2.0)
        self.assertFalse(flt.precision_mode)

        s1 = flt.update("ILoveYou", 0.92, True, now=10.0)
        self.assertEqual(s1.command, "S")
        self.assertFalse(s1.precision_mode)

        s2 = flt.update("ILoveYou", 0.92, True, now=10.5)
        self.assertAlmostEqual(s2.precision_hold_progress, 0.5, places=2)
        self.assertFalse(s2.precision_mode)

        s3 = flt.update("ILoveYou", 0.92, True, now=11.05)
        self.assertTrue(s3.precision_mode)


class TestSocketCommunication(unittest.TestCase):
    def test_tcp_client_sends_commands_and_stop(self) -> None:
        received: list[str] = []
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.listen(1)

        def _serve() -> None:
            conn, _ = server.accept()
            conn.settimeout(1.5)
            buf = ""
            with conn:
                while True:
                    try:
                        data = conn.recv(256)
                        if not data:
                            break
                        buf += data.decode("ascii")
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            received.append(line.strip())
                    except socket.timeout:
                        break
            server.close()

        t = threading.Thread(target=_serve, daemon=True)
        t.start()

        client = CarSocketClient(host="127.0.0.1", port=port, heartbeat_interval=0.1)
        client.start()

        deadline = time.monotonic() + 2.0
        while not client.is_connected and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(client.is_connected)

        client.set_command("F", 190, 180)
        time.sleep(0.15)
        client.set_command("R", 160, 160)
        time.sleep(0.15)
        client.stop()
        t.join(timeout=2.0)

        self.assertIn("CMD:F,190,180", received)
        self.assertIn("CMD:R,160,160", received)
        self.assertEqual(received[-1], "CMD:S,0,0")

    def test_format_command_clamping(self) -> None:
        self.assertEqual(format_command("F", 300, -10), "CMD:F,255,0\n")
        self.assertEqual(format_command("X", 100, 100), "CMD:S,100,100\n")


class TestMediaPipeModelLoad(unittest.TestCase):
    @unittest.skipUnless(MODEL_PATH.exists(), "El modelo gesture_recognizer.task aún no está descargado.")
    def test_model_loads_and_processes_blank_frame(self) -> None:
        import numpy as np
        from src.gesture_controller import GestureController

        ctrl = GestureController(MODEL_PATH)
        try:
            blank = np.zeros((240, 320, 3), dtype=np.uint8)
            state, landmarks = ctrl.process_frame(blank)
            self.assertFalse(state.hand_detected)
            self.assertEqual(state.command, "S")
            self.assertEqual(landmarks, [])
        finally:
            ctrl.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
