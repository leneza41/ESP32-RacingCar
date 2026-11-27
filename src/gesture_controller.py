"""Reconocimiento de gestos con MediaPipe, filtro antirrebote y HUD visual."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from config import (
    COMMAND_LABELS,
    GESTURE_TO_COMMAND,
    MIN_GESTURE_CONFIDENCE,
    MODEL_PATH,
    NO_HAND_STOP_FRAMES,
    PRECISION_COOLDOWN_SEC,
    PRECISION_HOLD_SEC,
    PRECISION_TOGGLE_GESTURE,
    STABILITY_FRAMES,
    CalibrationProfile,
)

# Conexiones estándar de los 21 landmarks de la mano (sin depender de mp.solutions)
HAND_CONNECTIONS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 2), (2, 3), (3, 4),          # Pulgar
    (0, 5), (5, 6), (6, 7), (7, 8),          # Índice
    (5, 9), (9, 10), (10, 11), (11, 12),     # Medio
    (9, 13), (13, 14), (14, 15), (15, 16),   # Anular
    (13, 17), (17, 18), (18, 19), (19, 20),  # Meñique
    (0, 17),                                 # Palma
)


@dataclass
class GestureState:
    raw_gesture: str = "None"
    confidence: float = 0.0
    command: str = "S"
    precision_mode: bool = False
    precision_hold_progress: float = 0.0
    hand_detected: bool = False


class GestureStabilityFilter:
    """Suaviza lecturas cuadro a cuadro y maneja el cambio de modo con gesto ILoveYou."""

    def __init__(
        self,
        min_confidence: float = MIN_GESTURE_CONFIDENCE,
        stability_frames: int = STABILITY_FRAMES,
        no_hand_stop_frames: int = NO_HAND_STOP_FRAMES,
        precision_hold_sec: float = PRECISION_HOLD_SEC,
        precision_cooldown_sec: float = PRECISION_COOLDOWN_SEC,
    ) -> None:
        self.min_confidence = min_confidence
        self.stability_frames = stability_frames
        self.no_hand_stop_frames = no_hand_stop_frames
        self.precision_hold_sec = precision_hold_sec
        self.precision_cooldown_sec = precision_cooldown_sec

        self._current_command = "S"
        self._candidate_command = "S"
        self._candidate_count = 0
        self._no_hand_count = 0

        self.precision_mode = False
        self._precision_hold_start: float | None = None
        self._last_precision_toggle: float = 0.0

    def update(
        self,
        gesture_name: str | None,
        confidence: float,
        hand_detected: bool,
        now: float | None = None,
    ) -> GestureState:
        ts = time.monotonic() if now is None else now
        raw = gesture_name or "None"
        hold_progress = 0.0

        # 1. Sin mano detectada -> detener rápido tras NO_HAND_STOP_FRAMES
        if not hand_detected:
            self._precision_hold_start = None
            self._no_hand_count += 1
            if self._no_hand_count >= self.no_hand_stop_frames:
                self._current_command = "S"
                self._candidate_command = "S"
                self._candidate_count = 0
            return GestureState(
                raw_gesture="None",
                confidence=0.0,
                command=self._current_command,
                precision_mode=self.precision_mode,
                precision_hold_progress=0.0,
                hand_detected=False,
            )

        self._no_hand_count = 0

        # 2. Gesto especial ILoveYou -> alterna modo Precisión / Normal con la mano
        if raw == PRECISION_TOGGLE_GESTURE and confidence >= self.min_confidence:
            self._current_command = "S"
            self._candidate_command = "S"
            self._candidate_count = 0

            if ts - self._last_precision_toggle >= self.precision_cooldown_sec:
                if self._precision_hold_start is None:
                    self._precision_hold_start = ts
                elapsed = ts - self._precision_hold_start
                hold_progress = min(1.0, elapsed / self.precision_hold_sec)
                if elapsed >= self.precision_hold_sec:
                    self.precision_mode = not self.precision_mode
                    self._last_precision_toggle = ts
                    self._precision_hold_start = None
                    hold_progress = 1.0

            return GestureState(
                raw_gesture=raw,
                confidence=confidence,
                command="S",
                precision_mode=self.precision_mode,
                precision_hold_progress=hold_progress,
                hand_detected=True,
            )

        self._precision_hold_start = None

        # 3. Mapeo de gestos normales
        if confidence >= self.min_confidence and raw in GESTURE_TO_COMMAND:
            target = GESTURE_TO_COMMAND[raw]
        else:
            target = "S"

        # STOP con puño cerrado o palma abierta responde al instante por seguridad
        if target == "S" and raw in ("Closed_Fist", "Open_Palm") and confidence >= self.min_confidence:
            self._current_command = "S"
            self._candidate_command = "S"
            self._candidate_count = 0
        else:
            if target == self._candidate_command:
                self._candidate_count += 1
            else:
                self._candidate_command = target
                self._candidate_count = 1

            required = 1 if target == "S" and self._current_command == "S" else self.stability_frames
            if self._candidate_count >= required:
                self._current_command = target

        return GestureState(
            raw_gesture=raw,
            confidence=confidence,
            command=self._current_command,
            precision_mode=self.precision_mode,
            precision_hold_progress=hold_progress,
            hand_detected=True,
        )


class GestureController:
    """Envuelve MediaPipe GestureRecognizer y dibuja la interfaz visual en OpenCV."""

    def __init__(self, model_path: Path = MODEL_PATH) -> None:
        if not model_path.exists():
            raise FileNotFoundError(
                f"No se encontró el modelo en {model_path}. Ejecuta: python scripts/download_model.py"
            )

        base_options = mp.tasks.BaseOptions(model_asset_path=str(model_path))
        options = mp.tasks.vision.GestureRecognizerOptions(
            base_options=base_options,
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._recognizer = mp.tasks.vision.GestureRecognizer.create_from_options(options)
        self.filter = GestureStabilityFilter()
        self._last_timestamp_ms = 0

    def process_frame(self, frame_bgr: np.ndarray) -> tuple[GestureState, list]:
        """Analiza un frame BGR y devuelve el estado estabilizado + landmarks de la mano."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        timestamp_ms = int(time.monotonic() * 1000)
        if timestamp_ms <= self._last_timestamp_ms:
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        result = self._recognizer.recognize_for_video(mp_image, timestamp_ms)

        hand_detected = bool(result.hand_landmarks)
        landmarks = result.hand_landmarks[0] if hand_detected else []

        raw_gesture = "None"
        confidence = 0.0
        if result.gestures and result.gestures[0]:
            top = result.gestures[0][0]
            raw_gesture = top.category_name
            confidence = float(top.score)

        state = self.filter.update(raw_gesture, confidence, hand_detected)
        return state, landmarks

    @staticmethod
    def draw_hand_landmarks(frame: np.ndarray, landmarks: list) -> None:
        if not landmarks:
            return
        h, w = frame.shape[:2]
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]

        for start_idx, end_idx in HAND_CONNECTIONS:
            cv2.line(frame, pts[start_idx], pts[end_idx], (0, 220, 255), 2, cv2.LINE_AA)
        for pt in pts:
            cv2.circle(frame, pt, 4, (255, 80, 0), -1, cv2.LINE_AA)

    @staticmethod
    def draw_hud(
        frame: np.ndarray,
        state: GestureState,
        pwm_left: int,
        pwm_right: int,
        profile: CalibrationProfile,
        connected: bool,
        endpoint: str,
        notice_text: str = "",
    ) -> None:
        """Dibuja el tablero de control e información de calibración sobre el video."""
        h, w = frame.shape[:2]

        # Panel superior semitransparente
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 120), (20, 20, 24), -1)
        cv2.rectangle(overlay, (0, h - 74), (w, h), (20, 20, 24), -1)
        cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

        # Estado WiFi
        status_color = (60, 220, 90) if connected else (60, 80, 240)
        status_text = f"ESP32 CONECTADO ({endpoint})" if connected else f"DESCONECTADO ({endpoint})"
        cv2.circle(frame, (20, 24), 7, status_color, -1)
        cv2.putText(frame, status_text, (36, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.58, status_color, 2, cv2.LINE_AA)

        # Modo de velocidad (Normal / Precisión)
        mode_text = "MODO: PRECISION (PISTA)" if state.precision_mode else "MODO: NORMAL"
        mode_color = (0, 215, 255) if state.precision_mode else (220, 220, 220)
        cv2.putText(frame, mode_text, (w - 270, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.58, mode_color, 2, cv2.LINE_AA)

        # Comando actual en grande
        cmd_label = COMMAND_LABELS.get(state.command, "ALTO")
        cmd_color = (80, 255, 120) if state.command != "S" else (120, 180, 255)
        cv2.putText(frame, f"CMD: {cmd_label}", (16, 76), cv2.FONT_HERSHEY_SIMPLEX, 1.05, cmd_color, 3, cv2.LINE_AA)

        # Gesto detectado y confianza
        conf_pct = int(state.confidence * 100)
        cv2.putText(
            frame,
            f"Gesto: {state.raw_gesture} ({conf_pct}%)",
            (16, 106),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (230, 230, 230),
            1,
            cv2.LINE_AA,
        )

        # PWM izquierdo / derecho y trim
        cv2.putText(
            frame,
            f"PWM Izq: {pwm_left:3d} | Der: {pwm_right:3d} | Trim: {profile.trim_balance:+d}",
            (w - 375, 72),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.56,
            (240, 240, 240),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"Base F:{profile.forward_pwm} B:{profile.backward_pwm} Giro L:{profile.left_turn_pwm} R:{profile.right_turn_pwm}",
            (w - 375, 102),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (190, 210, 220),
            1,
            cv2.LINE_AA,
        )

        # Barra de progreso para alternar modo precisión con gesto ILoveYou
        if state.precision_hold_progress > 0.0:
            bar_w = int(220 * state.precision_hold_progress)
            cv2.rectangle(frame, (w // 2 - 110, 130), (w // 2 + 110, 152), (40, 40, 40), -1)
            cv2.rectangle(frame, (w // 2 - 110, 130), (w // 2 - 110 + bar_w, 152), (0, 215, 255), -1)
            cv2.putText(
                frame,
                "Cambiando modo...",
                (w // 2 - 80, 147),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

        if notice_text:
            cv2.putText(
                frame,
                notice_text,
                (16, h - 84),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.56,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )

        # Leyenda inferior de gestos y atajos de calibración
        cv2.putText(
            frame,
            "Manos: PulgarArriba=Adelante | PulgarAbajo=Atras | Indice=Izq | Victoria=Der | Puno/Palma=Alto | ILoveYou(1s)=Precision",
            (12, h - 46),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43,
            (235, 235, 235),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "Calibracion pista: [+/-] Vel. Recta | [,/.] Vel. Giro | [[ / ]] Trim | [G] Guardar JSON | [Q] Salir",
            (12, h - 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43,
            (175, 210, 230),
            1,
            cv2.LINE_AA,
        )

    def close(self) -> None:
        self._recognizer.close()
