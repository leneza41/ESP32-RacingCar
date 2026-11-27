"""Configuración central y perfil de calibración para LawamyRacing."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
MODELS_DIR = PROJECT_ROOT / "models"
MODEL_PATH = MODELS_DIR / "gesture_recognizer.task"
CALIBRATION_PATH = PROJECT_ROOT / "calibration.json"

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
    "gesture_recognizer/float16/1/gesture_recognizer.task"
)

# Red WiFi por defecto (Modo Access Point del ESP32)
DEFAULT_HOST = "192.168.4.1"
DEFAULT_PORT = 8888
HEARTBEAT_INTERVAL_SEC = 0.20
RECONNECT_INTERVAL_SEC = 2.0

# Parámetros de reconocimiento de gestos
MIN_GESTURE_CONFIDENCE = 0.50
STABILITY_FRAMES = 3
NO_HAND_STOP_FRAMES = 2
PRECISION_HOLD_SEC = 1.0
PRECISION_COOLDOWN_SEC = 2.0

# Mapeo de categorías oficiales de MediaPipe gesture_recognizer.task -> comandos
GESTURE_TO_COMMAND: dict[str, str] = {
    "Thumb_Up": "F",      # Pulgar arriba -> Adelante
    "Thumb_Down": "B",    # Pulgar abajo  -> Atrás
    "Pointing_Up": "L",   # Índice arriba -> Izquierda
    "Victory": "R",       # Victoria      -> Derecha
    "Closed_Fist": "S",   # Puño cerrado  -> Alto
    "Open_Palm": "S",     # Palma abierta -> Alto seguro
    "None": "S",
}

PRECISION_TOGGLE_GESTURE = "ILoveYou"

COMMAND_LABELS: dict[str, str] = {
    "F": "ADELANTE",
    "B": "ATRAS",
    "L": "IZQUIERDA",
    "R": "DERECHA",
    "S": "ALTO",
}


def _clamp_pwm(value: int) -> int:
    return max(0, min(255, int(round(value))))


@dataclass
class CalibrationProfile:
    """Parámetros de velocidad PWM y balanceo para la pista cuadrada."""

    forward_pwm: int = 190
    backward_pwm: int = 180
    left_turn_pwm: int = 165
    right_turn_pwm: int = 165
    # trim_balance: positivo reduce izq / sube der (corrige desvío a la derecha)
    #               negativo sube izq / reduce der (corrige desvío a la izquierda)
    trim_balance: int = 0
    precision_scale: float = 0.72

    @classmethod
    def load(cls, path: Path = CALIBRATION_PATH) -> "CalibrationProfile":
        if not path.exists():
            profile = cls()
            profile.save(path)
            return profile
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls(
            forward_pwm=_clamp_pwm(data.get("forward_pwm", 190)),
            backward_pwm=_clamp_pwm(data.get("backward_pwm", 180)),
            left_turn_pwm=_clamp_pwm(data.get("left_turn_pwm", 165)),
            right_turn_pwm=_clamp_pwm(data.get("right_turn_pwm", 165)),
            trim_balance=max(-80, min(80, int(data.get("trim_balance", 0)))),
            precision_scale=max(0.35, min(1.0, float(data.get("precision_scale", 0.72)))),
        )

    def save(self, path: Path = CALIBRATION_PATH) -> None:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)
            fh.write("\n")

    def compute_pwms(self, direction: str, precision_mode: bool = False) -> tuple[int, int]:
        """Calcula (pwm_izq, pwm_der) aplicando trim y modo precisión."""
        if direction == "S":
            return 0, 0

        scale = self.precision_scale if precision_mode else 1.0

        if direction == "F":
            base = self.forward_pwm * scale
            half_trim = self.trim_balance / 2.0
            pwm_left = _clamp_pwm(base - half_trim)
            pwm_right = _clamp_pwm(base + half_trim)
            return pwm_left, pwm_right

        if direction == "B":
            base = self.backward_pwm * scale
            half_trim = self.trim_balance / 2.0
            pwm_left = _clamp_pwm(base - half_trim)
            pwm_right = _clamp_pwm(base + half_trim)
            return pwm_left, pwm_right

        if direction == "L":
            pwm = _clamp_pwm(self.left_turn_pwm * scale)
            return pwm, pwm

        if direction == "R":
            pwm = _clamp_pwm(self.right_turn_pwm * scale)
            return pwm, pwm

        return 0, 0

    def adjust_drive_speed(self, delta: int) -> None:
        self.forward_pwm = _clamp_pwm(self.forward_pwm + delta)
        self.backward_pwm = _clamp_pwm(self.backward_pwm + delta)

    def adjust_turn_speed(self, delta: int) -> None:
        self.left_turn_pwm = _clamp_pwm(self.left_turn_pwm + delta)
        self.right_turn_pwm = _clamp_pwm(self.right_turn_pwm + delta)

    def adjust_trim(self, delta: int) -> None:
        self.trim_balance = max(-80, min(80, self.trim_balance + delta))
