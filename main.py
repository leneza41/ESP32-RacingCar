"""Punto de entrada principal de LawamyRacing (Webcam + MediaPipe + Sockets WiFi)."""

from __future__ import annotations

import argparse
import time

import cv2

from config import CALIBRATION_PATH, COMMAND_LABELS, DEFAULT_HOST, DEFAULT_PORT, CalibrationProfile
from scripts.download_model import ensure_model_downloaded
from src.gesture_controller import GestureController
from src.socket_client import CarSocketClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Controla el carrito ESP32 mediante gestos de la mano (MediaPipe + Sockets WiFi)."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"IP del ESP32 o simulador (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Puerto TCP del ESP32 (default: {DEFAULT_PORT})")
    parser.add_argument("--camera", type=int, default=0, help="Índice de la webcam en OpenCV (default: 0)")
    parser.add_argument(
        "--no-socket",
        action="store_true",
        help="Ejecuta solo reconocimiento de gestos en cámara sin abrir conexión Socket.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    model_path = ensure_model_downloaded()
    profile = CalibrationProfile.load(CALIBRATION_PATH)
    controller = GestureController(model_path=model_path)

    client: CarSocketClient | None = None
    if not args.no_socket:
        client = CarSocketClient(host=args.host, port=args.port)
        client.start()

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        if client:
            client.stop()
        controller.close()
        raise RuntimeError(
            f"No se pudo abrir la webcam (índice {args.camera}). Verifica que no esté en uso por otra app."
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)

    window_name = "LawamyRacing - Control por Gestos"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 960, 540)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)

    endpoint_label = "SIN SOCKET" if args.no_socket else f"{args.host}:{args.port}"
    notice_text = ""
    notice_until = 0.0
    last_logged = None

    def show_notice(msg: str, duration: float = 2.0) -> None:
        nonlocal notice_text, notice_until
        notice_text = msg
        notice_until = time.monotonic() + duration

    print("[INFO] LawamyRacing iniciado. Presiona 'Q' o 'ESC' en la ventana de cámara para salir.", flush=True)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[WARN] No se pudo leer un frame de la cámara.", flush=True)
                time.sleep(0.05)
                continue

            # Espejo horizontal para que izquierda/derecha coincidan naturalmente
            frame = cv2.flip(frame, 1)

            state, landmarks = controller.process_frame(frame)
            pwm_left, pwm_right = profile.compute_pwms(state.command, state.precision_mode)

            # Retroalimentación en consola al cambiar gesto o comando
            log_key = (state.command, state.raw_gesture, state.precision_mode, pwm_left, pwm_right)
            if log_key != last_logged:
                ts = time.strftime("%H:%M:%S")
                cmd_name = COMMAND_LABELS.get(state.command, "ALTO")
                mode_name = "PRECISION" if state.precision_mode else "NORMAL"
                conf_pct = int(state.confidence * 100)
                print(
                    f"[{ts}] Gesto: {state.raw_gesture:<12} ({conf_pct:3d}%) -> "
                    f"CMD: {cmd_name:<9} | Modo: {mode_name:<9} | PWM Izq={pwm_left:3d} Der={pwm_right:3d}",
                    flush=True,
                )
                last_logged = log_key

            if client is not None:
                client.set_command(state.command, pwm_left, pwm_right)

            controller.draw_hand_landmarks(frame, landmarks)
            active_notice = notice_text if time.monotonic() < notice_until else ""
            controller.draw_hud(
                frame=frame,
                state=state,
                pwm_left=pwm_left,
                pwm_right=pwm_right,
                profile=profile,
                connected=client.is_connected if client else False,
                endpoint=endpoint_label,
                notice_text=active_notice,
            )

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), ord("Q"), 27):  # Q o ESC
                break
            elif key in (ord("+"), ord("=")):
                profile.adjust_drive_speed(+5)
                show_notice(f"Velocidad recta: F={profile.forward_pwm} B={profile.backward_pwm}")
            elif key in (ord("-"), ord("_")):
                profile.adjust_drive_speed(-5)
                show_notice(f"Velocidad recta: F={profile.forward_pwm} B={profile.backward_pwm}")
            elif key == ord("."):
                profile.adjust_turn_speed(+5)
                show_notice(f"Velocidad giro: L={profile.left_turn_pwm} R={profile.right_turn_pwm}")
            elif key == ord(","):
                profile.adjust_turn_speed(-5)
                show_notice(f"Velocidad giro: L={profile.left_turn_pwm} R={profile.right_turn_pwm}")
            elif key == ord("["):
                profile.adjust_trim(-3)
                show_notice(f"Trim ajustado: {profile.trim_balance:+d} (empuja hacia derecha)")
            elif key == ord("]"):
                profile.adjust_trim(+3)
                show_notice(f"Trim ajustado: {profile.trim_balance:+d} (empuja hacia izquierda)")
            elif key in (ord("p"), ord("P")):
                controller.filter.precision_mode = not controller.filter.precision_mode
                mode_name = "PRECISION" if controller.filter.precision_mode else "NORMAL"
                show_notice(f"Modo cambiado a {mode_name}")
            elif key in (ord("g"), ord("G")):
                profile.save(CALIBRATION_PATH)
                show_notice(f"Calibracion guardada en {CALIBRATION_PATH.name}")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        controller.close()
        if client is not None:
            client.stop()
        print("[INFO] LawamyRacing finalizado de forma segura (motores detenidos).")


if __name__ == "__main__":
    main()
